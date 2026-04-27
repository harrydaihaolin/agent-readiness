# Rubric: what `agent-readiness` measures

## North Star

> **AI readiness**: how prepared a repository is for AI coding agents to
> do useful work in it — find the right code, make a correct change,
> verify it, and iterate — with minimal human supervision.

That's the score. It is a measure of *potential*, not measured outcomes.

The thing we use to validate the score is **agent task success rate** on a
benchmark of standardised tasks (see § Validation strategy). Score and
validation are not the same number; we measure the first and use the
second to check we're measuring the right thing.

A repo can be "clean" by traditional code-quality standards and still be
unready for agents — no run instructions, 30-minute test suite, GUI-only
dev tools, undocumented env vars. Conversely, a "messy" repo with a
working `make test`, a README that explains how to run things, and a
CLAUDE.md can be highly ready.

## A note on code quality

Code quality matters here, but not for its own sake — only where it
predicts agent success. Mega-files, ambiguous names, dead code, missing
type annotations all have direct lines to agent failure modes (context
overflow, noisy greps, wasted reading, missing static signals). Those
get measured.

What we **don't** do is reproduce a full static-analysis taxonomy.
Linters, security scanners, complexity-reporters, dependency auditors —
those products exist and are good at what they do. We integrate signal
from them where useful (e.g., "lint passes" is a Feedback-pillar
check); we don't try to be them.

## Design principle: agents are headless

This is not a check, it's the **lens through which every check is
written**.

We assume the agent has stdin / stdout / files / git / HTTP and
nothing else. No browser, no dashboard, no clickable button, no chat
window with a human. If a piece of important information about the
repo's state — whether tests pass, what the error was, how to deploy,
what's currently configured — is reachable *only* through a UI, that
information is invisible to the agent. The repo loses points for
those gaps wherever they appear, across all pillars:

- A test runner that only renders results to an HTML report → Feedback.
- A setup wizard with click-through prompts → Flow.
- A dashboard-only API key configuration → Cognitive load (the agent
  can't see what's set).

This principle applies to **our own tool too**. `agent-readiness` is
itself headless: no interactive prompts required for any operation,
stable JSON output via `--json`, exit codes that mean things,
machine-readable findings.

## The product framing

`agent-readiness` is a **benchmark for AI agent readiness**. The same
way Lighthouse scores a webpage on Performance / Accessibility / SEO
and hands you a prioritised punchlist, we score a repo on AI readiness
and tell you the highest-leverage things to fix.

Audience: engineering leaders and platform teams who have rolled out AI
coding agents (Claude Code, Cursor, Copilot, Cline, etc.) and now ask
"why do they keep going off the rails on *our* codebase?" The model is
the variable they can't change. The repo is what they can.

## The three pillars

We adapt the human DevEx framework (Forsgren/Storey/Noda — cognitive load,
feedback loops, flow) to agents. The pillars are not arbitrary buckets;
each captures a distinct kind of friction agents demonstrably hit.

### Pillar 1 — Cognitive load
*What does the agent have to hold in its head to make a correct change?*

An agent's "context" is its working memory. Cognitive load goes up when the
agent has to read more files, chase more indirection, or guess at unstated
conventions. It goes down when the repo tells the agent what it needs to
know, where to look, and what's safe to ignore.

What we measure here:
- **Bootstrap docs.** README that actually explains purpose + how to run.
  Agent-targeted docs (`AGENTS.md`, `CLAUDE.md`, `.cursorrules`,
  `.github/copilot-instructions.md`, `ARCHITECTURE.md`).
- **Entry-point legibility.** Is it obvious where execution starts?
  Single `main` / `bin/` / `cmd/` / `src/index.*` vs scattered.
- **Repo shape.** Top-level file count, directory depth, file size
  distribution, presence of mega-files (>2k LOC).
- **Boundary clarity.** Vendored / generated / source clearly separated;
  `.gitignore` keeps build artefacts out so the agent isn't reading them.
- **Naming and search precision.** Greps for likely terms return signal,
  not noise. (Heuristic: count of files matching common ambiguous terms
  like `utils`, `helpers`, `manager`.)
- **Context budget.** Estimated tokens for "the smallest set of files an
  agent must read to orient itself" (README + manifest + entry points).

### Pillar 2 — Feedback loops
*After the agent makes a change, how fast and how clearly does it learn whether the change is correct?*

This is the single most predictive pillar. Agents that get a green/red
signal in seconds, with a clear error pointing to a file and line,
self-correct. Agents that wait 8 minutes for a flaky CI run, or get a
1,000-line stack trace, spiral.

What we measure here:
- **Test command discoverable.** Makefile target / npm script / pyproject
  config / conventional command.
- **Test runtime.** Wall time when `--run` is enabled.
- **Test command exit code maps to truth.** It actually fails when tests
  fail (no swallowed errors, no `|| true`).
- **Type checker / linter configured.** Static signal before tests even
  run. Big multiplier on agent throughput.
- **Reproducibility.** Lockfile present and up to date; pinned tool
  versions; CI config exists (parity between local and CI).
