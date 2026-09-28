"""Tiny in-process TTL cache for read endpoints.

The dashboard polls every minute; caching keeps DB work bounded no matter how
many browsers are open. Source APIs are never called from request handlers.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

_store: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def cached(key: str, ttl_seconds: float, compute: Callable[[], Any]) -> Any:
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if hit and now - hit[0] < ttl_seconds:
            return hit[1]
    value = compute()
    with _lock:
        _store[key] = (now, value)
    return value


def clear() -> None:
    with _lock:
        _store.clear()
