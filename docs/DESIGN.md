# MarketLab — Design Proposal

This document is the pre-implementation design required by spec §17. It covers
repository structure, architecture, data flow, core data models, API contracts,
dependencies, OpenShift deployment design, testing plan, and Phase 1 acceptance
criteria. It was written before implementation; all phases have since been built.
Where the implementation deviates from this design, the deviations are listed in
§10. The operations guide and the code are authoritative; `IMPLEMENTATION_STATUS.md`
records what was verified.

---

## 1. Repository structure

```
marketlab/
├── backend/                     Python 3.12 / FastAPI modular monolith
│   ├── app/
│   │   ├── main.py              App factory, lifespan (startup/shutdown)
│   │   ├── config.py            Pydantic Settings — all env-driven config
│   │   ├── logging_setup.py     JSON structured logging to stdout
│   │   ├── core/                IDs, clocks, Decimal/tick helpers, errors
│   │   ├── events/              Event model + bounded event bus
│   │   ├── simulation/          Orchestrator (clock, start/pause/reset/speed)
│   │   ├── persistence/         Repository interfaces + in-memory impl
│   │   ├── marketmaker/         (Phase 2) quoting, order book, matching, ledger
│   │   ├── fx/                  (Phase 3) pairs, books A/B/C, router
│   │   ├── portfolio/           (Phase 4) exposure, hedging, futures
│   │   ├── tcplab/              (Phase 5) raw TCP + HTTP benchmark harness
│   │   └── api/v1/              REST + WebSocket routers
│   ├── tests/                   pytest unit + integration tests
│   ├── pyproject.toml           Project metadata, tool config
│   ├── requirements.txt         Pinned runtime deps
│   ├── requirements-dev.txt     Pinned test deps
│   └── Containerfile
├── frontend/                    React 18 + TypeScript + Vite
│   ├── src/
│   │   ├── api/                 Typed REST client + WebSocket stream hook
│   │   ├── state/               View-mode (Simple/Technical) context
│   │   ├── components/          Design-system components, control bar, etc.
│   │   ├── pages/               Home, MarketMaker, FX, TCP Lab
│   │   └── test/                Vitest + Testing Library
│   ├── nginx/                   nginx.conf template + entrypoint
│   └── Containerfile
├── deploy/kustomize/
│   ├── base/                    Deployments, Services, ConfigMaps, SAs, NetworkPolicy
│   └── overlays/
│       ├── local/               Plain Kubernetes (kind/minikube/podman kube)
│       └── openshift/           Adds Route, OpenShift-specific tweaks
├── scripts/                     install.sh, uninstall.sh, verify.sh, dev helpers
├── tests/deploy/                Manifest validation tests (render + assert)
├── docs/                        Design, architecture/ops, finance & networking guides
├── .env.example
├── README.md
└── IMPLEMENTATION_STATUS.md
```

## 2. Architecture

A **modular monolith**: one backend process owns all authoritative state; one
static frontend served by nginx that also reverse-proxies `/api` to the backend.
This gives a single browser origin (no CORS), a single Route, and WebSockets on
the same host.

```
                    Browser (React SPA)
                         │  HTTPS (OpenShift Route, edge TLS)
                         ▼
        ┌────────────────────────────────────┐
        │ frontend pod (nginx, UID-agnostic) │
        │  /         → static SPA assets     │
        │  /api/*    → proxy to backend      │  (WebSocket upgrade passthrough)
        └───────────────┬────────────────────┘
                        │ ClusterIP Service marketlab-backend:8000
                        ▼
        ┌────────────────────────────────────────────────────────┐
        │ backend pod (uvicorn, single worker, replicas: 1)      │
        │                                                        │
        │  api/v1 (REST + WS) ──► Simulation Orchestrator ──┐    │
        │       │                   (tick loop, seed, speed) │    │
        │       │                                            ▼    │
        │       │     ┌──────────── domain modules ──────────────┐│
        │       │     │ marketdata │ marketmaker │ fx │ portfolio ││
        │       │     │            │ (book+match │(A/B/C│(exposure ││
        │       │     │            │  +ledger)   │router)│+hedges) ││
        │       │     └────────────────────┬─────────────────────┘│
        │       │                          ▼                       │
        │       └──────────────► Event Bus (bounded ring buffer,   │
        │                         per-subscriber bounded queues)   │
        │                                  │                       │
        │  Repository interface ◄──────────┘                       │
        │   ├─ InMemoryRepository  (ephemeral, default)            │
        │   └─ PostgresRepository  (Phase 2+, optional)            │
        │                                                        │
        │  tcplab: in-process benchmark client ──► own HTTP port │
        │          and own raw-TCP framing listener (:9500)      │
        └────────────────────────────────────────────────────────┘
```

Key decisions:

