# agent-readiness

**A benchmark for AI agent readiness of a code repository.**

You bought the seats. Your team is using Claude Code, Cursor, Copilot,
Cline. And the agents keep going off the rails on *your* codebase.

The model is the variable you can't change. The repo is what you can.

`agent-readiness` scans a repository (or a whole workspace of repos)
and scores how ready it is for AI coding agents — across cognitive
load, feedback loops, flow, safety, and (for multi-repo workspaces)
coordination — then hands you a prioritised punchlist of fixes. Like
Lighthouse, but for AI agent readiness instead of page load.

There are two ways to use it:

- [**As a skill in your coding agent**](#install-as-a-skill-recommended) — ask
  Claude / Cursor / Codex *"score this repo for agent-readiness"* and
  it scores + fixes via the bundled MCP server. Multi-repo workspaces
  auto-launch a live browser dashboard.
- [**As a CLI in your shell or CI**](#install-as-a-cli) — `agent-readiness scan .` for the
  same scoring engine, with `--fail-below` for CI gates and `--json`
  for machine output.

Both surfaces wrap the same scoring engine. Pick whichever fits your
workflow; you can mix them.

---

## Install — as a skill (recommended)

The scanner ships as a Claude Code
[plugin](https://code.claude.com/docs/en/discover-plugins) and a portable
[Agent Skill](https://agentskills.io/specification) (works in Cursor and
any other harness that loads `SKILL.md`).

### Claude Code

```
/plugin marketplace add harrydaihaolin/agent-readiness-skill
/plugin install agent-readiness@agent-readiness-skill
```

That's it — the plugin bundles the MCP server config, so there's no
JSON to paste. The skill registers `enumerate_workspace`, `scan_repo`,
`check_workspace_readiness`, `scan_workspace_async` (dashboard mode),
`get_scan_status`, and `apply_top_action` automatically.

Prerequisite once per machine:

```bash
pip install agent-readiness-mcp
```

### Cursor / Claude Desktop / other harnesses

Clone the skill repo and run its installer:

```bash
git clone https://github.com/harrydaihaolin/agent-readiness-skill.git
cd agent-readiness-skill
./scripts/install.sh          # auto-detect; or --target=cursor
```

See the [skill repo](https://github.com/harrydaihaolin/agent-readiness-skill)
for per-harness install details and the community marketplace status.

### Use it

Just talk to your agent:

> *"Score this repo for agent-readiness."*
>
> *"What should I add to AGENTS.md?"*
>
> *"Score the whole workspace and open the dashboard."*

For a single repo, the skill prints the score, the top friction, and
offers to apply the highest-priority deterministic fix.

For a multi-repo workspace, the skill auto-launches **dashboard mode**
— a live browser surface that streams per-repo progress, lets the user
answer interactive prompts inline, and stays out of the chat instead of
blocking it for minutes. The chat side stays hands-off and only checks
status when the user types. See [Dashboard mode](#dashboard-mode-multi-repo-workspaces)
below.

---

## Install — as a CLI

```bash
pip install agent-readiness
```

Requires Python 3.11+. From source:

```bash
git clone https://github.com/harrydaihaolin/agent-readiness.git
cd agent-readiness
pip install -e ".[dev]"   # or: make dev
```

### Use it

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
```

Every WARN/ERROR finding also carries a paste-ready `fix_prompt` block
(one paragraph of agent-led prose + a verify command), so you can hand
it straight to your coding agent. Pipe `--json` for the structured
output the skill consumes internally.

### Full CLI surface

```bash
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

# Multi-repo (workspace) scans
agent-readiness scan-workspace .              # static, headless
agent-readiness scan-and-view . --children .  # local dashboard server

# Ontology bootstrap + inference (Bundle C)
agent-readiness ontology validate ontology/ --strict
agent-readiness ontology reason ontology/ --json

# Apply the top action
agent-readiness apply-top-action .

# Other commands
agent-readiness list-checks
agent-readiness explain manifest.detected
agent-readiness init                          # write .agent-readiness.toml
```

---

## What gets measured

See [`docs/RUBRIC.md`](./docs/RUBRIC.md) for the full definition. Short
version:

| Pillar | What it captures |
|---|---|
| **Cognitive load** | What the agent must absorb to make a correct change. |
| **Feedback loops** | How fast and clear is the signal after a change. |
| **Flow / reliability** | Headless walkability + how often friction outside the task blocks the agent. |
| **Safety & trust** | Secrets, destructive scripts, gitignore hygiene. (Cap, not weight.) |
| **Coordination** (workspace-only) | Whether agents can operate coherently across N repos. Root `AGENTS.md`, member repos declared, dep / change order documented. |

A sixth namespace, **ontology / inference**, ships derived findings —
violations the scanner *infers* from your declared ontology (Bundle C):
e.g. a Library coupled with a Protocol whose consumers disagree on the
major version, a Repo claiming `Releasable` without a release workflow,
or an Action chain that crosses a tenant boundary without the required
intent template.

---

## Dashboard mode (multi-repo workspaces)

For workspaces of two or more repos, the skill auto-launches a live
browser dashboard (`agent-readiness-analytics-dashboard`) and streams
the scan over Server-Sent Events. The UX you'd otherwise miss in chat:

- **Per-repo grid loads progressively** — each repo lights up as it
  starts, ticks, and completes. No 4-minute wait staring at a spinner.
- **Interactive prompts in-browser** — the scanner occasionally needs
  a human decision (classify this directory as code/data/docs?; ratify
  this proposed ontology atom?; apply the top action?). Those land as
  cards in a **Prompts queue** in the dashboard and the user answers
  them with a click instead of having them interrupt the chat.
- **Exit dashboard mode anytime** — click the *"Exit dashboard"* button
  in the browser or type `/agent-readiness exit-dashboard` in chat.
  The scan keeps running; only the surface changes.
- **Findings feed + pillar sidebar + log tail** — the same prioritised
  punchlist the CLI prints, refreshed live.

Run it directly from the CLI:

```bash
agent-readiness scan-and-view . --children .
# opens http://localhost:8765/live/<scan_id>
```

Or, in the agent skill, just say *"score the whole workspace"* — it
hands the URL back in chat and stays out of the way until the scan
completes or you ask for status.

---

## Design principles

**Agents are headless.** We assume the agent has stdin / stdout / files
/ git / HTTP and nothing else. No browser, no dashboard, no clickable
button. If important state is reachable only through a UI, it's
invisible to the agent — and the repo loses points wherever that's
true.

This applies to our own tool, too. The scanner is fully headless: no
required interactive prompts, stable JSON via `--json`, exit codes that
mean things, machine-readable findings. The dashboard is opt-in icing
on top, never a required path.

**Code quality counts only where it predicts agent success.** Mega-files,
ambiguous names, dead code, missing types — those have direct lines to
agent failure modes and get measured. We don't reproduce the full
SonarQube taxonomy. Other tools do that well.

**Run untrusted code in Docker, always.** Any check that executes code
from the target repo runs inside a sandboxed container. See
[`docs/SANDBOX.md`](./docs/SANDBOX.md).

---

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

## Status

All phases implemented through v3.4.1 — 30+ checks across 5 pillars
plus the `ontology/inference` namespace (Bundle C, 6 derived rules),
Docker sandbox, HTML + SARIF renderers, full CLI surface, MCP server,
Claude Code plugin / Cursor skill, and a live SSE dashboard for
multi-repo workspaces (Bundle D). See [`docs/PLAN.md`](./docs/PLAN.md)
for the full roadmap and [`CHANGELOG.md`](./CHANGELOG.md) for per-phase
release notes.

## License

MIT for the code; see [`LICENSE`](LICENSE). The project name and
logo are governed separately by [`TRADEMARK.md`](TRADEMARK.md):
forks are welcome, "agent-readiness" the brand is reserved for the
canonical project.
