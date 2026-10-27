import { http } from "./client";
import type { Level, Order, Trade } from "./mm";

export type BookRole = "a_book" | "b_book" | "c_book";
export interface BookConfig {
  name: string; role: BookRole; description: string; spread_pips: string; price_offset_pips: string; fee_bps: string; latency_ms: number;
  levels: number; level_step_pips: string; qty_per_level: number; last_look_reject_pct: string;
  max_client_order: number; keep_pct: string;
}
export interface RoleInfo { title: string; who: string; how: string }
export interface DeskPair {
  pair: string; position: number; avg_price: string | null; mid: string; spread_earned: string; realized: string; unrealized: string;
  fees: string; pnl_usd: string; client_volume: number; externalised: number; direction: string;
}
export interface Desk {
  config: { hedge_threshold: number; max_position: number };
  pairs: DeskPair[]; gbp_exposure: number; total_pnl_usd: string;
  futures: { spec: { symbol: string; contract_size: number; label: string }; contracts: number; gbp_equivalent: number; price: string; unrealized_usd: string; realized_usd: string; fees_usd: string };
  log: { kind: string; book: string; pair: string; side: string; quantity: number; price: string; fee?: string }[];
}
export interface BookSnap {
  name: string; config: BookConfig; role: BookRole; role_info: RoleInfo; label: string; pair: string; best_bid: string | null; best_ask: string | null; spread: string | null;
  bids: Level[]; asks: Level[]; bid_depth: number; ask_depth: number; fill_rate: string | null; fund_requested_qty: number;
  fund_filled_qty: number; recent_trades: Trade[]; resting_fund_orders: Order[]; latency_ms: number;
}
export interface Candidate {
  book: string; price: string; available: number; fee_bps: string; latency_ms: number; effective_price: string; rank: number;
  allocated: number; eligible: boolean; note: string;
}
export interface Plan {
  mode: string; side: string; quantity: number; limit_price: string | null; include_fees: boolean; latency_penalty_bps_per_100ms: string;
  planned_qty: number; expected_vwap: string | null; unfilled_qty: number; explanation: string;
  allocations: { book: string; quantity: number; worst_price: string; levels: { price: string; quantity: number }[] }[];
  candidates: Candidate[];
}
export interface Child {
  order_id: string; book: string; quantity: number; limit_price: string | null; tif: string; status: string; filled_qty: number;
  avg_price: string | null; fees: string; sim_latency_ms: number; sent_ts: string; sim_arrival_ts: string; reason: string | null;
}
export interface Parent {
  id: string; pair: string; side: "buy" | "sell"; type: string; quantity: number; limit_price: string | null; routing_mode: string;
  purpose: string; hedge_id: string | null; status: string; filled_qty: number; notional: string; vwap: string | null; total_fees: string;
  unfilled_qty: number; resting_qty: number; children: Child[]; plan: Plan; explanation: string; created_ts: string;
}
export interface PairSpec { symbol: string; base: string; quote: string; pip: string; tick_size: string; initial_mid: string; lot_size: number }
export interface Scenario { id: string; title: string; expect: string; steps: { title: string; observe: string; action: Record<string, unknown> }[]; next_step?: number; complete?: boolean }
export interface FXState {
  pair: PairSpec; pairs: string[]; mid: string; mids: Record<string, string>; weights: { include_fees: boolean; latency_penalty_bps_per_100ms: string };
  books: BookSnap[]; parents: Parent[]; rate_series: { tick: number; mid: string }[]; scenario: Scenario | null; notice: string;
  desk: Desk;
}
export interface OrderBody {
  pair: string; side: string; type: string; quantity: number; limit_price?: string; routing_mode: string;
  weights?: { include_fees: boolean; latency_penalty_bps_per_100ms: string };
}

export const fxApi = {
  state: (pair: string) => http.get<FXState>(`/fx/state?pair=${encodeURIComponent(pair)}`),
  scenarios: () => http.get<Scenario[]>("/fx/scenarios"),
  loadScenario: (id: string) => http.post<FXState>(`/fx/scenarios/${id}/reset`),
  stepScenario: (id: string) => http.post<{ title: string; observe: string; parent?: Parent }>(`/fx/scenarios/${id}/step`),
  preview: (b: OrderBody) => http.post<Plan>("/fx/route-preview", b),
  submit: (b: OrderBody, key: string) => http.post<{ parent: Parent; idempotent_replay: boolean }>("/fx/orders", b, key),
  cancel: (id: string) => http.del<Parent>(`/fx/orders/${id}`),
  order: (id: string) => http.get<{ parent: Parent; trades: Trade[] }>(`/fx/orders/${id}`),
  putBook: (cfg: BookConfig) => http.put<BookConfig>(`/fx/books/${cfg.name}/config`, cfg),
  setRate: (pair: string, body: { rate?: string; shift_pct?: string }) => http.post("/fx/rates", { pair, ...body }),
  reset: () => http.post<FXState>("/fx/reset"),
  deskHedge: (pair: string) => http.post<{ message: string; before: number; after: number }>("/fx/desk/hedge", { pair }),
  deskConfig: (cfg: { hedge_threshold: number; max_position: number }) => http.put("/fx/desk/config", cfg),
};

