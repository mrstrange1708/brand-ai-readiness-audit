#!/usr/bin/env python3
"""Stage 2-3 evidence: can an AI crawler REACH this site, and is it told where to look?

Collects facts only. Severity and narrative are decided by SKILL.md, not here.

    python3 crawl_probe.py example.com --out evidence/crawl.json --pages 10

Key idea: robots.txt is only half the access story. A CDN/WAF can return 403 to a
bot User-Agent while robots.txt says "Allow: /" and a browser gets 200. That gap is
invisible unless you actually fetch as the bot -- which is what --ua-probe does.
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

BLOCK_STATUSES = {401, 403, 405, 406, 429, 451, 503}


def parse_robots(text):
    """Return {ua_token: {"allow": [...], "disallow": [...]}} plus sitemaps."""
    groups, sitemaps, current = {}, [], []
    if not text:
        return groups, sitemaps
    pending_ua = True
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            if not pending_ua:
                current = []
            current.append(value)
            groups.setdefault(value, {"allow": [], "disallow": []})
            pending_ua = True
        elif field in ("allow", "disallow"):
            pending_ua = False
            for ua in current or ["*"]:
                groups.setdefault(ua, {"allow": [], "disallow": []})[field].append(value)
        elif field == "sitemap":
            sitemaps.append(value)
    return groups, sitemaps


def sitemap_urls(base, sitemap_hints, budget=3):
    """Fetch sitemap(s), including one level of sitemap-index nesting."""
    tried, found, lastmods, results = [], [], 0, []
    queue = list(sitemap_hints) or [urllib.parse.urljoin(base, "/sitemap.xml")]
    if urllib.parse.urljoin(base, "/sitemap.xml") not in queue:
        queue.append(urllib.parse.urljoin(base, "/sitemap.xml"))
    while queue and len(tried) < budget:
        sm = queue.pop(0)
        if sm in tried:
            continue
        tried.append(sm)
        r = A.fetch(sm)
        rec = {"url": sm, "status": r["status"], "bytes": r["bytes"], "error": r["error"]}
        body = r["body"]
        if r["status"] == 200 and body:
            locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", body, re.I | re.S)
            lastmods += len(re.findall(r"<lastmod>", body, re.I))
            rec["loc_count"] = len(locs)
            rec["is_index"] = "<sitemapindex" in body[:2000].lower()
            if rec["is_index"]:
                queue.extend(locs[:2])
            else:
                found.extend(locs)
        results.append(rec)
    # de-dup, keep order
    seen, uniq = set(), []
    for u in found:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return {"documents": results, "url_count": len(uniq), "lastmod_count": lastmods,
            "sample": uniq[:20]}, uniq


def probe_user_agents(url, robots_text):
    """Fetch the same URL as every crawler family. This is the CDN-block detector."""
    rows = []
    for ua in ["browser", "Googlebot"] + A.CITATION_BOTS + A.TRAINING_BOTS:
        r = A.fetch(url, ua=ua)
        rows.append({
            "ua": ua,
            "family": A.UAS[ua][0],
            "status": r["status"],
            "bytes": r["bytes"],
            "error": r["error"],
            "elapsed_ms": r["elapsed_ms"],
            "robots_allows": A.robots_allows(robots_text, ua, url),
            "server": r["headers"].get("server"),
            "x_robots_tag": r["headers"].get("x-robots-tag"),
            "cf_mitigated": r["headers"].get("cf-mitigated"),
        })
    return rows


def derive_access(rows):
    """Deterministic derivation -- still evidence, no severity assigned."""
    ctrl = next((r for r in rows if r["ua"] == "browser"), None)
    ctrl_ok = bool(ctrl and ctrl["status"] == 200)
    out = {"control_status": ctrl["status"] if ctrl else None,
           "robots_disallowed": [], "edge_blocked": [], "transport_failed": []}
    for r in rows:
        if r["ua"] == "browser":
            continue
        if r["robots_allows"] is False:
            out["robots_disallowed"].append({"ua": r["ua"], "family": r["family"]})
        if r["error"]:
            out["transport_failed"].append({"ua": r["ua"], "family": r["family"], "error": r["error"]})
        elif ctrl_ok and r["status"] in BLOCK_STATUSES:
            out["edge_blocked"].append({"ua": r["ua"], "family": r["family"], "status": r["status"],
                                        "server": r["server"], "cf_mitigated": r["cf_mitigated"]})
    for key in ("robots_disallowed", "edge_blocked"):
        out[key + "_citation"] = [x["ua"] for x in out[key] if x["family"] == "citation"]
        out[key + "_training"] = [x["ua"] for x in out[key] if x["family"] == "training"]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="domain or URL, e.g. example.com")
    ap.add_argument("--out", help="also write JSON evidence here")
    ap.add_argument("--pages", type=int, default=10, help="how many page URLs to shortlist (default 10)")
    ap.add_argument("--no-ua-probe", action="store_true", help="skip the per-crawler fetch")
    args = ap.parse_args()

    base = A.norm_base(args.target)
    started = time.monotonic()
    ev = {"site": urllib.parse.urlsplit(base).netloc,
          "base_url": base,
          "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
          "probe": "crawl_probe",
          "tls_trust_source": A.tls_trust_source()}

    # -- homepage / transport ------------------------------------------------
    home = A.fetch(base)
    ev["homepage"] = {"status": home["status"], "final_url": home["final_url"],
                      "bytes": home["bytes"], "elapsed_ms": home["elapsed_ms"],
                      "error": home["error"],
                      "error_class": home.get("error_class"),
                      "error_attribution": home.get("error_attribution"),
                      "https": home["final_url"].startswith("https://"),
                      "redirected": home["final_url"].rstrip("/") != base.rstrip("/"),
                      "x_robots_tag": home["headers"].get("x-robots-tag"),
                      "content_type": home["headers"].get("content-type"),
                      "last_modified": home["headers"].get("last-modified"),
                      "server": home["headers"].get("server")}

    # -- robots.txt ----------------------------------------------------------
    robots_url, rr = A.robots_for(base)
    robots_text = rr["body"] if rr["status"] == 200 else ""
    groups, sitemaps = parse_robots(robots_text)
    ev["robots"] = {"url": robots_url, "status": rr["status"], "present": rr["status"] == 200,
                    "bytes": rr["bytes"], "declares_sitemap": bool(sitemaps),
                    "sitemaps": sitemaps[:5], "ua_groups": sorted(groups.keys())[:40],
                    "blanket_disallow_all": groups.get("*", {}).get("disallow") == ["/"],
                    "excerpt": robots_text[:1200]}

    # -- llms.txt ------------------------------------------------------------
    llms_url = urllib.parse.urljoin(base, "/llms.txt")
    lr = A.fetch(llms_url)
    is_html = "<html" in lr["body"][:600].lower()
    ev["llms_txt"] = {"url": llms_url, "status": lr["status"],
                      "present": lr["status"] == 200 and not is_html,
                      "served_html_instead": lr["status"] == 200 and is_html,
                      "bytes": lr["bytes"],
                      "link_count": len(re.findall(r"\]\(", lr["body"])) if lr["status"] == 200 else 0}

    # -- sitemap -------------------------------------------------------------
    sm_ev, sm_urls = sitemap_urls(base, sitemaps)
    ev["sitemap"] = sm_ev

    # -- per-crawler access probe -------------------------------------------
    if not args.no_ua_probe:
        rows = probe_user_agents(base, robots_text)
        ev["ua_probe"] = rows
        ev["access"] = derive_access(rows)

    # -- shortlist pages for the downstream probes ---------------------------
    candidates = list(sm_urls)
    if home["status"] == 200:
        for l in A.internal_links(home["body"], base, limit=120):
            if l["url"] not in candidates:
                candidates.append(l["url"])
    allowed = [u for u in candidates if A.robots_allows(robots_text, "*", u) is not False]
    ev["robots_excluded_candidates"] = len(candidates) - len(allowed)

    # Prefer depth and variety over homepage-adjacent noise.
    def score(u):
        p = urllib.parse.urlsplit(u).path.lower()
        depth = len([s for s in p.split("/") if s])
        interesting = any(k in p for k in ("product", "pricing", "price", "plan", "docs", "blog",
                                           "news", "about", "faq", "service", "solution", "case"))
        return (0 if interesting else 1, abs(depth - 2))

    shortlist, seen_dirs = [], set()
    for u in sorted(set(allowed), key=score):
        top = urllib.parse.urlsplit(u).path.strip("/").split("/")[0]
        if top in seen_dirs and len(shortlist) > args.pages // 2:
            continue
        seen_dirs.add(top)
        shortlist.append(u)
        if len(shortlist) >= args.pages:
            break
    if base not in shortlist:
        shortlist.insert(0, base)
    ev["page_shortlist"] = shortlist[: args.pages]
    ev["discovered_url_count"] = len(set(candidates))
    ev["elapsed_ms"] = int((time.monotonic() - started) * 1000)

    A.emit(ev)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(ev, f, indent=2, ensure_ascii=False, default=str)
    return 0


def _demo():
    """Offline self-check of the pure logic."""
    g, sm = parse_robots("""
