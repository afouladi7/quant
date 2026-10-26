"""Time sources.

Wall-clock timestamps (UTC) are for display and audit; the monotonic
nanosecond clock is for ordering and latency measurement (never goes backwards).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def mono_ns() -> int:
    return time.monotonic_ns()
