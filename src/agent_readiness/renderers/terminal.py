"""Terminal renderer.

Uses `rich` when available for nicer formatting; falls back to plain
text otherwise so the tool runs in environments without rich installed
(and keeps the stdout stable for piping). The plain-text path also
serves as our deterministic snapshot format.
"""

from __future__ import annotations

from agent_readiness.models import Pillar, Report, Severity


_PILLAR_LABEL = {
    Pillar.COGNITIVE_LOAD: "Cognitive load",
    Pillar.FEEDBACK:       "Feedback loops",
    Pillar.FLOW:           "Flow & reliability",
    Pillar.SAFETY:         "Safety",
}


def _bar(score: float, width: int = 20) -> str:
    """Tiny ASCII bar so the summary is scannable without colour."""
    filled = int(round(score / 100.0 * width))
    return "█" * filled + "·" * (width - filled)


def _top_friction(report: Report, n: int = 5) -> list[tuple[str, str, str, float]]:
    """Return up to *n* (check_id, pillar, message, score_impact) for the worst issues.

    A "friction" item is either:
      - a check with at least one WARN or ERROR finding (use the worst one), or
      - a check with no WARN+/ERROR findings but score < 60 (synthetic message).
    INFO findings on partial-credit checks are explicitly excluded — they
    describe the situation, not friction the maintainer should fix.

    Sort key: score_impact descending (highest potential gain first),
    then severity (error > warn > "low score, no findings") as tiebreaker,
    then (100 - score) descending.
    """
    sev_rank = {Severity.ERROR: 0, Severity.WARN: 1, Severity.INFO: 2}
    rows: list[tuple[float, int, float, str, str, str, float]] = []
    for ps in report.pillar_scores:
        for cr in ps.check_results:
            impact = cr.score_impact or 0.0
            actionable = [f for f in cr.findings
                          if f.severity in (Severity.WARN, Severity.ERROR)]
            if actionable:
                worst = min(actionable, key=lambda f: sev_rank[f.severity])
                rows.append((-impact, sev_rank[worst.severity], 100.0 - cr.score,
                             cr.check_id, _PILLAR_LABEL[cr.pillar],
                             worst.message, impact))
            elif cr.score < 60.0 and not cr.not_measured:
                rows.append((-impact, sev_rank[Severity.WARN] + 1,
                             100.0 - cr.score, cr.check_id,
                             _PILLAR_LABEL[cr.pillar],
                             f"score {cr.score:.0f}/100", impact))
    rows.sort(key=lambda r: (r[0], r[1], -r[2]))
    return [(check_id, pillar, msg, imp)
            for _, _, _, check_id, pillar, msg, imp in rows[:n]]


def render(report: Report, use_rich: bool | None = None) -> str:
    """Render the report as a string. If *use_rich* is None, autodetect."""
    if use_rich is None:
        try:
            import rich  # noqa: F401
            use_rich = True
        except ImportError:
            use_rich = False

    return _render_rich(report) if use_rich else _render_plain(report)


def _render_plain(report: Report) -> str:
    lines: list[str] = []
    lines.append(f"AI Readiness  {report.overall_score:>5.1f} / 100")
    if report.safety_cap_applied:
        lines.append(f"  (safety cap took off {report.safety_cap_applied:.1f} points)")
    lines.append("")
    for ps in report.pillar_scores:
        label = _PILLAR_LABEL[ps.pillar]
        lines.append(f"  {label:<20s} {ps.score:>5.1f}  {_bar(ps.score)}")
    lines.append("")
    friction = _top_friction(report)
    if friction:
        lines.append("Top friction (fix these first):")
        for i, (check_id, pillar, msg, impact) in enumerate(friction, start=1):
            suffix = f"  (+{impact:.1f} pts)" if impact > 0 else ""
            lines.append(f"  {i}. {check_id} — {msg}{suffix}")
    else:
        lines.append("No findings. Looking good.")
    return "\n".join(lines)


def _render_rich(report: Report) -> str:
    """Same content as _render_plain but rendered via rich for colour/box."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    import io

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, color_system="truecolor",
                      width=88)

    overall_text = Text()
    overall_text.append("AI Readiness  ", style="bold")
    overall_text.append(f"{report.overall_score:.1f} / 100",
                        style=_score_style(report.overall_score))
    if report.safety_cap_applied:
        overall_text.append(
            f"   (safety cap took {report.safety_cap_applied:.1f} pts)",
            style="dim red",
        )
    console.print(Panel(overall_text, expand=False, padding=(0, 2)))

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("pillar", justify="left", no_wrap=True)
    table.add_column("score", justify="right")
    table.add_column("bar")
    for ps in report.pillar_scores:
        table.add_row(
            _PILLAR_LABEL[ps.pillar],
            Text(f"{ps.score:.1f}", style=_score_style(ps.score)),
            Text(_bar(ps.score), style="dim"),
        )
    console.print(table)

    friction = _top_friction(report)
    if friction:
        console.print()
        console.print("[bold]Top friction (fix these first):[/bold]")
        for i, (check_id, _, msg, impact) in enumerate(friction, start=1):
            suffix = f"  [dim](+{impact:.1f} pts)[/dim]" if impact > 0 else ""
            console.print(f"  [bold]{i}.[/bold] [cyan]{check_id}[/cyan] — {msg}{suffix}")
    else:
        console.print("\n[green]No findings. Looking good.[/green]")
    return buf.getvalue()


def _score_style(score: float) -> str:
    if score >= 80:
        return "green"
    if score >= 60:
        return "yellow"
    return "red"
