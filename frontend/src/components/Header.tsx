import { NavLink } from "react-router-dom";
import { useStream, type ConnectionState } from "../api/stream";
import { useViewMode } from "../state/viewMode";

const CONNECTION_LABEL: Record<ConnectionState, { icon: string; text: string }> = {
  connected: { icon: "●", text: "Backend connected" },
  connecting: { icon: "◌", text: "Connecting…" },
  disconnected: { icon: "✕", text: "Backend disconnected — retrying" },
};

export function Header() {
  const { connection } = useStream();
  const { mode, setMode } = useViewMode();
  const conn = CONNECTION_LABEL[connection];
  return (
    <header className="header">
      <NavLink to="/" className="brand" aria-label="MarketLab home">
        <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
          <rect width="32" height="32" rx="7" fill="var(--panel-2)" />
          <path d="M6 22l6-7 5 4 9-11" fill="none" stroke="var(--accent)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span>MarketLab</span>
      </NavLink>
      <span className="sim-badge" role="status" title="All prices and trades are hypothetical">
        SIMULATION MODE
      </span>
      <nav className="nav" aria-label="Modules">
        <NavLink to="/market-maker">Market Maker</NavLink>
        <NavLink to="/fx">FX Routing &amp; Hedging</NavLink>
        <NavLink to="/tcp-lab">TCP Lab</NavLink>
      </nav>
      <div className="header-right">
        <div className="segmented" role="group" aria-label="Presentation level">
          <button type="button" aria-pressed={mode === "simple"} onClick={() => setMode("simple")}>
            Simple
          </button>
          <button type="button" aria-pressed={mode === "technical"} onClick={() => setMode("technical")}>
            Technical
          </button>
        </div>
        <span className={`conn conn-${connection}`} data-testid="connection-status">
          <span aria-hidden="true">{conn.icon}</span> {conn.text}
        </span>
      </div>
    </header>
  );
}
