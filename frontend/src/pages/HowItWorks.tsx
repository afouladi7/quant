import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { http } from "../api/client";
import { getCalls, subscribeCalls, type RecordedCall } from "../api/inspector";
import { EventTimeline } from "../components/EventTimeline";
import { StartHere, Term } from "../components/learn";
import { ErrorNote, Panel, TechOnly, useAction } from "../components/ui";

const SRC = "https://github.com/afouladi7/quant/blob/main/";

const JOURNEY = [
  { who: "Your browser", what: "You click “Buy”. The page (React, TypeScript) sends an HTTP request such as POST /api/v1/playground/orders with the order as JSON.", file: "frontend/src/api/client.ts" },
  { who: "Web server (nginx)", what: "Serves the web pages and forwards anything under /api to the backend. In OpenShift this is the only part exposed to the outside.", file: "frontend/nginx/nginx.conf.template" },
  { who: "API layer (FastAPI)", what: "Checks the request is valid (e.g. quantity is positive, price is on a tick) and rejects bad input with a clear error. Typed models describe every request and response.", file: "backend/app/api/v1/playground.py" },
  { who: "Matching engine", what: "Looks at the order book, matches the order by price-time priority, records trades and updates who owns what. All prices use exact decimals, never floating point.", file: "backend/app/markets/venue.py" },
  { who: "Accounting", what: "Updates cash, inventory and profit & loss from each trade, using first-in-first-out lots so every number reconciles.", file: "backend/app/markets/ledger.py" },
  { who: "Event bus", what: "Every step (order received, trade executed, P&L updated) becomes an event with a timestamp and ID. Events are kept in a bounded history and optionally archived to PostgreSQL.", file: "backend/app/events/bus.py" },
  { who: "WebSocket", what: "Events are pushed to every open browser over a long-lived connection, so timelines and charts update live without refreshing.", file: "backend/app/api/v1/events.py" },
  { who: "Back in your browser", what: "The page receives the response (and the events), then redraws the book, charts and explanations. The browser never calculates prices or P&L itself: the backend is the single source of truth.", file: "frontend/src/lib/useLive.ts" },
];

const MODULES = [
  { name: "Simulation clock", file: "backend/app/simulation/orchestrator.py", what: "Start/pause/reset, speed, and a seeded random generator per module so runs are repeatable." },
  { name: "Order book & venue", file: "backend/app/markets/book.py", what: "Price levels with first-in-first-out queues; the venue adds validation, fees and order states." },
  { name: "Market maker", file: "backend/app/marketmaker/service.py", what: "Quotes with inventory skew, synthetic customers, presets." },
  { name: "FX books & router", file: "backend/app/fx/router.py", what: "Books A/B/C and the smart router that splits parent orders by effective cost." },
  { name: "Portfolio & hedging", file: "backend/app/portfolio/service.py", what: "Currency balances, exposure, futures and hedge proposals." },
  { name: "Options & risk labs", file: "backend/app/quant/options.py", what: "Black-Scholes, Greeks, binomial trees, simulated returns and risk statistics." },
  { name: "TCP lab", file: "backend/app/tcplab/server.py", what: "A raw TCP server and HTTP target that only process complete messages, plus the benchmark client." },
  { name: "Persistence (optional)", file: "backend/app/persistence/sink.py", what: "Background writer that archives events, trades and benchmarks to PostgreSQL." },
];

const IDEAS = [
  { t: "The backend is the single source of truth", d: "Prices, fills and P&L are only ever calculated on the server. The browser displays them. This avoids two copies of the truth disagreeing." },
  { t: "Exact money", d: "Prices and cash use Decimal numbers, so 0.1 + 0.2 is exactly 0.3. Binary floating point would slowly introduce rounding errors into accounts." },
  { t: "No duplicate orders", d: "Each order carries an idempotency key. If the network hiccups and the browser retries, the server returns the original result instead of trading twice." },
  { t: "Repeatable randomness", d: "Simulations use seeded random generators, so a guided demo gives the same numbers every time, which makes them teachable and testable." },
  { t: "Bounded memory", d: "Histories, queues and order lists have size limits, so the app can run for weeks without slowly eating memory." },
  { t: "Everything is an event", d: "A single, ordered event log powers the timelines, the order traces and the database archive." },
];

