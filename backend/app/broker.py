from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractQueue, AbstractRobustConnection
from aio_pika.pool import Pool
from pydantic_core import to_json

from app.config import get_settings

TASK_QUEUE = "tracemesh_tasks"
# Messages a worker rejects (malformed, or failed twice) are parked here
# instead of being dropped or redelivered forever.
DEAD_LETTER_QUEUE = f"{TASK_QUEUE}.dead"

CONNECTION_POOL_SIZE = 2
CHANNEL_POOL_SIZE = 10


async def declare_task_queues(channel: AbstractChannel) -> AbstractQueue:
    """Declare the task queue and its dead-letter queue; returns the task queue.

    Producer and worker both call this so the queue exists whichever starts
    first. The arguments must stay identical everywhere: RabbitMQ refuses to
    redeclare an existing queue with different ones.
    """
    await channel.declare_queue(DEAD_LETTER_QUEUE, durable=True)
    return await channel.declare_queue(
        TASK_QUEUE,
        durable=True,
        arguments={
            # Dead-letter through the default exchange, straight to the DLQ.
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": DEAD_LETTER_QUEUE,
        },
    )


class Broker:
    """Pooled RabbitMQ connections and channels for the API process."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._connection_pool: Pool[AbstractRobustConnection] | None = None
        self._channel_pool: Pool[AbstractChannel] | None = None

    async def _get_connection(self) -> AbstractRobustConnection:
        # Robust connections reconnect and restore channels after network drops.
        return await aio_pika.connect_robust(self._url)

    async def _get_channel(self) -> AbstractChannel:
        assert self._connection_pool is not None
        async with self._connection_pool.acquire() as connection:
            # Publisher confirms (on by default) make publish() wait for the
            # broker to take responsibility for the message; on_return_raises
            # turns an unroutable message into an error instead of a silent drop.
            return await connection.channel(on_return_raises=True)

    async def connect(self) -> None:
        if self._channel_pool is not None:
            return
        self._connection_pool = Pool(self._get_connection, max_size=CONNECTION_POOL_SIZE)
        self._channel_pool = Pool(self._get_channel, max_size=CHANNEL_POOL_SIZE)
        try:
            # Opens the first connection now, so a bad URL fails at startup.
            async with self._channel_pool.acquire() as channel:
                await declare_task_queues(channel)
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        if self._channel_pool is not None:
            await self._channel_pool.close()
        if self._connection_pool is not None:
            await self._connection_pool.close()
        self._channel_pool = None
        self._connection_pool = None

    async def ping(self) -> bool:
        """True if a pooled channel is open (reconnecting counts as down)."""
        if self._channel_pool is None:
            return False
        async with self._channel_pool.acquire() as channel:
            return not channel.is_closed

    async def publish_task(self, payload: dict[str, Any]) -> str:
        """Serialize payload as JSON and publish it to the task queue.

        Returns the message id. Raises if the broker does not confirm the
        message, so a successful return means it is stored in the queue.
        """
        if self._channel_pool is None:
            raise RuntimeError("Broker is not connected; call connect() first")

        message_id = uuid4().hex
        message = aio_pika.Message(
            # pydantic_core handles UUIDs, datetimes and enums, and raises on
            # anything it can't encode rather than stringifying it.
            body=to_json(payload),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=message_id,
            timestamp=datetime.now(timezone.utc),
        )
        async with self._channel_pool.acquire() as channel:
            await channel.default_exchange.publish(message, routing_key=TASK_QUEUE)
        return message_id


broker = Broker(get_settings().rabbitmq_url)


async def publish_task(payload: dict[str, Any]) -> str:
    return await broker.publish_task(payload)
