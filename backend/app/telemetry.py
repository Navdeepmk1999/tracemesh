"""Live execution traces over Redis Pub/Sub.

Each execution has its own channel, trace:{execution_id}. Pub/Sub is
fire-and-forget: only clients subscribed at publish time receive an event,
and nothing is stored. The executions table remains the durable record.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis
from pydantic_core import to_json

from app.config import get_settings

TRACE_CHANNEL_PREFIX = "trace:"

_client: redis.Redis | None = None


def trace_channel(execution_id: uuid.UUID | str) -> str:
    return f"{TRACE_CHANNEL_PREFIX}{execution_id}"


def get_redis() -> redis.Redis:
    """Shared client; its connection pool is created lazily on first use."""
    global _client
    if _client is None:
        _client = redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            # Upstash drops idle connections; ping before reusing a stale one.
            health_check_interval=30,
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def publish_trace(execution_id: uuid.UUID | str, event_data: dict[str, Any]) -> int:
    """Publish one JSON trace event to trace:{execution_id}.

    Adds execution_id and a UTC timestamp to the event. Returns how many
    subscribers received it (0 is normal when nobody is watching).
    """
    message = {
        "execution_id": str(execution_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **event_data,
    }
    return await get_redis().publish(trace_channel(execution_id), to_json(message))
