#!/usr/bin/env python3
"""Compose the four probes' evidence into ONE audit report.

Two jobs, deliberately separated:
  1. Apply the finding catalog -- deterministic rules, one per known failure mode.
  2. Enforce the EVIDENCE GATE -- a rule may only emit a finding if it can quote a
     literal artifact (status code + UA, a count, a URL, a verbatim string).
     No artifact, no finding. This is what keeps false positives near zero.

Severity is DERIVED, never guessed:
    severity = base(funnel stage) escalated/de-escalated by blast radius
Findings downstream of a hard access block are kept but marked `blocked_by`, so a
reader is not handed 20 cosmetic issues while the front door is nailed shut.

    python3 compose_report.py --evidence-dir evidence/ --out report.json --markdown report.md

The agent then adds proactive_recommendations and measurement_plan per SKILL.md.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

SEV_ORDER = ["critical", "high", "medium", "low", "info"]

# Funnel stages, in the order a page must pass them. A break at an earlier stage
# makes every later stage moot -- that ordering is the whole point.
STAGES = ["discovered", "accessible", "renderable", "extractable",
          "corroborated", "selected", "retained"]


def bump(sev, steps):
    """Move severity up (negative steps) or down (positive) the ladder."""
    return SEV_ORDER[max(0, min(len(SEV_ORDER) - 1, SEV_ORDER.index(sev) + steps))]


def ratio(part, whole):
    return round(len(part) / whole, 3) if whole else 0.0


def blast(part, whole):
    """Blast radius -> severity adjustment. Site-wide is worse than one page."""
    if not whole:
        return 0
    r = len(part) / whole
    if r >= 0.8:
        return -1          # affects nearly everything: escalate
    if r <= 0.25:
        return 1           # isolated: de-escalate
    return 0


def j(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# The finding catalog. Each rule returns None, or a dict with:
#   evidence (a literal, quotable artifact), where (URLs), extra severity shift.
# --------------------------------------------------------------------------
def build_rules():
    R = []

    def rule(fid, title, stage, base, action, how, verify, source):
        def deco(fn):
            R.append({"id": fid, "title": title, "stage": stage, "base": base,
                      "action": action, "how": how, "verify": verify,
                      "source": source, "check": fn})
            return fn
        return deco

    # ---------------- ACCESS (stage: accessible) --------------------------
    @rule("F-ACC-001", "AI citation crawlers are disallowed in robots.txt", "accessible", "critical",
          "Allow the answer-time crawlers in robots.txt; keep training-bot policy separate.",
          ["Add explicit Allow groups for OAI-SearchBot, Claude-SearchBot/Claude-User, PerplexityBot "
           "and Google-Extended if you want to be quoted.",
           "Decide training policy separately: blocking GPTBot/ClaudeBot/CCBot limits model memory "
           "but does NOT stop live citation. Blocking the search bots does.",
           "Keep one User-agent group per bot; a later group does not inherit an earlier one's rules."],
          "Re-run crawl_probe.py; access.robots_disallowed_citation must be empty.",
          "crawl")
    def _(ev):
        blocked = ev.get("crawl", {}).get("access", {}).get("robots_disallowed_citation", [])
        if not blocked:
            return None
        return {"evidence": f"robots.txt at {ev['crawl']['robots']['url']} returns Disallow for "
                            f"citation-time crawlers: {', '.join(blocked)}. These fetch pages at "
                            f"answer time; while disallowed the site cannot be cited by them.",
                "where": [ev["crawl"]["robots"]["url"]]}

    @rule("F-ACC-002", "CDN/WAF returns an error to AI crawlers while serving browsers normally",
          "accessible", "critical",
          "Allowlist the AI crawler user-agents at the CDN/WAF layer.",
          ["This block is invisible in robots.txt -- it happens at the edge, before your origin.",
           "In Cloudflare: WAF > Tools > User Agent Blocking, plus check Bot Fight Mode and any "
           "'Block AI Scrapers' toggle, which also blocks answer-time citation bots.",
           "Verify by forward-DNS-confirming the bot IP rather than trusting the UA string, then allow.",
           "Re-test from outside your network; a rule can pass internally and fail at the edge."],
          "Re-run crawl_probe.py; every citation-family row in ua_probe must return 200.",
          "crawl")
    def _(ev):
        acc = ev.get("crawl", {}).get("access", {})
        rows = [r for r in acc.get("edge_blocked", []) if r["family"] == "citation"]
        if not rows:
            return None
        detail = "; ".join(f"{r['ua']} -> HTTP {r['status']}" for r in rows)
        srv = next((r.get("server") for r in rows if r.get("server")), "unknown")
        return {"evidence": f"Browser UA received HTTP {acc.get('control_status')} from "
                            f"{ev['crawl']['base_url']}, but {detail} (server: {srv}) while "
                            f"robots.txt permits them. The block is at the edge, not in robots.txt.",
                "where": [ev["crawl"]["base_url"]]}

    @rule("F-ACC-003", "robots.txt blocks all crawlers site-wide", "accessible", "critical",
          "Remove the blanket `Disallow: /` from the `User-agent: *` group.",
          ["A blanket disallow usually survives from a staging config. Confirm it is not intentional.",
           "Replace with targeted disallows for admin/cart/search-results paths only."],
          "crawl_probe.py: robots.blanket_disallow_all must be false.",
          "crawl")
    def _(ev):
        if not ev.get("crawl", {}).get("robots", {}).get("blanket_disallow_all"):
            return None
        return {"evidence": f"robots.txt contains `User-agent: *` with `Disallow: /` at "
                            f"{ev['crawl']['robots']['url']}. No compliant crawler may fetch any page.",
                "where": [ev["crawl"]["robots"]["url"]]}

    @rule("F-ACC-004", "AI training crawlers are blocked", "discovered", "medium",
          "Confirm this is a deliberate policy choice, not an accident.",
          ["Blocking GPTBot/ClaudeBot/CCBot/Google-Extended keeps the brand out of model memory, so "
           "assistants cannot answer about it without live retrieval.",
           "If the intent was only to stop scraping-for-training, keep this and make doubly sure the "
           "citation bots are allowed -- that is the path that still earns mentions.",
           "If it was accidental (a default CDN toggle), remove it."],
          "crawl_probe.py: access.robots_disallowed_training reflects your intended policy.",
          "crawl")
    def _(ev):
        acc = ev.get("crawl", {}).get("access", {})
        blocked = acc.get("robots_disallowed_training", []) + acc.get("edge_blocked_training", [])
        if not blocked:
            return None
        return {"evidence": f"Training crawlers blocked: {', '.join(sorted(set(blocked)))}. "
                            f"This removes the brand from model training corpora.",
                "where": [ev["crawl"]["robots"]["url"]]}

    @rule("F-ACC-005", "No XML sitemap is reachable", "discovered", "medium",
          "Publish /sitemap.xml with <lastmod> on every entry and declare it in robots.txt.",
          ["Generate from your CMS/build so it never drifts from reality.",
           "Include <lastmod> with a real modification date -- it is the cheapest recency signal a "
           "crawler can read without fetching the page.",
           "Add `Sitemap: https://<domain>/sitemap.xml` as the last line of robots.txt."],
          "crawl_probe.py: sitemap.url_count > 0 and robots.declares_sitemap is true.",
          "crawl")
    def _(ev):
        sm = ev.get("crawl", {}).get("sitemap", {})
        if sm.get("url_count"):
            return None
        docs = sm.get("documents") or [{}]
        return {"evidence": f"{docs[0].get('url', '/sitemap.xml')} returned HTTP "
                            f"{docs[0].get('status')} and robots.txt declares "
                            f"{'a' if ev['crawl']['robots'].get('declares_sitemap') else 'no'} "
                            f"Sitemap directive. No sitemap URLs were discoverable.",
                "where": [d.get("url") for d in docs if d.get("url")]}

    @rule("F-ACC-006", "Sitemap entries carry no <lastmod> dates", "corroborated", "low",
          "Emit <lastmod> for every sitemap URL.",
          ["Without lastmod a crawler cannot tell a page updated today from one frozen in 2019, so it "
           "re-crawls on its own schedule and your fresh facts wait.",
           "Set it from the content's real modification time, not the build time."],
          "crawl_probe.py: sitemap.lastmod_count equals sitemap.url_count.",
          "crawl")
    def _(ev):
        sm = ev.get("crawl", {}).get("sitemap", {})
        if not sm.get("url_count") or sm.get("lastmod_count"):
            return None
        return {"evidence": f"Sitemap lists {sm['url_count']} URLs and 0 <lastmod> elements.",
                "where": [d.get("url") for d in sm.get("documents", []) if d.get("url")]}

    @rule("F-ACC-007", "No llms.txt is published", "discovered", "low",
          "Publish /llms.txt pointing at the canonical, quotable pages.",
          ["Plain markdown: an H1 with the brand name, a one-line description, then linked sections "
           "(Products, Pricing, Docs, About, Press) with one line of context per link.",
           "Point it at the pages that state hard facts, not at marketing landing pages.",
           "Keep it in sync with the sitemap; a stale llms.txt is worse than none."],
          "crawl_probe.py: llms_txt.present is true.",
          "crawl")
    def _(ev):
        lt = ev.get("crawl", {}).get("llms_txt", {})
        if not lt or lt.get("present"):
            return None
        note = " (the URL returned an HTML page, not a text file)" if lt.get("served_html_instead") else ""
        return {"evidence": f"{lt['url']} returned HTTP {lt['status']}{note}.",
                "where": [lt["url"]]}

    @rule("F-ACC-008", "Homepage is not served over HTTPS", "accessible", "high",
          "Serve the whole site over HTTPS and 301 all HTTP requests to it.",
          ["Add HSTS once redirects are verified.",
           "Update internal links and canonical tags to the https:// origin."],
          "crawl_probe.py: homepage.https is true.",
          "crawl")
    def _(ev):
        hp = ev.get("crawl", {}).get("homepage", {})
        if not hp or hp.get("https"):
            return None
        return {"evidence": f"Homepage resolved to {hp.get('final_url')} (not HTTPS).",
                "where": [hp.get("final_url")]}

    @rule("F-ACC-009", "Homepage did not return HTTP 200", "accessible", "critical",
          "Restore a 200 response at the site root.",
          ["Check origin health, DNS, and any geo/IP filtering that could differ per client.",
           "If the root legitimately redirects, make sure it lands on 200 in one hop."],
          "crawl_probe.py: homepage.status == 200.",
          "crawl")
    def _(ev):
        hp = ev.get("crawl", {}).get("homepage", {})
        if not hp or (hp.get("status") == 200 and not hp.get("error")):
            return None
        return {"evidence": f"GET {ev['crawl']['base_url']} returned "
                            f"{hp.get('error') or 'HTTP ' + str(hp.get('status'))}.",
                "where": [ev["crawl"]["base_url"]]}

    # ---------------- RENDER / EXTRACTABILITY ----------------------------
    @rule("F-RND-001", "Page content requires JavaScript; crawlers receive an empty shell",
          "renderable", "critical",
          "Server-render or pre-render the pages that state facts you want quoted.",
          ["Adopt SSR/SSG for content routes (Next.js app router, Nuxt, Astro, or a prerender step).",
           "Not every assistant fetcher executes JavaScript, and those that do often time out first. "
           "Content that only exists after hydration is content that may never be read.",
           "Interim mitigation: emit the key facts into the initial HTML (JSON-LD plus a <noscript> "
           "block) even while the interactive UI still hydrates client-side.",
           "Verify with `curl -A 'OAI-SearchBot' <url> | wc -w`, not with your browser."],
          "render_probe.py: pages_with_empty_spa_root is empty and median_visible_words > 300.",
          "render")
    def _(ev):
        s = ev.get("render", {}).get("summary", {})
        pages = s.get("pages_with_empty_spa_root") or []
        if not pages:
            return None
        fw = ", ".join(s.get("frameworks_seen") or []) or "a client-side framework"
        return {"evidence": f"{len(pages)}/{s.get('pages_analysed')} pages served an empty mount "
                            f"element with no server-rendered content ({fw} detected). "
                            f"Median machine-visible words across the sample: "
                            f"{s.get('median_visible_words')}.",
                "where": pages, "shift": blast(pages, s.get("pages_analysed", 0))}

    @rule("F-RND-002", "Pages contain almost no machine-readable text", "renderable", "high",
          "Ensure each page's substantive content is present in the delivered HTML.",
          ["Compare `curl -s <url> | wc -c` against the visible word count -- a large gap means the "
           "words are locked behind script execution or images.",
           "Move key claims out of background images, canvas, and script-injected widgets into real "
           "text nodes.",
           "Aim for at least a few hundred words of substantive text on any page you want cited."],
          "render_probe.py: pages_under_120_words is empty.",
          "render")
    def _(ev):
        s = ev.get("render", {}).get("summary", {})
        pages = [p for p in (s.get("pages_under_120_words") or [])
                 if p not in (s.get("pages_with_empty_spa_root") or [])]
        if not pages:
            return None
        return {"evidence": f"{len(pages)}/{s.get('pages_analysed')} sampled pages contained under "
                            f"120 machine-visible words after stripping scripts and styles "
                            f"(minimum observed: {s.get('min_visible_words')}).",
                "where": pages, "shift": blast(pages, s.get("pages_analysed", 0))}

    @rule("F-RND-003", "Pages are excluded from indexing by a noindex directive", "discovered",
          "critical",
          "Remove `noindex` from pages that should be findable.",
          ["Check both the `<meta name=\"robots\">` tag and the `X-Robots-Tag` HTTP header -- either "
           "one suppresses the page, and the header is easy to set globally by accident.",
           "A staging-environment header leaking to production is the usual cause."],
          "render_probe.py: pages_with_noindex is empty.",
          "render")
    def _(ev):
        s = ev.get("render", {}).get("summary", {})
        pages = s.get("pages_with_noindex") or []
        if not pages:
            return None
        return {"evidence": f"{len(pages)}/{s.get('pages_analysed')} sampled pages carry a noindex "
                            f"directive.",
                "where": pages, "shift": blast(pages, s.get("pages_analysed", 0))}

    @rule("F-RND-004", "Pages share duplicate <title> values", "extractable", "medium",
          "Give every page a unique, specific title naming the entity and the page's subject.",
          ["Pattern: `<Specific thing> - <Brand>`. Front-load the distinguishing words.",
           "Identical titles across a sample usually mean an SPA shell title that never updates on "
           "route change -- fix the route-level title, not just the template."],
          "render_probe.py: duplicate_titles == 0.",
          "render")
    def _(ev):
        s = ev.get("render", {}).get("summary", {})
        n = s.get("duplicate_titles") or 0
        if n < 1:
            return None
        return {"evidence": f"{n} duplicate <title> values across {s.get('pages_analysed')} sampled "
                            f"pages.", "where": []}

    @rule("F-RND-005", "Pages have no <h1>", "extractable", "medium",
          "Give every page exactly one <h1> that names the entity and the subject in plain words.",
          ["The h1 is the strongest cue a retriever has for what a page is about.",
           "Write it as the answer to the question the page exists to answer, not as a slogan."],
          "render_probe.py: pages_missing_h1 is empty.",
          "render")
    def _(ev):
        s = ev.get("render", {}).get("summary", {})
        pages = s.get("pages_missing_h1") or []
        if not pages:
            return None
        return {"evidence": f"{len(pages)}/{s.get('pages_analysed')} sampled pages have no <h1>.",
                "where": pages, "shift": blast(pages, s.get("pages_analysed", 0))}

    @rule("F-RND-006", "Pages have no meta description", "selected", "medium",
          "Write a one-sentence meta description stating the page's specific claim.",
          ["Assistants and search snippets both use it as a cheap summary when they do not fetch "
           "the full page.",
           "State a fact, not a mood: what it is, who it is for, one distinguishing number."],
          "render_probe.py: pages_missing_meta_description is empty.",
          "render")
    def _(ev):
        s = ev.get("render", {}).get("summary", {})
        pages = s.get("pages_missing_meta_description") or []
        if not pages:
            return None
        return {"evidence": f"{len(pages)}/{s.get('pages_analysed')} sampled pages have no "
                            f"meta description.",
                "where": pages, "shift": blast(pages, s.get("pages_analysed", 0))}

    @rule("F-RND-007", "Pages declare no canonical URL", "discovered", "medium",
          "Add a self-referencing <link rel=\"canonical\"> to every page.",
          ["Without it, tracking parameters, trailing-slash variants and http/https duplicates split "
           "the same content across several URLs, so no single version accumulates authority.",
           "Point the canonical at the absolute https:// URL you want quoted."],
          "render_probe.py: pages_missing_canonical is empty.",
          "render")
    def _(ev):
        s = ev.get("render", {}).get("summary", {})
        pages = s.get("pages_missing_canonical") or []
        if not pages:
            return None
        return {"evidence": f"{len(pages)}/{s.get('pages_analysed')} sampled pages have no "
                            f"rel=canonical link.",
                "where": pages, "shift": blast(pages, s.get("pages_analysed", 0))}

    @rule("F-RND-008", "Product or pricing pages state no price in machine-readable text",
          "extractable", "high",
          "Put the price in real text and mirror it in Offer JSON-LD.",
          ["A price rendered inside an image, a canvas, or a script-injected widget is invisible to "
           "the reader that decides whether to quote you.",
           "Emit `Offer` with price, priceCurrency and availability, and keep the visible text and "
           "the markup in agreement -- a mismatch is worse than either alone.",
           "Where price genuinely varies, state the starting price as text: 'from $29 per month'."],
          "render_probe.py: fact_pages_without_currency_in_text is empty.",
          "render")
    def _(ev):
        s = ev.get("render", {}).get("summary", {})
        pages = s.get("fact_pages_without_currency_in_text") or []
        checked = s.get("fact_pages_checked") or []
        if not pages:
            return None
        return {"evidence": f"{len(pages)}/{len(checked)} product/pricing-path pages contain no "
                            f"currency value anywhere in machine-visible text.",
                "where": pages, "shift": blast(pages, len(checked))}

    @rule("F-RND-009", "Images carry no alt text", "extractable", "medium",
          "Write alt text that states the fact the image conveys.",
          ["Alt text is the only way a fact that lives in an image reaches a text-based reader.",
           "Describe the content, not the file: 'Velocity X9 running shoe, recycled sole, 240g' "
           "beats 'product photo'.",
           "For charts and spec tables rendered as images, also provide the numbers as real text or "
           "a <table> nearby."],
          "render_probe.py: total_images_without_alt is 0 (or only decorative images remain).",
          "render")
    def _(ev):
        s = ev.get("render", {}).get("summary", {})
        total, missing = s.get("total_images") or 0, s.get("total_images_without_alt") or 0
        if not total or missing / total < 0.3:
            return None
        return {"evidence": f"{missing}/{total} images across {s.get('pages_analysed')} sampled "
                            f"pages have empty or absent alt attributes.",
                "where": s.get("fact_pages_checked") or [],
                "shift": -1 if missing / total >= 0.8 else 0}

    @rule("F-RND-010", "Pages cite no external sources", "corroborated", "medium",
          "Cite named, checkable sources next to your claims.",
          ["Measured effect, not folklore: the GEO study (arXiv:2311.09735, KDD'24, 10k queries) "
           "found citing sources, adding statistics and adding quotations lifted visibility in "
           "generative answers by up to ~40%, while fluency edits and keyword density did nothing.",
           "Link to standards bodies, published research, regulators or named third-party tests.",
           "Attribute quotes to a named person with a role -- attribution is what makes a passage "
           "safe for an assistant to repeat."],
          "render_probe.py: pages_with_zero_external_citations shrinks on content pages.",
          "render")
    def _(ev):
        s = ev.get("render", {}).get("summary", {})
        pages = s.get("pages_with_zero_external_citations") or []
        n = s.get("pages_analysed") or 0
        if not n or len(pages) / n < 0.6:
            return None
        return {"evidence": f"{len(pages)}/{n} sampled pages link to zero external domains "
                            f"(excluding social profiles).",
                "where": pages[:8]}

    # ---------------- ENTITY / FRESHNESS / CORROBORATION -----------------
    @rule("F-ENT-001", "No structured data (JSON-LD) anywhere on the site", "extractable", "high",
          "Add schema.org JSON-LD, starting with Organization on every page.",
          ["Organization with name, url, logo, description and sameAs is the single highest-leverage "
           "block: it tells a machine which real-world entity this site is.",
           "Then add the type that matches each template: Product+Offer, Article, FAQPage, "
           "BreadcrumbList.",
           "Keep markup and visible text in agreement -- contradictions get the markup discounted.",
           "Validate with the Schema.org validator and Google's Rich Results Test before shipping."],
          "entity_probe.py: jsonld_coverage_ratio approaches 1.0.",
          "entity")
    def _(ev):
        s = ev.get("entity", {}).get("summary", {})
        if not s.get("pages_analysed") or s.get("jsonld_coverage_ratio", 0) > 0:
            return None
        return {"evidence": f"0/{s['pages_analysed']} sampled pages contain any application/ld+json "
                            f"block (also 0 microdata and 0 RDFa declarations).",
                "where": s.get("pages_without_jsonld", [])[:8]}

    @rule("F-ENT-002", "Structured data is present but incomplete across the site", "extractable",
          "medium",
          "Extend JSON-LD coverage to every template, not just the homepage.",
          ["Partial coverage means the pages that state your hard facts are the ones a machine "
           "cannot parse.",
           "Add the markup at the template level so new pages inherit it automatically."],
          "entity_probe.py: pages_without_jsonld is empty.",
          "entity")
    def _(ev):
        s = ev.get("entity", {}).get("summary", {})
        r = s.get("jsonld_coverage_ratio", 0)
        missing = s.get("pages_without_jsonld") or []
        if not missing or r == 0:
            return None
        return {"evidence": f"JSON-LD present on {int(r * 100)}% of sampled pages; "
                            f"{len(missing)} page(s) have none.",
                "where": missing[:8]}

    @rule("F-ENT-003", "Structured data fails to parse", "extractable", "high",
          "Fix the malformed JSON-LD blocks.",
          ["A block that does not parse is silently discarded whole -- you get zero credit for it.",
           "Usual causes: unescaped quotes in a description, a trailing comma, or a templating engine "
           "injecting HTML entities into the JSON.",
           "Serialize with a real JSON encoder instead of string concatenation in the template."],
          "entity_probe.py: jsonld_parse_error_count == 0.",
          "entity")
    def _(ev):
        s = ev.get("entity", {}).get("summary", {})
        n = s.get("jsonld_parse_error_count") or 0
        if not n:
            return None
        sample = (s.get("jsonld_parse_error_sample") or [{}])[0]
        return {"evidence": f"{n} JSON-LD block(s) failed to parse. First error: "
                            f"{sample.get('error', 'n/a')} near `{(sample.get('excerpt') or '')[:80]}`.",
                "where": s.get("pages_with_jsonld", [])[:5]}

    @rule("F-ENT-004", "No Organization entity is declared", "extractable", "high",
          "Publish Organization JSON-LD sitewide with a stable @id.",
          ["Give it a permanent @id such as `https://<domain>/#organization` and reference that same "
           "@id from Product, Article and WebSite blocks so everything resolves to one entity.",
           "Include legal name, founding date, logo and description -- the facts an assistant needs "
           "in order to answer 'what is this company'."],
          "entity_probe.py: has_organization_markup is true.",
          "entity")
    def _(ev):
        s = ev.get("entity", {}).get("summary", {})
        if not s.get("pages_analysed") or s.get("has_organization_markup"):
            return None
        types = ", ".join(s.get("jsonld_types_present") or []) or "none"
        return {"evidence": f"No Organization/LocalBusiness/Corporation type found across "
                            f"{s['pages_analysed']} sampled pages. Types present: {types}.",
                "where": s.get("pages_with_jsonld", [])[:5]}

    @rule("F-ENT-005", "The brand declares no sameAs links, so it cannot be disambiguated",
          "corroborated", "high",
          "Add sameAs pointing at independent registries that describe the same entity.",
          ["When several things share a name, sameAs is what tells a machine which one you are.",
           "Prioritise Wikidata (create an item if none exists), then LinkedIn company page, "
           "Crunchbase, GitHub org, and the relevant industry registry.",
           "The targets must independently describe the brand consistently -- a sameAs to a page "
           "that says something different creates the ambiguity it was meant to resolve."],
          "entity_probe.py: same_as_count >= 3 and same_as_broken is empty.",
          "entity")
    def _(ev):
        s = ev.get("entity", {}).get("summary", {})
        if not s.get("pages_analysed") or s.get("same_as_count", 0) >= 2:
            return None
        return {"evidence": f"sameAs declarations found: {s.get('same_as_count', 0)}. "
                            f"Authority-registry links found in page HTML: "
                            f"{s.get('authority_link_count', 0)}.",
                "where": s.get("pages_with_jsonld", [])[:5]}

    @rule("F-ENT-006", "Declared sameAs targets do not resolve", "corroborated", "medium",
          "Fix or remove the broken sameAs URLs.",
          ["A sameAs to a 404 is worse than no sameAs: it asserts a corroboration that does not exist.",
           "Re-check these whenever a social handle or profile URL changes.",
           "Targets that answer 403/429 to automated clients (Bloomberg, Crunchbase, LinkedIn) are "
           "reported separately as unverifiable, not broken -- do not remove those."],
          "entity_probe.py: same_as_broken is empty.",
          "entity")
    def _(ev):
        s = ev.get("entity", {}).get("summary", {})
        broken = s.get("same_as_broken") or []
        if not broken:
            return None
        checked = s.get("same_as_check") or []
        detail = "; ".join(f"{c['url']} -> HTTP {c['status']}" for c in checked
                           if c.get("verdict") in ("dead", "unreachable"))[:400]
        unver = s.get("same_as_unverifiable") or []
        tail = (f" A further {len(unver)} target(s) block automated checks and were not "
                f"counted as broken.") if unver else ""
        return {"evidence": f"{len(broken)}/{len(checked)} declared sameAs targets are dead or "
                            f"unreachable: {detail}{tail}", "where": broken}

    @rule("F-ENT-007", "Key schema types are missing the properties that make them quotable",
          "extractable", "medium",
          "Fill in the properties an answer engine actually reads.",
          ["Present-but-empty markup passes validators and still fails to answer anything.",
           "Product needs offers/brand/image; Offer needs price, priceCurrency and availability; "
           "Article needs author, datePublished and dateModified."],
          "entity_probe.py: missing_props_detail is empty.",
          "entity")
    def _(ev):
        s = ev.get("entity", {}).get("summary", {})
        detail = s.get("missing_props_detail") or []
        if not detail:
            return None
        pretty = "; ".join(f"{d['type']} missing {', '.join(d['missing'])}" for d in detail[:4])
        return {"evidence": f"{len(detail)} typed block(s) lack recommended properties: {pretty}.",
                "where": sorted({d["url"] for d in detail})[:8]}

    @rule("F-ENT-008", "The brand name is written inconsistently across the site", "corroborated",
          "medium",
          "Pick one canonical brand string and use it everywhere, on-site and off.",
          ["Machines treat 'Acme', 'Acme Corp' and 'ACME Technologies' as candidate-different "
           "entities until something proves otherwise.",
           "First decide which case this is. If the variants are one entity written loosely, set the "
           "canonical form in Organization.name and list the rest as `alternateName`.",
           "If they are genuinely two entities -- a foundation and the site it runs, say -- do not "
           "collapse them: declare both with distinct @id values and link them with "
           "`parentOrganization`/`subOrganization`. Ambiguity comes from the relationship being "
           "unstated, not from having two names.",
           "Then push the same strings to every off-site profile -- consistency across independent "
           "sources is what turns a claim into a believed fact."],
          "entity_probe.py: name_variant_count == 1.",
          "entity")
    def _(ev):
        s = ev.get("entity", {}).get("summary", {})
        if s.get("name_variant_count", 0) < 2:
            return None
        # Quote only what the site DECLARES about itself. Page titles are not
        # brand declarations and are deliberately excluded from this claim.
        declared = s.get("declared_names") or []
        variants = {k: v for k, v in (s.get("name_variants") or {}).items()
                    if k in ("jsonld", "og_site_name")}
        pretty = "; ".join(f"{k}: {', '.join(v)}" for k, v in variants.items())
        return {"evidence": f"{s['name_variant_count']} distinct brand names are declared by the "
                            f"site itself ({', '.join(declared)}) -- {pretty}.",
                "where": s.get("pages_with_jsonld", [])[:5],
                # Two names may be one sloppy entity or two real ones. The evidence is
                # solid; the diagnosis needs a human. Say so rather than over-claim.
                "confidence": "medium" if s["name_variant_count"] == 2 else "high"}

    @rule("F-ENT-009", "Pages carry no date signal at all", "corroborated", "high",
          "Publish and maintain machine-readable dates.",
          ["With no date, a machine cannot tell your current fact from a 2019 copy of it elsewhere, "
           "so the older, better-corroborated version wins.",
           "Emit datePublished and dateModified in JSON-LD, show a visible 'Last updated' line, and "
           "make sure the HTTP Last-Modified header is truthful.",
           "Update dateModified only on substantive change -- churning it on every deploy trains "
           "consumers to ignore it."],
          "entity_probe.py: pages_with_no_date_signal is empty.",
          "entity")
    def _(ev):
        s = ev.get("entity", {}).get("summary", {})
        pages = s.get("pages_with_no_date_signal") or []
        n = s.get("pages_analysed") or 0
        if not pages or not n:
            return None
        return {"evidence": f"{len(pages)}/{n} sampled pages expose no datePublished, no "
                            f"dateModified and no visible date.",
                "where": pages[:8], "shift": blast(pages, n)}

    @rule("F-ENT-010", "Date signals contradict each other", "corroborated", "medium",
          "Make the dates agree across markup, headers and visible text.",
          ["Conflicting dates make every date on the page less trustworthy, including the correct one.",
           "Drive all three from one source of truth in the CMS."],
          "entity_probe.py: date_contradictions is empty.",
          "entity")
    def _(ev):
        s = ev.get("entity", {}).get("summary", {})
        c = s.get("date_contradictions") or []
        if not c:
            return None
        f = c[0]
        return {"evidence": f"{len(c)} page(s) disagree by 2+ years between JSON-LD dateModified and "
                            f"the HTTP Last-Modified header. Example: {f['url']} declares "
                            f"{f['jsonld_modified']} but the header says {f['http_last_modified']}.",
                "where": [x["url"] for x in c]}

    @rule("F-ENT-011", "Visible copyright year is stale", "corroborated", "low",
          "Render the copyright year dynamically.",
          ["A visibly stale year is a cheap, widely-used freshness heuristic -- it makes every other "
           "fact on the page look unmaintained.",
           "Emit it from the server/build date rather than hardcoding."],
          "entity_probe.py: stale_copyright is empty.",
          "entity")
    def _(ev):
        s = ev.get("entity", {}).get("summary", {})
        stale = s.get("stale_copyright") or []
        if not stale:
            return None
        return {"evidence": f"Copyright year(s) {', '.join(str(y) for y in stale)} rendered on the "
                            f"site; current year is {s.get('current_year')}.", "where": []}

    # ---------------- ENGAGEMENT / CONTINUITY ---------------------------
    @rule("F-ENG-001", "Facts cannot be deep-linked; only whole pages can be referenced",
          "retained", "high",
          "Give every fact-bearing heading a stable id so it can be linked directly.",
          ["An AI-referred visitor arrives already knowing the answer and clicks only to confirm it. "
           "Landing them at the top of a long page and making them hunt is the bounce.",
           "Add `id` to h2/h3 (`id=\"pricing\"`, `id=\"specs\"`), keep the ids stable across "
           "redesigns, and link to them from your own nav, sitemap and llms.txt.",
           "Assistants can then cite `/product#specs` instead of `/product`, so the visitor lands "
           "on the sentence they were promised."],
          "continuity_probe.py: fact_pages_without_anchors is empty.",
          "engagement")
    def _(ev):
        s = ev.get("engagement", {}).get("summary", {})
        pages = s.get("fact_pages_without_anchors") or []
        if not pages:
            return None
        return {"evidence": f"{len(pages)} page(s) that state hard facts (price, specs, "
                            f"availability) expose no heading anchor ids. Anchor coverage across the "
                            f"crawl: {int((s.get('anchor_id_coverage_ratio') or 0) * 100)}%.",
                "where": pages}

    @rule("F-ENG-002", "No page reachable from the entry point states a concrete fact", "retained",
          "high",
          "Publish at least one page that states your hard facts as plain, quotable text.",
          ["If nothing on the site states a price, a spec or an availability status in text, there is "
           "nothing for an assistant to quote and nothing for an arriving visitor to confirm.",
           "One canonical facts page per product, written as short declarative sentences, does more "
           "for citation than a redesign."],
          "continuity_probe.py: hops_to_first_hard_fact is not null.",
          "engagement")
    def _(ev):
        s = ev.get("engagement", {}).get("summary", {})
        if not s.get("pages_analysed") or s.get("hops_to_first_hard_fact") is not None:
            return None
        return {"evidence": f"Across {s['pages_analysed']} pages crawled to depth "
                            f"{s.get('max_depth_reached')}, no page stated a price, measurement or "
                            f"availability value in machine-visible text.",
                "where": [s.get("entry_url")]}

    @rule("F-ENG-003", "The landing page does not orient an arriving visitor", "retained", "medium",
          "Make the first screen state who you are, what you sell, and one distinguishing fact.",
          ["A visitor sent by an assistant has no navigation context -- they did not browse in, they "
           "teleported in mid-journey.",
           "Replace a generic hero headline with a specific one: entity + category + differentiator.",
           "Put the answer in text within the first ~50 words, not in a carousel or a video."],
          "continuity_probe.py: entry_h1_generic is false and entry_lede_words > 25.",
          "engagement")
    def _(ev):
        s = ev.get("engagement", {}).get("summary", {})
        if not s.get("pages_analysed"):
            return None
        if not s.get("entry_h1_generic") and (s.get("entry_lede_words") or 0) >= 25:
            return None
        h1 = s.get("entry_h1")
        why = []
        if s.get("entry_h1_generic"):
            why.append(f"the h1 is generic (\"{h1}\")")
        if (s.get("entry_lede_words") or 0) < 25:
            why.append(f"only {s.get('entry_lede_words')} words of text precede the fold")
        return {"evidence": f"On {s.get('entry_url')}, " + " and ".join(why) +
                            f". Opening text: \"{(s.get('entry_lede_excerpt') or '')[:140]}\"",
                "where": [s.get("entry_url")]}

    @rule("F-ENG-004", "The promised fact is several clicks from the entry point", "retained",
          "medium",
          "Surface fact pages one click from the entry point and link them from llms.txt.",
          ["Every extra hop between the assistant's answer and the confirming sentence is a chance "
           "to leave.",
           "Add direct links to pricing/specs in the primary nav and in the page that assistants "
           "most often cite."],
          "continuity_probe.py: hops_to_first_hard_fact <= 1.",
          "engagement")
    def _(ev):
        s = ev.get("engagement", {}).get("summary", {})
        hops = s.get("hops_to_first_hard_fact")
        if hops is None or hops <= 1:
            return None
        return {"evidence": f"The nearest page stating a concrete fact is {hops} hops from "
                            f"{s.get('entry_url')}.",
                "where": (s.get("pages_stating_hard_facts") or [])[:4]}

    @rule("F-ENG-005", "No site search, so a disoriented visitor cannot self-rescue", "retained",
          "medium",
          "Add site search, and make its results page a real indexable URL.",
          ["A visitor who arrived with a specific question and cannot find it needs one input box, "
           "not a better menu.",
           "Use `/search?q=<term>` so the query is in the URL -- it is linkable, measurable, and it "
           "tells you exactly which questions your content fails to answer.",
           "Mine those logged queries: they are the highest-signal content backlog you will get."],
          "continuity_probe.py: site_search_present is true.",
          "engagement")
    def _(ev):
        s = ev.get("engagement", {}).get("summary", {})
        if not s.get("pages_analysed") or s.get("site_search_present"):
            return None
        return {"evidence": f"No search input or role=\"search\" landmark found on any of "
                            f"{s['pages_analysed']} crawled pages.",
                "where": [s.get("entry_url")]}

    @rule("F-ENG-006", "An overlay may block content on first paint", "retained", "medium",
          "Ensure the page's substance renders before, and behind, any consent or promo overlay.",
          ["A consent wall or newsletter modal on first paint spends the visitor's entire patience "
           "budget before they see the fact they came for.",
           "Keep the content in the DOM and readable; never couple consent to content rendering.",
           "Delay promotional modals until a scroll or exit-intent signal, never on load."],
          "continuity_probe.py: pages_with_blocker_hints is empty, or verified non-blocking.",
          "engagement")
    def _(ev):
        s = ev.get("engagement", {}).get("summary", {})
        hits = s.get("pages_with_blocker_hints") or []
        if not hits:
            return None
        words = sorted({w for h in hits for w in h["hints"]})
        return {"evidence": f"{len(hits)} page(s) contain overlay-pattern class names "
                            f"({', '.join(words)}). Static analysis cannot confirm whether they "
                            f"block first paint -- verify manually.",
                "where": [h["url"] for h in hits], "confidence": "medium"}

    @rule("F-ENG-007", "No content is written in answer shape", "selected", "medium",
          "Add question-shaped headings followed by a direct one-sentence answer.",
          ["Retrieval works on passages, not pages. A heading that asks the user's actual question, "
           "answered immediately beneath in one self-contained sentence, is the most quotable unit "
           "you can write.",
           "Self-contained means it survives being lifted out of context: name the subject in the "
           "sentence instead of writing 'it' or 'this'.",
           "Mark them up as FAQPage where they genuinely are FAQs."],
          "render_probe.py / continuity_probe.py: pages_with_question_headings is non-empty.",
          "engagement")
    def _(ev):
        s = ev.get("engagement", {}).get("summary", {})
        r = ev.get("render", {}).get("summary", {})
        n = s.get("pages_analysed") or r.get("pages_analysed") or 0
        found = (s.get("pages_with_question_headings") or []) + \
                (r.get("pages_with_question_headings") or [])
        if not n or found:
            return None
        return {"evidence": f"0 of {n} sampled pages contain a heading phrased as a question.",
                "where": []}

    @rule("F-ENG-008", "No breadcrumb trail to orient a mid-journey visitor", "retained", "low",
          "Add visible breadcrumbs plus BreadcrumbList JSON-LD.",
          ["Breadcrumbs tell a visitor who teleported in where they are and what else exists.",
           "The markup also lets assistants describe your site's structure when they cite a "
           "deep page."],
          "continuity_probe.py: breadcrumbs_present is true.",
          "engagement")
    def _(ev):
        s = ev.get("engagement", {}).get("summary", {})
        if not s.get("pages_analysed") or s.get("breadcrumbs_present"):
            return None
        return {"evidence": f"No breadcrumb markup or breadcrumb class found across "
                            f"{s['pages_analysed']} crawled pages.", "where": []}

    return R


# --------------------------------------------------------------------------
# THE TRANSPORT GATE.
# "Absence of evidence is not evidence of absence" is only enforceable if the
# code knows whether the transport worked. A fetch that never completed leaves
# status=None and count=0 -- values indistinguishable from a site that really
# has no sitemap. Reporting those as defects invents findings about a site
# nobody successfully connected to, which is the worst error an audit can make.
# So: no HTTP response, no inference.
# --------------------------------------------------------------------------
# Findings that remain defensible when the site root never returned a status.
_REACHABILITY_RULES = {"F-ACC-008", "F-ACC-009"}


def transport_state(ev):
    """Did we actually reach the site, and if not, whose fault is it?"""
    crawl = ev.get("crawl") or {}
    hp = crawl.get("homepage") or {}
    err = hp.get("error")
    if not err and hp.get("status") is not None:
        return {"ok": True, "class": None, "error": None, "why": None,
                "trust_store": crawl.get("tls_trust_source")}
    klass = hp.get("error_class") or "unknown"
    return {"ok": False, "class": klass, "error": err or "no HTTP status recorded",
            "why": hp.get("error_attribution"),
            "trust_store": crawl.get("tls_trust_source")}


def _inconclusive(site, entry, ts, ev):
    """The audit could not run. Say so; conclude nothing about the site."""
    env = ts["class"] == "environment"
    finding = {
        "id": "F-ENV-001",
        "title": ("Audit could not connect from this machine; no conclusions drawn"
                  if env else "Audit could not reach the site; cause unattributed"),
        "severity": "info",
        "funnel_stage": "accessible",
        "confidence": "high",
        "evidence": (f"GET {entry} failed with {ts['error']}. "
                     f"{ts['why'] or ''} TLS trust store in use: {ts['trust_store'] or 'unknown'}. "
                     f"No page was retrieved, so no finding about this site's content, "
                     f"markup or configuration can be supported by evidence."),
        "where": [entry],
        "suggested_action": {
            "summary": ("Fix connectivity on the auditing machine, then re-run. This is not a "
                        "defect in the audited site." if env else
                        "Re-run from a network that can reach the site before drawing conclusions."),
            "how": ([
                "If the error mentions a certificate: this Python has no usable CA bundle. "
                "On macOS run the 'Install Certificates.command' in /Applications/Python 3.x/, "
                "or `pip install certifi`.",
                "If it mentions a proxy or unreachable network: the audit host has no route out.",
                "Re-run the audit once `curl -sI <site>` succeeds from the same shell.",
            ] if env else [
                "Confirm the domain resolves and the origin answers: `curl -sI <site>`.",
                "Re-run from a different network to rule out local filtering.",
                "If the failure is a real DNS or TLS fault at the site, that is itself the "
                "critical finding -- it makes the site invisible to every crawler.",
            ]),
            "priority": "info",
            "verify": "Re-run crawl_probe.py; homepage.status must be a real HTTP status.",
        },
    }
    return {
        "site": site,
        "audited_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "entry_url": entry,
        "audit_version": "1.1.0",
        "audit_valid": False,
        "summary": {
            "total_findings": 1, "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 1,
            "blocking_finding": "F-ENV-001",
            "stages_broken": [],
            "note": "Inconclusive audit: the site was never retrieved.",
        },
        "findings": [finding],
        "proactive_recommendations": [],
        "measurement_plan": {},
        "coverage": {
            "probes_run": sorted(k for k in ev if ev.get(k)),
            "rules_evaluated": 0,
            "rejected_by_evidence_gate": [],
            "transport": ts,
            "suppressed_by_transport_gate": "all content rules",
        },
    }


def compose(ev, site, entry):
    ts = transport_state(ev)
    # Nothing was retrieved and the cause is this machine (or unknown): the only
    # honest output is "inconclusive". Never convert that into site defects.
    if not ts["ok"] and ts["class"] in ("environment", "unknown"):
        return _inconclusive(site, entry, ts, ev)

    findings, gate_rejects = [], []
    for r in build_rules():
        try:
            hit = r["check"](ev)
        except Exception as e:                     # a broken rule must never kill the audit
            gate_rejects.append({"id": r["id"], "reason": f"rule error: {type(e).__name__}: {e}"})
            continue
        if not hit:
            continue
        # --- THE TRANSPORT GATE -----------------------------------------
        # The root never answered, and the failure is the site's own. Only
        # reachability findings survive: every other rule would be reading
        # meaning into counts produced by fetches that never completed.
        if not ts["ok"] and r["id"] not in _REACHABILITY_RULES:
            gate_rejects.append({"id": r["id"],
                                 "reason": "suppressed: site returned no HTTP status, "
                                           "so absence could not be distinguished from failure"})
            continue
        # --- THE EVIDENCE GATE ------------------------------------------
        if not hit.get("evidence") or len(str(hit["evidence"]).strip()) < 20:
            gate_rejects.append({"id": r["id"], "reason": "no quotable evidence artifact"})
            continue
        sev = bump(r["base"], hit.get("shift", 0))
        # `critical` means the page effectively does not exist for a machine:
        # refused at the door, or fetched and empty. Only those two stages can
        # reach it. A later-stage problem can be site-wide and still not be that
        # kind of emergency -- letting blast radius escalate it there puts "no
        # dates anywhere" beside "the crawler is blocked" and flattens the very
        # distinction the funnel exists to draw.
        if sev == "critical" and r["stage"] not in ("accessible", "renderable"):
            sev = "high"
        findings.append({
            "id": r["id"],
            "title": r["title"],
            "severity": sev,
            "funnel_stage": r["stage"],
            "confidence": hit.get("confidence", "high"),
            "evidence": hit["evidence"],
            "where": [w for w in (hit.get("where") or []) if w][:10],
            "suggested_action": {
                "summary": r["action"],
                "how": r["how"],
                "priority": sev,
                "verify": r["verify"],
            },
        })

    # Findings behind a hard access block are noise until the door opens.
    blockers = [f for f in findings
                if f["funnel_stage"] == "accessible" and f["severity"] == "critical"]
    if blockers:
        bid = blockers[0]["id"]
        for f in findings:
            if f["funnel_stage"] in ("renderable", "extractable", "corroborated",
                                     "selected", "retained"):
                f["blocked_by"] = bid

    findings.sort(key=lambda f: (SEV_ORDER.index(f["severity"]),
                                 STAGES.index(f["funnel_stage"])))
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEV_ORDER}
    return {
        "site": site,
        "audited_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "entry_url": entry,
        "audit_version": "1.0.0",
        "summary": {
            "total_findings": len(findings),
            **{k: v for k, v in counts.items()},
            "blocking_finding": blockers[0]["id"] if blockers else None,
            "stages_broken": sorted({f["funnel_stage"] for f in findings},
                                    key=STAGES.index),
        },
        "findings": findings,
        "proactive_recommendations": [],
        "measurement_plan": {},
        "coverage": {
            "probes_run": sorted(k for k in ev if ev.get(k)),
            "rules_evaluated": len(build_rules()),
            "rejected_by_evidence_gate": gate_rejects,
            "transport": ts,
        },
    }


def to_markdown(rep):
    L = [f"# AI-Readiness Audit - {rep['site']}", "",
         f"Audited {rep['audited_at']} - entry `{rep['entry_url']}`", ""]
    s = rep["summary"]
    L.append(f"**{s['total_findings']} findings** - "
             f"{s['critical']} critical, {s['high']} high, {s['medium']} medium, {s['low']} low")
    if s.get("blocking_finding"):
        L += ["", f"> **Fix {s['blocking_finding']} first.** It blocks access, so every finding "
                  f"below it is unverifiable until it is resolved."]
    L.append("")
    for f in rep["findings"]:
        L.append(f"## [{f['severity'].upper()}] {f['id']} - {f['title']}")
        L.append(f"*stage: {f['funnel_stage']} - confidence: {f['confidence']}"
                 + (f" - blocked by {f['blocked_by']}" if f.get("blocked_by") else "") + "*")
        L += ["", f"**Evidence.** {f['evidence']}", ""]
        if f["where"]:
            L += ["**Where.**"] + [f"- {w}" for w in f["where"][:5]] + [""]
        L.append(f"**Fix.** {f['suggested_action']['summary']}")
        L += [f"{i}. {h}" for i, h in enumerate(f["suggested_action"]["how"], 1)]
        L += ["", f"**Verify.** {f['suggested_action']['verify']}", ""]
    if rep.get("proactive_recommendations"):
        L.append("## Proactive recommendations")
        for p in rep["proactive_recommendations"]:
            L.append(f"- **{p.get('title')}** - {p.get('rationale', '')}")
    return "\n".join(L)


REQUIRED_FINDING = ("id", "title", "severity", "evidence", "suggested_action")


def validate(rep):
    """The report must satisfy the contract before anyone reads it."""
    errs = []
    for k in ("site", "audited_at", "summary", "findings"):
        if k not in rep:
            errs.append(f"missing top-level key: {k}")
    for k in ("total_findings", "critical", "high", "medium"):
        if k not in rep.get("summary", {}):
            errs.append(f"missing summary key: {k}")
    ids = set()
    for i, f in enumerate(rep.get("findings", [])):
        for k in REQUIRED_FINDING:
            if not f.get(k):
                errs.append(f"finding[{i}] missing {k}")
        if f.get("severity") not in SEV_ORDER:
            errs.append(f"finding[{i}] bad severity {f.get('severity')!r}")
        if f.get("id") in ids:
            errs.append(f"duplicate finding id {f.get('id')}")
        ids.add(f.get("id"))
        if not f.get("suggested_action", {}).get("summary"):
            errs.append(f"finding[{i}] suggested_action.summary is empty")
    if rep.get("summary", {}).get("total_findings") != len(rep.get("findings", [])):
        errs.append("summary.total_findings does not match len(findings)")
    return errs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--evidence-dir", default="evidence")
    ap.add_argument("--out", default="report.json")
    ap.add_argument("--markdown")
    args = ap.parse_args()

    d = args.evidence_dir
    ev = {"crawl": j(os.path.join(d, "crawl.json")),
          "render": j(os.path.join(d, "render.json")),
          "entity": j(os.path.join(d, "entity.json")),
          "engagement": j(os.path.join(d, "engagement.json"))}
    if not any(ev.values()):
        print(f"no evidence files found in {d}/", file=sys.stderr)
        return 2
    site = next((v.get("site") for v in ev.values() if v.get("site")), "unknown")
    entry = ev.get("crawl", {}).get("base_url") or ev.get("engagement", {}).get("entry_url") or ""

    rep = compose(ev, site, entry)
    errs = validate(rep)
    if errs:
        print("SCHEMA VALIDATION FAILED:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 3
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as f:
            f.write(to_markdown(rep))
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    return 0


def _demo():
    ev = {
        "crawl": {"site": "x.example", "base_url": "https://x.example/",
                  "robots": {"url": "https://x.example/robots.txt", "declares_sitemap": False,
                             "blanket_disallow_all": False},
                  "llms_txt": {"url": "https://x.example/llms.txt", "status": 404, "present": False},
                  "homepage": {"status": 200, "https": True, "final_url": "https://x.example/"},
                  "sitemap": {"url_count": 0, "documents": [{"url": "https://x.example/sitemap.xml",
                                                             "status": 404}]},
                  "access": {"control_status": 200,
                             "robots_disallowed_citation": [],
                             "edge_blocked": [{"ua": "PerplexityBot", "family": "citation",
                                               "status": 403, "server": "cloudflare",
                                               "cf_mitigated": None}],
                             "robots_disallowed_training": ["GPTBot"],
                             "edge_blocked_training": []}},
        "render": {"summary": {"pages_analysed": 4, "pages_with_empty_spa_root": ["a", "b", "c", "d"],
                               "frameworks_seen": ["react"], "median_visible_words": 15,
                               "min_visible_words": 9, "pages_under_120_words": ["a", "b", "c", "d"],
                               "duplicate_titles": 3, "pages_missing_h1": ["a"],
                               "pages_missing_meta_description": [], "pages_missing_canonical": [],
                               "pages_with_noindex": [], "fact_pages_checked": [],
                               "fact_pages_without_currency_in_text": [], "total_images": 0,
                               "total_images_without_alt": 0,
                               "pages_with_zero_external_citations": ["a", "b", "c", "d"],
                               "pages_with_question_headings": []}},
        "entity": {"summary": {"pages_analysed": 4, "jsonld_coverage_ratio": 0.0,
                               "pages_without_jsonld": ["a", "b"], "jsonld_parse_error_count": 0,
                               "has_organization_markup": False, "same_as_count": 0,
                               "authority_link_count": 0, "same_as_broken": [], "same_as_check": [],
                               "missing_props_detail": [], "name_variant_count": 1,
                               "pages_with_no_date_signal": ["a", "b", "c", "d"],
                               "date_contradictions": [], "stale_copyright": [2019],
                               "current_year": 2026, "jsonld_types_present": [],
                               "pages_with_jsonld": []}},
        "engagement": {"summary": {"pages_analysed": 4, "entry_url": "https://x.example/",
                                   "entry_h1": "Welcome", "entry_h1_generic": True,
                                   "entry_lede_words": 8, "entry_lede_excerpt": "Welcome",
                                   "hops_to_first_hard_fact": None, "max_depth_reached": 2,
                                   "fact_pages_without_anchors": [], "anchor_id_coverage_ratio": 0.0,
                                   "site_search_present": False, "breadcrumbs_present": False,
                                   "pages_with_blocker_hints": [], "pages_stating_hard_facts": [],
                                   "pages_with_question_headings": []}},
    }
    rep = compose(ev, "x.example", "https://x.example/")
    assert validate(rep) == [], validate(rep)
    ids = {f["id"]: f for f in rep["findings"]}

    # the edge block must be found, and must outrank everything
    assert "F-ACC-002" in ids and ids["F-ACC-002"]["severity"] == "critical", ids.keys()
    assert rep["findings"][0]["severity"] == "critical"
    assert rep["summary"]["blocking_finding"] == "F-ACC-002", rep["summary"]

    # everything downstream is retained but marked as blocked, not dropped
    assert ids["F-ENT-001"]["blocked_by"] == "F-ACC-002", ids["F-ENT-001"]
    assert "blocked_by" not in ids["F-ACC-005"], ids["F-ACC-005"]

    # blast radius escalated the site-wide render gap; it did not stay at base
    assert ids["F-RND-001"]["severity"] == "critical", ids["F-RND-001"]
    # F-RND-002 must not double-report the same pages as F-RND-001
    assert "F-RND-002" not in ids, "thin-text rule double-counted the SPA-shell pages"

    # the critical cap: only accessible/renderable may reach critical, however
    # site-wide a later-stage problem is. `critical` must keep one meaning.
    for f in rep["findings"]:
        if f["severity"] == "critical":
            assert f["funnel_stage"] in ("accessible", "renderable"), f

    # evidence gate: every emitted finding carries a quotable artifact
    for f in rep["findings"]:
        assert len(f["evidence"]) >= 20 and f["suggested_action"]["how"], f
    assert rep["summary"]["total_findings"] == len(rep["findings"])
    assert "accessible" in rep["summary"]["stages_broken"]

    # a rule that raises must be caught, not crash the audit
    bad = compose({"crawl": {"access": None}}, "y.example", "")
    assert isinstance(bad["findings"], list)

    md = to_markdown(rep)
    assert "Fix F-ACC-002 first" in md and "F-ENT-001" in md, md[:400]
    print(f"compose_report self-check OK ({len(rep['findings'])} findings, "
          f"{len(build_rules())} rules)")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _demo()
    else:
        sys.exit(main())
