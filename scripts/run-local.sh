#!/usr/bin/env bash
# Run MarketLab in a podman pod the way OpenShift would: arbitrary UID in group 0,
# read-only root FS, all capabilities dropped.  UI: http://127.0.0.1:${PORT:-8080}
#
#   scripts/run-local.sh [up|down]
#
# Uses locally built images (localhost/marketlab-*:$TAG, from scripts/build-images.sh)
# when they exist, otherwise the published images pinned in
# deploy/kustomize/components/images (pulled automatically). podman is auto-detected,
# including the host's podman from inside a toolbox.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
detect_podman
P=$PODMAN; PORT=${PORT:-8080}; TAG=${TAG:-dev}
SEC=(--user 54321:0 --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges)

pick() {  # $1 = backend|frontend
  local local_ref="localhost/marketlab-$1:$TAG"
  if $P image exists "$local_ref" 2>/dev/null; then echo "$local_ref"; else published_image "marketlab-$1"; fi
}

case ${1:-up} in
  up)
    BE=$(pick backend); FE=$(pick frontend)
    info "Backend image:  $BE"; info "Frontend image: $FE"
    $P pod rm -f marketlab >/dev/null 2>&1 || true
    $P pod create --name marketlab -p "127.0.0.1:$PORT:8080" >/dev/null
    $P run -d --pod marketlab --name marketlab-backend "${SEC[@]}" "$BE" >/dev/null
    $P run -d --pod marketlab --name marketlab-frontend "${SEC[@]}" -e MARKETLAB_BACKEND_HOSTPORT=127.0.0.1:8000 "$FE" >/dev/null
    for _ in $(seq 1 60); do curl -sf --max-time 2 "http://127.0.0.1:$PORT/healthz/ready" >/dev/null && break; sleep 1; done
    curl -sf --max-time 2 "http://127.0.0.1:$PORT/healthz/ready" >/dev/null || die "MarketLab did not become ready; see: $P logs marketlab-backend"
    ok "MarketLab running at http://127.0.0.1:$PORT  (verify: scripts/verify.sh --url http://127.0.0.1:$PORT)" ;;
  down) $P pod rm -f marketlab >/dev/null && ok "Stopped" ;;
  *) die "usage: $0 [up|down]" ;;
esac
