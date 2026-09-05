---
name: freshness-corroboration
description: >-
  Audit whether a website's facts are attributable, current and corroborated
  enough for an AI assistant to repeat them. Checks schema.org JSON-LD presence,
  parse validity and property completeness; whether a resolvable Organization
  entity with sameAs links to independent registries exists so the brand can be
  told apart from others sharing its name; whether machine-readable dates exist
  and agree across JSON-LD, HTTP headers and visible text; and whether claims
  cite external sources. Use when an assistant repeats outdated facts about a
  brand, confuses it with another company, or declines to mention it at all.
  Read-only; never modifies a site.
license: MIT
compatibility: Requires Python 3.9+ (standard library only) and outbound HTTPS access.
allowed-tools: Bash(python3:*) Read Write
---

# Freshness & Corroboration Audit

Stages **5–6**: *extractable* → *corroborated*. A machine has now read the page.
This skill asks the two questions that decide whether it will repeat what it
read: **which entity is this, and is this version of the fact the current one?**

## When to use

- An assistant repeats a discontinued product, an old logo, or a dead price.
- An assistant confuses the brand with a similarly-named company.
- The site was updated but assistants still answer with the previous version.

## Inputs

`evidence/crawl.json` from `crawl-render-audit`, or a list of URLs.

## Procedure

1. `python3 scripts/entity_probe.py --from evidence/crawl.json --out evidence/entity.json`

   Parses every JSON-LD block (flattening `@graph`), records types and which
   useful properties each is missing, collects brand-name strings from JSON-LD,
   `og:site_name` and delimited `<title>` tails, gathers `sameAs` targets and
   **fetches them to confirm they resolve**, and collects every date signal —
   `datePublished`, `dateModified`, HTTP `Last-Modified`, visible dates and the
   rendered copyright year.

2. **Interpret** with `references/entity-and-freshness.md`, which covers what
   each schema type must carry to be quotable, how to read a name-variant
   result, and the false positives to expect.

3. **Report only what the evidence supports.** `same_as_count: 0` is a fact.
   "The brand has no off-site presence" is not — this skill sees only what the
   site declares. Say what was measured.

## The three mechanisms behind these checks

**Identity.** When several things share a name, a system mixes them up unless
something distinguishes them. `sameAs` pointing at Wikidata, LinkedIn or
Crunchbase is that something — a resolvable link into a registry that already
disambiguates. Without it, the brand is a string, not an entity.

**Freshness.** Updating your own page does not erase older copies elsewhere. An
assistant meets your current page alongside a 2019 article, a stale retailer
listing and a cached description, and must decide which to trust. With no date
signal, your version has no advantage — and the older, more-repeated one wins.

**Corroboration.** A claim in exactly one place is fragile. The same claim
stated consistently across independent sources is repeated back. This skill
measures the on-site half — declared `sameAs`, links to authority registries,
external citations — and the report names the off-site half as follow-up work,
because a read-only site audit cannot see the whole web.

## Output

`evidence/entity.json`, consumed by `audit-orchestrator`. Evidence only; the
orchestrator assigns severity.

## Safety

Read-only `GET`. Fetches at most six declared `sameAs` URLs, purely to confirm
they return 200. No authentication, no writes, no third-party APIs.
