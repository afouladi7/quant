# MarketLab

An interactive laboratory for understanding how financial markets work, how traders manage risk, and how
software networking affects performance. **Every trade and price in the simulator is hypothetical.** No real
orders, funds, accounts or market data are involved.

Built for every level: start with the **learning path** (18 short lessons with quizzes), hover any underlined term for a
definition, and press **?** on any panel to learn what it shows.

| Area | Level | What you can do |
|---|---|---|
| **Learning path & glossary** | All | Lessons from “what is a bid?” to Black-Scholes and backend design, each with a hands-on exercise and a quiz; about 75 terms defined in plain English. |
| **Order book playground** | Beginner | Place orders as yourself, Alice, Bob or Carol and get a step-by-step explanation of how the matching engine handled each one. |
| **Market maker** | Beginner | Watch a market maker quote, trade with customers through a price-time-priority matching engine, and track inventory, cash and P&L. Guided presets: *Spread Capture*, *Inventory Risk*. |
| **FX routing & hedging** | Intermediate | Trade currencies through a broker's **A-book** (passed to outside liquidity providers, with last look), **B-book** (the broker takes the other side and hedges with 6B-style British pound futures) or **C-book** (hybrid), or let the smart router split the order; eight reproducible scenarios; then hedge the fund's own GBP exposure and compare risk scenarios. |
| **Risk & returns lab** | Intermediate | Simulate prices and measure returns, volatility, drawdown, Sharpe ratio, historical vs. bell-curve VaR, fat tails, and diversification between two assets. |
| **Options lab** | Advanced | Black-Scholes prices, the Greeks in plain English, payoff and time-decay charts, implied volatility, put-call parity and binomial-tree convergence. |
| **TCP latency lab** | Advanced | Real benchmarks against the backend itself: complete vs. split messages, cold vs. reused connections, useful early work, percentiles, CSV export. |
| **How it works** | All | Follow a click through the system, watch the browser's real API calls live, explore every endpoint, and jump to the source code. |

Every view has a **Simple** (plain English) and a **Technical** (IDs, formulas, raw events, routing
calculations, per-trial timings) presentation, driven by the same backend data. Status: see
[`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md).

## Architecture

```
Browser ──HTTPS──► Route ──► frontend (nginx: SPA + /api reverse proxy, WebSocket-aware)
                                  │ ClusterIP
                                  ▼
                            backend (FastAPI, 1 process, authoritative in-memory state)
                              ├─ simulation clock (seeded, start/pause/reset/speed/step)
                              ├─ market maker · FX books A/B/C + router · portfolio & hedging
                              ├─ TCP lab (raw TCP listener + HTTP echo, loopback only)
                              ├─ event bus → bounded history → WebSocket
                              └─ optional PostgreSQL archive (events, trades, benchmarks, configs)
```

Details: [`docs/DESIGN.md`](docs/DESIGN.md) (design, data models, API contracts) ·
[`docs/OPERATIONS.md`](docs/OPERATIONS.md) (deployment, air-gap, configuration, troubleshooting) ·
[`docs/finance-guide.md`](docs/finance-guide.md) · [`docs/networking-guide.md`](docs/networking-guide.md).

## Prerequisites

| For | Need |
|---|---|
| Local development | Python ≥ 3.12, Node.js 22 + npm |
| Container builds | podman (or buildah); no root or privileged mode |
| Cluster deployment | `oc` (or `kubectl`) with *edit* rights on one namespace; `kustomize` optional (`oc kustomize` otherwise) |

## Local development

```bash
git clone https://github.com/afouladi7/quant.git && cd quant
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements-dev.txt
cd backend && .venv/bin/uvicorn --factory app.main:factory --port 8000      # http://127.0.0.1:8000
cd frontend && npm ci && npm run dev                                          # http://localhost:5173 (proxies /api)
```

Optional: `cp .env.example backend/.env`. Note: `uvicorn --reload` sockets lack TCP_NODELAY, which distorts HTTP
benchmarks in the TCP lab (see the networking guide); run without `--reload` when benchmarking.

## Containers

```bash
scripts/build-images.sh                       # localhost/marketlab-{backend,frontend}:dev
scripts/run-local.sh up                       # podman pod, arbitrary UID, read-only rootfs → http://127.0.0.1:8080
scripts/verify.sh --url http://127.0.0.1:8080
scripts/run-local.sh down
```

## OpenShift deployment

```bash
TAG=0.1.0 REGISTRY=registry.lab:5000/marketlab scripts/build-images.sh --push

BACKEND_IMAGE=registry.lab:5000/marketlab/marketlab-backend:0.1.0 \
FRONTEND_IMAGE=registry.lab:5000/marketlab/marketlab-frontend:0.1.0 \
scripts/install.sh -n marketlab --create-namespace [--with-postgres]

scripts/verify.sh -n marketlab          # add -k for a self-signed ingress certificate
scripts/uninstall.sh -n marketlab [--delete-data]
```

Nothing in the manifests names a cluster, hostname, namespace or registry. Plain Kubernetes: add `-o local`.
`--with-postgres` adds an in-namespace PostgreSQL (PVC, random-password Secret created at install time).

## Air-gapped deployment

Build online, carry the images in (`scripts/build-images.sh --save dist/images`), push them to the lab
registry, and install with `BACKEND_IMAGE`, `FRONTEND_IMAGE` (and `POSTGRES_IMAGE`). The backend can also be
rebuilt offline from a wheelhouse. Full procedure: [`docs/OPERATIONS.md#air-gapped-deployment`](docs/OPERATIONS.md#air-gapped-deployment).
The running app makes no internet calls.

## Configuration

`MARKETLAB_*` environment variables; see [`.env.example`](.env.example) and the reference table in the
operations guide. Invalid values stop the backend at startup with a clear message.

## Testing

```bash
scripts/test-all.sh           # backend pytest, frontend typecheck + vitest + build, manifest tests, script syntax
MARKETLAB_TEST_DATABASE_URL=postgresql://user:pw@127.0.0.1:5432/db backend/.venv/bin/pytest backend/tests/test_persistence.py
```

## Trust model and security

- **No authentication**: a deliberate local-demo decision. Run MarketLab only on an isolated, trusted network.
  Do not expose the Route to untrusted users without an authenticating proxy in front of it.
- Containers run non-root under any UID: all capabilities dropped, no privilege escalation, read-only root
  (frontend/backend), `RuntimeDefault` seccomp, no service-account token, no RBAC, no host access.
- NetworkPolicies: only the frontend reaches the backend; only the backend reaches PostgreSQL.
- Bounded inputs everywhere. The TCP lab can only target this process's own loopback endpoints.

## Troubleshooting

`scripts/verify.sh` names the failing hop; see [`docs/OPERATIONS.md#troubleshooting`](docs/OPERATIONS.md#troubleshooting).

## Known limitations

- Live simulation state is in memory, single process, single replica; it resets on restart. Persistent mode
  archives history and configurations only.
- Simplified market model: no auctions, market impact beyond book depth, financing, clearing or margin calls.
  Futures terms are illustrative.
- TCP lab: loopback within one process; no packet-level observation; HTTP server timestamps are application-level.
- Validated on podman and on a kind cluster enforcing the restricted Pod Security Standard. **Not yet run on a
  real OpenShift cluster.**
