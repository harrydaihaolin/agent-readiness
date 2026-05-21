"""Private matcher: ``secret_scanning_config``.

Replaces a naive ``path_glob`` for the ``safety.gitleaks_config`` rule
with a two-stage check:

1. **Accept**: if any of the well-known secret-scanning config files
   exists (``accept_paths`` in the rule's YAML), the rule passes.
2. **Precondition**: if no accept path exists *and* the repo shows
   evidence of handling secrets (env-file usage, env-var reads in
   source, cloud SDK imports, or compose / IaC declarations that bind
   secrets), the rule fires with a message that names the evidence
   so the user can see why it applies to *their* repo.
3. **Skip silently** when no accept path exists *and* there's no
   secret-handling surface area — a pure-library repo (e.g. a JVM
   numerics package, an OCaml type-system playground) is not penalised
   for omitting a tool it has no use for.

This closes the FP residue surfaced by the 2026-05-21 calibration
cycle, where ``safety.gitleaks_config`` over-fired on the JVM /
long-tail-language cohort because the original ``path_glob`` had no
notion of *whether the repo even handles credentials*.

Config:

```yaml
match:
  type: secret_scanning_config
  accept_paths:
    - .gitleaks.toml
    - .gitleaks.yaml
    - .secrets.baseline
    - .pre-commit-config.yaml
    - .github/workflows/gitleaks.yml
    - ...
  require_precondition: true       # default true
  max_files_scanned: 200           # cap on source-file scan
  max_bytes_per_file: 64000
```

When ``require_precondition: false``, the matcher degrades gracefully
to plain accept-path-presence — useful for downstream rule packs that
want the v1.5.0 semantics back.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import register_private_matcher

# Files / globs that signal the repo opts into env-driven secrets.
# `.env` and `.env.<env>` are real secret carriers; `.env.example`
# is the placeholder used to declare an env-driven contract, which
# we treat as evidence the team uses env-files for credentials.
_ENV_FILE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\.env(\.[a-zA-Z0-9_.-]+)?$"),
    re.compile(r"^\.envrc$"),
)

# Source-file extensions worth scanning for env-read / cloud SDK
# evidence. Mirrors regex_secret_scan's text-suffix set but trimmed
# to the file types where credential-handling actually lives.
_SOURCE_SUFFIXES: frozenset[str] = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
    ".rb", ".go", ".rs",
    ".java", ".kt", ".kts", ".scala", ".clj", ".cljs", ".cljc",
    ".cs", ".fs", ".fsx", ".vb",
    ".php", ".swift", ".m", ".mm",
    ".sh", ".bash", ".zsh",
    ".ex", ".exs", ".erl",
    ".ml", ".mli", ".jl", ".r", ".R",
    ".hs", ".lhs",
    ".groovy", ".gradle", ".gradle.kts",
})

# Evidence pattern table. Each row is (evidence_label, compiled regex,
# scope) where scope controls *where* the pattern is allowed to match:
#
# - "source":   only source files (suffix in _SOURCE_SUFFIXES)
# - "config":   only YAML/TOML/HCL/JSON/Dockerfile-style configs
# - "anywhere": both
#
# Keep this list conservative — false-positives on the precondition
# turn this matcher back into a noise generator.
_ENV_READ_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("env-var read",  re.compile(r"\bos\.environ\b|\bos\.getenv\s*\("),                 "source"),
    ("env-var read",  re.compile(r"\bprocess\.env\."),                                  "source"),
    ("env-var read",  re.compile(r"\bSystem\.getenv\s*\("),                             "source"),
    ("env-var read",  re.compile(r"\bos\.Getenv\s*\("),                                 "source"),
    ("env-var read",  re.compile(r"std::env::var\b"),                                   "source"),
    ("env-var read",  re.compile(r"\bENV\["),                                           "source"),
    ("env-var read",  re.compile(r"\bgetenv\s*\("),                                     "source"),
    ("env-var read",  re.compile(r"\bSys\.getenv\b"),                                   "source"),
    ("env-var read",  re.compile(r"\bSystem\.GetEnvironmentVariable\b"),                "source"),
    ("env-var read",  re.compile(r"\bConfig\.fetch\s*:env\b|\bSys\.get_env\b"),         "source"),
    ("env-var read",  re.compile(r"\bget_env\s*\(|\bdotenv!\b"),                        "source"),
    ("dotenv lib",    re.compile(r"\b(import\s+dotenv|require\s*\(\s*['\"]dotenv['\"])"), "source"),
    ("dotenv lib",    re.compile(r"\bfrom\s+dotenv\b|\bload_dotenv\b"),                 "source"),
)

_CLOUD_SDK_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("AWS SDK",       re.compile(r"\bimport\s+boto3\b|\bfrom\s+boto3\b"),               "source"),
    ("AWS SDK",       re.compile(r"['\"]aws-sdk['\"]|@aws-sdk/"),                       "source"),
    ("AWS SDK",       re.compile(r"github\.com/aws/aws-sdk-go"),                        "source"),
    ("AWS SDK",       re.compile(r"software\.amazon\.awssdk|com\.amazonaws"),           "source"),
    ("GCP SDK",       re.compile(r"\bgoogle\.cloud\b|\bgoogle-cloud-"),                 "source"),
    ("GCP SDK",       re.compile(r"@google-cloud/"),                                    "source"),
    ("Azure SDK",     re.compile(r"\bazure\.identity\b|@azure/identity"),               "source"),
    ("Azure SDK",     re.compile(r"\bMicrosoft\.Azure\b"),                              "source"),
    ("Firebase Admin", re.compile(r"\bfirebase-admin\b|\bfirebase_admin\b"),            "source"),
    ("Stripe SDK",    re.compile(r"\bimport\s+stripe\b|['\"]stripe['\"]"),              "source"),
    ("Twilio SDK",    re.compile(r"\btwilio\b"),                                        "source"),
    ("Vault client",  re.compile(r"\bhvac\b|\bhashicorp/vault\b"),                      "source"),
    ("Database URL",  re.compile(r"\b(postgres|mysql|mongodb|redis)://"),               "source"),
)

# High-confidence credential-shape patterns. A repo that ships
# hardcoded keys is exactly where gitleaks belongs, even if the
# author never wired in a single ``os.environ`` call. Mirrors the
# patterns used by ``secrets.basic_scan`` so the two rules stay
# aligned on what counts as "this repo handles secrets".
_HARDCODED_CRED_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("AWS access key",   re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                            "source"),
    ("GitHub token",     re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),                  "source"),
    ("Slack token",      re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),                "source"),
    ("Google API key",   re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),                      "source"),
    ("Stripe live key",  re.compile(r"\b(sk|pk)_live_[0-9A-Za-z]{16,}\b"),               "source"),
    ("PEM private key",  re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),              "source"),
)

_CONFIG_EVIDENCE_FILES: frozenset[str] = frozenset({
    "docker-compose.yml", "docker-compose.yaml",
    "compose.yml", "compose.yaml",
    "Dockerfile",
})

# Config-scope patterns checked in YAML/TF/JSON/Dockerfile content.
_CONFIG_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("compose secrets:",   re.compile(r"^\s*secrets\s*:", re.M)),
    ("compose env_file:",  re.compile(r"^\s*env_file\s*:", re.M)),
    ("k8s Secret",         re.compile(r"^\s*kind\s*:\s*Secret\b", re.M)),
    ("terraform secret",   re.compile(
        r"\baws_secretsmanager_secret\b|"
        r"\bgoogle_secret_manager_secret\b|"
        r"\bazurerm_key_vault_secret\b|"
        r"\bvault_generic_secret\b"
    )),
    ("helm Secret",        re.compile(r"\.Values\.[A-Za-z0-9_.]*[Ss]ecret\b")),
)


def _matches_env_file(rel: Path) -> bool:
    name = rel.name
    return any(p.match(name) for p in _ENV_FILE_PATTERNS)


def _accept_path_present(ctx: RepoContext, accept_paths: list[str]) -> str | None:
    """Return the first accept_path that exists, or None.

    Paths are matched literally against the repo root (no glob); the
    YAML config supplies the full list of well-known locations.
    """
    for p in accept_paths:
        if (ctx.root / p).is_file():
            return p
    return None


def _collect_evidence(
    ctx: RepoContext,
    *,
    max_files_scanned: int,
    max_bytes_per_file: int,
) -> list[str]:
    """Return a deduped list of evidence labels found in the repo.

    Returns the empty list when the repo has no secret-handling
    surface area. Order is stable across runs so the message reads
    deterministically.
    """
    evidence: list[str] = []
    seen: set[str] = set()

    def _add(label: str) -> None:
        if label not in seen:
            seen.add(label)
            evidence.append(label)

    # Stage 1: file-existence signals (cheap).
    for rel in ctx.files:
        if _matches_env_file(rel):
            _add(f"env file ({rel.name})")
            break

    # Stage 2: source-file content scan (bounded).
    scanned_source = 0
    scanned_config = 0
    for rel in ctx.files:
        if scanned_source >= max_files_scanned and scanned_config >= max_files_scanned:
            break
        suffix = rel.suffix.lower()
        is_source = suffix in _SOURCE_SUFFIXES
        is_config = (
            suffix in {".yml", ".yaml", ".tf", ".hcl", ".json"}
            or rel.name in _CONFIG_EVIDENCE_FILES
        )
        if not is_source and not is_config:
            continue
        text = ctx.read_text(rel, max_bytes=max_bytes_per_file)
        if text is None:
            continue
        if is_source and scanned_source < max_files_scanned:
            scanned_source += 1
            for label, pattern, _scope in _ENV_READ_PATTERNS:
                if pattern.search(text):
                    _add(label)
                    break
            for label, pattern, _scope in _CLOUD_SDK_PATTERNS:
                if pattern.search(text):
                    _add(label)
                    break
            for label, pattern, _scope in _HARDCODED_CRED_PATTERNS:
                if pattern.search(text):
                    _add(f"hardcoded {label}")
                    break
        if is_config and scanned_config < max_files_scanned:
            scanned_config += 1
            for label, pattern in _CONFIG_SECRET_PATTERNS:
                if pattern.search(text):
                    _add(label)
                    break
    return evidence


def match_secret_scanning_config(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    accept_paths = list(cfg.get("accept_paths") or [])
    require_precondition = bool(cfg.get("require_precondition", True))
    max_files_scanned = int(cfg.get("max_files_scanned", 200))
    max_bytes_per_file = int(cfg.get("max_bytes_per_file", 64_000))

    if not accept_paths:
        # Misconfigured rule — be conservative and skip rather than
        # noisily firing.
        return []

    if _accept_path_present(ctx, accept_paths) is not None:
        return []

    if not require_precondition:
        return [(
            None, None,
            f"None of these expected paths exist: {', '.join(accept_paths)}",
        )]

    evidence = _collect_evidence(
        ctx,
        max_files_scanned=max_files_scanned,
        max_bytes_per_file=max_bytes_per_file,
    )
    if not evidence:
        # No secret-handling surface area; skip the rule rather than
        # firing on a repo that has no need for gitleaks.
        return []

    # Cap evidence list shown in the message so a chatty repo doesn't
    # produce a wall of text.
    shown = evidence[:5]
    suffix = f" (+{len(evidence) - len(shown)} more)" if len(evidence) > len(shown) else ""
    msg = (
        f"This repo handles secrets ({', '.join(shown)}{suffix}) but ships no "
        f"secret-scanning config. None of these expected paths exist: "
        f"{', '.join(accept_paths)}"
    )
    return [(None, None, msg)]


register_private_matcher("secret_scanning_config", match_secret_scanning_config)
