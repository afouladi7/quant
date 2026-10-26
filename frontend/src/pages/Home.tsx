import { useState } from "react";
import { Link } from "react-router-dom";
import { NAV } from "../nav";
import { LESSONS } from "../learn/lessons";
import { useProgress } from "../learn/progress";

const PATHS = [
  {
    id: "new", title: "I'm new to finance",
    text: "Start with how a market works: buyers, sellers, prices. No maths needed.",
    steps: [
      { to: "/learn/what-is-a-market", label: "Lesson: What is a market?" },
      { to: "/playground", label: "Place your first orders in the playground" },
      { to: "/market-maker", label: "Run the Spread Capture demo" },
    ],
  },
  {
    id: "some", title: "I know the basics",
    text: "Go deeper into how traders manage risk: inventory, routing, hedging and volatility.",
    steps: [
      { to: "/market-maker", label: "Inventory Risk demo" },
      { to: "/fx", label: "FX routing scenarios" },
      { to: "/risk", label: "Risk & returns lab" },
    ],
  },
  {
    id: "quant", title: "I'm a quant or engineer",
    text: "Models, formulas and the system underneath: options pricing, risk statistics, latency and the backend.",
    steps: [
      { to: "/options", label: "Options lab: Black-Scholes and Greeks" },
      { to: "/how-it-works", label: "How the backend works (live)" },
      { to: "/tcp-lab", label: "TCP latency lab" },
    ],
  },
];

export function Home() {
  const [path, setPath] = useState<string | null>(null);
  const { done } = useProgress();
  const chosen = PATHS.find((p) => p.id === path);
  return (
    <div className="page">
      <section className="hero">
        <h1>Learn how markets, trading risk and trading systems really work</h1>
        <p className="lead">
          MarketLab is a hands-on laboratory. Instead of reading about an order book, you place orders and watch them match.
          Instead of a formula for risk, you simulate prices and measure it. Everything here is simulated: no real money,
          no real market data.
        </p>
      </section>

      <section aria-labelledby="start-title" className="panel">
        <h2 id="start-title">Where should I start?</h2>
        <div className="paths" role="group" aria-label="Choose your starting point">
          {PATHS.map((p) => (
            <button key={p.id} type="button" className={`path ${path === p.id ? "active" : ""}`} aria-pressed={path === p.id} onClick={() => setPath(p.id)}>
              <b>{p.title}</b>
              <span>{p.text}</span>
            </button>
          ))}
        </div>
        {chosen && (
          <ol className="path-steps">
            {chosen.steps.map((s) => <li key={s.to + s.label}><Link to={s.to}>{s.label} →</Link></li>)}
          </ol>
        )}
        <p className="small muted">
          Learning path progress: {done.size} of {LESSONS.length} lessons complete. <Link to="/learn">Open the learning path →</Link>
        </p>
      </section>

      {NAV.slice(1).map((g) => (
        <section key={g.title} aria-labelledby={`g-${g.title}`}>
          <h2 id={`g-${g.title}`} className="section-title">{g.title}</h2>
          <div className="cards">
            {g.items.map((i) => (
              <Link key={i.to} to={i.to} className="card">
                <span className={`lvl lvl-${i.level.toLowerCase().replace(" ", "-")}`}>{i.level}</span>
                <h3>{i.label}</h3>
                <p>{i.blurb}</p>
                <span className="card-cta">Open →</span>
              </Link>
            ))}
          </div>
        </section>
      ))}

      <section className="panel how-to-use">
        <h2>How to use MarketLab</h2>
        <ul>
          <li><b>Simple / Technical</b> (top right): Simple explains in plain English; Technical adds IDs, formulas and raw data.</li>
          <li><b>Dotted-underlined words</b> are glossary terms: hover or tab to them for a definition.</li>
          <li><b>The ? button</b> on a panel explains what you're looking at.</li>
          <li><b>Guided demos</b> on each page run step by step and always give the same results, so you can repeat them.</li>
        </ul>
      </section>
    </div>
  );
}
