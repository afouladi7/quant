"""Descriptive statistics for benchmark samples (no claims of statistical certainty).

Percentiles use linear interpolation between closest ranks. p90 is reported only
with n >= 10, p95 with n >= 20 and p99 with n >= 100; below that they are None,
because a "p99" of 30 samples is just the maximum.
"""

from __future__ import annotations

import math
import statistics
from typing import Any


def percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        raise ValueError("empty sample")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def summarize(values: list[float], errors: int = 0, timeouts: int = 0) -> dict[str, Any]:
    total = len(values) + errors + timeouts
    out: dict[str, Any] = {
        "n": len(values), "attempted": total,
        "error_rate": (errors / total) if total else 0.0, "timeout_rate": (timeouts / total) if total else 0.0,
        "min": None, "max": None, "mean": None, "median": None, "stdev": None, "p25": None, "p75": None, "p90": None, "p95": None, "p99": None,
    }
    if not values:
        return out
    v = sorted(values)
    out.update(
        min=v[0], max=v[-1], mean=statistics.fmean(v), median=percentile(v, 0.5),
        stdev=statistics.stdev(v) if len(v) > 1 else 0.0, p25=percentile(v, 0.25), p75=percentile(v, 0.75),
    )
    if len(v) >= 10:
        out["p90"] = percentile(v, 0.90)
    if len(v) >= 20:
        out["p95"] = percentile(v, 0.95)
    if len(v) >= 100:
        out["p99"] = percentile(v, 0.99)
    return out
