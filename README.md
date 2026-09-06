# brand-ai-readiness-audit

An Agent Skill Marketplace that audits any website for the problems stopping AI
assistants from finding, trusting and citing it — and stopping AI-referred
visitors from engaging once they arrive. It emits one structured report:
findings with evidence and severity, prioritized fixes, proactive
recommendations, and a plan for measuring whether the fixes worked.

**Recommend-only.** Every skill is read-only. Nothing here modifies a live site,
authenticates, or submits a form.

## Quick start

```bash
python3 validate_marketplace.py          # check the package is well-formed
```

Then point an agent at the entrypoint skill with a domain. It runs:

```bash
mkdir -p evidence
S=skills
python3 $S/crawl-render-audit/scripts/crawl_probe.py       example.com --out evidence/crawl.json --pages 10
# render, entity and engagement depend only on crawl.json, not on each other --
# run them concurrently or their per-page fetches add up on a slow site
python3 $S/crawl-render-audit/scripts/render_probe.py      --from evidence/crawl.json --out evidence/render.json &
python3 $S/freshness-corroboration/scripts/entity_probe.py --from evidence/crawl.json --out evidence/entity.json &
python3 $S/engagement-audit/scripts/continuity_probe.py    --from evidence/crawl.json --out evidence/engagement.json &
wait
python3 $S/audit-orchestrator/scripts/compose_report.py    --evidence-dir evidence --out report.json --markdown report.md
```

Typical run: **20–90 seconds** for a 10-page sample, depending on how far away
and how fast the target site is. No `pip install` — Python 3 standard library
only, so it runs on any machine that has Python at all.

## The idea

Discovery is a funnel, not a switch. A page must clear every stage in order:

```
exists → discovered → accessible → renderable → extractable → corroborated → selected → retained
                      └── crawl-render-audit ──┘ └── freshness-corroboration ─┘ └ engagement-audit ┘
```

Every finding is anchored to **the stage that broke**, and that drives two things
a flat checklist cannot do:

- **Severity is derived, not guessed** — from the stage plus how much of the site
  is affected. Same site, same severities, every run.
- **Noise is suppressed** — if the citation crawler gets a `403`, "no JSON-LD on
  product pages" is not a second problem, it is an untested hypothesis. Those
  findings are kept but tagged `blocked_by`, so a non-expert fixes the front door
  before rearranging the furniture.

## The skills

| Skill | Stages | What it does |
|---|---|---|
| **audit-orchestrator** *(entrypoint)* | all | Runs the other three, applies the 38-rule catalog and the evidence gate, derives severity, validates and emits the report |
| **crawl-render-audit** | accessible, renderable, extractable | Per-crawler robots.txt parsing, **CDN/WAF block detection**, sitemap and llms.txt, JavaScript render gap, facts locked in non-text |
| **freshness-corroboration** | extractable, corroborated | Structured-data validity and completeness, entity identity and disambiguation, date signals and their contradictions |
| **engagement-audit** | retained | Answer-continuity: deep-linkability, hop distance to the promised fact, landing-page orientation, first-paint blockers |

Each folder is independently valid per [agentskills.io](https://agentskills.io):
its own `SKILL.md`, `scripts/`, `references/`, and its own copy of `auditlib.py`
so it stays portable if lifted out on its own.

## How the entrypoint composes them

1. `crawl-render-audit` runs first and produces `crawl.json`, which shortlists
   the pages every other probe samples — so all three skills audit the same
   pages and their counts are comparable.
2. `freshness-corroboration` and `engagement-audit` are independent once that
   exists and may run concurrently.
3. Each skill emits **evidence only** — never a severity. That is deliberate: a
   single site produces one consistent ranking instead of three competing ones.
4. `compose_report.py` applies the rules, enforces the evidence gate, derives
   severity, tags blocked findings, and validates the output against the schema.
   A non-zero exit means the report is not shippable.
5. The agent then verifies each finding against its cited artifact, and adds the
   two things a script cannot: proactive recommendations specific to this site,
   and the measurement plan.

## Design decisions worth knowing

**Scripts collect evidence; they never judge.** A probe prints status codes,
counts, tag names and verbatim strings. Interpretation lives in the SKILL.md.
That split is what makes the audit reproducible and the reasoning reviewable.

**The evidence gate.** A finding may only be emitted if it can quote a literal
artifact — a status code with the user-agent that produced it, a count with its
denominator, a URL, a verbatim string. No artifact, no finding. Recall is cheap;
precision is what makes an audit trustworthy.

**Honest confidence.** Measured facts are reported at `high`. Heuristics —
overlay class names, brand-name variants — are `medium`, and say what needs
manual confirmation. `references/evidence-rules.md` lists the ten known false
positives and how each is mitigated.

**Standard library only.** `requests` is nicer than `urllib` by about fifteen
minutes of author time and zero of the user's. A failed `pip install` on an
unknown machine costs the entire audit. Every skill also documents `curl`
fallbacks for when Python is unavailable.

## Safety

Read-only `GET` only. Honours `robots.txt` when selecting pages and records what
it skipped. Throttled to one request per host per 400 ms. Bounded page budgets.
Never authenticates, never submits a form, never follows a destructive link.
No external services — the manifest resolves entirely from this directory.

## Layout

```
brand-ai-readiness-audit/
├── marketplace.json              manifest: 4 skills, exactly one entrypoint
├── README.md
├── validate_marketplace.py       spec + manifest + syntax checks, stdlib only
└── skills/
    ├── audit-orchestrator/       ENTRYPOINT
    │   ├── SKILL.md
    │   ├── scripts/              compose_report.py (rules, gate, severity, schema)
    │   └── references/           report-schema, severity-model, finding-catalog,
    │                             evidence-rules, proactive-playbook,
    │                             measurement-protocol
    ├── crawl-render-audit/
    │   ├── SKILL.md
    │   ├── scripts/              crawl_probe.py, render_probe.py
    │   └── references/           ai-crawler-registry, render-checks
    ├── freshness-corroboration/
    │   ├── SKILL.md
    │   ├── scripts/              entity_probe.py
    │   └── references/           entity-and-freshness
    └── engagement-audit/
        ├── SKILL.md
        ├── scripts/              continuity_probe.py
        └── references/           answer-continuity
```

## Tests

Every script carries a runnable, dependency-free self-check:

```bash
for s in skills/*/scripts/*.py; do python3 "$s" --self-check 2>/dev/null; done
python3 validate_marketplace.py
```

The self-checks cover the parsing logic, the severity derivation, the blocked-by
suppression, and the evidence gate — including negative cases, so a rule that
would fire on everything fails the check instead of shipping.

## License

MIT.