| Decision | Rationale |
|---|---|
| Single uvicorn worker, `replicas: 1`, `strategy: Recreate` | In-memory state must live in exactly one process. Scaling out would split order books. Documented as a deliberate constraint. |
| nginx reverse proxy for `/api` | One origin, one Route, WebSockets work through the default OpenShift router; backend never exposed directly. |
| WebSocket (not SSE) for live events | Bidirectional (client can send subscription filters later), well supported by HAProxy router with a long timeout annotation. |
| Decimal for prices/money, integer ticks inside books | Exact arithmetic; tick-integer comparisons make price-time priority unambiguous. |
| Deterministic seeded RNG per module | Reproducible scenarios and tests; seed exposed in config + reset API. |
| No auth in MVP | Explicit local-demo decision (spec §2.2). Documented trust assumption: isolated trusted network only. |

## 3. Data flow

**Command path (REST):** Browser → nginx → `POST /api/v1/...` → Pydantic
validation → domain module mutates state under a single `asyncio.Lock` per
module → emits `Event`s → response returns authoritative result.

**Live path (WebSocket):** Event Bus fan-out → each connected client has a
bounded `asyncio.Queue` (drop-oldest on overflow, with a `dropped` counter sent
to the client) → `/api/v1/stream` → frontend reducer. Periodic `status`
snapshots (tick, state, speed) let a reconnecting client resynchronise without
replaying history; history is fetched via `GET /api/v1/events`.

**Simulation loop:** The orchestrator owns one asyncio task. Each tick
(`base_tick_interval / speed`) it advances simulated time and calls registered
`Tickable` modules (market data, synthetic order flow) in a fixed order. Pause
cancels nothing — it simply stops advancing. Reset re-seeds RNGs and asks every
module to restore its initial state, then emits `simulation.reset`.

**Order trace (Phase 2–4):** a single `correlation_id` is minted when an order
is received and propagated through routing → child orders → fills → inventory →
P&L → hedge proposal, so the timeline can filter by it.

## 4. Core data models

All IDs are server-generated (`<prefix>-<monotonic counter>-<short random>`,
e.g. `ORD-000042-7f3a`). Timestamps are UTC wall clock (`datetime`) plus a
monotonic nanosecond reading for ordering/latency. Money is `Decimal` serialised
as strings in JSON to avoid float loss.

```python
# Shared
class Event:            id, seq:int, ts:datetime, mono_ns:int, type:str, module:str,
                        entity_id:str|None, correlation_id:str|None,
                        message:str, data:dict
class SimulationStatus: state: "stopped"|"running"|"paused", tick:int,
                        sim_time:datetime, speed:Decimal, seed:int

# Phase 2 — market maker
class Instrument:       symbol, tick_size:Decimal, lot_size:int
class MMConfig:         fair_value, spread, quote_size, max_inventory,
                        inventory_sensitivity, volatility, arrival_rate,
                        buy_probability, fee_per_share, tick_size, seed,
                        market_order_remainder_policy: "cancel"|"rest_as_limit"
class Quote:            id, bid:Decimal, ask:Decimal, bid_size, ask_size,
                        reference_price, skew, ts
class Order:            id, client_order_id(idempotency key), side, type,
                        quantity, limit_price|None, filled_qty, remaining_qty,
                        status: open|partially_filled|filled|canceled|rejected,
                        reject_reason|None, book:str, parent_id|None,
                        correlation_id, created_ts, updated_ts
class Trade:            id, order_id, counterparty_order_id, book, side,
                        price, quantity, fee, aggressor, ts
class Ledger:           cash, inventory, avg_cost, realized_pnl,
                        unrealized_pnl, fees, gross_spread_captured
                        (avg-cost method; formulas in docs/finance-guide.md)

# Phase 3 — FX
class CurrencyPair:     base:"GBP", quote:"USD", tick_size, symbol "GBP/USD"
class BookConfig:       name:A|B|C, spread, depth_levels, qty_per_level,
                        fee_bps, latency_ms, seed
class ParentOrder:      Order + routing_mode: A|B|C|smart, children:[Order],
                        vwap, total_fees, unfilled_qty, routing_plan
class RoutingPlan:      candidates:[{book, price, qty, fee, latency, score}],
                        objective_weights, chosen:[(book, qty)]

# Phase 4 — portfolio / hedging
class CashBalance:      currency, amount
class Position:         instrument_kind: spot|future, instrument, quantity,
                        avg_price
class FuturesContract:  symbol, underlying_pair, contract_size (base ccy),
                        quote_convention, expiry, initial_margin,
                        maintenance_margin  (illustrative, labelled as such)
class Exposure:         currency, spot_exposure, derivative_exposure,
                        net_exposure, valuation_ccy, sensitivity_per_1pct
class HedgeProposal:    id, instrument, direction, quantity, contracts|None,
                        projected_residual, assumptions:[str], status

# Phase 5 — TCP lab
class BenchmarkConfig:  mode: complete|split|persistent|early_work,
                        transport: raw_tcp|http, payload_size, trials, warmup,
                        split_delay_ms, reuse_connection, server_processing_ms,
                        concurrency, tcp_nodelay, timeout_ms
class TrialResult:      trial, connect_ns, first_write_ns, last_write_ns,
                        server_first_rx_ns, server_complete_ns,
                        server_processing_ns, ttfb_ns, total_ns, error|None,
                        nodelay_applied:bool|None
class BenchmarkSummary: n, min, median, mean, stdev, p90?, p95?, p99?,
                        error_rate, timeout_rate (pXX only when n is adequate)
```

