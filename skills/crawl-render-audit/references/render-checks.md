# Render & extractability checks

What each signal means, the threshold used, and how it can be wrong.

## The core question

Not "does this page look right" but **"how much of it exists before JavaScript
runs?"** Fetch the HTML, strip `<script>`, `<style>`, `<noscript>`, `<svg>` and
`<template>`, and count what is left. That is what a text-based reader gets.

## Signals

| Signal | Threshold | Means | Can be wrong when |
|---|---|---|---|
| `visible_words` | < 120 | Little to extract | Legitimate index or redirect stub |
| `text_to_html_ratio` | < 0.02 | Payload is mostly framework | Heavy inline SVG or CSS-in-JS |
| `empty_spa_root_ids` | any | Mount element with no server-rendered content — the strongest single render-gap signal | A shell that hydrates fast still fails a non-JS fetcher, so this stands |
| `frameworks_detected` | — | Context only, never a finding on its own | SSR frameworks appear here too. **Never report a framework as a defect** |
| `noscript_words` | > 50 | A fallback exists; partial mitigation | — |
| `duplicate_titles` | ≥ 1 | Retrieval cannot tell pages apart | Genuinely paginated series |
| `h1_count` | 0 | No subject cue | Image-logo heading patterns |
| `images_without_alt` | ≥ 30% of images | Facts locked in non-text | Purely decorative images legitimately take `alt=""` |
| `has_currency_in_text` | false on a product path | The exact fact a buyer wants is unreadable | Genuine "contact us for pricing" — verify before reporting |
| `external_citation_count` | 0 on ≥ 60% of pages | No corroboration signal | Legitimately self-contained reference sites |

## Why the SPA signal is weighted so heavily

Fetchers differ: some execute JavaScript, many do not, and those that do apply
short timeouts. Content that exists only after hydration is content that may
never be read — and unlike a slow page, it fails silently. Nobody sees a
`403`; the page simply contributes nothing.

The mitigation ladder, cheapest first:

1. Emit the key facts into the initial HTML — JSON-LD plus a `<noscript>` block
   — even while the interactive UI still hydrates client-side.
2. Pre-render content routes at build time (SSG).
3. Server-render (SSR) the templates that state facts you want quoted.

Marketing and product pages need this. A logged-in dashboard does not.

## Manual equivalents, when Python is unavailable

```bash
# machine-visible word count as a citation crawler sees it
curl -sL -A "OAI-SearchBot/1.0" https://example.com/page \
  | sed -e 's/<script[^>]*>.*<\/script>//g' -e 's/<[^>]*>/ /g' | tr -s ' ' | wc -w

# empty SPA mount element
curl -sL https://example.com/page | grep -o '<div id="[^"]*"></div>'

# structured data present at all
curl -sL https://example.com/page | grep -c 'application/ld+json'

# headings, title, canonical, meta description
curl -sL https://example.com/page | grep -oE '<h1[^>]*>[^<]*|<title>[^<]*|rel="canonical"[^>]*|name="description"[^>]*'

# indexing directives — check the header as well as the tag
curl -sI https://example.com/page | grep -i 'x-robots-tag'
```

## Reporting discipline

- Always give the denominator: `8/12 sampled pages`, never "most pages".
- Never report `frameworks_detected` as a problem by itself.
- If a page is already reported as an SPA shell, do not also report it as thin
  text — that is one defect, counted twice, and it inflates the severity of both.
