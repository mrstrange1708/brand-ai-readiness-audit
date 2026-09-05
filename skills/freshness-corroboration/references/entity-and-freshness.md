# Entity identity, freshness, corroboration

## Part 1 — identity

A brand name is a string. An entity is a thing a machine can resolve and tell
apart from others sharing that name. The gap between the two is why an assistant
confidently describes the wrong company.

**Minimum viable entity**, on every page:

```json
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "@id": "https://example.com/#organization",
  "name": "Example Corp",
  "alternateName": ["Example", "ExampleCorp"],
  "url": "https://example.com",
  "logo": "https://example.com/logo.png",
  "description": "One sentence stating what the company does and for whom.",
  "foundingDate": "1994-03-01",
  "sameAs": [
    "https://www.wikidata.org/wiki/Q...",
    "https://www.linkedin.com/company/...",
    "https://www.crunchbase.com/organization/..."
  ]
}
```

Three things make this work:

- **A stable `@id`.** Reference the same `@id` from `Product`, `Article` and
  `WebSite` blocks so every page resolves to one entity rather than declaring a
  new company each time.
- **`sameAs` into registries that already disambiguate.** Wikidata first — it is
  the graph most consumers reconcile against. The targets must independently
  describe the same brand consistently; a `sameAs` to a page saying something
  different creates the ambiguity it was meant to resolve.
- **`alternateName` for variants you cannot retire.** This is how you keep the
  variants without splitting the entity.

**Reading a name-variant result.** Two names may be one entity written loosely,
or two real entities (a foundation and the site it runs). These need opposite
fixes — collapse into `alternateName`, or declare both with distinct `@id`s
linked by `parentOrganization`/`subOrganization`. Never assume sloppiness.
The ambiguity comes from the relationship being unstated, not from having two
names. Report at medium confidence and say which check settles it.

## Part 2 — freshness

Updating your page does not erase older copies. An assistant meets your current
page next to a two-year-old article, a stale retailer listing and a cached
description, then decides which to trust. Recency, clarity, source quality and
agreement between sources all feed that decision.

Four date signals, all of which should agree:

| Signal | Where | Notes |
|---|---|---|
| `dateModified` | JSON-LD | The one most consumers read |
| `datePublished` | JSON-LD | Distinguishes new from updated |
| `Last-Modified` | HTTP header | Free; often wrong on CDN-cached pages |
| Visible "Last updated" | Page text | The one a human trusts |
| `<lastmod>` | Sitemap | Read before the page is even fetched |

Rules that keep them trustworthy:

- Drive all of them from **one** source of truth in the CMS.
- Update `dateModified` only on substantive change. Churning it every deploy
  trains consumers to ignore it.
- A contradiction of two or more years between JSON-LD and the header is
  `F-ENT-010`; it discredits every date on the page, including the correct one.
- A visibly stale copyright year is a weak signal on its own but a widely-used
  one. Render it dynamically; it costs one line.

**Superseding an old fact needs more than a new page.** Say explicitly what
changed and when — "Renamed from X in March 2024", "The X9 replaced the X7 in
2024" — so a reader encountering both can order them. An unmarked replacement
just adds a second competing claim.

## Part 3 — corroboration

A claim in exactly one place is fragile. The same claim across independent
sources gets repeated back.

This skill measures the **on-site half**: declared `sameAs`, whether those
targets resolve, links to authority registries, external citations. That is the
honest limit of a read-only site audit, and findings must say so — `same_as_count:
0` means *the site declares none*, not *none exist*.

The **off-site half** belongs in `proactive_recommendations`: get the same
canonical facts into places that already rank and are independent of you — a
Wikidata item, accurate LinkedIn and Crunchbase profiles, official docs,
industry directories, retailer and partner listings. Consistency across
independent sources is what turns a claim into a believed fact.

## Schema types worth having, in priority order

1. `Organization` — sitewide. The highest-leverage single block.
2. `WebSite` with `potentialAction: SearchAction` — declares site search.
3. `Product` + `Offer` — price, `priceCurrency`, `availability`. An `Offer`
   with no price is decoration.
4. `Article` / `BlogPosting` — `author`, `datePublished`, `dateModified`.
5. `FAQPage` — only where the questions are genuine.
6. `BreadcrumbList` — structure for deep pages.

Keep markup and visible text in agreement. A price in `Offer` that contradicts
the price on the page gets the markup discounted, and possibly the page with it.

Validate with the Schema.org validator and Google's Rich Results Test before
shipping. A block that fails to parse is discarded whole — no partial credit.
