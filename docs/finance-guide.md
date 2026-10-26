# Financial Education Guide

Everything in MarketLab is **hypothetical**: synthetic prices, simulated
customers, illustrative contracts. This guide explains the concepts, then states
exactly how the simulator models them, so you can check any number on screen.

---

## 1. Market makers, bid, ask and spread

A **market maker** continuously offers to trade both ways:

- the **bid** is the price at which it will *buy* from you;
- the **ask** (or offer) is the price at which it will *sell* to you;
- the **spread** is ask − bid.

In MarketLab's default state, the market maker quotes **$99.95 bid / $100.05
ask** for the fictional MARKETLAB-100 (fair value $100.00), a $0.10 spread.

> "The market maker is willing to buy at $99.95 and sell at $100.05. If it buys at
> the bid and later sells at the ask, it may capture a $0.10 spread per share
> before fees and changes in market value."

**Capturing the spread is not a guaranteed profit.** Between buying and
selling, the market can move. Preset 1 (*Spread Capture*) shows a round trip
earning $10 gross / $9 net, then a $0.30 price drop turning the position into a
loss.

## 2. Liquidity and the order book

**Liquidity** is how much you can trade, and at what prices, without moving the
price much. An **order book** lists resting buy orders (bids) from the highest
price down and resting sell orders (asks) from the lowest price up. Each **price
level** shows the total quantity waiting there.

**Price-time priority** decides who trades first: a better price always wins;
at the same price, the order that arrived first wins.

## 3. Market and limit orders, partial fills

- A **market order** trades immediately against whatever liquidity exists, best
  price first. It may "walk the book" to worse prices if the best level is too
  small.
- A **limit order** sets a worst acceptable price. It **never** executes at a
  worse price. Whatever cannot trade immediately can **rest** in the book.
- A **partial fill** means only part of an order traded.

MarketLab execution rules:

| Order | Time in force | Unfilled remainder |
|---|---|---|
| Market | IOC (default) | canceled immediately ("immediate or cancel") |
| Market | FOK | the whole order is rejected unless it can fill completely |
| Limit | GTC (default) | rests in the book until filled or canceled |
| Limit | IOC / FOK | as above, never rests |

Self-trade prevention: if an incoming order would trade against a resting order
of the *same owner*, the resting order is canceled instead.

## 4. Inventory and why it is risky

**Inventory** is the market maker's position: positive (long) after buying,
negative (short) after selling more than it bought. While it holds inventory,
price moves change its wealth. MarketLab's market maker therefore **skews** its
quotes:

```
utilization u = clamp(inventory / max_inventory, −1, 1)
skew          = −inventory_sensitivity × u × spread
reservation   = fair_value + skew
bid           = round_down(reservation − spread/2)   (to the tick)
ask           = round_up  (reservation + spread/2)
```

When long, both quotes move **down**: its ask becomes cheaper (helping it
sell) and its bid less attractive (discouraging more buying). When short, both
move **up**. At ±`max_inventory` it stops quoting the side that would increase
risk. Preset 2 (*Inventory Risk*) shows this. This is a teaching model, not an
optimal or profitable strategy.

## 5. Cash, P&L and the accounting convention

MarketLab uses exact decimal arithmetic and **FIFO lots**:

- A buy of *q* at *p*: cash −= *q·p*, inventory += *q* (a new lot, or closing
  short lots first).
- A sell: cash += *q·p*, inventory −= *q*.
- Fees are paid in cash and accumulated separately.
- **Realized P&L**: when a trade reduces a position, the oldest open lots are
  closed first: long lots give (sell price − lot price) × *q*; short lots give
  (lot price − buy price) × *q*.
- **Unrealized P&L** marks every open lot to the current **fair value**:
  Σ lot_qty × (mark − lot price).
- **Net (mark-to-market) P&L** = realized + unrealized − fees.
- **Gross spread captured** = Σ (fair − price) × signed qty at the moment of each
  fill: the edge versus fair value. It is *not* profit.

The simulator's tests verify this identity on every run:

```
cash + inventory × mark − initial_cash  ==  realized + unrealized − fees
```

## 6. Foreign exchange pairs

A pair **BASE/QUOTE** is priced in QUOTE per 1 BASE. **GBP/USD 1.27000** means
£1 costs $1.27. Buying GBP/USD means buying pounds and paying dollars.
A **pip** is 0.0001 for USD-quoted pairs (0.01 for JPY-quoted); MarketLab prices
in tenths of a pip. Quantities are in base-currency units.

## 7. Fragmented liquidity and order routing

The same currency trades on several venues. MarketLab has three independent
books with hypothetical profiles:

| Book | Profile (default) |
|---|---|
| A | tightest spread (0.6 pip) but only 200,000 per level |
| B | 1.0 pip spread, 1,000,000 per level |
| C | 0.7 pip spread, lowest fee, but 45 ms simulated latency |

The **smart router** ranks every price level on every book by *effective
price*:

```
effective = price × (1 ± (fee_bps + latency_penalty_bps_per_100ms × latency_ms/100) / 10,000)
            (+ for buys, − for sells)
```

and fills from the best effective price until the order is complete. A large
order therefore becomes several **child orders** across books. The parent's
filled quantity is the sum of its children and its **weighted-average price**
(VWAP) is Σ(price × qty) / Σ qty. The latency penalty is a modelling choice: a
proxy for the risk the price moves while a slow order travels. Execution in the
simulator is instantaneous; latency is recorded, not slept.

