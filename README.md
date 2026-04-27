# agent-readiness

**A DevEx benchmark for AI coding agents.**

You bought the seats. Your team is using Claude Code, Cursor, Copilot, Cline.
And the agents keep going off the rails on *your* codebase.

The model is the variable you can't change. The repo is what you can.

`agent-readiness` scans a repository and scores how operable it is for
coding agents — across cognitive load, feedback loops, and flow —
then hands you a prioritised punchlist of fixes. Like Lighthouse, but for
agent productivity instead of page load.

```
$ agent-readiness scan .

Agent Readiness  64 / 100

  Cognitive load     71 / 100
  Feedback loops     48 / 100   ← biggest drag on agent throughput
  Flow & reliability 73 / 100
  Safety             OK

Top friction (fix these first):
  1. No test command discoverable from Makefile or package.json scripts
  2. README does not document how to install or run
  3. 4 files exceed 2,000 lines (largest: src/legacy/orders.py, 4,812)
```

## What gets measured

See [`RUBRIC.md`](./RUBRIC.md) for the full definition. Short version:

| Pillar | What it captures |
|---|---|
| **Cognitive load** | What the agent must absorb to make a correct change. |
| **Feedback loops** | How fast and clear is the signal after a change. |
| **Flow / reliability** | How often does friction outside the task block the agent. |
| **Safety & trust** | Secrets, destructive scripts, gitignore hygiene. (Cap, not weight.) |

The unit of value is **agent task success rate**, not code aesthetics.
Every check we ship is justified against that goal in `agent-readiness explain`.

## Status

Pre-alpha, v0.1 in progress. See [`PLAN.md`](./PLAN.md) for the roadmap.
