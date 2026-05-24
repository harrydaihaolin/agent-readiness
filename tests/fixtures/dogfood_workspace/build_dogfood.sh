#!/usr/bin/env bash
# Build a dogfood workspace stub for manual inspection (tests use tmp_path instead).
set -euo pipefail

ROOT="${1:-$(mktemp -d)}"
echo "Building dogfood workspace at: ${ROOT}"

for name in repo-a repo-b repo-c-ambiguous; do
  mkdir -p "${ROOT}/${name}/.git"
  echo "ref: refs/heads/main" > "${ROOT}/${name}/.git/HEAD"
  echo "# ${name}" > "${ROOT}/${name}/README.md"
done

cat > "${ROOT}/repo-a/pyproject.toml" <<'EOF'
[project]
name = "repo-a"
version = "0.1.0"
EOF

cat > "${ROOT}/repo-b/package.json" <<'EOF'
{"name": "repo-b", "version": "0.2.0"}
EOF

cat > "${ROOT}/repo-c-ambiguous/pyproject.toml" <<'EOF'
[project]
name = "repo-c-ambiguous"
version = "0.3.0"
EOF

cat > "${ROOT}/repo-c-ambiguous/package.json" <<'EOF'
{"name": "repo-c-ambiguous", "version": "0.3.0"}
EOF

mkdir -p "${ROOT}/not-a-repo"
echo "nope" > "${ROOT}/not-a-repo/README.md"

echo "Done."
