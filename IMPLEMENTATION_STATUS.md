# MarketLab: Implementation Status

_Last updated: 2026-10-25_

## Current phase

**All seven phases are implemented and tested locally.** One acceptance item is still open:
**deployment to a real OpenShift cluster has not been performed** (none was available). Instead the manifests
and scripts were run on a real Kubernetes cluster (kind, Kubernetes 1.34) whose namespace enforced the
**restricted** Pod Security Standard, plus podman runs with an arbitrary UID. See "Not verified".

## What exists

| Area | Implemented | Verified by |
|---|---|---|
| **Foundation** | Config (env, validated, fail-fast), JSON logs, health/readiness, `/metrics`, seeded simulation clock (start/pause/resume/reset/speed/step), event bus with bounded history and per-client WebSocket queues, error envelope, OpenAPI | unit + API tests |
| **Market maker** | Decimal/tick money; price-time-priority order book; venue with validation, market/limit, IOC/FOK/GTC, partial fills, resting orders, cancel, expiry, self-trade prevention, fees; FIFO ledger (cash, inventory, avg cost, realized/unrealized/net P&L, fees, gross spread); quote engine with linear inventory skew and inventory limits; Poisson synthetic flow; idempotent order entry; presets *Spread Capture* and *Inventory Risk*; Reset Demo | 45 tests incl. exact preset numbers, cash/inventory reconciliation against every fill over 300 random ticks, same-seed reproducibility |
| **FX books & routing** | GBP/USD, EUR/USD, USD/JPY synthetic rates; books A/B/C, each an independent venue per pair with its own liquidity, fees and latency; pure smart router (effective price = price ± fees ± latency penalty) with candidate table and plain-English explanation; parent/child orders with VWAP, fees and unfilled quantity; resting limit children that fill later; scenarios 1–6 with reset; idempotent submission | router unit tests; all six scenarios assert their documented outcomes; 40 randomized orders reconcile (filled = Σ children = Σ trades, fees, VWAP, limit never violated); book independence |
| **Hedging** | Multi-currency balances; exposure (spot + futures-equivalent, pre/post hedge); USD valuation; P&L breakdown; illustrative GBP future (basis convergence, spread, fees, margin reporting, partial fills, expiry settlement); offset-FX and futures hedges, manual and rule-based, with projected impact, assumptions, risk limit and approval; auto-hedge rule; risk scenarios (±1%, VaR at normal/doubled volatility, partial hedge, basis, expiry); guided GBP scenario | P&L components sum exactly to total P&L; rounding residual (16 contracts → 30,000 GBP); partial fill; basis shock (−500 USD); expiry settlement; auto-hedge threshold |
| **TCP lab** | Raw-TCP framed protocol and in-process server (commits only on a complete message); streaming HTTP echo endpoint; benchmark client (complete/split/early-work, cold/reused, TCP_NODELAY read back, concurrency, timeouts, warm-up); statistics (min/median/mean/stdev/p25/p75 and p90/p95/p99 only with adequate n); Preset 5 suite; CSV export; notes on limitations; loopback-only target | framing tests incl. byte-at-a-time delivery; a test proving the server does not respond before the last byte; early-work overlap; HTTP split over a real uvicorn server; service run/CSV |
| **Persistence** | Optional PostgreSQL archive: SQL migrations + runner, background writer (bounded queue, retries after outage), events/trades/benchmarks/configs, config restore on start, `/api/v1/history/*`; DB outage → `degraded`, not unready | 3 tests against real PostgreSQL 16 (restart keeps history, configs restored, benchmarks archived); manual outage test: 0 records lost after reconnect |
| **Frontend** | React 19/TS/Vite. Home dashboard; control bar; Simple/Technical views (also `?view=`); connection state with reconnect + backfill; Market Maker, FX routing, Hedging, TCP Lab pages; event-driven flow and routing diagrams; order traces by correlation ID; SVG charts with a validated, CVD-safe palette; light/dark; responsive to phone width; no external fonts or CDNs | 20 Vitest tests (order entry + Idempotency-Key, cancel, presets, book rendering, validation errors, unreachable backend, FX scenario + routing diagram, route preview, hedge propose/execute, benchmark run/results, 409 busy, disconnect/reconnect); headless-Chromium screenshots of every page at 1366–1400 px and 390 px |
| **Deployment** | UBI images (backend ≈300 MB on python-312-minimal, frontend ≈340 MB); Kustomize base + `local`/`openshift` overlays + `components/postgres`; restricted security contexts, probes, limits, NetworkPolicies, Route; `install.sh` (`--with-postgres`, image overrides incl. digests, random DB secret), `uninstall.sh` (`--delete-data`), `verify.sh` (23 end-to-end checks), `build-images.sh`, `prepare-offline.sh`, `run-local.sh`, `test-all.sh` | 20 manifest tests; kind deployment (see below) |
| **Docs** | README, DESIGN (with deviations), OPERATIONS (architecture, config reference, API, deploy/upgrade/uninstall, air-gap, storage/backup, observability, troubleshooting), finance guide, networking guide | review |

