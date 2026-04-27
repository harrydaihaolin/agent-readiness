# Validation Framework

This directory contains the planned validation study for agent-readiness scores.

## Goal

Demonstrate that agent-readiness scores correlate with real-world agent task
success rates — measured as: fraction of tasks an LLM coding agent completes
correctly without human intervention, given a fixed token budget.

## Methodology

### Dataset

- Minimum 50 public repositories across Python, JavaScript, Go, and Rust
- Each repository scored by agent-readiness and assigned to a score bucket:
  0-40 (low), 40-70 (medium), 70-100 (high)
- Repositories selected to represent a range of project sizes and domains

### Agent Task Battery

For each repository, run a fixed set of tasks:
1. **Dependency install**: `make install` or ecosystem equivalent
2. **Test suite**: Run the test suite and return pass/fail count
3. **Small bug fix**: Apply a synthetic one-line bug and ask the agent to fix it
4. **New feature stub**: Ask the agent to add a minimal new endpoint/function
5. **Documentation update**: Ask the agent to update README with a new section

### Success Metric

- Task is "successful" if it completes without human intervention and the
  resulting code passes the test suite
- Report: success rate per score bucket; Spearman correlation between
  agent-readiness score and task success rate

### Pilot Results (Phase 9, planned)

| Score bucket | N repos | Avg task success rate |
|---|---|---|
| 0-40 | 17 | ~32% |
| 40-70 | 18 | ~61% |
| 70-100 | 15 | ~89% |

*These are illustrative targets, not measured results. The study will be
conducted in a future phase.*

## Running the Study

```bash
# Install study deps
pip install -e ".[full]"

# Run against a repository
PYTHONPATH=src python3 -m agent_readiness.cli scan /path/to/repo --json > scores.json

# Compare against baseline
PYTHONPATH=src python3 -m agent_readiness.cli scan /path/to/repo --json --baseline scores.json
```

## Notes

- Sandbox all agent execution via DockerSandbox (`--run` flag)
- Use `--fail-below 60` in CI to enforce minimum readiness
- SARIF output (`--sarif`) integrates with GitHub Code Scanning
