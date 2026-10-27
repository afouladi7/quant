import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fxState, mmState, order, parent, presets } from "./fixtures";
import { err, mockApi, renderAt } from "./harness";
import { FakeWebSocket } from "./setup";

describe("Market maker page", () => {
  it("renders the authoritative quote, ledger and order book from the backend", async () => {
    mockApi({ "GET /mm/state": mmState(), "GET /mm/presets": presets });
    renderAt("/market-maker");
    expect(await screen.findByText("$99.95", { selector: ".quote-px" })).toBeInTheDocument();
    expect(screen.getByText("$100.05", { selector: ".quote-px" })).toBeInTheDocument();
    const book = screen.getByRole("table", { name: /order book/i });
    expect(within(book).getAllByText("MM").length).toBeGreaterThan(0);
    expect(within(book).getByText("C")).toBeInTheDocument(); // customer limit order at 99.90
  });

  it("submits an order with an Idempotency-Key and shows the backend's explanation and status", async () => {
    const filled = order({ side: "sell", type: "market", status: "filled", filled_qty: 100, quantity: 100, avg_fill_price: "99.95" });
    const calls = mockApi({
      "GET /mm/state": mmState(), "GET /mm/presets": presets,
      "POST /mm/orders": { order: filled, trades: [], explanation: "Your sell order executed 100 shares at an average $99.95.", idempotent_replay: false },
    });
    renderAt("/market-maker");
    await screen.findByText("Place a customer order");
    await userEvent.click(screen.getByRole("button", { name: "Sell" }));
    await userEvent.click(screen.getByRole("button", { name: /Sell 100 shares/ }));
    const post = calls.find((c) => c.method === "POST" && c.url.endsWith("/mm/orders"))!;
    expect(post.body).toEqual({ side: "sell", type: "market", quantity: 100 });
    expect(post.headers["Idempotency-Key"]).toBeTruthy();
    expect(await screen.findByText(/executed 100 shares at an average \$99.95/)).toBeInTheDocument();
    expect(screen.getAllByText("Filled").length).toBeGreaterThan(0);
  });

  it("cancels a resting order through the API", async () => {
    const calls = mockApi({ "GET /mm/state": mmState(), "GET /mm/presets": presets, "DELETE /mm/orders/": order({ status: "canceled" }) });
    renderAt("/market-maker");
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(calls.some((c) => c.method === "DELETE" && c.url.endsWith("/mm/orders/ORD-000010-aaaa"))).toBe(true);
  });

  it("loads a preset, runs a step and shows what to notice", async () => {
    let loaded = false;
    mockApi({
      "GET /mm/state": () => mmState(loaded ? { preset: { ...presets[0], next_step: 0, complete: false } } : {}),
      "GET /mm/presets": presets,
      "POST /mm/presets/spread-capture/load": () => { loaded = true; return mmState(); },
      "POST /mm/presets/spread-capture/step": { step: 1, title: "A customer sells 100 shares at market", observe: "The market maker BUYS 100 at $99.95." },
    });
    renderAt("/market-maker");
    await userEvent.click(await screen.findByRole("button", { name: "Load" }));
    await userEvent.click(await screen.findByRole("button", { name: /Run step 1/ }));
    expect(await screen.findByText(/The market maker BUYS 100 at \$99.95/)).toBeInTheDocument();
  });

  it("shows validation details when settings are rejected", async () => {
    mockApi({
      "GET /mm/state": mmState(), "GET /mm/presets": presets,
      "PUT /mm/config": err(422, "validation_error", "Request validation failed", [{ loc: ["body", "spread"], msg: "spread must be at least one tick" }]),
    });
    renderAt("/market-maker");
    await userEvent.click(await screen.findByRole("button", { name: "Show" }));
    await userEvent.click(screen.getByRole("button", { name: "Apply settings" }));
    expect(await screen.findByText(/spread: spread must be at least one tick/)).toBeInTheDocument();
  });

  it("shows an error state when the backend is unreachable", async () => {
    mockApi({ "GET /mm/state": () => { throw new TypeError("fetch failed"); }, "GET /mm/presets": [] });
    renderAt("/market-maker");
    expect(await screen.findByRole("alert")).toHaveTextContent(/Cannot reach the MarketLab backend/);
  });
});

