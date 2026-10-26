import { useEffect, useMemo, useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import { mmApi, type MMConfig, type MMState, type Order, type OrderResponse, type Preset } from "../api/mm";
import { useStream } from "../api/stream";
import type { MarketLabEvent } from "../api/types";
import { LineChart } from "../components/charts";
import { EventTimeline } from "../components/EventTimeline";
import { OrderTrace } from "../components/OrderTrace";
import { StartHere, Term } from "../components/learn";
import { ErrorNote, Explain, JsonBlock, Loading, Panel, SimpleOnly, Stat, StatusBadge, TechOnly, useAction } from "../components/ui";
import { fmtMoney, fmtNum, fmtPct, fmtSignedMoney, shortTime } from "../lib/format";
import { useLive } from "../lib/useLive";

export function MarketMaker() {
  const { data, error, loading, refresh } = useLive(mmApi.state, ["marketmaker"], 800);
  const [trace, setTrace] = useState<string | null>(null);
  if (loading && !data) return <div className="page"><Loading what="market maker" /></div>;
  if (!data) return <div className="page"><ErrorNote error={error ?? "Market maker unavailable"} /></div>;
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Market Maker Simulator</h1>
          <p className="lead">
            A <Term id="market_maker">market maker</Term> continuously offers to buy (the <Term id="bid">bid</Term>) and sell
            (the <Term id="ask">ask</Term>) {data.instrument}, a made-up stock. It earns the gap between the two, the{" "}
            <Term id="spread">spread</Term>, when customers trade on both sides, but it carries risk while it holds shares.
          </p>
        </div>
        <ResetDemo onDone={refresh} />
      </header>
      <StartHere steps={[
        <>In <b>Guided demos</b>, load <b>Spread Capture</b> and press “Run step” five times, reading <b>What to notice</b> each time.</>,
        <>Watch the <b>Inventory & P&L</b> tiles change. Hover any underlined word for a definition, or press <b>?</b> on a panel.</>,
        <>Then try <b>Inventory Risk</b>, or press <b>Start</b> in the clock bar above to let synthetic customers trade.</>,
      ]} />
      <ErrorNote error={error} />
      <Presets state={data} onChange={refresh} />
      <div className="grid-2">
        <QuoteCard s={data} />
        <LedgerCard s={data} />
      </div>
      <FlowDiagram onInspect={setTrace} />
      {trace && <OrderTrace correlationId={trace} onClose={() => setTrace(null)} />}
      <div className="grid-2">
        <BookLadder s={data} />
        <OrderEntry s={data} onDone={refresh} onTrace={setTrace} />
      </div>
      <Charts s={data} />
      <div className="grid-2">
        <TradesTape s={data} onTrace={setTrace} />
        <EventTimeline modules={["marketmaker"]} title="What just happened" limit={14} />
      </div>
      <Settings cfg={data.config} onDone={refresh} />
    </div>
  );
}

function ResetDemo({ onDone }: { onDone: () => void }) {
  const { busy, error, run } = useAction();
  return (
    <div>
      <button type="button" className="btn" disabled={busy} onClick={() => run(async () => { await mmApi.reset(); onDone(); })}>
        ↺ Reset Demo
      </button>
      <ErrorNote error={error} />
    </div>
  );
}

