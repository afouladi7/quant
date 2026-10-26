// Mirrors backend Pydantic models (backend/app). Decimals arrive as strings.

export type SimState = "stopped" | "running" | "paused";

export interface SimulationStatus {
  state: SimState;
  tick: number;
  sim_time: string;
  speed: string;
  seed: number;
  tick_interval_ms: number;
}

export interface MarketLabEvent {
  seq: number;
  id: string;
  ts: string;
  mono_ns: number;
  type: string;
  module: string;
  entity_id: string | null;
  correlation_id: string | null;
  message: string;
  data: Record<string, unknown>;
}

export interface InfoResponse {
  name: string;
  version: string;
  environment: string;
  simulation_mode: boolean;
  persistence_mode: string;
  ephemeral: boolean;
  notice: string;
  authentication: string;
  limits: Record<string, number>;
}

export type StreamMessage =
  | { kind: "hello"; status: SimulationStatus; last_seq: number }
  | { kind: "status"; status: SimulationStatus }
  | { kind: "event"; event: MarketLabEvent }
  | { kind: "dropped"; count: number };

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown };
}
