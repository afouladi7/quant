import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { StreamProvider } from "../api/stream";
import type { SimulationStatus } from "../api/types";
import { ViewModeProvider } from "../state/viewMode";
import { FakeWebSocket } from "./setup";

const status = (over: Partial<SimulationStatus> = {}): SimulationStatus => ({
  state: "stopped",
  tick: 0,
  sim_time: "2026-01-05T14:30:00Z",
  speed: "1",
  seed: 42,
  tick_interval_ms: 250,
  ...over,
});

function mockFetch(handler: (url: string, init?: RequestInit) => unknown) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const body = handler(url, init);
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body), { status: 200 });
  });
}

function renderApp(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ViewModeProvider>
        <StreamProvider>
          <App />
        </StreamProvider>
      </ViewModeProvider>
    </MemoryRouter>,
  );
}

function connect(s = status()) {
  act(() => FakeWebSocket.last.emit({ kind: "hello", status: s, last_seq: 0 }));
}

describe("App shell", () => {
  it("shows the simulation-mode banner, intro and three module cards", () => {
    mockFetch(() => []);
    renderApp();
    expect(screen.getByText("SIMULATION MODE")).toBeInTheDocument();
    expect(screen.getByText(/Every trade and price in the simulator is hypothetical/)).toBeInTheDocument();
    for (const t of ["Market Maker Simulator", "FX Order Routing and Hedging", "TCP Performance Lab"]) {
      expect(screen.getByRole("heading", { name: t })).toBeInTheDocument();
    }
  });

  it("reports connecting, then connected, then disconnected with retry", () => {
    mockFetch(() => []);
    renderApp();
    expect(screen.getByTestId("connection-status")).toHaveTextContent("Connecting");
    connect();
    expect(screen.getByTestId("connection-status")).toHaveTextContent("Backend connected");
    vi.useFakeTimers();
    act(() => FakeWebSocket.last.serverClose());
    expect(screen.getByTestId("connection-status")).toHaveTextContent("disconnected");
    act(() => vi.advanceTimersByTime(600));
    expect(FakeWebSocket.instances).toHaveLength(2);
    vi.useRealTimers();
  });

  it("disables controls while disconnected", () => {
    mockFetch(() => []);
    renderApp();
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
  });

  it("Start calls the backend and shows the authoritative state it returns", async () => {
    const fetchSpy = mockFetch((url) => (url.endsWith("/simulation/start") ? status({ state: "running" }) : []));
    renderApp();
    connect();
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(fetchSpy).toHaveBeenCalledWith("/api/v1/simulation/start", expect.objectContaining({ method: "POST" }));
    expect(screen.getByTestId("sim-state")).toHaveTextContent("Running");
    expect(screen.getByRole("button", { name: "Pause" })).toBeEnabled();
  });

  it("shows backend error messages from the error envelope", async () => {
    mockFetch((url) =>
      url.endsWith("/simulation/start")
        ? new Response(JSON.stringify({ error: { code: "invalid_transition", message: "simulation is already running" } }), {
            status: 409,
          })
        : [],
    );
    renderApp();
    connect();
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(screen.getByRole("alert")).toHaveTextContent("simulation is already running");
  });

  it("renders streamed events and reveals technical details on click", async () => {
    mockFetch(() => []);
    renderApp();
    connect();
    act(() =>
      FakeWebSocket.last.emit({
        kind: "event",
        event: {
          seq: 1, id: "EVT-000001-abcd", ts: "2026-10-25T12:00:00Z", mono_ns: 1, type: "simulation.started",
          module: "simulation", entity_id: null, correlation_id: null, message: "Simulation started at tick 0.", data: {},
        },
      }),
    );
    const item = screen.getByRole("button", { name: /Simulation started at tick 0/ });
    await userEvent.click(item);
    expect(screen.getByLabelText("Event technical details")).toHaveTextContent("EVT-000001-abcd");
  });

  it("Technical view reveals tick and seed; Simple view hides them", async () => {
    mockFetch(() => []);
    renderApp();
    connect(status({ tick: 17 }));
    expect(screen.queryByTestId("sim-tick")).not.toBeInTheDocument();
    await userEvent.click(within(screen.getByRole("group", { name: "Presentation level" })).getByRole("button", { name: "Technical" }));
    expect(screen.getByTestId("sim-tick")).toHaveTextContent("17");
  });

  it("home links to all five demo presets", () => {
    mockFetch(() => []);
    renderApp();
    for (const t of ["1. Spread Capture", "2. Inventory Risk", "3. Fragmented FX Liquidity", "4. GBP Hedging", "5. TCP Latency"]) {
      expect(screen.getByText(t)).toBeInTheDocument();
    }
  });
});