function Presets({ state, onChange }: { state: MMState; onChange: () => void }) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [last, setLast] = useState<{ title: string; observe: string; explanation?: string } | null>(null);
  const { busy, error, run } = useAction();
  useEffect(() => { void mmApi.presets().then(setPresets).catch(() => undefined); }, []);
  const active = state.preset;
  return (
    <Panel title="Guided demos" id="mm-presets" help={<><p>Step-by-step demos with fixed starting conditions, so every run gives the same numbers. Load one, then press “Run step” and read <b>What to notice</b>.</p><p>Loading a demo pauses the simulation clock so nothing else interferes.</p></>} actions={<span className="muted small">Deterministic: same steps, same results, every time</span>}>
      <div className="preset-row">
        {presets.map((p) => (
          <div key={p.id} className={`preset ${active?.id === p.id ? "active" : ""}`}>
            <h3>{p.title}</h3>
            <p className="small">{p.summary}</p>
            <button type="button" className="btn" disabled={busy} onClick={() => run(async () => { await mmApi.loadPreset(p.id); setLast(null); onChange(); })}>
              {active?.id === p.id ? "↺ Reset scenario" : "Load"}
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
            <button
              type="button" className="btn primary" disabled={busy || active.complete}
              onClick={() => run(async () => { setLast(await mmApi.stepPreset(active.id)); onChange(); })}
            >
              {active.complete ? "All steps done" : `Run step ${(active.next_step ?? 0) + 1}: ${active.steps[active.next_step ?? 0]?.title}`}
            </button>
          </div>
          {last && (
            <div className="observe" role="status">
              <strong>What to notice:</strong> {last.observe}
              {last.explanation && <p className="small muted">{last.explanation}</p>}
            </div>
          )}
        </div>
      )}
      <ErrorNote error={error} />
    </Panel>
  );
}

function QuoteCard({ s }: { s: MMState }) {
  const q = s.quote;
  return (
    <Panel title="Current quote" id="mm-quote" help={<><p>The <Term id="market_maker">market maker</Term>'s current <Term id="quote">quote</Term>: the <Term id="bid">bid</Term> is what it pays if you sell to it; the <Term id="ask">ask</Term> is what you pay to buy from it. The difference is the <Term id="spread">spread</Term>, its reward for always being available.</p><p>“Fair value” is the simulator's estimate of the true price; the quote is built around it and shifted by inventory (<Term id="skew">skew</Term>).</p></>}>
      <div className="quote-big">
        <div className="quote-side bid">
          <span className="quote-label">Bid · MM buys at</span>
          <span className="quote-px">{q?.bid ? fmtMoney(q.bid) : "no bid"}</span>
          <span className="small muted">{fmtNum(q?.bid_size)} shares</span>
        </div>
        <div className="quote-mid">
          <span className="small muted">Spread</span>
          <b>{q?.spread ? fmtMoney(q.spread) : "—"}</b>
          <span className="small muted">Fair {fmtMoney(s.fair_value)}</span>
        </div>
        <div className="quote-side ask">
          <span className="quote-label">Ask · MM sells at</span>
          <span className="quote-px">{q?.ask ? fmtMoney(q.ask) : "no offer"}</span>
          <span className="small muted">{fmtNum(q?.ask_size)} shares</span>
        </div>
      </div>
      <Explain
        simple={
          q && (Number(q.inventory) === 0
            ? "Inventory is flat, so the quote is centred on fair value."
            : Number(s.config.inventory_sensitivity) === 0
              ? `The market maker holds ${fmtNum(q.inventory)} shares, but inventory sensitivity is 0 in this scenario, so its quotes do not react to inventory.`
            : Number(q.inventory) > 0
              ? `The market maker holds ${fmtNum(q.inventory)} shares, so it has lowered both prices: selling becomes easier, buying more becomes less attractive.`
              : `The market maker is short ${fmtNum(-q.inventory)} shares, so it has raised both prices to attract sellers.`)
        }
        technical={
          q && (
            <p className="mono small">
              u = inventory / max = {q.inventory} / {s.config.max_inventory} = {Number(q.utilization).toFixed(3)}; skew = −{s.config.inventory_sensitivity} × u × {s.config.spread} = {Number(q.skew).toFixed(4)};
              reservation = {Number(q.reference).toFixed(4)} + skew = {Number(q.reservation).toFixed(4)}; bid = ⌊r − spread/2⌋ = {q.bid ?? "—"}, ask = ⌈r + spread/2⌉ = {q.ask ?? "—"} (tick {s.config.tick_size}).
            </p>
          )
        }
      />
    </Panel>
  );
}

