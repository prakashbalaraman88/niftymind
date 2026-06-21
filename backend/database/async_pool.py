"""Async database connection pool manager using asyncpg.

Provides a singleton async connection pool with health checks,
connection recycling, and graceful shutdown. Replaces the
synchronous psycopg2 ThreadedConnectionPool used throughout the
legacy codebase.

Usage::

    from database.async_pool import get_db_pool

    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM trades WHERE id = $1", trade_id)
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Any, AsyncGenerator

import asyncpg

logger = logging.getLogger("niftymind.async_pool")

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Default pool sizing (override via env vars)
# ---------------------------------------------------------------------------
DEFAULT_POOL_MIN: int = int(os.getenv("DB_POOL_MIN", "5"))
DEFAULT_POOL_MAX: int = int(os.getenv("DB_POOL_MAX", "20"))
DEFAULT_POOL_MAX_INACTIVE_TIME: int = int(os.getenv("DB_POOL_MAX_INACTIVE_TIME", "300"))  # 5 min
DEFAULT_POOL_MAX_QUERIES: int = int(os.getenv("DB_POOL_MAX_QUERIES", "1000"))
DB_COMMAND_TIMEOUT: int = int(os.getenv("DB_COMMAND_TIMEOUT", "30"))


class DatabasePool:
    """Singleton asyncpg connection pool manager.

    Features:
        - Lazy initialisation (first call to ``connect()``)
        - Connection health check via ``ping()``
        - Connection recycling after max queries or idle time
        - Graceful ``close()`` that drains pending work
        - Context-manager helper for safe acquisition
    """

    _instance: DatabasePool | None = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> DatabasePool:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        dsn: str | None = None,
        min_size: int = DEFAULT_POOL_MIN,
        max_size: int = DEFAULT_POOL_MAX,
        max_inactive_time: int = DEFAULT_POOL_MAX_INACTIVE_TIME,
        max_queries: int = DEFAULT_POOL_MAX_QUERIES,
    ) -> None:
        if self._initialized:
            return
        self._dsn = dsn or os.getenv("DATABASE_URL", "")
        self._min_size = min_size
        self._max_size = max_size
        self._max_inactive_time = max_inactive_time
        self._max_queries = max_queries
        self._pool: asyncpg.Pool | None = None
        self._health_task: asyncio.Task | None = None
        self._initialized = True
        self._connect_count: int = 0
        self._fail_count: int = 0
        self._fail_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Create the asyncpg pool. Idempotent — safe to call multiple times."""
        if self._pool is not None and not self._pool._closed:
            logger.debug("Pool already connected")
            return
        if not self._dsn:
            logger.error("DATABASE_URL not set — cannot create pool")
            return

        try:
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
                max_inactive_connection_lifetime=self._max_inactive_time,
                max_queries=self._max_queries,
                command_timeout=DB_COMMAND_TIMEOUT,
                # Connection is established lazily by default; we want
                # to validate the DSN immediately, so open *one* conn.
                loop=None,
            )
            self._connect_count = 0
            logger.info(
                "Asyncpg pool created  (min=%d, max=%d, max_idle=%ds, max_queries=%d)",
                self._min_size,
                self._max_size,
                self._max_inactive_time,
                self._max_queries,
            )
            # Start background health-check loop
            self._health_task = asyncio.create_task(
                self._health_check_loop(), name="db-pool-health"
            )
        except Exception as exc:
            self._pool = None
            logger.error("Failed to create asyncpg pool: %s", exc)
            raise

    async def close(self) -> None:
        """Graceful shutdown — cancels health task and closes the pool."""
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
        if self._pool and not self._pool._closed:
            await self._pool.close()
            logger.info("Asyncpg pool closed")
        self._pool = None
        DatabasePool._instance = None
        self._initialized = False

    # ------------------------------------------------------------------
    # Connection acquisition
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """Acquire a connection from the pool with automatic release."""
        if self._pool is None or self._pool._closed:
            await self.connect()
        if self._pool is None:
            raise RuntimeError("Database pool is not available")
        async with self._pool.acquire() as conn:
            self._connect_count += 1
            try:
                yield conn
            finally:
                pass  # pool.release() handled by context manager

    # ------------------------------------------------------------------
    # Convenience helpers (used by routes & db_logger)
    # ------------------------------------------------------------------

    async def fetch(
        self, sql: str, *args: Any
    ) -> list[asyncpg.Record]:
        """Execute a SELECT query and return all rows."""
        async with self.acquire() as conn:
            return await conn.fetch(sql, *args)

    async def fetchrow(
        self, sql: str, *args: Any
    ) -> asyncpg.Record | None:
        """Execute a SELECT query and return at most one row."""
        async with self.acquire() as conn:
            return await conn.fetchrow(sql, *args)

    async def fetchval(
        self, sql: str, *args: Any
    ) -> Any | None:
        """Execute a SELECT query and return a single scalar value."""
        async with self.acquire() as conn:
            return await conn.fetchval(sql, *args)

    async def execute(self, sql: str, *args: Any) -> str:
        """Execute an INSERT / UPDATE / DELETE and return the status."""
        async with self.acquire() as conn:
            return await conn.execute(sql, *args)

    async def executemany(self, sql: str, args: list[tuple]) -> str:
        """Execute a batch operation."""
        async with self.acquire() as conn:
            return await conn.executemany(sql, args)

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    async def ping(self) -> bool:
        """Return *True* if the pool can serve a connection."""
        if self._pool is None or self._pool._closed:
            return False
        try:
            async with self.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
                return result == 1
        except Exception as exc:
            logger.warning("DB health-check ping failed: %s", exc)
            return False

    async def _health_check_loop(self) -> None:
        """Background task: ping the DB every 30 s and log pool stats."""
        while True:
            try:
                await asyncio.sleep(30)
                if self._pool is None or self._pool._closed:
                    logger.warning("Pool closed during health check — reconnecting")
                    await self.connect()
                    continue
                healthy = await self.ping()
                size = self._pool.get_size()
                free = self._pool.get_free_size()
                pending = self._pool._queue.qsize() if hasattr(self._pool._queue, "qsize") else "?"
                logger.debug(
                    "DB pool health=%s  size=%d  free=%d  pending_acquires=%s",
                    healthy, size, free, pending,
                )
                if not healthy:
                    logger.error("DB health-check FAILED — marking connections stale")
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("DB health-check loop error: %s", exc)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return pool statistics for the /healthz endpoint."""
        if self._pool is None:
            return {"status": "not_initialized"}
        return {
            "status": "closed" if self._pool._closed else "open",
            "pool_size": self._pool.get_size(),
            "free_connections": self._pool.get_free_size(),
            "min_size": self._min_size,
            "max_size": self._max_size,
            "total_acquisitions": self._connect_count,
            "total_failures": self._fail_count,
        }


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

_db_pool: DatabasePool | None = None
_db_pool_lock: asyncio.Lock = asyncio.Lock()


async def get_db_pool() -> DatabasePool:
    """Return the singleton ``DatabasePool``, creating it on first call."""
    global _db_pool
    if _db_pool is not None:
        return _db_pool
    async with _db_pool_lock:
        if _db_pool is not None:
            return _db_pool
        _db_pool = DatabasePool()
        await _db_pool.connect()
        return _db_pool


async def close_db_pool() -> None:
    """Close the global pool. Safe to call multiple times."""
    global _db_pool
    if _db_pool is not None:
        await _db_pool.close()
        _db_pool = None


async def db_health_check() -> bool:
    """Quick health check usable by the FastAPI /healthz endpoint."""
    try:
        pool = await get_db_pool()
        return await pool.ping()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JSON helpers (asyncpg does not auto-serialise dicts / lists)
# ---------------------------------------------------------------------------

def dumps_json(obj: Any) -> str | None:
    """Serialise *obj* to a JSON string, returning ``None`` for *None*."""
    if obj is None:
        return None
    import json
    return json.dumps(obj, default=str)
