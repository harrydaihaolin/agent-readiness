#!/usr/bin/env bash
# vendor_rules.sh: refresh src/agent_readiness/rules_pack/ from a tagged release
# of harrydaihaolin/agent-readiness-rules.
#
# Usage: scripts/vendor_rules.sh v1.0.0
#
# Writes a MANIFEST file recording the source repo + tag + SHA so we have
# full traceability of what shipped in any given agent-readiness release.

set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <tag>"
  echo "Example: $0 v1.0.0"
  exit 2
fi

TAG="$1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/src/agent_readiness/rules_pack"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

REPO="harrydaihaolin/agent-readiness-rules"

echo "Fetching $REPO@$TAG ..."

if command -v gh >/dev/null 2>&1; then
  # Prefer gh for authenticated rate limits
  gh release download "$TAG" --repo "$REPO" --archive=tar.gz --dir "$TMP" 2>/dev/null || true
fi

ARCHIVE=$(ls "$TMP"/*.tar.gz 2>/dev/null | head -1 || true)
if [ -z "$ARCHIVE" ]; then
  # Fall back to GitHub's tag tarball endpoint
  curl -fsSL "https://github.com/$REPO/archive/refs/tags/$TAG.tar.gz" -o "$TMP/pack.tar.gz"
  ARCHIVE="$TMP/pack.tar.gz"
fi

tar -xzf "$ARCHIVE" -C "$TMP"
PACK_DIR=$(find "$TMP" -mindepth 1 -maxdepth 2 -type d -name 'agent-readiness-rules-*' | head -1)
if [ -z "$PACK_DIR" ]; then
  echo "error: could not find unpacked pack dir under $TMP"
  ls -la "$TMP"
  exit 1
fi

echo "Vendoring rules into $DEST ..."
rm -rf "$DEST"
mkdir -p "$DEST"
cp -r "$PACK_DIR/rules/." "$DEST/"
cp "$PACK_DIR/manifest.toml" "$DEST/manifest.toml"

# Compute a SHA from the tarball for traceability.
SHA=$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')

cat > "$DEST/MANIFEST" <<EOF
# Vendored from harrydaihaolin/agent-readiness-rules@$TAG
# Do not edit by hand; regenerate via scripts/vendor_rules.sh <tag>.
vendored_from = "harrydaihaolin/agent-readiness-rules"
vendored_tag  = "$TAG"
vendored_at   = "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
tarball_sha256 = "$SHA"
EOF

echo "Done. Vendored from $REPO@$TAG."
echo "Files now under $DEST:"
find "$DEST" -type f | sort
