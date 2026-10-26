#!/usr/bin/env bash
# Build both images with podman (or buildah via BUILDER=buildah), optionally push or save.
# podman is auto-detected, including the host's podman from inside a toolbox.
# To publish a release to quay.io/allenfouladi/quant and re-pin the manifests, use scripts/release-images.sh.
#
#   scripts/build-images.sh                                  # -> localhost/marketlab-{backend,frontend}:dev
#   TAG=0.1.0 REGISTRY=registry.lab:5000/marketlab scripts/build-images.sh --push
#   TAG=0.1.0 scripts/build-images.sh --save dist/images     # tarballs for air-gapped transfer
#   OFFLINE=1 scripts/build-images.sh                       # backend from backend/wheels, no network
set -euo pipefail
source "$(dirname "$0")/lib.sh"

if [ -n "${BUILDER:-}" ]; then command -v "${BUILDER%% *}" >/dev/null || die "$BUILDER not found"; else detect_podman; BUILDER=$PODMAN; fi
REGISTRY=${REGISTRY:-localhost}
TAG=${TAG:-dev}
PUSH=false; SAVE_DIR=""
while [ $# -gt 0 ]; do
  case $1 in
    --push) PUSH=true; shift ;;
    --save) SAVE_DIR=$2; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

BE="$REGISTRY/marketlab-backend:$TAG"; FE="$REGISTRY/marketlab-frontend:$TAG"
BE_ARGS=()
if [ "${OFFLINE:-0}" = 1 ]; then
  ls "$REPO_ROOT"/backend/wheels/*.whl >/dev/null 2>&1 || die "backend/wheels is empty: run scripts/prepare-offline.sh while online"
  BE_ARGS=(--network=none --build-arg "PIP_INSTALL_ARGS=--no-index --find-links=/build/wheels")
fi

info "Building $BE"
$BUILDER build "${BE_ARGS[@]}" -t "$BE" -f "$REPO_ROOT/backend/Containerfile" "$REPO_ROOT/backend"
info "Building $FE"
$BUILDER build ${NPM_CONFIG_REGISTRY:+--build-arg NPM_CONFIG_REGISTRY=$NPM_CONFIG_REGISTRY} \
  -t "$FE" -f "$REPO_ROOT/frontend/Containerfile" "$REPO_ROOT/frontend"

if $PUSH; then
  for img in "$BE" "$FE"; do info "Pushing $img"; $BUILDER push "$img"; done
fi
if [ -n "$SAVE_DIR" ]; then
  mkdir -p "$SAVE_DIR"
  for img in "$BE" "$FE"; do
    f="$SAVE_DIR/$(basename "${img%:*}")-$TAG.tar"
    info "Saving $img -> $f"; $BUILDER save --format oci-archive -o "$f" "$img"
  done
  (cd "$SAVE_DIR" && sha256sum ./*.tar > SHA256SUMS) && info "Checksums in $SAVE_DIR/SHA256SUMS"
fi
ok "Images: $BE  $FE"
