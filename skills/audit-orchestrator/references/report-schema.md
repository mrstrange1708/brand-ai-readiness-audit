# Report schema

`compose_report.py` emits this and validates it before writing. A non-zero exit
means validation failed — the report is not shippable.

```json
{
  "site": "example.com",
  "audited_at": "2026-09-20T14:32:00Z",
  "entry_url": "https://example.com/",
  "audit_version": "1.0.0",
  "summary": {
    "total_findings": 6,
    "critical": 1,
    "high": 2,
    "medium": 3,
    "low": 0,
    "info": 0,
    "blocking_finding": "F-ACC-002",
    "stages_broken": ["accessible", "extractable", "retained"]
  },
  "findings": [
    {
      "id": "F-ACC-002",
      "title": "CDN/WAF returns an error to AI crawlers while serving browsers normally",
      "severity": "critical",
      "funnel_stage": "accessible",
      "confidence": "high",
      "evidence": "Browser UA received HTTP 200 from https://example.com/, but OAI-SearchBot -> HTTP 403; PerplexityBot -> HTTP 403 (server: cloudflare) while robots.txt permits them. The block is at the edge, not in robots.txt.",
      "where": ["https://example.com/"],
      "blocked_by": null,
      "suggested_action": {
        "summary": "Allowlist the AI crawler user-agents at the CDN/WAF layer.",
        "how": ["...ordered, concrete steps..."],
        "priority": "critical",
        "verify": "Re-run crawl_probe.py; every citation-family row in ua_probe must return 200."
      }
    }
  ],
  "proactive_recommendations": [
    {
      "title": "Publish a canonical facts page per product",
      "rationale": "Why this helps, stated as a mechanism.",
      "priority": "high",
      "effort": "medium",
      "how": ["..."]
    }
  ],
  "measurement_plan": {
    "query_set": ["..."],
    "metrics": ["..."],
    "cadence": "monthly",
    "baseline_date": "2026-09-20"
  },
  "coverage": {
    "probes_run": ["crawl", "render", "entity", "engagement"],
    "rules_evaluated": 38,
    "rejected_by_evidence_gate": []
  }
}
```

## Field contract

**Required by the brief** — `site`, `audited_at`, a counts-by-severity `summary`,
and per finding `id`, `title`, `severity`, `evidence`, `suggested_action`.

**Added by this marketplace, and why each earns its place:**

| Field | Why |
|---|---|
| `funnel_stage` | Makes the ordering meaningful and severity reproducible. |
| `confidence` | Separates measured fact from heuristic. Prevents over-claiming. |
| `where` | The exact URLs, so a fix can be verified without re-auditing. |
| `blocked_by` | Says which finding must be fixed first. Stops noise. |
| `suggested_action.how` | Ordered steps. A summary alone is not actionable. |
| `suggested_action.verify` | The command that proves the fix landed. |
| `proactive_recommendations` | Improvements where no defect was found. |
| `measurement_plan` | How the owner knows it worked. |
| `coverage` | What ran, what did not, what the gate rejected. Honest limits. |

## Rules

- `severity` ∈ `critical | high | medium | low | info`.
- `confidence` ∈ `high | medium`. Anything lower does not get reported.
- `summary.total_findings` must equal `len(findings)`.
- Finding ids are stable across runs and across sites, so two audits of the same
  site are directly comparable and a fix can be tracked by id.
- `evidence` is a quotable artifact, minimum 20 characters. Never a restatement
  of the title.
