"""Optional Redis cache for beach payloads. Falls back to memory-only when REDIS_URL is unset."""

from __future__ import annotations

import json
import os
from typing import Dict, Optional

REDIS_URL = os.environ.get("REDIS_URL", "").strip()
CACHE_PREFIX = "marine:beach:"
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "600"))

_redis_client = None
_redis_init_attempted = False


def _get_client():
    global _redis_client, _redis_init_attempted
    if _redis_init_attempted:
        return _redis_client
    _redis_init_attempted = True
    if not REDIS_URL:
        print("[CACHE] REDIS_URL not set — memory-only mode")
        return None
    try:
        import redis

        client = redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=4)
        client.ping()
        _redis_client = client
        print("[CACHE] Redis connected")
    except Exception as exc:
        print(f"[CACHE] Redis unavailable (memory-only): {str(exc)[:120]}")
        _redis_client = None
    return _redis_client


def is_connected() -> bool:
    client = _get_client()
    if client is None:
        return False
    try:
        client.ping()
        return True
    except Exception:
        return False


def status() -> dict:
    return {
        "enabled": bool(REDIS_URL),
        "connected": is_connected(),
        "ttl_seconds": CACHE_TTL_SECONDS,
    }


def write_beach(beach_id: str, data: dict) -> bool:
    client = _get_client()
    if client is None:
        return False
    try:
        client.setex(f"{CACHE_PREFIX}{beach_id}", CACHE_TTL_SECONDS, json.dumps(data))
        return True
    except Exception as exc:
        print(f"[CACHE] write {beach_id} failed: {str(exc)[:80]}")
        return False


def read_beach(beach_id: str) -> Optional[dict]:
    client = _get_client()
    if client is None:
        return None
    try:
        raw = client.get(f"{CACHE_PREFIX}{beach_id}")
        if not raw:
            return None
        return json.loads(raw)
    except Exception as exc:
        print(f"[CACHE] read {beach_id} failed: {str(exc)[:80]}")
        return None


def load_all(beach_ids) -> Dict[str, dict]:
    loaded: Dict[str, dict] = {}
    for beach_id in beach_ids:
        payload = read_beach(beach_id)
        if payload and not payload.get("error"):
            loaded[beach_id] = payload
    return loaded