- **Error legibility (heuristic).** Proxy signals: stringly-typed
  exceptions, custom error hierarchies, `assert` without messages.
  (Coarse in v0; sharper later.)

### Pillar 3 — Flow / reliability
*How often does the agent get blocked by something outside the change it's trying to make?*

This is the "yak shaving" pillar. Hidden prerequisites, missing creds,
broken main, undocumented setup steps, GUI-only dev tools — every one
of these stops the agent dead and usually requires a human to unblock.

What we measure here:
- **Headless walkability.** Every important state and action reachable
  via stdin / stdout / files / git / HTTP. Setup runs non-interactively
  (no prompts requiring a TTY). Test results stream to stdout, not just
  to an HTML report or dashboard. Errors include file:line. Status
  queries (build status, env config) have CLI equivalents. (See the
  "Design principle: agents are headless" section above — this pillar
  is where it gets concrete checks.)
- **Steps from clone to first green test.** Counted from README and/or
  observed when `--run` is enabled. Anything more than ~3 commands is a
  red flag.
- **Hidden prerequisites.** Hard-coded absolute paths, references to
  Docker / specific OS / system packages without `.env.example` or
  setup script.
- **Working main.** CI green on default branch (when CI config exists
  and we can check status — deferred to later versions).
- **Test isolation.** Can a single test run without external services?
  (Heuristic: tests reference `localhost:5432`, real URLs, etc.)
- **`.env.example` parity.** If anything reads from `.env`, an
  `.env.example` exists with the keys (no values).

### Cross-cutting — Safety & trust

Not a pillar but a gate. Findings here can cap the overall score even if
the pillars look fine.
- **Secrets in repo.** Hard fail if real-looking secrets are detected.
- **Destructive scripts** without dry-run guards.
- **`.gitignore` quality.** Build artefacts and local config kept out.

## Scoring

- Each pillar produces a 0–100 score from its checks.
- Overall score is a weighted average; v0 default weights:
  - Feedback loops: 0.40 (the highest-leverage pillar)
  - Cognitive load: 0.30
  - Flow / reliability: 0.30
  - Safety & trust: applied as a cap, not weighted in
- Weights are configurable via `.agent-readiness.toml`. We will publish
  default weights with a written rationale; users disagreeing with our
  rationale should be able to override and run with their own.

## What we explicitly do **not** measure

These are out of scope for this tool. Other tools do them well; we
don't try to compete.

- **Aesthetic style** (line length, single-vs-double quotes, naming
  conventions). Auto-formatters handle this for humans; agents don't
  much care.
- **Test coverage percentage as a target.** High coverage with bad
  tests is worse than 60 % with good ones. We may add coverage later,
  weighted by test *quality* signals — not in v0.
- **Architectural elegance.** SOLID, DDD, hexagonal, layered — out of
  scope. Agents succeed in plenty of "ugly" architectures with good
  feedback loops.
- **Full lint / SAST / SCA taxonomy.** SonarQube, Snyk, CodeClimate
  exist. We integrate signal from them ("does the linter pass?",
  "are there critical CVEs?") rather than reproduce their rule sets.
- **Human-doc completeness.** Docstrings on every method don't make
  a repo agent-friendly. Clear names, working tests, and a README
  that explains how to run things do.

The line we draw: a code-quality signal earns a place in the rubric
when it has a plausible, name-able path to an agent failure mode. If
we can't write the sentence "agents fail at X because of Y," Y
doesn't ship.

## Execution model

Static checks (file walk, manifest parse, regex scans, git log reads) run
on the host. Any check that **executes code from the target repo** —
running tests, install scripts, build commands — runs inside a Docker
container under the rules in [`SANDBOX.md`](./SANDBOX.md).

This forces a clean split in scoring:

- A **static scan** (no `--run`) produces partial Feedback-pillar scores.
  Runtime checks are reported as `not measured`, not as zero.
- A **full scan** (`--run`) requires a working Docker daemon, fails loudly
  if Docker is unavailable, and reports both static and runtime findings.

We will publish reference numbers as **static / full** pairs. They are
not interchangeable; the static score is a lower-bound estimate.

## Validation strategy (post-v0)

A score is only as good as its predictive power. Once v0.1–0.3 ship, we
will validate by:
1. Assembling a small benchmark of repos (10–20) spanning "obviously
   good" to "obviously rough" for agents.
2. Running a fixed task suite (small refactor, add a feature, fix a
   seeded bug) with one or two coding agents on each repo.
3. Measuring agent task success rate per repo.
4. Checking that `agent-readiness` score correlates with success rate.

If a check doesn't move with task success in this study, we cut it.

## Anti-goals

- We will not be a linter. If a finding doesn't change agent behaviour,
  it doesn't belong here.
- We will not be a moralist. Repos that score badly aren't "bad" — they
  just have specific friction we can name. Tone of the report should be
  diagnostic, not scolding.
- We will not optimise for our own number going up. Every check ships
  with an `explain` entry that ties it back to a concrete agent failure
  mode it predicts.
