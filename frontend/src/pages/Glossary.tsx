import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { GLOSSARY, TOPICS } from "../learn/glossary";
import { useViewMode } from "../state/viewMode";

export function Glossary() {
  const [q, setQ] = useState("");
  const [topic, setTopic] = useState<string>("All");
  const { mode } = useViewMode();
  const { hash } = useLocation();
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView({ block: "center" });
  }, [hash]);
  const entries = useMemo(() => Object.entries(GLOSSARY)
    .filter(([, e]) => topic === "All" || e.topic === topic)
    .filter(([, e]) => !q || `${e.term} ${e.simple} ${e.technical ?? ""}`.toLowerCase().includes(q.toLowerCase()))
    .sort(([, a], [, b]) => a.term.localeCompare(b.term)), [q, topic]);
  return (
    <div className="page">
      <header>
        <h1>Glossary</h1>
        <p className="lead">Every term used in MarketLab, in plain English. Switch to Technical view (top right) to also see precise definitions.</p>
      </header>
      <div className="form-row">
        <label>Search<input type="text" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. spread, delta, VaR" /></label>
        <label>Topic
          <select value={topic} onChange={(e) => setTopic(e.target.value)}>
            <option>All</option>{TOPICS.map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
      </div>
      <p className="small muted">{entries.length} term{entries.length === 1 ? "" : "s"}</p>
      <dl className="glossary">
        {entries.map(([id, e]) => (
          <div key={id} id={id} className={`gl-entry ${hash === `#${id}` ? "target" : ""}`}>
            <dt>{e.term} <span className="tag">{e.topic}</span></dt>
            <dd>
              {e.simple}
              {mode === "technical" && e.technical && <span className="term-tech"> {e.technical}</span>}
              {e.see && <> <Link to={e.see} className="small">See it in action →</Link></>}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
