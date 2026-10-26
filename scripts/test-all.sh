#!/usr/bin/env bash
# Run every automated test suite that does not need a cluster.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd "$REPO_ROOT"

PY=backend/.venv/bin/python
[ -x "$PY" ] || die "Create the backend venv first: python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements-dev.txt"

info "Backend unit + API tests"
(cd backend && .venv/bin/pytest -q)
info "Frontend typecheck + tests + build"
(cd frontend && npm run typecheck && npm test && npm run build >/dev/null)
if [ -n "${MARKETLAB_TEST_DATABASE_URL:-}" ]; then
  info "PostgreSQL persistence tests ran above against \$MARKETLAB_TEST_DATABASE_URL"
else
  warn "PostgreSQL persistence tests skipped (set MARKETLAB_TEST_DATABASE_URL to a disposable database)"
fi
info "Manifest render + policy tests"
"$PY" -m pytest -q -p no:cacheprovider tests/deploy
for f in scripts/*.sh; do bash -n "$f"; done
ok "All local test suites passed"
