# agent-readiness

**A benchmark for AI agent readiness of a code repository.**

You bought the seats. Your team is using Claude Code, Cursor, Copilot, Cline.
And the agents keep going off the rails on *your* codebase.

The model is the variable you can't change. The repo is what you can.

`agent-readiness` scans a repository and scores how ready it is for AI
coding agents — across cognitive load, feedback loops, and flow — then
hands you a prioritised punchlist of fixes. Like Lighthouse, but for AI
agent readiness instead of page load.

```
$ agent-readiness scan .

AI Readiness  62 / 100

  Cognitive load     70 / 100
  Feedback loops     40 / 100   ← biggest drag
  Flow & reliability 75 / 100
  Safety             OK

Top friction (fix these first):
  1. test_command.discoverable — no test invocation found in Makefile,
     package.json, or pyproject.toml
  2. agent_docs.present — no AGENTS.md / CLAUDE.md / .cursorrules at root
  3. headless.no_setup_prompts — README mentions "log in to the dashboard"
     during setup; agents can't traverse this

Every WARN/ERROR finding also carries a paste-ready `fix_prompt` block
(one paragraph of agent-led prose + a verify command) so you can hand it
straight to your coding agent. Pipe `--json` to see them, or use the MCP
server's `list_friction(path)` tool.
```

## Install

```bash
pip install agent-readiness
```

Requires Python 3.11+. From source:

```bash
git clone https://github.com/<org>/agent-readiness.git
cd agent-readiness
pip install -e ".[dev]"   # or: make dev
```

## Use from your coding agent

The scanner is also packaged as a Claude Code
[plugin](https://code.claude.com/docs/en/discover-plugins) and a portable
[Agent Skill](https://agentskills.io/specification). Ask your agent
*"score this repo for agent readiness"* and it scans + fixes via the
same scoring engine as the CLI.

The MCP server exposes `scan_repo(path)` (full scan + score) and
`list_friction(path)` (every WARN/ERROR with its paste-ready
`fix_prompt`, sorted by `score_impact` desc). Either call returns
the same agent-led prose the CLI prints.

**Claude Code (recommended):** the plugin bundles the MCP server config
— no manual JSON paste.

```
/plugin marketplace add harrydaihaolin/agent-readiness-skill
/plugin install agent-readiness@agent-readiness-skill
```

Prerequisite: `pip install agent-readiness-mcp` once.

**Cursor / Claude Desktop:** clone the skill repo and run its installer
for the bare SKILL.md path, then paste the MCP config it prints into
your harness:

```bash
git clone https://github.com/harrydaihaolin/agent-readiness-skill.git
cd agent-readiness-skill
./scripts/install.sh
```

See the [skill repo](https://github.com/harrydaihaolin/agent-readiness-skill)
for per-harness install details and the community marketplace status.

## Design principles

**Agents are headless.** We assume the agent has stdin / stdout / files /
git / HTTP and nothing else. No browser, no dashboard, no clickable
button. If important state is reachable only through a UI, it's invisible
to the agent — and the repo loses points wherever that's true.

This applies to our own tool, too. `agent-readiness` is fully headless:
no required interactive prompts, stable JSON via `--json`, exit codes
that mean things, machine-readable findings.

**Code quality counts only where it predicts agent success.** Mega-files,
ambiguous names, dead code, missing types — those have direct lines to
agent failure modes and get measured. We don't reproduce the full
SonarQube taxonomy. Other tools do that well.

**Run untrusted code in Docker, always.** Any check that executes code
from the target repo runs inside a sandboxed container. See
[`docs/SANDBOX.md`](./docs/SANDBOX.md).

## What gets measured

See [`docs/RUBRIC.md`](./docs/RUBRIC.md) for the full definition. Short version:

| Pillar | What it captures |
|---|---|
| **Cognitive load** | What the agent must absorb to make a correct change. |
| **Feedback loops** | How fast and clear is the signal after a change. |
| **Flow / reliability** | Headless walkability + how often friction outside the task blocks the agent. |
| **Safety & trust** | Secrets, destructive scripts, gitignore hygiene. (Cap, not weight.) |

## This repo's score

Dogfooding: `agent-readiness scan .` run against this repository itself.

```
╭─────────────────────────────╮
│  AI Readiness  100.0 / 100  │
╰─────────────────────────────╯
 Cognitive load      100.0  ████████████████████
 Feedback loops      100.0  ████████████████████
 Flow & reliability  100.0  ████████████████████
 Safety              100.0  ████████████████████

No findings. Looking good.
```

Score updated after each iteration as part of the development workflow.

## Usage

```
# Static scan (no Docker needed)
agent-readiness scan .
agent-readiness scan . --json
agent-readiness scan . --fail-below 70        # exit 1 if score < 70 (CI gate)
agent-readiness scan . --only feedback        # filter to one pillar
agent-readiness scan . --baseline prev.json   # diff against a previous run
agent-readiness scan . --report report.html   # HTML report (requires jinja2)
agent-readiness scan . --badge badge.svg      # score badge SVG
agent-readiness scan . --sarif findings.sarif # SARIF for GitHub code scanning

# Runtime scan (executes tests inside Docker)
agent-readiness scan . --run

# Other commands
agent-readiness list-checks
agent-readiness explain manifest.detected
agent-readiness init                          # write .agent-readiness.toml
```

## Status

All phases implemented (v0.1–v0.9). 22 checks across 4 pillars, Docker
sandbox, HTML + SARIF renderers, CLI surface, plugin API. See
[`docs/PLAN.md`](./docs/PLAN.md) for the full roadmap and
[`CHANGELOG.md`](./CHANGELOG.md) for per-phase release notes.

## License

MIT for the code; see [`LICENSE`](LICENSE). The project name and
logo are governed separately by [`TRADEMARK.md`](TRADEMARK.md):
forks are welcome, "agent-readiness" the brand is reserved for the
canonical project.