function LedgerCard({ s }: { s: MMState }) {
  const l = s.ledger;
  const util = Math.abs(Number(l.inventory_utilization));
  return (
    <Panel title="Inventory & P&L" id="mm-ledger" help={<><p>The market maker's books. <Term id="inventory">Inventory</Term> is how many shares it holds (negative = <Term id="long_short">short</Term>). <Term id="realized">Realized</Term> P&L is locked in; <Term id="unrealized">unrealized</Term> P&L is what open positions are worth at today's fair value.</p><p>Net P&L = realized + unrealized − <Term id="fees">fees</Term>. “Gross spread captured” measures how far from fair value each trade was; it is <i>not</i> profit.</p></>} actions={<span className="muted small">marked at fair value {fmtMoney(l.mark_price)}</span>}>
      <div className="stats">
        <Stat label="Inventory" value={`${fmtNum(l.position)} sh`} hint={l.position > 0 ? "long" : l.position < 0 ? "short" : "flat"} raw={l.position} />
        <Stat label="Average cost" value={l.avg_cost ? fmtMoney(l.avg_cost, 4) : "—"} raw={l.avg_cost} />
        <Stat label="Cash" value={fmtMoney(l.cash)} raw={l.cash} />
        <Stat label="Net P&L" value={fmtSignedMoney(l.net_pnl)} tone={l.net_pnl} hint="realized + unrealized − fees" raw={l.net_pnl} />
        <Stat label="Realized P&L" value={fmtSignedMoney(l.realized_pnl)} tone={l.realized_pnl} raw={l.realized_pnl} />
        <Stat label="Unrealized P&L" value={fmtSignedMoney(l.unrealized_pnl)} tone={l.unrealized_pnl} raw={l.unrealized_pnl} />
        <Stat label="Fees paid" value={fmtMoney(l.fees)} raw={l.fees} />
        <Stat label="Gross spread captured" value={fmtSignedMoney(l.gross_spread_captured)} hint="edge vs. fair value; not net profit" raw={l.gross_spread_captured} />
      </div>
      <div className="meter" aria-label={`Inventory utilization ${fmtPct(util)}`}>
        <div className="meter-label small"><span>Inventory utilization</span><span>{fmtPct(util)} of ±{fmtNum(l.max_inventory)}</span></div>
        <div className="meter-track"><div className={`meter-fill ${util > 0.9 ? "danger" : util > 0.6 ? "warn" : ""}`} style={{ width: `${Math.min(100, util * 100)}%` }} /></div>
      </div>
      <TechOnly>
        <p className="mono small">
          Check: equity − initial cash = {fmtMoney(Number(l.equity) - Number(l.initial_cash), 4)} ; realized + unrealized − fees = {fmtMoney(l.net_pnl, 4)}.
          Open FIFO lots: {l.open_lots.length ? l.open_lots.map((x) => `${x.quantity}@${x.price}`).join(", ") : "none"}. Trades: {l.trade_count} ({fmtNum(l.buy_quantity)} bought / {fmtNum(l.sell_quantity)} sold).
        </p>
      </TechOnly>
    </Panel>
  );
}

const STAGES = [
  { key: "order", label: "Customer order", types: ["order.received"] },
  { key: "quote", label: "Quote", types: ["quote.updated"] },
  { key: "match", label: "Matching engine", types: ["order.resting", "order.canceled", "order.rejected", "trade.executed"] },
  { key: "trade", label: "Trade execution", types: ["trade.executed"] },
  { key: "inventory", label: "Inventory update", types: ["inventory.changed"] },
  { key: "pnl", label: "P&L update", types: ["pnl.updated"] },
];

