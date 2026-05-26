"""Apply a single structured ``top_action`` to a repository in-place.

This module is the executor side of the EXP-4 "Top Action Pin" contract:
``agent_readiness.scorer.compute_top_action`` returns a JSON-shaped dict
describing one structured fix; this module materialises that fix in the
working copy and (optionally) runs the rule's ``verify`` command so the
caller can confirm the rule no longer fires.

The contract is intentionally narrow:

- One action at a time.
- Action handlers are pure functions ``action_dict -> list[str]``
  returning the repo-relative paths they touched.
- A path-escape guard refuses any handler that would write outside the
  repo root.
- Errors never raise out of ``apply_top_action``; they're returned in
  the ``ApplyResult`` envelope so MCP / dogfood callers can render
  them.

Consumers:

- ``agent_readiness.cli``: ``scan --apply-top-action [--verify]``.
- ``agent_readiness_mcp.server``: the ``apply_top_action`` MCP tool.
- ``agent-readiness-action`` / ``agent-readiness-pro``'s dogfood
  workflows.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - 3.11 is the floor declared in pyproject.toml
    raise RuntimeError(
        "agent_readiness.apply_action requires Python 3.11+ for tomllib"
    )

logger = logging.getLogger(__name__)

__all__ = ["ApplyResult", "apply_top_action"]


# ---------------------------------------------------------------------------
# Public envelope
# ---------------------------------------------------------------------------


@dataclass
class ApplyResult:
    """Outcome envelope returned by :func:`apply_top_action`.

    Attributes
    ----------
    applied:
        ``True`` if the handler ran to completion and wrote (or
        intentionally no-op'd) the target files. ``False`` if the
        action was skipped (no structured action available, unknown
        kind) or raised.
    written:
        Repo-relative paths the handler touched. Empty when the
        handler intentionally no-ops (``edit_gitignore`` with all
        entries already present, ``run_command`` whose side effects
        live outside the path tree we track).
    verified:
        ``True``/``False`` when ``run_verify`` was on and the rule
        ships a verify block; ``None`` otherwise.
    verify:
        Structured record of the verify subprocess: command, exit
        code, stdout/stderr tails. ``None`` if verify was skipped.
    skipped_reason:
        Set when ``applied=False`` because there was nothing to do
        (no top action, no structured action, etc.). Distinct from
        ``error``: a skip is benign, an error is not.
    error:
        ``"ExcClass: message"`` when a handler raised. The handler
        does NOT half-write: callers can safely retry or revert via
        git.
    """

    applied: bool
    written: list[str] = field(default_factory=list)
    verified: bool | None = None
    verify: dict[str, Any] | None = None
    skipped_reason: str | None = None
    error: str | None = None
    confirm_required: bool = False
    """Set when the top action's rule has ``confidence == "medium"``.

    The engine refuses to mutate; the MCP layer's ``confirm_apply``
    tool is meant to pick up from this envelope, ask the user, and
    either re-invoke ``apply_top_action`` with the rule confidence
    overridden to ``high`` (approved) or record a Gap (rejected).
    Added in agent-readiness v3.2.0.
    """
    gap_payload: dict[str, Any] | None = None
    """Set when the top action's rule has ``confidence == "low"``.

    The engine refuses to mutate and returns enough context for the
    caller to ``record_gap()`` so the unresolved ambiguity surfaces on
    the next ``agent-readiness scan`` via ``ontology.gaps_unresolved``.
    The shape mirrors the protocol's :class:`Gap` model's serialisable
    fields (``kind``, ``detail``, ``candidate_resolutions``, and a
    ``check_id``/``severity`` cross-reference so the caller can
    attribute the gap back to the originating finding). Added in
    agent-readiness v3.2.0.
    """

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly dict.

        Strips keys whose values are ``None``, ``False``, or empty
        lists so the emitted JSON matches the convention used by
        ``report.to_dict`` (only carry fields that carry information).
        """
        out: dict[str, Any] = {}
        for k, v in asdict(self).items():
            if v is None:
                continue
            if isinstance(v, list) and not v:
                continue
            if k in ("confirm_required",) and v is False:
                # Default False is uninformative for v0.5 consumers.
                continue
            out[k] = v
        return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def apply_top_action(
    top_action: dict[str, Any] | None,
    repo: Path,
    *,
    run_verify: bool = True,
    verify_timeout: float | None = None,
) -> ApplyResult:
    """Apply ``top_action`` to ``repo`` and optionally run its verify.

    Parameters
    ----------
    top_action:
        A dict shaped like :func:`agent_readiness.scorer.compute_top_action`
        output. May be ``None`` (no findings) or carry only ``fix_hint``
        (rules_version=1 rule), in which case we skip cleanly.
    repo:
        Path to the repository root. Must be a real directory.
    run_verify:
        When ``True`` (default) and the action ships a ``verify`` block,
        run that command after applying and record the outcome.
    verify_timeout:
        Override the verify block's ``timeout_seconds`` (default 15).

    Returns
    -------
    ApplyResult
        Envelope. Inspect ``.applied`` and ``.verified``.
    """
    if top_action is None:
        return ApplyResult(applied=False, skipped_reason="top_action is None")

    action = top_action.get("action")
    if not isinstance(action, dict):
        # rules_version=1 rules surface fix_hint only; nothing to apply
        # programmatically. The MCP tool / scan CLI still print the
        # fix_hint so the agent isn't left empty-handed.
        return ApplyResult(
            applied=False,
            skipped_reason=(
                "top_action has no structured action "
                "(v1 rule with fix_hint only)"
            ),
        )

    # Confidence gating (Bundle B / B2). Branches BEFORE handler lookup
    # so even a perfectly-structured action is refused when the rule
    # author hasn't opted in to ``high``. A missing ``confidence`` key
    # is treated as ``medium`` to match the protocol default — never
    # silently fall through to apply.
    confidence = top_action.get("confidence", "medium")
    if confidence == "low":
        return ApplyResult(
            applied=False,
            skipped_reason="low_confidence_record_gap",
            gap_payload={
                "kind": "low_confidence_top_action",
                "detail": (
                    f"Top action {top_action.get('check_id')!r} has "
                    "confidence=low; refusing to mutate. The MCP layer "
                    "should record_gap() with this payload so the "
                    "ambiguity surfaces on the next scan."
                ),
                "check_id": top_action.get("check_id"),
                "severity": top_action.get("severity"),
                "candidate_resolutions": (
                    [top_action.get("fix_hint")]
                    if top_action.get("fix_hint")
                    else []
                ),
            },
        )
    if confidence == "medium":
        return ApplyResult(
            applied=False,
            skipped_reason="confirm_required",
            confirm_required=True,
        )
    # confidence == "high" falls through to the existing apply path.

    kind = action.get("kind")
    handler = _ACTION_HANDLERS.get(kind)
    if handler is None:
        return ApplyResult(
            applied=False,
            error=f"unknown action kind: {kind!r}",
        )

    repo = Path(repo).resolve()
    if not repo.is_dir():
        return ApplyResult(
            applied=False,
            error=f"repo path is not a directory: {str(repo)!r}",
        )

    try:
        written = handler(action, repo)
    except Exception as exc:
        logger.exception("apply_action handler %r raised", kind)
        return ApplyResult(
            applied=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    verified: bool | None = None
    verify_block: dict[str, Any] | None = None
    if run_verify:
        verify_step = top_action.get("verify")
        if isinstance(verify_step, dict) and verify_step.get("command"):
            verify_block, verified = _run_verify(
                verify_step, repo, timeout_override=verify_timeout
            )

    return ApplyResult(
        applied=True,
        written=written,
        verified=verified,
        verify=verify_block,
    )


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------


def _apply_create_file(action: dict[str, Any], repo: Path) -> list[str]:
    """Materialise a new file from ``template``.

    Refuses to overwrite an existing file — the contract is that
    ``create_file`` is for a missing artefact. Use ``append_to_file``
    or ``insert_after`` for edits.
    """
    path = _require_str(action, "path", "create_file")
    template = _require_str(action, "template", "create_file")
    target = _resolve_in_repo(repo, path, kind="create_file")

    if target.exists():
        raise FileExistsError(
            f"{path!r} already exists; create_file refuses to overwrite. "
            "Use append_to_file or insert_after for edits."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template, encoding="utf-8")
    return [path]


def _apply_append_to_file(action: dict[str, Any], repo: Path) -> list[str]:
    """Append ``template`` to ``path``; create it if absent."""
    path = _require_str(action, "path", "append_to_file")
    template = _require_str(action, "template", "append_to_file")
    target = _resolve_in_repo(repo, path, kind="append_to_file")

    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    sep = "" if not existing or existing.endswith("\n") else "\n"
    target.write_text(existing + sep + template, encoding="utf-8")
    return [path]


def _apply_insert_after(action: dict[str, Any], repo: Path) -> list[str]:
    """Insert ``template`` right after the first line matching ``after_pattern``.

    Regex is compiled with :data:`re.MULTILINE` so ``^`` / ``$`` mean
    "start/end of line". The handler refuses to operate on a missing
    file — the contract is "insert into existing structure".
    """
    path = _require_str(action, "path", "insert_after")
    after_pattern = _require_str(action, "after_pattern", "insert_after")
    template = _require_str(action, "template", "insert_after")
    target = _resolve_in_repo(repo, path, kind="insert_after")

    if not target.exists():
        raise FileNotFoundError(
            f"{path!r} not found; insert_after requires an existing file"
        )

    try:
        pat = re.compile(after_pattern, re.MULTILINE)
    except re.error as exc:
        raise ValueError(
            f"insert_after pattern is not valid regex: {after_pattern!r} "
            f"({exc})"
        ) from exc

    text = target.read_text(encoding="utf-8")
    m = pat.search(text)
    if not m:
        raise ValueError(
            f"insert_after pattern not found in {path!r}: {after_pattern!r}"
        )

    line_end = text.find("\n", m.end())
    if line_end == -1:
        # match was on the final unterminated line
        new = text + ("\n" if not text.endswith("\n") else "") + template
        if not template.endswith("\n"):
            new += "\n"
    else:
        insertion = template if template.endswith("\n") else template + "\n"
        new = text[: line_end + 1] + insertion + text[line_end + 1 :]
    target.write_text(new, encoding="utf-8")
    return [path]


def _apply_edit_gitignore(action: dict[str, Any], repo: Path) -> list[str]:
    """Append missing entries to ``.gitignore`` (create if absent).

    Idempotent: returns an empty ``written`` list when every entry is
    already present.
    """
    entries_raw = action.get("entries")
    if not isinstance(entries_raw, list) or not entries_raw:
        raise ValueError("edit_gitignore requires a non-empty `entries` list")
    entries = [str(e) for e in entries_raw]

    target = repo / ".gitignore"
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    existing_lines = {line.strip() for line in existing.splitlines()}
    to_add = [e for e in entries if e.strip() and e.strip() not in existing_lines]
    if not to_add:
        return []

    sep = "" if not existing or existing.endswith("\n") else "\n"
    target.write_text(
        existing + sep + "\n".join(to_add) + "\n",
        encoding="utf-8",
    )
    return [".gitignore"]


def _apply_modify_manifest_field(
    action: dict[str, Any], repo: Path
) -> list[str]:
    """Set ``field_path`` to ``value`` inside the structured manifest.

    JSON / YAML: parse, set the dotted field, rewrite.
    TOML: parse, check whether the field already exists; if not,
    append a ``[section]\\nkey = "value"`` block at the file end. The
    protocol's contract is "appends a fresh table if the field is
    missing", which keeps us out of needing a TOML writer dep for
    most cases.
    """
    manifest = _require_str(action, "manifest", "modify_manifest_field")
    field_path = _require_str(action, "field_path", "modify_manifest_field")
    value = _require_str(action, "value", "modify_manifest_field")
    target = _resolve_in_repo(repo, manifest, kind="modify_manifest_field")

    if not target.exists():
        raise FileNotFoundError(
            f"{manifest!r} not found; modify_manifest_field cannot "
            "create a missing manifest (use create_file)"
        )

    suffix = target.suffix.lower()
    if suffix == ".json":
        return _modify_json_field(target, manifest, field_path, value)
    if suffix in (".yaml", ".yml"):
        return _modify_yaml_field(target, manifest, field_path, value)
    if suffix == ".toml":
        return _modify_toml_field(target, manifest, field_path, value)
    raise ValueError(
        f"unsupported manifest type for {manifest!r}: {suffix!r} "
        "(supported: .json, .yaml/.yml, .toml)"
    )


def _modify_json_field(
    target: Path, manifest: str, field_path: str, value: str
) -> list[str]:
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(
            f"{manifest!r} top-level is not an object; "
            "modify_manifest_field requires a mapping root"
        )
    _set_dotted(data, field_path, value)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return [manifest]


def _modify_yaml_field(
    target: Path, manifest: str, field_path: str, value: str
) -> list[str]:
    raw = target.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) if raw.strip() else {}
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(
            f"{manifest!r} top-level is not a mapping; "
            "modify_manifest_field requires a mapping root"
        )
    _set_dotted(data, field_path, value)
    target.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return [manifest]


def _modify_toml_field(
    target: Path, manifest: str, field_path: str, value: str
) -> list[str]:
    data = tomllib.loads(target.read_text(encoding="utf-8"))
    if _get_dotted(data, field_path) is not None:
        # Already present; idempotent no-op rather than rewriting in
        # an ambiguous shape.
        return []

    parts = field_path.split(".")
    if len(parts) < 2:
        raise ValueError(
            f"modify_manifest_field requires a `section.key` form "
            f"for TOML, got {field_path!r}"
        )
    table = ".".join(parts[:-1])
    key = parts[-1]

    existing = target.read_text(encoding="utf-8")
    sep = "" if not existing or existing.endswith("\n") else "\n"
    # Escape backslashes and double quotes in value for TOML basic string.
    escaped = value.replace("\\", "\\\\").replace("\"", "\\\"")
    addition = f"{sep}\n[{table}]\n{key} = \"{escaped}\"\n"
    target.write_text(existing + addition, encoding="utf-8")
    return [manifest]


def _apply_run_command(action: dict[str, Any], repo: Path) -> list[str]:
    """Run the structured shell command in the repo root.

    Side effects show up in ``git diff`` after the call; we don't
    attempt to track which files were touched (would require a
    pre/post snapshot diff, which is what the caller's "show diff"
    step already does). Returns an empty ``written`` list.
    """
    command = _require_str(action, "command", "run_command")
    proc = subprocess.run(
        command,
        shell=True,
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        # Truncate to keep error envelopes readable.
        stderr_tail = proc.stderr.strip()[-400:]
        raise RuntimeError(
            f"run_command failed (exit {proc.returncode}): {stderr_tail!r}"
        )
    return []


_ACTION_HANDLERS = {
    "create_file": _apply_create_file,
    "append_to_file": _apply_append_to_file,
    "insert_after": _apply_insert_after,
    "edit_gitignore": _apply_edit_gitignore,
    "modify_manifest_field": _apply_modify_manifest_field,
    "run_command": _apply_run_command,
}


# ---------------------------------------------------------------------------
# Verify subprocess runner
# ---------------------------------------------------------------------------


def _run_verify(
    verify: dict[str, Any],
    repo: Path,
    *,
    timeout_override: float | None = None,
) -> tuple[dict[str, Any], bool]:
    command = verify.get("command")
    if not isinstance(command, str) or not command.strip():
        return ({"error": "verify block missing `command`"}, False)

    timeout = (
        timeout_override
        if timeout_override is not None
        else float(verify.get("timeout_seconds", 15))
    )
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return (
            {
                "command": command,
                "timed_out": True,
                "timeout_seconds": timeout,
                "stdout": (exc.stdout or b"").decode("utf-8", errors="replace")[-2000:],
                "stderr": (exc.stderr or b"").decode("utf-8", errors="replace")[-2000:],
            },
            False,
        )

    block = {
        "command": command,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-2000:],
        "stderr": proc.stderr[-2000:],
    }
    return block, proc.returncode == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_in_repo(repo: Path, path: str, *, kind: str) -> Path:
    """Resolve ``path`` (repo-relative) under ``repo`` with an escape guard.

    Refuses absolute paths, ``..`` escapes, and symlinks that resolve
    outside the repo root.
    """
    if not path or path.startswith("/") or path.startswith("\\"):
        raise ValueError(
            f"{kind}: absolute path is not allowed: {path!r}"
        )
    target = (repo / path).resolve()
    try:
        target.relative_to(repo)
    except ValueError as exc:
        raise ValueError(
            f"{kind} path escapes repo root: {path!r}"
        ) from exc
    return target


def _require_str(action: dict[str, Any], key: str, kind: str) -> str:
    val = action.get(key)
    if not isinstance(val, str) or not val:
        raise ValueError(f"{kind} requires non-empty string field {key!r}")
    return val


def _set_dotted(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor = data
    for p in parts[:-1]:
        nxt = cursor.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[p] = nxt
        cursor = nxt
    cursor[parts[-1]] = value


def _get_dotted(data: dict[str, Any], path: str) -> Any:
    cursor: Any = data
    for p in path.split("."):
        if not isinstance(cursor, dict) or p not in cursor:
            return None
        cursor = cursor[p]
    return cursor
