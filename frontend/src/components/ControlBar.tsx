import { useState } from "react";
import { api, ApiError } from "../api/client";
import { useStream } from "../api/stream";
import type { SimState, SimulationStatus } from "../api/types";
import { useViewMode } from "../state/viewMode";
import { HelpToggle } from "./learn";

const SPEEDS = ["0.5", "1", "2", "5", "10"];

const STATE_LABEL: Record<SimState, { icon: string; text: string }> = {
  running: { icon: "▶", text: "Running" },
  paused: { icon: "❚❚", text: "Paused" },
  stopped: { icon: "■", text: "Stopped" },
};

export function ControlBar() {
  const { status, connection, applyStatus } = useStream();
  const { mode } = useViewMode();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<SimulationStatus>) => {
    setBusy(true);
    setError(null);
    try {
      applyStatus(await fn());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Unexpected error");
    } finally {
      setBusy(false);
    }
  };

  const disabled = busy || connection !== "connected" || !status;
  const state = status?.state ?? "stopped";
  const label = STATE_LABEL[state];

  return (
    <section className="control-bar" aria-label="Simulation controls">
      <span className={`state-pill state-${state}`} data-testid="sim-state">
        <span aria-hidden="true">{label.icon}</span> {status ? label.text : "Unknown"}
      </span>
      <div className="controls">
        <button type="button" className="btn primary" disabled={disabled || state === "running"} onClick={() => run(api.start)}>
          {state === "paused" ? "Resume" : "Start"}
        </button>
        <button type="button" className="btn" disabled={disabled || state !== "running"} onClick={() => run(api.pause)}>
          Pause
        </button>
        <button type="button" className="btn" disabled={disabled} onClick={() => run(() => api.reset())}>
          Reset
        </button>
        <label className="speed">
          Speed
          <select
            value={status ? String(Number(status.speed)) : "1"}
            disabled={disabled}
            onChange={(e) => run(() => api.setSpeed(e.target.value))}
          >
            {SPEEDS.map((s) => (
              <option key={s} value={s}>
                {s}×
              </option>
            ))}
          </select>
        </label>
      </div>
      {status && (
        <dl className="sim-meta">
          <div>
            <dt>Simulated time</dt>
            <dd>{new Date(status.sim_time).toISOString().replace("T", " ").slice(0, 19)} UTC</dd>
          </div>
          {mode === "technical" && (
            <>
              <div>
                <dt>Tick</dt>
                <dd data-testid="sim-tick">{status.tick}</dd>
              </div>
              <div>
                <dt>Seed</dt>
                <dd>{status.seed}</dd>
              </div>
              <div>
                <dt>Tick interval</dt>
                <dd>{status.tick_interval_ms} ms @ 1×</dd>
              </div>
            </>
          )}
        </dl>
      )}
      <HelpToggle label="What does the simulation clock do?">
        <p><b>The simulation clock</b> makes time pass in the simulated market. While it runs, every tick (one simulated second)
          the fair price drifts randomly, synthetic customers send orders, the market maker re-quotes and FX books refresh their prices.</p>
        <p><b>Pause</b> freezes everything so you can look closely. <b>Reset</b> puts every module back to its starting state.
          <b> Speed</b> makes ticks happen faster or slower. The guided demos pause the clock automatically so their steps are repeatable.</p>
      </HelpToggle>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
