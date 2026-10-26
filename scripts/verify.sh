#!/usr/bin/env bash
# Verify a MarketLab installation. No manual steps needed:
#
#   scripts/verify.sh                      # namespace "marketlab": cluster checks + HTTP checks
#   scripts/verify.sh -n <namespace>       # another namespace
#   scripts/verify.sh --url <base-url>     # HTTP checks only (e.g. scripts/run-local.sh at http://127.0.0.1:8080)
#
# HTTP checks go through the Route when there is one, otherwise through a temporary
# port-forward that this script starts and stops itself. A self-signed ingress
# certificate is detected and accepted with a warning (-k forces it).
#
# NOTE: this script mutates simulation state (orders, scenarios, resets, a short benchmark) as part of the smoke test.
set -uo pipefail
source "$(dirname "$0")/lib.sh"

NAMESPACE="${MARKETLAB_NAMESPACE:-}"
URL=""
PF_PID=""
cleanup() { [ -n "$PF_PID" ] && kill "$PF_PID" 2>/dev/null; true; }
trap cleanup EXIT
CURL_OPTS=(-sS --max-time 10)
while [ $# -gt 0 ]; do
  case $1 in
    -n|--namespace) NAMESPACE=$2; shift 2 ;;
    --url) URL=${2%/}; shift 2 ;;
    -k|--insecure) CURL_OPTS+=(-k); shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[ -n "$NAMESPACE$URL" ] || NAMESPACE=marketlab
command -v curl >/dev/null || die "curl is required"

PASS=0; FAILED=0; SKIPPED=0
check() { local name=$1; shift; if "$@"; then ok "$name"; PASS=$((PASS+1)); else fail "$name"; FAILED=$((FAILED+1)); fi; }
skip() { warn "SKIP: $1"; SKIPPED=$((SKIPPED+1)); }

# ---------- cluster-level checks ----------
if [ -n "$NAMESPACE" ]; then
  detect_cli
  for d in marketlab-backend marketlab-frontend; do
    check "deployment $d has ready replicas" \
      bash -c "[ \"\$($CLI get deploy $d -n $NAMESPACE -o jsonpath='{.status.readyReplicas}' 2>/dev/null)\" -ge 1 ]"
  done
  check "backend /healthz/ready (inside backend pod)" \
    $CLI exec -n "$NAMESPACE" deploy/marketlab-backend -- curl -sf --max-time 5 http://127.0.0.1:8000/healthz/ready -o /dev/null
  check "frontend -> backend Service (proxied /healthz/ready from frontend pod)" \
    $CLI exec -n "$NAMESPACE" deploy/marketlab-frontend -- curl -sf --max-time 5 http://127.0.0.1:8080/healthz/ready -o /dev/null
  if [ -z "$URL" ] && $CLI get route marketlab -n "$NAMESPACE" >/dev/null 2>&1; then
    URL="https://$($CLI get route marketlab -n "$NAMESPACE" -o jsonpath='{.spec.host}')"
    info "Using Route URL $URL"
  fi
  if [ -z "$URL" ]; then
    # No Route (plain Kubernetes): port-forward the frontend Service ourselves.
    PF_PORT=$(( 20000 + RANDOM % 20000 ))
    $CLI port-forward -n "$NAMESPACE" svc/marketlab-frontend "$PF_PORT:8080" >/dev/null 2>&1 &
    PF_PID=$!
    for _ in $(seq 1 30); do curl -sf --max-time 2 "http://127.0.0.1:$PF_PORT/nginx-health" >/dev/null && break; sleep 0.5; done
    URL="http://127.0.0.1:$PF_PORT"
    info "No Route: using a temporary port-forward at $URL"
  fi
fi

