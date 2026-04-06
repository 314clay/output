import asyncio
import base64
import json
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import markdown
from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

import db
from models import AppendLogRequest, CreateChannelRequest, PushItemRequest, TemplateDefinition

# --- Config ---

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "upload_data"))
PORT = int(os.environ.get("PORT", "3051"))
START_TIME = time.time()

# --- Template Engine ---

template_dir = Path(__file__).parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)


def relative_time(dt: datetime) -> str:
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def enrich_item(item: dict) -> dict:
    """Add computed fields to an item dict for template rendering."""
    content = json.loads(item["content"]) if isinstance(item["content"], str) else item["content"]
    item["content"] = content
    item["age"] = relative_time(item["created_at"])

    # Format-specific enrichment
    if item["format"] == "text" and content.get("render") == "markdown":
        item["rendered_html"] = markdown.markdown(
            content.get("body", ""),
            extensions=["fenced_code", "tables", "nl2br"],
        )
    if item["format"] == "chart":
        chart_config = {
            "type": content.get("chart_type", "bar"),
            "data": content.get("data", {}),
            "options": content.get("options", {}),
        }
        item["chart_json"] = json.dumps(chart_config)
    if item["format"] == "json":
        item["json_str"] = json.dumps(content.get("data", content))

    return item


def render_item(item: dict) -> Markup:
    """Render a single item using its format's partial template."""
    enriched = enrich_item(item)
    partial = jinja_env.get_template(f"partials/{enriched['format']}.html")
    return Markup(partial.render(item=enriched))


# --- SSE ---

sse_listeners: dict[str, set[asyncio.Queue]] = defaultdict(set)


async def broadcast(channel_id: str, event_type: str, data: dict):
    message = f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"
    dead = set()
    for queue in sse_listeners.get(channel_id, set()):
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            dead.add(queue)
    if dead:
        sse_listeners[channel_id] -= dead


# --- App ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    yield
    await db.close_pool()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


# Make render_item available in Jinja2 templates
jinja_env.globals["render_item"] = render_item


# --- Routes: Health ---

@app.get("/api/state")
async def health():
    return {
        "status": "ok",
        "service": "output",
        "db": "connected" if db.pool else "disconnected",
        "uptime_seconds": int(time.time() - START_TIME),
    }


# --- Routes: Channel Management ---

@app.post("/api/channel")
async def create_channel(req: CreateChannelRequest):
    existing = await db.get_channel(req.id)
    if existing:
        return JSONResponse({"error": f"channel '{req.id}' already exists"}, 409)

    name = req.name or req.id.replace("-", " ").replace("_", " ").title()
    row = await db.create_channel(req.id, name, req.description, req.metadata)
    return JSONResponse({
        "id": row["id"],
        "url": f"/{row['id']}",
        "name": row["name"],
        "created_at": row["created_at"].isoformat(),
    }, 201)


