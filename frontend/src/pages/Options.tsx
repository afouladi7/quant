import { useEffect, useState } from "react";
import { ApiError, http } from "../api/client";
import { LineChart } from "../components/charts";
import { StartHere, Term } from "../components/learn";
import { ErrorNote, Panel, SimpleOnly, Stat, TechOnly, useAction } from "../components/ui";

interface Inputs { spot: number; strike: number; days: number; rate: number; vol: number; kind: "call" | "put"; dividend_yield: number }
interface Analysis {
  input: Inputs & { t_years: number };
  result: { price: number; d1: number; d2: number; n_d1: number; n_d2: number; delta: number; gamma: number; vega: number; theta: number; rho: number; intrinsic: number; time_value: number; prob_itm: number };
  moneyness: string; breakeven: number;
  parity: { call: number; put: number; call_minus_put: number; s_minus_pv_k: number; holds: boolean };
  binomial: { convergence: { steps: number; price: number }[]; american_200_steps: number; early_exercise_premium: number };
  curve: { spot: number; value_today: number; payoff_at_expiry: number; profit_at_expiry: number }[];
  time_decay: { days: number; value: number }[];
  explain: string[];
}

const DEFAULT: Inputs = { spot: 100, strike: 100, days: 30, rate: 0.04, vol: 0.2, kind: "call", dividend_yield: 0 };
const f2 = (v: number) => v.toFixed(2);

