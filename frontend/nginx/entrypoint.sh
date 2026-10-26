#!/bin/sh
# Render nginx.conf from environment and start nginx in the foreground.
# Works under any UID (OpenShift restricted-v2) with a read-only root FS,
# provided /tmp is writable (emptyDir in Kubernetes, --tmpfs in podman).
set -eu

: "${MARKETLAB_BACKEND_HOSTPORT:=marketlab-backend:8000}"
: "${NGINX_PORT:=8080}"
export MARKETLAB_BACKEND_HOSTPORT NGINX_PORT

case "$MARKETLAB_BACKEND_HOSTPORT" in
  *[!A-Za-z0-9.:_-]*|"") echo "invalid MARKETLAB_BACKEND_HOSTPORT: $MARKETLAB_BACKEND_HOSTPORT" >&2; exit 1 ;;
esac

mkdir -p /tmp/nginx
envsubst '${MARKETLAB_BACKEND_HOSTPORT} ${NGINX_PORT}' \
  < /opt/marketlab/nginx.conf.template > /tmp/nginx/nginx.conf
nginx -t -q -c /tmp/nginx/nginx.conf
exec nginx -c /tmp/nginx/nginx.conf -g 'daemon off;'
