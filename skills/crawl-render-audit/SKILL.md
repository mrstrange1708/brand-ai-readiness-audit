---
name: crawl-render-audit
description: >-
  Audit whether an AI crawler can reach a website and read it. Checks robots.txt
  per crawler family, detects CDN/WAF blocks that return errors to bot
  user-agents while serving browsers normally, verifies sitemap and llms.txt,
  and measures how much of each page survives without JavaScript — empty
  single-page-app shells, thin machine-visible text, facts locked in images,
  missing titles, headings, canonicals and meta descriptions. Use when
  diagnosing why a brand is missing from AI assistant answers, why a site that
  looks fine in a browser is invisible to crawlers, or as the access and
  render stage of a wider AI-readiness audit. Read-only; never modifies a site.
license: MIT
compatibility: Requires Python 3.9+ (standard library only) and outbound HTTPS access.
allowed-tools: Bash Read Write
---

# Crawl & Render Audit

Stages **2–4** of the discovery funnel: *accessible* → *renderable* → *extractable*.
A page must clear all three before any other quality matters. Findings here
outrank everything downstream, because a page a crawler cannot fetch or read has
no structured data problem — it has no data at all.

## When to use

- A brand is absent from AI assistant answers and nobody knows why.
- The site looks complete in a browser; you need to know what a machine sees.
- As the first stage invoked by `audit-orchestrator`.

## Inputs

A domain or URL (`example.com`, `https://example.com/`). Nothing else.

## Procedure

Run from the marketplace root. Both scripts print JSON and write it to `--out`.

1. **Access probe.** `python3 scripts/crawl_probe.py <target> --out evidence/crawl.json --pages 10`

   Fetches `robots.txt`, `llms.txt`, `sitemap.xml` (following one level of
   sitemap-index nesting), then fetches the site root **once per crawler
   user-agent** and records status, bytes and headers for each.

2. **Render probe.** `python3 scripts/render_probe.py --from evidence/crawl.json --out evidence/render.json`

   Fetches each shortlisted page and measures what survives with no JavaScript:
   visible word count, text-to-HTML ratio, empty mount elements, framework
   fingerprints, headings, titles, canonicals, alt text, external citations.

3. **Interpret**, using `references/ai-crawler-registry.md` for what each
   user-agent means and `references/render-checks.md` for thresholds and the
   known false positives for each signal.

4. **Never report a finding you cannot quote.** Every claim must carry a literal
   artifact from the evidence JSON — a status code with the user-agent that
   produced it, a count with its denominator, or a URL. If the evidence is
   absent, say the check was inconclusive; do not infer.

If Python is unavailable, `references/render-checks.md` has the equivalent
`curl` commands for every check.

## The check that is usually missed

`robots.txt` is only half the access story. A CDN or WAF can return `403` to a
bot user-agent while `robots.txt` says `Allow: /` and a browser gets `200`. This
is invisible unless you fetch as the bot — which is what step 1 does. Compare
the `browser` control row against every other row in `ua_probe`.

Two crawler families behave differently and must never be conflated:

| Family | Examples | Blocking it means |
|---|---|---|
| **Training** | GPTBot, ClaudeBot, CCBot, Google-Extended | the brand is absent from model memory |
| **Citation** | OAI-SearchBot, Claude-SearchBot/User, PerplexityBot | the brand can never be cited live, whatever the content says |

Blocking training crawlers is a legitimate policy choice. Blocking citation
crawlers while wanting to be cited is almost always an accident.

## Output

Two evidence files consumed by `audit-orchestrator`:
`evidence/crawl.json` and `evidence/render.json`. This skill emits evidence, not
severities — the orchestrator assigns those, so one site produces one consistent
ranking rather than three competing ones.

## Safety

Read-only `GET` requests. Honours `robots.txt` when selecting pages to crawl
(`robots_excluded_candidates` records what was skipped). Throttled to one
request per host per 400 ms. Never authenticates, submits a form, or follows a
destructive link.
