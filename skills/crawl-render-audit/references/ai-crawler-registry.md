# AI crawler registry

The distinction that decides whether a brand can be cited.

## Two families

**Training crawlers** collect corpora. Blocking them removes the brand from
model memory — the assistant will not know it offhand — but does **not** stop it
being cited from a live fetch.

**Citation crawlers** fetch pages *at answer time*, to build an answer being
written right now. Blocking them makes the site permanently unciteable by that
assistant, however good the content is.

| User-agent token | Operator | Family |
|---|---|---|
| `GPTBot` | OpenAI | training |
| `OAI-SearchBot` | OpenAI | **citation** |
| `ChatGPT-User` | OpenAI | **citation** (user-triggered fetch) |
| `ClaudeBot` | Anthropic | training |
| `Claude-SearchBot` | Anthropic | **citation** |
| `Claude-User` | Anthropic | **citation** (user-triggered fetch) |
| `PerplexityBot` | Perplexity | **citation** |
| `Perplexity-User` | Perplexity | **citation** (user-triggered fetch) |
| `Google-Extended` | Google | training (Gemini/Vertex) |
| `Applebot-Extended` | Apple | training |
| `CCBot` | Common Crawl | training (feeds many models) |
| `meta-externalagent` | Meta | training |
| `Googlebot` / `Bingbot` | Google / Microsoft | search index — also feeds AI overviews |

Tokens change. Treat this table as a starting set and confirm against each
operator's published documentation before advising a client to block anything.

## The common accidents

**Blocking the wrong half.** A site wants to stop training scraping, adds
`Disallow: /` for everything AI-shaped, and takes the citation bots down with it.
Result: invisible in AI answers, which was never the intent.

**The CDN block nobody can see.** Cloudflare's bot-fight and "block AI scrapers"
controls, or a WAF user-agent rule, return `403` before the request reaches the
origin. `robots.txt` still reads `Allow: /`. Nothing in the site's own config is
wrong. Only fetching as the bot reveals it — which is why `crawl_probe.py`
fetches the root once per user-agent and compares against a browser control.

**Group inheritance.** A later `User-agent:` group does **not** inherit rules
from an earlier one. A robots.txt with a permissive `*` group followed by a
`User-agent: GPTBot` group containing only `Disallow: /` blocks GPTBot entirely.

**Blocking Googlebot by accident.** Google's AI overviews draw on the main
search index, so a Googlebot block costs both channels at once.

## Recommended shape

```
User-agent: *
Allow: /

User-agent: OAI-SearchBot
Allow: /

User-agent: Claude-SearchBot
Allow: /

User-agent: PerplexityBot
Allow: /

# Training policy — a deliberate choice, stated separately:
User-agent: GPTBot
Disallow: /

Sitemap: https://example.com/sitemap.xml
```

Then verify at the edge, because robots.txt cannot see the CDN:

```bash
for ua in "OAI-SearchBot/1.0" "Claude-SearchBot/1.0" "PerplexityBot/1.0" "Mozilla/5.0"; do
  printf '%-24s %s\n' "$ua" "$(curl -s -o /dev/null -w '%{http_code}' -A "$ua" https://example.com/)"
done
```

Every line must read `200`. A citation bot returning `403` while the browser
returns `200` is finding `F-ACC-002`.

## Verifying a bot is genuine

Before allowlisting by user-agent alone, remember the string is trivially
spoofed. Operators publish IP ranges or support reverse-DNS verification; use
those for allow rules that matter, and keep rate limits in place.