export function Options() {
  const [inp, setInp] = useState<Inputs>(DEFAULT);
  const [a, setA] = useState<Analysis | null>(null);
  const { error, run } = useAction();
  useEffect(() => {
    const t = setTimeout(() => void run(async () => setA(await http.post<Analysis>("/quant/options/price", inp))), 150);
    return () => clearTimeout(t);
  }, [inp]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k: keyof Inputs, v: number | string) => setInp({ ...inp, [k]: v });

  return (
    <div className="page">
      <header>
        <h1>Options lab</h1>
        <p className="lead">
          An <Term id="option">option</Term> is the right, but not the obligation, to buy (<Term id="call">call</Term>) or sell
          (<Term id="put">put</Term>) a stock at a fixed price, the <Term id="strike">strike</Term>, until an expiry date.
          Move the sliders and watch the price and its sensitivities, the <Term id="greeks">Greeks</Term>, change.
        </p>
      </header>
      <StartHere steps={[
        "Start with the defaults: a 30-day call, stock and strike both at 100.",
        "Drag the stock price up: the call gains value (delta tells you how fast).",
        "Raise volatility: every option becomes more valuable, because bigger moves help the holder.",
        "Shorten the days to expiry: the time value melts away (theta).",
      ]} />
      <ErrorNote error={error} />
      <div className="grid-2">
        <Panel title="Inputs" id="opt-in" help={<p>These are the five Black-Scholes inputs plus the option type. Volatility is the only one you cannot look up; it is a forecast of how much the stock will move.</p>}>
          <div className="segmented" role="group" aria-label="Option type">
            <button type="button" aria-pressed={inp.kind === "call"} onClick={() => set("kind", "call")}>Call (right to buy)</button>
            <button type="button" aria-pressed={inp.kind === "put"} onClick={() => set("kind", "put")}>Put (right to sell)</button>
          </div>
          <Slider label="Stock price" value={inp.spot} min={50} max={150} step={1} onChange={(v) => set("spot", v)} />
          <Slider label="Strike price" value={inp.strike} min={50} max={150} step={1} onChange={(v) => set("strike", v)} />
          <Slider label="Days to expiry" value={inp.days} min={1} max={365} step={1} onChange={(v) => set("days", v)} />
          <Slider label="Volatility" value={inp.vol} min={0.05} max={1} step={0.01} pct onChange={(v) => set("vol", v)} term="volatility" />
          <Slider label="Interest rate" value={inp.rate} min={0} max={0.1} step={0.0025} pct onChange={(v) => set("rate", v)} />
          <TechOnly><Slider label="Dividend yield" value={inp.dividend_yield} min={0} max={0.1} step={0.0025} pct onChange={(v) => set("dividend_yield", v)} /></TechOnly>
          <button type="button" className="btn" onClick={() => setInp(DEFAULT)}>↺ Reset inputs</button>
        </Panel>
        {a && (
          <Panel title="Price" id="opt-price" help={<p>The model price splits into <Term id="intrinsic">intrinsic value</Term> (worth if used now) and <Term id="time_value">time value</Term> (the chance it gets better before expiry).</p>}>
            <div className="hero-figure">{f2(a.result.price)}</div>
            <p className="small muted">Model price of the {inp.kind} ({a.moneyness})</p>
            <div className="stats">
              <Stat label="Intrinsic value" value={f2(a.result.intrinsic)} hint="worth if exercised now" />
              <Stat label="Time value" value={f2(a.result.time_value)} hint="price − intrinsic" />
              <Stat label="Breakeven at expiry" value={f2(a.breakeven)} hint={inp.kind === "call" ? "strike + premium" : "strike − premium"} />
              <Stat label="Chance of finishing in the money" value={`${(a.result.prob_itm * 100).toFixed(0)}%`} hint="model probability, not a forecast" />
            </div>
          </Panel>
        )}
      </div>
      {a && (
        <>
          <Panel title="The Greeks: how the price reacts" id="opt-greeks" help={<p>Each Greek answers “if this one thing changes a little, how much does the option price change?”. Traders use them to understand and hedge risk.</p>}>
            <div className="greeks">
              <Greek id="delta" name="Delta" value={a.result.delta.toFixed(3)} text={`Stock +1.00 → option ${a.result.delta >= 0 ? "+" : ""}${a.result.delta.toFixed(2)}`} />
              <Greek id="gamma" name="Gamma" value={a.result.gamma.toFixed(4)} text="How quickly delta itself changes" />
              <Greek id="vega" name="Vega" value={a.result.vega.toFixed(3)} text={`Volatility +1 point → option +${a.result.vega.toFixed(2)}`} />
              <Greek id="theta" name="Theta" value={a.result.theta.toFixed(3)} text={`One day passes → option ${a.result.theta.toFixed(2)}`} />
              <Greek id="greeks" name="Rho" value={a.result.rho.toFixed(3)} text={`Interest rate +1% → option ${a.result.rho >= 0 ? "+" : ""}${a.result.rho.toFixed(2)}`} />
            </div>
          </Panel>
          <div className="grid-2">
            <Panel help={<p>The flat-then-rising line is what the option pays at expiry. The curve is what it is worth today: always above the payoff line for a call, because there is still time for things to improve.</p>}>
              <LineChart
                title="Value today vs. payoff at expiry" xLabel="stock price" endLabels={false}
                series={[
                  { key: "today", label: "Value today", slot: 1, points: a.curve.map((c) => ({ x: Math.round(c.spot * 100) / 100, y: c.value_today })) },
                  { key: "expiry", label: "Payoff at expiry", slot: 2, points: a.curve.map((c) => ({ x: Math.round(c.spot * 100) / 100, y: c.payoff_at_expiry })) },
                ]}
                yFormat={(v) => v.toFixed(1)}
              />
            </Panel>
            <Panel help={<p>Holding everything else constant, the option loses value as expiry approaches. The loss speeds up near the end: that is theta.</p>}>
              <LineChart
                title="Time decay: value as expiry approaches" xLabel="days to expiry"
                series={[{ key: "v", label: "Option value", slot: 1, points: [...a.time_decay].reverse().map((d) => ({ x: d.days, y: d.value })) }]}
                yFormat={(v) => v.toFixed(2)}
              />
            </Panel>
          </div>
          <Panel title="What this means, in plain English" id="opt-explain">
            <ul className="explain-list">{a.explain.map((e) => <li key={e}>{e}</li>)}</ul>
          </Panel>
          <div className="grid-2">
            <ImpliedVol inp={inp} />
            <Panel title="Under the hood" id="opt-tech" help={<p>The formula's intermediate values, a consistency check (put-call parity), and a second method (a binomial tree) that should agree.</p>}>
              <SimpleOnly><p className="small muted">Switch to Technical view (top right) for d1, d2, put-call parity and the binomial tree.</p></SimpleOnly>
              <TechOnly>
                <pre className="formula">{`d1 = [ln(S/K) + (r − q + σ²/2)·T] / (σ·√T) = ${a.result.d1.toFixed(4)}
d2 = d1 − σ·√T = ${a.result.d2.toFixed(4)}
N(d1) = ${a.result.n_d1.toFixed(4)}   N(d2) = ${a.result.n_d2.toFixed(4)}   T = ${a.input.t_years.toFixed(4)} years`}</pre>
                <p className="small"><b>Put-call parity</b>: C − P = S·e^(−qT) − K·e^(−rT) → {a.parity.call_minus_put.toFixed(4)} vs {a.parity.s_minus_pv_k.toFixed(4)} {a.parity.holds ? "✓ holds" : "✕"}</p>
                <table className="table compact">
                  <caption className="small muted">Binomial tree (Cox-Ross-Rubinstein) converging to Black-Scholes {f2(a.result.price)}</caption>
                  <thead><tr><th className="num">Steps</th><th className="num">Tree price</th><th className="num">Difference</th></tr></thead>
                  <tbody>{a.binomial.convergence.map((c) => <tr key={c.steps}><td className="num">{c.steps}</td><td className="num">{c.price.toFixed(4)}</td><td className="num">{(c.price - a.result.price).toFixed(4)}</td></tr>)}</tbody>
                </table>
                <p className="small">American (early exercise allowed), 200 steps: {a.binomial.american_200_steps.toFixed(4)} · early-exercise premium {a.binomial.early_exercise_premium.toFixed(4)}</p>
              </TechOnly>
            </Panel>
          </div>
          <p className="small muted">Black-Scholes assumes constant volatility and interest rates, no transaction costs, and log-normally distributed prices. Real options are priced by markets, not formulas; this is a model for learning.</p>
        </>
      )}
    </div>
  );
}

function Slider({ label, value, min, max, step, onChange, pct, term }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; pct?: boolean; term?: string }) {
  const shown = pct ? `${(value * 100).toFixed(step < 0.01 ? 2 : 0)}%` : String(value);
  return (
    <label className="slider">
      <span className="slider-label">{term ? <Term id={term}>{label}</Term> : label} <b>{shown}</b></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function Greek({ id, name, value, text }: { id: string; name: string; value: string; text: string }) {
  return (
    <div className="stat">
      <div className="stat-label"><Term id={id}>{name}</Term></div>
      <div className="stat-value">{value}</div>
      <div className="stat-hint">{text}</div>
    </div>
  );
}

function ImpliedVol({ inp }: { inp: Inputs }) {
  const [price, setPrice] = useState("3.00");
  const [res, setRes] = useState<{ implied_vol: number } | null>(null);
  const { busy, error, run, setError } = useAction();
  return (
    <Panel title="Implied volatility" id="opt-iv" help={<p>Markets quote option prices, not volatility. <Term id="implied_vol">Implied volatility</Term> is the volatility that makes the formula match a given price: the market's estimate of future movement.</p>}>
      <p className="small">If this {inp.kind} trades at a given price, what volatility does that imply (using the other inputs above)?</p>
      <div className="form-row">
        <label>Market price<input type="number" step="0.01" min="0.01" value={price} onChange={(e) => setPrice(e.target.value)} /></label>
        <button type="button" className="btn primary" disabled={busy} onClick={() => run(async () => {
          setRes(null);
          try {
            setRes(await http.post<{ implied_vol: number }>("/quant/options/implied-vol", { ...inp, market_price: Number(price) }));
          } catch (e) {
            if (e instanceof ApiError) setError(e.message); else throw e;
          }
        })}>Solve</button>
      </div>
      {res && <p className="observe">Implied volatility: <b>{(res.implied_vol * 100).toFixed(2)}%</b> per year.</p>}
      <ErrorNote error={error} />
    </Panel>
  );
}
