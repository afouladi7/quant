import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { fxApi, type BookConfig, type BookSnap, type FXState, type OrderBody, type Parent, type Plan, type Scenario } from "../api/fx";
import { useStream } from "../api/stream";
import { BarList, LineChart } from "../components/charts";
import { EventTimeline } from "../components/EventTimeline";
import { OrderTrace } from "../components/OrderTrace";
import { ErrorNote, Explain, Loading, Panel, StatusBadge, Tabs, TechOnly, useAction } from "../components/ui";
import { compact, fmtNum, fmtPct } from "../lib/format";
import { useLive } from "../lib/useLive";
import { Hedging } from "./Hedging";

type Tab = "routing" | "hedging";

export function FX() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "routing";
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>FX Order Routing &amp; Hedging</h1>
          <p className="lead">
            A simulated hedge fund trades currencies on three independent order books, A, B and C, then manages the
            currency risk it has taken on. Rates and book settings are synthetic and hypothetical, not live market data.
          </p>
        </div>
      </header>
      <Tabs<Tab>
        label="FX sections" value={tab} onChange={(t) => setParams({ tab: t })}
        tabs={[{ id: "routing", label: "Order routing (books A · B · C)" }, { id: "hedging", label: "Portfolio & hedging" }]}
      />
      {tab === "routing" ? <Routing /> : <Hedging />}
    </div>
  );
}

function Routing() {
  const [pair, setPair] = useState("GBP/USD");
  const { data, error, loading, refresh } = useLive(() => fxApi.state(pair), ["fx", "portfolio"], 1000);
  useEffect(() => { void refresh(); }, [pair, refresh]);
  const [trace, setTrace] = useState<string | null>(null);
  const [lastParent, setLastParent] = useState<Parent | null>(null);
  if (loading && !data) return <Loading what="FX books" />;
  if (!data) return <ErrorNote error={error ?? "FX module unavailable"} />;
  const digits = data.pair.tick_size.split(".")[1]?.length ?? 5;
  return (
    <>
      <ErrorNote error={error} />
      <Scenarios state={data} onChange={refresh} onParent={setLastParent} />
      <div className="grid-2">
        <Panel title="Market rate" id="fx-rate" actions={
          <label className="small">Pair{" "}
            <select value={pair} onChange={(e) => setPair(e.target.value)}>{data.pairs.map((p) => <option key={p}>{p}</option>)}</select>
          </label>
        }>
          <div className="quote-mid big-rate">
            <span className="small muted">{data.pair.symbol} mid · {data.pair.quote} per 1 {data.pair.base}</span>
            <b className="quote-px">{data.mid}</b>
          </div>
          <LineChart title={`${data.pair.symbol} synthetic mid`} series={[{ key: "mid", label: "Mid", slot: 1, points: data.rate_series.map((p, i) => ({ x: i + 1, y: Number(p.mid) })) }]} yFormat={(v) => v.toFixed(digits)} xLabel="update" height={160} />
          <p className="small muted">{data.notice}</p>
        </Panel>
        <OrderTicket state={data} onDone={(p) => { setLastParent(p); void refresh(); }} />
      </div>
      {lastParent && <RoutingResult parent={lastParent} books={data.books} onTrace={setTrace} />}
      {trace && <OrderTrace correlationId={trace} onClose={() => setTrace(null)} />}
      <Comparison books={data.books} pip={data.pair.pip} />
      <div className="grid-3">
        {data.books.map((b) => <BookCard key={b.name} b={b} digits={digits} onChange={refresh} />)}
      </div>
      <ParentList parents={data.parents} onTrace={setTrace} onSelect={setLastParent} onChange={refresh} />
      <EventTimeline modules={["fx"]} title="FX events" limit={14} />
    </>
  );
}

