import asyncio
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

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await broker.connect()
    try:
        yield
    finally:
        await broker.close()
        await engine.dispose()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


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
