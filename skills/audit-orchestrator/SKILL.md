---
name: audit-orchestrator
description: >-
  Audit any website for the problems that stop AI assistants finding, trusting
  and citing it, and that stop AI-referred visitors engaging once they arrive —
  crawler and CDN access blocks, JavaScript render gaps, facts locked in
  non-text, missing or invalid structured data, entity ambiguity, stale or
  uncorroborated facts, and weak answer-continuity on landing — then emit one
  audit report of findings with evidence, severity and prioritized, verifiable
  fixes, plus proactive recommendations and a plan for measuring whether the
  fixes worked. This is the entrypoint of the brand-ai-readiness-audit
  marketplace; it composes crawl-render-audit, freshness-corroboration and
  engagement-audit. Use when asked to audit a site's AI discoverability or
  engagement, or to diagnose why a brand is invisible, misrepresented or
  bouncing in AI apps. Recommend-only; never modifies the audited site.
license: MIT
compatibility: Requires Python 3.9+ (standard library only) and outbound HTTPS access. Runs read-only.
allowed-tools: Bash Read Write
---

# Brand AI-Readiness Audit — entrypoint

Takes a website. Emits one audit report: findings with evidence and severity,
prioritized fixes, and proactive recommendations.

## The model everything hangs off

Discovery is a funnel, not a switch. A page must clear every stage in order:

```
exists → discovered → accessible → renderable → extractable → corroborated → selected → retained
                      └── crawl-render-audit ──┘ └── freshness-corroboration ─┘ └ engagement-audit ┘
```

Two consequences drive this whole skill:

1. **A break at an early stage makes later findings unverifiable.** If the
   citation crawler gets a `403`, "no JSON-LD on product pages" is not a
   second problem — it is an untested hypothesis. Report it, but mark it
   `blocked_by` so a non-expert fixes the door before the furniture.
2. **Severity is derived from the stage that broke and how much of the site it
   affects — never guessed.** Same site, same severities, every run.

## Inputs

A domain or URL. Optionally `--pages N` (default 10) to widen the sample.

## Procedure

Deterministic. Steps 1–5 are mechanical; steps 6–8 are where judgment belongs.

1. **Set up.** `mkdir -p evidence`. Resolve the target to a scheme + host root.
   Let `S=skills` be the marketplace's skills directory.

2. **Access + render** (`crawl-render-audit`):
   ```
   python3 $S/crawl-render-audit/scripts/crawl_probe.py  <target> --out evidence/crawl.json --pages 10
   python3 $S/crawl-render-audit/scripts/render_probe.py --from evidence/crawl.json --out evidence/render.json
   ```
   If `homepage.status` is not 200 and `error` is set, stop and report a single
   critical finding: the site was unreachable. Do not emit downstream findings
   from an empty crawl — absence of evidence is not evidence of absence.

3. **Entity + freshness** (`freshness-corroboration`):
   ```
   python3 $S/freshness-corroboration/scripts/entity_probe.py --from evidence/crawl.json --out evidence/entity.json
   ```

4. **Engagement** (`engagement-audit`):
   ```
   python3 $S/engagement-audit/scripts/continuity_probe.py --from evidence/crawl.json --out evidence/engagement.json --max-pages 12
   ```
   Steps 2–4 are independent once `crawl.json` exists and may run concurrently.

5. **Compose.**
   ```
   python3 $S/audit-orchestrator/scripts/compose_report.py --evidence-dir evidence --out report.json --markdown report.md
   ```
   Applies the 38-rule catalog, enforces the evidence gate, derives severity,
   marks blocked findings, and validates the report against the schema. A
   non-zero exit means the report failed validation — fix it, never ship it.

6. **Verify every finding before you present it.** For each finding, open the
   cited evidence and confirm the artifact exists and says what the finding
   claims. Anything you cannot confirm gets deleted or demoted to
   `proactive_recommendations`. This step is the difference between an audit and
   a guess. See `references/evidence-rules.md`.

7. **Add what only judgment can add.** Populate `proactive_recommendations`
   using `references/proactive-playbook.md`. These are improvements where no
   defect was detected — they must be specific to what you actually observed on
   this site, and must state the mechanism, not just the tactic. Drop any that
   the findings already cover.

8. **Add the measurement plan.** Populate `measurement_plan` from
   `references/measurement-protocol.md`: a site-specific query set and the
   metrics to track, so the owner can tell whether the fixes worked. Generate
   the queries from this site's own products, category and locations.

## Output

`report.json` (contract in `references/report-schema.md`) and `report.md`.
Required per finding: `id`, `title`, `severity`, `evidence`, `suggested_action`.
Required summary: `site`, `audited_at`, counts by severity. This marketplace
also emits `funnel_stage`, `confidence`, `where`, `blocked_by`,
`suggested_action.how`, `suggested_action.verify`, `proactive_recommendations`
and `measurement_plan`.

Lead the written summary with the single blocking finding if one exists, then
critical and high findings in funnel order. A non-expert should be able to read
the first screen and know what to fix on Monday.

## Rules that are not negotiable

- **Recommend-only.** Audit and report. Never modify the audited site, never
  authenticate, never submit a form.
- **Evidence or silence.** No finding without a quotable artifact.
- **Honest confidence.** Measured facts are `high`. Heuristics — overlay class
  names, name variants — are `medium` and must say what needs manual checking.
- **No fabricated numbers.** Never invent a page count, a status code or a
  percentage. Quote what the probes returned.
- **Deterministic.** Same site, same evidence, same severities.

## Failure modes and what to do

| Situation | Do this |
|---|---|
| Python unavailable | Fall back to the `curl` procedures in each skill's references; note the reduced sample in `coverage`. |
| Site unreachable / DNS fails | One critical finding; no downstream findings. |
| `robots.txt` blocks the crawl | Honour it. Audit only permitted pages and record what was skipped. |
| Fewer than 3 pages sampled | Emit the report, but set every blast-radius-derived severity to its base and say the sample was too small to generalize. |
| A probe crashes | Continue with the others; list the missing probe in `coverage.probes_run`. |

## References

- `references/report-schema.md` — the output contract
- `references/severity-model.md` — how severity is derived
- `references/finding-catalog.md` — the 38 rules and the mechanism behind each
- `references/evidence-rules.md` — the evidence gate and known false positives
- `references/proactive-playbook.md` — beyond-defect recommendations
- `references/measurement-protocol.md` — how to tell whether fixes worked
