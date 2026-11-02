"""The API's lifespan runs the task consumer in-process (app/main.py).

aio-pika is faked: the fake queue captures the consumer callback, and tests
call it the way aio-pika does, one task per delivery.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import main, worker


class FakeConnection:
    def __init__(self, channel):
        self._channel = channel
        self.closed = False

    async def channel(self):
        return self._channel

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True


@pytest.fixture
def queue():
    q = MagicMock()
    q.callback = None

    async def consume(callback):
        q.callback = callback
        return "ctag"

    q.consume = AsyncMock(side_effect=consume)
    q.cancel = AsyncMock()
    return q


@pytest.fixture
def connection(queue, monkeypatch):
    channel = MagicMock()
    channel.set_qos = AsyncMock()
    channel.declare_queue = AsyncMock(return_value=queue)
    conn = FakeConnection(channel)
    monkeypatch.setattr(worker.aio_pika, "connect_robust", AsyncMock(return_value=conn))
    return conn


@pytest.fixture(autouse=True)
def infrastructure(monkeypatch):
    """Stub out what the lifespan opens and closes besides the consumer."""
    monkeypatch.setattr(main.broker, "connect", AsyncMock())
    monkeypatch.setattr(main.broker, "close", AsyncMock())
    monkeypatch.setattr(main, "close_redis", AsyncMock())
    monkeypatch.setattr(main, "engine", MagicMock(dispose=AsyncMock()))


def deliver(queue, message="msg"):
    return asyncio.create_task(queue.callback(message))


async def test_consumer_is_registered_before_the_app_serves(queue, connection):
    async with main.lifespan(main.app):
        queue.consume.assert_awaited_once()
    assert connection.closed
    main.broker.close.assert_awaited_once()


async def test_shutdown_drains_in_flight_messages(queue, connection, monkeypatch):
    release = asyncio.Event()
    handled = []

    async def handle(message):
        await release.wait()
        handled.append(message)

    monkeypatch.setattr(worker, "handle_message", handle)

    async with main.lifespan(main.app):
        delivery = deliver(queue)
        await asyncio.sleep(0)
        # Finish the message only after shutdown has begun.
        asyncio.get_running_loop().call_later(0.05, release.set)

    queue.cancel.assert_awaited_once_with("ctag")
    assert handled == ["msg"]
    assert delivery.done() and not delivery.cancelled()


async def test_drain_past_the_deadline_cancels_the_message(queue, connection, monkeypatch):
    monkeypatch.setattr(main, "CONSUMER_DRAIN_SECONDS", 0.05)
    monkeypatch.setattr(worker, "handle_message", lambda message: asyncio.Event().wait())

    async with main.lifespan(main.app):
        delivery = deliver(queue)
        await asyncio.sleep(0)

    await asyncio.sleep(0)  # let the cancellation land
    # Never acked, so RabbitMQ will redeliver it once the connection closes.
    assert delivery.cancelled()
    assert connection.closed


async def test_startup_fails_if_the_consumer_cannot_connect(monkeypatch):
    monkeypatch.setattr(worker.aio_pika, "connect_robust", AsyncMock(side_effect=ConnectionError("refused")))

    with pytest.raises(ConnectionError, match="refused"):
        async with main.lifespan(main.app):
            pytest.fail("the app must not serve without a consumer")
    main.broker.close.assert_awaited_once()
    main.close_redis.assert_awaited_once()
