#!/usr/bin/env bash
# Install or upgrade MarketLab. With no arguments it needs no manual steps:
#
#   scripts/install.sh
#
# Defaults: namespace "marketlab" (created if missing), overlay auto-detected (openshift
# when the Route API exists, otherwise local), the published images pinned in
# deploy/kustomize/components/images (quay.io/allenfouladi/quant), and scripts/verify.sh
# runs automatically at the end.
#
# Options:
#   -n, --namespace NS        target namespace (default: marketlab, or $MARKETLAB_NAMESPACE)
#   -o, --overlay NAME        openshift | local (default: auto-detect)
#   --with-postgres           persistent mode with in-namespace PostgreSQL (PVC + generated Secret).
#                             Kept automatically on upgrades once installed; --without-postgres disables.
#   --no-create-namespace     fail instead of creating a missing namespace
#   --no-verify               skip the post-install verification
#   --timeout DUR             rollout wait per deployment (default 300s)
#   --dry-run                 render + server-side dry run only
# Image overrides (optional, e.g. an air-gapped registry): BACKEND_IMAGE, FRONTEND_IMAGE, POSTGRES_IMAGE.
#
# Requires oc (or kubectl) logged in with edit rights on the namespace; never cluster-admin.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

NAMESPACE="${MARKETLAB_NAMESPACE:-marketlab}"
OVERLAY=""
CREATE_NS=true
TIMEOUT=300s
DRY_RUN=false
WITH_PG=""          # "", true or false; "" = auto (keep whatever is installed)
VERIFY=true

usage() { sed -n '2,24p' "$0"; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
  case $1 in
    -n|--namespace) NAMESPACE=$2; shift 2 ;;
    -o|--overlay) OVERLAY=$2; shift 2 ;;
    --create-namespace) CREATE_NS=true; shift ;;           # accepted for compatibility (default)
    --no-create-namespace) CREATE_NS=false; shift ;;
    --timeout) TIMEOUT=$2; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --with-postgres) WITH_PG=true; shift ;;
    --without-postgres) WITH_PG=false; shift ;;
    --no-verify) VERIFY=false; shift ;;
    -h|--help) usage 0 ;;
    *) fail "unknown argument: $1"; usage 1 ;;
  esac
done

# --- 1. tools & inputs --------------------------------------------------------------
detect_cli
info "Using CLI: $CLI ($($CLI version --client 2>/dev/null | head -1))"
[[ "$NAMESPACE" =~ ^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$ ]] || die "Invalid namespace name: '$NAMESPACE'"

# --- 2. cluster access ------------------------------------------------------------------
$CLI auth can-i get pods >/dev/null 2>&1 || die "Not logged in to a cluster (try: oc login <api-url>)"
info "Cluster: $($CLI config current-context 2>/dev/null || echo unknown)"
HAS_ROUTES=false
$CLI api-resources --api-group=route.openshift.io 2>/dev/null | grep -q '^routes' && HAS_ROUTES=true
if [ -z "$OVERLAY" ]; then
  if $HAS_ROUTES; then OVERLAY=openshift; else OVERLAY=local; fi
  info "Overlay: $OVERLAY (auto-detected)"
fi
[ -d "$KUSTOMIZE_DIR/overlays/$OVERLAY" ] || die "Unknown overlay '$OVERLAY' (have: $(ls "$KUSTOMIZE_DIR/overlays" | tr '\n' ' '))"
[ "$OVERLAY" != openshift ] || $HAS_ROUTES || die "This cluster has no route.openshift.io API; use -o local."

if ! $CLI get namespace "$NAMESPACE" >/dev/null 2>&1; then
  $CREATE_NS || die "Namespace '$NAMESPACE' not found (remove --no-create-namespace to create it)."
  info "Creating namespace $NAMESPACE"
  if [ "$CLI" = oc ]; then
    oc new-project "$NAMESPACE" --skip-config-write >/dev/null 2>&1 || oc create namespace "$NAMESPACE" >/dev/null \
      || die "Could not create namespace $NAMESPACE (ask an admin to create it, then rerun)"
  else
    kubectl create namespace "$NAMESPACE" >/dev/null || die "Could not create namespace $NAMESPACE"
  fi
fi

# Persistent mode: keep it on upgrades if it is already installed.
if [ -z "$WITH_PG" ]; then
  if $CLI get deploy marketlab-postgres -n "$NAMESPACE" >/dev/null 2>&1; then
    WITH_PG=true; info "PostgreSQL already installed here: keeping persistent mode (--without-postgres to change)"
  else
    WITH_PG=false
  fi
fi

PERMS=("create deployments.apps" "create services" "create configmaps" "create networkpolicies.networking.k8s.io")
$WITH_PG && PERMS+=("create persistentvolumeclaims" "create secrets")
for verb_res in "${PERMS[@]}"; do
  # shellcheck disable=SC2086
  $CLI auth can-i $verb_res -n "$NAMESPACE" >/dev/null 2>&1 || die "Missing permission in $NAMESPACE: $verb_res (ask for the 'edit' role)"
