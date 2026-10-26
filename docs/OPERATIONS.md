# MarketLab: Architecture & Operations Guide

## Components

| Component | Image | Port | Role |
|---|---|---|---|
| `marketlab-frontend` | `ubi9/nginx-124` + built SPA (≈340 MB) | 8080 | Serves the React app; reverse-proxies `/api/*` and `/healthz/*` to the backend (WebSocket upgrade on `/api/v1/stream`). Own liveness at `/nginx-health`. |
| `marketlab-backend` | `ubi9/python-312-minimal` + venv (≈300 MB) | 8000 (HTTP), 9500 (TCP-lab listener, loopback only) | FastAPI app, one uvicorn worker. Authoritative for all simulation state. |
| `marketlab-postgres` *(optional)* | `quay.io/sclorg/postgresql-16-c9s` | 5432 | Archive for events, trades, benchmark results and configurations (persistent mode). |

```
                    Browser
                       │ HTTPS (Route, edge TLS)            ── only the frontend is exposed
                       ▼
     ┌──────────── frontend pod (nginx) ───────────┐
     │  /            static SPA                     │
     │  /api/*       → marketlab-backend:8000       │  NetworkPolicy: backend accepts
     │  /api/v1/stream (WebSocket, 1 h timeout)     │  traffic only from frontend pods
     └──────────────────────┬──────────────────────┘
                            ▼
     ┌──────────── backend pod (uvicorn ×1) ────────────────────────────────────┐
     │  simulation orchestrator ─ tick ─► market maker │ FX books A/B/C │ portfolio │
     │  event bus ─► bounded history ─► WebSocket clients                        │
     │            └► PostgresSink (background writer thread) ───────────────┐    │
     │  TCP lab: client ⇄ 127.0.0.1:9500 (raw) and 127.0.0.1:8000 (HTTP)    │    │
     └───────────────────────────────────────────────────────────────────────┼───┘
                                                                              ▼
                                      marketlab-postgres:5432 (optional; backend-only NetworkPolicy)
```

### Data flow

```
REST command:  browser → Route → nginx → backend → validate → mutate in-memory state → emit Event(s) → JSON response
Live updates:  Event bus → per-client bounded queue → WebSocket /api/v1/stream → browser (refetches snapshots on events)
Reconnect:     WS "hello" (status + last seq) → GET /api/v1/events backfill
Persistence:   Event bus → PostgresSink queue (bounded) → writer thread → events / trades / benchmark_runs / configs
```

Live simulation state (books, orders, ledgers, portfolio) is always **in memory**
and resets on restart; that is deliberate for a single-process educational
simulator. Persistent mode archives **history** and **configurations**, and
restores the saved configurations at startup.

## OpenShift resource layout

```
deploy/kustomize/
├── base/                         namespace-agnostic, no registry
│   ├── backend.yaml              ServiceAccount, ConfigMap, Service, Deployment (replicas 1, Recreate)
│   ├── frontend.yaml             ServiceAccount, ConfigMap, Service, Deployment
│   └── networkpolicy.yaml        backend ingress only from frontend pods
├── components/postgres/          optional persistent mode
│   ├── postgres.yaml             PVC (2 Gi, default StorageClass), Service, Deployment (Recreate), NetworkPolicy
│   └── backend-db-patch.yaml     backend env from Secret marketlab-db; ConfigMap → persistence_mode=postgres
└── overlays/
    ├── openshift/                + Route (edge TLS, redirect, 1 h timeout), router NetworkPolicy, placeholder images
    └── local/                    localhost/*:dev images, DEBUG logging, no Route
```

All resources carry `app.kubernetes.io/part-of=marketlab`.

### Restricted-v2 compatibility

- No `runAsUser`: OpenShift assigns a UID from the namespace range. Images own their files by group 0
  with group permissions equal to user permissions.
- `runAsNonRoot`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, `seccompProfile: RuntimeDefault`.
- Frontend and backend: `readOnlyRootFilesystem: true`, writable `emptyDir` at `/tmp` only.
  PostgreSQL writes to its PVC (its image also needs a writable root, so it is the one exception).
- `automountServiceAccountToken: false`; no Roles or RoleBindings; no host access.

**Validated so far** (see `IMPLEMENTATION_STATUS.md`): podman with an arbitrary UID, read-only root and dropped
capabilities; a kind (Kubernetes 1.34) cluster with the namespace enforcing the **restricted** Pod Security
Standard, the upstream counterpart of restricted-v2. **Not yet validated on a real OpenShift cluster** (Route,
SCC admission, arbitrary UID assignment by OpenShift).