function Scenarios({ state, onChange, onParent }: { state: FXState; onChange: () => void; onParent: (p: Parent) => void }) {
  const [list, setList] = useState<Scenario[]>([]);
  const [last, setLast] = useState<{ title: string; observe: string } | null>(null);
  const { busy, error, run } = useAction();
  useEffect(() => { void fxApi.scenarios().then(setList).catch(() => undefined); }, []);
  const active = state.scenario;
  return (
    <Panel title="Routing scenarios" id="fx-scen" actions={<span className="small muted">GBP/USD fixed at 1.27000 · simulation paused · reproducible</span>}>
      <div className="scenario-grid">
        {list.map((s) => (
          <div key={s.id} className={`preset ${active?.id === s.id ? "active" : ""}`}>
            <h3>{s.id}. {s.title}</h3>
            <p className="small">{s.expect}</p>
            <button type="button" className="btn" disabled={busy} onClick={() => run(async () => { await fxApi.loadScenario(s.id); setLast(null); onChange(); })}>
              {active?.id === s.id ? "↺ Reset Scenario" : "Load"}
            </button>
          </div>
        ))}
      </div>
      {active && (
        <div className="stepper">
          <ol className="steps">
            {active.steps.map((s, i) => (
              <li key={s.title} className={i < (active.next_step ?? 0) ? "done" : i === active.next_step ? "current" : ""}>
                <span aria-hidden="true">{i < (active.next_step ?? 0) ? "✓" : i + 1}</span> {s.title}
              </li>
            ))}
          </ol>
          <div className="step-actions">
            <button type="button" className="btn primary" disabled={busy || active.complete}
              onClick={() => run(async () => { const r = await fxApi.stepScenario(active.id); setLast(r); if (r.parent) onParent(r.parent); onChange(); })}>
              {active.complete ? "Scenario complete" : `Run step ${(active.next_step ?? 0) + 1}: ${active.steps[active.next_step ?? 0]?.title}`}
            </button>
          </div>
          {last && <div className="observe" role="status"><strong>What should happen:</strong> {last.observe}</div>}
        </div>
      )}
      <ErrorNote error={error} />
    </Panel>
  );
}

function OrderTicket({ state, onDone }: { state: FXState; onDone: (p: Parent) => void }) {
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [type, setType] = useState<"market" | "limit">("market");
  const [qty, setQty] = useState("1000000");
  const [limit, setLimit] = useState("");
  const [mode, setMode] = useState("smart");
  const [fees, setFees] = useState(state.weights.include_fees);
  const [penalty, setPenalty] = useState(state.weights.latency_penalty_bps_per_100ms);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [key, setKey] = useState(() => crypto.randomUUID?.() ?? String(Date.now()));
  const { busy, error, run } = useAction();
  const body = (): OrderBody => ({
    pair: state.pair.symbol, side, type, quantity: Number(qty), routing_mode: mode,
    ...(type === "limit" ? { limit_price: limit } : {}),
    weights: { include_fees: fees, latency_penalty_bps_per_100ms: penalty },
  });
  useEffect(() => { setKey(crypto.randomUUID?.() ?? String(Date.now())); setPlan(null); }, [side, type, qty, limit, mode, fees, penalty, state.pair.symbol]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => { const r = await fxApi.submit(body(), key); onDone(r.parent); });
  };
  return (
    <Panel title="Fund order ticket" id="fx-ticket">
      <form className="order-form" onSubmit={submit}>
        <div className="segmented" role="group" aria-label="Side">
          <button type="button" aria-pressed={side === "buy"} onClick={() => setSide("buy")}>Buy {state.pair.base}</button>
          <button type="button" aria-pressed={side === "sell"} onClick={() => setSide("sell")}>Sell {state.pair.base}</button>
        </div>
        <div className="form-row">
          <label>Quantity ({state.pair.base})
            <input type="number" min={state.pair.lot_size} step={state.pair.lot_size} value={qty} onChange={(e) => setQty(e.target.value)} required />
          </label>
          <label>Type
            <select value={type} onChange={(e) => setType(e.target.value as "market" | "limit")}>
              <option value="market">Market</option><option value="limit">Limit</option>
            </select>
          </label>
          {type === "limit" && (
            <label>Limit ({state.pair.quote})
              <input type="number" step={state.pair.tick_size} value={limit} onChange={(e) => setLimit(e.target.value)} required placeholder={state.mid} />
            </label>
          )}
        </div>
        <fieldset className="route-mode">
          <legend className="small muted">Routing</legend>
          {["A", "B", "C", "smart"].map((m) => (
            <label key={m} className="radio"><input type="radio" name="mode" checked={mode === m} onChange={() => setMode(m)} /> {m === "smart" ? "Smart (all books)" : `Book ${m} only`}</label>
          ))}
        </fieldset>
        {mode === "smart" && (
          <div className="form-row">
            <label className="radio"><input type="checkbox" checked={fees} onChange={(e) => setFees(e.target.checked)} /> Include fees in the routing objective</label>
            <label>Latency penalty (bps per 100 ms)
              <input type="number" step="0.05" min="0" value={penalty} onChange={(e) => setPenalty(e.target.value)} />
            </label>
          </div>
        )}
        <div className="form-row">
          <button type="button" className="btn" disabled={busy} onClick={() => run(async () => setPlan(await fxApi.preview(body())))}>Preview route</button>
          <button type="submit" className={`btn primary ${side}`} disabled={busy}>Send {side} order</button>
        </div>
        <TechOnly><p className="mono small">Idempotency-Key: {key}</p></TechOnly>
      </form>
      <ErrorNote error={error} />
      {plan && <div className="result"><strong>Preview (nothing sent):</strong> {plan.explanation}<PlanTable plan={plan} /></div>}
    </Panel>
  );
}

