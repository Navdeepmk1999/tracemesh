"""app/broker.py with aio-pika mocked out: message shape and queue topology."""

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import aio_pika
import pytest

from app.broker import DEAD_LETTER_QUEUE, TASK_QUEUE, Broker, declare_task_queues


class FakePool:
    def __init__(self, channel):
        self.channel = channel

    @asynccontextmanager
    async def acquire(self):
        yield self.channel


@pytest.fixture
def channel():
    ch = MagicMock()
    ch.default_exchange.publish = AsyncMock()
    ch.declare_queue = AsyncMock()
    ch.is_closed = False
    return ch


@pytest.fixture
def connected_broker(channel):
    broker = Broker("amqp://unused")
    broker._channel_pool = FakePool(channel)
    return broker


async def test_publish_task_sends_a_persistent_json_message(connected_broker, channel):
    workflow_id = uuid.uuid4()
    message_id = await connected_broker.publish_task({"workflow_id": workflow_id, "n": 1})

    channel.default_exchange.publish.assert_awaited_once()
    message, = channel.default_exchange.publish.await_args.args
    assert channel.default_exchange.publish.await_args.kwargs == {"routing_key": TASK_QUEUE}
    assert isinstance(message, aio_pika.Message)
    # UUIDs serialize as strings rather than failing.
    assert json.loads(message.body) == {"workflow_id": str(workflow_id), "n": 1}
    assert message.content_type == "application/json"
    assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT  # survives a broker restart
    assert message.message_id == message_id
    assert abs((datetime.now(timezone.utc) - message.timestamp).total_seconds()) < 5


async def test_unserializable_payload_raises_instead_of_publishing(connected_broker, channel):
    with pytest.raises(Exception):
        await connected_broker.publish_task({"x": object()})
    channel.default_exchange.publish.assert_not_awaited()


async def test_publish_before_connect_raises():
    with pytest.raises(RuntimeError, match="not connected"):
        await Broker("amqp://unused").publish_task({})


async def test_broker_errors_propagate_to_the_caller(connected_broker, channel):
    # e.g. no publisher confirm; the API turns this into a FAILED execution.
    channel.default_exchange.publish.side_effect = aio_pika.exceptions.DeliveryError(None, None)
    with pytest.raises(aio_pika.exceptions.DeliveryError):
        await connected_broker.publish_task({"a": 1})


async def test_task_queue_dead_letters_to_its_dlq(channel):
    await declare_task_queues(channel)
    calls = {c.args[0]: c.kwargs for c in channel.declare_queue.await_args_list}
    assert calls[DEAD_LETTER_QUEUE] == {"durable": True}
    assert calls[TASK_QUEUE] == {
        "durable": True,
        "arguments": {"x-dead-letter-exchange": "", "x-dead-letter-routing-key": DEAD_LETTER_QUEUE},
    }


async def test_ping(connected_broker, channel):
    assert await connected_broker.ping() is True
    channel.is_closed = True
    assert await connected_broker.ping() is False
    assert await Broker("amqp://unused").ping() is False
