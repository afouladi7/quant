import { http } from "./client";

export interface Level { price: string; quantity: number; orders: number; by_owner: Record<string, number>; order_ids: string[] }
export interface Depth { venue: string; instrument: string; best_bid: string | null; best_ask: string | null; spread: string | null; bids: Level[]; asks: Level[] }
export interface Order {
  id: string; venue: string; instrument: string; owner: string; side: "buy" | "sell"; type: "market" | "limit"; tif: string;
  quantity: number; limit_price: string | null; filled_qty: number; avg_fill_price: string | null; fees: string;
  status: string; reason: string | null; parent_id: string | null; correlation_id: string | null; client_order_id: string | null;
  created_ts: string; updated_ts: string;
}
export interface Trade {
  id: string; venue: string; instrument: string; price: string; quantity: number; aggressor_side: "buy" | "sell";
  taker_order_id: string; maker_order_id: string; taker_owner: string; maker_owner: string; taker_fee: string; maker_fee: string;
  correlation_id: string | null; ts: string; tick: number; mm_side?: "buy" | "sell" | null;
}
export interface MMConfig {
  fair_value: string; spread: string; quote_size: number; quote_levels: number; level_step_ticks: number; max_inventory: number;
  inventory_sensitivity: string; volatility: string; arrival_rate: string; buy_probability: string; limit_order_fraction: string;
  customer_order_size: number; synthetic_limit_ttl_ticks: number; fee_per_share: string; tick_size: string; lot_size: number;
  max_order_qty: number; market_order_policy: "ioc" | "fok"; initial_cash: string;
}
export interface QuoteInfo {
  reference: string; inventory: number; utilization: string; skew: string; reservation: string; bid: string | null; ask: string | null;
  bid_size: number; ask_size: number; spread: string | null; bids: { price: string; size: number }[]; asks: { price: string; size: number }[];
}
export interface Ledger {
  position: number; avg_cost: string | null; cost_basis: string; cash: string; initial_cash: string; mark_price: string; market_value: string;
  equity: string; realized_pnl: string; unrealized_pnl: string; fees: string; gross_pnl: string; net_pnl: string; gross_spread_captured: string;
  trade_count: number; traded_quantity: number; buy_quantity: number; sell_quantity: number; open_lots: { quantity: number; price: string }[];
  inventory_utilization: string; max_inventory: number;
}
export interface PresetStep { title: string; action: Record<string, unknown>; observe: string }
export interface Preset { id: string; title: string; summary: string; seed: number; config: Record<string, unknown>; steps: PresetStep[]; next_step?: number; complete?: boolean }
export interface MMState {
  instrument: string; config: MMConfig; fair_value: string; quote: QuoteInfo | null; book: Depth; ledger: Ledger; trades: Trade[];
  customer_orders: Order[]; series: { n: number; tick: number; fair: string; bid: string | null; ask: string | null; inventory: number; net_pnl: string }[];
  stats: Record<string, number>; preset: Preset | null;
}
export interface OrderResponse { order: Order; trades: Trade[]; explanation: string; idempotent_replay: boolean }

export const mmApi = {
  state: () => http.get<MMState>("/mm/state"),
  presets: () => http.get<Preset[]>("/mm/presets"),
  loadPreset: (id: string) => http.post<MMState>(`/mm/presets/${id}/load`),
  stepPreset: (id: string) => http.post<{ step: number; title: string; observe: string; explanation?: string }>(`/mm/presets/${id}/step`),
  submit: (body: { side: string; type: string; quantity: number; limit_price?: string; tif?: string }, key: string) =>
    http.post<OrderResponse>("/mm/orders", body, key),
  cancel: (id: string) => http.del<Order>(`/mm/orders/${id}`),
  reset: () => http.post<MMState>("/mm/reset"),
  putConfig: (cfg: MMConfig) => http.put<MMConfig>("/mm/config", cfg),
  shiftFair: (shift: string) => http.post("/mm/fair-value", { shift }),
};
