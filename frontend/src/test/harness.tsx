import { act, render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "../App";
import { StreamProvider } from "../api/stream";
import { ViewModeProvider } from "../state/viewMode";
import { FakeWebSocket } from "./setup";

export type Call = { method: string; url: string; body: unknown; headers: Record<string, string> };
type Handler = (c: Call) => unknown;

/** Route fetch() calls to handlers keyed by "METHOD /path-prefix". Records every call. */
export function mockApi(routes: Record<string, Handler | unknown>) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const call: Call = { method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined, headers: (init?.headers ?? {}) as Record<string, string> };
    calls.push(call);
    const key = Object.keys(routes)
      .filter((k) => { const [m, p] = k.split(" "); return m === method && url.startsWith(`/api/v1${p}`); })
      .sort((a, b) => b.length - a.length)[0];
    const h = key ? routes[key] : [];
    const out = typeof h === "function" ? (h as Handler)(call) : h;
    if (out instanceof Response) return out;
    return new Response(JSON.stringify(out ?? null), { status: 200 });
  });
  return calls;
}

export function renderAt(path: string) {
  const r = render(
    <MemoryRouter initialEntries={[path]}>
      <ViewModeProvider><StreamProvider><App /></StreamProvider></ViewModeProvider>
    </MemoryRouter>,
  );
  act(() => FakeWebSocket.last.emit({ kind: "hello", status: { state: "stopped", tick: 0, sim_time: "2026-01-05T14:30:00Z", speed: "1", seed: 42, tick_interval_ms: 250 }, last_seq: 0 }));
  return r;
}

export const err = (status: number, code: string, message: string, details?: unknown) =>
  new Response(JSON.stringify({ error: { code, message, details } }), { status });
