#!/usr/bin/env python3
"""Stage 8 evidence: the visitor arrived mid-journey. Can they land on the fact?

An AI-referred visitor is pre-qualified -- an assistant already told them the
answer and they clicked to confirm it. They do not browse. They bounce when the
promised fact is not reachable from where the link dropped them.

So this probe measures reachability of facts, not generic "UX quality":
  - can a fact be DEEP-LINKED (stable anchor ids) or only a whole page?
  - how many hops from the entry point to a page that states a hard fact?
  - does the landing page ORIENT (say who/what, in text, above the fold)?
  - does anything BLOCK the first paint (consent wall, modal, scroll lock)?
  - can a lost visitor SELF-SERVE (site search, FAQ, breadcrumbs)?

    python3 continuity_probe.py --from evidence/crawl.json --out evidence/engagement.json

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

HARD_FACT = re.compile(
    r"(?:[$€£¥₹]|\b(?:USD|EUR|GBP|INR)\b)\s?\d"                     # price
    r"|\b\d+(?:\.\d+)?\s?(?:GB|TB|MB|kg|g|mm|cm|inch|\"|hrs?|hours?|days?|users?|seats?)\b"
    r"|\b(?:in stock|out of stock|available now|free trial|per month|/mo|per year|/yr)\b",
    re.I)
GENERIC_H1 = re.compile(r"^\s*(welcome|home|homepage|untitled|hello|index)\b", re.I)
CLASS_ATTR = re.compile(r"class\s*=\s*[\"']([^\"']*)[\"']", re.I)
BLOCKER_WORDS = ("cookie", "consent", "gdpr", "modal", "overlay", "popup",
                 "interstitial", "paywall", "age-gate", "agegate")


def blocker_hints(html):
    """Every blocker keyword present in any class attribute, not just the first
    one a greedy regex happens to land on."""
    hits = set()
    for m in CLASS_ATTR.finditer(html):
        val = m.group(1).lower()
        for w in BLOCKER_WORDS:
            if w in val:
                hits.add(w)
    return sorted(hits)
SCROLL_LOCK = re.compile(r"(overflow\s*:\s*hidden[^}]*)?\b(no-?scroll|scroll-?lock|modal-open)\b", re.I)
SEARCH_PAT = re.compile(r"type\s*=\s*[\"']search[\"']|role\s*=\s*[\"']search[\"']|"
                        r"name\s*=\s*[\"'](?:q|s|query|search)[\"']", re.I)


def page_facts(url, html, text):
    heads = A.tags(html, ["h1", "h2", "h3"])
    anchored = [h["attrs"]["id"] for h in heads if h["attrs"].get("id")]
    h1s = [h["text"] for h in heads if h["tag"] == "h1" and h["text"]]
    hash_links = [a["attrs"].get("href", "") for a in A.tags(html, ["a"])
                  if a["attrs"].get("href", "").startswith("#")
                  and a["attrs"].get("href", "") != "#"]
    facts = HARD_FACT.findall(text)
    # "Above the fold" proxy: the first 400 characters of machine-visible text.
    lede = text[:400]
    return {
        "visible_words": len(text.split()),
        "h1": h1s[0] if h1s else None,
        "h1_generic": bool(h1s and GENERIC_H1.search(h1s[0])),
        "heading_anchor_ids": anchored[:20],
        "heading_anchor_count": len(anchored),
        "in_page_anchor_links": len(set(hash_links)),
        "states_hard_fact": bool(facts),
        "hard_fact_sample": [f if isinstance(f, str) else str(f) for f in facts[:5]],
        "lede_words": len(lede.split()),
        "lede_excerpt": lede[:220],
        "question_headings": [h["text"] for h in heads if h["text"].strip().endswith("?")][:8],
        "has_site_search": bool(SEARCH_PAT.search(html)),
        "has_breadcrumb_markup": ('"BreadcrumbList"' in html) or bool(
            re.search(r"class\s*=\s*[\"'][^\"']*breadcrumb", html, re.I)),
        "blocker_hints": blocker_hints(html)[:6],
        "scroll_lock_hint": bool(SCROLL_LOCK.search(html)),
        "skip_link": bool(re.search(r"skip\s*(to|-)\s*(main|content)", html, re.I)),
        "script_count": len(A.tags(html, ["script"])),
        "html_bytes": len(html),
    }


def walk(base, max_pages, max_depth):
    """Bounded BFS from the entry point. Records the hop count at which a hard fact
    first becomes readable -- the visitor's real distance to the answer."""
    seen, queue, pages = {base}, [(base, 0)], []
    while queue and len(pages) < max_pages:
        url, depth = queue.pop(0)
        r = A.fetch(url)
        if r["status"] != 200 or not r["body"]:
            pages.append({"url": url, "depth": depth, "status": r["status"], "error": r["error"]})
            continue
        text = A.visible_text(r["body"])
        rec = {"url": url, "depth": depth, "status": r["status"], "elapsed_ms": r["elapsed_ms"]}
        rec.update(page_facts(url, r["body"], text))
        pages.append(rec)
        if depth < max_depth:
            for l in A.internal_links(r["body"], url, limit=60):
                if l["url"] not in seen and len(seen) < max_pages * 3:
                    seen.add(l["url"])
                    queue.append((l["url"], depth + 1))
    return pages


