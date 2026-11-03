import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import router as api_router
from app.broker import broker
from app.config import get_settings
from app.database import engine, get_db
from app.telemetry import close_redis
from app.websockets import router as ws_router
from app.worker import consume, log

settings = get_settings()
# uvicorn configures this logger, so its messages reach the Render log stream.
logger = logging.getLogger("uvicorn.error")

# Render allows 30s from SIGTERM to SIGKILL; this leaves room for the rest of
# shutdown. Executions still running after it are redelivered and re-run.
CONSUMER_DRAIN_SECONDS = 20


async def wait_until_started(consumer: asyncio.Task[None], started: asyncio.Event) -> None:
    """Return once the consumer is registered; raise if it fails first.

    Failing startup beats serving an API that queues executions nobody runs.
    """
    waiter = asyncio.create_task(started.wait())
    try:
        await asyncio.wait((consumer, waiter), return_when=asyncio.FIRST_COMPLETED)
    finally:
        waiter.cancel()
    if consumer.done():
        consumer.result()  # re-raises why it stopped
        raise RuntimeError("task consumer exited during startup")


async def stop_consumer(consumer: asyncio.Task[None], stop: asyncio.Event) -> None:
    """Let in-flight messages finish, cancelling the consumer past the deadline."""
    stop.set()
    if consumer.done():  # it failed to start, and startup already raised why
        return
    try:
        await asyncio.wait_for(consumer, timeout=CONSUMER_DRAIN_SECONDS)
    except TimeoutError:
        pass  # wait_for cancelled it; consume() logs the messages it abandoned
    except Exception as exc:
        log(f"consumer shutdown failed: {exc!r}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # A preflight from any other origin gets 400 "Disallowed CORS origin"; the
    # log shows what the deployed env var actually parsed to.
    logger.info("CORS allowed origins: %s", settings.cors_origins)
    await broker.connect()
    # Modular monolith: the task consumer shares this process and event loop
    # with the web server, so one container runs everything.
    stop, started = asyncio.Event(), asyncio.Event()
    consumer = asyncio.create_task(consume(stop, started), name="task-consumer")
    try:
        await wait_until_started(consumer, started)
        yield
    finally:
        await stop_consumer(consumer, stop)
        await broker.close()
        await close_redis()
        await engine.dispose()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # The frontend authenticates with an Authorization: Bearer header, which
    # makes every API call a preflighted request; "*" allows that header.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(ws_router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok"}


@app.get("/health/db", tags=["meta"])
async def health_db(db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, str]:
    """Readiness: the database is reachable through the pooler."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ok"}


@app.get("/health/broker", tags=["meta"])
async def health_broker() -> dict[str, str]:
    """Readiness: RabbitMQ is reachable over the pooled connection."""
    try:
        ok = await asyncio.wait_for(broker.ping(), timeout=5)
    except Exception:
        ok = False
    if not ok:
        raise HTTPException(status_code=503, detail="broker unavailable")
    return {"status": "ok"}
