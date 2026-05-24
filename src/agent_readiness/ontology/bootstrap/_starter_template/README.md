# Workspace Ontology

This directory is the canonical Workspace Ontology for the agent-readiness
project, per `agent-readiness-research/docs/superpowers/specs/2026-05-24-ontology-pillar-design.md`.

## Layout

- `objectTypes/`  — Type definitions for workspace nouns (Repo, Service, …)
- `linkTypes/`    — Typed relations between Object Types
- `interfaces/`   — Structural-typing contracts (Releasable, Documented, …)
- `functions/`    — Pure typed computations over the graph
- `actionTypes/`  — Atomic single-system mutations (publish, tag, refactor)
- `intentTypes/`  — Cross-repo flows (release_cascade, deprecate_repo)
- `instances/`    — Object / Link / Interface-claim instances (one file per atom)
- `intents/`      — Runtime intent ledgers (append-only JSONL)

## Lifecycle

Every instance file carries a `lifecycle:` block — `state: proposed | ratified`.
Ratified atoms cannot reference unratified atoms (CI closure invariant).
See `agent-readiness ontology --help` for the bootstrap loop.

## Status

Type definitions in this directory are ratified by template (this repo's commit history).
Instances are populated by the M2 dogfooding step against the umbrella workspace.
