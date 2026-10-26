import type { ApiErrorBody, InfoResponse, MarketLabEvent, SimulationStatus } from "./types";

// All calls are same-origin: nginx (container) or Vite (dev) proxies /api.
const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the MarketLab backend.");
  }
  const text = await res.text();
  const body: unknown = text ? safeJson(text) : null;
  if (!res.ok) {
    const err = (body as ApiErrorBody | null)?.error;
    throw new ApiError(res.status, err?.code ?? "http_error", err?.message ?? `HTTP ${res.status}`, err?.details);
  }
  return body as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function newKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `k-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** Generic helpers. Every state-changing POST carries an Idempotency-Key so a retry never duplicates. */
export const http = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown, idempotencyKey?: string) =>
    request<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
      headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
    }),
  put: <T>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  newKey,
};

export const api = {
  info: () => request<InfoResponse>("/info"),
  simulation: () => request<SimulationStatus>("/simulation"),
  start: () => request<SimulationStatus>("/simulation/start", { method: "POST" }),
  pause: () => request<SimulationStatus>("/simulation/pause", { method: "POST" }),
  reset: (seed?: number) =>
    request<SimulationStatus>("/simulation/reset", {
      method: "POST",
      body: seed === undefined ? undefined : JSON.stringify({ seed }),
    }),
  setSpeed: (speed: string) =>
    request<SimulationStatus>("/simulation/speed", { method: "PUT", body: JSON.stringify({ speed }) }),
  events: (params: { limit?: number; after_seq?: number; type?: string } = {}) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && q.set(k, String(v)));
    return request<MarketLabEvent[]>(`/events${q.size ? `?${q}` : ""}`);
  },
};

export function streamUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${BASE}/stream`;
}