## 5. API contracts (all under `/api/v1`)

Errors use one shape: `{"error": {"code": str, "message": str, "details": any}}`.

| Method & path | Purpose | Phase |
|---|---|---|
| `GET /healthz/live` (root, unversioned) | Liveness — process responsive | 1 ✅ |
| `GET /healthz/ready` | Readiness — config valid, sim loop alive, repository OK | 1 ✅ |
| `GET /api/v1/info` | Version, mode (ephemeral/persistent), simulation-mode banner | 1 ✅ |
| `GET /api/v1/simulation` | `SimulationStatus` | 1 ✅ |
| `POST /api/v1/simulation/start` · `/pause` · `/reset` | Control loop; reset accepts optional `{seed}` | 1 ✅ |
| `PUT /api/v1/simulation/speed` | `{speed}` bounded 0.1–10 | 1 ✅ |
| `GET /api/v1/events?limit&type&correlation_id&after_seq` | Bounded history | 1 ✅ |
| `WS /api/v1/stream` | `{"kind":"event"|"status"|"hello"|"dropped", ...}` | 1 ✅ |
| `GET/PUT /api/v1/mm/config` | Market-maker configuration | 2 |
| `GET /api/v1/mm/quote` · `/mm/book` · `/mm/ledger` · `/mm/trades` | Snapshots | 2 |
| `POST /api/v1/mm/orders` (header `Idempotency-Key`) | Submit order | 2 |
| `DELETE /api/v1/mm/orders/{id}` · `GET /mm/orders[/{id}]` | Cancel / status | 2 |
| `POST /api/v1/mm/presets/{name}` | Load deterministic preset | 2 |
| `GET/PUT /api/v1/fx/books/{A|B|C}/config` · `GET /fx/books/{id}` | Per-book config/snapshot | 3 |
| `POST /api/v1/fx/orders` (routing_mode, Idempotency-Key) · `GET /fx/orders/{id}` | Routed parent order incl. plan | 3 |
| `POST /api/v1/fx/scenarios/{n}/reset` | FX scenarios 1–6 | 3 |
| `GET /api/v1/portfolio` · `/portfolio/exposure` | Balances, positions, exposure | 4 |
| `POST /api/v1/portfolio/rates` | Shock/set FX rate (hypothetical) | 4 |
| `POST /api/v1/hedges/proposals` · `POST /hedges/proposals/{id}/execute` | Rule-based + manual hedging | 4 |
| `POST /api/v1/tcp/benchmarks` · `GET /tcp/benchmarks/{id}` · `.../csv` | Run / fetch / export | 5 |
| `POST /api/v1/tcp/echo` | HTTP target endpoint (streams body, completes only on full body) | 5 |

The OpenAPI schema is generated by FastAPI at `/api/v1/openapi.json` (docs UI
at `/api/v1/docs`, served from the image — no CDN; see §6).

Idempotency (Phase 2+): state-changing order endpoints require an
`Idempotency-Key`; the repository stores `key → response` (bounded LRU) and a
retry with the same key + same body returns the original response; same key +
different body → `409`.

## 6. Dependencies (and why)

**Backend runtime** (pinned in `requirements.txt`):
- `fastapi` — typed REST/WS, auto OpenAPI.
- `uvicorn` (with `websockets`, no `[standard]` extras to stay lean) — ASGI server.
- `pydantic`, `pydantic-settings` — validation and env-driven config.

FastAPI's Swagger UI loads JS from a CDN by default; we disable the default
docs route and only expose the OpenAPI JSON + ReDoc-less schema so nothing
calls out at runtime. (A self-hosted docs UI can be added later.)

Phase 2+ candidates, added only when needed: `sqlalchemy` + `psycopg` +
`alembic` (persistent mode). No numpy needed: stats are done with `statistics`.

**Backend dev:** `pytest`, `pytest-asyncio`, `httpx` (TestClient), `pyyaml`
(manifest tests).

**Frontend runtime:** `react`, `react-dom`, `react-router-dom`. Phase 5 adds
`recharts` for latency distributions (pure SVG, bundled — no CDN).
Fonts: system font stack only (no hosted fonts).

