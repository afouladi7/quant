// Site map: one place defines the sidebar groups, page titles and who each page is for.
export interface NavItem { to: string; label: string; level: "Beginner" | "Intermediate" | "Advanced" | "All levels"; blurb: string }
export interface NavGroup { title: string; items: NavItem[] }

export const NAV: NavGroup[] = [
  {
    title: "Start",
    items: [
      { to: "/", label: "Home", level: "All levels", blurb: "What MarketLab is and where to begin." },
      { to: "/learn", label: "Learning path", level: "All levels", blurb: "Short lessons with quizzes, from beginner to advanced." },
      { to: "/glossary", label: "Glossary", level: "All levels", blurb: "Every term explained in plain English." },
    ],
  },
  {
    title: "Markets",
    items: [
      { to: "/playground", label: "Order book playground", level: "Beginner", blurb: "Place orders yourself and see exactly how they match." },
      { to: "/market-maker", label: "Market maker", level: "Beginner", blurb: "Quote prices, trade with customers, track inventory and P&L." },
      { to: "/fx", label: "FX routing & hedging", level: "Intermediate", blurb: "Route currency orders across three books, then hedge the risk." },
    ],
  },
  {
    title: "Quant labs",
    items: [
      { to: "/risk", label: "Risk & returns", level: "Intermediate", blurb: "Volatility, drawdown, Sharpe ratio, VaR and diversification." },
      { to: "/options", label: "Options", level: "Advanced", blurb: "Black-Scholes, the Greeks, payoffs and implied volatility." },
    ],
  },
  {
    title: "Technology",
    items: [
      { to: "/tcp-lab", label: "TCP latency lab", level: "Advanced", blurb: "Measure how networking choices change real latency." },
      { to: "/how-it-works", label: "How it works", level: "All levels", blurb: "How a click travels through the backend, live." },
    ],
  },
];
