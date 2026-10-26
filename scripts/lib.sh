# Shared helpers for MarketLab scripts. Source, don't execute.
# shellcheck shell=bash

if [ -t 1 ]; then BOLD=$'\e[1m'; RED=$'\e[31m'; GRN=$'\e[32m'; YEL=$'\e[33m'; RST=$'\e[0m'; else BOLD= RED= GRN= YEL= RST=; fi
info() { printf '%s==>%s %s\n' "$BOLD" "$RST" "$*"; }
ok()   { printf '%s[PASS]%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '%s[WARN]%s %s\n' "$YEL" "$RST" "$*" >&2; }
fail() { printf '%s[FAIL]%s %s\n' "$RED" "$RST" "$*" >&2; }
die()  { fail "$*"; exit 1; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KUSTOMIZE_DIR="$REPO_ROOT/deploy/kustomize"

# Pick the cluster CLI: oc preferred, kubectl accepted.
detect_cli() {
  if [ -n "${CLI:-}" ]; then command -v "$CLI" >/dev/null || die "CLI=$CLI not found"; return; fi
  if command -v oc >/dev/null; then CLI=oc
  elif command -v kubectl >/dev/null; then CLI=kubectl
  else die "Neither 'oc' nor 'kubectl' found on PATH. Install the OpenShift CLI (oc)."; fi
}

# Render a kustomization directory to stdout using whatever is available.
kustomize_build() {
  local dir=$1
  if [ -n "${KUSTOMIZE:-}" ]; then "$KUSTOMIZE" build "$dir"
  elif command -v kustomize >/dev/null; then kustomize build "$dir"
  elif [ -n "${CLI:-}" ]; then "$CLI" kustomize "$dir"
  else die "No kustomize renderer: install kustomize, oc or kubectl (or set KUSTOMIZE=/path/to/kustomize)"; fi
}

# Container engine for build/run scripts: podman on PATH, otherwise the host's podman
# when running inside a toolbox/flatpak (where rootless podman cannot start).
# Sets PODMAN to a command that may be several words: use it unquoted.
detect_podman() {
  [ -n "${PODMAN:-}" ] && return
  if command -v podman >/dev/null && podman info >/dev/null 2>&1; then PODMAN=podman
  elif command -v flatpak-spawn >/dev/null && flatpak-spawn --host podman --version >/dev/null 2>&1; then PODMAN="flatpak-spawn --host podman"
  else die "podman not found (install podman, or set PODMAN to your container engine command)"; fi
}

# Published image references (single source of truth: deploy/kustomize/components/images).
published_image() {  # $1 = marketlab-backend | marketlab-frontend  -> repo@digest
  awk -v want="$1" '
    $1 == "-" && $2 == "name:" { cur = $3 }
    cur == want && $1 == "newName:" { name = $2 }
    cur == want && $1 == "digest:" { print name "@" $2; exit }
  ' "$KUSTOMIZE_DIR/components/images/kustomization.yaml"
}

# Replace container images in rendered YAML, matching by container name (backend/frontend/postgres).
# Kustomize emits keys alphabetically, so a container's "image:" precedes its "name:"; for each
# image line we scan forward within the same list item for the name at the same indentation.
# Usage: override_images <file> backend=<ref> frontend=<ref> postgres=<ref>  (empty refs are ignored)
override_images() {
  local file=$1; shift
  local args=() kv
  for kv in "$@"; do [ -n "${kv#*=}" ] && args+=("$kv"); done
  [ ${#args[@]} -eq 0 ] && return 0
  awk -v specs="${args[*]}" '
    function keyindent(line,   m) { match(line, /^ */); m = RLENGTH; if (substr(line, m + 1, 2) == "- ") m += 2; return m }
    BEGIN { n = split(specs, a, " "); for (i = 1; i <= n; i++) { p = index(a[i], "="); map[substr(a[i], 1, p - 1)] = substr(a[i], p + 1) } }
    { line[NR] = $0 }
    END {
      for (i = 1; i <= NR; i++) {
        if (line[i] ~ /^ *(- )?image: /) {
          ind = keyindent(line[i])
          for (j = i + 1; j <= NR; j++) {
            if (line[j] ~ /^ *$/) continue
            k = keyindent(line[j])
            if (k < ind || (k == ind && line[j] ~ /^ *- /)) break     # left this container item
            if (k == ind && match(line[j], /name: [A-Za-z0-9_-]+ *$/)) {
              nm = line[j]; sub(/^ *(- )?name: /, "", nm); sub(/ *$/, "", nm)
              if (nm in map) sub(/image: .*/, "image: " map[nm], line[i])
              break
            }
          }
        }
        print line[i]
      }
    }
  ' "$file" > "$file.tmp" && mv "$file.tmp" "$file"
}