@app.get("/api/channels")
async def list_channels(active: bool = True):
    rows = await db.list_channels(active_only=active)
    return {
        "channels": [
            {
                "id": r["id"],
                "name": r["name"],
                "description": r["description"],
                "item_count": r["item_count"],
                "archived": r["archived_at"] is not None,
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }


@app.delete("/api/channel/{channel_id}")
async def archive_channel(channel_id: str):
    result = await db.archive_channel(channel_id)
    if not result:
        ch = await db.get_channel(channel_id)
        if not ch:
            return JSONResponse({"error": "not found"}, 404)
        return JSONResponse({"error": "already archived", "archived_at": ch["archived_at"].isoformat()}, 409)

    return {
        "id": channel_id,
        "archived_at": result["archived_at"].isoformat(),
    }


# --- Routes: Push Items ---

async def ensure_channel(channel_id: str) -> dict:
    """Auto-create channel if it doesn't exist."""
    ch = await db.get_channel(channel_id)
    if not ch:
        name = channel_id.replace("-", " ").replace("_", " ").title()
        ch = await db.create_channel(channel_id, name, None, {})
    return ch


@app.post("/api/push/{channel_id}")
async def push_item(channel_id: str, req: PushItemRequest):
    ch = await ensure_channel(channel_id)
    if ch.get("archived_at"):
        return JSONResponse({"error": "channel is archived"}, 410)

    if req.slot:
        # Validate slot exists in channel template
        metadata = json.loads(ch["metadata"]) if isinstance(ch["metadata"], str) else (ch["metadata"] or {})
        tmpl = metadata.get("template")
        if not tmpl or req.slot not in tmpl.get("slots", {}):
            return JSONResponse({"error": f"slot '{req.slot}' not defined in channel template"}, 422)

        row = await db.upsert_slot_item(channel_id, req.slot, req.format, req.title, req.content)
        html_fragment = render_item(dict(row))

        await broadcast(channel_id, "slot_update", {
            "slot_name": req.slot,
            "item_id": row["id"],
            "format": row["format"],
            "html": html_fragment,
            "created_at": row["created_at"].isoformat(),
        })
    else:
        row = await db.create_item(channel_id, req.format, req.title, req.content, req.pinned)
        html_fragment = render_item(dict(row))

        await broadcast(channel_id, "new_item", {
            "item_id": row["id"],
            "format": row["format"],
            "html": html_fragment,
            "created_at": row["created_at"].isoformat(),
        })

    return JSONResponse({
        "item_id": row["id"],
        "channel_id": channel_id,
        "format": row["format"],
        "created_at": row["created_at"].isoformat(),
    }, 201)


@app.post("/api/push/{channel_id}/append")
async def append_log(channel_id: str, req: AppendLogRequest):
    if req.slot:
        result = await db.append_log_to_slot(channel_id, req.slot, req.lines)
    else:
        result = await db.append_log_lines(channel_id, req.lines)

    if not result:
        error_msg = f"no log item found in slot '{req.slot}'" if req.slot else "no log item found in channel"
        return JSONResponse({"error": error_msg}, 404)

    content = json.loads(result["content"]) if isinstance(result["content"], str) else result["content"]
    total_lines = len(content.get("lines", []))

    await broadcast(channel_id, "append_log", {
        "item_id": result["id"],
        "lines": req.lines,
        "level": content.get("level"),
        "total_lines": total_lines,
        "slot_name": req.slot,
    })

    return {
        "item_id": result["id"],
        "total_lines": total_lines,
    }


@app.get("/api/items/{channel_id}")
async def get_items(
    channel_id: str,
    since: str | None = None,
    limit: int = 50,
    format: str | None = None,
):
    ch = await db.get_channel(channel_id)
    if not ch:
        return JSONResponse({"error": "not found"}, 404)

    since_dt = datetime.fromisoformat(since) if since else None
    items = await db.get_items(channel_id, since=since_dt, limit=limit, format_filter=format)

    return {
        "channel_id": channel_id,
        "items": [
            {
                "id": i["id"],
                "format": i["format"],
                "title": i["title"],
                "content": json.loads(i["content"]) if isinstance(i["content"], str) else i["content"],
                "pinned": i["pinned"],
                "created_at": i["created_at"].isoformat(),
            }
            for i in items
        ],
        "count": len(items),
    }


@app.delete("/api/item/{item_id}")
async def delete_item(item_id: int):
    item = await db.get_item(item_id)
    if not item:
        return JSONResponse({"error": "not found"}, 404)

    channel_id = item["channel_id"]
    await db.delete_item(item_id)

    await broadcast(channel_id, "item_deleted", {"item_id": item_id})

    return {"deleted": True, "item_id": item_id}


@app.post("/api/clear/{channel_id}")
async def clear_channel(channel_id: str):
    ch = await db.get_channel(channel_id)
    if not ch:
        return JSONResponse({"error": "not found"}, 404)

    count = await db.clear_items(channel_id)

    await broadcast(channel_id, "channel_cleared", {"channel_id": channel_id})

    return {"channel_id": channel_id, "items_deleted": count}


# --- Routes: Templates ---

@app.get("/api/channel/{channel_id}/template")
async def get_template(channel_id: str):
    ch = await db.get_channel(channel_id)
    if not ch:
        return JSONResponse({"error": "not found"}, 404)

    metadata = json.loads(ch["metadata"]) if isinstance(ch["metadata"], str) else (ch["metadata"] or {})
    tmpl = metadata.get("template")
    if not tmpl:
        return JSONResponse({"error": "channel has no template"}, 404)

    slot_items_raw = await db.get_slot_items(channel_id)
    slot_items = {}
    for item in slot_items_raw:
        content = json.loads(item["content"]) if isinstance(item["content"], str) else item["content"]
        slot_items[item["slot_name"]] = {
            "id": item["id"],
            "format": item["format"],
            "title": item["title"],
            "content": content,
            "created_at": item["created_at"].isoformat(),
        }

    return {"template": tmpl, "slot_items": slot_items}


@app.put("/api/channel/{channel_id}/template")
async def update_template(channel_id: str, req: TemplateDefinition):
    ch = await db.get_channel(channel_id)
    if not ch:
        return JSONResponse({"error": "not found"}, 404)

    metadata = json.loads(ch["metadata"]) if isinstance(ch["metadata"], str) else (ch["metadata"] or {})
    metadata["template"] = req.model_dump()
    result = await db.update_channel_metadata(channel_id, metadata)

    await broadcast(channel_id, "template_updated", {"template": req.model_dump()})

    return {"id": channel_id, "template": req.model_dump()}


# --- Routes: File Upload ---

@app.post("/api/upload/{channel_id}")
async def upload_file(channel_id: str, file: UploadFile):
    """Upload a file and create an image item referencing it."""
    ch = await ensure_channel(channel_id)
    if ch.get("archived_at"):
        return JSONResponse({"error": "channel is archived"}, 410)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    contents = await file.read()
    file_name = f"{channel_id}_{int(time.time())}_{file.filename or 'upload'}"
    file_path = UPLOAD_DIR / file_name
    file_path.write_bytes(contents)

    # Create an image item first, then link the upload to it
    mime = file.content_type or "application/octet-stream"
    item_row = await db.create_item(
        channel_id, "image", file.filename,
        {"url": "", "alt": file.filename or "", "caption": ""},
    )
    upload_id = await db.store_file_upload(
        item_row["id"], str(file_path), mime, len(contents), file.filename,
    )

    # Update the item content to reference the upload
    await db.pool.execute(
        "UPDATE items SET content = $1 WHERE id = $2",
        json.dumps({"upload_id": upload_id, "alt": file.filename or "", "caption": ""}),
        item_row["id"],
    )

    # Broadcast
    updated_item = await db.get_item(item_row["id"])
    html_fragment = render_item(dict(updated_item))
    await broadcast(channel_id, "new_item", {
        "item_id": item_row["id"],
        "format": "image",
        "html": html_fragment,
        "created_at": item_row["created_at"].isoformat(),
    })

    return JSONResponse({
        "upload_id": upload_id,
        "item_id": item_row["id"],
        "url": f"/api/file/{upload_id}",
        "size_bytes": len(contents),
        "mime_type": mime,
    }, 201)


@app.get("/api/file/{upload_id}")
async def serve_file(upload_id: int):
    upload = await db.get_file_upload(upload_id)
    if not upload:
        return JSONResponse({"error": "not found"}, 404)
    return FileResponse(upload["file_path"], media_type=upload["mime_type"])


# --- Routes: SSE ---

@app.get("/api/listen/{channel_id}")
async def listen(channel_id: str, request: Request, replay: bool = False):
    ch = await db.get_channel(channel_id)
    if not ch:
        return JSONResponse({"error": "not found"}, 404)

    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    sse_listeners[channel_id].add(queue)

    async def event_generator():
        try:
            if replay:
                items = await db.get_items(channel_id, limit=100)
                for item in reversed(items):  # oldest first
                    html = render_item(dict(item))
                    data = {
                        "item_id": item["id"],
                        "format": item["format"],
                        "html": html,
                        "created_at": item["created_at"].isoformat(),
                    }
                    yield f"event: new_item\ndata: {json.dumps(data, default=str)}\n\n"

            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield message
                except asyncio.TimeoutError:
                    yield f"event: heartbeat\ndata: {json.dumps({'time': datetime.now(timezone.utc).isoformat()})}\n\n"

                if await request.is_disconnected():
                    break
        finally:
            sse_listeners[channel_id].discard(queue)
            if not sse_listeners[channel_id]:
                del sse_listeners[channel_id]

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Routes: Pages ---

@app.get("/")
async def index():
    rows = await db.list_channels(active_only=True)
    channels = [
        {**r, "age": relative_time(r["created_at"])}
        for r in rows
    ]
    tmpl = jinja_env.get_template("index.html")
    html = tmpl.render(channels=channels, total=len(channels))
    return HTMLResponse(html)


@app.get("/{channel_id}")
async def serve_channel(channel_id: str):
    ch = await db.get_channel(channel_id)
    if not ch:
        return HTMLResponse("<h1>Not found</h1>", 404)

    metadata = json.loads(ch["metadata"]) if isinstance(ch["metadata"], str) else (ch["metadata"] or {})
    template_def = metadata.get("template")

    if template_def:
        # Dashboard mode
        slot_items_raw = await db.get_slot_items(channel_id)
        slot_items = {}
        for item in slot_items_raw:
            slot_items[item["slot_name"]] = enrich_item(dict(item))

        tmpl = jinja_env.get_template("dashboard.html")
        html = tmpl.render(
            channel=ch,
            tmpl=template_def,
            slot_items=slot_items,
        )
    else:
        # Chronological feed mode
        items_raw = await db.get_items(channel_id, limit=100)
        items = [enrich_item(dict(i)) for i in reversed(items_raw)]

        tmpl = jinja_env.get_template("channel.html")
        html = tmpl.render(
            channel=ch,
            items=items,
            item_count=len(items),
        )
    return HTMLResponse(html)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
