"""Built-in OSS match types (file_size, path_glob, composite, …)."""

from __future__ import annotations

import fnmatch
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable

from agent_readiness.context import RepoContext

MatcherFn = Callable[[RepoContext, dict[str, Any]], list[tuple[str | None, int | None, str]]]


@lru_cache(maxsize=512)
def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    out = ["^"]
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                if i + 2 < len(pattern) and pattern[i + 2] == "/":
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
            continue
        if c == "?":
            out.append("[^/]")
            i += 1
            continue
        out.append(re.escape(c))
        i += 1
    out.append("$")
    return re.compile("".join(out))


def _matches_any_glob(rel: Path, patterns: Iterable[str]) -> bool:
    s = str(rel).replace("\\", "/")
    name = rel.name
    for pat in patterns:
        regex = _glob_to_regex(pat)
        if regex.match(s) or regex.match(name):
            return True
        if fnmatch.fnmatch(s, pat) or fnmatch.fnmatch(name, pat):
            return True
    return False


def match_file_size(ctx: RepoContext, cfg: dict[str, Any]) -> list[tuple[str | None, int | None, str]]:
    threshold_lines = int(cfg.get("threshold_lines", 500))
    threshold_bytes = int(cfg.get("threshold_bytes", 51_200))
    excludes = list(cfg.get("exclude_globs", []))

    findings: list[tuple[str | None, int | None, str]] = []
    for rel in ctx.files:
        if _matches_any_glob(rel, excludes):
            continue
        full = ctx.root / rel
        try:
            size = full.stat().st_size
        except OSError:
            continue
        if size <= threshold_bytes:
            if size < threshold_lines:
                continue
        if size > threshold_bytes:
            findings.append((str(rel), None, f"Large file: {rel} ({size:,} bytes > {threshold_bytes:,})"))
            continue
        text = ctx.read_text(rel, max_bytes=threshold_bytes * 2)
        if text is None:
            continue
        lines = text.count("\n") + 1
        if lines > threshold_lines:
            findings.append((str(rel), None, f"Large file: {rel} ({lines:,} lines > {threshold_lines:,})"))
    return findings


def match_path_glob(ctx: RepoContext, cfg: dict[str, Any]) -> list[tuple[str | None, int | None, str]]:
    require = list(cfg.get("require_globs", []))
    forbid = list(cfg.get("forbid_globs", []))
    findings: list[tuple[str | None, int | None, str]] = []

    if require:
        if not any(_matches_any_glob(rel, require) for rel in ctx.files):
            findings.append((None, None, f"None of these expected paths exist: {', '.join(require)}"))
    for rel in ctx.files:
        if forbid and _matches_any_glob(rel, forbid):
            findings.append((str(rel), None, f"Forbidden path present: {rel}"))
    return findings


def _walk_dotted(data: Any, dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        if part not in cur:
            return None
        cur = cur[part]
    return cur


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    name = path.name.lower()
    try:
        if name == "pyproject.toml":
            try:
                import tomllib
            except ImportError:
                return None
            return tomllib.loads(path.read_text())
        if name == "package.json":
            import json
            return json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return None


def match_manifest_field(ctx: RepoContext, cfg: dict[str, Any]) -> list[tuple[str | None, int | None, str]]:
    manifest_name = str(cfg["manifest"])
    field_path = str(cfg["field_path"])
    fire_when = cfg.get("fire_when", "missing")

    manifest = _load_manifest(ctx.root / manifest_name)
    if manifest is None:
        if fire_when == "missing":
            return [(manifest_name, None, f"Manifest {manifest_name} not present.")]
        return []
    value = _walk_dotted(manifest, field_path)
    present = value is not None and value != {} and value != []
    if fire_when == "missing" and not present:
        return [(manifest_name, None, f"{manifest_name}: '{field_path}' is missing or empty.")]
    if fire_when == "present" and present:
        return [(manifest_name, None, f"{manifest_name}: '{field_path}' is present (rule expected absent).")]
    return []


def match_regex_in_files(ctx: RepoContext, cfg: dict[str, Any]) -> list[tuple[str | None, int | None, str]]:
    pattern = re.compile(
        str(cfg["pattern"]),
        re.IGNORECASE if cfg.get("case_insensitive") else 0,
    )
    file_globs = list(cfg.get("file_globs", ["**/*"]))
    fire_when = cfg.get("fire_when", "match")
    findings: list[tuple[str | None, int | None, str]] = []

    matched_anywhere = False
    for rel in ctx.files:
        if not _matches_any_glob(rel, file_globs):
            continue
        text = ctx.read_text(rel)
        if text is None:
            continue
        m = pattern.search(text)
        if m:
            matched_anywhere = True
            if fire_when == "match":
                line = text[: m.start()].count("\n") + 1
                findings.append((str(rel), line, f"Pattern matched in {rel}"))
                if len(findings) >= 50:
                    break
    if fire_when == "no_match" and not matched_anywhere:
        findings.append((None, None, f"Expected pattern not found in any matching file ({', '.join(file_globs)})."))
    return findings


def match_command_in_makefile(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    target = str(cfg["target"])
    fire_when = cfg.get("fire_when", "missing")
    text = ctx.read_text("Makefile") or ctx.read_text("makefile")
    if text is None:
        if fire_when == "missing":
            return [("Makefile", None, "Makefile not present.")]
        return []
    pat = re.compile(rf"^{re.escape(target)}\s*:", re.MULTILINE)
    found = bool(pat.search(text))
    if fire_when == "missing" and not found:
        return [("Makefile", None, f"Makefile is missing target '{target}:'.")]
    if fire_when == "present" and found:
        return [("Makefile", None, f"Makefile target '{target}:' is present (rule expected absent).")]
    return []


_COMPOSITE_MAX_DEPTH = 4


def _registry() -> dict[str, MatcherFn]:
    from agent_readiness.rules_eval.matchers import OssMatchTypeRegistry
    return OssMatchTypeRegistry


def _eval_clause(
    clause: dict[str, Any], ctx: RepoContext, depth: int
) -> list[tuple[str | None, int | None, str]]:
    ctype = str(clause.get("type", ""))
    if ctype == "composite":
        return _match_composite(ctx, clause, depth=depth + 1)
    matcher = _registry().get(ctype)
    if matcher is None:
        return []
    return matcher(ctx, clause)


def _match_composite(
    ctx: RepoContext, cfg: dict[str, Any], depth: int = 0
) -> list[tuple[str | None, int | None, str]]:
    if depth > _COMPOSITE_MAX_DEPTH:
        return []
    op = str(cfg.get("op", "and")).lower()
    clauses = cfg.get("clauses") or []
    if not clauses:
        return []
    summary = cfg.get("summary")

    if op == "not":
        sub = _eval_clause(clauses[0], ctx, depth)
        if sub:
            return []
        msg = summary or "Composite NOT: expected absence, but found nothing required to fire."
        ctype = clauses[0].get("type", "?")
        return [(None, None, f"{msg} (clause type={ctype})")]

    sub_findings = [_eval_clause(c, ctx, depth) for c in clauses]
    if op == "and":
        if not all(sub for sub in sub_findings):
            return []
        msg = summary or "Composite AND fired: all clauses produced findings."
        return [(None, None, msg)]
    if op == "or":
        if any(not sub for sub in sub_findings):
            return []
        out: list[tuple[str | None, int | None, str]] = []
        for sub in sub_findings:
            if sub:
                out.append(sub[0])
        if summary:
            return [(None, None, f"{summary} (no clause matched)"), *out]
        return out
    return []


def match_composite(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    return _match_composite(ctx, cfg, depth=0)
