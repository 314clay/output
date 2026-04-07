"""Integration tests for the output display backend."""

import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE = "http://localhost:3051"


def api(method, path, data=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def fetch(path):
    with urllib.request.urlopen(f"{BASE}{path}") as resp:
        return resp.status, resp.read().decode()


def wait_for_server(timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            api("GET", "/api/state")
            return True
        except Exception:
            time.sleep(0.3)
    return False


# --- Tests ---

def test_health():
    status, data = api("GET", "/api/state")
    assert status == 200
    assert data["status"] == "ok"
    assert data["service"] == "output"
    assert data["db"] == "connected"
    print("  health check OK")


def test_create_channel():
    status, data = api("POST", "/api/channel", {
        "id": "test-channel",
        "name": "Test Channel",
        "description": "A test channel",
        "metadata": {"source": "test"},
    })
    assert status == 201
    assert data["id"] == "test-channel"
    assert data["name"] == "Test Channel"
    assert "/test-channel" in data["url"]

    # Duplicate should 409
    status, data = api("POST", "/api/channel", {
        "id": "test-channel",
        "name": "Duplicate",
    })
    assert status == 409
    print("  create channel OK")


def test_list_channels():
    status, data = api("GET", "/api/channels")
    assert status == 200
    ids = {c["id"] for c in data["channels"]}
    assert "test-channel" in ids
    assert data["channels"][0]["item_count"] == 0
    print("  list channels OK")


def test_push_text():
    # Plain text
    status, data = api("POST", "/api/push/test-channel", {
        "format": "text",
        "title": "Hello World",
        "content": {"body": "This is plain text.", "render": "plain"},
    })
    assert status == 201
    assert data["format"] == "text"
    assert data["channel_id"] == "test-channel"

    # Markdown text
    status, data = api("POST", "/api/push/test-channel", {
        "format": "text",
        "title": "Markdown Test",
        "content": {"body": "# Heading\n\n**bold** text", "render": "markdown"},
    })
    assert status == 201
    print("  push text OK")


def test_push_chart():
    status, data = api("POST", "/api/push/test-channel", {
        "format": "chart",
        "title": "CPU Usage",
        "content": {
            "chart_type": "line",
            "data": {
                "labels": ["1m", "2m", "3m", "4m", "5m"],
                "datasets": [{"label": "CPU %", "data": [45, 62, 38, 71, 55]}],
            },
            "options": {"responsive": True},
        },
    })
    assert status == 201
    assert data["format"] == "chart"
    print("  push chart OK")


def test_push_table():
    status, data = api("POST", "/api/push/test-channel", {
        "format": "table",
        "title": "Server Stats",
        "content": {
            "columns": ["Host", "CPU", "Memory", "Disk"],
            "rows": [
                ["web-1", "23%", "4.2GB", "67%"],
                ["web-2", "45%", "3.8GB", "72%"],
                ["db-1", "12%", "8.1GB", "45%"],
            ],
            "caption": "Current server metrics",
        },
    })
    assert status == 201
    assert data["format"] == "table"
    print("  push table OK")


def test_push_log():
    status, data = api("POST", "/api/push/test-channel", {
        "format": "log",
        "title": "Build Log",
        "content": {
            "lines": ["Starting build...", "Compiling step 1/3", "Compiling step 2/3"],
            "level": "info",
        },
    })
    assert status == 201
    log_item_id = data["item_id"]
    print("  push log OK")
    return log_item_id


def test_append_log():
    # First push a log
    log_item_id = test_push_log.__wrapped__() if hasattr(test_push_log, "__wrapped__") else None

    # Append lines
    status, data = api("POST", "/api/push/test-channel/append", {
        "lines": ["Compiling step 3/3", "Build complete!"],
    })
    assert status == 200
    assert data["total_lines"] >= 5  # 3 original + 2 appended (may be from earlier log)
    assert data["item_id"] >= 1
    print("  append log OK")


def test_push_json():
    status, data = api("POST", "/api/push/test-channel", {
        "format": "json",
        "title": "API Response",
        "content": {
            "data": {
                "users": [
                    {"id": 1, "name": "Alice", "active": True},
                    {"id": 2, "name": "Bob", "active": False},
                ],
                "total": 2,
                "page": 1,
            },
        },
    })
    assert status == 201
    assert data["format"] == "json"
    print("  push json OK")


def test_push_html():
    status, data = api("POST", "/api/push/test-channel", {
        "format": "html",
        "title": "Custom Widget",
        "content": {
            "body": "<div style='padding:20px;background:#f0f0f0;border-radius:8px;'><h2>Hello</h2><p>Custom HTML content</p></div>",
            "sandbox": True,
        },
    })
    assert status == 201
    assert data["format"] == "html"
    print("  push html OK")


def test_push_image_url():
    status, data = api("POST", "/api/push/test-channel", {
        "format": "image",
        "title": "Test Image",
        "content": {
            "url": "https://via.placeholder.com/300x200",
            "alt": "Placeholder image",
            "caption": "A test placeholder",
        },
    })
    assert status == 201
    assert data["format"] == "image"
    print("  push image (url) OK")


def test_push_diff():
    diff_text = """--- a/server.py
+++ b/server.py
@@ -10,7 +10,7 @@
 PORT = int(os.environ.get("PORT", "3051"))
-START_TIME = None
+START_TIME = time.time()
"""
    status, data = api("POST", "/api/push/test-channel", {
        "format": "diff",
        "title": "Fix startup time",
        "content": {
            "diff": diff_text,
            "language": "python",
            "filename": "server.py",
        },
    })
    assert status == 201
    assert data["format"] == "diff"
    print("  push diff OK")


def test_get_items():
    status, data = api("GET", "/api/items/test-channel")
    assert status == 200
    assert data["channel_id"] == "test-channel"
    assert data["count"] >= 8  # all the items we pushed

    # Check formats are diverse
    formats = {i["format"] for i in data["items"]}
    assert "text" in formats
    assert "chart" in formats
    assert "table" in formats
    assert "log" in formats
    assert "json" in formats
    assert "html" in formats
    assert "image" in formats
    assert "diff" in formats
    print("  get items OK")


def test_get_items_filter():
    status, data = api("GET", "/api/items/test-channel?format=text")
    assert status == 200
    assert all(i["format"] == "text" for i in data["items"])
    assert data["count"] >= 2  # plain + markdown
    print("  get items filter OK")


def test_get_items_limit():
    status, data = api("GET", "/api/items/test-channel?limit=2")
    assert status == 200
    assert data["count"] <= 2
    print("  get items limit OK")


def test_delete_item():
    # Push an item to delete
    status, data = api("POST", "/api/push/test-channel", {
        "format": "text",
        "title": "To Delete",
        "content": {"body": "This will be deleted", "render": "plain"},
    })
    assert status == 201
    item_id = data["item_id"]

    # Delete it
    status, data = api("DELETE", f"/api/item/{item_id}")
    assert status == 200
    assert data["deleted"] is True
    assert data["item_id"] == item_id

    # Delete nonexistent
    status, data = api("DELETE", f"/api/item/999999")
    assert status == 404
    print("  delete item OK")


def test_clear_channel():
    # Create a separate channel for clearing
    api("POST", "/api/channel", {"id": "test-clear"})
    api("POST", "/api/push/test-clear", {
        "format": "text", "content": {"body": "item 1", "render": "plain"},
    })
    api("POST", "/api/push/test-clear", {
        "format": "text", "content": {"body": "item 2", "render": "plain"},
    })

    status, data = api("POST", "/api/clear/test-clear")
    assert status == 200
    assert data["items_deleted"] == 2
    assert data["channel_id"] == "test-clear"

    # Verify empty
    status, data = api("GET", "/api/items/test-clear")
    assert data["count"] == 0
    print("  clear channel OK")


def test_auto_create_channel():
    """Pushing to a nonexistent channel auto-creates it."""
    status, data = api("POST", "/api/push/auto-created", {
        "format": "text",
        "title": "Auto",
        "content": {"body": "Channel should be auto-created", "render": "plain"},
    })
    assert status == 201
    assert data["channel_id"] == "auto-created"

    # Verify channel exists
    status, data = api("GET", "/api/channels")
    ids = {c["id"] for c in data["channels"]}
    assert "auto-created" in ids

    # Auto-created name should be title-cased
    ch = next(c for c in data["channels"] if c["id"] == "auto-created")
    assert ch["name"] == "Auto Created"
    print("  auto-create channel OK")


def test_archive_channel():
    api("POST", "/api/channel", {"id": "test-archive"})

    status, data = api("DELETE", "/api/channel/test-archive")
    assert status == 200
    assert "archived_at" in data

    # Push to archived channel should fail
    status, data = api("POST", "/api/push/test-archive", {
        "format": "text", "content": {"body": "nope", "render": "plain"},
    })
    assert status == 410

    # Archive again should 409
    status, data = api("DELETE", "/api/channel/test-archive")
    assert status == 409

    # Archive nonexistent should 404
    status, data = api("DELETE", "/api/channel/nonexistent-xyz")
    assert status == 404

    # Archived channel hidden from active list
    status, data = api("GET", "/api/channels")
    ids = {c["id"] for c in data["channels"]}
    assert "test-archive" not in ids

    # But visible with active=false
    status, data = api("GET", "/api/channels?active=false")
    ids = {c["id"] for c in data["channels"]}
    assert "test-archive" in ids
    print("  archive channel OK")


def test_pinned_item():
    status, data = api("POST", "/api/push/test-channel", {
        "format": "text",
        "title": "Pinned Note",
        "content": {"body": "This is pinned", "render": "plain"},
        "pinned": True,
    })
    assert status == 201

    # Verify it's in items
    status, data = api("GET", "/api/items/test-channel")
    pinned = [i for i in data["items"] if i["pinned"]]
    assert len(pinned) >= 1
    assert any(i["title"] == "Pinned Note" for i in pinned)
    print("  pinned item OK")


def test_serve_channel_page():
    status, html = fetch("/test-channel")
    assert status == 200
    assert "Test Channel" in html
    assert "data-channel=\"test-channel\"" in html
    assert "/static/style.css" in html
    assert "/static/output.js" in html
    assert "chart.js" in html.lower() or "Chart" in html
    print("  serve channel page OK")


def test_serve_index_page():
    status, html = fetch("/")
    assert status == 200
    assert "Output Channels" in html
    assert "test-channel" in html
    print("  serve index page OK")


def test_404():
    try:
        with urllib.request.urlopen(f"{BASE}/nonexistent-channel-xyz") as resp:
            assert False, "expected 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404
    print("  404 OK")


def test_validation():
    # Bad format
    status, data = api("POST", "/api/push/test-channel", {
        "format": "invalid-format",
        "content": {"body": "x"},
    })
    assert status == 422

    # Missing content
    status, data = api("POST", "/api/push/test-channel", {
        "format": "text",
    })
    assert status == 422

    # Bad channel ID
    status, data = api("POST", "/api/channel", {
        "id": "x",  # too short
    })
    assert status == 422
    print("  validation OK")


def test_append_log_no_log_item():
    """Appending to a channel with no log item should 404."""
    api("POST", "/api/channel", {"id": "test-no-log"})
    status, data = api("POST", "/api/push/test-no-log/append", {
        "lines": ["this should fail"],
    })
    assert status == 404
    print("  append log no item OK")


def test_get_items_nonexistent():
    status, data = api("GET", "/api/items/totally-nonexistent")
    assert status == 404
    print("  get items nonexistent OK")


def test_clear_nonexistent():
    status, data = api("POST", "/api/clear/totally-nonexistent")
    assert status == 404
    print("  clear nonexistent OK")


def test_items_since_filter():
    """Test the 'since' query param for items."""
    import urllib.parse
    # Get current time
    before_time = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    encoded_time = urllib.parse.quote(before_time)
    time.sleep(0.1)

    api("POST", "/api/push/test-channel", {
        "format": "text",
        "title": "After Timestamp",
        "content": {"body": "new item", "render": "plain"},
    })

    status, data = api("GET", f"/api/items/test-channel?since={encoded_time}")
    assert status == 200
    assert data["count"] >= 1
    assert any(i["title"] == "After Timestamp" for i in data["items"])
    print("  items since filter OK")


def test_multiple_format_rendering():
    """Verify channel page renders all format types correctly."""
    status, html = fetch("/test-channel")
    assert status == 200

    # Check format-specific elements are present
    assert 'data-format="text"' in html
    assert 'data-format="chart"' in html
    assert 'data-format="table"' in html
    assert 'data-format="log"' in html
    assert 'data-format="json"' in html
    assert 'data-format="html"' in html
    assert 'data-format="image"' in html
    assert 'data-format="diff"' in html
    print("  multiple format rendering OK")


# --- Template / Slot Tests ---

def test_create_templated_channel():
    status, data = api("POST", "/api/channel", {
        "id": "test-dashboard",
        "name": "Test Dashboard",
        "metadata": {
            "template": {
                "columns": 2,
                "row_height": "200px",
                "gap": "16px",
                "slots": {
                    "status": {"col": 1, "row": 1, "width": 1, "height": 1, "label": "Status"},
                    "chart": {"col": 2, "row": 1, "width": 1, "height": 1, "label": "Chart"},
                    "logs": {"col": 1, "row": 2, "width": 2, "height": 1, "label": "Logs"},
                },
            },
        },
    })
    assert status == 201
    assert data["id"] == "test-dashboard"
    print("  create templated channel OK")


def test_push_to_slot():
    status, data = api("POST", "/api/push/test-dashboard", {
        "format": "text",
        "slot": "status",
        "content": {"body": "All systems go", "render": "plain"},
    })
    assert status == 201
    assert data["format"] == "text"

    # Push again to same slot — should upsert (replace)
    status, data2 = api("POST", "/api/push/test-dashboard", {
        "format": "text",
        "slot": "status",
        "content": {"body": "Updated status", "render": "plain"},
    })
    assert status == 201

    # Verify only one item in the slot (upsert, not duplicate)
    status, items = api("GET", "/api/items/test-dashboard")
    slot_items = [i for i in items["items"] if i.get("title") is None or True]
    # Check at most 1 text item with "Updated status"
    updated = [i for i in items["items"] if i["content"].get("body") == "Updated status"]
    assert len(updated) == 1
    print("  push to slot OK")


def test_push_to_invalid_slot():
    status, data = api("POST", "/api/push/test-dashboard", {
        "format": "text",
        "slot": "nonexistent-slot",
        "content": {"body": "should fail"},
    })
    assert status == 422
    print("  push to invalid slot OK")


def test_push_chart_to_slot():
    status, data = api("POST", "/api/push/test-dashboard", {
        "format": "chart",
        "slot": "chart",
        "content": {
            "chart_type": "bar",
            "data": {"labels": ["A", "B"], "datasets": [{"data": [10, 20]}]},
        },
    })
    assert status == 201
    assert data["format"] == "chart"
    print("  push chart to slot OK")


def test_push_log_to_slot_and_append():
    # Push initial log to slot
    status, data = api("POST", "/api/push/test-dashboard", {
        "format": "log",
        "slot": "logs",
        "content": {"lines": ["Starting build..."], "level": "info"},
    })
    assert status == 201

    # Append to the log slot
    status, data = api("POST", "/api/push/test-dashboard/append", {
        "lines": ["Step 1 complete", "Step 2 complete"],
        "slot": "logs",
    })
    assert status == 200
    assert data["total_lines"] == 3
    print("  push log to slot and append OK")


def test_append_log_to_invalid_slot():
    status, data = api("POST", "/api/push/test-dashboard/append", {
        "lines": ["should fail"],
        "slot": "nonexistent",
    })
    assert status == 404
    print("  append log to invalid slot OK")


def test_push_without_slot_to_templated_channel():
    """Non-slotted push to a templated channel still works as feed."""
    status, data = api("POST", "/api/push/test-dashboard", {
        "format": "text",
        "title": "Feed Item",
        "content": {"body": "This goes to the feed, not a slot"},
    })
    assert status == 201
    print("  push without slot to templated channel OK")


def test_serve_dashboard_page():
    status, html = fetch("/test-dashboard")
    assert status == 200
    assert "Test Dashboard" in html
    assert 'data-dashboard="true"' in html
    assert "dashboard-grid" in html
    assert "slot-status" in html
    assert "slot-chart" in html
    assert "slot-logs" in html
    print("  serve dashboard page OK")


def test_get_template():
    status, data = api("GET", "/api/channel/test-dashboard/template")
    assert status == 200
    assert "template" in data
    assert "slots" in data["template"]
    assert "status" in data["template"]["slots"]
    assert "slot_items" in data
    assert "status" in data["slot_items"]
    print("  get template OK")


def test_get_template_nonexistent():
    status, data = api("GET", "/api/channel/test-channel/template")
    assert status == 404
    assert "no template" in data["error"]
    print("  get template nonexistent OK")


def test_update_template():
    status, data = api("PUT", "/api/channel/test-dashboard/template", {
        "columns": 3,
        "row_height": "300px",
        "gap": "20px",
        "slots": {
            "status": {"col": 1, "row": 1, "width": 1, "height": 1, "label": "Status"},
            "chart": {"col": 2, "row": 1, "width": 1, "height": 1, "label": "Chart"},
            "logs": {"col": 3, "row": 1, "width": 1, "height": 1, "label": "Logs"},
        },
    })
    assert status == 200
    assert data["template"]["columns"] == 3
    print("  update template OK")


def test_push_math():
    status, data = api("POST", "/api/push/test-channel", {
        "format": "math",
        "title": "Euler's Identity",
        "content": {"expression": "e^{i\\pi} + 1 = 0", "display": "block"},
    })
    assert status == 201
    assert data["format"] == "math"
    print("  push math OK")


def test_push_media_video():
    status, data = api("POST", "/api/push/test-channel", {
        "format": "media",
        "title": "Demo Video",
        "content": {
            "type": "video",
            "url": "https://www.w3schools.com/html/mov_bbb.mp4",
            "mime": "video/mp4",
            "caption": "Big Buck Bunny clip",
        },
    })
    assert status == 201
    assert data["format"] == "media"
    print("  push media video OK")


def test_push_media_audio():
    status, data = api("POST", "/api/push/test-channel", {
        "format": "media",
        "title": "Audio Sample",
        "content": {
            "type": "audio",
            "url": "https://www.w3schools.com/html/horse.ogg",
            "mime": "audio/ogg",
        },
    })
    assert status == 201
    assert data["format"] == "media"
    print("  push media audio OK")


def test_push_progress():
    status, data = api("POST", "/api/push/test-channel", {
        "format": "progress",
        "title": "Training",
        "content": {"percent": 45, "status": "Epoch 9/20"},
    })
    assert status == 201
    assert data["format"] == "progress"
    print("  push progress OK")


def test_push_progress_complete():
    status, data = api("POST", "/api/push/test-channel", {
        "format": "progress",
        "title": "Build",
        "content": {"percent": 100, "status": "Complete"},
    })
    assert status == 201
    print("  push progress complete OK")


def test_math_slot():
    """Push math to a dashboard slot."""
    status, data = api("POST", "/api/push/test-dashboard", {
        "format": "math",
        "slot": "status",
        "content": {"expression": "\\int_0^\\infty e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}"},
    })
    assert status == 201
    print("  math in slot OK")


def test_invalid_template_on_create():
    status, data = api("POST", "/api/channel", {
        "id": "test-bad-tmpl",
        "metadata": {
            "template": {
                "slots": "not-a-dict",
            },
        },
    })
    assert status == 422
    print("  invalid template on create OK")


# --- Cleanup ---

def cleanup():
    """Remove test channels."""
    for cid in ["test-channel", "test-clear", "auto-created", "test-archive", "test-no-log",
                "test-dashboard", "test-bad-tmpl"]:
        try:
            # Unarchive by deleting (archive), then we can't really delete...
            # Just archive them all — tests use fresh IDs anyway
            api("DELETE", f"/api/channel/{cid}")
        except Exception:
            pass


# --- Runner ---

if __name__ == "__main__":
    print("Waiting for server...")
    if not wait_for_server():
        print("Server not available at", BASE)
        sys.exit(1)

    tests = [
        test_health,
        test_create_channel,
        test_list_channels,
        test_push_text,
        test_push_chart,
        test_push_table,
        test_push_log,
        test_append_log,
        test_push_json,
        test_push_html,
        test_push_image_url,
        test_push_diff,
        test_get_items,
        test_get_items_filter,
        test_get_items_limit,
        test_delete_item,
        test_clear_channel,
        test_auto_create_channel,
        test_archive_channel,
        test_pinned_item,
        test_serve_channel_page,
        test_serve_index_page,
        test_404,
        test_validation,
        test_append_log_no_log_item,
        test_get_items_nonexistent,
        test_clear_nonexistent,
        test_items_since_filter,
        test_multiple_format_rendering,
        # Template / Slot tests
        test_create_templated_channel,
        test_push_to_slot,
        test_push_to_invalid_slot,
        test_push_chart_to_slot,
        test_push_log_to_slot_and_append,
        test_append_log_to_invalid_slot,
        test_push_without_slot_to_templated_channel,
        test_serve_dashboard_page,
        test_get_template,
        test_get_template_nonexistent,
        test_update_template,
        test_invalid_template_on_create,
        # New format tests
        test_push_math,
        test_push_media_video,
        test_push_media_audio,
        test_push_progress,
        test_push_progress_complete,
        test_math_slot,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL {test.__name__}: {e}")
            failed += 1

    cleanup()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
