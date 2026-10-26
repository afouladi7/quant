#!/usr/bin/env bash
# Build, publish and pin a MarketLab release in one step:
#   1. build both images from the current source
#   2. push them to $REPO as backend-<version> / frontend-<version>
#   3. rewrite deploy/kustomize/components/images with the pushed digests
#   4. confirm the manifests render with the new references
# After this, scripts/install.sh deploys exactly the images just pushed.
#
#   scripts/release-images.sh [--version X.Y.Z]
#
# Defaults: REPO=quay.io/allenfouladi/quant, version = APP_VERSION in backend/app/config.py.
# Prerequisite (once): podman logged in to the registry with push rights,
#   e.g. podman login quay.io -u '<namespace>+<robot>' --password-stdin < token-file
set -euo pipefail
source "$(dirname "$0")/lib.sh"
detect_podman

REPO=${REPO:-quay.io/allenfouladi/quant}
VERSION=$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' "$REPO_ROOT/backend/app/config.py")
while [ $# -gt 0 ]; do
  case $1 in
    --version) VERSION=$2; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[[ "$VERSION" =~ ^[0-9A-Za-z][0-9A-Za-z._-]*$ ]] || die "invalid version '$VERSION'"
REGISTRY_HOST=${REPO%%/*}
$PODMAN login --get-login "$REGISTRY_HOST" >/dev/null 2>&1 \
  || die "podman is not logged in to $REGISTRY_HOST. Log in once (a robot account is recommended), then rerun."

info "Building images (version $VERSION)"
PODMAN="$PODMAN" TAG="$VERSION" "$REPO_ROOT/scripts/build-images.sh" >/dev/null

declare -A DIGEST
for c in backend frontend; do
  ref="$REPO:$c-$VERSION"
  $PODMAN tag "localhost/marketlab-$c:$VERSION" "$ref"
  info "Pushing $ref"
  # podman runs on the host when inside a toolbox: write the digest file somewhere both can see.
  dfile="$REPO_ROOT/deploy/kustomize/.digest-$c-$$"
  $PODMAN push -q --digestfile "$dfile" "$ref"
  DIGEST[$c]=$(cat "$dfile"); rm -f "$dfile"
  [[ "${DIGEST[$c]}" =~ ^sha256:[0-9a-f]{64}$ ]] || die "could not read the pushed digest for $ref"
  ok "$ref -> ${DIGEST[$c]}"
done

IMAGES_FILE="$KUSTOMIZE_DIR/components/images/kustomization.yaml"
cat > "$IMAGES_FILE" <<YAML
# Published MarketLab images, pinned by digest. This file is the single source of truth
# for image references and is rewritten automatically by scripts/release-images.sh.
# Repository: $REPO (tags backend-<ver> / frontend-<ver>).
apiVersion: kustomize.config.k8s.io/v1alpha1
kind: Component
images:
  - name: marketlab-backend
    newName: $REPO
    digest: ${DIGEST[backend]}  # backend-$VERSION
  - name: marketlab-frontend
    newName: $REPO
    digest: ${DIGEST[frontend]}  # frontend-$VERSION
YAML
if [ -n "${KUSTOMIZE:-}" ] || command -v kustomize >/dev/null || command -v oc >/dev/null || command -v kubectl >/dev/null; then
  command -v oc >/dev/null && CLI=oc || { command -v kubectl >/dev/null && CLI=kubectl; } || true
  kustomize_build "$KUSTOMIZE_DIR/overlays/openshift" | grep -q "$REPO@${DIGEST[backend]}" || die "manifests do not render the new backend digest"
else
  warn "no kustomize/oc/kubectl here: skipped the render check"
fi
ok "Pinned in deploy/kustomize/components/images. Deploy with: scripts/install.sh"
