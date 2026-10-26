import { useState, type FormEvent } from "react";
import { pfApi, type HedgeRequest, type HedgeRule, type Portfolio, type Proposal, type Risk } from "../api/fx";
import { LineChart } from "../components/charts";
import { EventTimeline } from "../components/EventTimeline";
import { ErrorNote, Explain, JsonBlock, Loading, Panel, SimpleOnly, Stat, StatusBadge, TechOnly, useAction } from "../components/ui";
import { fmtMoney, fmtNum, fmtSignedMoney, shortTime } from "../lib/format";
import { useLive } from "../lib/useLive";

const GUIDED = [
  "The fund buys GBP 1,000,000 against USD",
  "GBP/USD moves",
  "Calculate the hedge",
  "Execute the hedge",
  "Compare: GBP/USD moves again",
];

export function Hedging() {
  const pf = useLive(pfApi.state, ["fx", "portfolio"], 1000);
  const risk = useLive(pfApi.risk, ["fx", "portfolio"], 1500);
  const refresh = () => { void pf.refresh(); void risk.refresh(); };
  if (pf.loading && !pf.data) return <Loading what="portfolio" />;
  if (!pf.data) return <ErrorNote error={pf.error ?? "Portfolio unavailable"} />;
  const s = pf.data;
  return (
    <>
      <ErrorNote error={pf.error} />
      <Guided s={s} onChange={refresh} />
      <Summary s={s} />
      <div className="grid-2">
        <Exposure s={s} />
        <HedgePanel s={s} onChange={refresh} />
      </div>
      {risk.data && <RiskTable r={risk.data} />}
      <div className="grid-2">
        <Futures s={s} onChange={refresh} />
        <RulePanel rule={s.rule} onChange={refresh} />
      </div>
      <div className="grid-2">
        <Panel>
          <LineChart title="Portfolio P&L (USD)" zeroLine xLabel="update" series={[{ key: "pnl", label: "P&L", slot: 1, points: s.history.map((h) => ({ x: h.n, y: Number(h.pnl) })) }]} yFormat={(v) => fmtMoney(v, 0)} />
        </Panel>
        <Panel>
          <LineChart title="Net GBP exposure (GBP)" zeroLine stepped xLabel="update" series={[{ key: "e", label: "GBP exposure", slot: 1, points: s.history.map((h) => ({ x: h.n, y: Number(h.gbp_exposure) })) }]} yFormat={(v) => fmtNum(v)} />
        </Panel>
      </div>
      <div className="grid-2">
        <Records s={s} />
        <EventTimeline modules={["portfolio", "fx"]} title="Portfolio & hedge events" limit={14} />
      </div>
    </>
  );
}

function Guided({ s, onChange }: { s: Portfolio; onChange: () => void }) {
  const [instrument, setInstrument] = useState<"futures" | "fx_offset">("futures");
  const [pct, setPct] = useState("1");
  const [pct2, setPct2] = useState("-1");
  const [log, setLog] = useState<{ title: string; observe: string }[]>([]);
  const { busy, error, run } = useAction();
  const step = s.guided_step;
  const next = () => run(async () => {
    const r = await pfApi.guidedStep(instrument, step === 1 ? pct : step === 4 ? pct2 : undefined);
    setLog((l) => [...l, { title: `${r.step}. ${r.title}`, observe: r.observe }]);
    onChange();
  });
  return (
    <Panel title="Guided scenario: hedging a GBP position" id="pf-guided"
      actions={<button type="button" className="btn" disabled={busy} onClick={() => run(async () => { await pfApi.guidedReset(); setLog([]); onChange(); })}>↺ Reset scenario</button>}>
      <SimpleOnly>
        <p className="small">
          If the fund benefits when the pound rises, a short GBP position may reduce that exposure. The hedge can also introduce
          costs, basis risk and additional risks. Walk through it step by step; every number comes from the simulator.
        </p>
      </SimpleOnly>
      <ol className="steps">
        {GUIDED.map((t, i) => (
          <li key={t} className={i < step ? "done" : i === step ? "current" : ""}><span aria-hidden="true">{i < step ? "✓" : i + 1}</span> {t}</li>
        ))}
      </ol>
      <div className="form-row">
        {step <= 2 && (
          <label>Hedge instrument
            <select value={instrument} onChange={(e) => setInstrument(e.target.value as "futures" | "fx_offset")}>
              <option value="futures">GBP futures (illustrative contract)</option>
              <option value="fx_offset">Offset FX trade (sell GBP/USD)</option>
            </select>
          </label>
        )}
        {step === 1 && <label>GBP/USD move (%)<input type="number" step="0.1" value={pct} onChange={(e) => setPct(e.target.value)} /></label>}
        {step === 4 && <label>Second GBP/USD move (%)<input type="number" step="0.1" value={pct2} onChange={(e) => setPct2(e.target.value)} /></label>}
        <button type="button" className="btn primary" disabled={busy || step >= GUIDED.length} onClick={() => void next()}>
          {step >= GUIDED.length ? "Scenario complete" : step === 0 && s.fills.length ? `Step 1 (reset first for a clean run)` : `Run step ${step + 1}`}
        </button>
      </div>
      {log.map((l) => <div key={l.title} className="observe"><strong>{l.title}.</strong> {l.observe}</div>)}
      <ErrorNote error={error} />
    </Panel>
  );
}

