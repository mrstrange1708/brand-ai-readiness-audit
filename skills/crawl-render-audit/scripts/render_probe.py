#!/usr/bin/env python3
"""Stage 4-5 evidence: once a crawler is let in, can it READ and QUOTE the page?

A page that looks complete to a person can be empty to a machine. This probe
measures how much of each page survives without JavaScript, and how quotable
what survives actually is.

    python3 render_probe.py --from evidence/crawl.json --out evidence/render.json
    python3 render_probe.py https://example.com/a https://example.com/b

Collects facts only. SKILL.md decides severity.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auditlib as A  # noqa: E402

SPA_ROOT_IDS = {"root", "app", "__next", "__nuxt", "___gatsby", "svelte", "q-app", "main-app"}
FRAMEWORK_HINTS = [
    ("next.js", r"/_next/static|__NEXT_DATA__"),
    ("nuxt", r"/_nuxt/|__NUXT__"),
    ("react", r"react(-dom)?[.@\-][\d.]*(production|development)?\.?m?in?\.js|data-reactroot"),
    ("vue", r"vue[.@\-][\d.]*(runtime|esm)?.*\.js|data-v-[0-9a-f]{8}"),
    ("angular", r"ng-version=|<app-root|\bng-app\b"),
    ("gatsby", r"gatsby|___gatsby"),
    ("svelte", r"svelte-[0-9a-z]{6}"),
]
CURRENCY = r"(?:[$€£¥₹]|\b(?:USD|EUR|GBP|INR|JPY|AUD|CAD)\b)\s?\d"
SOCIAL = ("facebook.", "twitter.", "x.com", "instagram.", "linkedin.", "youtube.", "tiktok.",
          "pinterest.", "t.co", "threads.")
# Page kinds where a missing hard fact (price, spec) is materially different from
# a missing fact on, say, an About page.
FACT_PATH_SEGMENTS = {"product", "products", "pricing", "price", "prices", "plan", "plans",
                      "shop", "store", "buy", "checkout", "subscription", "subscriptions"}
COMMERCE_TEXT = re.compile(
    r"\b(add to (?:cart|bag|basket)|buy now|checkout|per month|per year|/mo\b|/yr\b|"
    r"free trial|subscribe|in stock|out of stock|order now|starting at|from \$)", re.I)
SHELL_WORD_LIMIT = 200
DECORATIVE_SRC = re.compile(r"(spacer|blank|pixel|1x1|transparent|dot)\.(gif|png|svg)$", re.I)


def is_decorative(attrs):
    """Spacer gifs, tracking pixels and role=presentation images carry no fact, so a
    missing alt on them is correct HTML rather than a defect."""
    if attrs.get("role") == "presentation" or attrs.get("aria-hidden") == "true":
        return True
    if DECORATIVE_SRC.search(attrs.get("src", "")):
        return True
    for dim in ("width", "height"):
        v = attrs.get(dim, "")
        if v.isdigit() and int(v) <= 2:
            return True
    return False


def looks_like_fact_page(url, text):
    """Path segment AND commerce language. Either alone is too loose: news sites use
    /item, and blogs discuss pricing."""
    segs = {s for s in urllib.parse.urlsplit(url).path.lower().split("/") if s}
    return bool(segs & FACT_PATH_SEGMENTS) and bool(COMMERCE_TEXT.search(text))


def analyse(url):
    r = A.fetch(url)
    rec = {"url": url, "status": r["status"], "final_url": r["final_url"],
           "bytes": r["bytes"], "elapsed_ms": r["elapsed_ms"], "error": r["error"]}
    if r["status"] != 200 or not r["body"]:
        return rec
    rec.update(analyse_html(url, r["body"]))
    return rec


def analyse_html(url, html):
    """Pure: HTML in, signals out. Split from analyse() so the render-gap logic can
    be tested without the network."""
    rec = {}
    text = A.visible_text(html)
    words = len(text.split())

    head = A.tags(html, ["title", "meta", "link", "h1", "h2", "h3", "img", "a", "table", "ul",
                         "ol", "blockquote", "script", "div", "main", "article", "noscript"])
    by = {}
    for t in head:
        by.setdefault(t["tag"], []).append(t)

    def metas(name_key, name_val):
        return [m["attrs"].get("content", "") for m in by.get("meta", [])
                if m["attrs"].get(name_key, "").lower() == name_val]

    titles = [t["text"] for t in by.get("title", [])]
    desc = metas("name", "description") or metas("property", "og:description")
    canon = [l["attrs"].get("href") for l in by.get("link", [])
             if "canonical" in l["attrs"].get("rel", "")]
    robots_meta = metas("name", "robots")

    # --- JS-render gap signals ------------------------------------------
    spa_roots = [d["attrs"].get("id") for d in by.get("div", [])
                 if d["attrs"].get("id", "").lower() in SPA_ROOT_IDS and len(d["text"].strip()) < 40]
    # A mount element is only evidence of a render gap when the PAGE is also thin.
    # stripe.com ships <div id="__next"> with ~1900 server-rendered words; that is
    # not a shell. Without this gate every Next.js/Nuxt site is a false positive.
    spa_shell = bool(spa_roots) and words < SHELL_WORD_LIMIT
    frameworks = [n for n, pat in FRAMEWORK_HINTS if re.search(pat, html, re.I)]
    noscript_text = " ".join(A.visible_text(n["text"]) for n in by.get("noscript", []))
    rec["render"] = {
        "visible_words": words,
        "html_bytes": len(html),
        "text_to_html_ratio": round(len(text) / max(len(html), 1), 4),
        "empty_spa_root_ids": [i for i in spa_roots if i] if spa_shell else [],
        "mount_elements_seen": [i for i in spa_roots if i],
        "spa_shell_suspected": spa_shell,
        "frameworks_detected": frameworks,
        "script_tag_count": len(by.get("script", [])),
        "noscript_words": len(noscript_text.split()),
        "has_main_or_article": bool(by.get("main") or by.get("article")),
    }

    # --- extractability / quotability -----------------------------------
    h1s = [h["text"] for h in by.get("h1", []) if h["text"]]
    h2s = [h["text"] for h in by.get("h2", []) if h["text"]]
    question_headings = [h for h in h1s + h2s + [h["text"] for h in by.get("h3", [])]
                         if h.strip().endswith("?")]
    imgs = [i for i in by.get("img", []) if not is_decorative(i["attrs"])]
    no_alt = [i["attrs"].get("src", "")[:120] for i in imgs
              if not i["attrs"].get("alt", "").strip()]
    ext_links = []
    for a in by.get("a", []):
        href = a["attrs"].get("href", "")
        if href.startswith("http"):
            netloc = urllib.parse.urlsplit(href).netloc.lower()
            if netloc and netloc.removeprefix("www.") != urllib.parse.urlsplit(url).netloc.lower().removeprefix("www."):
                ext_links.append(netloc)
    citations = [d for d in ext_links if not any(s in d for s in SOCIAL)]
    numbers = re.findall(r"(?<![\w/])\d[\d,.]*\s?(?:%|percent|million|billion|bn|k\b|x\b)", text, re.I)

    rec["extract"] = {
        "title": (titles[0] if titles else None),
        "title_len": len(titles[0]) if titles else 0,
        "meta_description_len": len(desc[0]) if desc else 0,
        "canonical": canon[0] if canon else None,
        "meta_robots": robots_meta[0] if robots_meta else None,
        "h1_count": len(h1s),
        "h1_texts": h1s[:3],
        "h2_count": len(h2s),
        "question_headings": question_headings[:8],
        "list_count": len(by.get("ul", [])) + len(by.get("ol", [])),
        "table_count": len(by.get("table", [])),
        "blockquote_count": len(by.get("blockquote", [])),
        "image_count": len(imgs),
        "images_without_alt": len(no_alt),
        "images_without_alt_sample": no_alt[:5],
        "external_citation_domains": sorted(set(citations))[:12],
        "external_citation_count": len(set(citations)),
        "statistic_mentions": len(numbers),
        "statistic_sample": numbers[:6],
        "has_currency_in_text": bool(re.search(CURRENCY, text)),
        "looks_like_fact_page": looks_like_fact_page(url, text),
        "heading_ids": [d["attrs"]["id"] for d in A.tags(html, ["h2", "h3"]) if d["attrs"].get("id")][:15],
    }
    return rec


def summarise(pages):
    """Cross-page rollups. Facts, not verdicts."""
    ok = [p for p in pages if p.get("status") == 200 and "render" in p]
    if not ok:
        return {"pages_analysed": 0}
    words = sorted(p["render"]["visible_words"] for p in ok)
    titles = [p["extract"]["title"] for p in ok if p["extract"]["title"]]
    fact_pages = [p for p in ok if p["extract"]["looks_like_fact_page"]]
    return {
        "pages_analysed": len(ok),
        "pages_failed": len(pages) - len(ok),
        "median_visible_words": words[len(words) // 2],
        "min_visible_words": words[0],
        "pages_under_120_words": [p["url"] for p in ok if p["render"]["visible_words"] < 120],
        "pages_with_empty_spa_root": [p["url"] for p in ok if p["render"]["empty_spa_root_ids"]],
        "frameworks_seen": sorted({f for p in ok for f in p["render"]["frameworks_detected"]}),
        "duplicate_titles": len(titles) - len(set(titles)),
        "pages_missing_h1": [p["url"] for p in ok if p["extract"]["h1_count"] == 0],
        "pages_multiple_h1": [p["url"] for p in ok if p["extract"]["h1_count"] > 1],
        "pages_missing_meta_description": [p["url"] for p in ok if p["extract"]["meta_description_len"] == 0],
        "pages_missing_canonical": [p["url"] for p in ok if not p["extract"]["canonical"]],
        "pages_with_noindex": [p["url"] for p in ok
                               if (p["extract"]["meta_robots"] or "").lower().find("noindex") >= 0],
        "fact_pages_checked": [p["url"] for p in fact_pages],
        "fact_pages_without_currency_in_text": [p["url"] for p in fact_pages
                                                if not p["extract"]["has_currency_in_text"]],
        "total_images": sum(p["extract"]["image_count"] for p in ok),
        "total_images_without_alt": sum(p["extract"]["images_without_alt"] for p in ok),
        "pages_with_zero_external_citations": [p["url"] for p in ok
                                               if p["extract"]["external_citation_count"] == 0],
        "pages_with_question_headings": [p["url"] for p in ok if p["extract"]["question_headings"]],
        "pages_with_anchor_ids": [p["url"] for p in ok if p["extract"]["heading_ids"]],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="*", help="page URLs to analyse")
    ap.add_argument("--from", dest="src", help="crawl_probe.py JSON; uses its page_shortlist")
    ap.add_argument("--out", help="also write JSON evidence here")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--budget-seconds", type=float, default=90,
                    help="soft wall-clock budget for the per-page sweep (default 90)")
    args = ap.parse_args()

    urls = list(args.urls)
    site = None
    if args.src:
        with open(args.src, encoding="utf-8") as f:
            crawl = json.load(f)
        site = crawl.get("site")
        urls = crawl.get("page_shortlist", []) + urls
    if not urls:
        ap.error("no URLs: pass them directly or use --from evidence/crawl.json")
    seen, ordered = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    ordered = ordered[: args.limit]

    started = time.monotonic()
    deadline = A.Deadline(args.budget_seconds)
    pages, skipped = [], []
    for u in ordered:
        if deadline.expired():
            skipped.append(u)
            continue
        pages.append(analyse(u))
    ev = {"site": site or urllib.parse.urlsplit(ordered[0]).netloc,
          "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
          "probe": "render_probe",
          "summary": summarise(pages),
          "pages": pages,
          "budget_seconds": args.budget_seconds,
          "budget_exceeded": bool(skipped),
          "skipped_by_budget": skipped,
          "elapsed_ms": int((time.monotonic() - started) * 1000)}
    A.emit(ev)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(ev, f, indent=2, ensure_ascii=False, default=str)
    return 0


def _demo():
    """Offline self-check of the rollup logic."""
    pages = [
        {"url": "u1", "status": 200,
         "render": {"visible_words": 12, "empty_spa_root_ids": ["root"], "frameworks_detected": ["react"]},
         "extract": {"title": "Same", "h1_count": 0, "meta_description_len": 0, "canonical": None,
                     "meta_robots": "noindex,follow", "looks_like_fact_page": True,
                     "has_currency_in_text": False, "image_count": 3, "images_without_alt": 3,
                     "external_citation_count": 0, "question_headings": [], "heading_ids": []}},
        {"url": "u2", "status": 200,
         "render": {"visible_words": 900, "empty_spa_root_ids": [], "frameworks_detected": []},
         "extract": {"title": "Same", "h1_count": 2, "meta_description_len": 140, "canonical": "u2",
                     "meta_robots": None, "looks_like_fact_page": False,
                     "has_currency_in_text": True, "image_count": 1, "images_without_alt": 0,
                     "external_citation_count": 4, "question_headings": ["What is X?"],
                     "heading_ids": ["spec"]}},
        {"url": "u3", "status": 404},
    ]
    # render-gap gate: must fire on a real shell, must NOT fire on SSR ------
    shell = '<html><body><div id="__next"></div><script src="/_next/static/x.js"></script></body></html>'
    r_shell = analyse_html("https://x.example/", shell)
    assert r_shell["render"]["spa_shell_suspected"] is True, r_shell["render"]
    assert r_shell["render"]["empty_spa_root_ids"] == ["__next"], r_shell["render"]

    # same mount element, but server-rendered prose in descendants (the stripe.com
    # shape). The tag collector sees no DIRECT text on the root, so only the
    # whole-page word count separates this from a genuine shell.
    # Nested divs, so the outer mount has no DIRECT text -- the exact shape that
    # made stripe.com (1894 server-rendered words) look like an empty shell.
    body = " ".join(f"<div><p>Sentence number {i} with real content in it.</p></div>"
                    for i in range(40))
    ssr = f'<html><body><div id="__next">{body}</div><script src="/_next/static/x.js"></script></body></html>'
    r_ssr = analyse_html("https://y.example/", ssr)
    assert r_ssr["render"]["visible_words"] > SHELL_WORD_LIMIT, r_ssr["render"]["visible_words"]
    assert r_ssr["render"]["spa_shell_suspected"] is False, r_ssr["render"]
    assert r_ssr["render"]["empty_spa_root_ids"] == [], r_ssr["render"]
    assert r_ssr["render"]["mount_elements_seen"] == ["__next"], r_ssr["render"]

    # A bare attribute (<img alt>, no ="value") is real HTML that HTMLParser
    # reports as (name, None). It crashed every probe that reached
    # .get("alt", "").strip() on Wikipedia, Netlify, Fastmail and others in a
    # 38-site sweep -- a single such image took down the whole render probe.
    bare = ('<html><body><img src="/a.png" alt><img src="/b.png"><input disabled>'
            '<div id="root"></div></body></html>')
    r_bare = analyse_html("https://z.example/", bare)
    assert r_bare["extract"]["images_without_alt"] == 2, r_bare["extract"]

    # FP regressions -------------------------------------------------------
    assert not looks_like_fact_page("https://news.ycombinator.com/item?id=1", "a comment thread")
    assert looks_like_fact_page("https://x.example/pricing", "Plans from $9 per month")
    assert not looks_like_fact_page("https://x.example/blog/our-pricing-philosophy",
                                    "thoughts on per month billing")
    assert is_decorative({"src": "/s.gif", "width": "1", "height": "1"})
    assert is_decorative({"src": "/x.png", "role": "presentation"})
    assert not is_decorative({"src": "/shoe.jpg", "width": "600"})
    assert "angular" not in [n for n, p in FRAMEWORK_HINTS
                             if re.search(p, '<script src="/polyfills-42372ed.js">', re.I)]
    assert "angular" in [n for n, p in FRAMEWORK_HINTS
                         if re.search(p, '<html ng-version="17">', re.I)]

    s = summarise(pages)
    assert s["pages_analysed"] == 2 and s["pages_failed"] == 1, s
    assert s["pages_under_120_words"] == ["u1"], s
    assert s["pages_with_empty_spa_root"] == ["u1"], s
    assert s["duplicate_titles"] == 1, s
    assert s["pages_with_noindex"] == ["u1"], s
    assert s["fact_pages_without_currency_in_text"] == ["u1"], s
    assert s["pages_multiple_h1"] == ["u2"] and s["pages_missing_h1"] == ["u1"], s
    assert s["total_images_without_alt"] == 3, s
    assert s["median_visible_words"] == 900, s
    print("render_probe self-check OK")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _demo()
    else:
        sys.exit(main())
