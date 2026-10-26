import { Link } from "react-router-dom";
import { EventTimeline } from "../components/EventTimeline";
import { Panel } from "../components/ui";
import { MODULES } from "./modules";

const PRESETS = [
  { n: 1, title: "Spread Capture", to: "/market-maker", what: "Buy at the bid, sell at the ask, pay fees — then watch a price move erase the profit." },
  { n: 2, title: "Inventory Risk", to: "/market-maker", what: "Sustained customer buying pushes the market maker short and its quotes upward." },
  { n: 3, title: "Fragmented FX Liquidity", to: "/fx", what: "Six scenarios comparing price, depth, fees and latency across books A, B and C." },
  { n: 4, title: "GBP Hedging", to: "/fx?tab=hedging", what: "Buy GBP 1m, move the rate, hedge with an FX offset or futures, compare before and after." },
  { n: 5, title: "TCP Latency", to: "/tcp-lab", what: "Complete vs. split messages, cold vs. pre-established connections, useful early work." },
];

export function Home() {
  return (
    <div className="page">
      <section className="hero">
        <h1>An interactive laboratory for markets and networks</h1>
        <p className="lead">
          MarketLab is an interactive laboratory for understanding how financial markets work, how traders manage risk,
          and how software networking affects performance. Every trade and price in the simulator is hypothetical.
        </p>
      </section>

      <div className="cards">
        {MODULES.map((m) => (
          <Link key={m.path} to={m.path} className="card" aria-describedby={`${m.key}-desc`}>
            <div className="card-icon" aria-hidden="true">{m.icon}</div>
            <h2>{m.title}</h2>
            <p id={`${m.key}-desc`}>{m.summary}</p>
            <ul className="card-list small">{m.highlights.map((h) => <li key={h}>{h}</li>)}</ul>
            <span className="card-cta">Open module →</span>
          </Link>
        ))}
      </div>

      <Panel title="Guided demo presets" id="home-presets" actions={<span className="small muted">deterministic and resettable; no live data needed</span>}>
        <ol className="preset-links">
          {PRESETS.map((p) => (
            <li key={p.n}>
              <Link to={p.to}><b>{p.n}. {p.title}</b></Link>
              <span className="small muted"> — {p.what}</span>
            </li>
          ))}
        </ol>
      </Panel>

      <EventTimeline />
    </div>
  );
}
