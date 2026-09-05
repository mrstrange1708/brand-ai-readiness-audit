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
    ("angular", r"ng-version|/polyfills[.-][0-9a-z]+\.js"),
    ("gatsby", r"gatsby|___gatsby"),
    ("svelte", r"svelte-[0-9a-z]{6}"),
]
CURRENCY = r"(?:[$€£¥₹]|\b(?:USD|EUR|GBP|INR|JPY|AUD|CAD)\b)\s?\d"
SOCIAL = ("facebook.", "twitter.", "x.com", "instagram.", "linkedin.", "youtube.", "tiktok.",
          "pinterest.", "t.co", "threads.")
# Page kinds where a missing hard fact (price, spec) is materially different from
# a missing fact on, say, an About page.
FACT_PATHS = ("product", "pricing", "price", "plan", "shop", "buy", "store", "item", "sku")


def analyse(url):
    r = A.fetch(url)
    rec = {"url": url, "status": r["status"], "final_url": r["final_url"],
           "bytes": r["bytes"], "elapsed_ms": r["elapsed_ms"], "error": r["error"]}
    if r["status"] != 200 or not r["body"]:
        return rec
    html = r["body"]
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
    frameworks = [n for n, pat in FRAMEWORK_HINTS if re.search(pat, html, re.I)]
    noscript_text = " ".join(A.visible_text(n["text"]) for n in by.get("noscript", []))
    rec["render"] = {
        "visible_words": words,
        "html_bytes": len(html),
        "text_to_html_ratio": round(len(text) / max(len(html), 1), 4),
        "empty_spa_root_ids": [i for i in spa_roots if i],
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
    imgs = by.get("img", [])
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
    path = urllib.parse.urlsplit(url).path.lower()

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
        "looks_like_fact_page": any(k in path for k in FACT_PATHS),
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
    pages = [analyse(u) for u in ordered]
    ev = {"site": site or urllib.parse.urlsplit(ordered[0]).netloc,
          "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
          "probe": "render_probe",
          "summary": summarise(pages),
          "pages": pages,
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