def summarise(pages):
    ok = [p for p in pages if p.get("status") == 200 and "visible_words" in p]
    if not ok:
        return {"pages_analysed": 0}
    fact_pages = [p for p in ok if p["states_hard_fact"]]
    entry = ok[0]
    return {
        "pages_analysed": len(ok),
        "entry_url": entry["url"],
        "entry_h1": entry["h1"],
        "entry_h1_generic": entry["h1_generic"],
        "entry_lede_words": entry["lede_words"],
        "entry_lede_excerpt": entry["lede_excerpt"],
        "entry_states_hard_fact": entry["states_hard_fact"],
        "hops_to_first_hard_fact": min((p["depth"] for p in fact_pages), default=None),
        "pages_stating_hard_facts": [p["url"] for p in fact_pages][:10],
        "hard_fact_page_ratio": round(len(fact_pages) / len(ok), 3),
        "pages_with_anchor_ids": [p["url"] for p in ok if p["heading_anchor_count"] > 0],
        "anchor_id_coverage_ratio": round(
            sum(1 for p in ok if p["heading_anchor_count"] > 0) / len(ok), 3),
        "deep_linkable_fact_pages": [p["url"] for p in fact_pages if p["heading_anchor_count"] > 0],
        "fact_pages_without_anchors": [p["url"] for p in fact_pages if p["heading_anchor_count"] == 0],
        "pages_with_site_search": [p["url"] for p in ok if p["has_site_search"]],
        "site_search_present": any(p["has_site_search"] for p in ok),
        "breadcrumbs_present": any(p["has_breadcrumb_markup"] for p in ok),
        "pages_with_question_headings": [p["url"] for p in ok if p["question_headings"]],
        "pages_with_blocker_hints": [{"url": p["url"], "hints": p["blocker_hints"]}
                                     for p in ok if p["blocker_hints"]][:8],
        "pages_with_scroll_lock_hint": [p["url"] for p in ok if p["scroll_lock_hint"]][:8],
        "pages_missing_skip_link": [p["url"] for p in ok if not p["skip_link"]][:8],
        "thin_pages": [p["url"] for p in ok if p["visible_words"] < 120],
        "median_script_count": sorted(p["script_count"] for p in ok)[len(ok) // 2],
        "median_html_kb": round(sorted(p["html_bytes"] for p in ok)[len(ok) // 2] / 1024, 1),
        "max_depth_reached": max(p["depth"] for p in ok),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", help="entry URL or domain")
    ap.add_argument("--from", dest="src", help="crawl_probe.py JSON (uses base_url as entry)")
    ap.add_argument("--out")
    ap.add_argument("--max-pages", type=int, default=12)
    ap.add_argument("--max-depth", type=int, default=2)
    args = ap.parse_args()

    site = None
    if args.src:
        with open(args.src, encoding="utf-8") as f:
            crawl = json.load(f)
        base, site = crawl["base_url"], crawl.get("site")
    elif args.target:
        base = A.norm_base(args.target)
    else:
        ap.error("pass a target or --from evidence/crawl.json")

    started = time.monotonic()
    pages = walk(base, args.max_pages, args.max_depth)
    ev = {"site": site or urllib.parse.urlsplit(base).netloc,
          "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
          "probe": "continuity_probe",
          "entry_url": base,
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
    html = ('<h1>Welcome</h1><h2 id="pricing">Pricing</h2><p>Plans from $29 per month.</p>'
            '<h3>What is included?</h3><a href="#pricing">jump</a>'
            '<div class="cookie-consent-banner">ok</div><input type="search" name="q">'
            '<script></script>')
    text = A.visible_text(html)
    f = page_facts("https://x.example/", html, text)
    assert f["h1_generic"] is True, f
    assert f["heading_anchor_ids"] == ["pricing"], f
    assert f["states_hard_fact"] is True and f["in_page_anchor_links"] == 1, f
    assert f["has_site_search"] is True, f
    assert f["blocker_hints"] == ["consent", "cookie"], f  # both hints, not just one
    assert f["question_headings"] == ["What is included?"], f

    pages = [
        {"url": "e", "depth": 0, "status": 200, "visible_words": 300, "h1": "Welcome",
         "h1_generic": True, "heading_anchor_ids": [], "heading_anchor_count": 0,
         "in_page_anchor_links": 0, "states_hard_fact": False, "hard_fact_sample": [],
         "lede_words": 40, "lede_excerpt": "...", "question_headings": [], "has_site_search": False,
         "has_breadcrumb_markup": False, "blocker_hints": ["cookie"], "scroll_lock_hint": False,
         "skip_link": False, "script_count": 10, "html_bytes": 2048},
        {"url": "p", "depth": 2, "status": 200, "visible_words": 500, "h1": "Pricing",
         "h1_generic": False, "heading_anchor_ids": [], "heading_anchor_count": 0,
         "in_page_anchor_links": 0, "states_hard_fact": True, "hard_fact_sample": ["$29"],
         "lede_words": 40, "lede_excerpt": "...", "question_headings": ["Why?"],
         "has_site_search": True, "has_breadcrumb_markup": True, "blocker_hints": [],
         "scroll_lock_hint": False, "skip_link": True, "script_count": 4, "html_bytes": 4096},
    ]
    s = summarise(pages)
    assert s["hops_to_first_hard_fact"] == 2, s          # answer is 2 clicks deep
    assert s["fact_pages_without_anchors"] == ["p"], s   # cannot be deep-linked
    assert s["entry_h1_generic"] is True and s["entry_states_hard_fact"] is False, s
    assert s["anchor_id_coverage_ratio"] == 0.0, s
    assert s["site_search_present"] is True and s["breadcrumbs_present"] is True, s
    assert s["pages_with_blocker_hints"][0]["url"] == "e", s
    print("continuity_probe self-check OK")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _demo()
    else:
        sys.exit(main())
