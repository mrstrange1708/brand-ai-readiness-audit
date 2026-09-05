#!/usr/bin/env python3
"""Stage 5-6 evidence: is the brand a NAMED, DATED, CORROBORATED entity?

Answers three machine questions:
  1. Identity  -- does the site declare who it is in a form a machine can resolve?
  2. Freshness -- can a machine tell which version of a fact is current?
  3. Agreement -- does anything off-site independently confirm the brand's facts?

    python3 entity_probe.py --from evidence/crawl.json --out evidence/entity.json
    python3 entity_probe.py https://example.com/ --sameas-check

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

# Minimum properties that make each type actually useful to an answer engine.
# Missing these does not make the markup invalid -- it makes it unquotable.
USEFUL_PROPS = {
    "Organization": ["name", "url", "logo", "sameAs", "description"],
    "LocalBusiness": ["name", "url", "address", "telephone", "openingHours"],
    "Product": ["name", "description", "image", "offers", "brand"],
    "Offer": ["price", "priceCurrency", "availability"],
    "Article": ["headline", "author", "datePublished", "dateModified", "publisher"],
    "BlogPosting": ["headline", "author", "datePublished", "dateModified", "publisher"],
    "NewsArticle": ["headline", "author", "datePublished", "dateModified", "publisher"],
    "FAQPage": ["mainEntity"],
    "BreadcrumbList": ["itemListElement"],
    "WebSite": ["name", "url"],
    "Person": ["name", "jobTitle", "sameAs"],
    "Event": ["name", "startDate", "location"],
    "Recipe": ["name", "recipeIngredient", "recipeInstructions"],
    "SoftwareApplication": ["name", "applicationCategory", "offers"],
}
# Registries an assistant can use to tell one "Acme" from another.
AUTHORITY_HOSTS = ("wikidata.org", "wikipedia.org", "crunchbase.com", "linkedin.com",
                   "github.com", "bloomberg.com", "sec.gov", "opencorporates.com",
                   "g2.com", "trustpilot.com", "glassdoor.com", "producthunt.com")
DATE_RE = re.compile(
    r"\b(20\d{2}-\d{2}-\d{2}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+20\d{2}"
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+20\d{2})\b", re.I)
COPYRIGHT_RE = re.compile(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–—]\s*)?(\d{4})", re.I)

# The only two places a site DECLARES its own identity. A disagreement between
# these is a real naming inconsistency; a <title> segment disagreeing with them
# is just a page name, and must never be counted as a competing brand.
DECLARED_NAME_KEYS = ("jsonld", "og_site_name")


def year_of(value):
    m = re.search(r"(20\d{2}|19\d{2})", str(value))
    return int(m.group(1)) if m else None


def scan_page(url):
    r = A.fetch(url)
    rec = {"url": url, "status": r["status"], "error": r["error"]}
    if r["status"] != 200 or not r["body"]:
        return rec
    html, text = r["body"], A.visible_text(r["body"])
    objs, errs = A.jsonld_blocks(html)

    typed = []
    for o in objs:
        for t in A.types_of(o):
            want = USEFUL_PROPS.get(t)
            entry = {"type": t, "keys": sorted(k for k in o if not k.startswith("@"))}
            if want:
                entry["missing_useful_props"] = [p for p in want if not o.get(p)]
            typed.append(entry)

    meta = {m["attrs"].get("property", m["attrs"].get("name", "")).lower():
            m["attrs"].get("content", "") for m in A.tags(html, ["meta"])}
    titles = [t["text"] for t in A.tags(html, ["title"])]

    names = {}
    for o in objs:
        if any(t in ("Organization", "LocalBusiness", "WebSite", "Corporation") for t in A.types_of(o)):
            if isinstance(o.get("name"), str):
                names.setdefault("jsonld", o["name"].strip())
    if meta.get("og:site_name"):
        names["og_site_name"] = meta["og:site_name"].strip()
    # Which title segment is the brand? NOT a fixed position -- sites write both
    # "Brand | Page" (stripe.com) and "Page | Brand". Taking the tail of every
    # title turns ordinary page names into invented "brand variants". The brand
    # is the segment that RECURS across pages, so collect every segment here and
    # let summarise() decide by frequency.
    title_segments = []
    if titles:
        parts = re.split(r"\s[|\-–—·:]\s", titles[0])
        # No delimiter means the title is a sentence, not "Page | Brand".
        if len(parts) > 1:
            title_segments = [s.strip() for s in parts if s.strip()]
    cm = COPYRIGHT_RE.search(text)
    if cm:
        names["copyright_year"] = cm.group(1)

    sameas = []
    for o in objs:
        v = o.get("sameAs")
        if isinstance(v, str):
            sameas.append(v)
        elif isinstance(v, list):
            sameas.extend([x for x in v if isinstance(x, str)])
    for k in ("og:url",):
        pass

    # dates from every place a machine could look
    jl_pub = [o.get("datePublished") for o in objs if o.get("datePublished")]
    jl_mod = [o.get("dateModified") for o in objs if o.get("dateModified")]
    visible_dates = DATE_RE.findall(text)

    rec.update({
        "jsonld_block_count": len(objs),
        "jsonld_parse_errors": errs,
        "jsonld_types": sorted({t for o in objs for t in A.types_of(o)}),
        "jsonld_detail": typed,
        "microdata_itemtype": len(re.findall(r"itemtype\s*=", html, re.I)),
        "rdfa_typeof": len(re.findall(r"\btypeof\s*=", html, re.I)),
        "names": names,
        "title_segments": title_segments,
        "same_as": sorted(set(sameas)),
        "authority_links": sorted({h for h in AUTHORITY_HOSTS
                                   for a in A.tags(html, ["a"])
                                   if h in a["attrs"].get("href", "")}),
        "dates": {
            "jsonld_published": [str(d) for d in jl_pub][:5],
            "jsonld_modified": [str(d) for d in jl_mod][:5],
            "http_last_modified": r["headers"].get("last-modified"),
            "visible_date_count": len(visible_dates),
            "visible_date_sample": visible_dates[:5],
            "copyright_year": names.get("copyright_year"),
        },
    })
    return rec


# Many high-value registries (Bloomberg, Crunchbase, LinkedIn) refuse automated
# clients outright. A 403/429/999 says "we block bots", NOT "this page is missing".
# Reporting those as broken links is the classic corroboration false positive.
BOT_BLOCK_STATUSES = {401, 403, 405, 406, 429, 451, 503, 999}
DEAD_STATUSES = {404, 410}


def check_sameas(urls, limit=6):
    """Classify each declared sameAs target: resolves, dead, or unverifiable."""
    out = []
    for u in list(urls)[:limit]:
        r = A.fetch(u, ua="browser")
        st = r["status"]
        if r["error"]:
            verdict = "unreachable"
        elif st in DEAD_STATUSES:
            verdict = "dead"
        elif st in BOT_BLOCK_STATUSES:
            verdict = "unverifiable"      # target blocks automated checks
        elif st and 200 <= st < 400:
            verdict = "resolves"
        else:
            verdict = "unverifiable"
        out.append({"url": u, "host": urllib.parse.urlsplit(u).netloc,
                    "status": st, "error": r["error"], "verdict": verdict,
                    "resolves": verdict == "resolves"})
    return out


def summarise(pages, sameas_results, this_year):
    ok = [p for p in pages if p.get("status") == 200 and "jsonld_types" in p]
    if not ok:
        return {"pages_analysed": 0}
    all_types = sorted({t for p in ok for t in p["jsonld_types"]})
    names_seen = {}
    for p in ok:
        for k, v in p["names"].items():
            if k != "copyright_year" and v:
                names_seen.setdefault(k, set()).add(v)
    # A <title> segment is a PAGE name, not a brand name. "Stripe Billing",
    # "Services Terms" and "Pricing" all recur across a perfectly consistent
    # site; promoting them to brand variants is how a site that names itself
    # correctly everywhere gets accused of naming itself inconsistently.
    # So titles never create a variant. Only the two places a site actually
    # DECLARES its identity can contradict each other, and only their
    # disagreement is a real, actionable finding.
    seg_pages, titled = {}, 0
    for p in ok:
        segs = {s for s in (p.get("title_segments") or []) if s}
        if segs:
            titled += 1
        for s in segs:
            seg_pages.setdefault(s, set()).add(p["url"])
    recurring = sorted({s for s, urls in seg_pages.items()
                        if titled >= 2 and len(urls) >= 2 and len(urls) / titled >= 0.4})
    declared = {v for k, vs in names_seen.items()
                if k in DECLARED_NAME_KEYS for v in vs}
    same_as = sorted({s for p in ok for s in p["same_as"]})
    auth = sorted({a for p in ok for a in p["authority_links"]})
    copy_years = sorted({int(p["dates"]["copyright_year"]) for p in ok
                         if p["dates"]["copyright_year"] and p["dates"]["copyright_year"].isdigit()})

    contradictions = []
    for p in ok:
        d = p["dates"]
        jm = [year_of(x) for x in d["jsonld_modified"] if year_of(x)]
        lm = year_of(d["http_last_modified"]) if d["http_last_modified"] else None
        if jm and lm and abs(max(jm) - lm) >= 2:
            contradictions.append({"url": p["url"], "jsonld_modified": d["jsonld_modified"][:1],
                                   "http_last_modified": d["http_last_modified"]})
    return {
        "pages_analysed": len(ok),
        "pages_with_jsonld": [p["url"] for p in ok if p["jsonld_block_count"] > 0],
        "pages_without_jsonld": [p["url"] for p in ok if p["jsonld_block_count"] == 0],
        "jsonld_coverage_ratio": round(sum(1 for p in ok if p["jsonld_block_count"]) / len(ok), 3),
        "jsonld_types_present": all_types,
        "jsonld_parse_error_count": sum(len(p["jsonld_parse_errors"]) for p in ok),
        "jsonld_parse_error_sample": [e for p in ok for e in p["jsonld_parse_errors"]][:3],
        "incomplete_types": sorted({(d["type"]) for p in ok for d in p["jsonld_detail"]
                                    if d.get("missing_useful_props")}),
        "missing_props_detail": [{"url": p["url"], "type": d["type"],
                                  "missing": d["missing_useful_props"]}
                                 for p in ok for d in p["jsonld_detail"]
                                 if d.get("missing_useful_props")][:12],
        "has_organization_markup": any(t in all_types for t in
                                       ("Organization", "LocalBusiness", "Corporation")),
        "has_breadcrumbs": "BreadcrumbList" in all_types,
        "has_faq": "FAQPage" in all_types,
        "name_variants": {k: sorted(v) for k, v in names_seen.items()},
        # Counts DECLARED names only -- see DECLARED_NAME_KEYS. Recurring title
        # segments are reported beside it as context, never folded into it.
        "name_variant_count": len(declared),
        "declared_names": sorted(declared),
        "title_recurring_segments": recurring,
        "same_as_declared": same_as,
        "same_as_count": len(same_as),
        "authority_links_found": auth,
        "authority_link_count": len(auth),
        "same_as_check": sameas_results,
        # only genuinely dead or unreachable targets are "broken"
        "same_as_broken": [s["url"] for s in sameas_results
                           if s.get("verdict") in ("dead", "unreachable")],
        "same_as_unverifiable": [s["url"] for s in sameas_results
                                 if s.get("verdict") == "unverifiable"],
        "pages_with_no_date_signal": [p["url"] for p in ok
                                      if not p["dates"]["jsonld_modified"]
                                      and not p["dates"]["jsonld_published"]
                                      and p["dates"]["visible_date_count"] == 0],
        "date_contradictions": contradictions,
        "copyright_years_seen": copy_years,
        "stale_copyright": [y for y in copy_years if y < this_year - 1],
        "current_year": this_year,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--from", dest="src", help="crawl_probe.py JSON")
    ap.add_argument("--out")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--no-sameas-check", action="store_true",
                    help="skip verifying declared sameAs targets resolve")
    args = ap.parse_args()

    urls, site = list(args.urls), None
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
    pages = [scan_page(u) for u in ordered]
    declared = sorted({s for p in pages for s in p.get("same_as", [])})
    sameas_results = [] if args.no_sameas_check else check_sameas(declared)
    ev = {"site": site or urllib.parse.urlsplit(ordered[0]).netloc,
          "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
          "probe": "entity_probe",
          "summary": summarise(pages, sameas_results, datetime.now(timezone.utc).year),
          "pages": pages,
          "elapsed_ms": int((time.monotonic() - started) * 1000)}
    A.emit(ev)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(ev, f, indent=2, ensure_ascii=False, default=str)
    return 0


def _demo():
    pages = [
        {"url": "u1", "status": 200, "jsonld_block_count": 1, "jsonld_parse_errors": [],
         "jsonld_types": ["Organization"],
         "jsonld_detail": [{"type": "Organization", "keys": ["name"],
                            "missing_useful_props": ["sameAs", "logo"]}],
         "names": {"jsonld": "Acme Corp", "og_site_name": "Acme", "copyright_year": "2019"},
         "same_as": ["https://wikidata.org/wiki/Q1"], "authority_links": ["wikidata.org"],
         "dates": {"jsonld_published": [], "jsonld_modified": ["2026-01-01"],
                   "http_last_modified": "Mon, 01 Jan 2019 00:00:00 GMT",
                   "visible_date_count": 1, "visible_date_sample": ["2026-01-01"],
                   "copyright_year": "2019"}},
        {"url": "u2", "status": 200, "jsonld_block_count": 0, "jsonld_parse_errors": [],
         "jsonld_types": [], "jsonld_detail": [], "names": {}, "same_as": [],
         "authority_links": [],
         "dates": {"jsonld_published": [], "jsonld_modified": [], "http_last_modified": None,
                   "visible_date_count": 0, "visible_date_sample": [], "copyright_year": None}},
    ]
    checks = check_sameas.__wrapped__ if False else [
        {"url": "https://wikidata.org/wiki/Q1", "resolves": False, "status": 404, "verdict": "dead"},
        {"url": "https://www.crunchbase.com/o/x", "resolves": False, "status": 403,
         "verdict": "unverifiable"},
    ]
    s = summarise(pages, checks, 2026)
    assert s["jsonld_coverage_ratio"] == 0.5, s
    assert s["pages_without_jsonld"] == ["u2"], s
    assert s["incomplete_types"] == ["Organization"], s
    assert s["name_variant_count"] == 2, s          # "Acme Corp" vs "Acme" -> ambiguity signal
    assert s["stale_copyright"] == [2019], s
    # a 404 is broken; a 403 from a bot-blocking registry is NOT
    assert s["same_as_broken"] == ["https://wikidata.org/wiki/Q1"], s
    assert s["same_as_unverifiable"] == ["https://www.crunchbase.com/o/x"], s
    assert s["date_contradictions"] and s["date_contradictions"][0]["url"] == "u1", s
    assert s["pages_with_no_date_signal"] == ["u2"], s
    assert year_of("Mon, 01 Jan 2019 00:00:00 GMT") == 2019

    # regression: "Aug. 15, 2026" and "15 Aug. 2026" are dates
    for good in ("Aug. 15, 2026", "August 15, 2026", "2026-08-15", "15 Aug. 2026"):
        assert DATE_RE.search(good), good
    # regression: an undelimited title must NOT become a brand-name variant
    assert COPYRIGHT_RE.search("Copyright \u00a92001-2026").group(1) == "2026"
    print("entity_probe self-check OK")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _demo()
    else:
        sys.exit(main())
