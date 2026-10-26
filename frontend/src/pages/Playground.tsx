import { useCallback, useEffect, useState, type FormEvent } from "react";
import { http } from "../api/client";
import { StartHere, Term } from "../components/learn";
import { ErrorNote, Panel, StatusBadge, TechOnly, useAction } from "../components/ui";

interface PgOrder { label: string; trader: string; remaining: number; id: string }
interface PgLevel { price: string; total: number; orders: PgOrder[] }
interface PgState {
  instrument: string; best_bid: string | null; best_ask: string | null; spread: string | null; traders: string[];
  bids: PgLevel[]; asks: PgLevel[];
  trades: { id: string; price: string; quantity: number; buyer: string; seller: string; aggressor: string; taker_label: string; maker_label: string }[];
  history: { label: string; trader: string; side: string; type: string; quantity: number; price: string | null; status: string; filled: number; steps: string[] }[];
}
interface PlaceResult { label: string; steps: string[]; order: { status: string; filled_qty: number; quantity: number; id: string } }

const EXAMPLES = [
  { label: "You buy 7 at up to $102", body: { trader: "you", side: "buy", type: "limit", quantity: 7, price: "102" }, lesson: "Two sellers at $101: who goes first?" },
  { label: "You buy 5 at up to $100", body: { trader: "you", side: "buy", type: "limit", quantity: 5, price: "100" }, lesson: "Nobody sells that cheap: the order waits." },
  { label: "Bob sells 20 at market", body: { trader: "bob", side: "sell", type: "market", quantity: 20 }, lesson: "Bob meets his own order, and the book runs out." },
  { label: "Carol sells 2 at $100", body: { trader: "carol", side: "sell", type: "limit", quantity: 2, price: "100" }, lesson: "Matches a waiting bid if there is one at $100." },
];

const name = (t: string) => (t === "you" ? "You" : t[0].toUpperCase() + t.slice(1));

export function Playground() {
  const [s, setS] = useState<PgState | null>(null);
  const [last, setLast] = useState<PlaceResult | null>(null);
  const { busy, error, run } = useAction();
  const refresh = useCallback(async () => setS(await http.get<PgState>("/playground")), []);
  useEffect(() => { void run(refresh); }, [refresh]); // eslint-disable-line react-hooks/exhaustive-deps

  const place = (body: unknown) => run(async () => { setLast(await http.post<PlaceResult>("/playground/orders", body)); await refresh(); });

  return (
    <div className="page">
      <header>
        <h1>Order book playground</h1>
        <p className="lead">
          A tiny market for one made-up stock, <b>TOY</b>. Alice, Bob and Carol already have orders waiting. Send your own (or theirs)
          and the matching engine explains every decision it makes. This is the same engine the rest of MarketLab uses.
        </p>
      </header>
      <StartHere steps={[
        <>Look at the <Term id="order_book">order book</Term> below: buyers on the left, sellers on the right, best prices in the middle.</>,
        <>Click an example such as <b>“You buy 7 at up to $102”</b>.</>,
        <>Read <b>What the engine did</b>: each step explains which order matched and why.</>,
      ]} />
      <ErrorNote error={error} />
      <div className="grid-2">
        <Panel title="Send an order" id="pg-ticket" help={
          <p>Pick who is trading, whether they buy or sell, and how. A <Term id="limit_order">limit order</Term> sets the worst price you accept and may wait in the book.
            A <Term id="market_order">market order</Term> trades immediately with whatever is available. Prices are whole dollars to keep it simple.</p>
        }>
          <div className="examples" role="group" aria-label="Examples">
            {EXAMPLES.map((e) => (
              <button key={e.label} type="button" className="example" disabled={busy} onClick={() => void place(e.body)}>
                <b>{e.label}</b><span className="small muted">{e.lesson}</span>
              </button>
            ))}
          </div>
          <OrderForm traders={s?.traders ?? ["you", "alice", "bob", "carol"]} busy={busy} onSend={place} />
        </Panel>
        <Panel title="What the engine did" id="pg-explain" help={<p>A plain-English replay of what the matching engine actually did with the last order, in the order it did it.</p>}>
          {!last ? <p className="empty">Send an order to see a step-by-step explanation here.</p> : (
            <>
              <div className="panel-head"><b>Order {last.label}</b><StatusBadge status={last.order.status} filled={last.order.filled_qty} quantity={last.order.quantity} /></div>
              <ol className="steps-explained">{last.steps.map((st, i) => <li key={i} style={{ animationDelay: `${i * 80}ms` }}>{st}</li>)}</ol>
            </>
          )}
        </Panel>
      </div>
      {s && <BookView s={s} onChange={refresh} />}
      {s && (
        <div className="grid-2">
          <Panel title="Trades" id="pg-trades" help={<p>Every completed trade. The price is always the price of the order that was waiting (the <Term id="maker_taker">maker</Term>).</p>}>
            {s.trades.length === 0 ? <p className="empty">No trades yet.</p> : (
              <table className="table compact">
                <thead><tr><th>Buyer</th><th>Seller</th><th className="num">Qty</th><th className="num">Price</th><TechOnly><th>Orders</th></TechOnly></tr></thead>
                <tbody>{s.trades.map((t) => (
                  <tr key={t.id}><td>{name(t.buyer)}</td><td>{name(t.seller)}</td><td className="num">{t.quantity}</td><td className="num">${t.price}</td>
                    <TechOnly><td className="small mono">{t.taker_label} took {t.maker_label}</td></TechOnly></tr>
                ))}</tbody>
              </table>
            )}
          </Panel>
          <Panel title="Earlier orders" id="pg-history">
            {s.history.length === 0 ? <p className="empty">Your orders and their explanations will be listed here.</p> : (
              <ul className="history">{s.history.map((h) => (
                <li key={h.label}>
                  <details>
                    <summary>{h.label}: {name(h.trader)} {h.side} {h.quantity} {h.type === "market" ? "at market" : `at $${h.price}`} · <StatusBadge status={h.status} filled={h.filled} quantity={h.quantity} /></summary>
                    <ol className="small">{h.steps.map((st, i) => <li key={i}>{st}</li>)}</ol>
                  </details>
                </li>
              ))}</ul>
            )}
          </Panel>
        </div>
      )}
      <div className="form-row">
        <button type="button" className="btn" disabled={busy} onClick={() => void run(async () => { await http.post("/playground/reset", { seed: true }); setLast(null); await refresh(); })}>↺ Reset to the example book</button>
        <button type="button" className="btn" disabled={busy} onClick={() => void run(async () => { await http.post("/playground/reset", { seed: false }); setLast(null); await refresh(); })}>Start with an empty book</button>
      </div>
    </div>
  );
}

