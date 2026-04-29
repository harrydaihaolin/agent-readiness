"""Private matcher: ``regex_secret_scan``.

Multi-pattern, conservative-by-design secret scanner. Skips files
under any segment in ``exclude_path_segments`` (default test/example/
fixture/docs/sample/mock paths). One finding per matched pattern per
file is enough to make the point.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import register_private_matcher


# File suffixes worth scanning (text-ish). Keep this in sync with the
# original ``checks/secrets.py`` set.
_TEXT_SUFFIXES: frozenset[str] = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".rb", ".go", ".rs",
    ".java", ".kt", ".cs", ".php", ".swift", ".m", ".mm",
    ".sh", ".bash", ".zsh", ".fish",
    ".md", ".rst", ".txt", ".yml", ".yaml", ".toml", ".ini", ".cfg",
    ".env", ".dotenv", ".conf",
    ".json", ".xml", ".html", ".htm",
})

# Extensionless filenames that should still be scanned.
_NO_EXT_NAMES: frozenset[str] = frozenset({
    ".env", ".envrc", "Dockerfile", "Procfile", "Makefile",
})


def _is_scannable(rel: Path) -> bool:
    if rel.suffix.lower() in _TEXT_SUFFIXES:
        return True
    if rel.suffix == "" and rel.name in _NO_EXT_NAMES:
        return True
    return False


def _is_excluded_path(rel: Path, exclude_segments: tuple[str, ...]) -> bool:
    if not exclude_segments:
        return False
    parts_lower = [p.lower() for p in rel.parts]
    return any(seg in part for seg in exclude_segments for part in parts_lower)


def match_regex_secret_scan(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    raw_patterns = cfg.get("patterns") or []
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for entry in raw_patterns:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "secret"))
        pat = entry.get("regex")
        if not isinstance(pat, str):
            continue
        try:
            compiled.append((name, re.compile(pat)))
        except re.error:
            continue
    if not compiled:
        return []

    exclude_segments = tuple(cfg.get("exclude_path_segments") or ())
    max_bytes = int(cfg.get("max_bytes_per_file", 64_000))
    max_findings = int(cfg.get("max_findings", 50))

    findings: list[tuple[str | None, int | None, str]] = []
    for rel in ctx.files:
        if _is_excluded_path(rel, exclude_segments) or not _is_scannable(rel):
            continue
        text = ctx.read_text(rel, max_bytes=max_bytes)
        if text is None:
            continue
        for label, pattern in compiled:
            m = pattern.search(text)
            if m is None:
                continue
            line = text.count("\n", 0, m.start()) + 1
            findings.append((str(rel), line, f"Possible {label} found."))
            if len(findings) >= max_findings:
                return findings
            break  # one finding per file is enough
    return findings


register_private_matcher("regex_secret_scan", match_regex_secret_scan)
