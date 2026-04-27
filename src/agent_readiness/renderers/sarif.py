"""SARIF 2.1.0 export for findings."""

from __future__ import annotations

import json

from agent_readiness.models import Report, Severity


def render(report: Report) -> str:
    results = []
    rules: dict[str, dict] = {}
    for ps in report.pillar_scores:
        for cr in ps.check_results:
            rules[cr.check_id] = {
                "id": cr.check_id,
                "name": cr.check_id.replace(".", "_"),
                "shortDescription": {"text": cr.check_id},
            }
            for f in cr.findings:
                if f.severity not in (Severity.WARN, Severity.ERROR):
                    continue
                level = "error" if f.severity is Severity.ERROR else "warning"
                result: dict = {
                    "ruleId": cr.check_id,
                    "level": level,
                    "message": {"text": f.message},
                }
                if f.file:
                    result["locations"] = [{
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": str(f.file),
                                "uriBaseId": "%SRCROOT%",
                            },
                            **({"region": {"startLine": f.line}} if f.line else {}),
                        }
                    }]
                results.append(result)

    sarif = {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "agent-readiness",
                    "informationUri": "https://github.com/your-org/agent-readiness",
                    "rules": list(rules.values()),
                }
            },
            "results": results,
        }]
    }
    return json.dumps(sarif, indent=2)
