"""Explicitly defined server work used by the TCP lab.

*Preparation* (may overlap with communication in early-work mode): validate the
header and hash the received prefix repeatedly for ``ms`` milliseconds — standing in
for parsing, risk checks or pre-allocating state.
*Processing* (only after the full message): hash the complete message repeatedly
for ``ms`` milliseconds, then "commit".

The work runs in a worker thread so the event loop keeps receiving bytes meanwhile.
"""

from __future__ import annotations

import asyncio
import hashlib
import time


def _burn(data: bytes, ms: int) -> tuple[int, int, str]:
    start = time.monotonic_ns()
    deadline = start + ms * 1_000_000
    digest = hashlib.sha256(data).digest()
    while time.monotonic_ns() < deadline:
        digest = hashlib.sha256(digest + data[:64]).digest()
    return start, time.monotonic_ns(), digest.hex()[:16]


async def do_work(data: bytes, ms: int) -> tuple[int, int, str]:
    if ms <= 0:
        now = time.monotonic_ns()
        return now, now, hashlib.sha256(data).hexdigest()[:16]
    return await asyncio.to_thread(_burn, data, ms)