/** Pipeline diagram driven only by real backend events of the latest customer order. */
function FlowDiagram({ onInspect }: { onInspect: (id: string) => void }) {
  const { events } = useStream();
  const chain = useMemo(() => {
    const mm = events.filter((e) => e.module === "marketmaker");
    const lastOrder = [...mm].reverse().find((e) => e.type === "order.received" && e.data.owner === "customer");
    if (!lastOrder) return null;
    const corr = lastOrder.correlation_id;
    const related = mm.filter((e) => e.correlation_id === corr);
    const quote = [...mm].reverse().find((e) => e.type === "quote.updated" && e.seq > lastOrder.seq);
    return { corr, related: quote ? [...related, quote] : related, order: lastOrder };
  }, [events]);
  const has = (types: string[]) => chain?.related.some((e) => types.includes(e.type));
  return (
    <Panel title="Order flow" id="mm-flow" help={<p>The path your last order took through the system. Each box lights up when the backend reports that step happened. Click “Trace this order” to see every recorded event for it.</p>} actions={chain?.corr && <button type="button" className="link" onClick={() => onInspect(chain.corr!)}>Trace this order →</button>}>
      <ol className="flow" key={chain?.corr ?? "none"}>
        {STAGES.map((st, i) => {
          const on = st.key === "quote" ? has(["quote.updated"]) || has(["trade.executed"]) : has(st.types);
          return (
            <li key={st.key} className={on ? "on" : ""} style={{ animationDelay: `${i * 90}ms` }}>
              <span className="flow-dot" aria-hidden="true">{on ? "●" : "○"}</span>
              <span>{st.label}</span>
            </li>
          );
        })}
      </ol>
      {chain ? (
        <ul className="flow-notes small">
          {chain.related.filter((e) => e.type !== "order.received").slice(0, 6).map((e: MarketLabEvent) => (
            <li key={e.seq}><span className="tag">{e.type}</span> {e.message}</li>
          ))}
        </ul>
      ) : (
        <p className="empty small">Send an order below (or run a guided demo step) to watch it travel through the pipeline. Synthetic orders are not shown here.</p>
      )}
    </Panel>
  );
}

function BookLadder({ s }: { s: MMState }) {
  const asks = [...s.book.asks].slice(0, 8).reverse();
  const bids = s.book.bids.slice(0, 8);
  const maxQ = Math.max(1, ...asks.map((l) => l.quantity), ...bids.map((l) => l.quantity));
  const row = (l: (typeof bids)[number], side: "bid" | "ask") => (
    <tr key={`${side}-${l.price}`} className={`ladder-${side}`}>
      <td className="num">{side === "bid" ? <Qty l={l} max={maxQ} side="bid" /> : ""}</td>
      <td className="num price">{fmtMoney(l.price)}</td>
      <td className="num">{side === "ask" ? <Qty l={l} max={maxQ} side="ask" /> : ""}</td>
    </tr>
  );
  return (
    <Panel title="Order book" id="mm-book" help={<p>The live <Term id="order_book">order book</Term>. Sellers (asks) are on top, buyers (bids) below; the bars show how many shares wait at each price. “MM” marks the market maker's own quotes, “C” customers' limit orders.</p>} actions={<span className="muted small">{s.stats.resting_orders} resting orders</span>}>
      <table className="ladder">
        <caption className="sr-only">Order book: bids and asks by price</caption>
        <thead><tr><th scope="col">Bid size</th><th scope="col">Price</th><th scope="col">Ask size</th></tr></thead>
        <tbody>
          {asks.length === 0 && <tr><td colSpan={3} className="empty small">No sellers</td></tr>}
          {asks.map((l) => row(l, "ask"))}
          <tr className="ladder-spread"><td colSpan={3}>spread {s.book.spread ? fmtMoney(s.book.spread) : "—"}</td></tr>
          {bids.map((l) => row(l, "bid"))}
          {bids.length === 0 && <tr><td colSpan={3} className="empty small">No buyers</td></tr>}
        </tbody>
      </table>
      <p className="small muted"><span className="chip mm">MM</span> market-maker quote · <span className="chip cust">C</span> customer limit orders</p>
    </Panel>
  );
}

function Qty({ l, max, side }: { l: { quantity: number; by_owner: Record<string, number> }; max: number; side: "bid" | "ask" }) {
  const mm = l.by_owner.mm ?? 0;
  const other = l.quantity - mm;
  return (
    <span className={`qty qty-${side}`}>
      <span className="qty-bar" style={{ width: `${(l.quantity / max) * 100}%` }} aria-hidden="true" />
      <span className="qty-text">
        {fmtNum(l.quantity)} {mm > 0 && <span className="chip mm" title={`${mm} from the market maker`}>MM</span>}
        {other > 0 && <span className="chip cust" title={`${other} from customers`}>C</span>}
      </span>
    </span>
  );
}