export function HowItWorks() {
  const calls = useSyncExternalStore(subscribeCalls, getCalls);
  const [selected, setSelected] = useState<number | null>(null);
  const demo = useAction();
  return (
    <div className="page">
      <header>
        <h1>How it works</h1>
        <p className="lead">
          What actually happens when you click a button? This page follows a single order from your browser, through the{" "}
          <Term id="backend">backend</Term>, and back, and shows the real requests this browser is making, live.
        </p>
      </header>
      <StartHere steps={[
        "Read the journey of a click below, top to bottom.",
        <>Press <b>Send a test order</b>: a real request appears in the inspector, and the events it caused appear in the timeline.</>,
        "Open the API explorer at the bottom and try a few endpoints yourself.",
      ]} />

      <Panel title="The journey of a click" id="hw-journey" help={<p>Each box is a separate piece of software with one job. Switch to Technical view to see the source file for each step.</p>}>
        <ol className="journey">
          {JOURNEY.map((j, i) => (
            <li key={j.who}>
              <span className="journey-n" aria-hidden="true">{i + 1}</span>
              <div>
                <b>{j.who}</b>
                <p>{j.what}</p>
                <TechOnly><a className="small mono" href={SRC + j.file} target="_blank" rel="noreferrer">{j.file}</a></TechOnly>
              </div>
            </li>
          ))}
        </ol>
      </Panel>

      <div className="grid-2">
        <Panel title="Live request inspector" id="hw-inspector"
          actions={<button type="button" className="btn primary" disabled={demo.busy} onClick={() => demo.run(() => http.post("/playground/orders", { trader: "alice", side: "buy", type: "limit", quantity: 1, price: "97" }))}>Send a test order</button>}
          help={<p>Every request this browser has sent to the backend <Term id="api">API</Term>, newest first: method, address, result code and how long it took. Click one to see what was sent and received.</p>}>
          <ErrorNote error={demo.error} />
          {calls.length === 0 ? <p className="empty">No requests yet.</p> : (
            <div className="scroll">
              <table className="table compact">
                <thead><tr><th>Method</th><th>Path</th><th className="num">Status</th><th className="num">Time</th></tr></thead>
                <tbody>
                  {calls.slice(0, 25).map((c) => (
                    <tr key={c.id} className={selected === c.id ? "row-on" : ""} onClick={() => setSelected(selected === c.id ? null : c.id)} style={{ cursor: "pointer" }}>
                      <td className="mono small">{c.method}</td>
                      <td className="mono small">/api/v1{c.path}</td>
                      <td className={`num ${c.status >= 400 || c.status === 0 ? "neg" : ""}`}>{c.status || "—"}</td>
                      <td className="num">{c.ms.toFixed(0)} ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {selected !== null && <CallDetail call={calls.find((c) => c.id === selected)} />}
          <p className="small muted">Status 2xx = success, 4xx = the request was refused (e.g. invalid input), 5xx = server error. Pages refresh their data by re-requesting it when events arrive.</p>
        </Panel>
        <EventTimeline title="Events the backend recorded" limit={14} />
      </div>

      <Panel title="Ideas that make it reliable" id="hw-ideas">
        <div className="ideas">{IDEAS.map((i) => <div key={i.t} className="idea"><b>{i.t}</b><p className="small">{i.d}</p></div>)}</div>
      </Panel>

      <Panel title="Backend map" id="hw-map" help={<p>The backend is one Python program organised into modules. Each link opens the source code on GitHub.</p>}>
        <table className="table">
          <thead><tr><th>Module</th><th>What it does</th><th>Source</th></tr></thead>
          <tbody>{MODULES.map((m) => <tr key={m.name}><td><b>{m.name}</b></td><td className="small">{m.what}</td><td><a className="small mono" href={SRC + m.file} target="_blank" rel="noreferrer">{m.file.split("/").slice(-2).join("/")}</a></td></tr>)}</tbody>
        </table>
        <h3 className="sub">How it runs on OpenShift</h3>
        <p className="small">
          Three containers (pods): the <b>frontend</b> (nginx serving the pages), the <b>backend</b> (this Python program) and optionally
          <b> PostgreSQL</b> for history. Only the frontend is reachable from outside (through an OpenShift Route with HTTPS);
          network policies stop anything except the frontend from talking to the backend, and anything except the backend from
          talking to the database. Containers run without root privileges and with read-only file systems.
        </p>
      </Panel>

      <ApiExplorer />
    </div>
  );
}

function CallDetail({ call }: { call?: RecordedCall }) {
  if (!call) return null;
  let pretty = call.responsePreview ?? "";
  try { pretty = JSON.stringify(JSON.parse(pretty), null, 2); } catch { /* truncated preview */ }
  return (
    <div className="call-detail">
      <p className="small mono">{call.method} /api/v1{call.path} → {call.status} in {call.ms.toFixed(1)} ms</p>
      {call.requestBody !== undefined && <><b className="small">Sent</b><pre className="event-detail">{JSON.stringify(call.requestBody, null, 2)}</pre></>}
      <b className="small">Received (first 600 characters)</b><pre className="event-detail">{pretty || "(empty)"}</pre>
    </div>
  );
}

interface OpenApiOp { summary?: string; description?: string; tags?: string[] }
type OpenApi = { paths: Record<string, Record<string, OpenApiOp>> };

function ApiExplorer() {
  const [spec, setSpec] = useState<OpenApi | null>(null);
  const [tag, setTag] = useState("all");
  const [out, setOut] = useState<{ path: string; body: string } | null>(null);
  const { busy, error, run } = useAction();
  useEffect(() => { void run(async () => setSpec(await fetch("/api/v1/openapi.json").then((r) => r.json()))); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const ops = useMemo(() => {
    if (!spec?.paths) return [];
    return Object.entries(spec.paths).flatMap(([path, methods]) =>
      Object.entries(methods).map(([method, op]) => ({ path, method: method.toUpperCase(), tag: op.tags?.[0] ?? "other", summary: op.summary ?? "", description: op.description ?? "" })));
  }, [spec]);
  const tags = [...new Set(ops.map((o) => o.tag))].sort();
  const shown = ops.filter((o) => tag === "all" || o.tag === tag);
  const tryGet = (path: string) => run(async () => {
    const res = await fetch(path);
    const text = await res.text();
    let body = text;
    try { body = JSON.stringify(JSON.parse(text), null, 2); } catch { /* not JSON */ }
    setOut({ path, body: body.slice(0, 4000) + (body.length > 4000 ? "\n… (truncated)" : "") });
  });
  return (
    <Panel title="API explorer" id="hw-api" help={<p>Every request the backend understands, generated automatically from the code (the OpenAPI specification). Simple read-only requests (GET without parameters in the path) can be tried directly.</p>}>
      <div className="form-row">
        <label>Area<select value={tag} onChange={(e) => setTag(e.target.value)}><option value="all">All ({ops.length})</option>{tags.map((t) => <option key={t}>{t}</option>)}</select></label>
        <a className="btn" href="/api/v1/openapi.json" target="_blank" rel="noreferrer">Raw OpenAPI JSON</a>
      </div>
      <ErrorNote error={error} />
      <div className="scroll">
        <table className="table compact">
          <thead><tr><th>Method</th><th>Path</th><th>What it does</th><th /></tr></thead>
          <tbody>
            {shown.map((o) => (
              <tr key={o.method + o.path}>
                <td className={`mono small method-${o.method.toLowerCase()}`}>{o.method}</td>
                <td className="mono small">{o.path}</td>
                <td className="small">{o.description.split("\n")[0] || o.summary}</td>
                <td>{o.method === "GET" && !o.path.includes("{") && (o.path.startsWith("/api/") || o.path.startsWith("/healthz/")) && <button type="button" className="link small" disabled={busy} onClick={() => tryGet(o.path)}>Try</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {out && <><p className="small mono">GET {out.path}</p><pre className="event-detail">{out.body}</pre></>}
    </Panel>
  );
}
