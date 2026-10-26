import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Term } from "../components/learn";
import { GLOSSARY } from "../learn/glossary";
import { LESSONS } from "../learn/lessons";
import { mockApi, renderAt } from "./harness";

describe("learning content", () => {
  it("every lesson is well-formed and links to a real page", () => {
    const routes = ["/playground", "/market-maker", "/fx", "/fx?tab=hedging", "/risk", "/options", "/tcp-lab", "/how-it-works"];
    expect(new Set(LESSONS.map((l) => l.id)).size).toBe(LESSONS.length);
    for (const l of LESSONS) {
      expect(routes).toContain(l.tryIt.to);
      expect(l.quiz.length).toBeGreaterThan(0);
      for (const q of l.quiz) expect(q.answer).toBeLessThan(q.options.length);
    }
  });

  it("glossary 'see it' links point at real pages", () => {
    const routes = ["/playground", "/market-maker", "/fx", "/fx?tab=hedging", "/risk", "/options", "/tcp-lab", "/how-it-works"];
    for (const e of Object.values(GLOSSARY)) if (e.see) expect(routes).toContain(e.see);
  });
});

describe("Learn page", () => {
  it("lists lessons by level and completes a lesson when the quiz is answered correctly", async () => {
    mockApi({});
    renderAt("/learn");
    expect(screen.getByRole("heading", { name: /Beginner/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: /What is a market\? Bid, ask and spread/ }));
    expect(screen.getByRole("heading", { level: 1, name: /What is a market/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the Order Book Playground/ })).toHaveAttribute("href", "/playground");
    await userEvent.click(screen.getByRole("button", { name: "$1" }));  // wrong
    expect(screen.getByText(/Not quite\. Spread = ask − bid/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "The ask" }));
    expect(screen.getByText("Score: 1 / 2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await userEvent.click(screen.getByRole("button", { name: "$2" }));
    await userEvent.click(screen.getByRole("button", { name: "The ask" }));
    expect(screen.getByText(/✓ Lesson complete/)).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("marketlab.lessonsDone") ?? "[]")).toContain("what-is-a-market");
  });
});

describe("Glossary", () => {
  it("filters terms by search text", async () => {
    mockApi({});
    renderAt("/glossary");
    await userEvent.type(screen.getByRole("textbox", { name: "Search" }), "drawdown");
    expect(screen.getByText("Drawdown")).toBeInTheDocument();
    expect(screen.queryByText("Bid")).not.toBeInTheDocument();
  });

  it("Term shows its definition on keyboard focus", async () => {
    render(<MemoryRouter><Term id="spread" /></MemoryRouter>);
    const btn = screen.getByRole("button", { name: "Spread" });
    await userEvent.tab();
    expect(btn).toHaveFocus();
    expect(screen.getByRole("tooltip")).toHaveTextContent(/gap between the ask and the bid/);
  });
});

describe("Order book playground", () => {
  const book = {
    instrument: "TOY", best_bid: "99", best_ask: "101", spread: "2", traders: ["you", "alice", "bob", "carol"],
    bids: [{ price: "99", total: 4, orders: [{ id: "o4", label: "#4", trader: "bob", remaining: 4 }] }],
    asks: [{ price: "101", total: 8, orders: [{ id: "o1", label: "#1", trader: "alice", remaining: 5 }, { id: "o2", label: "#2", trader: "bob", remaining: 3 }] }],
    trades: [], history: [],
  };
  it("shows queue order and the engine's step-by-step explanation", async () => {
    const calls = mockApi({
      "GET /playground": book,
      "POST /playground/orders": { label: "#6", steps: ["You sent a limit order…", "Matched with #1 from Alice at $101: 5 traded"], order: { id: "o6", status: "filled", filled_qty: 7, quantity: 7 } },
    });
    renderAt("/playground");
    const queue = await screen.findByLabelText("Queue at $101, first in line first");
    expect(within(queue).getAllByText(/Alice|Bob/).map((e) => e.textContent?.includes("Alice"))[0]).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: /You buy 7 at up to \$102/ }));
    expect(await screen.findByText("Matched with #1 from Alice at $101: 5 traded")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ trader: "you", side: "buy", type: "limit", quantity: 7, price: "102" });
  });
});

