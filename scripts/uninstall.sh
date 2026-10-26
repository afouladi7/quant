#!/usr/bin/env bash
# Remove MarketLab resources from a namespace (the namespace itself is kept).
#   scripts/uninstall.sh [-n marketlab] [--delete-data] [--delete-namespace]
# By default the PostgreSQL PVC and the marketlab-db Secret (persistent mode) are KEPT.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

NAMESPACE="${MARKETLAB_NAMESPACE:-marketlab}"
DELETE_NS=false
DELETE_DATA=false
while [ $# -gt 0 ]; do
  case $1 in
    -n|--namespace) NAMESPACE=$2; shift 2 ;;
    --delete-namespace) DELETE_NS=true; shift ;;
    --delete-data) DELETE_DATA=true; shift ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
detect_cli

info "Deleting MarketLab resources from $NAMESPACE"
KINDS="deployment,service,configmap,serviceaccount,networkpolicy"
$CLI api-resources --api-group=route.openshift.io 2>/dev/null | grep -q '^routes' && KINDS="$KINDS,route"
$CLI delete "$KINDS" -n "$NAMESPACE" -l app.kubernetes.io/part-of=marketlab --ignore-not-found --wait=true
if $DELETE_DATA; then
  info "Deleting persistent data (PVC marketlab-postgres, Secret marketlab-db)"
  $CLI delete pvc marketlab-postgres -n "$NAMESPACE" --ignore-not-found
  $CLI delete secret marketlab-db -n "$NAMESPACE" --ignore-not-found
else
  $CLI get pvc marketlab-postgres -n "$NAMESPACE" >/dev/null 2>&1 && warn "Kept PVC marketlab-postgres and Secret marketlab-db (use --delete-data to remove)"
fi
if $DELETE_NS; then
  info "Deleting namespace $NAMESPACE"
  $CLI delete namespace "$NAMESPACE" --ignore-not-found
fi
ok "Uninstalled."
