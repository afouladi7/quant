"""European option pricing for the Options Lab (a teaching tool, not a trading model).

Black-Scholes(-Merton) with a continuous dividend/carry yield q:

    d1 = [ln(S/K) + (r − q + σ²/2)·T] / (σ·√T)
    d2 = d1 − σ·√T
    call = S·e^(−qT)·N(d1) − K·e^(−rT)·N(d2)
    put  = K·e^(−rT)·N(−d2) − S·e^(−qT)·N(−d1)

Greeks are reported in trader-friendly units: vega per 1 volatility point,
theta per calendar day, rho per 1 percentage point of interest rate.
A Cox-Ross-Rubinstein binomial tree prices the same option step by step and
converges to Black-Scholes as the number of steps grows (and can price American
early exercise). Floating point is fine here: this is model math, not accounting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Kind = Literal["call", "put"]
SQRT2 = math.sqrt(2.0)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / SQRT2))


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


@dataclass(frozen=True)
class OptionInput:
    spot: float
    strike: float
    days: float
    rate: float  # annual, continuous, decimal (0.05 = 5%)
    vol: float  # annual, decimal (0.20 = 20%)
    kind: Kind = "call"
    dividend_yield: float = 0.0

    @property
    def t(self) -> float:
        return self.days / 365.0


def black_scholes(o: OptionInput) -> dict[str, float]:
    S, K, T, r, sig, q = o.spot, o.strike, o.t, o.rate, o.vol, o.dividend_yield
    sqrt_t = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sig * sig) * T) / (sig * sqrt_t)
    d2 = d1 - sig * sqrt_t
    disc_r, disc_q = math.exp(-r * T), math.exp(-q * T)
    if o.kind == "call":
        price = S * disc_q * norm_cdf(d1) - K * disc_r * norm_cdf(d2)
        delta = disc_q * norm_cdf(d1)
        theta_y = (-S * disc_q * norm_pdf(d1) * sig / (2 * sqrt_t) - r * K * disc_r * norm_cdf(d2) + q * S * disc_q * norm_cdf(d1))
        rho = K * T * disc_r * norm_cdf(d2)
        intrinsic = max(S - K, 0.0)
    else:
        price = K * disc_r * norm_cdf(-d2) - S * disc_q * norm_cdf(-d1)
        delta = -disc_q * norm_cdf(-d1)
        theta_y = (-S * disc_q * norm_pdf(d1) * sig / (2 * sqrt_t) + r * K * disc_r * norm_cdf(-d2) - q * S * disc_q * norm_cdf(-d1))
        rho = -K * T * disc_r * norm_cdf(-d2)
        intrinsic = max(K - S, 0.0)
    gamma = disc_q * norm_pdf(d1) / (S * sig * sqrt_t)
    vega = S * disc_q * norm_pdf(d1) * sqrt_t
    return {
        "price": price, "d1": d1, "d2": d2, "n_d1": norm_cdf(d1), "n_d2": norm_cdf(d2),
        "delta": delta, "gamma": gamma, "vega": vega / 100.0, "theta": theta_y / 365.0, "rho": rho / 100.0,
        "intrinsic": intrinsic, "time_value": price - intrinsic,
        "prob_itm": norm_cdf(d2) if o.kind == "call" else norm_cdf(-d2),
    }


def binomial(o: OptionInput, steps: int, american: bool = False) -> float:
    """Cox-Ross-Rubinstein tree."""
    dt = o.t / steps
    u = math.exp(o.vol * math.sqrt(dt))
    d = 1.0 / u
    disc = math.exp(-o.rate * dt)
    p = (math.exp((o.rate - o.dividend_yield) * dt) - d) / (u - d)
    sign = 1.0 if o.kind == "call" else -1.0
    values = [max(sign * (o.spot * u ** j * d ** (steps - j) - o.strike), 0.0) for j in range(steps + 1)]
    for i in range(steps - 1, -1, -1):
        for j in range(i + 1):
            cont = disc * (p * values[j + 1] + (1 - p) * values[j])
            if american:
                cont = max(cont, sign * (o.spot * u ** j * d ** (i - j) - o.strike))
            values[j] = cont
    return values[0]


def implied_vol(target: float, o: OptionInput) -> float | None:
    """Volatility that makes Black-Scholes equal ``target`` (bisection; None if out of range)."""
    lo, hi = 1e-4, 5.0
    f = lambda v: black_scholes(OptionInput(o.spot, o.strike, o.days, o.rate, v, o.kind, o.dividend_yield))["price"] - target  # noqa: E731
    if f(lo) > 0 or f(hi) < 0:
        return None
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-7:
            break
    return 0.5 * (lo + hi)


def moneyness(o: OptionInput) -> str:
    ratio = o.spot / o.strike
    if abs(ratio - 1) < 0.02:
        return "at the money"
    itm = ratio > 1 if o.kind == "call" else ratio < 1
    return "in the money" if itm else "out of the money"


def analyse(o: OptionInput) -> dict:
    bs = black_scholes(o)
    other = black_scholes(OptionInput(o.spot, o.strike, o.days, o.rate, o.vol, "put" if o.kind == "call" else "call", o.dividend_yield))
    call, put = (bs["price"], other["price"]) if o.kind == "call" else (other["price"], bs["price"])
    parity_rhs = o.spot * math.exp(-o.dividend_yield * o.t) - o.strike * math.exp(-o.rate * o.t)

    grid = [o.spot * (0.5 + i * 0.025) for i in range(41)]
    curve = []
    for s in grid:
        v = black_scholes(OptionInput(s, o.strike, o.days, o.rate, o.vol, o.kind, o.dividend_yield))["price"]
        payoff = max(s - o.strike, 0.0) if o.kind == "call" else max(o.strike - s, 0.0)
        curve.append({"spot": s, "value_today": v, "payoff_at_expiry": payoff, "profit_at_expiry": payoff - bs["price"]})
    decay = []
    for days_left in sorted({max(1, int(o.days * f)) for f in (1, 0.9, 0.75, 0.6, 0.5, 0.4, 0.3, 0.2, 0.15, 0.1, 0.05)} | {1}, reverse=True):
        decay.append({"days": days_left, "value": black_scholes(OptionInput(o.spot, o.strike, days_left, o.rate, o.vol, o.kind, o.dividend_yield))["price"]})
    convergence = [{"steps": n, "price": binomial(o, n)} for n in (1, 2, 3, 5, 10, 25, 50, 100, 200)]
    american = binomial(o, 200, american=True)
    breakeven = o.strike + bs["price"] if o.kind == "call" else o.strike - bs["price"]

    explain = [
        f"This {o.kind} is {moneyness(o)}: the stock is at {o.spot:.2f} and the strike is {o.strike:.2f}.",
        f"Its model price is {bs['price']:.2f} = intrinsic value {bs['intrinsic']:.2f} (what it is worth if exercised now) "
        f"+ time value {bs['time_value']:.2f} (the chance it becomes more valuable before expiry).",
        f"Delta {bs['delta']:+.3f}: if the stock rises by 1.00, the option's value changes by about {bs['delta']:+.3f}.",
        f"Gamma {bs['gamma']:.4f}: how fast delta itself changes when the stock moves by 1.00.",
        f"Vega {bs['vega']:.3f}: value change if volatility rises by 1 percentage point (e.g. {o.vol * 100:.0f}% → {o.vol * 100 + 1:.0f}%).",
        f"Theta {bs['theta']:.3f}: value lost per day just from time passing, all else equal.",
        f"Rho {bs['rho']:+.3f}: value change if interest rates rise by 1 percentage point.",
        f"At expiry the buyer breaks even if the stock is {'above' if o.kind == 'call' else 'below'} {breakeven:.2f} (strike {'+' if o.kind == 'call' else '−'} premium).",
        f"Under the model's assumptions, the chance of finishing in the money is about {bs['prob_itm'] * 100:.0f}% (N(d2) is a risk-neutral probability, not a forecast).",
    ]
    return {
        "input": o.__dict__ | {"t_years": o.t},
        "result": bs,
        "moneyness": moneyness(o),
        "breakeven": breakeven,
        "parity": {"call": call, "put": put, "call_minus_put": call - put, "s_minus_pv_k": parity_rhs,
                   "holds": abs((call - put) - parity_rhs) < 1e-9 * max(1.0, o.spot)},
        "binomial": {"convergence": convergence, "american_200_steps": american,
                     "early_exercise_premium": american - convergence[-1]["price"]},
        "curve": curve,
        "time_decay": decay,
        "explain": explain,
    }
