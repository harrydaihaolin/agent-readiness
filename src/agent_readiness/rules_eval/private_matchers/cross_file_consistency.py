"""Private matcher: ``cross_file_consistency``.

Two YAML modes:
- ``mode: env_parity`` — fires when source files reference env vars
  AND no ``.env.example``-style file exists. Used by
  ``env.example_parity``.
- ``mode: readme_repo_match`` — fires per inconsistency between
  README claims and repo contents. Used by ``meta.consistency``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import register_private_matcher

_README_NAMES = ("README.md", "README.rst", "README.txt", "README")

# Per-extension single-line comment patterns to strip before env-var search.
_COMMENT_LINE_RE: dict[str, re.Pattern[str]] = {
    ".py": re.compile(r"^\s*#.*$", re.MULTILINE),
    ".rb": re.compile(r"^\s*#.*$", re.MULTILINE),
    ".sh": re.compile(r"^\s*#.*$", re.MULTILINE),
    ".js": re.compile(r"^\s*//.*$", re.MULTILINE),
    ".ts": re.compile(r"^\s*//.*$", re.MULTILINE),
    ".go": re.compile(r"^\s*//.*$", re.MULTILINE),
}


def _strip_comments(text: str, suffix: str) -> str:
    pat = _COMMENT_LINE_RE.get(suffix)
    return pat.sub("", text) if pat is not None else text


def _matches_any_glob_simple(rel: Path, patterns: tuple[str, ...]) -> bool:
    """Lightweight glob match — defers to the OSS matcher's helper if a
    full glob engine isn't needed (we only support `**/*.py`-style)."""
    import fnmatch
    s = str(rel).replace("\\", "/")
    return any(fnmatch.fnmatch(s, pat) for pat in patterns)


def _env_parity_mode(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    raw_patterns = cfg.get("env_patterns") or []
    compiled = []
    for pat in raw_patterns:
        try:
            compiled.append(re.compile(pat))
        except (re.error, TypeError):
            continue
    if not compiled:
        return []

    source_globs = tuple(cfg.get("source_globs") or ("src/**/*.py", "src/**/*.js", "src/**/*.ts"))
    exclude_segments = {seg.lower() for seg in (cfg.get("exclude_path_segments") or [])}
    require_one_of = tuple(cfg.get("require_one_of") or (".env.example", ".env.sample"))

    has_env_refs = False
    for f in ctx._files:
        # Cheap path-segment exclusion.
        if exclude_segments and any(p.lower() in exclude_segments for p in f.parts):
            continue
        if not _matches_any_glob_simple(f, source_globs):
            continue
        raw = ctx.read_text(f) or ""
        text = _strip_comments(raw, f.suffix)
        for pat in compiled:
            if pat.search(text):
                has_env_refs = True
                break
        if has_env_refs:
            break

    if not has_env_refs:
        return []

    for candidate in require_one_of:
        if (ctx.root / candidate).is_file():
            return []

    return [(
        None, None,
        f"Env var usage found in source files but none of {', '.join(require_one_of)} present.",
    )]


def _read_readme(ctx: RepoContext) -> str | None:
    for name in _README_NAMES:
        text = ctx.read_text(name)
        if text is not None:
            return text
    return None


def _has_pytest_config(ctx: RepoContext) -> bool:
    if (ctx.root / "pytest.ini").is_file():
        return True
    if (ctx.root / "setup.cfg").is_file():
        if "[tool:pytest]" in (ctx.read_text("setup.cfg") or ""):
            return True
    if (ctx.root / "pyproject.toml").is_file():
        if "[tool.pytest" in (ctx.read_text("pyproject.toml") or ""):
            return True
    return False


# Each named consistency check returns a finding tuple if it fires.
_PYTEST_RE = re.compile(r"\bpytest\b", re.IGNORECASE)
_NPM_TEST_RE = re.compile(r"\bnpm\s+test\b|\bnpm\s+run\s+test\b", re.IGNORECASE)
_AGENT_DOC_NAMES = ("AGENTS.md", "CLAUDE.md")
_PLACEHOLDER_BYTES = 100


def _readme_repo_match_mode(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    enabled = set(cfg.get("checks") or [
        "pytest_mention_requires_config",
        "npm_test_requires_package_json",
        "agent_doc_not_placeholder",
    ])
    findings: list[tuple[str | None, int | None, str]] = []
    readme_text = _read_readme(ctx)

    if readme_text is not None:
        if (
            "pytest_mention_requires_config" in enabled
            and _PYTEST_RE.search(readme_text)
            and not _has_pytest_config(ctx)
        ):
            findings.append((
                None, None,
                "README references pytest but no pytest configuration was found.",
            ))
        if (
            "npm_test_requires_package_json" in enabled
            and _NPM_TEST_RE.search(readme_text)
            and not (ctx.root / "package.json").is_file()
        ):
            findings.append((
                None, None,
                "README references npm test but no package.json was found.",
            ))

    if "agent_doc_not_placeholder" in enabled:
        for doc_name in _AGENT_DOC_NAMES:
            doc_path = ctx.root / doc_name
            if doc_path.is_file():
                try:
                    size = doc_path.stat().st_size
                except OSError:
                    continue
                if size < _PLACEHOLDER_BYTES:
                    findings.append((
                        doc_name, None,
                        f"{doc_name} is present but appears to be a placeholder ({size} bytes).",
                    ))

    return findings


def match_cross_file_consistency(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    mode = str(cfg.get("mode", ""))
    if mode == "env_parity":
        return _env_parity_mode(ctx, cfg)
    if mode == "readme_repo_match":
        return _readme_repo_match_mode(ctx, cfg)
    return []


register_private_matcher("cross_file_consistency", match_cross_file_consistency)