function Summary({ s }: { s: Portfolio }) {
  const b = s.pnl_breakdown;
  return (
    <Panel title="Fund portfolio" id="pf-summary" actions={<span className="small muted">valued in {s.valuation_currency} · {s.notice}</span>}>
      <div className="stats">
        <Stat label="Equity" value={fmtMoney(s.equity_usd, 0)} raw={s.equity_usd} />
        <Stat label="Total P&L" value={fmtSignedMoney(s.total_pnl_usd)} tone={s.total_pnl_usd} hint={`vs. initial ${fmtMoney(s.initial_equity_usd, 0)}`} raw={s.total_pnl_usd} />
        <Stat label="Gross exposure" value={fmtMoney(s.gross_exposure_usd, 0)} hint="sum of |currency exposure|" />
        <Stat label="Net exposure" value={fmtSignedMoney(s.net_exposure_usd, 0)} hint="signed sum, non-USD currencies" />
        <Stat label="Spot realized" value={fmtSignedMoney(b.spot_realized_usd)} tone={b.spot_realized_usd} />
        <Stat label="Spot unrealized" value={fmtSignedMoney(b.spot_unrealized_usd)} tone={b.spot_unrealized_usd} />
        <Stat label="Futures P&L" value={fmtSignedMoney(Number(b.futures_realized_usd) + Number(b.futures_unrealized_usd))} tone={Number(b.futures_realized_usd) + Number(b.futures_unrealized_usd)} hint="realized + unrealized" />
        <Stat label="Fees & costs" value={fmtMoney(Number(b.spot_fees_usd) + Number(b.futures_fees_usd))} />
      </div>
      <div className="balances">
        <h3 className="sub">Cash balances (by currency)</h3>
        <table className="table compact">
          <thead><tr><th>Currency</th><th className="num">Balance</th><th className="num">USD value</th></tr></thead>
          <tbody>{s.balances.map((x) => <tr key={x.currency}><td>{x.currency}</td><td className="num">{fmtNum(x.amount, 2)}</td><td className="num">{fmtMoney(x.usd_value)}</td></tr>)}</tbody>
        </table>
        <p className="small muted">Futures contracts are derivative positions, not cash: they appear under exposure and P&L, never in these balances.</p>
      </div>
      <TechOnly><p className="mono small">Rates: {Object.entries(s.rates).map(([k, v]) => `${k} ${v}`).join(" · ")}. {b.note}</p></TechOnly>
    </Panel>
  );
}