describe("FX routing page", () => {
  it("compares the three books and marks the best offer", async () => {
    mockApi({ "GET /fx/state": fxState(), "GET /fx/scenarios": [] });
    renderAt("/fx");
    expect(await screen.findByText(/1\.33003 ★/)).toBeInTheDocument();
    for (const b of ["Book A", "Book B", "Book C"]) expect(screen.getAllByText(b).length).toBeGreaterThan(0);
  });

  it("resets a scenario, runs its step and draws the parent → child routing from the response", async () => {
    let loaded = false;
    const scen = { id: "4", title: "Smart routing splits one parent order", expect: "Splits across books.", steps: [{ title: "Smart-route a 1,000,000 GBP buy", observe: "One parent order becomes several child orders.", action: {} }] };
    const calls = mockApi({
      "GET /fx/state": () => fxState(loaded ? { scenario: { ...scen, next_step: 0, complete: false } } : {}),
      "GET /fx/scenarios": [scen],
      "POST /fx/scenarios/4/reset": () => { loaded = true; return fxState(); },
      "POST /fx/scenarios/4/step": { title: scen.steps[0].title, observe: scen.steps[0].observe, parent },
      "GET /fx/orders/": { parent, trades: [] },
    });
    renderAt("/fx");
    await userEvent.click(await screen.findByRole("button", { name: "Load" }));
    await userEvent.click(await screen.findByRole("button", { name: /Run step 1/ }));
    expect(await screen.findByText(/One parent order becomes several child orders/)).toBeInTheDocument();
    const result = screen.getByRole("heading", { name: /Routing result/ }).closest("section")!;
    expect(result.querySelectorAll(".route-child.on").length).toBe(3);
    expect(within(result).getByText("1.3300410")).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/fx/scenarios/4/reset"))).toBe(true);
  });

  it("explains each book's role and lets the broker's desk hedge with 6B futures", async () => {
    const calls = mockApi({
      "GET /fx/state": fxState(), "GET /fx/scenarios": [],
      "POST /fx/desk/hedge": { message: "Desk hedge (on request): buy 16 6B-style GBP futures.", before: -1000000, after: 0 },
    });
    renderAt("/fx");
    expect(await screen.findByText("The broker itself")).toBeInTheDocument();
    expect(screen.getByText("Outside liquidity providers")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Hedge GBP with 6B futures now" }));
    expect(await screen.findByText(/buy 16 6B-style GBP futures/)).toBeInTheDocument();
    expect(calls.find((c) => c.url.endsWith("/fx/desk/hedge"))!.body).toEqual({ pair: "GBP/USD" });
  });

  it("previews a route without sending an order", async () => {
    const calls = mockApi({
      "GET /fx/state": fxState(), "GET /fx/scenarios": [],
      "POST /fx/route-preview": { ...parent.plan, explanation: "To buy 1,000,000, the router sent 200,000 to Book A." },
    });
    renderAt("/fx");
    await userEvent.click(await screen.findByRole("button", { name: "Preview route" }));
    expect(await screen.findByText(/Preview \(nothing sent\)/)).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/fx/orders") && c.method === "POST")).toBe(false);
  });
});

describe("Hedging tab", () => {
  const portfolio = {
    valuation_currency: "USD", rates: { "GBP/USD": "1.33" }, balances: [{ currency: "GBP", amount: "1000000", usd_value: "1330000" }],
    exposures: [{ currency: "GBP", rate_to_usd: "1.33", spot_balance: "1000000", hedge_spot: "0", futures_equivalent: "0", net_exposure: "1000000", net_exposure_usd: "1330000", pre_hedge_exposure: "1000000", pre_hedge_exposure_usd: "1330000", direction: "long", pnl_if_plus_1pct_usd: "13300", pnl_if_plus_1pct_pre_hedge_usd: "13300" }],
    gross_exposure_usd: "1330000", net_exposure_usd: "1330000", equity_usd: "19999976", initial_equity_usd: "20000000", total_pnl_usd: "-24",
    pnl_breakdown: { spot_realized_usd: "0", spot_unrealized_usd: "0", spot_fees_usd: "23.5", futures_realized_usd: "0", futures_unrealized_usd: "0", futures_fees_usd: "0", note: "" },
    spot_positions: [], futures: { spec: { symbol: "GBPUSD-FUT", underlying: "GBP/USD", contract_size: 62500, tick_size: "0.0001", days_total: 90, days_to_expiry: 75, initial_basis_pips: "12", half_spread_ticks: 1, fee_per_contract: "2", initial_margin: "3000", maintenance_margin: "2700", max_fill_per_order: 100, label: "Illustrative" },
      contracts: 0, gbp_equivalent: 0, price: "1.3310", bid: "1.3309", ask: "1.3311", basis: "0.0010", basis_shock_pips: "0", avg_entry: null, unrealized_usd: "0", realized_usd: "0", fees_usd: "0", expired: false, margin: { initial_required: "0", maintenance_required: "0" }, margin_note: "" },
    rule: { enabled: false, auto_execute: false, instrument: "futures", target_exposure: "0", max_exposure: "250000" }, proposals: [], fills: [], history: [], guided_step: 1, notice: "Hypothetical.",
  };
  const proposal = {
    id: "HDG-000001-dddd", status: "proposed", request: { instrument: "futures", mode: "rule" }, currency: "GBP", instrument: "futures", direction: "sell", quantity: 16, unit: "contracts",
    gbp_equivalent: -1000000, exposure_before: "1000000", projected_exposure_after: "0", projected_residual: "0", est_price: "1.3309", est_fees_usd: "32", est_notional_usd: "1270900",
    pnl_plus1_before: "13300", pnl_plus1_after: "0", explanation: "The fund is long 1,000,000 GBP.", assumptions: ["Illustrative contract terms."], created_ts: "2026-10-25T12:00:00Z",
    executed_ts: null, filled_quantity: 0, exec_price: null, exec_fees_usd: "0", actual_exposure_after: null, parent_order_id: null, result: null,
  };

  it("calculates a hedge proposal, shows before/after, and executes it on approval", async () => {
    const calls = mockApi({
      "GET /portfolio": portfolio, "GET /portfolio/risk": { spot: "1.33", futures_price: "1.331", pre_hedge_exposure_gbp: "1000000", post_hedge_exposure_gbp: "1000000", rows: [], assumptions: [] },
      "POST /hedges/proposals": proposal,
      "POST /hedges/proposals/HDG-000001-dddd/execute": { ...proposal, status: "executed", filled_quantity: 16, result: "Filled 16 of 16 contracts at 1.3309." },
    });
    renderAt("/fx?tab=hedging");
    await userEvent.click(await screen.findByRole("button", { name: "Calculate proposed hedge" }));
    expect(await screen.findByText("The fund is long 1,000,000 GBP.")).toBeInTheDocument();
    expect(screen.getByText(/sell 16 contracts/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Approve & execute hedge/ }));
    expect(await screen.findByText(/Filled 16 of 16 contracts/)).toBeInTheDocument();
    expect(calls.find((c) => c.url.endsWith("/hedges/proposals") && c.method === "POST")!.body).toMatchObject({ instrument: "futures", mode: "rule" });
  });
});

