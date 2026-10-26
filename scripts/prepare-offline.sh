#!/usr/bin/env bash
# Run while ONLINE. Collects everything needed to install or rebuild MarketLab without internet:
#   offline/app-images.tar   published MarketLab images (pinned digests) + the PostgreSQL image
#   offline/base-images.tar  UBI base images, to rebuild inside the lab
#   backend/wheels/          Python wheels for the image's Python 3.12 / x86_64
# Frontend npm packages: rebuild the frontend online, or point NPM_CONFIG_REGISTRY at an internal mirror.
#
#   scripts/prepare-offline.sh [output-dir]
set -euo pipefail
source "$(dirname "$0")/lib.sh"
detect_podman

OUT=${1:-"$REPO_ROOT/offline"}
mkdir -p "$OUT"
PY=${PYTHON:-python3}
info "Downloading Python wheels into backend/wheels"
"$PY" -m pip download -q --dest "$REPO_ROOT/backend/wheels" --only-binary=:all: \
  --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux_2_28_x86_64 \
  --python-version 3.12 --implementation cp -r "$REPO_ROOT/backend/requirements.txt"

PG=$(awk '/name: marketlab-postgres/{getline; n=$2; getline; print n ":" $2; exit}' "$KUSTOMIZE_DIR/components/postgres/kustomization.yaml")
APPS=("$(published_image marketlab-backend)" "$(published_image marketlab-frontend)" "$PG")
info "Pulling application images"
for i in "${APPS[@]}"; do $PODMAN pull -q "$i" >/dev/null && echo "    $i"; done
$PODMAN save -m -o "$OUT/app-images.tar" "${APPS[@]}"
printf '%s\n' "${APPS[@]}" > "$OUT/app-images.txt"

BASES=(registry.access.redhat.com/ubi9/python-312:latest registry.access.redhat.com/ubi9/python-312-minimal:latest
       registry.access.redhat.com/ubi9/nodejs-22:latest registry.access.redhat.com/ubi9/nginx-124:latest)
info "Pulling base images"
for b in "${BASES[@]}"; do $PODMAN pull -q "$b" >/dev/null && echo "    $b"; done
$PODMAN save -m -o "$OUT/base-images.tar" "${BASES[@]}"
(cd "$OUT" && sha256sum ./*.tar > SHA256SUMS)
ok "Offline bundle ready in $OUT (app-images.tar, base-images.tar, SHA256SUMS) plus backend/wheels."
echo "In the lab: podman load -i app-images.tar, push to your registry, then"
echo "  BACKEND_IMAGE=<lab-registry>/... FRONTEND_IMAGE=<lab-registry>/... POSTGRES_IMAGE=<lab-registry>/... scripts/install.sh"
