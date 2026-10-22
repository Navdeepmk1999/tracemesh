"""Standalone task consumer.

Run from backend/:  tracemesh-env/bin/python -m app.worker

Delivery is at-least-once: a message is acked only after processing finishes,
so if the worker dies mid-task the broker redelivers it to another consumer.
The executions row, not the message, is the source of truth for whether work
still needs doing, which makes redeliveries safe.

Progress is published to Redis (trace:{execution_id}) after each DB write:
execution.started, node.started, node.completed | node.failed, then
execution.completed | execution.failed.
"""

import asyncio
import json
import signal
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import aio_pika
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy import update

from app.broker import TASK_QUEUE, declare_task_queues
from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import Execution, ExecutionStatus
from app.telemetry import close_redis, publish_trace

SIMULATED_SECONDS_PER_NODE = 1
TRACE_TIMEOUT_SECONDS = 2
MAX_ERROR_LENGTH = 4000

# A RUNNING row on delivery means a previous worker died before acking (the
# broker gives a message to one consumer at a time), so it is safe to re-run.
CLAIMABLE = (ExecutionStatus.PENDING, ExecutionStatus.RUNNING)


def log(text: str) -> None:
    print(f"[worker {datetime.now(timezone.utc):%H:%M:%S}] {text}", flush=True)


class MalformedTask(ValueError):
    pass


class NodeFailed(Exception):
    """A node raised; str() is the message stored in executions.error_message."""


def describe(exc: BaseException) -> str:
    # str() alone is often empty or ambiguous, e.g. KeyError('x') -> "'x'".
    text = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    return text[:MAX_ERROR_LENGTH]


def elapsed_ms(start: float) -> int:
    return round((time.monotonic() - start) * 1000)