## Commands executed and results (2026-10-25, final code)

| Command | Result |
|---|---|
| `MARKETLAB_TEST_DATABASE_URL=… scripts/test-all.sh` | backend **96 passed** (incl. 3 PostgreSQL); frontend typecheck clean, **20 passed**, build OK; manifests **18 passed** (20 after the label fix below) |
| `backend/.venv/bin/pytest tests/deploy` (after label fix) | **20 passed** |
| `scripts/build-images.sh` (podman) | both images built |
| kind 1.34 cluster, namespace labelled `pod-security.kubernetes.io/enforce=restricted`: `install.sh -o local --with-postgres` | all three Deployments admitted and rolled out |
| `verify.sh -n marketlab-test --url …` (persistent) | **23 passed, 0 failed** |
| NetworkPolicy probe pod | other pod → backend: blocked; other pod → PostgreSQL: blocked; frontend → backend: 200; frontend → PostgreSQL: blocked; backend → PostgreSQL: open |
| Pod checks | backend/frontend UID 1001, PostgreSQL UID 26; root filesystems not writable |
| `kubectl rollout restart` backend | archived history kept (2 app instances, 21 trades); live state reset by design |
| `uninstall.sh` / `--delete-data` / reinstall | data kept by default and reused on reinstall; fully removed with `--delete-data` |
| ephemeral install on kind + `verify.sh` | **22 passed, 1 skipped** (persistence) |
| `scripts/run-local.sh up` + `verify.sh --url http://127.0.0.1:8080` (final images) | **18 passed, 1 skipped** |
| `podman build --network=none` backend from the wheelhouse (19 wheels incl. psycopg) | OK; image imports the app as UID 54321 with a read-only root |
| TCP suites (raw TCP, dev; HTTP, in-container) | results recorded in `docs/networking-guide.md` §8 |

## Educational upgrade (2026-10-26)

| Addition | What it is | Verified by |
|---|---|---|
| Learning path | 18 lessons in three levels (beginner → advanced), each with explanation, key ideas, formula, a “try it” link into the app and a quiz; progress saved per browser | Vitest: lesson integrity (unique ids, valid answers, real routes), quiz scoring and completion |
| Glossary + hover terms | ~75 terms with plain and technical definitions; `<Term>` tooltips on hover/keyboard focus across all pages | Vitest: search filter, keyboard-focus tooltip, “see it” links resolve |
| Panel help & “Start here” | A “?” explanation on every panel (29 in the original modules plus all new pages) and a 3–4 step starter on each page | Screenshots |
| Order book playground | Sandbox book on the real matching engine; orders as You/Alice/Bob/Carol; numbered explanation of every matching decision in engine order (price-time priority, partial fills, limits, self-trade prevention, resting) | 4 pytest tests (explanations match actual fills and ordering) + Vitest |
| Risk & returns lab | Seeded GBM paths; returns, volatility, Sharpe, max drawdown, historical/parametric VaR, expected shortfall, skew/kurtosis, histogram vs. normal curve, optional crash days; two-asset diversification | 4 pytest tests (formula consistency, determinism, fat tails raise kurtosis, ρ = ±1 limits) + Vitest |
| Options lab | Black-Scholes with dividend yield, Greeks (trader units), payoff/value and time-decay charts, implied volatility, put-call parity, CRR binomial convergence and American price | 4 pytest tests (Hull textbook values 4.76/0.81, Greeks vs. finite differences, convergence, IV round-trip) + Vitest |
| How it works | The journey of a click, a live inspector of this browser's real API calls, the backend event stream, a code map linked to GitHub, and an API explorer generated from OpenAPI | Vitest: inspector records a real call with its body |
| Navigation | Sidebar grouped Start / Markets / Quant labs / Technology with level badges; “Where should I start?” chooser on Home; the simulation clock bar only on pages that use it | Vitest + screenshots (1400 px and 390 px) |

