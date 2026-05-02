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
    doc_globs = tuple(cfg.get("doc_globs") or ())
    doc_pattern_strs = cfg.get("doc_patterns") or ()
    doc_compiled: list[re.Pattern[str]] = []
    for pat in doc_pattern_strs:
        try:
            doc_compiled.append(re.compile(pat))
        except (re.error, TypeError):
            continue

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

    # Doc-only fallback: prose documentation of env vars
    # (e.g. `export FOO=` snippets or an "Environment vars" heading)
    # counts as parity even without a .env.example file.
    if doc_globs and doc_compiled:
        for doc in doc_globs:
            text = ctx.read_text(doc)
            if not text:
                continue
            for pat in doc_compiled:
                if pat.search(text):
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
_MAKE_TARGET_RE = re.compile(r"`?make\s+([a-zA-Z][a-zA-Z0-9_-]*)`?")
_NPM_RUN_RE = re.compile(r"`?npm\s+run\s+([a-zA-Z][a-zA-Z0-9:_-]*)`?")
_PIP_EDITABLE_RE = re.compile(r"pip\s+install\s+-e\s+\.")
_AGENT_DOC_NAMES = ("AGENTS.md", "CLAUDE.md")
_PLACEHOLDER_BYTES = 100

# Make-target stop-words: README boilerplate that looks like
# `make X` but isn't really invoking a target (e.g. "make sure", "make a").
_MAKE_STOPWORDS = frozenset({
    "sure", "a", "an", "the", "it", "your", "this", "that",
    "changes", "sense", "use", "do", "you",
})

# npm-script stop-words for the same reason.
_NPM_RUN_STOPWORDS = frozenset({"the", "a", "your"})


def _makefile_targets(ctx: RepoContext) -> set[str]:
    """Return the set of `target:` names in any present Makefile-like
    file. Empty set if no Makefile exists (caller will treat that as a
    no-op rather than a finding-storm)."""
    targets: set[str] = set()
    target_re = re.compile(r"^([a-zA-Z][a-zA-Z0-9_-]*)\s*:(?!=)", re.MULTILINE)
    for name in ("Makefile", "GNUmakefile", "makefile"):
        text = ctx.read_text(name)
        if not text:
            continue
        targets.update(m.group(1) for m in target_re.finditer(text))
    return targets


def _package_json_scripts(ctx: RepoContext) -> set[str] | None:
    """Return the set of npm script names, or None if no package.json
    exists. None means "downstream check is moot, suppress findings"."""
    raw = ctx.read_text("package.json")
    if not raw:
        return None
    try:
        import json
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return set()
    scripts = data.get("scripts") or {}
    if not isinstance(scripts, dict):
        return set()
    return set(scripts.keys())


def _readme_repo_match_mode(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    enabled = set(cfg.get("checks") or [
        "pytest_mention_requires_config",
        "npm_test_requires_package_json",
        "agent_doc_not_placeholder",
        "make_target_referenced_in_readme",
        "package_json_script_referenced_in_readme",
        "pip_editable_requires_manifest",
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

        if "make_target_referenced_in_readme" in enabled:
            mentioned = {
                m.group(1).lower()
                for m in _MAKE_TARGET_RE.finditer(readme_text)
                if m.group(1).lower() not in _MAKE_STOPWORDS
            }
            if mentioned:
                actual = {t.lower() for t in _makefile_targets(ctx)}
                # Only fire when *some* Makefile exists; otherwise the
                # mention is documentation-only and a different rule
                # (entry_points / test_command) is the right channel.
                makefile_present = any(
                    (ctx.root / n).is_file()
                    for n in ("Makefile", "GNUmakefile", "makefile")
                )
                if makefile_present:
                    for target in sorted(mentioned - actual):
                        findings.append((
                            "README.md", None,
                            f"README references `make {target}` but no `{target}:` target exists in Makefile.",
                        ))

        if "package_json_script_referenced_in_readme" in enabled:
            mentioned = {
                m.group(1)
                for m in _NPM_RUN_RE.finditer(readme_text)
                if m.group(1).lower() not in _NPM_RUN_STOPWORDS
            }
            if mentioned:
                scripts = _package_json_scripts(ctx)
                if scripts is not None:
                    for script in sorted(mentioned - scripts):
                        findings.append((
                            "README.md", None,
                            f"README references `npm run {script}` but `scripts.{script}` is missing from package.json.",
                        ))

        if (
            "pip_editable_requires_manifest" in enabled
            and _PIP_EDITABLE_RE.search(readme_text)
            and not (ctx.root / "pyproject.toml").is_file()
            and not (ctx.root / "setup.py").is_file()
        ):
            findings.append((
                "README.md", None,
                "README documents `pip install -e .` but neither pyproject.toml nor setup.py exists.",
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