# Self-signed ingress certificates are common in home labs: detect and accept with a warning.
if [[ "$URL" == https://* ]] && [[ " ${CURL_OPTS[*]} " != *" -k "* ]]; then
  curl -s -o /dev/null --max-time 10 "$URL/nginx-health"; rc=$?
  if [ "$rc" -eq 60 ] || [ "$rc" -eq 35 ]; then
    warn "TLS certificate for $URL is not trusted by this machine (self-signed?); continuing with -k"
    CURL_OPTS+=(-k)
  fi
fi

# ---------- HTTP checks through the public entry point ----------
if [ -n "$URL" ]; then
  get()  { curl "${CURL_OPTS[@]}" "$URL$1"; }
  post() { curl "${CURL_OPTS[@]}" -X POST -H 'Content-Type: application/json' "$URL$1" ${2:+-d "$2"}; }
  has()  { grep -q "$1" <<<"$2"; }

  check "frontend serves the SPA" bash -c "curl ${CURL_OPTS[*]} '$URL/' | grep -q '<div id=\"root\">'"
  check "SPA deep link falls back to index.html" bash -c "curl ${CURL_OPTS[*]} '$URL/market-maker' | grep -q '<div id=\"root\">'"
  check "backend readiness via proxy" has '"status":"ok"' "$(get /healthz/ready)"
  check "API info reports simulation mode" has '"simulation_mode":true' "$(get /api/v1/info)"

  post /api/v1/simulation/reset >/dev/null
  check "simulation start" has '"state":"running"' "$(post /api/v1/simulation/start)"
  sleep 1
  PAUSED=$(post /api/v1/simulation/pause)
  paused_ok() { has '"state":"paused"' "$PAUSED" && ! has '"tick":0,' "$PAUSED"; }
  check "simulation pause after ticks advanced" paused_ok
  check "simulation reset to tick 0" has '"tick":0' "$(post /api/v1/simulation/reset)"
  check "event history recorded the lifecycle" has 'simulation.paused' "$(get '/api/v1/events?type=simulation.')"
  check "error envelope on invalid transition" has '"invalid_transition"' "$(post /api/v1/simulation/pause)"

  # WebSocket upgrade through nginx / the Route (handshake only).
  WS_CODE=$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' --max-time 3 \
    -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' \
    -H 'Sec-WebSocket-Key: bWFya2V0bGFiLXZlcmlmeQ==' "$URL/api/v1/stream" 2>/dev/null)
  check "WebSocket upgrade on /api/v1/stream (HTTP 101)" test "$WS_CODE" = 101

  # ---- primary market-maker workflow: order -> match -> trade -> inventory/cash -> P&L ----
  post /api/v1/simulation/reset >/dev/null
  post /api/v1/mm/reset >/dev/null
  KEY="verify-$(date +%s)-$$"
  mm_order() { curl "${CURL_OPTS[@]}" -X POST -H 'Content-Type: application/json' -H "Idempotency-Key: $KEY" "$URL/api/v1/mm/orders" -d '{"side":"sell","type":"market","quantity":100}'; }
  check "MM: customer market sell fills against the market maker's bid" has '"status":"filled"' "$(mm_order)"
  LEDGER=$(get /api/v1/mm/ledger)
  check "MM: inventory updated to +100 shares" has '"position":100' "$LEDGER"
  check "MM: cash reconciles (1,000,000 - 100 x 99.95 - 0.50 fee)" has '"cash":"990004.5' "$LEDGER"
  retry_not_duplicated() { has '"idempotent_replay":true' "$(mm_order)" && has '"position":100' "$(get /api/v1/mm/ledger)"; }
  check "MM: retry with the same Idempotency-Key is not duplicated" retry_not_duplicated
  check "MM: market maker re-quoted after the trade (skewed bid 99.94)" has '"bid":"99.94"' "$(get /api/v1/mm/quote)"

  # ---- FX routing and hedging ----
  post /api/v1/fx/scenarios/4/reset >/dev/null
  FX=$(post /api/v1/fx/scenarios/4/step)
  fx_split() { has '"status":"filled"' "$FX" && [ "$(grep -o '"book":"[ABC]","quantity"' <<<"$FX" | sort -u | wc -l)" -ge 2 ]; }
  check "FX: smart routing splits a 1,000,000 parent across books and fills it" fx_split
  post /api/v1/portfolio/scenarios/gbp-hedge/reset >/dev/null
  for _ in 1 2 3; do post /api/v1/portfolio/scenarios/gbp-hedge/step '{"instrument":"futures"}' >/dev/null; done
  check "Hedging: futures hedge executes and neutralises GBP exposure" has '"status":"executed"' "$(post /api/v1/portfolio/scenarios/gbp-hedge/step '{"instrument":"futures"}')"

  # ---- TCP lab: a short real benchmark ----
  RUN=$(curl "${CURL_OPTS[@]}" -X POST -H 'Content-Type: application/json' "$URL/api/v1/tcp/benchmarks" -d '{"mode":"split","connection":"reused","trials":10,"warmup":1,"split_delay_ms":1}')
  RUN_ID=$(grep -o '"id":"RUN-[^"]*"' <<<"$RUN" | head -1 | cut -d'"' -f4)
  for _ in $(seq 1 30); do
    R=$(get "/api/v1/tcp/benchmarks/$RUN_ID"); grep -q '"status":"\(completed\|failed\)"' <<<"$R" && break; sleep 1
  done
  bench_ok() { has '"status":"completed"' "$R" && has '"n":10' "$R"; }
  check "TCP lab: split-message benchmark completed with 10 measured trials" bench_ok

  # ---- persistence (only meaningful when enabled) ----
  PST=$(get /api/v1/history/status)
  if grep -q '"persistent":true' <<<"$PST"; then
    check "Persistence: PostgreSQL archive connected" has '"connected":true' "$PST"
  else
    skip "persistence checks (ephemeral mode)"
  fi
  post /api/v1/mm/reset >/dev/null; post /api/v1/fx/reset >/dev/null
else
  skip "HTTP checks (no --url and no Route found)"
fi

echo
info "Summary: $PASS passed, $FAILED failed, $SKIPPED skipped"
[ "$FAILED" -eq 0 ]