Commands (final code): `scripts/test-all.sh` → backend **105 passed** (3 PostgreSQL tests skipped without a database),
frontend typecheck clean and **30 passed**, manifests **21 passed**; `scripts/build-images.sh` and `scripts/run-local.sh up`
(both auto-detected the host's podman from inside the toolbox) → `scripts/verify.sh --url http://127.0.0.1:8080` **18 passed,
1 skipped**; new endpoints and lesson routes answer through nginx.

Not done: the published quay images (`components/images`) still pin the previous release; run `scripts/release-images.sh`
to publish this version. Not re-tested on Kubernetes after these changes (no manifest changes were needed).

## Bugs found and fixed during verification

- `install.sh`: image overrides did not match after overlay renaming; untagged `host:port/…` references were
  mangled; `tr </dev/urandom | head` aborted the script under `pipefail` (silent exit before creating the DB
  Secret).
- `verify.sh`: JSON containing apostrophes broke `bash -c` checks (rewritten as functions).
- Uninstall left PostgreSQL resources and the OpenShift Route/router policy behind (missing `part-of` labels);
  a manifest test now asserts every resource is labelled.
- Readiness failed during a database outage, which would have taken the whole app offline; it now reports `degraded`.
- The PostgreSQL writer dropped a batch on failure; it now retries after reconnecting.
- The HTTP benchmark exposed a real ~40 ms Nagle/delayed-ACK stall under `uvicorn --reload` (sockets without
  TCP_NODELAY). It is documented and flagged in run notes; the production image is unaffected.

## Not verified

- **Real OpenShift**: Route admission/TLS, WebSockets through the HAProxy router (the 1 h timeout annotation),
  SCC `restricted-v2` admission, and OpenShift's arbitrary UID assignment. Arbitrary UIDs were tested with podman
  (UID 54321, GID 0) and restricted admission with upstream Pod Security; neither is identical to OpenShift.
- The frontend offline build via an npm mirror.
- Behaviour under real network latency (the TCP lab is loopback by design).
- Tablet-specific layouts were not screenshotted (desktop and 390 px phone width were).
- No shellcheck or Python linter run (not installed).

## Known limitations (by design)

Live state in memory with a single backend replica; simplified market and futures models; no authentication;
the TCP lab cannot observe TCP segments; HTTP server timestamps are application-level. See the README and the
operations guide.

## Published images (2026-10-25)

Public repository `quay.io/allenfouladi/quant` (anonymous pull verified, digests confirmed):

| Image | Tag | Digest |
|---|---|---|
| backend | `backend-0.1.0` | `sha256:be232b72bc03603624b795dfd932fb86d3bfbd986496b4377a1c86f774f5c598` |
| frontend | `frontend-0.1.0` | `sha256:3b86857d42d5ea6302d07f5d120d3771330bb70a70f6e16feba33b7e151551dd` |

## Exact next steps

1. On the home OpenShift cluster:
   ```bash
   BACKEND_IMAGE=quay.io/allenfouladi/quant@sha256:be232b72bc03603624b795dfd932fb86d3bfbd986496b4377a1c86f774f5c598 \
   FRONTEND_IMAGE=quay.io/allenfouladi/quant@sha256:3b86857d42d5ea6302d07f5d120d3771330bb70a70f6e16feba33b7e151551dd \
     scripts/install.sh -n marketlab --create-namespace --with-postgres
   scripts/verify.sh -n marketlab -k
   ```
   Record the result here.
2. Optionally pin base images by digest for fully reproducible builds.
