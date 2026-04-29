"""Private matcher: ``ast_complexity``.

Uses ``lizard`` (optional dep) to compute cyclomatic complexity per
function. Fires per function whose CC exceeds ``max_cc``. Returns no
findings if lizard isn't installed — the evaluator turns no-findings
into a clean score, which is the right "we can't measure this here"
outcome.
"""

from __future__ import annotations

from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import register_private_matcher

_LANG_TO_SUFFIX = {
    "python": ".py",
    "javascript": ".js",
    "typescript": ".ts",
    "go": ".go",
    "java": ".java",
    "ruby": ".rb",
    "rust": ".rs",
    "c": ".c",
    "cpp": ".cpp",
    "csharp": ".cs",
    "php": ".php",
    "swift": ".swift",
    "kotlin": ".kt",
    "scala": ".scala",
}


def match_ast_complexity(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    try:
        import lizard  # type: ignore[import-not-found]
    except ImportError:
        # Lizard not installed; matcher silently produces no findings.
        # The evaluator's clean-score behaviour is the right "not
        # measured" surface for the OSS path.
        return []

    max_cc = int(cfg.get("max_cc", 15))
    top_n = int(cfg.get("top_n", 5))
    langs = cfg.get("languages") or list(_LANG_TO_SUFFIX.keys())
    suffixes = {_LANG_TO_SUFFIX[lang] for lang in langs if lang in _LANG_TO_SUFFIX}

    high_complexity: list[tuple[str, str, int]] = []  # (file, func, cc)
    for f in ctx._files:
        if f.suffix not in suffixes:
            continue
        try:
            file_info = lizard.analyze_file(str(ctx.root / f))
        except Exception:  # noqa: BLE001 — lizard parse errors are non-fatal
            continue
        for func in file_info.function_list:
            cc = func.cyclomatic_complexity
            if cc > max_cc:
                high_complexity.append((str(f), func.name, cc))

    high_complexity.sort(key=lambda x: x[2], reverse=True)
    return [
        (file, None, f"Function '{func}' has cyclomatic complexity {cc}.")
        for file, func, cc in high_complexity[:top_n]
    ]


register_private_matcher("ast_complexity", match_ast_complexity)