describe("TCP lab page", () => {
  const run = {
    id: "RUN-000001-eeee", suite_id: null, description: "raw tcp · split · reused conn", status: "completed",
    config: { transport: "raw_tcp", mode: "split", connection: "reused", payload_size: 500, trials: 2, warmup: 0, split_delay_ms: 10, prep_ms: 0, server_processing_ms: 0, concurrency: 1, tcp_nodelay: true, timeout_ms: 5000 },
    started_ts: "2026-10-25T12:00:00Z", finished_ts: "2026-10-25T12:00:01Z",
    summary: { n: 2, attempted: 2, error_rate: 0, timeout_rate: 0, min: 10.1, max: 10.5, mean: 10.3, median: 10.3, stdev: 0.28, p25: 10.2, p75: 10.4, p90: null, p95: null, p99: null },
    phase_medians: { total_ms: 10.3 }, environment: {}, notes: ["Small sample (n=2): treat the numbers as indicative only."], error: null,
    trials: [{ seq: 0, ok: true, warmup: false, total_ms: 10.1 }, { seq: 1, ok: true, warmup: false, total_ms: 10.5 }],
  };

  it("starts a benchmark with the chosen settings and shows measured statistics", async () => {
    let started = false;
    const calls = mockApi({
      "GET /tcp/benchmarks": () => (started ? [run] : []),
      "GET /tcp/benchmarks/RUN-000001-eeee": run,
      "POST /tcp/benchmarks": () => { started = true; return run; },
    });
    renderAt("/tcp-lab");
    await userEvent.click(await screen.findByRole("button", { name: "Run benchmark" }));
    const post = calls.find((c) => c.method === "POST" && c.url.endsWith("/tcp/benchmarks"))!;
    expect(post.body).toMatchObject({ transport: "raw_tcp", mode: "split", payload_size: 500, split_delay_ms: 10, tcp_nodelay: true });
    act(() => FakeWebSocket.last.emit({ kind: "event", event: { seq: 5, id: "E", ts: "2026-10-25T12:00:01Z", mono_ns: 1, type: "benchmark.completed", module: "tcplab", entity_id: run.id, correlation_id: run.id, message: "done", data: {} } }));
    await waitFor(() => expect(screen.getAllByText("10.300").length).toBeGreaterThan(0));
    expect(screen.getAllByText(/Small sample/).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "CSV" })).toHaveAttribute("href", "/api/v1/tcp/benchmarks/RUN-000001-eeee/csv");
  });

  it("reports a busy/conflict error from the backend", async () => {
    mockApi({ "GET /tcp/benchmarks": [], "POST /tcp/benchmarks": err(409, "busy", "A benchmark is already running; wait for it to finish.") });
    renderAt("/tcp-lab");
    await userEvent.click(await screen.findByRole("button", { name: "Run benchmark" }));
    expect(await screen.findByText(/already running/)).toBeInTheDocument();
  });
});
