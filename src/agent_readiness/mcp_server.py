"""MCP server for agent-readiness.

Exposes three tools to AI agents via the Model Context Protocol:
  - check_repo_readiness: full scan returning the JSON report
  - get_repo_context:     lightweight repo metadata (no scoring)
  - init_files:           scaffold missing files from templates

Usage:
    agent-readiness mcp          # stdio transport (default)

Requires:
    pip install agent-readiness[mcp]
"""

from __future__ import annotations

from pathlib import Path


def main() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError(
            "MCP server requires the mcp package. "
            "Install with: pip install agent-readiness[mcp]"
        ) from exc

    from agent_readiness.checks import _ensure_loaded, all_checks
    from agent_readiness.context import RepoContext
    from agent_readiness.plugins import load_entry_point_plugins, load_local_plugins
    from agent_readiness.scorer import score as score_results

    mcp = FastMCP("agent-readiness")

    @mcp.tool()
    def check_repo_readiness(repo_path: str) -> str:
        """Scan a repository and return a full AI-readiness JSON report.

        Args:
            repo_path: Absolute or relative path to the repository root.

        Returns:
            JSON string with schema, overall_score, pillar scores, findings,
            and context (languages, monorepo_tools).
        """
        import json

        path = Path(repo_path).resolve()
        load_local_plugins(path)
        load_entry_point_plugins()
        _ensure_loaded()

        ctx = RepoContext(root=path)
        specs = all_checks()
        results = [spec.fn(ctx) for spec in specs]
        for cr, spec in zip(results, specs, strict=True):
            if cr.weight == 1.0 and spec.weight != 1.0:
                cr.weight = spec.weight

        report = score_results(path, results)
        report.languages = ctx.detected_languages
        report.monorepo_tools = ctx.monorepo_tools
        return json.dumps(report.to_dict(), indent=2)

    @mcp.tool()
    def get_repo_context(repo_path: str) -> str:
        """Return lightweight repository metadata without running checks.

        Args:
            repo_path: Absolute or relative path to the repository root.

        Returns:
            JSON string with languages, monorepo_tools, is_monorepo,
            file_count, commit_count, and orientation_tokens.
        """
        import json

        path = Path(repo_path).resolve()
        ctx = RepoContext(root=path)
        return json.dumps({
            "repo_path": str(path),
            "languages": ctx.detected_languages,
            "monorepo_tools": ctx.monorepo_tools,
            "is_monorepo": ctx.is_monorepo,
            "file_count": len(ctx.files),
            "commit_count": ctx.commit_count,
            "orientation_tokens": ctx.orientation_tokens,
        }, indent=2)

    @mcp.tool()
    def init_files(
        repo_path: str,
        dry_run: bool = False,
        force: bool = False,
        only_checks: str = "",
    ) -> str:
        """Scaffold missing agent-readiness files from templates.

        Args:
            repo_path:    Absolute or relative path to the repository root.
            dry_run:      If true, return what would be created without writing.
            force:        If true, overwrite files that already exist.
            only_checks:  Comma-separated check IDs to scaffold for (empty = all).

        Returns:
            JSON string with lists of created, skipped, and error paths.
        """
        import json
        from unittest.mock import patch

        from agent_readiness.scaffold import run_scaffold

        path = Path(repo_path).resolve()
        output_lines: list[str] = []

        # Capture click.echo output
        with patch("click.echo", side_effect=lambda msg="", **_: output_lines.append(str(msg))):
            run_scaffold(
                path,
                dry_run=dry_run,
                force=force,
                only_checks=only_checks or None,
            )

        return json.dumps({"output": output_lines}, indent=2)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