function OrderForm({ traders, busy, onSend }: { traders: string[]; busy: boolean; onSend: (b: unknown) => void }) {
  const [trader, setTrader] = useState("you");
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [type, setType] = useState<"limit" | "market">("limit");
  const [qty, setQty] = useState("3");
  const [price, setPrice] = useState("100");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSend({ trader, side, type, quantity: Number(qty), ...(type === "limit" ? { price } : {}) });
  };
  return (
    <form className="order-form" onSubmit={submit}>
      <h3 className="sub">Or build your own</h3>
      <div className="form-row">
        <label>Trader<select value={trader} onChange={(e) => setTrader(e.target.value)}>{traders.map((t) => <option key={t} value={t}>{name(t)}</option>)}</select></label>
        <label>Side<select value={side} onChange={(e) => setSide(e.target.value as "buy" | "sell")}><option value="buy">Buy</option><option value="sell">Sell</option></select></label>
        <label>Type<select value={type} onChange={(e) => setType(e.target.value as "limit" | "market")}><option value="limit">Limit (set a price)</option><option value="market">Market (trade now)</option></select></label>
      </div>
      <div className="form-row">
        <label>Quantity<input type="number" min={1} max={1000} value={qty} onChange={(e) => setQty(e.target.value)} required /></label>
        {type === "limit" && <label>Price ($, whole dollars)<input type="number" min={1} step={1} value={price} onChange={(e) => setPrice(e.target.value)} required /></label>}
        <button type="submit" className={`btn primary ${side}`} disabled={busy}>Send {side} order</button>
      </div>
    </form>
  );
}

function BookView({ s, onChange }: { s: PgState; onChange: () => void }) {
  const cancel = useAction();
  const side = (levels: PgLevel[], kind: "bid" | "ask") => (
    <div className={`pg-side pg-${kind}`}>
      <h3 className="sub">{kind === "bid" ? "Buyers (bids): highest first" : "Sellers (asks): lowest first"}</h3>
      {levels.length === 0 ? <p className="empty small">No {kind === "bid" ? "buyers" : "sellers"}.</p> : (
        <ol className="pg-levels">
          {levels.map((l) => (
            <li key={l.price}>
              <span className="pg-price">${l.price}</span>
              <span className="pg-queue" aria-label={`Queue at $${l.price}, first in line first`}>
                {l.orders.map((o, i) => (
                  <span key={o.id} className={`pg-order owner-${o.trader}`} title={`${o.label}: ${name(o.trader)} wants to ${kind === "bid" ? "buy" : "sell"} ${o.remaining}${i === 0 ? " (first in line)" : ""}`}>
                    <span className="pg-pos">{i + 1}</span> {name(o.trader)} · {o.remaining}
                    <TechOnly><span className="mono small"> {o.label}</span></TechOnly>
                    {o.trader === "you" && <button type="button" className="link small" disabled={cancel.busy} onClick={() => cancel.run(async () => { await http.del(`/playground/orders/${o.id}`); onChange(); })} aria-label={`Cancel ${o.label}`}>✕</button>}
                  </span>
                ))}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
  return (
    <Panel title="The order book" id="pg-book" help={
      <>
        <p>Each row is a price. The chips are the individual orders waiting at that price, <b>in the order they arrived</b>; number 1 is first in line.</p>
        <p>An incoming buy order is matched against the sellers from the lowest price up; a sell order against the buyers from the highest price down.
          This is <Term id="price_time">price-time priority</Term>.</p>
      </>
    }>
      <div className="pg-summary">
        <span>Best <Term id="bid">bid</Term>: <b>{s.best_bid ? `$${s.best_bid}` : "none"}</b></span>
        <span>Best <Term id="ask">ask</Term>: <b>{s.best_ask ? `$${s.best_ask}` : "none"}</b></span>
        <span><Term id="spread">Spread</Term>: <b>{s.spread ? `$${s.spread}` : "—"}</b></span>
      </div>
      <div className="pg-book">
        {side(s.bids, "bid")}
        {side(s.asks, "ask")}
      </div>
      <ErrorNote error={cancel.error} />
    </Panel>
  );
}