function OrderEntry({ s, onDone, onTrace }: { s: MMState; onDone: () => void; onTrace: (id: string) => void }) {
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [type, setType] = useState<"market" | "limit">("market");
  const [qty, setQty] = useState("100");
  const [price, setPrice] = useState("");
  const [tif, setTif] = useState("");
  const [key, setKey] = useState(() => crypto.randomUUID?.() ?? String(Date.now()));
  const [result, setResult] = useState<OrderResponse | null>(null);
  const { busy, error, run } = useAction();
  const cancel = useAction();

  useEffect(() => setKey(crypto.randomUUID?.() ?? String(Date.now())), [side, type, qty, price, tif]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const body: { side: string; type: string; quantity: number; limit_price?: string; tif?: string } = { side, type, quantity: Number(qty) };
      if (type === "limit") body.limit_price = price;
      if (tif) body.tif = tif;
      const r = await mmApi.submit(body, key);
      setResult(r);
      onDone();
    });
  };
  const open = s.customer_orders.filter((o) => o.status === "open" || o.status === "partially_filled");
  return (
    <Panel title="Place a customer order" id="mm-entry" help={<p>Act as a customer. A <Term id="market_order">market order</Term> trades now at the best price; a <Term id="limit_order">limit order</Term> waits unless someone matches your price. Each order carries an <Term id="idempotency">idempotency key</Term> so a retry never creates a duplicate.</p>}>
      <form className="order-form" onSubmit={submit}>
        <div className="segmented" role="group" aria-label="Side">
          <button type="button" aria-pressed={side === "buy"} onClick={() => setSide("buy")}>Buy</button>
          <button type="button" aria-pressed={side === "sell"} onClick={() => setSide("sell")}>Sell</button>
        </div>
        <label>Type
          <select value={type} onChange={(e) => setType(e.target.value as "market" | "limit")}>
            <option value="market">Market — trade now at the best price</option>
            <option value="limit">Limit — only at my price or better</option>
          </select>
        </label>
        <label>Quantity
          <input type="number" min={1} step={s.config.lot_size} value={qty} onChange={(e) => setQty(e.target.value)} required />
        </label>
        {type === "limit" && (
          <label>Limit price ($)
            <input type="number" min={0} step={s.config.tick_size} value={price} onChange={(e) => setPrice(e.target.value)} required placeholder={s.quote?.bid ?? ""} />
          </label>
        )}
        <TechOnly>
          <label>Time in force
            <select value={tif} onChange={(e) => setTif(e.target.value)}>
              <option value="">default ({type === "market" ? s.config.market_order_policy.toUpperCase() : "GTC"})</option>
              <option value="ioc">IOC</option><option value="fok">FOK</option>
              {type === "limit" && <option value="gtc">GTC</option>}
            </select>
          </label>
          <p className="mono small">Idempotency-Key: {key}</p>
        </TechOnly>
        <button type="submit" className={`btn primary ${side}`} disabled={busy}>{side === "buy" ? "Buy" : "Sell"} {fmtNum(qty)} shares</button>
      </form>
      <ErrorNote error={error} />
      {result && (
        <div className="result" role="status">
          <StatusBadge status={result.order.status} filled={result.order.filled_qty} quantity={result.order.quantity} />
          <p>{result.explanation}</p>
          <TechOnly>
            <p className="mono small">{result.order.id} · {result.trades.length} trade(s){result.idempotent_replay ? " · idempotent replay" : ""}</p>
          </TechOnly>
          <button type="button" className="link" onClick={() => onTrace(result.order.correlation_id ?? result.order.id)}>Trace this order →</button>
        </div>
      )}
      <h3 className="sub">Your open orders</h3>
      {open.length === 0 ? <p className="empty small">No resting orders. Limit orders that do not execute immediately wait here.</p> : (
        <table className="table compact">
          <thead><tr><th>Side</th><th className="num">Qty</th><th className="num">Filled</th><th className="num">Limit</th><th>Status</th><th /></tr></thead>
          <tbody>
            {open.map((o: Order) => (
              <tr key={o.id}>
                <td>{o.side}</td><td className="num">{fmtNum(o.quantity)}</td><td className="num">{fmtNum(o.filled_qty)}</td>
                <td className="num">{o.limit_price ? fmtMoney(o.limit_price) : "—"}</td>
                <td><StatusBadge status={o.status} /></td>
                <td><button type="button" className="link" disabled={cancel.busy} onClick={() => cancel.run(async () => { await mmApi.cancel(o.id); onDone(); })}>Cancel</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ErrorNote error={cancel.error} />
      <RecentOrders orders={s.customer_orders.filter((o) => !(o.status === "open" || o.status === "partially_filled")).slice(0, 6)} onTrace={onTrace} />
    </Panel>
  );
}

function RecentOrders({ orders, onTrace }: { orders: Order[]; onTrace: (id: string) => void }) {
  if (!orders.length) return null;
  return (
    <>
      <h3 className="sub">Order history</h3>
      <table className="table compact">
        <thead><tr><th>Time</th><th>Order</th><th className="num">Filled</th><th className="num">Avg price</th><th>Status</th></tr></thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id}>
              <td>{shortTime(o.created_ts)}</td>
              <td><button type="button" className="link" onClick={() => onTrace(o.correlation_id ?? o.id)}>{o.side} {o.type} {fmtNum(o.quantity)}</button></td>
              <td className="num">{fmtNum(o.filled_qty)}</td>
              <td className="num">{o.avg_fill_price ? fmtMoney(o.avg_fill_price, 4) : "—"}</td>
              <td><StatusBadge status={o.status} filled={o.filled_qty} quantity={o.quantity} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function Charts({ s }: { s: MMState }) {
  const pts = s.series;
  return (
    <div className="grid-3">
      <Panel>
        <LineChart
          title="Fair value and quotes ($)" stepped xLabel="update"
          series={[
            { key: "ask", label: "Ask", slot: 2, points: pts.map((p) => ({ x: p.n, y: p.ask === null ? null : Number(p.ask) })) },
            { key: "fair", label: "Fair value", slot: 1, points: pts.map((p) => ({ x: p.n, y: Number(p.fair) })) },
            { key: "bid", label: "Bid", slot: 3, points: pts.map((p) => ({ x: p.n, y: p.bid === null ? null : Number(p.bid) })) },
          ]}
          yFormat={(v) => `$${v.toFixed(2)}`}
        />
      </Panel>
      <Panel>
        <LineChart title="Inventory (shares)" stepped zeroLine xLabel="update" series={[{ key: "inv", label: "Inventory", slot: 1, points: pts.map((p) => ({ x: p.n, y: p.inventory })) }]} yFormat={(v) => fmtNum(v)} />
      </Panel>
      <Panel>
        <LineChart title="Net P&L ($)" zeroLine xLabel="update" series={[{ key: "pnl", label: "Net P&L", slot: 1, points: pts.map((p) => ({ x: p.n, y: Number(p.net_pnl) })) }]} yFormat={(v) => fmtMoney(v)} />
      </Panel>
    </div>
  );
}

function TradesTape({ s, onTrace }: { s: MMState; onTrace: (id: string) => void }) {
  return (
    <Panel title="Recent trades" id="mm-trades" help={<p>Every executed trade, newest first. “▲ bought / ▼ sold” is from the market maker's point of view; synthetic customers trade too while the clock runs.</p>}>
      {s.trades.length === 0 ? <p className="empty">No trades yet.</p> : (
        <div className="scroll">
          <table className="table compact">
            <thead><tr><th>Tick</th><th className="num">Price</th><th className="num">Qty</th><th>Market maker</th><th>Counterparties</th><TechOnly><th>ID</th></TechOnly></tr></thead>
            <tbody>
              {s.trades.slice(0, 25).map((t) => (
                <tr key={t.id}>
                  <td>{t.tick}</td>
                  <td className="num">{fmtMoney(t.price)}</td>
                  <td className="num">{fmtNum(t.quantity)}</td>
                  <td>{t.mm_side ? <span className={`side side-${t.mm_side}`}>{t.mm_side === "buy" ? "▲ bought" : "▼ sold"}</span> : <span className="muted">not involved</span>}</td>
                  <td className="small">{t.taker_owner} → {t.maker_owner}</td>
                  <TechOnly><td><button type="button" className="link mono small" onClick={() => onTrace(t.correlation_id ?? t.id)}>{t.id}</button></td></TechOnly>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

const FIELDS: { k: keyof MMConfig; label: string; help: string; step?: string }[] = [
  { k: "fair_value", label: "Fair value ($)", help: "Starting reference price", step: "0.01" },
  { k: "spread", label: "Quote spread ($)", help: "Gap between bid and ask", step: "0.01" },
  { k: "quote_size", label: "Quote size", help: "Shares offered per level" },
  { k: "quote_levels", label: "Quote levels", help: "Price levels on each side" },
  { k: "max_inventory", label: "Max inventory", help: "Stop quoting a side at this limit" },
  { k: "inventory_sensitivity", label: "Inventory sensitivity", help: "How strongly inventory skews quotes", step: "0.1" },
  { k: "volatility", label: "Volatility ($/tick)", help: "Random fair-value move per second", step: "0.01" },
  { k: "arrival_rate", label: "Order arrival rate", help: "Synthetic orders per second", step: "0.1" },
  { k: "buy_probability", label: "Buy probability", help: "Share of customer orders that are buys", step: "0.05" },
  { k: "limit_order_fraction", label: "Limit-order share", help: "Share of synthetic orders that are limits", step: "0.05" },
  { k: "customer_order_size", label: "Customer order size", help: "Typical synthetic order size" },
  { k: "fee_per_share", label: "Fee per share ($)", help: "Charged to each side of every trade", step: "0.001" },
  { k: "tick_size", label: "Tick size ($)", help: "Minimum price increment", step: "0.01" },
  { k: "lot_size", label: "Lot size", help: "Quantities must be multiples" },
  { k: "market_order_policy", label: "Market-order remainder", help: "ioc: cancel unfilled rest · fok: all-or-nothing" },
];

function Settings({ cfg, onDone }: { cfg: MMConfig; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<MMConfig>(cfg);
  const { busy, error, run } = useAction();
  const [details, setDetails] = useState<string[]>([]);
  useEffect(() => { if (!open) setDraft(cfg); }, [cfg, open]);
  const apply = (e: FormEvent) => {
    e.preventDefault();
    setDetails([]);
    void run(async () => {
      try {
        await mmApi.putConfig(draft);
        onDone();
      } catch (err) {
        if (err instanceof ApiError && Array.isArray(err.details)) {
          setDetails((err.details as { loc: string[]; msg: string }[]).map((d) => `${d.loc.slice(1).join(".") || "config"}: ${d.msg}`));
        }
        throw err;
      }
    });
  };
  return (
    <Panel title="Simulation settings" id="mm-settings" help={<p>Change the simulated market: the market maker's spread and limits, how much prices move (volatility), how many customers arrive and which way they lean, fees and tick size. Invalid combinations are rejected with an explanation.</p>} actions={<button type="button" className="btn" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"}</button>}>
      {!open ? <p className="small muted">Adjust fair value, spread, inventory limits, volatility, order flow and fees. Changes are validated by the backend.</p> : (
        <form onSubmit={apply}>
          <div className="form-grid">
            {FIELDS.map((f) => (
              <label key={f.k}>
                {f.label}
                {f.k === "market_order_policy" ? (
                  <select value={draft.market_order_policy} onChange={(e) => setDraft({ ...draft, market_order_policy: e.target.value as "ioc" | "fok" })}>
                    <option value="ioc">IOC</option><option value="fok">FOK</option>
                  </select>
                ) : (
                  <input
                    type="number" step={f.step ?? "1"} value={String(draft[f.k])}
                    onChange={(e) => setDraft({ ...draft, [f.k]: typeof cfg[f.k] === "number" ? Number(e.target.value) : e.target.value })}
                  />
                )}
                <span className="small muted">{f.help}</span>
              </label>
            ))}
          </div>
          <button type="submit" className="btn primary" disabled={busy}>Apply settings</button>
          <ErrorNote error={error} />
          {details.length > 0 && <ul className="error-text small">{details.map((d) => <li key={d}>{d}</li>)}</ul>}
          <SimpleOnly><p className="small muted">Tip: raise “Buy probability” to 0.9 and press Start to watch inventory risk build up.</p></SimpleOnly>
          <TechOnly><JsonBlock value={cfg} label="Current configuration (JSON)" /></TechOnly>
        </form>
      )}
    </Panel>
  );
}
