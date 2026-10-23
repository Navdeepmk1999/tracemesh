"""Shared fixtures for the TraceMesh backend suite.

Infrastructure:
- PostgreSQL is real (JSONB, native enums, composite FKs and UPDATE ...
  RETURNING are part of what is under test). Point TEST_DATABASE_URL at a
  disposable database; the schema is built with the real Alembic migrations.
- RabbitMQ is mocked: the API's publish_task is replaced by a recorder.
- Redis is faked in-process with fakeredis (real Pub/Sub semantics).

Run from backend/:
    TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/tracemesh_test \\
        tracemesh-env/bin/pytest
"""

import os
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import jwt
import pytest
from sqlalchemy.engine import make_url

# --- Environment: must run before anything imports `app` ----------------------
#
# app.config reads backend/.env, which points at real Supabase, CloudAMQP and
# Upstash. Process env vars take precedence over .env, so every connection
# setting is overridden here, and the DB guard below refuses anything that
# doesn't look disposable: tests TRUNCATE tables after each case.

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/tracemesh_test"
)
_db = make_url(TEST_DATABASE_URL)
if _db.host not in {"localhost", "127.0.0.1"} or "test" not in (_db.database or ""):
    raise RuntimeError(
        f"Refusing to run tests against {_db.render_as_string(hide_password=True)}: the suite "
        "truncates tables, so TEST_DATABASE_URL must be a local database whose name contains 'test'."
    )

JWT_SECRET = "test-jwt-secret-that-is-at-least-32-bytes-long"
SUPABASE_URL = "https://test-project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"

os.environ.update(
    {
        "DATABASE_URL": TEST_DATABASE_URL,
        "MIGRATION_DATABASE_URL": TEST_DATABASE_URL,
        # Never contacted: the broker and Redis are mocked. .invalid can't resolve.
        "RABBITMQ_URL": "amqp://guest:guest@rabbitmq.invalid:5672/",
        "REDIS_URL": "redis://redis.invalid:6379/0",
        "SUPABASE_JWT_SECRET": JWT_SECRET,
        "SUPABASE_URL": SUPABASE_URL,
        "CORS_ORIGINS": '["http://testserver"]',
    }
)

import fakeredis  # noqa: E402
import httpx  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx_ws import AsyncWebSocketSession, aconnect_ws  # noqa: E402
from httpx_ws.transport import ASGIWebSocketTransport  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import telemetry  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent


# --- Database ------------------------------------------------------------------


def _alembic(*steps: tuple[str, str]) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    for action, revision in steps:
        getattr(command, action)(config, revision)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Build the schema from the real migrations, down then up, so every run
    also proves the migration chain applies and reverses cleanly."""
    # alembic's env.py calls asyncio.run(); keep it off any running loop.
    with ThreadPoolExecutor(1) as pool:
        pool.submit(_alembic, ("downgrade", "base"), ("upgrade", "head")).result()


@pytest.fixture(autouse=True)
async def clean_tables() -> AsyncIterator[None]:
    yield
    async with engine.begin() as conn:
        # workflows cascades to nodes, edges, executions and node_runs.
        await conn.execute(text("TRUNCATE workflows CASCADE"))


@pytest.fixture
def db_session():
    """Factory for short-lived sessions (same as the app's), for arranging and
    asserting on rows directly."""
    return SessionLocal


# --- Broker and Redis -----------------------------------------------------------


@pytest.fixture(autouse=True)
def published(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replaces RabbitMQ publishing in the API; returns the payloads 'sent'."""
    sent: list[dict[str, Any]] = []

    async def fake_publish(payload: dict[str, Any]) -> str:
        sent.append(payload)
        return uuid.uuid4().hex

    monkeypatch.setattr("app.api.publish_task", AsyncMock(side_effect=fake_publish))
    return sent


@pytest.fixture(autouse=True)
async def fake_redis(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[fakeredis.FakeAsyncRedis]:
    """In-process Redis shared by the API (WebSocket) and the worker (traces)."""
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(telemetry, "_client", client)
    yield client
    await client.aclose()


# --- HTTP / WebSocket client -----------------------------------------------------


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    # In-process ASGI client. Lifespan doesn't run, so no broker connection
    # is attempted.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


@asynccontextmanager
async def ws_connect(path: str) -> AsyncIterator[AsyncWebSocketSession]:
    """Open a WebSocket to the app in-process.

    A context manager rather than a fixture: the transport runs an anyio task
    group, which must be entered and exited in the same task, and
    pytest-asyncio tears async fixtures down in a different one.
    """
    async with httpx.AsyncClient(transport=ASGIWebSocketTransport(app=app), base_url="http://testserver") as c:
        async with aconnect_ws(f"http://testserver{path}", c, keepalive_ping_interval_seconds=None) as ws:
            yield ws


# --- Auth --------------------------------------------------------------------------


def make_token(sub: str | uuid.UUID | None = None, *, expires_in: int = 3600, **claims: Any) -> str:
    """A Supabase-style HS256 access token. Pass a claim as None to omit it."""
    payload: dict[str, Any] = {
        "sub": str(sub) if sub is not None else None,
        "aud": "authenticated",
        "role": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + expires_in,
        **claims,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


class User:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.token = make_token(self.id)
        self.headers = {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
def alice() -> User:
    return User()


@pytest.fixture
def bob() -> User:
    return User()


# --- Builders --------------------------------------------------------------------


@pytest.fixture
def build_workflow(client: httpx.AsyncClient) -> Callable[..., Any]:
    """Create a workflow through the API.

    nodes: list of node_type strings (or (node_type, config) pairs).
    edges: list of (source_index, target_index) into `nodes`.
    Returns (workflow, [node, ...], [edge, ...]) as API JSON.
    """

    async def build(
        user: User,
        nodes: list[str | tuple[str, dict[str, Any]]] = (),
        edges: list[tuple[int, int]] = (),
        name: str = "test workflow",
    ):
        r = await client.post("/workflows", json={"name": name}, headers=user.headers)
        assert r.status_code == 201, r.text
        workflow = r.json()
        created_nodes = []
        for spec in nodes:
            node_type, config = (spec, {}) if isinstance(spec, str) else spec
            r = await client.post(
                f"/workflows/{workflow['id']}/nodes",
                json={"node_type": node_type, "config_json": config},
                headers=user.headers,
            )
            assert r.status_code == 201, r.text
            created_nodes.append(r.json())
        created_edges = []
        for s, t in edges:
            r = await client.post(
                f"/workflows/{workflow['id']}/edges",
                json={"source_node_id": created_nodes[s]["id"], "target_node_id": created_nodes[t]["id"]},
                headers=user.headers,
            )
            assert r.status_code == 201, r.text
            created_edges.append(r.json())
        return workflow, created_nodes, created_edges

    return build
