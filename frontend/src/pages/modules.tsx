import type { ReactNode } from "react";

export interface ModuleInfo {
  key: string;
  path: string;
  title: string;
  summary: string;
  icon: ReactNode;
  highlights: string[];
}

const svg = (d: string) => (
  <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d={d} />
  </svg>
);

export const MODULES: ModuleInfo[] = [
  {
    key: "mm",
    path: "/market-maker",
    title: "Market Maker Simulator",
    summary: "Watch a market maker quote bid and ask prices, trade with customers, manage inventory and earn — or lose — money.",
    icon: svg("M3 17l6-6 4 4 8-8M14 7h7v7"),
    highlights: [
      "Live bid/ask quotes that shift as inventory builds up",
      "A real order book with price-time priority and partial fills",
      "Cash, inventory, realized and unrealized P&L that reconcile with every trade",
    ],
  },
  {
    key: "fx",
    path: "/fx",
    title: "FX Order Routing and Hedging",
    summary: "Route currency orders across three independent order books, then hedge a fund's GBP exposure with FX trades or futures.",
    icon: svg("M4 7h13l-3-3M20 17H7l3 3"),
    highlights: [
      "Books A, B and C with different prices, depth, fees and latency",
      "Smart routing that splits a parent order and explains why",
      "A GBP/USD hedging walkthrough with residual-exposure accounting",
    ],
  },
  {
    key: "tcp",
    path: "/tcp-lab",
    title: "TCP Performance Lab",
    summary: "See how traders front-load orders (send 499 bytes early, the last byte on the decision) and race a pre-sent order against a full one.",
    icon: svg("M4 12h4l3-7 4 14 3-7h2"),
    highlights: [
      "Real benchmark requests against MarketLab's own backend",
      "Front-loaded vs. full orders racing on the same signal; cold vs. open connections",
      "Latency distributions, percentiles and CSV export",
    ],
  },
];
