"""Idempotency-key store so a retried request cannot create a duplicate order.

Same key + same request body  -> the original response is returned again.
Same key + different body     -> conflict (HTTP 409).
Bounded LRU; keys are scoped by the caller (e.g. "mm:orders").
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from typing import Any


class IdempotencyConflict(Exception):
    pass


def fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


class IdempotencyStore:
    def __init__(self, capacity: int = 2000) -> None:
        self._items: OrderedDict[str, tuple[str, Any]] = OrderedDict()
        self._capacity = capacity

    def lookup(self, scope: str, key: str, fp: str) -> Any | None:
        item = self._items.get(f"{scope}:{key}")
        if item is None:
            return None
        if item[0] != fp:
            raise IdempotencyConflict(f"Idempotency-Key '{key}' was already used with a different request body.")
        self._items.move_to_end(f"{scope}:{key}")
        return item[1]

    def store(self, scope: str, key: str, fp: str, response: Any) -> None:
        self._items[f"{scope}:{key}"] = (fp, response)
        while len(self._items) > self._capacity:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()