function Exposure({ s }: { s: Portfolio }) {
  const gbp = s.exposures.find((e) => e.currency === "GBP")!;
  return (
    <Panel title="Currency exposure" id="pf-exposure">
      <table className="table compact">
        <thead><tr><th>Ccy</th><th className="num">Spot balance</th><th className="num">Futures equiv.</th><th className="num">Net exposure</th><th className="num">USD value</th><th className="num">P&L if +1%</th></tr></thead>
        <tbody>
          {s.exposures.map((e) => (
            <tr key={e.currency}>
              <td>{e.currency} <span className="small muted">{e.direction}</span></td>
              <td className="num">{fmtNum(e.spot_balance)}</td><td className="num">{fmtNum(e.futures_equivalent)}</td>
              <td className="num"><b>{fmtNum(e.net_exposure)}</b></td><td className="num">{fmtMoney(e.net_exposure_usd, 0)}</td>
              <td className="num">{fmtSignedMoney(e.pnl_if_plus_1pct_usd, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Explain
        simple={Number(gbp.net_exposure) === 0 && Number(gbp.pre_hedge_exposure) !== 0
          ? `Before hedging the fund was exposed to ${fmtNum(gbp.pre_hedge_exposure)} GBP. Its hedges now offset that, so a 1% GBP move barely changes its value.`
          : Number(gbp.net_exposure) > 0 ? `The fund is long ${fmtNum(gbp.net_exposure)} GBP: a 1% rise in GBP adds about ${fmtMoney(gbp.pnl_if_plus_1pct_usd, 0)}; a 1% fall costs the same.`
            : Number(gbp.net_exposure) < 0 ? `The fund is short ${fmtNum(-Number(gbp.net_exposure))} GBP: it gains if GBP falls.` : "No GBP exposure yet."}
        technical={<p className="mono small">GBP: pre-hedge {fmtNum(gbp.pre_hedge_exposure)} (excl. hedge spot {fmtNum(gbp.hedge_spot)} and futures {fmtNum(gbp.futures_equivalent)}) → net {fmtNum(gbp.net_exposure)}; sensitivity = net × rate × 1% = {gbp.pnl_if_plus_1pct_usd} USD.</p>}
      />
    </Panel>
  );
}

function HedgePanel({ s, onChange }: { s: Portfolio; onChange: () => void }) {
  const [mode, setMode] = useState<"rule" | "manual">("rule");
  const [instrument, setInstrument] = useState<"futures" | "fx_offset">("futures");
  const [direction, setDirection] = useState<"sell" | "buy">("sell");
  const [qty, setQty] = useState("16");
  const [target, setTarget] = useState("0");
  const [maxExp, setMaxExp] = useState("0");
  const [limitUsd, setLimitUsd] = useState("");
  const [routing, setRouting] = useState("smart");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const { busy, error, run } = useAction();
  const propose = (e: FormEvent) => {
    e.preventDefault();
    const req: HedgeRequest = { instrument, mode, currency: "GBP", routing_mode: routing };
    if (mode === "manual") Object.assign(req, { direction, quantity: Number(qty) });
    else Object.assign(req, { target_exposure: target, max_exposure: maxExp });
    if (limitUsd) req.max_hedge_notional_usd = limitUsd;
    void run(async () => setProposal(await pfApi.propose(req)));
  };
  const pending = proposal ?? s.proposals.find((p) => p.status === "proposed") ?? null;
  return (
    <Panel title="Hedge" id="pf-hedge">
      <form className="order-form" onSubmit={propose}>
        <div className="segmented" role="group" aria-label="Hedge mode">
          <button type="button" aria-pressed={mode === "rule"} onClick={() => setMode("rule")}>Rule-based</button>
          <button type="button" aria-pressed={mode === "manual"} onClick={() => setMode("manual")}>Manual</button>
        </div>
        <div className="form-row">
          <label>Instrument
            <select value={instrument} onChange={(e) => { setInstrument(e.target.value as "futures" | "fx_offset"); setQty(e.target.value === "futures" ? "16" : "1000000"); }}>
              <option value="futures">GBP futures</option><option value="fx_offset">Offset FX trade</option>
            </select>
          </label>
          {mode === "manual" ? (<>
            <label>Direction<select value={direction} onChange={(e) => setDirection(e.target.value as "sell" | "buy")}><option value="sell">Sell (short GBP)</option><option value="buy">Buy (long GBP)</option></select></label>
            <label>Quantity ({instrument === "futures" ? "contracts" : "GBP"})<input type="number" min="1" value={qty} onChange={(e) => setQty(e.target.value)} /></label>
          </>) : (<>
            <label>Target exposure (GBP)<input type="number" value={target} onChange={(e) => setTarget(e.target.value)} /></label>
            <label>Tolerance ± (GBP)<input type="number" min="0" value={maxExp} onChange={(e) => setMaxExp(e.target.value)} /></label>
          </>)}
        </div>
        <div className="form-row">
          {instrument === "fx_offset" && <label>Routing<select value={routing} onChange={(e) => setRouting(e.target.value)}><option value="smart">Smart</option><option value="A">Book A</option><option value="B">Book B</option><option value="C">Book C</option></select></label>}
          <label>Risk limit: max notional (USD, optional)<input type="number" min="0" value={limitUsd} onChange={(e) => setLimitUsd(e.target.value)} /></label>
        </div>
        <button type="submit" className="btn primary" disabled={busy}>Calculate proposed hedge</button>
      </form>
      <ErrorNote error={error} />
      {pending && <ProposalCard p={pending} onExecuted={(p) => { setProposal(p); onChange(); }} />}
    </Panel>
  );
}

function ProposalCard({ p, onExecuted }: { p: Proposal; onExecuted: (p: Proposal) => void }) {
  const { busy, error, run } = useAction();
  return (
    <div className="result proposal">
      <div className="panel-head"><b>Proposal {p.id}</b><StatusBadge status={p.status} /></div>
      <p>{p.explanation}</p>
      {p.direction && (
        <table className="table compact">
          <thead><tr><th /><th className="num">Before</th><th className="num">After (projected)</th></tr></thead>
          <tbody>
            <tr><td>GBP exposure</td><td className="num">{fmtNum(p.exposure_before)}</td><td className="num">{fmtNum(p.projected_exposure_after)}</td></tr>
            <tr><td>P&L if GBP +1%</td><td className="num">{fmtSignedMoney(p.pnl_plus1_before, 0)}</td><td className="num">{fmtSignedMoney(p.pnl_plus1_after, 0)}</td></tr>
            <tr><td>Hedge</td><td colSpan={2} className="num">{p.direction} {fmtNum(p.quantity)} {p.unit} @ ~{p.est_price ?? "—"} · est. fees {fmtMoney(p.est_fees_usd)} · notional {fmtMoney(p.est_notional_usd, 0)}</td></tr>
            <tr><td>Residual exposure</td><td colSpan={2} className="num">{fmtNum(p.projected_residual)} GBP</td></tr>
          </tbody>
        </table>
      )}
      <details><summary className="small">Assumptions ({p.assumptions.length})</summary><ul className="small">{p.assumptions.map((a) => <li key={a}>{a}</li>)}</ul></details>
      {p.result && <p className="small"><b>Result:</b> {p.result}</p>}
      {p.status === "proposed" && (
        <button type="button" className="btn primary" disabled={busy} onClick={() => run(async () => onExecuted(await pfApi.execute(p.id)))}>Approve &amp; execute hedge</button>
      )}
      <ErrorNote error={error} />
      <TechOnly><JsonBlock value={p} label="Proposal JSON" /></TechOnly>
    </div>
  );
}

function RiskTable({ r }: { r: Risk }) {
  return (
    <Panel title="Risk scenarios: unhedged vs. hedged" id="pf-risk" actions={<span className="small muted">GBP/USD {r.spot} · future {r.futures_price}</span>}>
      <div className="scroll">
        <table className="table">
          <thead><tr><th>Scenario</th><th className="num">Without hedges</th><th className="num">With hedges</th><th>What it shows</th></tr></thead>
          <tbody>
            {r.rows.map((row) => (
              <tr key={row.id}>
                <th scope="row">{row.title}</th>
                <td className={`num ${Number(row.unhedged) < 0 ? "neg" : Number(row.unhedged) > 0 ? "pos" : ""}`}>{fmtSignedMoney(row.unhedged, 0)}</td>
                <td className={`num ${Number(row.hedged) < 0 ? "neg" : Number(row.hedged) > 0 ? "pos" : ""}`}>{fmtSignedMoney(row.hedged, 0)}</td>
                <td className="small">{row.explain}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="small muted">Exposure: {fmtNum(r.pre_hedge_exposure_gbp)} GBP before hedges → {fmtNum(r.post_hedge_exposure_gbp)} GBP after. A hedge reduces particular risks; it does not guarantee a profit or eliminate all risk.</p>
      <TechOnly><ul className="small">{r.assumptions.map((a) => <li key={a}>{a}</li>)}</ul></TechOnly>
    </Panel>
  );
}

function Futures({ s, onChange }: { s: Portfolio; onChange: () => void }) {
  const f = s.futures;
  const [shock, setShock] = useState("5");
  const [days, setDays] = useState("30");
  const [msg, setMsg] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  return (
    <Panel title="GBP futures (illustrative contract)" id="pf-futures">
      <p className="small muted">{f.spec.label}</p>
      <div className="stats">
        <Stat label="Futures price" value={f.price} hint={`bid ${f.bid} / ask ${f.ask}`} />
        <Stat label="Basis (F − S)" value={Number(f.basis).toFixed(5)} hint={`${f.spec.days_to_expiry} days to expiry${Number(f.basis_shock_pips) ? ` · shock ${f.basis_shock_pips} pips` : ""}`} />
        <Stat label="Position" value={`${f.contracts} contracts`} hint={`${fmtNum(f.gbp_equivalent)} GBP equivalent`} />
        <Stat label="Unrealized" value={fmtSignedMoney(f.unrealized_usd)} tone={f.unrealized_usd} hint={f.avg_entry ? `entry ${Number(f.avg_entry).toFixed(4)}` : ""} />
        <Stat label="Initial margin" value={fmtMoney(f.margin.initial_required, 0)} hint={`maintenance ${fmtMoney(f.margin.maintenance_required, 0)}`} />
      </div>
      <p className="small muted">1 contract = {fmtNum(f.spec.contract_size)} GBP · tick {f.spec.tick_size} = {fmtMoney(Number(f.spec.tick_size) * f.spec.contract_size)} · fee {fmtMoney(f.spec.fee_per_contract)}/contract · up to {f.spec.max_fill_per_order} contracts per order. {f.margin_note}{f.expired ? " The contract has expired." : ""}</p>
      <div className="form-row">
        <label>Basis shock (pips)<input type="number" value={shock} onChange={(e) => setShock(e.target.value)} /></label>
        <button type="button" className="btn" disabled={busy} onClick={() => run(async () => { await pfApi.basis(shock); setMsg(`Basis shocked by ${shock} pips.`); onChange(); })}>Apply basis shock</button>
        <label>Advance calendar (days)<input type="number" min="1" value={days} onChange={(e) => setDays(e.target.value)} /></label>
        <button type="button" className="btn" disabled={busy} onClick={() => run(async () => { const r = await pfApi.advanceDays(Number(days)); setMsg(r.message); onChange(); })}>Advance toward expiry</button>
      </div>
      {msg && <p className="observe small">{msg}</p>}
      <ErrorNote error={error} />
      <TechOnly><JsonBlock value={f.spec} label="Contract specification" /></TechOnly>
    </Panel>
  );
}

function RulePanel({ rule, onChange }: { rule: HedgeRule; onChange: () => void }) {
  const [r, setR] = useState<HedgeRule>(rule);
  const { busy, error, run } = useAction();
  return (
    <Panel title="Automatic hedging rule" id="pf-rule">
      <p className="small">When enabled, the rule checks GBP exposure after every fund trade and each simulation tick. If it drifts beyond the tolerance, it proposes a hedge back to the target, and executes it only when auto-execute is on.</p>
      <form className="order-form" onSubmit={(e) => { e.preventDefault(); void run(async () => { await pfApi.putRule(r); onChange(); }); }}>
        <div className="form-row">
          <label className="radio"><input type="checkbox" checked={r.enabled} onChange={(e) => setR({ ...r, enabled: e.target.checked })} /> Enabled</label>
          <label className="radio"><input type="checkbox" checked={r.auto_execute} onChange={(e) => setR({ ...r, auto_execute: e.target.checked })} /> Auto-execute (demo)</label>
        </div>
        <div className="form-row">
          <label>Instrument<select value={r.instrument} onChange={(e) => setR({ ...r, instrument: e.target.value as "futures" | "fx_offset" })}><option value="futures">Futures</option><option value="fx_offset">Offset FX</option></select></label>
          <label>Target (GBP)<input type="number" value={r.target_exposure} onChange={(e) => setR({ ...r, target_exposure: e.target.value })} /></label>
          <label>Tolerance ± (GBP)<input type="number" min="0" value={r.max_exposure} onChange={(e) => setR({ ...r, max_exposure: e.target.value })} /></label>
        </div>
        <button type="submit" className="btn" disabled={busy}>Save rule</button>
        <span className="small muted"> Currently {rule.enabled ? `on${rule.auto_execute ? ", auto-executing" : ", proposals need approval"}` : "off"}.</span>
      </form>
      <ErrorNote error={error} />
    </Panel>
  );
}

function Records({ s }: { s: Portfolio }) {
  return (
    <Panel title="Trades, hedge orders and fills" id="pf-records">
      {s.fills.length === 0 ? <p className="empty">No fills yet.</p> : (
        <div className="scroll">
          <table className="table compact">
            <thead><tr><th>Time</th><th>Purpose</th><th>Instrument</th><th>Side</th><th className="num">Qty</th><th className="num">Price</th><th className="num">Fee</th><th>Venue</th></tr></thead>
            <tbody>{s.fills.map((f, i) => (
              <tr key={i}><td>{shortTime(f.ts)}</td><td>{f.purpose === "hedge" ? <b>hedge</b> : "trade"}</td><td>{f.instrument}</td><td>{f.side}</td><td className="num">{fmtNum(f.quantity)}</td><td className="num">{f.price}</td><td className="num">{f.fee} {f.fee_ccy}</td><td>{f.venue}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {s.proposals.length > 0 && (<>
        <h3 className="sub">Hedge proposals</h3>
        <table className="table compact">
          <thead><tr><th>ID</th><th>Instrument</th><th className="num">Qty</th><th className="num">Filled</th><th>Status</th></tr></thead>
          <tbody>{s.proposals.map((p) => <tr key={p.id}><td className="mono small">{p.id}</td><td>{p.instrument}</td><td className="num">{fmtNum(p.quantity)} {p.unit}</td><td className="num">{fmtNum(p.filled_quantity)}</td><td><StatusBadge status={p.status} /></td></tr>)}</tbody>
        </table>
      </>)}
    </Panel>
  );
}
