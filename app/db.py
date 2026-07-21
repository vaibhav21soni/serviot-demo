import logging
import pathlib

from psycopg_pool import AsyncConnectionPool

from app.config import get_settings

logger = logging.getLogger("serviot.db")

# Module-level pool; opened once on startup, closed on shutdown.
pool: AsyncConnectionPool | None = None

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"


async def open_pool() -> AsyncConnectionPool:
    """Create and open the global connection pool."""
    global pool
    settings = get_settings()
    pool = AsyncConnectionPool(
        conninfo=settings.dsn,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        open=False,
    )
    await pool.open(wait=True, timeout=10)
    logger.info("db pool opened (min=%s max=%s)", settings.db_pool_min, settings.db_pool_max)
    return pool


async def close_pool() -> None:
    global pool
    if pool is not None:
        await pool.close()
        pool = None
        logger.info("db pool closed")


async def run_migrations() -> None:
    """Apply every .sql file in migrations/ in filename order.

    Migrations are written idempotently (IF NOT EXISTS), so running them on
    every startup is safe and keeps dev parity without a separate migrate step.
    A production pipeline runs the same SQL as a dedicated pre-deploy job.
    """
    assert pool is not None, "pool not opened"
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    async with pool.connection() as conn:
        for f in files:
            sql = f.read_text()
            await conn.execute(sql)
            logger.info("applied migration %s", f.name)


async def check_db() -> bool:
    """Return True if a trivial query succeeds against the pool."""
    if pool is None:
        return False
    try:
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT 1")
            row = await cur.fetchone()
            return row is not None and row[0] == 1
    except Exception as exc:  # noqa: BLE001 - health check must never raise
        logger.warning("db health check failed: %s", exc)
        return False
