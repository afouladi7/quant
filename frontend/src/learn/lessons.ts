// The learning path. Each lesson: a short explanation, key ideas, an optional formula,
// a "try it" link into the app, and a quiz whose answers are explained.

export interface QuizQuestion {
  q: string;
  options: string[];
  answer: number;
  why: string;
}

export interface Lesson {
  id: string;
  level: 1 | 2 | 3;
  title: string;
  minutes: number;
  summary: string;
  body: string[];
  keyIdeas: string[];
  formula?: string;
  tryIt: { label: string; to: string; steps: string[] };
  quiz: QuizQuestion[];
}

export const LEVELS: Record<1 | 2 | 3, { name: string; who: string }> = {
  1: { name: "Beginner: how markets work", who: "No finance background needed." },
  2: { name: "Intermediate: trading and risk", who: "You know what a bid and ask are." },
  3: { name: "Advanced: quant models and systems", who: "Comfortable with formulas or code." },
};

export const LESSONS: Lesson[] = [
  {
    id: "what-is-a-market", level: 1, minutes: 4, title: "What is a market? Bid, ask and spread",
    summary: "Buyers say what they'll pay, sellers say what they'll accept, and a trade happens when they meet.",
    body: [
      "Imagine a noticeboard. Buyers pin notes saying “I'll buy 5 at $99”. Sellers pin notes saying “I'll sell 3 at $101”.",
      "The best buyer's price is the bid. The best seller's price is the ask. The gap between them is the spread.",
      "If nobody's prices overlap, nothing trades. As soon as someone is willing to pay the ask (or accept the bid), a trade happens.",
    ],
    keyIdeas: ["Bid = best price to sell into", "Ask = best price to buy from", "Spread = ask − bid: the cost of trading immediately"],
    formula: "spread = ask − bid      mid = (bid + ask) / 2",
    tryIt: { label: "Open the Order Book Playground", to: "/playground", steps: ["Look at the best bid ($99) and best ask ($101).", "The spread is $2.", "Send a buy limit at $101 and watch it trade."] },
    quiz: [
      { q: "The best bid is $99 and the best ask is $101. What is the spread?", options: ["$1", "$2", "$100", "$200"], answer: 1, why: "Spread = ask − bid = 101 − 99 = $2." },
      { q: "You want to buy right now. Which price do you pay?", options: ["The bid", "The ask", "The mid", "Any price you like"], answer: 1, why: "To buy immediately you take the cheapest seller: the ask." },
    ],
  },
  {
    id: "order-book", level: 1, minutes: 5, title: "The order book and who trades first",
    summary: "Orders wait in a queue. Best price goes first; at the same price, first come first served.",
    body: [
      "The order book is the list of waiting orders: buyers sorted from highest price down, sellers from lowest price up.",
      "When a new order arrives that can trade, the matching engine pairs it with waiting orders. The best price always goes first.",
      "If two orders have the same price, the one that arrived earlier trades first. This rule is called price-time priority.",
      "Trades happen at the price of the order that was already waiting (the maker), not the newcomer (the taker).",
    ],
    keyIdeas: ["Best price first", "Same price: earliest first", "Trade price = the waiting order's price"],
    tryIt: { label: "See price-time priority step by step", to: "/playground", steps: ["Alice and Bob both sell at $101; Alice was first.", "Buy 7 with a limit of $102.", "Read the explanation: Alice fills 5, then Bob fills 2, all at $101."] },
    quiz: [
      { q: "Alice (first) and Bob (second) both sell at $101. You buy 3. Who sells to you?", options: ["Bob", "Alice", "Half each", "Whoever is cheaper"], answer: 1, why: "Same price, so time decides: Alice arrived first." },
      { q: "You send a buy limit at $105 and the best ask is $101. What price do you pay?", options: ["$105", "$103", "$101", "$100"], answer: 2, why: "You trade at the resting order's price: $101. Your limit is only a maximum." },
    ],
  },
  {
    id: "order-types", level: 1, minutes: 4, title: "Market orders, limit orders and partial fills",
    summary: "A market order guarantees speed; a limit order guarantees price. You can't have both.",
    body: [
      "A market order says “now, at whatever price is available”. It may pay more than the best price if the first level runs out (“walking the book”).",
      "A limit order says “only at this price or better”. If nobody is there yet, it waits in the book.",
      "If only part of an order can trade, that's a partial fill. In MarketLab the unfilled part of a market order is canceled; a limit order's remainder waits.",
    ],
    keyIdeas: ["Market = certainty of trading, uncertain price", "Limit = certain price, uncertain fill", "Partial fills are normal"],
    tryIt: { label: "Try both in the playground", to: "/playground", steps: ["Send a market sell for 20: only what is available trades; the rest is canceled.", "Send a buy limit at $100: it waits in the book as the new best bid."] },
    quiz: [
      { q: "Which order type can never trade at a worse price than you chose?", options: ["Market", "Limit", "Both", "Neither"], answer: 1, why: "A limit order's price is a hard boundary." },
      { q: "You market-buy 10 but only 6 are offered. What happens here?", options: ["Nothing trades", "6 trade, 4 are canceled", "10 trade at a higher price", "The order waits"], answer: 1, why: "Market orders take what exists (IOC); the rest is canceled." },
    ],
  },
  {
    id: "market-maker", level: 1, minutes: 5, title: "What does a market maker do?",
    summary: "A market maker always quotes a bid and an ask and earns the spread, but carries risk while holding stock.",
    body: [
      "Markets work better when someone is always willing to trade. A market maker posts a bid and an ask continuously.",
      "If one customer sells to it at the bid and another buys from it at the ask, it earns the spread.",
      "Between those two trades it owns the stock. If the price drops meanwhile, it can lose more than the spread earned.",
    ],
    keyIdeas: ["Earns the spread on round trips", "Pays fees on every trade", "Holds inventory, which is risky"],
    tryIt: { label: "Run the Spread Capture demo", to: "/market-maker", steps: ["Load “Spread Capture”.", "Run steps 1–2: a $10 gross profit, $9 after fees.", "Run steps 3–4: a price drop wipes out the profit."] },
    quiz: [
      { q: "The market maker buys 100 at $99.95 and sells 100 at $100.05. Gross profit before fees?", options: ["$0.10", "$1", "$10", "$100"], answer: 2, why: "$0.10 per share × 100 shares = $10." },
      { q: "Is earning the spread a guaranteed profit?", options: ["Yes", "No"], answer: 1, why: "Prices can move while the market maker holds inventory, and fees are paid on every trade." },
    ],
  },
  {
    id: "pnl", level: 1, minutes: 5, title: "Profit and loss: realized vs unrealized",
    summary: "Realized P&L is locked in; unrealized P&L is what you'd make if you closed now.",
    body: [
      "When you sell something you bought, the profit or loss is realized: it can't change any more.",
      "If you still hold something, its profit or loss is unrealized: it changes with every price move. We value holdings at the current fair price (marking to market).",
      "Fees are paid in cash and reduce profit. Net P&L = realized + unrealized − fees.",
      "MarketLab uses FIFO: the oldest purchase is considered sold first.",
    ],
    keyIdeas: ["Realized = closed", "Unrealized = still open, at today's price", "Net = realized + unrealized − fees"],
    formula: "net P&L = realized + unrealized − fees\nunrealized = quantity × (current price − purchase price)",
    tryIt: { label: "Watch the P&L tiles change", to: "/market-maker", steps: ["Load “Spread Capture”, run step 1: +$5 unrealized (bought at 99.95, marked at 100).", "Run step 2: the $10 becomes realized."] },
    quiz: [
      { q: "You hold 100 shares bought at $10. The price is now $12. Unrealized P&L?", options: ["$2", "$200", "$1,200", "$0"], answer: 1, why: "100 × (12 − 10) = $200." },
      { q: "You sell those shares at $12. What happens to that $200?", options: ["It disappears", "It becomes realized", "It becomes a fee", "It doubles"], answer: 1, why: "Closing the position locks it in as realized P&L." },
    ],
  },
  {
    id: "fx-basics", level: 1, minutes: 4, title: "Currencies and FX pairs",
    summary: "GBP/USD 1.27 means £1 costs $1.27. Buying the pair means buying pounds with dollars.",
    body: [
      "Foreign exchange (FX) is trading one currency for another. Prices are quoted as pairs: BASE/QUOTE.",
      "GBP/USD = 1.27000 means one British pound costs 1.27 US dollars. If it rises to 1.28, the pound got stronger.",
      "Small moves are measured in pips: 0.0001 for most pairs. 1.27000 → 1.27010 is one pip.",
    ],
    keyIdeas: ["BASE/QUOTE = quote currency per 1 base", "Buying GBP/USD = buying pounds, paying dollars", "1 pip = 0.0001"],
    tryIt: { label: "See the FX books", to: "/fx", steps: ["Look at GBP/USD in books A, B and C.", "Each book shows slightly different prices and amounts."] },
    quiz: [
      { q: "GBP/USD goes from 1.2700 to 1.2800. What happened?", options: ["The pound weakened", "The pound strengthened", "Nothing", "The dollar strengthened"], answer: 1, why: "One pound now buys more dollars." },
      { q: "How many pips is 1.27000 → 1.27050?", options: ["0.5", "5", "50", "500"], answer: 1, why: "0.0005 / 0.0001 = 5 pips." },
    ],
  },
  {
    id: "inventory-risk", level: 2, minutes: 5, title: "Inventory risk and quote skew",
    summary: "A market maker leans its prices to attract the trades that shrink its risk.",
    body: [
      "If customers keep buying, the market maker keeps selling and ends up short. If the price then rises, it loses money.",
      "To manage this, it skews its quotes: when short it raises both bid and ask, making buying from it less attractive and selling to it more attractive.",
      "At its inventory limit it stops quoting the side that would add more risk.",
    ],
    keyIdeas: ["Inventory = risk", "Skew prices toward reducing inventory", "Hard limits stop risk growing"],
    formula: "skew = −sensitivity × (inventory / max inventory) × spread\nbid, ask = fair + skew ∓ spread/2",
    tryIt: { label: "Run the Inventory Risk demo", to: "/market-maker", steps: ["Load “Inventory Risk” and run the three steps.", "Watch inventory go negative and the quotes move above fair value.", "At −1,000 the ask disappears."] },
    quiz: [
      { q: "The market maker is very long (holds a lot). Which way do its quotes move?", options: ["Up", "Down", "They don't move", "The spread doubles"], answer: 1, why: "Lower prices attract buyers and discourage further selling to it." },
    ],
  },
  {
    id: "routing", level: 2, minutes: 6, title: "Fragmented liquidity and smart order routing",
    summary: "The best price is not always the best deal once you account for size, fees and speed.",
    body: [
      "The same currency trades on many venues. Each has its own prices, depth, fees and speed.",
      "A large order can exhaust the best price on one venue and “walk the book” to worse prices. Another venue with a slightly worse top price but more depth can be cheaper overall.",
      "A smart router ranks every available price across venues by effective cost (price + fees + a latency penalty) and fills from the cheapest, splitting the order into child orders.",
    ],
    keyIdeas: ["Top-of-book price ≠ average price for size", "Fees and latency are costs too", "Parent order → child orders"],
    formula: "effective price = price × (1 ± (fee bps + latency penalty) / 10,000)\naverage price (VWAP) = Σ(price × qty) / Σ qty",
    tryIt: { label: "Run FX scenarios 1, 2 and 4", to: "/fx", steps: ["Scenario 1: Book A's best price runs out.", "Scenario 2: Book B is better for 500,000.", "Scenario 4: the router splits 1,000,000 across books."] },
    quiz: [
      { q: "Book A: 200k at 1.27003, then 1.27008. Book B: 1M at 1.27005. You buy 500k. Better choice?", options: ["Book A", "Book B", "They're identical", "Can't tell"], answer: 1, why: "A averages ~1.27007 for 500k; B fills all at 1.27005." },
    ],
  },
  {
    id: "hedging", level: 2, minutes: 6, title: "Exposure and hedging",
    summary: "A hedge is a second position designed to gain when your first one loses.",
    body: [
      "A US fund that owns £1,000,000 gains about $12,700 if the pound rises 1% and loses the same if it falls 1%. That sensitivity is its exposure.",
      "To reduce it, the fund can sell pounds (an offset trade) or sell GBP futures. Either way, losses on one side are offset by gains on the other.",
      "Hedging removes upside as well as downside, costs fees, and can leave residual risk (rounding, partial fills, basis).",
    ],
    keyIdeas: ["Exposure = sensitivity to a price move", "Hedge = offsetting position", "Hedges reduce risk, they don't create profit"],
    formula: "P&L for a 1% move ≈ exposure × price × 1%",
    tryIt: { label: "Run the GBP hedging walkthrough", to: "/fx?tab=hedging", steps: ["Buy £1m, move GBP/USD +1%.", "Calculate and execute a futures hedge.", "Move the rate −1% and compare."] },
    quiz: [
      { q: "You own £1m at 1.27. GBP falls 1%. Roughly what is the loss in USD?", options: ["$1,270", "$12,700", "$127,000", "$0"], answer: 1, why: "1,000,000 × 1.27 × 1% = $12,700." },
      { q: "After a perfect hedge, GBP rises 1%. What happens?", options: ["You gain $12,700", "Roughly nothing", "You lose $12,700", "You gain double"], answer: 1, why: "The hedge loses what the position gains." },
    ],
  },
  {
    id: "futures", level: 2, minutes: 6, title: "Futures, basis and expiry",
    summary: "A future locks in a price for later. Its price differs from spot by the basis, which shrinks to zero at expiry.",
    body: [
      "A futures contract is an agreement to trade later at a price fixed today. Contracts have a fixed size (here £62,500), so hedges are rounded to whole contracts.",
      "The futures price usually differs from the spot price. The difference, the basis, reflects interest-rate differences and shrinks to zero at expiry.",
      "If the basis changes unexpectedly, the hedge stops matching the exposure exactly: that's basis risk. At expiry the hedge ends and must be rolled to keep protection.",
    ],
    keyIdeas: ["Whole contracts → residual exposure", "Basis = future − spot", "Expiry ends the hedge"],
    formula: "contracts = round(exposure / contract size)\nbasis = F − S → 0 at expiry",
    tryIt: { label: "Shock the basis and advance to expiry", to: "/fx?tab=hedging", steps: ["Hedge £1m with futures (16 contracts).", "Apply a basis shock of +5 pips: −$500.", "Advance 100 days: the contract settles, exposure returns."] },
    quiz: [
      { q: "Exposure £1,030,000, contract size £62,500. How many contracts and what's left over?", options: ["16, £30,000", "17, £0", "16, £0", "15, £92,500"], answer: 0, why: "1,030,000 / 62,500 = 16.48 → 16 contracts = £1,000,000; £30,000 remains unhedged." },
    ],
  },
  {
    id: "returns-vol", level: 2, minutes: 6, title: "Returns, volatility and drawdown",
    summary: "Return is how much you made; volatility is how bumpy the ride was; drawdown is how bad the worst fall felt.",
    body: [
      "A daily return is the percentage change from one day to the next. Many small returns compound into the total return.",
      "Volatility measures how spread out returns are. It is usually quoted per year: daily volatility × √252 trading days.",
      "Drawdown is the fall from the highest point so far. Max drawdown is the worst such fall: the number that keeps investors up at night.",
      "The Sharpe ratio divides excess return by volatility: return per unit of risk.",
    ],
    keyIdeas: ["Annual vol = daily vol × √252", "Max drawdown = worst peak-to-trough", "Sharpe = (return − risk-free) / volatility"],
    formula: "r_t = P_t / P_(t−1) − 1\nσ_annual = stdev(r) × √252\nSharpe = (mean(r) × 252 − r_f) / σ_annual",
    tryIt: { label: "Simulate prices in the Risk Lab", to: "/risk", steps: ["Change volatility from 20% to 40% and re-run.", "Compare the max drawdown and Sharpe ratio.", "Change the seed to see a different random path."] },
    quiz: [
      { q: "Daily volatility is 1%. Roughly what is annual volatility?", options: ["1%", "~16%", "252%", "~50%"], answer: 1, why: "1% × √252 ≈ 15.9%." },
      { q: "A price goes 100 → 150 → 90. What is the max drawdown?", options: ["−10%", "−40%", "−50%", "+50%"], answer: 1, why: "From the peak of 150 to 90 is −40%." },
    ],
  },
  {
    id: "var", level: 2, minutes: 6, title: "Value at Risk and fat tails",
    summary: "VaR answers “how bad is a bad day?”, but not “how bad is the worst day?”.",
    body: [
      "95% one-day VaR is a loss that should be exceeded on only 1 day in 20. Historical VaR reads it from past returns; parametric VaR assumes a bell curve.",
      "Expected shortfall is the average loss on the days beyond VaR, which says more about disasters.",
      "Real markets have fat tails: extreme days happen more often than a bell curve predicts, so parametric VaR can be too optimistic.",
    ],
    keyIdeas: ["VaR is a threshold, not a worst case", "Expected shortfall looks past the threshold", "Fat tails break bell-curve assumptions"],
    formula: "VaR_95 (parametric) = −(mean − 1.645 × stdev)\nES = average loss on days worse than VaR",
    tryIt: { label: "Switch on crash days", to: "/risk", steps: ["Run with crash days off, note VaR 99% and kurtosis.", "Turn crash days on and re-run.", "Historical VaR and expected shortfall jump; the bell curve under-predicts."] },
    quiz: [
      { q: "95% daily VaR is 2%. What does that mean?", options: ["You never lose more than 2%", "On about 1 day in 20 you lose more than 2%", "You lose 2% every day", "You gain 2%"], answer: 1, why: "VaR is exceeded on the remaining 5% of days." },
    ],
  },
  {
    id: "diversification", level: 2, minutes: 5, title: "Diversification and correlation",
    summary: "Combining assets that don't move together lowers risk without necessarily lowering return.",
    body: [
      "Correlation measures how two assets move together, from −1 (opposite) to +1 (in lockstep).",
      "A portfolio's volatility is less than the average of its parts unless correlation is +1. That gap is the diversification benefit: the closest thing to a free lunch in finance.",
      "With correlation −1, the right mix cancels risk entirely.",
    ],
    keyIdeas: ["Lower correlation → more benefit", "Correlation +1 → no benefit", "There is a minimum-risk mix"],
    formula: "σ_p² = w₁²σ₁² + w₂²σ₂² + 2·w₁·w₂·ρ·σ₁·σ₂",
    tryIt: { label: "Play with correlation", to: "/risk", steps: ["In the Diversification panel, set correlation to +1: the curve is a straight line.", "Set it to 0, then −1, and watch the risk curve bend."] },
    quiz: [
      { q: "Two assets each have 20% volatility and correlation +1. 50/50 mix volatility?", options: ["0%", "~14%", "20%", "40%"], answer: 2, why: "With correlation +1 there is no diversification: 20%." },
    ],
  },
  {
    id: "options-basics", level: 3, minutes: 6, title: "Options and payoffs",
    summary: "An option is a right, not an obligation. You pay a premium for asymmetric payoffs.",
    body: [
      "A call gives the right to buy at the strike price; a put, the right to sell. The buyer pays a premium for that right.",
      "At expiry a call is worth max(stock − strike, 0); a put max(strike − stock, 0). The buyer's loss is limited to the premium.",
      "Before expiry the option is worth more than its intrinsic value: the extra is time value, the chance it ends up better.",
    ],
    keyIdeas: ["Call = right to buy, put = right to sell", "Premium = intrinsic + time value", "Buyer's max loss = premium"],
    formula: "call payoff = max(S − K, 0)      put payoff = max(K − S, 0)\nbreakeven (call) = K + premium",
    tryIt: { label: "Draw payoff diagrams", to: "/options", steps: ["Look at the payoff-at-expiry line vs value-today curve.", "Switch to a put.", "Move the strike and watch intrinsic and time value change."] },
    quiz: [
      { q: "Call with strike 100. At expiry the stock is 112. Payoff?", options: ["0", "12", "100", "112"], answer: 1, why: "max(112 − 100, 0) = 12." },
      { q: "Same call, stock at 95 at expiry. Payoff?", options: ["−5", "0", "5", "95"], answer: 1, why: "You don't exercise; the payoff is 0 (you lost the premium)." },
    ],
  },
  {
    id: "black-scholes", level: 3, minutes: 8, title: "Black-Scholes and the Greeks",
    summary: "A formula that prices options from five inputs, and five sensitivities that traders manage.",
    body: [
      "Black-Scholes assumes prices follow a random walk with constant volatility. From spot, strike, time, rate and volatility it gives a fair option price.",
      "The Greeks describe how that price reacts: delta (stock moves), gamma (how delta changes), vega (volatility), theta (time passing), rho (interest rates).",
      "Traders use delta to hedge: holding −delta shares per call makes small stock moves cancel out.",
    ],
    keyIdeas: ["5 inputs: S, K, T, r, σ", "Delta ≈ shares needed to hedge", "Theta: options lose value as time passes"],
    formula: "d1 = [ln(S/K) + (r + σ²/2)T] / (σ√T),   d2 = d1 − σ√T\nC = S·N(d1) − K·e^(−rT)·N(d2)",
    tryIt: { label: "Explore the Greeks", to: "/options", steps: ["Increase volatility: price and vega rise.", "Reduce days to 1: theta grows, gamma spikes near the strike.", "Check put-call parity in Technical view."] },
    quiz: [
      { q: "A call has delta 0.6. The stock rises $1. The option rises about…", options: ["$0.06", "$0.60", "$1", "$6"], answer: 1, why: "Delta is the change per $1 move in the stock." },
      { q: "All else equal, what happens to an option's value as expiry approaches?", options: ["Rises", "Falls (theta)", "Unchanged", "Becomes the strike"], answer: 1, why: "Time value decays: theta is negative for a long option." },
    ],
  },
  {
    id: "iv-binomial", level: 3, minutes: 6, title: "Implied volatility and binomial trees",
    summary: "Read volatility out of market prices, and price options by walking a tree of possible futures.",
    body: [
      "Volatility is the only Black-Scholes input you can't observe. Turning the formula around, from a market price to a volatility, gives implied volatility: the market's estimate.",
      "A binomial tree models the stock going up or down each step. Working backwards from expiry gives a price that converges to Black-Scholes as steps increase.",
      "Trees can also price American options, which may be exercised early; that's where they differ from Black-Scholes.",
    ],
    keyIdeas: ["Implied vol = vol that matches the market price", "Trees converge to Black-Scholes", "Trees handle early exercise"],
    tryIt: { label: "Solve implied vol and watch convergence", to: "/options", steps: ["Enter a market price in the implied-volatility box.", "In Technical view, see the binomial price approach Black-Scholes as steps grow."] },
    quiz: [
      { q: "A market option price rises while S, K, T and r are unchanged. Implied volatility…", options: ["Falls", "Rises", "Unchanged", "Becomes zero"], answer: 1, why: "Higher price ⇔ higher volatility (vega is positive)." },
    ],
  },
  {
    id: "backend", level: 3, minutes: 7, title: "How the backend works",
    summary: "Browser → web server → API → engine → events → live updates back to every browser.",
    body: [
      "When you click “Buy”, the browser sends an HTTP request to the frontend server (nginx), which forwards /api requests to the backend.",
      "The backend (Python, FastAPI) validates the request, then the matching engine updates the order book, ledger and P&L in memory. Every step is recorded as an event.",
      "Events are pushed to all browsers over a WebSocket, which is why charts and timelines update live without refreshing.",
      "Decimal arithmetic avoids floating-point rounding errors in money, and idempotency keys stop duplicate orders on retries.",
    ],
    keyIdeas: ["Frontend shows, backend decides", "Every action becomes an event", "WebSocket = live push updates"],
    tryIt: { label: "Open How It Works", to: "/how-it-works", steps: ["Watch the live request inspector while you place an order.", "Open the API explorer and try a GET endpoint."] },
    quiz: [
      { q: "Where is the authoritative order book kept?", options: ["In the browser", "In the backend", "In nginx", "In the URL"], answer: 1, why: "The backend owns all state; the browser only displays it." },
      { q: "Why use an idempotency key?", options: ["Speed", "So a retried request doesn't create a duplicate order", "Encryption", "Logging"], answer: 1, why: "The server recognises the repeat and returns the original result." },
    ],
  },
  {
    id: "tcp", level: 3, minutes: 7, title: "TCP, latency and measuring it properly",
    summary: "TCP delivers a stream of bytes, not messages. Connection setup costs time; splitting a message rarely helps.",
    body: [
      "TCP guarantees bytes arrive in order, but has no idea where one message ends. The application must frame messages (here, a length header).",
      "Opening a connection costs a round trip before any data flows. Reusing a connection avoids that cost.",
      "Sending 499 bytes then 1 byte can't finish before the last byte arrives; only useful work done in the meantime can recover the delay.",
      "Latency must be measured as a distribution: look at the median and the tail (p95, p99), not one number.",
    ],
    keyIdeas: ["Byte stream → framing needed", "Reuse connections", "Report percentiles"],
    tryIt: { label: "Run the TCP comparison", to: "/tcp-lab", steps: ["Run the standard comparison.", "Compare cold vs pre-established connection.", "Compare split-with-prep-after vs useful early work."] },
    quiz: [
      { q: "Which removes the TCP handshake from a request's latency?", options: ["Splitting the message", "Reusing an open connection", "Turning off the server", "A bigger message"], answer: 1, why: "An existing connection has already done its handshake." },
      { q: "p95 latency is 3 ms. Meaning?", options: ["Average is 3 ms", "95% of requests were faster than 3 ms", "The fastest was 3 ms", "3% failed"], answer: 1, why: "A percentile is a threshold below which that share of measurements fall." },
    ],
  },
];
