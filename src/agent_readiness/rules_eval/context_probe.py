"""Context-probe runner for rules_version=2 actions (EXP-3).

When a rule declares ``action.context_probe: [{detect: <kind>}, ...]``, the
engine resolves each probe at scan time and substitutes the result into
``action.template`` placeholders. The probes are deterministic (no LLM in
the action path) and degrade gracefully — a probe that can't resolve emits
an empty string so the template still renders.

Supported probe kinds (matched 1:1 with
``agent_readiness_insights_protocol.ContextProbeKind``):

  primary_language       — coarse language pick from manifest extensions
                           and file-extension counts
  primary_manifest       — first manifest file present from a fixed
                           priority order (pyproject.toml, package.json,
                           Cargo.toml, go.mod, ...)
  package_manager        — package-manager guess derived from lockfile
                           presence (pnpm-lock.yaml -> pnpm, ...)
  makefile_targets       — comma-separated list of `^target:` declarations
                           in Makefile (best-effort regex; ignores phony
                           variants and blank lines)
  existing_entry_points  — entry-point names parsed from pyproject.toml
                           [project.scripts] or package.json `bin`
  test_directory         — first present of tests/, test/, __tests__/
  ci_present             — "true" / "false"
  lockfile_present       — "true" / "false"

Derived variables (filled in addition to the raw probe outputs so action
templates stay short and readable):

  language_test_command  — language-conventional "make-test" body string
  language_lint_command  — same, for lint
  language_install_cmd   — same, for install

Templates use a defaulting ``str.format``-style substitution: missing
keys render as the empty string rather than raising a KeyError. This
guarantees every Finding's ``action.template`` is a literal command-
or-content string at emit time, never a raw ``{variable}``.
"""

from __future__ import annotations

import logging
import re
import string
from typing import Any

from agent_readiness.context import RepoContext

logger = logging.getLogger(__name__)


# ---------- Language and manifest tables -----------------------------------


_LANGUAGE_BY_MANIFEST = (
    ("pyproject.toml", "python"),
    ("setup.py", "python"),
    ("setup.cfg", "python"),
    ("requirements.txt", "python"),
    ("package.json", "javascript"),
    ("tsconfig.json", "typescript"),
    ("Cargo.toml", "rust"),
    ("go.mod", "go"),
    ("Gemfile", "ruby"),
    ("composer.json", "php"),
    ("pom.xml", "java"),
    ("build.gradle", "java"),
    ("build.gradle.kts", "kotlin"),
    ("Package.swift", "swift"),
    ("mix.exs", "elixir"),
    ("project.clj", "clojure"),
)

# Priority order for primary_manifest. Python's pyproject is the modern
# canonical so it wins over setup.py / requirements.txt when both exist.
_MANIFEST_PRIORITY = [m for m, _ in _LANGUAGE_BY_MANIFEST]


_LANGUAGE_TEST_COMMAND = {
    "python": "python -m pytest tests/",
    "javascript": "npm test",
    "typescript": "npm test",
    "go": "go test ./...",
    "rust": "cargo test",
    "ruby": "bundle exec rspec",
    "java": "mvn test",
    "kotlin": "./gradlew test",
    "swift": "swift test",
    "elixir": "mix test",
}

_LANGUAGE_LINT_COMMAND = {
    "python": "ruff check .",
    "javascript": "npm run lint",
    "typescript": "npm run lint",
    "go": "go vet ./...",
    "rust": "cargo clippy",
    "ruby": "bundle exec rubocop",
    "java": "mvn checkstyle:check",
}

_LANGUAGE_INSTALL_COMMAND = {
    "python": "pip install -e .",
    "javascript": "npm install",
    "typescript": "npm install",
    "go": "go mod download",
    "rust": "cargo build",
    "ruby": "bundle install",
    "java": "mvn install",
}


_LOCKFILE_PACKAGE_MANAGER = (
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("bun.lock", "bun"),
    ("bun.lockb", "bun"),
    ("package-lock.json", "npm"),
    ("uv.lock", "uv"),
    ("poetry.lock", "poetry"),
    ("Pipfile.lock", "pipenv"),
    ("Cargo.lock", "cargo"),
    ("go.sum", "go"),
    ("Gemfile.lock", "bundler"),
    ("composer.lock", "composer"),
)


# ---------- Probe runners --------------------------------------------------


def _detect_primary_manifest(ctx: RepoContext) -> str:
    for m in _MANIFEST_PRIORITY:
        if (ctx.root / m).is_file():
            return m
    return ""


def _detect_primary_language(ctx: RepoContext) -> str:
    """Best-effort language pick.

    Manifest hits are stronger than file-extension counts because they
    are explicit declarations of intent; ext-count is only used to break
    ties when no manifest is present (e.g. a vendored Python script
    repo with no pyproject).
    """
    for manifest, lang in _LANGUAGE_BY_MANIFEST:
        if (ctx.root / manifest).is_file():
            return lang
    # Fall back to file-extension scan.
    counts: dict[str, int] = {}
    for ext_lang in (
        ("py", "python"),
        ("js", "javascript"),
        ("ts", "typescript"),
        ("go", "go"),
        ("rs", "rust"),
        ("rb", "ruby"),
        ("java", "java"),
    ):
        counts[ext_lang[1]] = counts.get(ext_lang[1], 0) + sum(
            1 for _ in ctx.root.rglob(f"*.{ext_lang[0]}")
        )
    if not any(counts.values()):
        return ""
    return max(counts, key=lambda k: counts[k])


