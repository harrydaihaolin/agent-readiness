"""Check: test_command.discoverable

Without running anything, can an agent figure out *the* command to run
the test suite? This is a Feedback-pillar prerequisite: even the best
test suite is invisible if the agent has to guess `pytest` vs
`python -m unittest` vs `make ci` vs `npm test`.

Detection priority (matches what a competent agent would try):
1. Makefile with a `test:` target
2. package.json with scripts.test
3. pyproject.toml with [tool.pytest.ini_options] or a [project.scripts]
   test entry; or a setup.cfg [tool:pytest]; or a pytest.ini
4. Cargo.toml present (cargo test is conventional)
5. go.mod present (go test ./... is conventional)
6. Gemfile + a Rakefile with a 'test' task
7. scripts/test or scripts/test.sh

Scoring:
- Found in 1..3:                                 100  (canonical)
- Found in 4..6 (convention, not declaration):    80
- Found only in 7 (custom script):                70
- Nothing found:                                   0
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


@dataclass
class _Match:
    where: str            # human description, e.g. "Makefile target 'test'"
    file: str             # repo-relative path
    score: float          # contribution to the check
    command: str | None   # the actual invocation, when knowable


def _check_makefile(ctx: RepoContext) -> _Match | None:
    text = ctx.read_text("Makefile")
    if text is None:
        return None
    # Match a line that begins a make target named test (with optional deps).
    if re.search(r"(?m)^test\s*:", text):
        return _Match("Makefile target 'test'", "Makefile", 100.0, "make test")
    # Also accept common aliases
    for alias in ("tests", "test-all", "check", "ci", "verify"):
        if re.search(rf"(?m)^{alias}\s*:", text):
            return _Match(f"Makefile target '{alias}'", "Makefile", 100.0, f"make {alias}")
    return None


def _check_package_json(ctx: RepoContext) -> _Match | None:
    text = ctx.read_text("package.json")
    if text is None:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    scripts = data.get("scripts") or {}
    if isinstance(scripts, dict) and isinstance(scripts.get("test"), str):
        return _Match("package.json scripts.test", "package.json",
                      100.0, "npm test")
    return None


def _check_pyproject(ctx: RepoContext) -> _Match | None:
    text = ctx.read_text("pyproject.toml")
    if text is None:
        return None
    # Avoid pulling tomllib import cost just for substring checks.
    if ("[tool.pytest.ini_options]" in text
            or re.search(r"(?m)^\[tool\.pytest", text)):
        return _Match("pyproject.toml [tool.pytest.ini_options]",
                      "pyproject.toml", 100.0, "pytest")
    return None


def _check_pytest_ini(ctx: RepoContext) -> _Match | None:
    if ctx.has_file("pytest.ini"):
        return _Match("pytest.ini", "pytest.ini", 100.0, "pytest")
    if ctx.has_file("setup.cfg"):
        text = ctx.read_text("setup.cfg") or ""
        if "[tool:pytest]" in text:
            return _Match("setup.cfg [tool:pytest]", "setup.cfg",
                          100.0, "pytest")
    return None


def _check_cargo(ctx: RepoContext) -> _Match | None:
    if ctx.has_file("Cargo.toml"):
        return _Match("Cargo.toml (cargo test convention)", "Cargo.toml",
                      80.0, "cargo test")
    return None


def _check_go_mod(ctx: RepoContext) -> _Match | None:
    if ctx.has_file("go.mod"):
        return _Match("go.mod (go test convention)", "go.mod",
                      80.0, "go test ./...")
    return None


def _check_gemfile_rakefile(ctx: RepoContext) -> _Match | None:
    if not ctx.has_file("Gemfile"):
        return None
    rake = ctx.read_text("Rakefile") or ""
    if "task :test" in rake or "Rake::TestTask" in rake:
        return _Match("Gemfile + Rakefile test task", "Rakefile",
                      80.0, "rake test")
    return None


def _check_tox(ctx: RepoContext) -> _Match | None:
    if ctx.has_file("tox.ini"):
        return _Match("tox.ini", "tox.ini", 100.0, "tox")
    return None


def _check_nox(ctx: RepoContext) -> _Match | None:
    if ctx.has_file("noxfile.py"):
        return _Match("noxfile.py", "noxfile.py", 100.0, "nox")
    return None


def _check_hatch(ctx: RepoContext) -> _Match | None:
    if ctx.has_file("hatch.toml"):
        return _Match("hatch.toml", "hatch.toml", 80.0, "hatch test")
    pyproject = ctx.read_text("pyproject.toml")
    if pyproject and "[tool.hatch.envs" in pyproject:
        return _Match("pyproject.toml [tool.hatch.envs]", "pyproject.toml",
                      80.0, "hatch test")
    return None


def _check_justfile(ctx: RepoContext) -> _Match | None:
    for name in ("Justfile", "justfile"):
        text = ctx.read_text(name)
        if text and re.search(r"(?m)^test\b", text):
            return _Match(f"{name} recipe 'test'", name, 80.0, "just test")
    return None


def _check_cmake(ctx: RepoContext) -> _Match | None:
    if ctx.has_file("CMakeLists.txt"):
        return _Match("CMakeLists.txt (CTest convention)", "CMakeLists.txt",
                      80.0, "ctest")
    return None


def _check_maven(ctx: RepoContext) -> _Match | None:
    if ctx.has_file("pom.xml"):
        return _Match("pom.xml (mvn test convention)", "pom.xml",
                      80.0, "mvn test")
    return None


def _check_gradle(ctx: RepoContext) -> _Match | None:
    for name in ("build.gradle", "build.gradle.kts"):
        if ctx.has_file(name):
            return _Match(f"{name} (Gradle test convention)", name,
                          80.0, "./gradlew test")
    return None


def _check_mix(ctx: RepoContext) -> _Match | None:
    if ctx.has_file("mix.exs"):
        return _Match("mix.exs (mix test convention)", "mix.exs",
                      80.0, "mix test")
    return None


def _check_sbt(ctx: RepoContext) -> _Match | None:
    if ctx.has_file("build.sbt"):
        return _Match("build.sbt (sbt test convention)", "build.sbt",
                      80.0, "sbt test")
    return None


def _check_conftest(ctx: RepoContext) -> _Match | None:
    """Root-level conftest.py is a strong pytest signal even without explicit config."""
    if ctx.has_file("conftest.py"):
        return _Match("conftest.py (pytest fixture root)", "conftest.py",
                      80.0, "pytest")
    return None


def _check_scripts_test(ctx: RepoContext) -> _Match | None:
    for name in (
        "scripts/test", "scripts/test.sh", "scripts/run_tests.sh",
        "scripts/test-all.sh", "scripts/ci.sh",
        "bin/test", "bin/ci",
        "ci/test.sh", "ci/run_tests.sh",
    ):
        if (ctx.root / name).is_file():
            return _Match(f"{name} (custom script)", name, 70.0,
                          f"./{name}")
    return None


_DETECTORS = (
    _check_makefile,
    _check_package_json,
    _check_pyproject,
    _check_pytest_ini,
    _check_tox,
    _check_nox,
    _check_hatch,
    _check_cargo,
    _check_go_mod,
    _check_maven,
    _check_gradle,
    _check_mix,
    _check_sbt,
    _check_gemfile_rakefile,
    _check_justfile,
    _check_cmake,
    _check_conftest,
    _check_scripts_test,
)


@register(
    check_id="test_command.discoverable",
    pillar=Pillar.FEEDBACK,
    title="A test invocation is statically discoverable",
    explanation="""
    The Feedback pillar's whole premise is that fast clear test feedback
    is what lets an agent self-correct. That breaks immediately if the
    agent doesn't know which command to run. We look for an explicit
    declaration first (Makefile / package.json / pyproject), then for
    ecosystem conventions (Cargo, go.mod), then for repo-local custom
    scripts. Anything is better than nothing.
    """,
)
def check(ctx: RepoContext) -> CheckResult:
    matches: list[_Match] = []
    for detector in _DETECTORS:
        m = detector(ctx)
        if m is not None:
            matches.append(m)

    if not matches:
        return CheckResult(
            check_id="test_command.discoverable",
            pillar=Pillar.FEEDBACK,
            score=0.0,
            findings=[Finding(
                check_id="test_command.discoverable",
                pillar=Pillar.FEEDBACK,
                severity=Severity.WARN,
                message="No test invocation discoverable from manifests, "
                        "Makefile, or scripts/.",
                fix_hint=("Add a 'test' target to your Makefile, a 'test' "
                          "script to package.json, or a [tool.pytest.ini_options] "
                          "section to pyproject.toml."),
            )],
        )

    # Pick the highest-confidence match.
    best = max(matches, key=lambda m: m.score)
    detail = best.where + (f"  (run with: `{best.command}`)" if best.command else "")
    return CheckResult(
        check_id="test_command.discoverable",
        pillar=Pillar.FEEDBACK,
        score=best.score,
        findings=[Finding(
            check_id="test_command.discoverable",
            pillar=Pillar.FEEDBACK,
            severity=Severity.INFO,
            file=best.file,
            message=f"Test command: {detail}",
        )],
    )