**Frontend dev:** `vite`, `@vitejs/plugin-react`, `typescript`, `vitest`,
`jsdom`, `@testing-library/react`, `@testing-library/jest-dom`,
`@testing-library/user-event`. Lockfile `package-lock.json` committed.

**Images** (Red Hat UBI 9, OpenShift-friendly, arbitrary-UID compatible):
- build/run backend: `registry.access.redhat.com/ubi9/python-312`
- build frontend: `registry.access.redhat.com/ubi9/nodejs-22`
- run frontend: `registry.access.redhat.com/ubi9/nginx-124`

## 7. OpenShift deployment design

- **No namespace in manifests.** `install.sh -n <ns>` applies into any namespace.
- **Images overridable** via `install.sh` env (`BACKEND_IMAGE`, `FRONTEND_IMAGE`) —
  the script generates a throwaway kustomization with an `images:` override.
- **Base:** backend Deployment/Service/ConfigMap/ServiceAccount, frontend
  Deployment/Service/ConfigMap/ServiceAccount, NetworkPolicy (backend accepts
  ingress only from frontend pods in the same namespace).
- **openshift overlay:** Route (edge TLS, HTTP→HTTPS redirect, 1h timeout
  annotation for WebSockets) to the frontend Service.
- **local overlay:** no Route; reach via `kubectl port-forward`.
- **Security context (restricted-v2 compatible):** `runAsNonRoot: true`, no
  `runAsUser` (OpenShift assigns one), `allowPrivilegeEscalation: false`,
  `capabilities: drop [ALL]`, `seccompProfile: RuntimeDefault`,
  `readOnlyRootFilesystem: true` with `emptyDir` at `/tmp`.
  `automountServiceAccountToken: false` — the app needs no API access; no RBAC.
- **Probes:** startup + readiness + liveness on both pods.
- **Resources:** requests/limits on every container.
- **Persistent mode (Phase 2+):** optional Kustomize component adding a
  PostgreSQL Deployment/Service/PVC + Secret reference. Not in Phase 1 because
  the backend does not yet implement the Postgres repository.

## 8. Testing plan

| Layer | Tool | Phase 1 scope |
|---|---|---|
| Backend unit | pytest | config validation, ID generation, event bus bounds & drop-oldest, orchestrator state machine |
| Backend API integration | pytest + FastAPI TestClient | health/ready, info, simulation start/pause/reset/speed, events query, WebSocket hello + event delivery, error envelope, validation 422 |
| Frontend | Vitest + Testing Library | app shell renders, simulation-mode banner, control bar calls API, disconnected state, Simple/Technical toggle |
| Manifests | pytest over `kustomize build` output | every Deployment has probes, limits, restricted securityContext, no runAsUser/host*/privileged, selectors match, no namespace hardcoded, Route only in openshift overlay |
| Containers | podman build + run | both images build; containers run as an arbitrary UID with read-only rootfs; health via nginx proxy |
| OpenShift | `scripts/verify.sh` | **Requires a cluster — not run in Phase 1** (no `oc` in dev env) |

Later phases add deterministic accounting/matching/routing/hedge tests
(spec §12) and TCP framing tests.

## 9. Phase 1 acceptance criteria

1. `pytest` passes for the backend.
2. `npm run build` and `npm test` pass for the frontend.
3. Both container images build with podman (no privileges) and start.
4. Backend container runs under an arbitrary non-root UID with a read-only root FS.
5. Health endpoints respond; readiness reflects the simulation loop.
6. Frontend container proxies `/api` (including the WebSocket) to the backend.
7. `kustomize build` renders both overlays; manifest tests pass.
8. No cluster URL, hostname, namespace, or credential is hardcoded.
9. `IMPLEMENTATION_STATUS.md` records exactly what was run and what was not.

## 10. Deviations from this design (as implemented)

- Persistence: PostgreSQL **archives** history (events, trades, benchmark runs) and saves/restores
  configurations; live simulation state remains in memory. Migrations are plain SQL files with a small runner
  (no Alembic/SQLAlchemy); the driver is psycopg 3. The archive is written by a background thread through a
  bounded queue and is not a readiness gate.
- Charts are hand-written SVG components instead of Recharts (fewer dependencies, full control over the
  validated colour palette, accessibility and hover behaviour).
- The market-maker ledger uses FIFO lots rather than average cost, so realized P&L is exact in Decimal arithmetic.
- The TCP-lab raw message is 500 bytes *including* a 16-byte header; over HTTP the 500 bytes are the body.
- Backend runtime image uses `ubi9/python-312-minimal` (≈300 MB vs ≈1.2 GB).
- Extra endpoints: `/metrics`, `/api/v1/history/*`, `/api/v1/simulation/advance`, `/api/v1/fx/route-preview`,
  guided-scenario and preset step endpoints.
