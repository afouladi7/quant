"""Risk & Returns Lab: simulated prices and the standard risk statistics, explained.

Prices follow geometric Brownian motion (the textbook "random walk" for stock prices):

    S(t+1) = S(t) · exp((μ − σ²/2)·Δt + σ·√Δt·Z),   Z ~ N(0, 1),  Δt = 1/252

Statistics use daily simple returns r_t = S_t / S_{t−1} − 1 and 252 trading days a year:

    annualised volatility = stdev(r) · √252
    annualised return     = (S_end / S_start)^(252 / days) − 1          (geometric)
    Sharpe ratio          = (mean(r) · 252 − risk-free) / annualised volatility
    max drawdown          = largest peak-to-trough fall of the price path
    historical VaR(c)     = −(1 − c) quantile of daily returns          (loss as a positive %)
    parametric VaR(c)     = −(mean(r) − z_c · stdev(r))                  (assumes normal returns)

Seeded, so the same inputs always give the same path.
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Any

from app.tcplab.stats import percentile

DAYS_PER_YEAR = 252
Z = {0.95: 1.6448536269514722, 0.99: 2.3263478740408408}


def simulate(start: float, mu: float, sigma: float, days: int, seed: int, risk_free: float, jumps: bool = False) -> dict[str, Any]:
    rng = random.Random(seed)
    dt = 1.0 / DAYS_PER_YEAR
    prices = [start]
    for _ in range(days):
        z = rng.gauss(0.0, 1.0)
        if jumps and rng.random() < 0.01:  # rare crash days to show fat tails
            z -= rng.uniform(4.0, 8.0)
        prices.append(prices[-1] * math.exp((mu - 0.5 * sigma * sigma) * dt + sigma * math.sqrt(dt) * z))
    rets = [prices[i] / prices[i - 1] - 1 for i in range(1, len(prices))]
    mean, sd = statistics.fmean(rets), statistics.stdev(rets)
    ann_vol = sd * math.sqrt(DAYS_PER_YEAR)
    ann_ret = (prices[-1] / prices[0]) ** (DAYS_PER_YEAR / days) - 1
    sharpe = (mean * DAYS_PER_YEAR - risk_free) / ann_vol if ann_vol else 0.0

    peak, mdd, peak_i, dd_start, dd_end = prices[0], 0.0, 0, 0, 0
    drawdown = []
    for i, p in enumerate(prices):
        if p > peak:
            peak, peak_i = p, i
        dd = p / peak - 1
        drawdown.append(dd)
        if dd < mdd:
            mdd, dd_start, dd_end = dd, peak_i, i

    srt = sorted(rets)
    var = {}
    for c in (0.95, 0.99):
        hist = -percentile(srt, 1 - c)
        param = -(mean - Z[c] * sd)
        tail = [r for r in rets if r <= -hist]
        var[str(c)] = {"historical": hist, "parametric": param, "expected_shortfall": -statistics.fmean(tail) if tail else hist}

    lo, hi = srt[0], srt[-1]
    nb = 30
    width = (hi - lo) / nb if hi > lo else 1.0
    bins = [{"from": lo + i * width, "to": lo + (i + 1) * width, "count": 0} for i in range(nb)]
    for r in rets:
        bins[min(nb - 1, int((r - lo) / width))]["count"] += 1
    normal_curve = [{"x": b["from"] + width / 2, "expected": len(rets) * width * math.exp(-0.5 * ((b["from"] + width / 2 - mean) / sd) ** 2) / (sd * math.sqrt(2 * math.pi))} for b in bins]

    skew = statistics.fmean([((r - mean) / sd) ** 3 for r in rets])
    kurt = statistics.fmean([((r - mean) / sd) ** 4 for r in rets]) - 3

    explain = [
        f"Over {days} trading days the price went from {start:.2f} to {prices[-1]:.2f}: a total return of {(prices[-1] / start - 1) * 100:+.1f}%, "
        f"or {ann_ret * 100:+.1f}% per year.",
        f"Daily moves had a standard deviation of {sd * 100:.2f}%. Scaled to a year (× √252) that is a volatility of {ann_vol * 100:.1f}% "
        f"(you set {sigma * 100:.0f}%; a finite sample never matches exactly).",
        f"Sharpe ratio {sharpe:.2f}: return earned above the {risk_free * 100:.1f}% risk-free rate per unit of volatility. "
        "Above 1 is generally considered good; it says nothing about rare crashes.",
        f"Max drawdown {mdd * 100:.1f}%: the worst fall from a previous high (day {dd_start} to day {dd_end}). "
        "This is the pain an investor would actually have felt.",
        f"95% one-day VaR: on 19 days out of 20 the loss should be smaller than {var['0.95']['historical'] * 100:.2f}% (from history) "
        f"or {var['0.95']['parametric'] * 100:.2f}% (bell-curve formula). Expected shortfall {var['0.95']['expected_shortfall'] * 100:.2f}% "
        "is the average loss on the bad days beyond that line.",
        f"Excess kurtosis {kurt:.2f}: 0 means bell-curve tails; positive means more extreme days than the normal distribution predicts"
        + (" (the crash days you switched on)." if jumps else "."),
    ]
    return {
        "inputs": {"start": start, "mu": mu, "sigma": sigma, "days": days, "seed": seed, "risk_free": risk_free, "jumps": jumps},
        "prices": prices, "returns": rets, "drawdown": drawdown,
        "stats": {
            "total_return": prices[-1] / start - 1, "annual_return": ann_ret, "annual_vol": ann_vol, "daily_mean": mean, "daily_stdev": sd,
            "sharpe": sharpe, "max_drawdown": mdd, "drawdown_start": dd_start, "drawdown_end": dd_end,
            "best_day": hi, "worst_day": lo, "up_days": sum(1 for r in rets if r > 0) / len(rets), "skew": skew, "excess_kurtosis": kurt,
        },
        "var": var,
        "histogram": bins,
        "normal_curve": normal_curve,
        "explain": explain,
    }


def two_assets(ret1: float, vol1: float, ret2: float, vol2: float, rho: float) -> dict[str, Any]:
    """Portfolio of two assets with weight w in asset 1: shows the diversification effect."""
    points = []
    for i in range(21):
        w = i / 20
        var = w * w * vol1 * vol1 + (1 - w) ** 2 * vol2 * vol2 + 2 * w * (1 - w) * rho * vol1 * vol2
        points.append({"w1": w, "ret": w * ret1 + (1 - w) * ret2, "vol": math.sqrt(max(var, 0.0)),
                       "naive_vol": w * vol1 + (1 - w) * vol2})
    denom = vol1 * vol1 + vol2 * vol2 - 2 * rho * vol1 * vol2
    w_min = (vol2 * vol2 - rho * vol1 * vol2) / denom if denom > 0 else 0.5
    w_min = min(1.0, max(0.0, w_min))
    vmin = math.sqrt(max(w_min ** 2 * vol1 ** 2 + (1 - w_min) ** 2 * vol2 ** 2 + 2 * w_min * (1 - w_min) * rho * vol1 * vol2, 0.0))
    half = points[10]
    explain = [
        f"With correlation {rho:+.2f}, a 50/50 mix has volatility {half['vol'] * 100:.1f}%, versus {half['naive_vol'] * 100:.1f}% "
        "if risks simply added up. The gap is the diversification benefit.",
        "Correlation +1: no benefit, risk is just the weighted average. Correlation 0: risk drops noticeably. "
        "Correlation −1: the right mix can cancel risk entirely.",
        f"The lowest-risk mix here puts {w_min * 100:.0f}% in asset 1, for a volatility of {vmin * 100:.1f}%.",
    ]
    return {"points": points, "min_variance": {"w1": w_min, "vol": vmin, "ret": w_min * ret1 + (1 - w_min) * ret2}, "explain": explain}
