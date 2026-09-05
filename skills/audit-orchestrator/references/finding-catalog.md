# Finding catalog — 38 rules

The executable rules live in `scripts/compose_report.py` (single source of truth
for detection). This file explains **the mechanism behind each** — why the signal
predicts a real failure. Read it when you need to justify a finding, adapt one,
or decide whether an edge case is genuinely a defect.

Ids are stable. `F-ACC` access, `F-RND` render/extract, `F-ENT` entity/freshness,
`F-ENG` engagement.

## Accessible / discovered — the crawler must be let in

| Id | Finding | Mechanism |
|---|---|---|
| F-ACC-001 | Citation crawlers disallowed in robots.txt | Answer-time fetchers are refused, so the site cannot appear in a cited answer no matter how good the content is |
| F-ACC-002 | CDN/WAF errors to bot UAs while browsers get 200 | The block lives at the edge, so robots.txt looks clean and the site owner never sees it. The commonest silent killer |
| F-ACC-003 | Blanket `Disallow: /` | Usually a staging config that shipped |
| F-ACC-004 | Training crawlers blocked | Removes the brand from model memory. Legitimate as policy; reported so it is a decision, not an accident |
| F-ACC-005 | No reachable XML sitemap | Crawlers fall back to link-following, so deep and orphaned pages may never be found |
| F-ACC-006 | Sitemap has no `<lastmod>` | Nothing tells a crawler the page changed, so re-crawl waits on its own schedule and fresh facts sit unread |
| F-ACC-007 | No `llms.txt` | No curated map of the quotable pages; the crawler guesses which pages matter |
| F-ACC-008 | Homepage not HTTPS | Downranked and often refused outright |
| F-ACC-009 | Homepage not 200 | Nothing downstream is measurable |

## Renderable / extractable — the machine must be able to read it

| Id | Finding | Mechanism |
|---|---|---|
| F-RND-001 | Content requires JavaScript; crawler gets an empty shell | Not every fetcher executes JS, and those that do often time out. Content that exists only after hydration may never be read |
| F-RND-002 | Almost no machine-readable text | Nothing to extract, nothing to quote. Excludes pages already counted by F-RND-001 |
| F-RND-003 | `noindex` present | Explicitly excluded from indexes. Check the `X-Robots-Tag` header too — it is easy to set globally by accident |
| F-RND-004 | Duplicate `<title>` | Retrieval cannot tell the pages apart. Usually an SPA shell title that never updates on route change |
| F-RND-005 | No `<h1>` | The strongest single cue for what a page is about is missing |
| F-RND-006 | No meta description | Removes the cheap summary used when the full page is not fetched |
| F-RND-007 | No canonical | Parameter and slash variants split authority across duplicate URLs |
| F-RND-008 | Product/pricing page states no price in text | The exact fact a buyer asks an assistant for is unreadable. Prices in images or script-injected widgets do not exist to a text reader |
| F-RND-009 | Images without alt text | Facts carried by images have no text path to a reader |
| F-RND-010 | No external citations | Measured: citing sources, statistics and quotations lift visibility in generative answers by up to ~40%; fluency edits and keyword density do not (arXiv:2311.09735, KDD'24) |

## Corroborated — the fact must be attributable and current

| Id | Finding | Mechanism |
|---|---|---|
| F-ENT-001 | No structured data at all | Everything must be inferred from prose; inference is lossy and gets discounted |
| F-ENT-002 | JSON-LD present but incomplete across templates | The pages holding hard facts are the unparseable ones |
| F-ENT-003 | JSON-LD fails to parse | A malformed block is discarded whole. Zero credit |
| F-ENT-004 | No Organization entity | The brand is a string, not a resolvable entity |
| F-ENT-005 | No `sameAs` | Nothing distinguishes this brand from others sharing its name |
| F-ENT-006 | `sameAs` targets 404 | Asserts a corroboration that does not exist — worse than none |
| F-ENT-007 | Types missing quotable properties | Passes validators, answers nothing. `Offer` with no price is decoration |
| F-ENT-008 | Inconsistent brand-name strings | Variants read as candidate-different entities until a relationship is declared |
| F-ENT-009 | No date signal anywhere | Your current fact cannot outrank an older, more-repeated copy elsewhere |
| F-ENT-010 | Date signals contradict | Undermines every date on the page, including the right one |
| F-ENT-011 | Stale visible copyright year | A cheap, widely-used staleness heuristic; makes everything else look unmaintained |

## Selected / retained — the visitor must reach the fact

| Id | Finding | Mechanism |
|---|---|---|
| F-ENG-001 | Fact pages have no heading anchor ids | Assistants can cite only the page, never the sentence. The visitor lands on top of a long page and hunts |
| F-ENG-002 | No reachable page states a concrete fact | Nothing to quote, nothing to confirm |
| F-ENG-003 | Landing page does not orient | A mid-journey arrival has no navigational context and a generic hero gives none |
| F-ENG-004 | Fact is several hops away | Every hop is an exit opportunity |
| F-ENG-005 | No site search | The one control that rescues a visitor whose question the nav does not answer |
| F-ENG-006 | Overlay may block first paint | Spends the patience budget before the fact is visible. Heuristic — verify manually |
| F-ENG-007 | Nothing written in answer shape | Retrieval works on passages. A question heading with a self-contained one-sentence answer is the most quotable unit there is |
| F-ENG-008 | No breadcrumbs | Nothing tells a teleported visitor where they are or what else exists |

## Adding a rule

1. Add the detection to the probe that owns the concern — evidence only.
2. Add a rule in `compose_report.py` with a next id in its family.
3. The rule must return a quotable artifact or `None`. Never a bare boolean.
4. Add a case to that script's `_demo()`, including one input that must **not**
   fire. A rule with no negative test will eventually fire on everything.
5. Add a row here with the mechanism. If you cannot state the mechanism in one
   sentence, the rule is not ready.
