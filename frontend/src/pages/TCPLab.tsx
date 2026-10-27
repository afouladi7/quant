import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { http } from "../api/client";
import { useStream } from "../api/stream";
import { DistributionChart } from "../components/charts";
import { EventTimeline } from "../components/EventTimeline";
import { StartHere, Term } from "../components/learn";
import { ErrorNote, Explain, JsonBlock, Panel, SimpleOnly, Stat, StatusBadge, TechOnly, useAction } from "../components/ui";
import { fmtMs, fmtPct } from "../lib/format";

interface Cfg {
  transport: "raw_tcp" | "http"; mode: "complete" | "split" | "early_work" | "abort" | "race"; connection: "cold" | "reused"; payload_size: number;
  trials: number; warmup: number; split_delay_ms: number; prep_ms: number; server_processing_ms: number; concurrency: number;
  tcp_nodelay: boolean; timeout_ms: number; label?: string | null;
}
type Summary = Record<string, number | null>;
interface Run {
  id: string; suite_id: string | null; config: Cfg; description: string; status: string; started_ts: string | null; finished_ts: string | null;
  summary: Summary; decision_summary: Summary; phase_medians: Record<string, number | null>;
  race: null | { trials: number; pre_sent_wins: number; full_payload_wins: number; ties: number; pre_sent_win_rate: number | null; margin: Summary;
    pre_decision_to_accept: Summary; full_decision_to_accept: Summary;
    by_scheduling_order: Record<string, { trials: number; pre_sent_wins: number }> };
  abort: null | { sent_incomplete: number; discarded_by_server: number; acted_on_by_server: number; premature_commits: number }; environment: Record<string, unknown>; notes: string[]; error: string | null;
  trials?: Record<string, number | boolean | string | null>[];
}

const DEFAULT: Cfg = {
  transport: "raw_tcp", mode: "split", connection: "reused", payload_size: 500, trials: 50, warmup: 5, split_delay_ms: 10,
  prep_ms: 0, server_processing_ms: 0, concurrency: 1, tcp_nodelay: true, timeout_ms: 5000,
};

const PHASES: [string, string][] = [
  ["connect_ms", "TCP connect"], ["first_write_ms", "First write done"], ["decision_ms", "Decision to trade made"], ["server_first_rx_ms", "Server first receive"],
  ["server_complete_ms", "Full message available"], ["wait_final_byte_ms", "Server waited for last byte"], ["prep_ms", "Preparation work"],
  ["server_processing_ms", "Processing work"], ["ttfb_ms", "First response byte"], ["response_spread_ms", "First→last response byte"], ["decision_to_accept_ms", "Decision → server accepted"], ["decision_to_response_ms", "Decision → response"], ["total_ms", "Total"],
];

export function TCPLab() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [details, setDetails] = useState<Record<string, Run>>({});
  const fetched = useRef<Record<string, string>>({}); // run id -> status we fetched details for
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const { events } = useStream();
  const lastSeq = events.filter((e) => e.module === "tcplab").at(-1)?.seq;

  const refresh = useCallback(async () => {
    try {
      const list = await http.get<Run[]>("/tcp/benchmarks");
      setRuns(list);
      setError(null);
      for (const r of list) {
        if (r.status === "running" || r.status === "queued" || fetched.current[r.id] === r.status) continue;
        fetched.current[r.id] = r.status;
        void http.get<Run>(`/tcp/benchmarks/${r.id}`).then((d) => setDetails((p) => ({ ...p, [r.id]: d })));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load benchmarks");
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh, lastSeq]);
  const busy = runs.some((r) => r.status === "running" || r.status === "queued");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => void refresh(), 1000);
    return () => clearInterval(t);
  }, [busy, refresh]);

  // Default selection: the most recent suite, else the most recent run.
  useEffect(() => {
    if (selected.length || !runs.length) return;
    const suite = runs.find((r) => r.suite_id)?.suite_id;
    setSelected(suite ? runs.filter((r) => r.suite_id === suite).map((r) => r.id).reverse() : [runs[0].id]);
  }, [runs, selected.length]);

  const onStarted = (ids: string[]) => { setSelected(ids); void refresh(); };
  const shown = selected.map((id) => details[id]).filter(Boolean);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>TCP Performance Lab</h1>
          <p className="lead">
            Real requests against MarketLab's own backend, measured with a high-resolution monotonic clock. Compare sending a
            500-byte message at once with sending 499 bytes and then the final byte, and see what a pre-established connection saves.
          </p>
        </div>
      </header>
      <StartHere steps={[
        <>Read <b>What is being measured</b> (four short ideas).</>,
        <>Press <b>Run comparison</b> and wait about 10 seconds.</>,
        <>Read <b>What this run measured</b> under the chart, then compare the medians in <b>Statistics</b>.</>,
      ]} />
      <Concepts />
      <div className="grid-2">
        <Suite busy={busy} onStarted={onStarted} />
        <Controls busy={busy} onStarted={onStarted} />
      </div>
      <ErrorNote error={error} />
      <Results shown={shown} />
      <RunList runs={runs} selected={selected} setSelected={setSelected} />
      <EventTimeline modules={["tcplab"]} title="Benchmark events" limit={8} />
    </div>
  );
}

