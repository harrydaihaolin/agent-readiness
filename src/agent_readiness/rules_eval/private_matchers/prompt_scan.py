"""Private matcher: ``prompt_scan``.

Two YAML modes operating on README-shaped prose:
- ``mode: readme_run_instructions`` — fires when README is missing OR
  is missing any of the requested signals (install / run / test) OR
  is missing fenced code when ``require_fenced_code: true``. Used by
  ``readme.has_run_instructions``.
- ``mode: headless_setup`` — fires per GUI-gating or OAuth phrase
  found in the README's setup-shaped section. Used by
  ``headless.no_setup_prompts``.
"""

from __future__ import annotations

import re
from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import register_private_matcher

_README_NAMES = (
    "README.md", "README.rst", "README.txt", "README", "README.markdown",
    "readme.md", "Readme.md",
)
_FENCE_RE = re.compile(r"```|~~~")
_INSTALL_RE = re.compile(
    r"\b(install(ation)?|setup|set[-\s]up|getting started|prerequisite|"
    r"requirement|dependency|dependencies|before you (begin|start))\b",
    re.I,
)
_RUN_RE = re.compile(
    r"\b(run|usage|quick ?start|how to use|example|examples|demo|"
    r"start|getting going|try it)\b",
    re.I,
)
_TEST_RE = re.compile(r"\btest(s|ing|suite)?\b|\bci\b|\bcoverage\b", re.I)
_SETUP_HEADINGS = re.compile(
    r"(?im)^\s*#{1,6}\s*(install(ation)?|setup|getting started|quick ?start)\b.*$"
)
_NEXT_HEADING = re.compile(r"(?m)^\s*#{1,6}\s+\S")


def _find_readme(ctx: RepoContext) -> tuple[str, str] | None:
    for name in _README_NAMES:
        text = ctx.read_text(name)
        if text is not None:
            return name, text
    return None


def _readme_run_instructions_mode(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    signals = set(cfg.get("signals") or ["install", "run", "test"])
    require_fenced = bool(cfg.get("require_fenced_code", True))

    found = _find_readme(ctx)
    if found is None:
        return [(None, None, "No README found at repo root.")]
    name, text = found

    findings: list[tuple[str | None, int | None, str]] = []
    sig_results = {
        "install": bool(_INSTALL_RE.search(text)),
        "run":     bool(_RUN_RE.search(text)),
        "test":    bool(_TEST_RE.search(text)),
    }
    missing_signals = sorted(s for s in signals if not sig_results.get(s, False))
    if missing_signals:
        findings.append((
            name, None,
            f"README is missing signals for: {', '.join(missing_signals)}.",
        ))
    if require_fenced and not _FENCE_RE.search(text):
        findings.append((
            name, None,
            "README has no fenced code blocks (agents cannot copy commands verbatim).",
        ))
    return findings


def _extract_setup_section(text: str) -> str:
    m = _SETUP_HEADINGS.search(text)
    if m is None:
        return text[:4000]
    start = m.end()
    nh = _NEXT_HEADING.search(text, pos=start)
    end = nh.start() if nh else len(text)
    return text[start:end]


def _headless_setup_mode(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    found = _find_readme(ctx)
    if found is None:
        return []  # readme.has_run_instructions covers the missing-README case
    name, text = found
    section = _extract_setup_section(text)

    gui_phrases = tuple(cfg.get("gui_phrases") or ())
    oauth_phrases = tuple(cfg.get("oauth_phrases") or ())

    findings: list[tuple[str | None, int | None, str]] = []
    lower = section.lower()
    for phrase in gui_phrases:
        if phrase.lower() in lower:
            findings.append((name, None, f"Setup mentions a GUI step: '{phrase}'."))
    for phrase in oauth_phrases:
        if phrase.lower() in lower:
            findings.append((name, None, f"Setup mentions browser-mediated auth: '{phrase}'."))
    return findings


def match_prompt_scan(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    mode = str(cfg.get("mode", ""))
    if mode == "readme_run_instructions":
        return _readme_run_instructions_mode(ctx, cfg)
    if mode == "headless_setup":
        return _headless_setup_mode(ctx, cfg)
    return []


register_private_matcher("prompt_scan", match_prompt_scan)
