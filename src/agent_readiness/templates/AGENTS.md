# Agent Guide — {{REPO_NAME}}

This file gives AI coding agents (Claude Code, GitHub Copilot, Cursor, Gemini)
the context they need to work effectively in this repository.

## Quick start

```bash
# Install dependencies
# <fill in your install command>

# Run tests
# <fill in your test command>

# Run the linter
# <fill in your lint command>
```

## CI and the feedback loop

**CI is part of the feedback loop.** After you push or update a PR, **monitor GitHub Actions / workflow runs and check results**. When **CI fails**, read the logs, **fix the root cause**, and push follow-up commits. Do not stop while checks are red or ignore failing workflows.

## Do-not-touch paths

- <!-- list paths agents should never modify, e.g. generated/, vendor/ -->

## Conventions

- **Branch naming:** `feat/<short-description>`, `fix/<issue>`, `chore/<topic>`
- **Commit style:** Conventional Commits (`feat:`, `fix:`, `docs:`, etc.)
- **PR scope:** One logical change per PR; keep diffs reviewable

## Architecture notes

<!-- Brief description of the repo layout and key modules -->

## Known friction points

<!-- Things that trip up agents or humans: flaky tests, required env vars, etc. -->
