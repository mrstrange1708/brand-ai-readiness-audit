---
name: engagement-audit
description: >-
  Audit whether a visitor sent by an AI assistant can reach the specific fact
  they were promised. Measures deep-linkability (stable heading anchor ids on
  fact-bearing sections), hop distance from the entry page to a page stating a
  concrete price, spec or availability, whether the landing page orients an
  arriving visitor in text above the fold, whether overlays block first paint,
  and whether site search, breadcrumbs and question-shaped headings let a lost
  visitor self-rescue. Use when AI-referred visitors bounce, when a site shows
  every visitor the same generic page regardless of the intent they arrived
  with, or as the engagement half of an AI-readiness audit. Read-only.
license: MIT
compatibility: Requires Python 3.9+ (standard library only) and outbound HTTPS access.
allowed-tools: Bash Read Write
---

# Engagement & Answer-Continuity Audit

Stage **8**: *retained*. Discovery succeeded — the assistant named the brand and
the visitor clicked. This skill audits what happens in the next four seconds.

## When to use

- AI referral traffic arrives and leaves immediately.
- Assistants link the homepage rather than the page that answers the question.
- The site treats a visitor who arrived mid-journey exactly like a cold browser.

## Inputs

`evidence/crawl.json`, or an entry URL.

## Procedure

1. `python3 scripts/continuity_probe.py --from evidence/crawl.json --out evidence/engagement.json --max-pages 12 --max-depth 2`

   Bounded breadth-first walk from the entry point. Per page it records heading
   anchor ids, whether the page states a hard fact (price, measurement,
   availability), the opening text a visitor actually sees, overlay-pattern
   class names, site-search landmarks, breadcrumbs and question-shaped headings.
   It records the **hop count at which a hard fact first becomes readable**.

2. **Interpret** with `references/answer-continuity.md`.

3. **Distinguish measured from inferred.** Overlay class names are a *hint* —
   static analysis cannot prove an element blocks first paint. Report those at
   medium confidence and say they need manual confirmation. Anchor ids and hop
   counts are measured; report those at high confidence.

## Why the usual engagement checklist is the wrong tool

An AI-referred visitor is not a cold browser. An assistant already gave them the
answer; they clicked to **confirm a specific fact**. They did not browse in —
they teleported into the middle of a journey with no navigational context. So
generic UX advice misses the actual defect, which is **answer-continuity**: the
distance between the sentence the assistant quoted and the sentence on your page.

That distance is measurable, and it has three components:

1. **Deep-linkability.** Without stable heading `id`s, an assistant can only
   cite `/product`, never `/product#specs`. The visitor lands at the top of a
   long page and hunts. Anchor ids are the single cheapest fix in this skill.
2. **Hop distance.** Every click between the entry page and the confirming fact
   is a chance to leave. Measured as `hops_to_first_hard_fact`.
3. **Orientation.** A generic hero headline tells a mid-journey visitor nothing.
   The first screen must state entity, category and one distinguishing fact in
   real text.

## Context retention

The site cannot see the assistant's conversation, so "personalisation" here
means something narrower and actually achievable: **preserve and use the context
that does arrive.** Referrer, UTM parameters, the `?q=` of an internal search,
and a returning visitor's own prior path are all available. A site that reads
none of them shows every visitor the same page regardless of why they came.
`references/answer-continuity.md` sets out what can be done read-only and what
requires server work, so recommendations stay honest about cost.

## Output

`evidence/engagement.json`, consumed by `audit-orchestrator`. Evidence only.

## Safety

Read-only `GET`, at most `--max-pages` fetches, throttled per host. Never
submits a form, adds to a cart, or follows a logout or delete link.