done

# --- 3. render ----------------------------------------------------------------------------
WORK="$KUSTOMIZE_DIR/.install-$$"   # inside the repo: kustomize rejects absolute resource paths
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK"
{
  echo "apiVersion: kustomize.config.k8s.io/v1beta1"
  echo "kind: Kustomization"
  echo "resources: [../overlays/$OVERLAY]"
  $WITH_PG && echo "components: [../components/postgres]"
  true
} > "$WORK/kustomization.yaml"
RENDERED="$WORK/rendered.yaml"
kustomize_build "$WORK" > "$RENDERED" || die "Manifest rendering failed"
override_images "$RENDERED" "backend=${BACKEND_IMAGE:-}" "frontend=${FRONTEND_IMAGE:-}" "postgres=${POSTGRES_IMAGE:-}"
if grep -Eq '^\s+image: (marketlab-|.*CHANGE-ME)' "$RENDERED"; then
  die "An image reference is unresolved; check deploy/kustomize/components/images"
fi
info "Images:"; grep -E '^\s+image:' "$RENDERED" | sed 's/^ */    /'

# --- 4. validate & apply ---------------------------------------------------------------------
info "Server-side dry run"
$CLI apply -n "$NAMESPACE" --dry-run=server -f "$RENDERED" >/dev/null || die "Server rejected the manifests (see error above)"
if $DRY_RUN; then ok "Dry run succeeded; nothing applied."; exit 0; fi

if $WITH_PG; then
  if $CLI get secret marketlab-db -n "$NAMESPACE" >/dev/null 2>&1; then
    info "Using existing Secret marketlab-db"
  else
    info "Creating Secret marketlab-db with a random password"
    # od reads exactly 16 random bytes (no SIGPIPE under pipefail, unlike tr </dev/urandom | head).
    PW=$(od -An -tx1 -N16 /dev/urandom | tr -d ' \n')
    [ ${#PW} -eq 32 ] || die "could not generate a database password"
    $CLI create secret generic marketlab-db -n "$NAMESPACE" \
      --from-literal=POSTGRESQL_USER=marketlab --from-literal=POSTGRESQL_DATABASE=marketlab --from-literal=POSTGRESQL_PASSWORD="$PW" >/dev/null
    $CLI label secret marketlab-db -n "$NAMESPACE" app.kubernetes.io/part-of=marketlab >/dev/null
    unset PW
  fi
fi

info "Applying to namespace $NAMESPACE"
$CLI apply -n "$NAMESPACE" -f "$RENDERED"

# --- 5. wait ---------------------------------------------------------------------------------
diagnose() {
  fail "Rollout did not complete. Diagnostics:"
  $CLI get pods -n "$NAMESPACE" -l app.kubernetes.io/part-of=marketlab -o wide || true
  $CLI get events -n "$NAMESPACE" --sort-by=.lastTimestamp 2>/dev/null | tail -20 || true
  for d in "${DEPLOYS[@]}"; do
    echo "--- logs: $d"; $CLI logs -n "$NAMESPACE" "deploy/$d" --tail=30 2>&1 || true
  done
  cat >&2 <<HINT
Common causes:
  ImagePullBackOff   -> the cluster cannot reach the registry (air-gapped? see docs/OPERATIONS.md) or needs a pull secret
  CrashLoopBackOff   -> check the logs above; invalid MARKETLAB_* config fails fast at startup
  Pending            -> insufficient CPU/memory, or (PostgreSQL) no default StorageClass for the PVC
  SCC / forbidden    -> the manifests target restricted-v2; report any SCC error verbatim
HINT
  exit 1
}
DEPLOYS=(marketlab-backend marketlab-frontend)
$WITH_PG && DEPLOYS=(marketlab-postgres "${DEPLOYS[@]}")
for d in "${DEPLOYS[@]}"; do
  info "Waiting for $d (timeout $TIMEOUT)"
  $CLI rollout status -n "$NAMESPACE" "deploy/$d" --timeout="$TIMEOUT" || diagnose
done

# --- 6. URL & verification -----------------------------------------------------------------------
if [ "$OVERLAY" = openshift ]; then
  HOST=""
  for _ in $(seq 1 30); do
    HOST=$($CLI get route marketlab -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || true)
    [ -n "$HOST" ] && break; sleep 2
  done
  [ -n "$HOST" ] && ok "MarketLab is available at: https://$HOST" || warn "Route host not assigned yet: $CLI get route marketlab -n $NAMESPACE"
else
  ok "Installed. To open the UI: $CLI -n $NAMESPACE port-forward svc/marketlab-frontend 8080:8080  -> http://localhost:8080"
fi
if $VERIFY; then
  info "Running scripts/verify.sh"
  CLI=$CLI "$REPO_ROOT/scripts/verify.sh" -n "$NAMESPACE" || die "Installed, but verification failed (see above)."
fi