User-agent: *
Disallow: /admin
Sitemap: https://x.example/sitemap.xml

User-agent: GPTBot
User-agent: CCBot
Disallow: /
""")
    assert g["*"]["disallow"] == ["/admin"], g
    assert g["GPTBot"]["disallow"] == ["/"] and g["CCBot"]["disallow"] == ["/"], g
    assert sm == ["https://x.example/sitemap.xml"], sm

    rows = [
        {"ua": "browser", "family": "control", "status": 200, "error": None, "robots_allows": True,
         "server": None, "cf_mitigated": None},
        {"ua": "OAI-SearchBot", "family": "citation", "status": 403, "error": None,
         "robots_allows": True, "server": "cloudflare", "cf_mitigated": "challenge"},
        {"ua": "GPTBot", "family": "training", "status": 200, "error": None, "robots_allows": False,
         "server": None, "cf_mitigated": None},
    ]
    d = derive_access(rows)
    # robots says yes, browser gets 200, bot gets 403 -> edge block, the invisible one
    assert d["edge_blocked_citation"] == ["OAI-SearchBot"], d
    assert d["robots_disallowed_training"] == ["GPTBot"], d
    assert d["edge_blocked_training"] == [] and d["robots_disallowed_citation"] == [], d
    print("crawl_probe self-check OK")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _demo()
    else:
        sys.exit(main())
