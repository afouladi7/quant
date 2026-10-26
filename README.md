# MarketLab

An interactive laboratory for understanding how financial markets work, how traders manage risk, and how
software networking affects performance. **Every trade and price in the simulator is hypothetical.** No real
orders, funds, accounts or market data are involved.

| Module | What you can do |
|---|---|
| **Market Maker Simulator** | Watch a market maker quote MARKETLAB-100, trade against customers (yours and synthetic ones) through a real price-time-priority matching engine, and follow inventory, cash, realized/unrealized P&L and fees. Inventory skews the quotes. Guided presets: *Spread Capture*, *Inventory Risk*. |
| **FX Routing & Hedging** | Route GBP/USD, EUR/USD and USD/JPY orders to three independent books (A, B, C) or let the smart router split them by price, depth, fees and latency. Six reproducible scenarios. Then hedge a fund's GBP exposure with an offset FX trade or an illustrative GBP future, and compare risk scenarios before and after. |
| **TCP Performance Lab** | Run real benchmarks against the backend itself: complete vs. 499+1 split messages, cold vs. pre-established connections, useful early work, TCP_NODELAY. Distributions, percentiles, phase breakdowns and CSV export. |

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
