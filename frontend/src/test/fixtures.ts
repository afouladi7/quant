export const order = (over: Record<string, unknown> = {}) => ({
  id: "ORD-000010-aaaa", venue: "MM", instrument: "MARKETLAB-100", owner: "customer", side: "buy", type: "limit", tif: "gtc",
  quantity: 50, limit_price: "99.90", filled_qty: 0, avg_fill_price: null, fees: "0", status: "open", reason: null, parent_id: null,
  correlation_id: null, client_order_id: null, created_ts: "2026-10-25T12:00:00Z", updated_ts: "2026-10-25T12:00:00Z", ...over,
});

export const mmState = (over: Record<string, unknown> = {}) => ({
  instrument: "MARKETLAB-100",
  config: {
    fair_value: "100.00", spread: "0.10", quote_size: 100, quote_levels: 1, level_step_ticks: 1, max_inventory: 1000, inventory_sensitivity: "1.0",
    volatility: "0.02", arrival_rate: "0.5", buy_probability: "0.5", limit_order_fraction: "0.2", customer_order_size: 100, synthetic_limit_ttl_ticks: 20,
    fee_per_share: "0.005", tick_size: "0.01", lot_size: 1, max_order_qty: 100000, market_order_policy: "ioc", initial_cash: "1000000",
  },
  fair_value: "100.00",
  quote: { reference: "100.00", inventory: 0, utilization: "0", skew: "0", reservation: "100.00", bid: "99.95", ask: "100.05", bid_size: 100, ask_size: 100, spread: "0.10", bids: [], asks: [] },
  book: {
    venue: "MM", instrument: "MARKETLAB-100", best_bid: "99.95", best_ask: "100.05", spread: "0.10",
    bids: [{ price: "99.95", quantity: 100, orders: 1, by_owner: { mm: 100 }, order_ids: [] }, { price: "99.90", quantity: 50, orders: 1, by_owner: { customer: 50 }, order_ids: ["ORD-000010-aaaa"] }],
    asks: [{ price: "100.05", quantity: 100, orders: 1, by_owner: { mm: 100 }, order_ids: [] }],
  },
  ledger: {
    position: 0, avg_cost: null, cost_basis: "0", cash: "1000000", initial_cash: "1000000", mark_price: "100.00", market_value: "0", equity: "1000000",
    realized_pnl: "0", unrealized_pnl: "0", fees: "0", gross_pnl: "0", net_pnl: "0", gross_spread_captured: "0", trade_count: 0, traded_quantity: 0,
    buy_quantity: 0, sell_quantity: 0, open_lots: [], inventory_utilization: "0", max_inventory: 1000,
  },
  trades: [], customer_orders: [order()], series: [], stats: { resting_orders: 3 }, preset: null, ...over,
});

export const presets = [
  { id: "spread-capture", title: "Spread Capture", summary: "Buy at the bid, sell at the ask.", seed: 1, config: {}, steps: [{ title: "A customer sells 100 shares at market", action: {}, observe: "The market maker BUYS 100 at $99.95." }] },
];

export const fxState = (over: Record<string, unknown> = {}) => {
  const book = (name: string, ask: string, desc: string) => ({
    name, config: { name, description: desc, spread_pips: "0.6", price_offset_pips: "0", levels: 3, level_step_pips: "0.5", qty_per_level: 200000, fee_bps: "0.25", latency_ms: name === "C" ? 45 : 2 },
    pair: "GBP/USD", best_bid: "1.26997", best_ask: ask, spread: "0.00006", bids: [], asks: [{ price: ask, quantity: 200000, orders: 1, by_owner: { lp: 200000 }, order_ids: [] }],
    bid_depth: 600000, ask_depth: 600000, fill_rate: null, fund_requested_qty: 0, fund_filled_qty: 0, recent_trades: [], resting_fund_orders: [], latency_ms: name === "C" ? 45 : 2,
  });
  return {
    pair: { symbol: "GBP/USD", base: "GBP", quote: "USD", pip: "0.0001", tick_size: "0.00001", initial_mid: "1.27000", lot_size: 1000 },
    pairs: ["GBP/USD", "EUR/USD", "USD/JPY"], mid: "1.27000", mids: {}, weights: { include_fees: true, latency_penalty_bps_per_100ms: "0.1" },
    books: [book("A", "1.27003", "Tight spread, thin depth"), book("B", "1.27005", "Deep liquidity"), book("C", "1.27004", "Competitive, slow")],
    parents: [], rate_series: [{ tick: 0, mid: "1.27000" }], scenario: null, notice: "All rates are synthetic.", ...over,
  };
};

export const parent = {
  id: "PAR-000001-bbbb", pair: "GBP/USD", side: "buy", type: "market", quantity: 1000000, limit_price: null, routing_mode: "smart", purpose: "trade",
  hedge_id: null, status: "filled", filled_qty: 1000000, notional: "1270041", vwap: "1.2700410", total_fees: "23.50", unfilled_qty: 0, resting_qty: 0,
  children: ["A", "B", "C"].map((b, i) => ({ order_id: `ORD-00010${i}-cccc`, book: b, quantity: [200000, 300000, 500000][i], limit_price: "1.27005", tif: "ioc",
    status: "filled", filled_qty: [200000, 300000, 500000][i], avg_price: "1.27004", fees: "5.00", sim_latency_ms: 2, sent_ts: "2026-10-25T12:00:00.000Z", sim_arrival_ts: "2026-10-25T12:00:00.002Z", reason: null })),
  plan: { mode: "smart", side: "buy", quantity: 1000000, limit_price: null, include_fees: true, latency_penalty_bps_per_100ms: "0.1", planned_qty: 1000000, expected_vwap: "1.2700410", unfilled_qty: 0, explanation: "split", allocations: [], candidates: [] },
  explanation: "To buy 1,000,000, the router sent 200,000 to Book A, 300,000 to Book B, 500,000 to Book C.", created_ts: "2026-10-25T12:00:00Z",
};