function Concepts() {
  return (
    <Panel title="What is being measured" id="tcp-concepts" help={<p>These experiments send real network messages to MarketLab's own backend and time each step with a high-resolution clock. Nothing is simulated here.</p>}>
      <Explain
        simple={
          <div className="concepts">
            <p><b>TCP is a stream of bytes, not of messages.</b> The receiver cannot act on a 500-byte order until all 500 bytes have arrived, however they were sent.</p>
            <p><b>Front-loading: send everything except the last byte ahead of time.</b> Traders open the connection and send the first 499 bytes of an order (for example most of an HTTP request) <i>before</i> they know whether they will trade. The incomplete message sits at the server. When the decision comes, only the final byte has to travel. If they decide not to trade, they drop it (close the connection) and the server discards it.</p>
            <p><b>Measure from the decision, not from the first byte.</b> What matters is <i>decision → response</i>. Time spent waiting before the decision doesn't count, because the trader hadn't decided yet.</p>
            <p><b>The big win is server-side work done early.</b> If the server parses and checks the first 499 bytes while waiting, only a tiny amount of work remains after the last byte arrives.</p>
            <p><b>Opening a connection costs time.</b> A connection set up in advance removes the handshake from the critical path.</p>
          </div>
        }
        technical={
          <div className="concepts small">
            <p>Raw TCP: 16-byte header (magic, flags, prep/proc ms, total length, seq) + payload; the server timestamps every socket read and commits only when <code>received == total_len</code>. HTTP: valid POST with <code>Content-Length</code>; the endpoint streams the body and completes only when the declared length has arrived.</p>
            <p>Client and server run in this process, so both use <code>time.monotonic_ns()</code> on the same clock. Loopback: no real RTT. Writes are application <code>write()</code> calls; TCP segment boundaries are not observed (no packet capture). TCP_NODELAY is set on the client socket and read back; for raw TCP the server applies it too.</p>
          </div>
        }
      />
    </Panel>
  );
}

function Suite({ busy, onStarted }: { busy: boolean; onStarted: (ids: string[]) => void }) {
  const [transport, setTransport] = useState<"raw_tcp" | "http">("raw_tcp");
  const [trials, setTrials] = useState(40);
  const { busy: posting, error, run } = useAction();
  return (
    <Panel title="Preset 5: run the standard comparison" id="tcp-suite" help={<p>Eight experiments run back to back with the same settings. Each changes one thing (connection reuse, sending ahead, doing work early, racing, aborting) so differences can be attributed to that change.</p>}>
      <ol className="small suite-list">
        <li><b>A</b> complete message, cold connection (connect measured)</li>
        <li><b>C</b> complete message, pre-established connection</li>
        <li><b>B</b> split 499 + 1 bytes, no delay</li>
        <li><b>B</b> split with a 20 ms pause; 10 ms preparation done after the last byte</li>
        <li><b>D</b> split with a 20 ms pause; the same 10 ms preparation done while waiting</li>
        <li><b>Race</b> pre-sent 499 bytes vs. full 500-byte payload on the same signal, no server prep</li>
        <li><b>Race</b> the same, with 10 ms of server preparation</li>
        <li><b>Abort</b> send 499 bytes ahead, then decide not to trade</li>
      </ol>
      <div className="form-row">
        <label>Transport<select value={transport} onChange={(e) => setTransport(e.target.value as "raw_tcp" | "http")}><option value="raw_tcp">Raw TCP</option><option value="http">HTTP POST</option></select></label>
        <label>Trials per experiment<input type="number" min={5} max={200} value={trials} onChange={(e) => setTrials(Number(e.target.value))} /></label>
        <button type="button" className="btn primary" disabled={busy || posting}
          onClick={() => run(async () => { const r = await http.post<{ id: string; run_ids: string[] }>("/tcp/suites", { transport, trials }); onStarted(r.run_ids); })}>
          {busy ? "Running…" : "Run comparison"}
        </button>
      </div>
      <p className="small muted">Results are whatever this machine measures — nothing is predetermined. Expect run-to-run noise.</p>
      <ErrorNote error={error} />
    </Panel>
  );
}

function Controls({ busy, onStarted }: { busy: boolean; onStarted: (ids: string[]) => void }) {
  const [cfg, setCfg] = useState<Cfg>(DEFAULT);
  const { busy: posting, error, run } = useAction();
  const set = <K extends keyof Cfg>(k: K, v: Cfg[K]) => setCfg({ ...cfg, [k]: v });
  const num = (k: keyof Cfg, label: string, min: number, max: number, step = 1) => (
    <label>{label}<input type="number" min={min} max={max} step={step} value={Number(cfg[k])} onChange={(e) => set(k, Number(e.target.value) as never)} /></label>
  );
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => { const r = await http.post<Run>("/tcp/benchmarks", cfg); onStarted([r.id]); });
  };
  return (
    <Panel title="Custom benchmark" id="tcp-custom" help={<><p>Design your own experiment. A <b>cold</b> connection performs the TCP <Term id="handshake">handshake</Term> every time; <b>reused</b> connects once. <b>Split</b> sends all but the last byte, waits, then sends the last byte. TCP_NODELAY turns off <Term id="nagle">Nagle's algorithm</Term>.</p></>} actions={busy ? <button type="button" className="btn" onClick={() => void http.post("/tcp/cancel")}>Cancel run</button> : null}>
      <form onSubmit={submit}>
        <div className="form-row">
          <label>Transport<select value={cfg.transport} onChange={(e) => set("transport", e.target.value as Cfg["transport"])}><option value="raw_tcp">Raw TCP</option><option value="http">HTTP POST</option></select></label>
          <label>Mode<select value={cfg.mode} onChange={(e) => set("mode", e.target.value as Cfg["mode"])}><option value="complete">Complete message (one write)</option><option value="split">Split: N−1 bytes, then last byte</option><option value="early_work">Split + useful early work</option><option value="abort">Send ahead, then abort (don't trade)</option><option value="race">Race: pre-sent vs full payload</option></select></label>
          <label>Connection<select value={cfg.connection} onChange={(e) => set("connection", e.target.value as Cfg["connection"])}><option value="cold">Cold (connect each trial)</option><option value="reused">Pre-established / reused</option></select></label>
        </div>
        <div className="form-grid tight">
          {num("payload_size", "Message bytes", 17, 65536)}
          {num("trials", "Trials", 1, 500)}
          {num("warmup", "Warm-up trials", 0, 50)}
          {num("split_delay_ms", "Delay before last byte (ms)", 0, 1000, 0.5)}
          {num("prep_ms", "Server preparation (ms)", 0, 200)}
          {num("server_processing_ms", "Server processing (ms)", 0, 200)}
          {num("concurrency", "Concurrency", 1, 8)}
          {num("timeout_ms", "Timeout (ms)", 100, 10000)}
        </div>
        <div className="form-row">
          <label className="radio"><input type="checkbox" checked={cfg.tcp_nodelay} onChange={(e) => set("tcp_nodelay", e.target.checked)} /> TCP_NODELAY (disable Nagle's algorithm)</label>
          <button type="submit" className="btn primary" disabled={busy || posting}>{busy ? "Running…" : "Run benchmark"}</button>
        </div>
      </form>
      <SimpleOnly><p className="small muted">Limits: ≤500 trials, ≤8 concurrent clients, ≤64 KiB messages, ≤120 s per run, only this server as the target.</p></SimpleOnly>
      <ErrorNote error={error} />
    </Panel>
  );
}

const f = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toFixed(3));

function Results({ shown }: { shown: Run[] }) {
  const [metric, setMetric] = useState<"decision" | "total">("decision");
  if (!shown.length) return <Panel title="Results"><p className="empty">Run the comparison or a custom benchmark to see measured results.</p></Panel>;
  const latency = shown.filter((r) => r.config.mode !== "abort" && r.config.mode !== "race");
  const rows = latency.map((r) => {
    const key = metric === "decision" ? "decision_to_response_ms" : "total_ms";
    const sum = metric === "decision" ? r.decision_summary : r.summary;
    const vals = (r.trials ?? []).filter((t) => !t.warmup && t.ok && t[key] != null).map((t) => Number(t[key]));
    return { key: r.id, label: r.description.length > 30 ? r.description.slice(0, 29) + "…" : r.description, values: vals, median: sum.median, p25: sum.p25, p75: sum.p75 };
  });
  return (
    <>
      {shown.filter((r) => r.race).map((r) => <RaceResult key={r.id} run={r} />)}
      {shown.filter((r) => r.abort).map((r) => <AbortResult key={r.id} run={r} />)}
      {latency.length > 0 && <Panel title="Latency distributions" id="tcp-dist" help={<>
        <p>Each dot is one measured request. <b>Decision → response</b> starts the clock when the client decides to trade: before sending a complete message, or just before the last byte of a pre-sent one. <b>Total</b> starts when the first byte is sent.</p>
        <p>For front-loaded orders, the decision → response time is what a trader experiences; the time the 499 bytes waited at the server happened before the decision.</p>
      </>} actions={
        <div className="segmented" role="group" aria-label="Latency measured from">
          <button type="button" aria-pressed={metric === "decision"} onClick={() => setMetric("decision")}>Decision → response</button>
          <button type="button" aria-pressed={metric === "total"} onClick={() => setMetric("total")}>Total time</button>
        </div>
      }>
        <DistributionChart title={metric === "decision" ? "Per-trial latency from the decision to trade" : "Per-trial total latency (from the first byte sent)"} rows={rows} />
        <Interpretation shown={latency} />
      </Panel>}
      <Panel title="Statistics" id="tcp-stats" help={<p>Summary statistics for each experiment. Look at the median for typical behaviour and p95/p99 for the slow tail (<Term id="percentile">percentiles</Term>).</p>} actions={shown[0]?.suite_id ? <a className="btn" href={`/api/v1/tcp/suites/${shown[0].suite_id}/csv`}>⬇ Suite CSV</a> : null}>
        <div className="scroll">
          <table className="table compact">
            <thead><tr><th>Experiment</th><th className="num">n</th><th className="num">decision → response median</th><th className="num">min</th><th className="num">median (total)</th><th className="num">mean</th><th className="num">stdev</th><th className="num">p90</th><th className="num">p95</th><th className="num">p99</th><th className="num">errors</th><th className="num">timeouts</th><th /></tr></thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.id}>
                  <th scope="row" className="small">{r.description} <StatusBadge status={r.status} /></th>
                  <td className="num">{r.summary.n}</td><td className="num"><b>{f(r.decision_summary?.median)}</b></td><td className="num">{f(r.summary.min)}</td><td className="num">{f(r.summary.median)}</td>
                  <td className="num">{f(r.summary.mean)}</td><td className="num">{f(r.summary.stdev)}</td><td className="num">{f(r.summary.p90)}</td>
                  <td className="num">{f(r.summary.p95)}</td><td className="num">{f(r.summary.p99)}</td>
                  <td className="num">{fmtPct(r.summary.error_rate)}</td><td className="num">{fmtPct(r.summary.timeout_rate)}</td>
                  <td><a className="link small" href={`/api/v1/tcp/benchmarks/${r.id}/csv`}>CSV</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted">All values in milliseconds. p90 needs ≥10 samples, p95 ≥20, p99 ≥100; otherwise “—”. Cold- and reused-connection runs are always reported separately.</p>
      </Panel>
      <Panel title="Where the time goes (median per phase, ms from request start)" id="tcp-phases" help={<p>Where the time went, as the median time from the start of the request until each event: connecting, writing, the server receiving the whole message, server work, and the response.</p>}>
        <div className="scroll">
          <table className="table compact">
            <thead><tr><th>Phase</th>{shown.map((r) => <th key={r.id} className="num small">{r.description.slice(0, 26)}</th>)}</tr></thead>
            <tbody>
              {PHASES.map(([k, label]) => (
                <tr key={k}><td>{label}</td>{shown.map((r) => <td key={r.id} className="num">{f(r.phase_medians[k])}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
        <TechOnly>
          {shown.map((r) => (
            <div key={r.id} className="run-notes">
              <h3 className="sub">{r.description}</h3>
              <ul className="small">{r.notes.map((n) => <li key={n}>{n}</li>)}</ul>
              <JsonBlock value={{ config: r.config, environment: r.environment }} label="Configuration & environment" />
              <TrialTable run={r} />
            </div>
          ))}
        </TechOnly>
        <SimpleOnly><ul className="small">{[...new Set(shown.flatMap((r) => r.notes))].slice(0, 4).map((n) => <li key={n}>{n}</li>)}</ul></SimpleOnly>
      </Panel>
    </>
  );
}

/** Plain-English reading of the measured medians — computed from the data, never assumed. */
function Interpretation({ shown }: { shown: Run[] }) {
  const pick = (pred: (r: Run) => boolean) => shown.find((r) => pred(r) && r.decision_summary?.median != null);
  const cold = pick((r) => r.config.mode === "complete" && r.config.connection === "cold");
  const warm = pick((r) => r.config.mode === "complete" && r.config.connection === "reused");
  const splitAfter = pick((r) => r.config.mode === "split" && r.config.prep_ms > 0);
  const early = pick((r) => r.config.mode === "early_work");
  const dm = (r: Run) => r.decision_summary.median as number;
  const lines: string[] = [];
  if (cold && warm) lines.push(`Pre-established connection vs. cold: ${fmtMs(dm(warm))} vs ${fmtMs(dm(cold))} from the decision (${dm(cold) >= dm(warm) ? "saves" : "costs"} ${fmtMs(Math.abs(dm(cold) - dm(warm)))}).`);
  if (early) lines.push(`Front-loaded with the server preparing early: ${fmtMs(dm(early))} from the decision to the response, even though the whole exchange took ${fmtMs(early.summary.median)} from the first byte.`);
  if (early && splitAfter) lines.push(`If the server only starts its ${early.config.prep_ms} ms of preparation after the last byte, decision → response is ${fmtMs(dm(splitAfter))}: front-loading the bytes alone doesn't help much; pre-processing them does.`);
  if (!lines.length) return null;
  return <div className="observe"><strong>What this run measured:</strong><ul>{lines.map((l) => <li key={l}>{l}</li>)}</ul></div>;
}

function RaceResult({ run }: { run: Run }) {
  const r = run.race!;
  const pct = r.trials ? (r.pre_sent_wins / r.trials) * 100 : 0;
  const order = r.by_scheduling_order;
  return (
    <Panel title={`Race: ${run.description}`} id={`race-${run.id}`} help={<>
      <p>Two clients receive the same trading signal at the same instant. <b>Pre-sent</b> had already sent the first {run.config.payload_size - 1} bytes on its open connection and only sends the last byte. <b>Full payload</b> sends all {run.config.payload_size} bytes. Both connections were open in advance and the server treats both messages identically.</p>
      <p>The winner is whichever order the <b>server accepted first</b>, using the server's own timestamps. Both clients run in one program, so which one the computer serves first after the signal alternates randomly; wins are shown for each order so you can see whether that, rather than the bytes, decided the race.</p>
    </>}>
      <div className="race-bar" aria-label={`Pre-sent won ${r.pre_sent_wins} of ${r.trials}`}>
        <span className="race-pre" style={{ width: `${pct}%` }}>{r.pre_sent_wins > 0 && `Pre-sent ${r.pre_sent_wins}`}</span>
        <span className="race-full" style={{ width: `${100 - pct}%` }}>{r.full_payload_wins > 0 && `Full ${r.full_payload_wins}`}</span>
      </div>
      <div className="stats">
        <Stat label="Pre-sent order won" value={`${r.pre_sent_wins} / ${r.trials}`} hint={r.ties ? `${r.ties} ties` : undefined} />
        <Stat label="Winning margin (median)" value={fmtMs(r.margin.median)} hint="full payload accepted − pre-sent accepted" />
        <Stat label="Pre-sent: decision → accepted" value={fmtMs(r.pre_decision_to_accept.median)} hint="median" />
        <Stat label="Full payload: decision → accepted" value={fmtMs(r.full_decision_to_accept.median)} hint="median" />
      </div>
      <p className="small">Pre-sent won {order.pre_scheduled_first.pre_sent_wins}/{order.pre_scheduled_first.trials} when it was served first after the signal, and {order.full_scheduled_first.pre_sent_wins}/{order.full_scheduled_first.trials} when the full-payload client was served first.</p>
      <ul className="small">{run.notes.filter((n) => n.startsWith("Same signal") || n.startsWith("The winner") || n.startsWith("Which client")).map((n) => <li key={n}>{n}</li>)}</ul>
    </Panel>
  );
}

function AbortResult({ run }: { run: Run }) {
  const a = run.abort!;
  const ok = a.discarded_by_server === a.sent_incomplete && a.acted_on_by_server === 0;
  return (
    <Panel title={`Abort: ${run.description}`} id={`abort-${run.id}`} help={<p>The client sends everything except the last byte, then decides not to trade and closes the connection. A correct server must throw the incomplete message away and never act on it.</p>}>
      <p className={ok ? "pos" : "neg"}><b>{ok ? "✓" : "✕"} {a.sent_incomplete} orders were sent without their final byte and abandoned. The server discarded {a.discarded_by_server} and acted on {a.acted_on_by_server}.</b></p>
      <p className="small muted">This is the “drop it” path of front-loading: an unsent last byte means no trade.</p>
    </Panel>
  );
}

function TrialTable({ run }: { run: Run }) {
  const [open, setOpen] = useState(false);
  const t = run.trials ?? [];
  return (
    <div>
      <button type="button" className="link small" onClick={() => setOpen(!open)}>{open ? "▾" : "▸"} Per-trial results ({t.length})</button>
      {open && (
        <div className="scroll">
          <table className="table compact mono small">
            <thead><tr><th>seq</th><th>warm-up</th><th>ok</th><th className="num">connect</th><th className="num">first write</th><th className="num">last write</th><th className="num">srv complete</th><th className="num">wait last</th><th className="num">prep</th><th className="num">ttfb</th><th className="num">total</th><th>error</th></tr></thead>
            <tbody>
              {t.map((x) => (
                <tr key={String(x.seq)}>
                  <td>{String(x.seq)}</td><td>{x.warmup ? "yes" : ""}</td><td>{x.ok ? "✓" : "✕"}</td>
                  <td className="num">{f(x.connect_ms as number)}</td><td className="num">{f(x.first_write_ms as number)}</td><td className="num">{f(x.last_write_ms as number)}</td>
                  <td className="num">{f(x.server_complete_ms as number)}</td><td className="num">{f(x.wait_final_byte_ms as number)}</td><td className="num">{f(x.prep_ms as number)}</td>
                  <td className="num">{f(x.ttfb_ms as number)}</td><td className="num">{f(x.total_ms as number)}</td><td>{x.error ? String(x.error) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function RunList({ runs, selected, setSelected }: { runs: Run[]; selected: string[]; setSelected: (s: string[]) => void }) {
  const toggle = (id: string) => setSelected(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  return (
    <Panel title="Benchmark history" id="tcp-history" help={<p>All recent runs. Tick several to compare their distributions above.</p>} actions={<span className="small muted">tick runs to compare (kept in memory, last 30)</span>}>
      {runs.length === 0 ? <p className="empty">No runs yet.</p> : (
        <div className="scroll">
          <table className="table compact">
            <thead><tr><th>Compare</th><th>Run</th><th>Status</th><th className="num">n</th><th className="num">median ms</th><th>Started</th></tr></thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td><input type="checkbox" aria-label={`Compare ${r.description}`} checked={selected.includes(r.id)} onChange={() => toggle(r.id)} /></td>
                  <td className="small">{r.description}<TechOnly> <code>{r.id}</code></TechOnly></td>
                  <td className="small">{r.status}{r.error ? `: ${r.error}` : ""}</td>
                  <td className="num">{r.summary.n ?? "—"}</td><td className="num">{f(r.summary.median)}</td>
                  <td className="small">{r.started_ts ? new Date(r.started_ts).toLocaleTimeString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