function PlanTable({ plan }: { plan: Plan }) {
  return (
    <TechOnly>
      <div className="scroll">
        <table className="table compact">
          <caption className="small muted">
            Routing calculation · effective = price × (1 ± (fee{plan.include_fees ? "" : " (ignored)"} + {plan.latency_penalty_bps_per_100ms} bps × latency/100 ms) / 10,000)
          </caption>
          <thead><tr><th>Rank</th><th>Book</th><th className="num">Price</th><th className="num">Available</th><th className="num">Fee bps</th><th className="num">Latency</th><th className="num">Effective</th><th className="num">Allocated</th><th>Note</th></tr></thead>
          <tbody>
            {plan.candidates.map((c, i) => (
              <tr key={i} className={c.allocated ? "row-on" : c.eligible ? "" : "row-off"}>
                <td>{c.rank || "—"}</td><td>{c.book}</td><td className="num">{c.price}</td><td className="num">{fmtNum(c.available)}</td>
                <td className="num">{c.fee_bps}</td><td className="num">{c.latency_ms} ms</td><td className="num mono">{c.effective_price}</td>
                <td className="num">{c.allocated ? fmtNum(c.allocated) : "—"}</td><td className="small">{c.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </TechOnly>
  );
}

/** Parent → child diagram for the most recent routed order, drawn from backend data. */
function RoutingResult({ parent, books, onTrace }: { parent: Parent; books: BookSnap[]; onTrace: (id: string) => void }) {
  const [p, setP] = useState(parent);
  const { events } = useStream();
  const lastSeq = events.filter((e) => e.correlation_id === parent.id).at(-1)?.seq;
  useEffect(() => { setP(parent); }, [parent]);
  useEffect(() => { if (lastSeq) void fxApi.order(parent.id).then((r) => setP(r.parent)).catch(() => undefined); }, [lastSeq, parent.id]);
  const byBook = useMemo(() => Object.fromEntries(books.map((b) => [b.name, b])), [books]);
  return (
    <Panel title={<>Routing result <StatusBadge status={p.status} filled={p.filled_qty} quantity={p.quantity} /></>} id="fx-result"
      actions={<button type="button" className="link" onClick={() => onTrace(p.id)}>Trace parent order →</button>}>
      <div className="route-diagram" key={p.id}>
        <div className="route-parent">
          <div className="small muted">Parent {p.purpose === "hedge" ? "hedge " : ""}order</div>
          <b>{p.side} {fmtNum(p.quantity)} {p.pair.split("/")[0]}</b>
          <div className="small">{p.type}{p.limit_price ? ` @ ${p.limit_price}` : ""} · {p.routing_mode === "smart" ? "smart" : `Book ${p.routing_mode}`}</div>
          <TechOnly><code className="small">{p.id}</code></TechOnly>
        </div>
        <div className="route-children">
          {["A", "B", "C"].map((name, i) => {
            const kids = p.children.filter((c) => c.book === name);
            const qty = kids.reduce((s, c) => s + c.quantity, 0);
            const filled = kids.reduce((s, c) => s + c.filled_qty, 0);
            return (
              <div key={name} className={`route-child ${kids.length ? "on" : ""}`} style={{ animationDelay: `${i * 120}ms` }}>
                <span className="route-arrow" aria-hidden="true">{kids.length ? "━━▶" : "┄┄"}</span>
                <div>
                  <b>Book {name}</b> <span className="small muted">{byBook[name]?.config.description}</span>
                  {kids.length ? (
                    <div className="small">
                      sent {fmtNum(qty)} · filled {fmtNum(filled)} {kids.map((c) => <StatusBadge key={c.order_id} status={c.status} filled={c.filled_qty} quantity={c.quantity} />)}
                      <br />avg {kids[0].avg_price ?? "—"} · fees {kids.reduce((s, c) => s + Number(c.fees), 0).toFixed(2)} · simulated latency {kids[0].sim_latency_ms} ms
                    </div>
                  ) : <div className="small muted">not used</div>}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div className="stats">
        <div className="stat"><div className="stat-label">Filled</div><div className="stat-value">{fmtNum(p.filled_qty)} / {fmtNum(p.quantity)}</div></div>
        <div className="stat"><div className="stat-label">Weighted-average price</div><div className="stat-value">{p.vwap ?? "—"}</div></div>
        <div className="stat"><div className="stat-label">Total fees</div><div className="stat-value">{Number(p.total_fees).toFixed(2)} {p.pair.split("/")[1]}</div></div>
        <div className="stat"><div className="stat-label">Unfilled</div><div className="stat-value">{fmtNum(p.unfilled_qty)}</div><div className="stat-hint">{p.resting_qty ? `${fmtNum(p.resting_qty)} resting` : p.unfilled_qty ? "canceled" : ""}</div></div>
      </div>
      <Explain simple={<p>{p.explanation}</p>} technical={<><p>{p.explanation}</p><PlanTable plan={p.plan} />
        <table className="table compact"><thead><tr><th>Child</th><th>Book</th><th>TIF</th><th className="num">Qty</th><th className="num">Filled</th><th className="num">Avg</th><th className="num">Fees</th><th>Sent → simulated arrival</th></tr></thead>
          <tbody>{p.children.map((c) => <tr key={c.order_id}><td className="mono small">{c.order_id}</td><td>{c.book}</td><td>{c.tif}</td><td className="num">{fmtNum(c.quantity)}</td><td className="num">{fmtNum(c.filled_qty)}</td><td className="num">{c.avg_price ?? "—"}</td><td className="num">{c.fees}</td><td className="small mono">{c.sent_ts.slice(11, 23)} → {c.sim_arrival_ts.slice(11, 23)}</td></tr>)}</tbody>
        </table></>} />
    </Panel>
  );
}

function Comparison({ books, pip }: { books: BookSnap[]; pip: string }) {
  const bestBid = Math.max(...books.map((b) => Number(b.best_bid ?? -Infinity)));
  const bestAsk = Math.min(...books.map((b) => Number(b.best_ask ?? Infinity)));
  return (
    <Panel title="Books compared" id="fx-compare" actions={<span className="small muted">★ = best price across books</span>}>
      <div className="scroll">
        <table className="table">
          <thead><tr><th>Book</th><th className="num">Best bid</th><th className="num">Best ask</th><th className="num">Spread</th><th className="num">Bid depth</th><th className="num">Ask depth</th><th className="num">Fee</th><th className="num">Latency</th><th className="num">Fund fill rate</th></tr></thead>
          <tbody>
            {books.map((b) => (
              <tr key={b.name}>
                <th scope="row">Book {b.name} <span className="small muted">{b.config.description}</span></th>
                <td className="num">{b.best_bid ?? "—"} {Number(b.best_bid) === bestBid && "★"}</td>
                <td className="num">{b.best_ask ?? "—"} {Number(b.best_ask) === bestAsk && "★"}</td>
                <td className="num">{b.spread ? `${(Number(b.spread) / Number(pip)).toFixed(1)} pips` : "—"}</td>
                <td className="num">{compact(b.bid_depth)}</td><td className="num">{compact(b.ask_depth)}</td>
                <td className="num">{b.config.fee_bps} bps</td><td className="num">{b.latency_ms} ms</td>
                <td className="num">{b.fill_rate === null ? "—" : fmtPct(b.fill_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid-2">
        <div><h3 className="sub">Offer depth (what a buyer can take)</h3><BarList items={books.map((b) => ({ label: `Book ${b.name}`, value: b.ask_depth, slot: 2 }))} format={compact} /></div>
        <div><h3 className="sub">Bid depth (what a seller can hit)</h3><BarList items={books.map((b) => ({ label: `Book ${b.name}`, value: b.bid_depth, slot: 1 }))} format={compact} /></div>
      </div>
    </Panel>
  );
}

function BookCard({ b, digits, onChange }: { b: BookSnap; digits: number; onChange: () => void }) {
  const [edit, setEdit] = useState(false);
  const [cfg, setCfg] = useState<BookConfig>(b.config);
  const { busy, error, run } = useAction();
  useEffect(() => { if (!edit) setCfg(b.config); }, [b.config, edit]);
  const asks = b.asks.slice(0, 5).reverse();
  const bids = b.bids.slice(0, 5);
  const max = Math.max(1, ...asks.map((l) => l.quantity), ...bids.map((l) => l.quantity));
  return (
    <Panel title={`Book ${b.name}`} id={`book-${b.name}`} actions={<button type="button" className="link" onClick={() => setEdit(!edit)}>{edit ? "Close" : "Configure"}</button>}>
      <p className="small muted">{b.config.description} · hypothetical · fee {b.config.fee_bps} bps · latency {b.latency_ms} ms</p>
      {edit ? (
        <form onSubmit={(e) => { e.preventDefault(); void run(async () => { await fxApi.putBook(cfg); setEdit(false); onChange(); }); }}>
          <div className="form-grid tight">
            {([["spread_pips", "Spread (pips)"], ["levels", "Levels"], ["level_step_pips", "Level step (pips)"], ["qty_per_level", "Qty per level"], ["fee_bps", "Fee (bps)"], ["latency_ms", "Latency (ms)"], ["price_offset_pips", "Price offset (pips)"]] as [keyof BookConfig, string][]).map(([k, label]) => (
              <label key={k}>{label}
                <input type="number" step="any" value={String(cfg[k])} onChange={(e) => setCfg({ ...cfg, [k]: typeof b.config[k] === "number" ? Number(e.target.value) : e.target.value })} />
              </label>
            ))}
          </div>
          <button type="submit" className="btn primary" disabled={busy}>Apply to Book {b.name}</button>
          <ErrorNote error={error} />
        </form>
      ) : (
        <table className="ladder">
          <thead><tr><th>Bid</th><th>Price</th><th>Ask</th></tr></thead>
          <tbody>
            {asks.map((l) => (
              <tr key={`a${l.price}`} className="ladder-ask"><td /><td className="num price">{Number(l.price).toFixed(digits)}</td>
                <td><span className="qty qty-ask"><span className="qty-bar" style={{ width: `${(l.quantity / max) * 100}%` }} /><span className="qty-text">{compact(l.quantity)}{l.by_owner.fund ? <span className="chip mm">FUND</span> : null}</span></span></td></tr>
            ))}
            <tr className="ladder-spread"><td colSpan={3}>spread {b.spread ? Number(b.spread).toFixed(digits) : "—"}</td></tr>
            {bids.map((l) => (
              <tr key={`b${l.price}`} className="ladder-bid">
                <td><span className="qty qty-bid"><span className="qty-bar" style={{ width: `${(l.quantity / max) * 100}%` }} /><span className="qty-text">{l.by_owner.fund ? <span className="chip mm">FUND</span> : null}{compact(l.quantity)}</span></span></td>
                <td className="num price">{Number(l.price).toFixed(digits)}</td><td /></tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="small">
        {b.resting_fund_orders.length ? `${b.resting_fund_orders.length} resting fund order(s) · ` : ""}
        {b.recent_trades.length} recent fund trade(s){b.recent_trades[0] ? `, last ${fmtNum(b.recent_trades[0].quantity)} @ ${b.recent_trades[0].price}` : ""}
      </p>
    </Panel>
  );
}

function ParentList({ parents, onTrace, onSelect, onChange }: { parents: Parent[]; onTrace: (id: string) => void; onSelect: (p: Parent) => void; onChange: () => void }) {
  const cancel = useAction();
  return (
    <Panel title="Fund orders" id="fx-orders">
      {parents.length === 0 ? <p className="empty">No fund orders yet. Use the ticket or a scenario above.</p> : (
        <div className="scroll">
          <table className="table compact">
            <thead><tr><th>Order</th><th>Purpose</th><th>Routing</th><th className="num">Filled</th><th className="num">VWAP</th><th className="num">Fees</th><th>Children</th><th>Status</th><th /></tr></thead>
            <tbody>
              {parents.map((p) => (
                <tr key={p.id}>
                  <td><button type="button" className="link" onClick={() => onSelect(p)}>{p.side} {fmtNum(p.quantity)}{p.limit_price ? ` @ ${p.limit_price}` : ""}</button></td>
                  <td>{p.purpose}</td><td>{p.routing_mode}</td>
                  <td className="num">{fmtNum(p.filled_qty)}</td><td className="num">{p.vwap ?? "—"}</td><td className="num">{Number(p.total_fees).toFixed(2)}</td>
                  <td>{p.children.map((c) => c.book).join(" + ") || "—"}</td>
                  <td><StatusBadge status={p.status} filled={p.filled_qty} quantity={p.quantity} /></td>
                  <td className="nowrap">
                    <button type="button" className="link" onClick={() => onTrace(p.id)}>Trace</button>
                    {p.resting_qty > 0 && <> · <button type="button" className="link" disabled={cancel.busy} onClick={() => cancel.run(async () => { await fxApi.cancel(p.id); onChange(); })}>Cancel</button></>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ErrorNote error={cancel.error} />
    </Panel>
  );
}
