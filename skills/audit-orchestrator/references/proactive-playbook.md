# Proactive recommendations

Improvements to recommend **where no defect was detected**. These go in
`proactive_recommendations`, never in `findings` — a finding needs evidence of a
problem; these are opportunities.

Two rules: each must be **specific to what was actually observed on this site**,
and each must state a **mechanism**, not a tactic. Delete any that a finding
already covers.

## Grounded in measurement, not folklore

The GEO study (arXiv:2311.09735, KDD'24 — 10,000 queries across nine domains)
tested content edits against visibility in generative answers:

- **Worked, up to ~40% lift:** citing sources, adding statistics, adding
  quotations from named third parties, authoritative voice.
- **Did essentially nothing:** fluency rewriting, keyword density.

So: recommend attribution and specificity. Never recommend keyword optimisation.
That single distinction separates a mechanism-sound recommendation from
recycled SEO advice.

## The playbook

**1. A canonical facts page per product or service.**
One URL that states every hard fact — price, specs, availability, dimensions,
compatibility — as short declarative sentences with anchored headings. This
becomes the page assistants quote and the page your own pages, sitemap and
`llms.txt` all point at. It converts a scattered set of claims into one
citeable, maintainable source.
*Recommend when:* facts exist but are spread across marketing pages.

**2. Write passages that survive extraction.**
A retriever lifts a passage out of its page. If the sentence says "it weighs
240g", the subject is gone the moment it is quoted. Write "The Velocity X9
weighs 240g." Name the subject in the sentence. This costs nothing and makes
every paragraph independently quotable.
*Recommend when:* prose is pronoun-heavy or heavily context-dependent.

**3. Question-shaped headings with self-contained answers.**
`## What does the Velocity X9 cost?` followed immediately by one complete
sentence answering it. Mirrors how people ask assistants, and gives the
retriever a clean passage boundary. Mark up as `FAQPage` where genuinely FAQs.

**4. Put a number next to every claim.**
"Fast" is unquotable. "Ships in 2 business days" is a fact a machine can repeat
and a reader can verify. Statistics were among the highest-lift edits measured.

**5. Attribute quotes to a named person with a role.**
An attributed quote is safe for an assistant to repeat; an anonymous claim is
not. Named sources were the other highest-lift edit.

**6. Build the off-site corroboration this audit cannot see.**
A read-only site audit sees only what the site declares. A fact stated in one
place is fragile. Get the same canonical facts into independent places that
already rank: a Wikidata item, an accurate LinkedIn and Crunchbase profile,
official docs, industry directories, and any retailer or partner listing that
carries your product data. Consistency across independent sources is what turns
a claim into a believed fact.
*Recommend when:* `same_as_count` is low or authority links are absent.

**7. Keep a public changelog or newsroom with dated entries.**
Gives every update a dated, linkable, crawlable artifact. Directly attacks
staleness: it creates the corroborating record that lets a new fact outrank an
old one elsewhere.

**8. Make anchor ids part of the content contract.**
Stable `id`s on fact-bearing headings, never renamed in a redesign. Once
assistants start citing `/product#specs`, that anchor is an address other people
depend on. Treat it like an API.

**9. Publish `llms.txt` and keep it honest.**
Point it at the canonical fact pages, not the marketing funnel. A stale
`llms.txt` is worse than none.

**10. Use the context that does arrive.**
The site cannot see the assistant's conversation, but referrer, UTM parameters,
the internal-search query and a returning visitor's own path are all available.
Reading them is how a landing page stops being identical for every visitor.
Keep the recommendation honest about cost: a same-page highlight for an inbound
`#anchor` is trivial; genuine server-side personalisation is not.

## Writing them up

```json
{
  "title": "Publish a canonical facts page for each product line",
  "rationale": "Specs are currently spread across three marketing pages with no anchors, so an assistant must synthesise rather than quote. One page it can quote outranks three it must summarise.",
  "priority": "high",
  "effort": "medium",
  "how": ["...concrete steps for THIS site..."]
}
```

`rationale` states the mechanism and cites what was observed. If it reads like
generic advice, it is generic advice — cut it.