class Tracer:
    """Best-effort trace publisher for one execution.

    Telemetry must never fail or stall an execution, so publish errors are
    logged and dropped. `seq` lets clients detect gaps and reorder events.
    """

    def __init__(self, execution_id: uuid.UUID) -> None:
        self.execution_id = execution_id
        self.seq = 0

    async def emit(self, event: str, **data: Any) -> None:
        self.seq += 1
        try:
            await asyncio.wait_for(
                publish_trace(self.execution_id, {"event": event, "seq": self.seq, **data}),
                timeout=TRACE_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            log(f"  trace dropped ({event}, seq={self.seq}): {exc!r}")


def parse_task(body: bytes) -> tuple[uuid.UUID, list[dict[str, Any]], list[str]]:
    try:
        payload = json.loads(body)
        execution_id = uuid.UUID(payload["execution_id"])
        nodes = {n["id"]: n for n in payload["nodes"]}
        order = [str(i) for i in payload["order"]]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise MalformedTask(f"{type(exc).__name__}: {exc}") from None
    if set(order) != set(nodes):
        raise MalformedTask("order does not match nodes")
    return execution_id, [nodes[i] for i in order], order


async def set_status(
    execution_id: uuid.UUID,
    new_status: ExecutionStatus,
    *,
    only_from: tuple[ExecutionStatus, ...],
    **values: Any,
) -> bool:
    """Conditionally move an execution to new_status; True if a row changed.

    The WHERE on the current status makes each transition atomic, so a
    duplicate delivery can never overwrite a finished execution. Each call is
    its own short transaction, which Supavisor's transaction mode needs.
    """
    async with SessionLocal() as session, session.begin():
        result = await session.execute(
            update(Execution)
            .where(Execution.id == execution_id, Execution.status.in_(only_from))
            .values(status=new_status, **values)
            .returning(Execution.id)
        )
        return result.scalar_one_or_none() is not None


async def run_node(node: dict[str, Any]) -> None:
    """Simulated agent work. Set config.simulate_failure to make a node raise."""
    await asyncio.sleep(SIMULATED_SECONDS_PER_NODE)
    failure = (node.get("config") or {}).get("simulate_failure")
    if failure:
        raise RuntimeError(failure if isinstance(failure, str) else "simulated node failure")


async def run_execution(nodes: list[dict[str, Any]], tracer: Tracer) -> None:
    total = len(nodes)
    for i, node in enumerate(nodes, start=1):
        node_info = {"node_id": node.get("id"), "node_type": node.get("node_type"), "index": i, "total": total}
        log(f"  {tracer.execution_id} node {i}/{total} {node_info['node_type']} ({node_info['node_id']})")
        await tracer.emit("node.started", **node_info)
        start = time.monotonic()
        try:
            await run_node(node)
        except Exception as exc:
            error = f"node {node_info['node_id']} ({node_info['node_type']}) failed: {describe(exc)}"
            await tracer.emit("node.failed", **node_info, duration_ms=elapsed_ms(start), error=error)
            raise NodeFailed(error[:MAX_ERROR_LENGTH]) from exc
        await tracer.emit("node.completed", **node_info, duration_ms=elapsed_ms(start))


async def handle_message(message: AbstractIncomingMessage) -> None:
    try:
        execution_id, nodes, order = parse_task(message.body)
    except MalformedTask as exc:
        # Retrying can't fix a malformed body: dead-letter it immediately.
        log(f"rejected {message.message_id}: {exc}")
        await message.reject(requeue=False)
        return

    try:
        claimed = await set_status(
            execution_id,
            ExecutionStatus.RUNNING,
            only_from=CLAIMABLE,
            started_at=datetime.now(timezone.utc),
            completed_at=None,
            error_message=None,
        )
        if not claimed:
            # Already COMPLETED/FAILED (duplicate delivery), or the workflow
            # was deleted. Either way there is nothing left to do.
            log(f"skipped {execution_id}: already finished or no longer exists")
            await message.ack()
            return

        log(f"running {execution_id}: {len(nodes)} node(s) (redelivered={message.redelivered})")
        tracer = Tracer(execution_id)
        start = time.monotonic()
        await tracer.emit(
            "execution.started",
            status=ExecutionStatus.RUNNING.value,
            node_count=len(nodes),
            order=order,
            redelivered=message.redelivered,
        )
        try:
            await run_execution(nodes, tracer)
        except Exception as exc:
            error = str(exc) if isinstance(exc, NodeFailed) else describe(exc)
            log(f"failed {execution_id}: {error}")
            await set_status(
                execution_id,
                ExecutionStatus.FAILED,
                only_from=(ExecutionStatus.RUNNING,),
                completed_at=datetime.now(timezone.utc),
                error_message=error,
            )
            await tracer.emit(
                "execution.failed",
                status=ExecutionStatus.FAILED.value,
                duration_ms=elapsed_ms(start),
                error=error,
            )
        else:
            await set_status(
                execution_id,
                ExecutionStatus.COMPLETED,
                only_from=(ExecutionStatus.RUNNING,),
                completed_at=datetime.now(timezone.utc),
            )
            await tracer.emit(
                "execution.completed",
                status=ExecutionStatus.COMPLETED.value,
                duration_ms=elapsed_ms(start),
            )
            log(f"completed {execution_id}")
    except Exception as exc:
        # Infrastructure failure (e.g. the database is unreachable): the status
        # could not be recorded. Retry once on a fresh delivery, then dead-letter.
        log(f"error on {execution_id}: {exc!r}")
        await message.nack(requeue=not message.redelivered)
        return

    await message.ack()


async def main() -> None:
    settings = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    in_flight: set[asyncio.Task[None]] = set()

    async def on_message(message: AbstractIncomingMessage) -> None:
        # Track each handler so shutdown can wait for it to ack.
        task = asyncio.current_task()
        assert task is not None
        in_flight.add(task)
        try:
            await handle_message(message)
        finally:
            in_flight.discard(task)

    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    try:
        async with connection:
            channel = await connection.channel()
            # Without a prefetch limit the broker pushes the whole backlog to the
            # first worker that connects; this caps it so work spreads evenly.
            await channel.set_qos(prefetch_count=settings.worker_prefetch_count)
            queue = await declare_task_queues(channel)

            consumer_tag = await queue.consume(on_message)
            log(f"consuming from {TASK_QUEUE!r} (prefetch={settings.worker_prefetch_count}); Ctrl+C to stop")

            await stop.wait()

            # Stop receiving new messages, then let in-flight ones finish and ack.
            log("shutting down: draining in-flight messages")
            await queue.cancel(consumer_tag)
            if in_flight:
                await asyncio.gather(*in_flight, return_exceptions=True)
    finally:
        await close_redis()
        await engine.dispose()
    log("stopped")


if __name__ == "__main__":
    asyncio.run(main())
