"""Data-access layer. Plain SQL over the async pool, returning dict rows.

Kept deliberately thin — the assignment evaluates infra, not business logic.
"""
from psycopg.rows import dict_row

from app import db
from app.models import DeviceCreate, DeviceUpdate

_COLS = "id, name, type, status, created_at, updated_at"


async def list_devices() -> list[dict]:
    async with db.pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(f"SELECT {_COLS} FROM devices ORDER BY id")
        return await cur.fetchall()


async def get_device(device_id: int) -> dict | None:
    async with db.pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            f"SELECT {_COLS} FROM devices WHERE id = %s", (device_id,)
        )
        return await cur.fetchone()


async def create_device(data: DeviceCreate) -> dict:
    async with db.pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            f"""INSERT INTO devices (name, type, status)
                VALUES (%s, %s, %s)
                RETURNING {_COLS}""",
            (data.name, data.type, data.status.value),
        )
        return await cur.fetchone()


async def update_device(device_id: int, data: DeviceUpdate) -> dict | None:
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        return await get_device(device_id)

    sets, values = [], []
    for key, value in fields.items():
        sets.append(f"{key} = %s")
        values.append(value.value if hasattr(value, "value") else value)
    values.append(device_id)

    async with db.pool.connection() as conn:
        conn.row_factory = dict_row
        cur = await conn.execute(
            f"""UPDATE devices SET {", ".join(sets)}, updated_at = now()
                WHERE id = %s
                RETURNING {_COLS}""",
            tuple(values),
        )
        return await cur.fetchone()


async def delete_device(device_id: int) -> bool:
    async with db.pool.connection() as conn:
        cur = await conn.execute("DELETE FROM devices WHERE id = %s", (device_id,))
        return cur.rowcount > 0