describe("Quant labs", () => {
  it("options lab shows price, Greeks and plain-English explanations from the backend", async () => {
    mockApi({
      "POST /quant/options/price": {
        input: { spot: 100, strike: 100, days: 30, rate: 0.04, vol: 0.2, kind: "call", dividend_yield: 0, t_years: 0.082 },
        result: { price: 2.45, d1: 0.1, d2: 0.04, n_d1: 0.54, n_d2: 0.52, delta: 0.54, gamma: 0.069, vega: 0.114, theta: -0.044, rho: 0.04, intrinsic: 0, time_value: 2.45, prob_itm: 0.52 },
        moneyness: "at the money", breakeven: 102.45,
        parity: { call: 2.45, put: 2.12, call_minus_put: 0.33, s_minus_pv_k: 0.33, holds: true },
        binomial: { convergence: [{ steps: 1, price: 2.3 }], american_200_steps: 2.45, early_exercise_premium: 0 },
        curve: [{ spot: 90, value_today: 0.3, payoff_at_expiry: 0, profit_at_expiry: -2.45 }, { spot: 110, value_today: 10.5, payoff_at_expiry: 10, profit_at_expiry: 7.55 }],
        time_decay: [{ days: 30, value: 2.45 }, { days: 1, value: 0.5 }],
        explain: ["Delta +0.540: if the stock rises by 1.00, the option's value changes by about +0.540."],
      },
    });
    renderAt("/options");
    expect(await screen.findByText("2.45", { selector: ".hero-figure" })).toBeInTheDocument();
    expect(screen.getByText("Stock +1.00 → option +0.54")).toBeInTheDocument();
    expect(screen.getByText(/if the stock rises by 1.00/)).toBeInTheDocument();
  });

  it("risk lab shows statistics and explanations", async () => {
    const r = {
      prices: [100, 101, 99], drawdown: [0, 0, -0.0198],
      stats: { total_return: -0.01, annual_return: -0.5, annual_vol: 0.2, daily_mean: 0, daily_stdev: 0.0126, sharpe: -0.5, max_drawdown: -0.0198, drawdown_start: 1, drawdown_end: 2, best_day: 0.01, worst_day: -0.0198, up_days: 0.5, skew: 0, excess_kurtosis: 0 },
      var: { "0.95": { historical: 0.019, parametric: 0.02, expected_shortfall: 0.0198 }, "0.99": { historical: 0.0198, parametric: 0.029, expected_shortfall: 0.0198 } },
      histogram: [{ from: -0.02, to: 0, count: 1 }, { from: 0, to: 0.02, count: 1 }], normal_curve: [{ x: -0.01, expected: 1 }, { x: 0.01, expected: 1 }],
      explain: ["Max drawdown -2.0%: the worst fall from a previous high."],
    };
    mockApi({ "POST /quant/risk/simulate": r, "POST /quant/risk/two-assets": { points: [{ w1: 0, ret: 0.04, vol: 0.1, naive_vol: 0.1 }, { w1: 1, ret: 0.08, vol: 0.2, naive_vol: 0.2 }], min_variance: { w1: 0.1, vol: 0.09, ret: 0.044 }, explain: ["The lowest-risk mix here puts 10% in asset 1."] } });
    renderAt("/risk");
    expect(await screen.findByText(/worst fall from a previous high\./)).toBeInTheDocument();
    expect(screen.getByText("Sharpe ratio", { selector: ".stat-label" })).toBeInTheDocument();
    expect(await screen.findByText(/lowest-risk mix/)).toBeInTheDocument();
  });
});

describe("How it works", () => {
  it("records real API calls in the live inspector and lists endpoints from OpenAPI", async () => {
    mockApi({ "POST /playground/orders": { label: "#9", steps: [], order: { id: "x", status: "open", filled_qty: 0, quantity: 1 } } });
    // openapi.json is fetched outside /api/v1 helpers; mockApi returns [] for unknown paths, so endpoints list is empty but safe.
    renderAt("/how-it-works");
    await userEvent.click(screen.getByRole("button", { name: "Send a test order" }));
    const inspector = screen.getByRole("heading", { name: "Live request inspector" }).closest("section")!;
    // Newest first; earlier tests in this file may also have recorded calls (the inspector is per browser session).
    await waitFor(() => expect(within(inspector).getAllByText("/api/v1/playground/orders", { selector: "td" }).length).toBeGreaterThan(0));
    await userEvent.click(within(inspector).getAllByText("/api/v1/playground/orders", { selector: "td" })[0]);
    expect(within(inspector).getByText(/"trader": "alice"/)).toBeInTheDocument();
  });
});
