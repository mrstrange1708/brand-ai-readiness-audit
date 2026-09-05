# Measurement protocol

Fill `measurement_plan`. The audit says what is broken; this says how the owner
will know it got fixed. Every finding already carries a
`suggested_action.verify` — that proves the *change* landed. This proves the
*outcome* moved.

## Two layers, and they are not interchangeable

**Layer 1 — did the fix land?** Deterministic, immediate, free. Re-run the
probe named in `verify`. Binary. Automate it in CI so a regression is caught the
day it ships, not the quarter after.

**Layer 2 — did visibility change?** Slower, noisier, and the one that matters.
Generative answers vary between users and over time — personalisation, session
context and live retrieval all move the result. So a single spot-check proves
nothing. Measure a **rate over a fixed query set**, not an anecdote.

## Building the query set

Generate 20–40 queries from what the probes actually found on this site — its
products, category, locations, and the questions its own headings ask. Cover
four intents:

| Intent | Shape | Tests |
|---|---|---|
| Category | "best <category> under <price> in <market>" | Whether the brand is named unprompted. The hardest and most valuable |
| Direct | "what is <brand>" | Whether the entity is known and correctly described |
| Fact | "how much does <product> cost" | Whether current facts surface, or stale ones |
| Comparison | "<brand> vs <competitor>" | How the brand is framed against alternatives |

Freeze the set. Changing queries between runs makes the trend meaningless.

## What to record, per run

For each query × assistant: whether the brand was **named**; whether it was
**cited with a link**; whether the facts stated were **correct** (compare
against the site's own canonical facts page); and **which URL** was cited.

Roll up to four numbers:

- **Mention rate** — % of queries naming the brand
- **Citation rate** — % linking to the site
- **Factual accuracy rate** — % of mentions with no stale or wrong fact
- **Cited-URL distribution** — which pages get quoted. This is the most
  actionable number in the whole plan: it tells you which content is doing the
  work, so you know what to write more of.

## How to run it honestly

- Test across several assistants; they retrieve differently and disagree.
- Use fresh sessions with no prior context, or personalisation confounds the run.
- Same day of week, same cadence. **Monthly** is the right default: shorter
  cycles measure noise, longer ones miss regressions.
- Record the date and the assistant version alongside every result.
- Expect movement in weeks, not days. Re-crawl, re-index and off-site
  corroboration all have to catch up before a fix shows in an answer.

## Also watch, from the site's own analytics

- Referral sessions from assistant domains, and their landing pages. If
  assistants cite the homepage rather than fact pages, anchors and deep links
  are not working yet.
- Bounce and scroll depth for that referral segment specifically — AI-referred
  visitors arrive pre-qualified, so they should behave *better* than average. If
  they do not, the answer-continuity findings are still live.
- Internal site-search queries from that segment. Every search is a question the
  content failed to answer where the visitor expected it. It is the highest-signal
  content backlog available, and it is free.

## Shape

```json
{
  "query_set": ["best <category> under <price>", "what is <brand>", "..."],
  "metrics": ["mention_rate", "citation_rate", "factual_accuracy_rate", "cited_url_distribution"],
  "assistants": ["ChatGPT", "Claude", "Perplexity", "Google AI Overviews"],
  "cadence": "monthly",
  "baseline_date": "<audit date>",
  "layer_1_regression_checks": ["<the verify command from each critical finding>"]
}
```
