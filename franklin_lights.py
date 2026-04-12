"""Franklin lights — control panel router.

Thin proxy to the lights daemon's HTTP API on Franklin
(http://100.112.120.2:6743). The daemon owns brightness state and the
state machine; this module just renders a page and forwards requests.
"""
from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

DAEMON_URL = os.environ.get("FRANKLIN_LIGHTS_DAEMON_URL", "http://100.112.120.2:6743")

router = APIRouter(prefix="/api/franklin-lights", tags=["franklin-lights"])


class BrightnessRequest(BaseModel):
    brightness: int = Field(ge=0, le=100)


async def _proxy_get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=3.0) as client:
        r = await client.get(f"{DAEMON_URL}{path}")
        r.raise_for_status()
        return r.json()


async def _proxy_post(path: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.post(f"{DAEMON_URL}{path}", json=payload)
        r.raise_for_status()
        return r.json()


@router.get("/state")
async def get_state():
    try:
        return await _proxy_get("/api/state")
    except httpx.HTTPError as e:
        return JSONResponse(
            {
                "error": f"daemon unreachable: {e}",
                "state": None,
                "color": "000000",
                "scaled_color": "000000",
                "brightness": None,
                "kuma_down": [],
                "cluster_issues": [],
                "meta_error": "lights daemon unreachable from output",
                "last_change_at": None,
                "since_seconds": None,
                "kuma_excluded": [],
            },
            status_code=503,
        )


@router.post("/brightness")
async def set_brightness(req: BrightnessRequest):
    try:
        return await _proxy_post("/api/brightness", {"brightness": req.brightness})
    except httpx.HTTPError as e:
        raise HTTPException(503, f"daemon unreachable: {e}")


@router.post("/push")
async def force_push():
    try:
        return await _proxy_post("/api/push", {})
    except httpx.HTTPError as e:
        raise HTTPException(503, f"daemon unreachable: {e}")
