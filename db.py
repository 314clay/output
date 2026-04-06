import json
import os
from datetime import datetime

import asyncpg

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://clayarnold@localhost:5432/output",
)

pool: asyncpg.Pool | None = None


async def init_pool():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)


async def close_pool():
    if pool:
        await pool.close()


async def create_channel(
    channel_id: str, name: str, description: str | None, metadata: dict,
) -> dict:
    row = await pool.fetchrow(
        """INSERT INTO channels (id, name, description, metadata)
           VALUES ($1, $2, $3, $4)
           RETURNING *""",
        channel_id, name, description, json.dumps(metadata),
    )
    return dict(row)


async def get_channel(channel_id: str) -> dict | None:
    row = await pool.fetchrow(
        "SELECT * FROM channels WHERE id = $1", channel_id,
    )
    return dict(row) if row else None


async def list_channels(active_only: bool = True) -> list[dict]:
    sql = """SELECT c.*, COUNT(i.id) AS item_count
             FROM channels c LEFT JOIN items i ON i.channel_id = c.id"""
    conditions = []
    if active_only:
        conditions.append("c.archived_at IS NULL")
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " GROUP BY c.id ORDER BY c.created_at DESC"
    rows = await pool.fetch(sql)
    return [dict(r) for r in rows]


async def archive_channel(channel_id: str) -> dict | None:
    row = await pool.fetchrow(
        """UPDATE channels SET archived_at = NOW(), updated_at = NOW()
           WHERE id = $1 AND archived_at IS NULL
           RETURNING *""",
        channel_id,
    )
    return dict(row) if row else None


async def create_item(
    channel_id: str, format: str, title: str | None, content: dict, pinned: bool = False,
) -> dict:
    row = await pool.fetchrow(
        """INSERT INTO items (channel_id, format, title, content, pinned)
           VALUES ($1, $2, $3, $4, $5)
           RETURNING *""",
        channel_id, format, title, json.dumps(content), pinned,
    )
    return dict(row)


async def get_items(
    channel_id: str, since: datetime | None = None, limit: int = 50,
    format_filter: str | None = None,
) -> list[dict]:
    sql = "SELECT * FROM items WHERE channel_id = $1"
    args: list = [channel_id]
    if since:
        args.append(since)
        sql += f" AND created_at > ${len(args)}"
    if format_filter:
        args.append(format_filter)
        sql += f" AND format = ${len(args)}"
    sql += " ORDER BY created_at DESC"
    args.append(limit)
    sql += f" LIMIT ${len(args)}"
    rows = await pool.fetch(sql, *args)
    return [dict(r) for r in rows]


async def get_item(item_id: int) -> dict | None:
    row = await pool.fetchrow(
        "SELECT * FROM items WHERE id = $1", item_id,
    )
    return dict(row) if row else None


async def delete_item(item_id: int) -> bool:
    result = await pool.execute(
        "DELETE FROM items WHERE id = $1", item_id,
    )
    return result == "DELETE 1"


async def clear_items(channel_id: str) -> int:
    result = await pool.execute(
        "DELETE FROM items WHERE channel_id = $1", channel_id,
    )
    # result is like "DELETE 42"
    return int(result.split()[-1])


async def append_log_lines(channel_id: str, lines: list[str]) -> dict | None:
    row = await pool.fetchrow(
        """UPDATE items
           SET content = jsonb_set(
               content,
               '{lines}',
               (COALESCE(content->'lines', '[]'::jsonb) || $2::jsonb)
           )
           WHERE id = (
               SELECT id FROM items
               WHERE channel_id = $1 AND format = 'log'
               ORDER BY created_at DESC LIMIT 1
           )
           RETURNING *""",
        channel_id, json.dumps(lines),
    )
    return dict(row) if row else None


async def upsert_slot_item(
    channel_id: str, slot_name: str, format: str, title: str | None, content: dict,
) -> dict:
    row = await pool.fetchrow(
        """INSERT INTO items (channel_id, slot_name, format, title, content)
           VALUES ($1, $2, $3, $4, $5)
           ON CONFLICT (channel_id, slot_name) WHERE slot_name IS NOT NULL
           DO UPDATE SET format = $3, title = $4, content = $5, created_at = NOW()
           RETURNING *""",
        channel_id, slot_name, format, title, json.dumps(content),
    )
    return dict(row)


async def get_slot_items(channel_id: str) -> list[dict]:
    rows = await pool.fetch(
        "SELECT * FROM items WHERE channel_id = $1 AND slot_name IS NOT NULL",
        channel_id,
    )
    return [dict(r) for r in rows]


async def append_log_to_slot(channel_id: str, slot_name: str, lines: list[str]) -> dict | None:
    row = await pool.fetchrow(
        """UPDATE items
           SET content = jsonb_set(
               content,
               '{lines}',
               (COALESCE(content->'lines', '[]'::jsonb) || $3::jsonb)
           )
           WHERE channel_id = $1 AND slot_name = $2 AND format = 'log'
           RETURNING *""",
        channel_id, slot_name, json.dumps(lines),
    )
    return dict(row) if row else None


async def update_channel_metadata(channel_id: str, metadata: dict) -> dict | None:
    row = await pool.fetchrow(
        """UPDATE channels SET metadata = $2, updated_at = NOW()
           WHERE id = $1
           RETURNING *""",
        channel_id, json.dumps(metadata),
    )
    return dict(row) if row else None


async def store_file_upload(
    item_id: int, file_path: str, mime_type: str,
    size_bytes: int | None, original_name: str | None,
) -> int:
    return await pool.fetchval(
        """INSERT INTO file_uploads (item_id, file_path, mime_type, size_bytes, original_name)
           VALUES ($1, $2, $3, $4, $5) RETURNING id""",
        item_id, file_path, mime_type, size_bytes, original_name,
    )


async def get_file_upload(upload_id: int) -> dict | None:
    row = await pool.fetchrow(
        "SELECT * FROM file_uploads WHERE id = $1", upload_id,
    )
    return dict(row) if row else None