## Configuration reference

Backend (`marketlab-backend-config` ConfigMap or environment):

| Variable | Default | Range / values | Meaning |
|---|---|---|---|
| `MARKETLAB_ENVIRONMENT` | `local` | ≤ 32 chars | Label in `/api/v1/info` |
| `MARKETLAB_LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR | |
| `MARKETLAB_LOG_JSON` | `true` (image) | bool | One JSON object per log line on stdout |
| `MARKETLAB_PERSISTENCE_MODE` | `memory` | memory, postgres | |
| `MARKETLAB_DATABASE_URL` | — | | Full PostgreSQL URL (alternative to the parts below) |
| `MARKETLAB_DB_HOST` / `_DB_PORT` / `_DB_NAME` / `_DB_USER` / `_DB_PASSWORD` | — / 5432 | | Connection parts (the component fills these from the Secret) |
| `MARKETLAB_DB_AUTO_MIGRATE` | `true` | bool | Apply SQL migrations at startup |
| `MARKETLAB_DB_CONNECT_RETRIES` | `30` | 1–300 | Startup attempts, 2 s apart |
| `MARKETLAB_SIM_SEED` | `42` | 0 – 2³²−1 | |
| `MARKETLAB_SIM_TICK_INTERVAL_MS` | `250` | 20–5000 | Wall ms per tick at 1× (1 tick = 1 simulated second) |
| `MARKETLAB_SIM_DEFAULT_SPEED` | `1` | 0.1–10 | |
| `MARKETLAB_SIM_AUTOSTART` | `false` | bool | |
| `MARKETLAB_STATUS_BROADCAST_INTERVAL_MS` | `1000` | 100–60000 | |
| `MARKETLAB_EVENT_HISTORY_LIMIT` | `5000` | 100–100000 | In-memory event ring buffer |
| `MARKETLAB_WS_QUEUE_SIZE` | `500` | 10–10000 | Per-client buffer (oldest dropped) |
| `MARKETLAB_WS_MAX_CLIENTS` | `20` | 1–200 | |
| `MARKETLAB_TCPLAB_HOST` | `127.0.0.1` | 127.0.0.1, ::1, localhost | Benchmark target host. Loopback only, enforced. |
| `MARKETLAB_TCPLAB_PORT` | `9500` | 0–65535 | Raw-TCP listener (0 = any free port) |
| `MARKETLAB_HTTP_PORT` | `8000` | | Port this backend listens on (HTTP benchmark target) |

Frontend (`marketlab-frontend-config`): `MARKETLAB_BACKEND_HOSTPORT` (default `marketlab-backend:8000`),
`NGINX_PORT` (8080).

Changing values on a cluster: `oc edit configmap marketlab-backend-config` then
`oc rollout restart deploy/marketlab-backend`. Settings edited **in the UI** (market-maker parameters, book
configurations, routing weights, futures contract terms, hedge rule) are saved to PostgreSQL in persistent mode
and restored at the next start.

Bounds that protect a long-running demo: event history, per-client WebSocket queues, orders per venue (terminal
orders pruned beyond 5,000), trades per venue (2,000), FX parent orders (1,000), hedge proposals (200), benchmark
runs (30), the persistence queue (10,000, oldest dropped and counted), and the TCP-lab limits.

## API

OpenAPI schema: `/api/v1/openapi.json` (the CDN-based Swagger UI is disabled for air-gap). Main groups:

| Prefix | Purpose |
|---|---|
| `/healthz/live`, `/healthz/ready`, `/metrics` | probes; Prometheus text metrics |
| `/api/v1/info`, `/simulation/*`, `/events`, `/stream` | system, clock (start/pause/reset/speed/advance), event history, WebSocket |
| `/api/v1/mm/*` | market maker: state, config, quote, book, ledger, trades, orders (POST with `Idempotency-Key`, GET, DELETE), fair-value, reset, presets |
| `/api/v1/fx/*` | FX: state, books & config, routing weights, route preview, parent orders, rates, scenarios 1–6, reset |
| `/api/v1/portfolio*`, `/api/v1/hedges/*` | portfolio, exposure, risk, futures (spec, basis shock, advance days), hedge proposals & execution, hedge rule, guided GBP scenario |
| `/api/v1/tcp/*` | echo target, benchmark runs, suites (Preset 5), CSV export, cancel |
| `/api/v1/history/*` | archived events, trades, benchmarks, instances (persistent mode) |

Errors always use `{"error": {"code", "message", "details"}}`. Decimals are JSON strings.

## Deployment, upgrade and uninstall

```bash
BACKEND_IMAGE=<registry>/marketlab-backend:<tag> FRONTEND_IMAGE=<registry>/marketlab-frontend:<tag> \
  scripts/install.sh -n <namespace> [--create-namespace] [--with-postgres] [-o openshift|local] [--dry-run]
```

The script checks tools, namespace name, login and permissions (including PVCs and Secrets with
`--with-postgres`) and the Route API on OpenShift. It renders the overlay with your images, refuses `CHANGE-ME`
placeholders, runs a server-side dry run, creates the `marketlab-db` Secret with a random password if missing
(it is never committed), applies, waits for each rollout, and prints the URL. On failure it prints pod status,
events, logs and hints. Image references accept tags or `@sha256:` digests; `POSTGRES_IMAGE` overrides the
database image.

**Upgrade:** rerun install with new image tags. The backend uses `Recreate`: a few seconds of downtime, and live
simulation state resets (archived history and saved configurations remain in persistent mode).

**Uninstall:** `scripts/uninstall.sh -n <ns> [--delete-data] [--delete-namespace]`. The PVC and DB Secret are
kept unless `--delete-data` is given.

**Verify:** `scripts/verify.sh -n <ns> [-k]` checks:

- readiness, in-pod health, and frontend→backend connectivity;
- the SPA, deep links, info, the simulation lifecycle, the error envelope and the WebSocket upgrade;
- the market-maker workflow (fill, inventory, exact cash, idempotent retry, re-quote);
- an FX split route, a futures hedge, a TCP-lab benchmark, and the persistence connection.

It changes simulation state and resets the modules afterwards. On the local overlay, start
`kubectl port-forward svc/marketlab-frontend 8080:8080` and pass `--url http://localhost:8080`.

### Testing on a local Kubernetes cluster (kind + rootless podman)

```bash
KIND_EXPERIMENTAL_PROVIDER=podman systemd-run --scope --user kind create cluster --name marketlab
podman save -m -o imgs.tar localhost/marketlab-backend:dev localhost/marketlab-frontend:dev quay.io/sclorg/postgresql-16-c9s:latest
KIND_EXPERIMENTAL_PROVIDER=podman kind load image-archive imgs.tar --name marketlab
kubectl create ns marketlab-test
kubectl label ns marketlab-test pod-security.kubernetes.io/enforce=restricted   # approximate restricted-v2
CLI=kubectl scripts/install.sh -n marketlab-test -o local --with-postgres
kubectl -n marketlab-test port-forward svc/marketlab-frontend 8080:8080 &
CLI=kubectl scripts/verify.sh -n marketlab-test --url http://127.0.0.1:8080
```

## Air-gapped deployment

### Option A: build online, carry images in

```bash
TAG=0.1.0 scripts/build-images.sh --save dist/images          # OCI archives + SHA256SUMS
podman pull quay.io/sclorg/postgresql-16-c9s:latest && podman save -o dist/images/postgres.tar quay.io/sclorg/postgresql-16-c9s:latest   # if using --with-postgres
# inside the lab
cd dist/images && sha256sum -c SHA256SUMS
podman load -i marketlab-backend-0.1.0.tar; podman load -i marketlab-frontend-0.1.0.tar; podman load -i postgres.tar
podman tag  localhost/marketlab-backend:0.1.0  registry.lab:5000/marketlab/marketlab-backend:0.1.0   # and the others
podman push registry.lab:5000/marketlab/marketlab-backend:0.1.0                                      # and the others
POSTGRES_IMAGE=registry.lab:5000/marketlab/postgresql-16-c9s:latest BACKEND_IMAGE=... FRONTEND_IMAGE=... \
  scripts/install.sh -n marketlab --with-postgres
```

Pull secrets: the pods use their own service accounts, so link a registry secret to `marketlab-backend`,
`marketlab-frontend` and `default` (the database pod uses `default`):
`oc secrets link marketlab-backend lab-registry --for=pull`, and the same for the others.
The OpenShift internal registry works too (`image-registry.openshift-image-registry.svc:5000/<ns>/...`).

### Option B: rebuild inside the lab

```bash
scripts/prepare-offline.sh            # online: Python wheels → backend/wheels, base images → offline/base-images.tar
podman load -i offline/base-images.tar
OFFLINE=1 scripts/build-images.sh     # backend built with --network=none from the wheelhouse
```

The frontend build needs npm packages: build it online (Option A) or point at an internal npm mirror with
`NPM_CONFIG_REGISTRY=...`. `frontend/package-lock.json` pins versions and integrity hashes.
Verified: the offline backend build. Not tested: the npm-mirror path.

### Dependency inventory

| Layer | Source | Pinned in |
|---|---|---|
| Base images | registry.access.redhat.com/ubi9/{python-312, python-312-minimal, nodejs-22, nginx-124}; quay.io/sclorg/postgresql-16-c9s | Containerfile ARGs / component (pin digests for strict reproducibility) |
| Python runtime | fastapi, starlette, uvicorn, websockets, pydantic(+core, -settings), anyio, h11, click, idna, python-dotenv, typing-extensions, typing-inspection, annotated-types, annotated-doc, opentelemetry-api (FastAPI dependency; no exporter, no network), psycopg + psycopg-binary (bundled libpq) | `backend/requirements.txt` |
| Python test | pytest, pytest-asyncio, httpx, PyYAML | `backend/requirements-dev.txt` |
| JS runtime | react, react-dom, react-router-dom (charts are hand-written SVG; no chart library) | `frontend/package-lock.json` |
| JS build/test | vite, @vitejs/plugin-react, typescript, vitest, jsdom, @testing-library/*, @types/* | `frontend/package-lock.json` |

Runtime makes no internet calls: no CDN, hosted fonts, analytics or external APIs.

## Storage and backup (persistent mode)

- Data lives in PVC `marketlab-postgres` (2 Gi, cluster default StorageClass; change it in an overlay).
- Back up: `oc exec deploy/marketlab-postgres -- pg_dump -U marketlab marketlab > marketlab.sql`.
- Restore: `oc exec -i deploy/marketlab-postgres -- psql -U marketlab marketlab < marketlab.sql`.
- Growth: every event is archived. Prune with e.g. `DELETE FROM events WHERE ts < now() - interval '30 days';`.
- Migrations: `migrations/*.sql`, applied in order at startup and tracked in `schema_migrations`. Run manually
  with `python -m app.persistence.migrate` inside the backend pod.
- External database: skip the component and set `MARKETLAB_PERSISTENCE_MODE=postgres` and
  `MARKETLAB_DATABASE_URL` from your own Secret.

## Observability

- Structured JSON logs on stdout/stderr (backend and nginx access logs).
- `/healthz/ready` returns `{"status": "ok" | "degraded" | "unavailable"}`. A PostgreSQL outage is reported as
  `degraded` but does **not** fail readiness, so the in-memory app stays reachable. Queued archive writes are
  retried after the database returns (verified).
- `/metrics` (Prometheus text): events, stream clients, tick, inventory, in-memory sizes, persistence
  written/dropped/queued, and TCP-lab premature commits (always 0). The backend NetworkPolicy admits only frontend
  pods, so to scrape it add a policy allowing your monitoring namespace.

## Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| UI: "Backend disconnected — retrying" | backend pod down, or nginx cannot reach it | `oc get pods -l app.kubernetes.io/part-of=marketlab`; `oc logs deploy/marketlab-frontend` |
| `/healthz/ready` → 502 via the Route | backend not ready, or NetworkPolicy | `oc exec deploy/marketlab-frontend -- curl -s localhost:8080/healthz/ready` |
| Live stream drops every ~30 s | Route timeout annotation missing | `oc get route marketlab -o yaml \| grep timeout` |
| Backend CrashLoopBackOff, log names a `MARKETLAB_` variable | invalid configuration (fails fast) | fix the ConfigMap, `oc rollout restart` |
| Backend log "database not ready" then exit | DB unreachable after `DB_CONNECT_RETRIES` | `oc get pods`, `oc logs deploy/marketlab-postgres`, Secret `marketlab-db` keys |
| `/healthz/ready` says `"degraded"` | persistent mode, DB connection lost | `/api/v1/history/status` → `last_error` |
| Postgres pod Pending | PVC unbound (no default StorageClass) | `oc get pvc`; set `storageClassName` in an overlay |
| `ImagePullBackOff` | registry unreachable, wrong reference, missing pull secret | `oc describe pod …` |
| Pod `Forbidden` / SCC errors | policy stricter than restricted-v2 | report the exact message; manifests request no special SCC |
| HTTP benchmarks show ~40 ms gaps | server socket without TCP_NODELAY (seen with `uvicorn --reload`) | see `docs/networking-guide.md` §5 |
| A benchmark returns 409 `busy` | one run at a time | wait, or `POST /api/v1/tcp/cancel` |

## Omitted production concerns

Authentication/authorization, high availability (single backend replica), real exchange rules, market impact,
financing costs, clearing and settlement, collateral and margin management, advanced portfolio risk, institutional
controls, audit/compliance, disaster recovery and multi-region operation are intentionally out of scope.