def _detect_package_manager(ctx: RepoContext) -> str:
    for lock, pm in _LOCKFILE_PACKAGE_MANAGER:
        if (ctx.root / lock).is_file():
            return pm
    return ""


_MAKEFILE_TARGET_RE = re.compile(
    r"^([a-zA-Z_][a-zA-Z0-9_-]*)\s*:(?!=)", re.MULTILINE
)


def _detect_makefile_targets(ctx: RepoContext) -> str:
    mf = ctx.root / "Makefile"
    if not mf.is_file():
        return ""
    try:
        text = mf.read_text(errors="ignore")
    except OSError:
        return ""
    targets = []
    for m in _MAKEFILE_TARGET_RE.finditer(text):
        t = m.group(1)
        if t and t not in {".PHONY", ".SUFFIXES"} and t not in targets:
            targets.append(t)
    return ", ".join(targets)


def _detect_existing_entry_points(ctx: RepoContext) -> str:
    # pyproject [project.scripts]
    pyproj = ctx.root / "pyproject.toml"
    if pyproj.is_file():
        try:
            text = pyproj.read_text(errors="ignore")
        except OSError:
            text = ""
        m = re.search(r"\[project\.scripts\]\s*\n([^[]*)", text)
        if m:
            names = re.findall(r"^\s*([a-zA-Z0-9_\-]+)\s*=", m.group(1), re.MULTILINE)
            if names:
                return ", ".join(names)
    # package.json bin
    pkg = ctx.root / "package.json"
    if pkg.is_file():
        try:
            text = pkg.read_text(errors="ignore")
        except OSError:
            text = ""
        m = re.search(r'"bin"\s*:\s*\{([^}]*)\}', text)
        if m:
            names = re.findall(r'"([^"]+)"\s*:', m.group(1))
            if names:
                return ", ".join(names)
        m = re.search(r'"bin"\s*:\s*"([^"]+)"', text)
        if m:
            return m.group(1)
    return ""


def _detect_test_directory(ctx: RepoContext) -> str:
    for d in ("tests", "test", "__tests__", "spec"):
        if (ctx.root / d).is_dir():
            return d + "/"
    return ""


def _detect_ci_present(ctx: RepoContext) -> str:
    if (ctx.root / ".github" / "workflows").is_dir():
        return "true"
    if (ctx.root / ".circleci" / "config.yml").is_file():
        return "true"
    if (ctx.root / ".gitlab-ci.yml").is_file():
        return "true"
    return "false"


def _detect_lockfile_present(ctx: RepoContext) -> str:
    return "true" if any((ctx.root / lock).is_file() for lock, _ in _LOCKFILE_PACKAGE_MANAGER) else "false"


_PROBES = {
    "primary_language": _detect_primary_language,
    "primary_manifest": _detect_primary_manifest,
    "package_manager": _detect_package_manager,
    "makefile_targets": _detect_makefile_targets,
    "existing_entry_points": _detect_existing_entry_points,
    "test_directory": _detect_test_directory,
    "ci_present": _detect_ci_present,
    "lockfile_present": _detect_lockfile_present,
}


def run_probes(probes: list[dict[str, Any]] | None, ctx: RepoContext) -> dict[str, str]:
    """Resolve every probe declared on an action. Unknown kinds are
    silently dropped (the schema validates kinds at load time, so the
    only way an unknown kind reaches the engine is a forward-compat
    rule with a probe a newer engine adds; degrade gracefully).
    """
    out: dict[str, str] = {}
    if not probes:
        return out
    for p in probes:
        kind = p.get("detect") if isinstance(p, dict) else None
        if not kind:
            continue
        runner = _PROBES.get(str(kind))
        if runner is None:
            logger.debug("context_probe: unknown detect=%r; skipping", kind)
            continue
        try:
            out[str(kind)] = runner(ctx) or ""
        except Exception:  # noqa: BLE001 - probes are best-effort, never fatal
            logger.debug("context_probe %s raised; using empty string", kind, exc_info=True)
            out[str(kind)] = ""

    # Synthesise derived variables. Templates that reference these
    # without a corresponding probe still get the empty string.
    if "primary_language" in out:
        lang = out["primary_language"]
        out.setdefault("language_test_command", _LANGUAGE_TEST_COMMAND.get(lang, ""))
        out.setdefault("language_lint_command", _LANGUAGE_LINT_COMMAND.get(lang, ""))
        out.setdefault("language_install_command", _LANGUAGE_INSTALL_COMMAND.get(lang, ""))
    return out


# ---------- Template rendering ---------------------------------------------


class _DefaultingDict(dict):
    """str.format-style mapping that maps missing keys to the empty
    string instead of raising. Keeps action templates renderable even
    when a probe didn't resolve."""

    def __missing__(self, key: str) -> str:  # type: ignore[override]
        return ""


def render_action(action: dict[str, Any] | None, vars: dict[str, str]) -> dict[str, Any] | None:
    """Substitute ``{variable}`` placeholders in template-bearing string
    fields of an action dict. Returns a *new* dict (does not mutate the
    rule's action). If ``action`` is None or has no string template
    field, returns it unchanged.
    """
    if not isinstance(action, dict) or not vars:
        return action
    out = dict(action)
    formatter = string.Formatter()
    mapping = _DefaultingDict(vars)
    for key in ("template", "command", "value"):
        v = out.get(key)
        if isinstance(v, str) and "{" in v:
            try:
                out[key] = formatter.vformat(v, (), mapping)
            except (IndexError, ValueError):
                # Bad template (e.g. unbalanced brace). Leave untouched
                # so downstream debugging surfaces the original string.
                logger.debug("template render failed on key %s; leaving raw", key, exc_info=True)
    return out
