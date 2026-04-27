"""Check: headless.no_setup_prompts

The headless-first design principle (RUBRIC.md) says: agents have stdin /
stdout / files / git / HTTP and nothing else. If setup gates on a
human-only step — clicking through a wizard, signing into a dashboard,
authorising an OAuth flow in a browser — the agent stalls.

This check reads README + common setup-script entry points and looks for
language that implies a TTY-only / GUI-only step. It's a heuristic; we
err toward false negatives (don't flag) over false positives (flag a
fine repo) so users trust the score.

Scoring:
- Setup-adjacent prose contains UI gating language:           30
- Setup-adjacent prose mentions browser auth (oauth/login):   60
- Looks clean (no flagged language found):                   100

We also reward presence of a non-interactive setup script
(scripts/setup, scripts/bootstrap, etc.) by adding +0 (it's the
expected baseline) but emit an INFO finding when present so the user
sees we noticed.
"""

from __future__ import annotations

import re

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


# Phrases that strongly imply a human-in-the-loop GUI step.
_GUI_GATE_PATTERNS = [
    re.compile(r"\bclick (the |on )?(.{0,40}?)button\b", re.I),
    re.compile(r"\bopen the dashboard\b", re.I),
    re.compile(r"\bin the (admin )?dashboard\b", re.I),
    re.compile(r"\bvisit the (web )?(ui|console|portal)\b", re.I),
    re.compile(r"\bsetup wizard\b", re.I),
    re.compile(r"\b(go|navigate) to (https?://\S+) (and|to) (click|sign)\b", re.I),
]

# Phrases that imply browser-mediated auth (oauth flows, etc.).
_BROWSER_AUTH_PATTERNS = [
    re.compile(r"\boauth (login|flow|consent)\b", re.I),
    re.compile(r"\bsign in (via|through) (the|your) browser\b", re.I),
    re.compile(r"\blog in (to|on) (https?://|the website)\b", re.I),
    re.compile(r"\bauthorize (the )?app(lication)? in (the )?browser\b", re.I),
]

# Files we read, in order, to find setup-adjacent prose. We deliberately
# don't grep the whole README — false positives would tank scores. We
# look for a setup-shaped section first.
_SETUP_HEADINGS = re.compile(
    r"(?im)^\s*#{1,6}\s*(install(ation)?|setup|getting started|quick ?start)\b.*$"
)
_NEXT_HEADING = re.compile(r"(?m)^\s*#{1,6}\s+\S")

_SETUP_SCRIPT_CANDIDATES = (
    "scripts/setup", "scripts/setup.sh", "scripts/bootstrap",
    "scripts/bootstrap.sh", "bin/setup", "bin/bootstrap",
)


def _extract_setup_section(text: str) -> str:
    """Return the substring under the first install/setup-shaped heading.

    If no heading found, return the first 4000 chars (better than nothing,
    since some READMEs are flat).
    """
    m = _SETUP_HEADINGS.search(text)
    if m is None:
        return text[:4000]
    start = m.end()
    next_heading = _NEXT_HEADING.search(text, pos=start)
    end = next_heading.start() if next_heading else len(text)
    return text[start:end]


@register(
    check_id="headless.no_setup_prompts",
    pillar=Pillar.FLOW,
    title="Setup is reachable headlessly",
    explanation="""
    Direct application of the headless-first principle: if the documented
    install / setup path tells a human to click a button, sign into a
    dashboard, or authorise an OAuth flow in a browser, an agent can't
    traverse it. We scan setup-shaped sections of the README for UI
    gating language. Heuristic and conservative — we'd rather miss a
    real issue than flag a clean repo.
    """,
)
def check(ctx: RepoContext) -> CheckResult:
    findings: list[Finding] = []

    # Collect setup-adjacent prose.
    sources: list[tuple[str, str]] = []  # (label, text)
    for readme_name in ("README.md", "README.rst", "README.txt", "README"):
        path = ctx.has_file(readme_name)
        if path is not None:
            text = ctx.read_text(path)
            if text:
                sources.append((str(path), _extract_setup_section(text)))
            break  # only one README

    # If a setup script exists, that's evidence of headless intent — note it.
    setup_script = next(
        (s for s in _SETUP_SCRIPT_CANDIDATES if (ctx.root / s).is_file()),
        None,
    )
    if setup_script:
        findings.append(Finding(
            check_id="headless.no_setup_prompts",
            pillar=Pillar.FLOW,
            severity=Severity.INFO,
            file=setup_script,
            message=f"Found non-interactive setup script: {setup_script}.",
        ))

    if not sources:
        # No README means we can't make a positive judgement. Don't punish
        # twice — readme.has_run_instructions already handles README absence.
        return CheckResult(
            check_id="headless.no_setup_prompts",
            pillar=Pillar.FLOW,
            score=70.0,  # neutral-leaning; no evidence either way
            findings=findings + [Finding(
                check_id="headless.no_setup_prompts",
                pillar=Pillar.FLOW,
                severity=Severity.INFO,
                message="No README to inspect for setup-prompt language.",
            )],
        )

    score = 100.0
    for label, text in sources:
        for pat in _GUI_GATE_PATTERNS:
            m = pat.search(text)
            if m:
                score = min(score, 30.0)
                findings.append(Finding(
                    check_id="headless.no_setup_prompts",
                    pillar=Pillar.FLOW,
                    severity=Severity.WARN,
                    file=label,
                    message=f"Setup mentions a GUI step: '{m.group(0)}'.",
                    fix_hint=("Provide a CLI / API / file-based equivalent "
                              "for any UI-gated setup step."),
                ))
        for pat in _BROWSER_AUTH_PATTERNS:
            m = pat.search(text)
            if m:
                score = min(score, 60.0)
                findings.append(Finding(
                    check_id="headless.no_setup_prompts",
                    pillar=Pillar.FLOW,
                    severity=Severity.WARN,
                    file=label,
                    message=f"Setup mentions browser-mediated auth: '{m.group(0)}'.",
                    fix_hint=("Document a non-interactive credential path "
                              "(env var, service account, .env file) for agents."),
                ))

    return CheckResult(
        check_id="headless.no_setup_prompts",
        pillar=Pillar.FLOW,
        score=score,
        findings=findings,
    )
