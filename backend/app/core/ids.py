"""Server-generated identifiers.

Format: ``<PREFIX>-<6-digit sequence>-<4 hex chars>``, e.g. ``ORD-000042-7f3a``.
The sequence makes IDs human-scannable and ordered; the random suffix keeps IDs
from different process lifetimes (or resets) distinguishable.
"""

from __future__ import annotations

import itertools
import secrets
import threading


class IdGenerator:
    def __init__(self) -> None:
        self._counters: dict[str, itertools.count[int]] = {}
        self._lock = threading.Lock()

    def next(self, prefix: str) -> str:
        if not prefix.isalnum() or not prefix.isupper():
            raise ValueError(f"invalid id prefix: {prefix!r}")
        with self._lock:
            counter = self._counters.setdefault(prefix, itertools.count(1))
            n = next(counter)
        return f"{prefix}-{n:06d}-{secrets.token_hex(2)}"

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