// ---- portfolio / hedging --------------------------------------------------------------
export interface ExposureRow {
  currency: string; rate_to_usd: string; spot_balance: string; hedge_spot: string; futures_equivalent: string; net_exposure: string;
  net_exposure_usd: string; pre_hedge_exposure: string; pre_hedge_exposure_usd: string; direction: string;
  pnl_if_plus_1pct_usd: string; pnl_if_plus_1pct_pre_hedge_usd: string;
}
export interface FuturesSpec {
  symbol: string; underlying: string; contract_size: number; tick_size: string; days_total: number; days_to_expiry: number;
  initial_basis_pips: string; half_spread_ticks: number; fee_per_contract: string; initial_margin: string; maintenance_margin: string;
  max_fill_per_order: number; label: string;
}
export interface HedgeRequest {
  instrument: "fx_offset" | "futures"; mode: "manual" | "rule"; currency?: string; direction?: "buy" | "sell"; quantity?: number;
  routing_mode?: string; limit_price?: string; max_hedge_notional_usd?: string; target_exposure?: string; max_exposure?: string;
}
export interface Proposal {
  id: string; status: string; request: HedgeRequest; currency: string; instrument: string; direction: "buy" | "sell" | null; quantity: number;
  unit: string; gbp_equivalent: number; exposure_before: string; projected_exposure_after: string; projected_residual: string;
  est_price: string | null; est_fees_usd: string; est_notional_usd: string; pnl_plus1_before: string; pnl_plus1_after: string;
  explanation: string; assumptions: string[]; created_ts: string; executed_ts: string | null; filled_quantity: number;
  exec_price: string | null; exec_fees_usd: string; actual_exposure_after: string | null; parent_order_id: string | null; result: string | null;
}
export interface HedgeRule { enabled: boolean; auto_execute: boolean; instrument: "fx_offset" | "futures"; target_exposure: string; max_exposure: string }
export interface Portfolio {
  valuation_currency: string; rates: Record<string, string>; balances: { currency: string; amount: string; usd_value: string }[];
  exposures: ExposureRow[]; gross_exposure_usd: string; net_exposure_usd: string; equity_usd: string; initial_equity_usd: string;
  total_pnl_usd: string; pnl_breakdown: Record<string, string>;
  spot_positions: { pair: string; position: number; avg_price: string | null; mark: string; realized_usd: string; unrealized_usd: string; fees_usd: string }[];
  futures: {
    spec: FuturesSpec; contracts: number; gbp_equivalent: number; price: string; bid: string; ask: string; basis: string; basis_shock_pips: string;
    avg_entry: string | null; unrealized_usd: string; realized_usd: string; fees_usd: string; expired: boolean;
    margin: { initial_required: string; maintenance_required: string }; margin_note: string;
  };
  rule: HedgeRule; proposals: Proposal[];
  fills: { ts: string; instrument: string; kind: string; purpose: string; side: string; quantity: number; price: string; fee: string; fee_ccy: string; venue: string; parent_id?: string; hedge_id?: string }[];
  history: { n: number; gbp_usd: string; equity: string; pnl: string; gbp_exposure: string }[];
  guided_step: number; notice: string;
}
export interface RiskRow { id: string; title: string; unhedged: string; hedged: string; explain: string }
export interface Risk { spot: string; futures_price: string; pre_hedge_exposure_gbp: string; post_hedge_exposure_gbp: string; rows: RiskRow[]; assumptions: string[] }

export const pfApi = {
  state: () => http.get<Portfolio>("/portfolio"),
  risk: () => http.get<Risk>("/portfolio/risk"),
  propose: (r: HedgeRequest) => http.post<Proposal>("/hedges/proposals", r),
  execute: (id: string) => http.post<Proposal>(`/hedges/proposals/${id}/execute`),
  putRule: (r: HedgeRule) => http.put<HedgeRule>("/hedges/rule", r),
  basis: (shock_pips: string) => http.post("/portfolio/futures/basis", { shock_pips }),
  advanceDays: (days: number) => http.post<{ message: string }>("/portfolio/futures/advance-days", { days }),
  putSpec: (s: FuturesSpec) => http.put<FuturesSpec>("/portfolio/futures/spec", s),
  guidedReset: () => http.post<{ steps: string[] }>("/portfolio/scenarios/gbp-hedge/reset"),
  guidedStep: (instrument: string, rate_pct?: string) =>
    http.post<{ step: number; title: string; observe: string; proposal?: Proposal; parent?: Parent }>("/portfolio/scenarios/gbp-hedge/step", { instrument, ...(rate_pct ? { rate_pct } : {}) }),
};
