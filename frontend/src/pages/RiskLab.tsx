import { useEffect, useState } from "react";
import { http } from "../api/client";
import { Histogram, LineChart } from "../components/charts";
import { StartHere, Term } from "../components/learn";
import { ErrorNote, Panel, Stat, TechOnly, useAction } from "../components/ui";

interface RiskInputs { start: number; mu: number; sigma: number; days: number; seed: number; risk_free: number; jumps: boolean }
interface RiskResult {
  prices: number[]; drawdown: number[];
  stats: Record<string, number>;
  var: Record<string, { historical: number; parametric: number; expected_shortfall: number }>;
  histogram: { from: number; to: number; count: number }[];
  normal_curve: { x: number; expected: number }[];
  explain: string[];
}
interface TwoInputs { ret1: number; vol1: number; ret2: number; vol2: number; rho: number }
interface TwoResult { points: { w1: number; ret: number; vol: number; naive_vol: number }[]; min_variance: { w1: number; vol: number; ret: number }; explain: string[] }

const pct = (v: number, d = 1) => `${(v * 100).toFixed(d)}%`;
const DEFAULT: RiskInputs = { start: 100, mu: 0.08, sigma: 0.2, days: 252, seed: 7, risk_free: 0.03, jumps: false };

export function RiskLab() {
  const [inp, setInp] = useState<RiskInputs>(DEFAULT);
  const [r, setR] = useState<RiskResult | null>(null);
  const { error, run } = useAction();
  useEffect(() => {
    const t = setTimeout(() => void run(async () => setR(await http.post<RiskResult>("/quant/risk/simulate", inp))), 150);
    return () => clearTimeout(t);
  }, [inp]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k: keyof RiskInputs, v: number | boolean) => setInp({ ...inp, [k]: v });

  return (
    <div className="page">
      <header>
        <h1>Risk & returns lab</h1>
        <p className="lead">
          How do professionals describe how risky an investment is? This lab simulates a stock price as a random walk, then
          measures it the way a risk manager would: <Term id="return">returns</Term>, <Term id="volatility">volatility</Term>,
          {" "}<Term id="drawdown">drawdown</Term>, <Term id="sharpe">Sharpe ratio</Term> and <Term id="var">Value at Risk</Term>.
        </p>
      </header>
      <StartHere steps={[
        "Look at the simulated year of prices and the statistics below.",
        "Click “New random path” a few times: same settings, very different outcomes. That is risk.",
        "Double the volatility and compare the drawdown and VaR.",
        "Turn on “crash days” and see how the bell curve underestimates bad days.",
      ]} />
      <ErrorNote error={error} />
      <div className="grid-2">
        <Panel title="Simulation settings" id="rk-in" help={<p>Prices follow geometric Brownian motion: each day's return is random, with the average (drift) and spread (volatility) you choose. A <Term id="seed">seed</Term> makes the randomness repeatable.</p>}>
          <Range label="Expected return per year" v={inp.mu} min={-0.3} max={0.3} step={0.01} on={(v) => set("mu", v)} />
          <Range label="Volatility per year" v={inp.sigma} min={0.05} max={0.8} step={0.01} on={(v) => set("sigma", v)} />
          <Range label="Risk-free rate" v={inp.risk_free} min={0} max={0.1} step={0.005} on={(v) => set("risk_free", v)} />
          <label className="slider"><span className="slider-label">Trading days <b>{inp.days}</b> (252 ≈ 1 year)</span>
            <input type="range" min={60} max={2520} step={21} value={inp.days} onChange={(e) => set("days", Number(e.target.value))} /></label>
          <div className="form-row">
            <label className="radio"><input type="checkbox" checked={inp.jumps} onChange={(e) => set("jumps", e.target.checked)} /><span>Add rare crash days (<Term id="fat_tails">fat tails</Term>)</span></label>
            <button type="button" className="btn" onClick={() => set("seed", inp.seed + 1)}>New random path</button>
            <button type="button" className="btn" onClick={() => setInp(DEFAULT)}>↺ Reset</button>
          </div>
          <TechOnly><p className="small mono">seed {inp.seed} · S(t+1) = S(t)·exp((μ − σ²/2)Δt + σ√Δt·Z), Δt = 1/252</p></TechOnly>
        </Panel>
        {r && (
          <Panel title="Results" id="rk-stats" help={<p>Each number summarises the path differently. Hover the underlined terms for definitions.</p>}>
            <div className="stats">
              <Stat label="Total return" value={pct(r.stats.total_return)} tone={r.stats.total_return} />
              <Stat label="Return per year" value={pct(r.stats.annual_return)} tone={r.stats.annual_return} />
              <Stat label="Volatility per year" value={pct(r.stats.annual_vol)} hint={`daily ${pct(r.stats.daily_stdev, 2)} × √252`} />
              <Stat label="Sharpe ratio" value={r.stats.sharpe.toFixed(2)} hint="return per unit of risk" />
              <Stat label="Max drawdown" value={pct(r.stats.max_drawdown)} tone={r.stats.max_drawdown} hint="worst fall from a high" />
              <Stat label="95% daily VaR" value={pct(r.var["0.95"].historical, 2)} hint={`bell curve says ${pct(r.var["0.95"].parametric, 2)}`} />
              <Stat label="99% daily VaR" value={pct(r.var["0.99"].historical, 2)} hint={`bell curve says ${pct(r.var["0.99"].parametric, 2)}`} />
              <Stat label="Expected shortfall (95%)" value={pct(r.var["0.95"].expected_shortfall, 2)} hint="average loss beyond VaR" />
              <Stat label="Worst / best day" value={`${pct(r.stats.worst_day, 1)} / ${pct(r.stats.best_day, 1)}`} />
              <Stat label="Days up" value={pct(r.stats.up_days, 0)} />
            </div>
            <TechOnly><p className="small mono">skew {r.stats.skew.toFixed(3)} · excess kurtosis {r.stats.excess_kurtosis.toFixed(3)} · mean daily {pct(r.stats.daily_mean, 3)}</p></TechOnly>
          </Panel>
        )}
      </div>
      {r && (
        <>
          <div className="grid-2">
            <Panel help={<p>One possible path for the price. Change the seed to see another equally likely one.</p>}>
              <LineChart title="Simulated price" xLabel="day" series={[{ key: "p", label: "Price", slot: 1, points: r.prices.map((p, i) => ({ x: i, y: p })) }]} yFormat={(v) => v.toFixed(0)} />
            </Panel>
            <Panel help={<p>How far below its previous high the price is on each day. The deepest point is the <Term id="drawdown">maximum drawdown</Term>.</p>}>
              <LineChart title="Drawdown from the previous high" xLabel="day" zeroLine series={[{ key: "dd", label: "Drawdown", slot: 2, points: r.drawdown.map((d, i) => ({ x: i, y: d * 100 })) }]} yFormat={(v) => `${v.toFixed(0)}%`} />
            </Panel>
          </div>
          <Panel help={<>
            <p>Each bar counts days whose return fell in that range. The line shows how many days a perfect bell curve would predict.</p>
            <p>The red line is 95% <Term id="var">VaR</Term>: about 1 day in 20 should fall to its left. With crash days on, the far-left tail has more days than the bell curve expects.</p>
          </>}>
            <Histogram
              title="Distribution of daily returns"
              bins={r.histogram.map((b) => ({ ...b, from: b.from * 100, to: b.to * 100 }))}
              curve={r.normal_curve.map((c) => ({ x: c.x * 100, y: c.expected }))}
              markers={[{ x: -r.var["0.95"].historical * 100, label: "95% VaR" }]}
              xFormat={(v) => `${v.toFixed(1)}%`}
            />
          </Panel>
          <Panel title="What this means, in plain English" id="rk-explain">
            <ul className="explain-list">{r.explain.map((e) => <li key={e}>{e}</li>)}</ul>
          </Panel>
        </>
      )}
      <Diversification />
    </div>
  );
}

function Range({ label, v, min, max, step, on }: { label: string; v: number; min: number; max: number; step: number; on: (v: number) => void }) {
  return (
    <label className="slider">
      <span className="slider-label">{label} <b>{pct(v, step < 0.01 ? 1 : 0)}</b></span>
      <input type="range" min={min} max={max} step={step} value={v} onChange={(e) => on(Number(e.target.value))} />
    </label>
  );
}

function Diversification() {
  const [inp, setInp] = useState<TwoInputs>({ ret1: 0.08, vol1: 0.2, ret2: 0.04, vol2: 0.1, rho: 0.2 });
  const [r, setR] = useState<TwoResult | null>(null);
  const { error, run } = useAction();
  useEffect(() => {
    const t = setTimeout(() => void run(async () => setR(await http.post<TwoResult>("/quant/risk/two-assets", inp))), 120);
    return () => clearTimeout(t);
  }, [inp]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Panel title="Diversification: mixing two investments" id="rk-div" help={<>
      <p>Asset 1 is riskier with a higher expected return (think: stocks); asset 2 is calmer (think: bonds). The chart shows the risk of every mix.</p>
      <p>If risks simply added up, the risk would follow the straight line labelled “If risks just added up”. Because the assets don't move perfectly together
        (<Term id="correlation">correlation</Term> below +1), the real risk curve bends below it: that is <Term id="diversification">diversification</Term>.</p>
    </>}>
      <div className="grid-2">
        <div>
          <label className="slider"><span className="slider-label"><Term id="correlation">Correlation</Term> <b>{inp.rho.toFixed(2)}</b></span>
            <input type="range" min={-1} max={1} step={0.05} value={inp.rho} onChange={(e) => setInp({ ...inp, rho: Number(e.target.value) })} /></label>
          <Range label="Asset 1 volatility" v={inp.vol1} min={0.05} max={0.5} step={0.01} on={(v) => setInp({ ...inp, vol1: v })} />
          <Range label="Asset 2 volatility" v={inp.vol2} min={0.05} max={0.5} step={0.01} on={(v) => setInp({ ...inp, vol2: v })} />
          {r && <ul className="explain-list">{r.explain.map((e) => <li key={e}>{e}</li>)}</ul>}
          <TechOnly><p className="small mono">σ_p² = w₁²σ₁² + w₂²σ₂² + 2·w₁·w₂·ρ·σ₁·σ₂</p></TechOnly>
        </div>
        {r && (
          <LineChart
            title="Portfolio risk by share of asset 1" xLabel="% in asset 1"
            series={[
              { key: "naive", label: "If risks just added up", slot: 2, points: r.points.map((p) => ({ x: Math.round(p.w1 * 100), y: p.naive_vol * 100 })) },
              { key: "vol", label: "Actual risk", slot: 1, points: r.points.map((p) => ({ x: Math.round(p.w1 * 100), y: p.vol * 100 })) },
            ]}
            yFormat={(v) => `${v.toFixed(1)}%`}
          />
        )}
      </div>
      <ErrorNote error={error} />
    </Panel>
  );
}