## 8. Currency exposure

**Exposure** is how much a portfolio's value (in USD) changes when a currency
moves. A fund holding £1,000,000 at 1.27 has £1m of GBP exposure (≈ $1.27m) and
gains about $12,700 if GBP rises 1%.

MarketLab keeps these separate: **cash balances** per currency; **exposure** =
spot balances + futures-equivalent amounts; **derivative positions** (futures
contracts, never added to cash); **P&L** = equity − initial equity, with equity
valued in USD at current mid rates.

## 9. Hedging

**Hedging** takes an offsetting position so gains and losses cancel. A fund long
£1m can:

- **Offset FX trade**: sell £1m against USD. GBP cash returns to zero, so
  exposure is gone, and so is any upside. Costs: spread and fees.
- **Futures**: sell GBP futures. GBP cash is unchanged, but the short future
  gains when GBP falls and loses when it rises.

## 10. Futures (as modelled)

The GBP future is **illustrative**; real contracts differ by exchange.

- Contract size 62,500 GBP; price in USD per GBP; tick 0.0001 = $6.25.
- Futures price **F = spot + basis**. Basis starts at 12 pips and shrinks
  linearly to 0 at expiry (convergence).
- Contracts needed = exposure / contract size, **rounded** to whole contracts;
  the remainder is **residual exposure** (e.g. £1,030,000 → 16 contracts →
  £30,000 unhedged).
- P&L = (F_now − F_entry) × contracts × contract size, credited in USD.
- Margin is *reported* (initial $3,000, maintenance $2,700 per contract) but not
  moved; daily variation-margin cycles are not simulated. At expiry the position
  is cash-settled at spot.

## 11. Basis risk and other residual risks

A hedge reduces specific risks; it does not guarantee a profit or remove all
risk. The *Risk scenarios* table quantifies:

- **Basis risk**: futures and spot do not move identically (e.g. spot +1%,
  future +0.8%).
- **Partial fills**: an unfilled hedge leaves exposure.
- **Rounding**: whole contracts and lots leave residuals.
- **Expiry**: at expiry the hedge disappears unless rolled; the basis converges.
- **Volatility**: 1-day 95% VaR = 1.645 × σ_daily × |exposure in USD|, with an
  illustrative 8% annual volatility; doubling volatility doubles VaR for any
  exposure that remains.

## 12. Returns, volatility and risk statistics (Risk & returns lab)

Prices are simulated with geometric Brownian motion, S(t+1) = S(t)·exp((μ − σ²/2)Δt + σ√Δt·Z), Δt = 1/252, seeded.

- **Daily return** r = S_t / S_(t−1) − 1. **Annual volatility** = stdev(r) × √252.
- **Annual return** (geometric) = (S_end / S_start)^(252/days) − 1.
- **Sharpe ratio** = (mean(r) × 252 − risk-free) / annual volatility.
- **Max drawdown**: the worst fall from a running peak.
- **VaR(c)**: historical = the (1 − c) quantile of daily returns, as a loss; parametric = −(mean − z_c × stdev),
  with z₉₅ = 1.645 and z₉₉ = 2.326. **Expected shortfall** = the average loss on days worse than VaR.
- **Fat tails**: the optional crash days make extreme losses more frequent than a normal distribution predicts;
  excess kurtosis rises and the bell-curve VaR becomes too optimistic.
- **Diversification**: σ_p² = w₁²σ₁² + w₂²σ₂² + 2w₁w₂ρσ₁σ₂. With ρ < 1, portfolio risk is below the weighted average;
  with ρ = −1 a mix exists with zero risk.

## 13. Options (Options lab)

- A **call** is the right to buy at the strike K; a **put**, the right to sell. Payoff at expiry: max(S − K, 0) and
  max(K − S, 0). Premium = intrinsic value + time value.
- **Black-Scholes(-Merton)** with dividend yield q: d1 = [ln(S/K) + (r − q + σ²/2)T]/(σ√T), d2 = d1 − σ√T,
  C = S·e^(−qT)·N(d1) − K·e^(−rT)·N(d2), P = K·e^(−rT)·N(−d2) − S·e^(−qT)·N(−d1). T = days/365.
- **Greeks** (as displayed): delta ∂V/∂S; gamma ∂²V/∂S²; vega per 1 volatility point; theta per calendar day;
  rho per 1 percentage point of rates. Verified in tests against finite differences.
- **Put-call parity**: C − P = S·e^(−qT) − K·e^(−rT).
- **Implied volatility**: the σ that reproduces a given price (bisection between 0.01% and 500%).
- **Binomial tree** (Cox-Ross-Rubinstein): converges to Black-Scholes as steps increase; with early exercise it
  prices American options.
- N(d2) is a *risk-neutral* probability of finishing in the money, not a forecast. The model assumes constant
  volatility and rates and no trading costs.

## 14. What MarketLab deliberately leaves out

Real exchange rules and auctions, market impact beyond book depth, financing and
interest carry (beyond the modelled basis), clearing and settlement cycles,
collateral and margin calls, counterparty risk, regulatory and institutional
controls, multi-asset portfolio risk, and tax. None of the strategies shown are
recommendations.
