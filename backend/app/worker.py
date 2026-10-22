"""Standalone task consumer.

Run from backend/:  tracemesh-env/bin/python -m app.worker

Delivery is at-least-once: a message is acked only after processing finishes,
so if the worker dies mid-task the broker redelivers it to another consumer.
"""

import asyncio
import json
import signal
from datetime import datetime, timezone

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from app.broker import TASK_QUEUE, declare_task_queues
from app.config import get_settings

SIMULATED_WORK_SECONDS = 2


def log(text: str) -> None:
    print(f"[worker {datetime.now(timezone.utc):%H:%M:%S}] {text}", flush=True)


async def handle_message(message: AbstractIncomingMessage) -> None:
    try:
        payload = json.loads(message.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        # Retrying can't fix a malformed body: dead-letter it immediately.
        log(f"rejected {message.message_id}: body is not valid JSON")
        await message.reject(requeue=False)
        return

    try:
        log(f"processing {message.message_id} (redelivered={message.redelivered})")
        await asyncio.sleep(SIMULATED_WORK_SECONDS)
        result = {"message_id": message.message_id, "status": "COMPLETED", "payload": payload}
    except Exception as exc:
        # Retry once on a fresh delivery; a second failure goes to the DLQ.
        log(f"failed {message.message_id}: {exc!r}")
        await message.nack(requeue=not message.redelivered)
        return

    await message.ack()
    log(f"acked {json.dumps(result)}")


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
    log("stopped")


if __name__ == "__main__":
    asyncio.run(main())
