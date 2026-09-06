#!/usr/bin/env python3
"""Stage 2-3 evidence: can an AI crawler REACH this site, and is it told where to look?

Collects facts only. Severity and narrative are decided by SKILL.md, not here.

    python3 crawl_probe.py example.com --out evidence/crawl.json --pages 10

Key idea: robots.txt is only half the access story. A CDN/WAF can return 403 to a
bot User-Agent while robots.txt says "Allow: /" and a browser gets 200. That gap is
invisible unless you actually fetch as the bot -- which is what --ua-probe does.
"""

import argparse
import html
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
            # The spec says <loc> is absolute; real sitemaps ship relative
            # paths and XML-escaped ampersands anyway. Resolve against the
            # sitemap's own URL and keep only http(s), because an unresolved
            # path only fails much later, inside a different probe.
            locs = [urllib.parse.urljoin(sm, html.unescape(x)) for x in
                    re.findall(r"<loc>\s*(.*?)\s*</loc>", body, re.I | re.S)]
            locs = [u for u in locs if u.startswith(("http://", "https://"))]
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


_UA_PROBE_TRIP_AFTER = 2  # consecutive transport-level failures on this SAME url


def probe_user_agents(url, robots_text, deadline=None):
    """Fetch the same URL as every crawler family. This is the CDN-block detector.

    Circuit breaker: if the last _UA_PROBE_TRIP_AFTER fetches of this exact URL
    each failed at the transport level (no HTTP status at all -- a real DNS/TLS/
    reset/timeout, not a 403 or 404), further identical requests are skipped
    rather than each paying a full timeout. Seen live on gnu.org: 14 sequential
    per-UA fetches of one dead connection cost ~140s of a ~180s crawl_probe run.
    Scoped to fetches of THIS url only, not the host in general -- a robots.txt
    or llms.txt 404 elsewhere must never suppress this sweep, which is the
    marketplace's core training-vs-citation signal.
    """
    rows = []
    consecutive_transport_failures = 0
    for ua in ["browser", "Googlebot"] + A.CITATION_BOTS + A.TRAINING_BOTS:
        if consecutive_transport_failures >= _UA_PROBE_TRIP_AFTER or (deadline and deadline.expired()):
            reason = ("deadline" if (deadline and deadline.expired()) else "transport")
            rows.append({"ua": ua, "family": A.UAS[ua][0], "status": None, "bytes": 0,
                        "error": (f"skipped: soft time budget spent probing this site -- a slow "
                                  f"but alive origin, not a code fault." if reason == "deadline" else
                                  f"skipped: the last {_UA_PROBE_TRIP_AFTER} fetches of this url "
                                  f"failed at the transport level, so further identical requests "
                                  f"would only add latency, not information."),
                        "elapsed_ms": 0, "robots_allows": A.robots_allows(robots_text, ua, url),
                        "server": None, "x_robots_tag": None, "cf_mitigated": None})
            continue
        r = A.fetch(url, ua=ua)
        consecutive_transport_failures = (
            consecutive_transport_failures + 1 if (r["error"] and r["status"] is None) else 0)
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
    ap.add_argument("--budget-seconds", type=float, default=90,
                    help="soft wall-clock budget for the per-crawler sweep (default 90)")
    args = ap.parse_args()

    base = A.norm_base(args.target)
    started = time.monotonic()
    deadline = A.Deadline(args.budget_seconds)
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
        rows = probe_user_agents(base, robots_text, deadline=deadline)
        ev["ua_probe"] = rows
        ev["access"] = derive_access(rows)
        # The homepage fetch above used one synthetic UA string. Some WAFs
        # individually challenge that exact request shape while allowlisting
        # recognised crawlers by verified signature -- so a non-200 there is
        # not proof the page is down if the crawlers this audit is actually
        # about reached the identical URL, moments apart, and got 200. Without
        # this, a single flaky/challenged request manufactures a "site is
        # unreachable" critical that the rest of this same evidence file
        # directly contradicts.
        #
        # Deliberately CITATION family only, not "any UA". Seen live: one
        # training bot (Google-Extended) got 200 from patagonia.com while
        # EVERY citation bot got 404 from a different backend entirely
        # (Akamai, 10 bytes -- not the real site). That is a genuine, different
        # defect -- citation crawlers dead-ended -- not evidence the site is
        # fine. Only a citation-family success answers the question this audit
        # exists to ask: can this site ever be cited.
        ev["homepage"]["corroborated_by"] = sorted({
            r["ua"] for r in rows if r["family"] == "citation" and r["status"] == 200})

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
    ev["budget_seconds"] = args.budget_seconds
    ev["budget_exceeded"] = deadline.expired()

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

    # A relative <loc> must be absolutised here, not blow up two probes later.
    body = ("<urlset><url><loc>/a/b</loc></url>"
            "<url><loc>https://x.test/c?d=1&amp;e=2</loc></url>"
            "<url><loc>ftp://x.test/skip</loc></url></urlset>")
    locs = [urllib.parse.urljoin("https://x.test/sitemap.xml", html.unescape(u))
            for u in re.findall(r"<loc>\s*(.*?)\s*</loc>", body, re.I | re.S)]
    locs = [u for u in locs if u.startswith(("http://", "https://"))]
    assert locs == ["https://x.test/a/b", "https://x.test/c?d=1&e=2"], locs

    # fetch() promises it never raises. A malformed URL must come back as data.
    bad = A.fetch("/relative/path")
    assert bad["error"] and bad["status"] is None, bad

    # corroborated_by must require CITATION family specifically. Seen live on
    # patagonia.com: one training bot (Google-Extended) got 200 while every
    # citation bot got 404 from a different backend -- that must NOT read as
    # "corroborated", or a real citation dead-end gets reported as fine.
    rows_train_only = [
        {"ua": "browser", "family": "control", "status": 403},
        {"ua": "Google-Extended", "family": "training", "status": 200},
        {"ua": "OAI-SearchBot", "family": "citation", "status": 404},
        {"ua": "PerplexityBot", "family": "citation", "status": 404},
    ]
    corr = sorted({r["ua"] for r in rows_train_only if r["family"] == "citation" and r["status"] == 200})
    assert corr == [], corr
    rows_citation_ok = rows_train_only[:2] + [
        {"ua": "OAI-SearchBot", "family": "citation", "status": 200},
        {"ua": "PerplexityBot", "family": "citation", "status": 404},
    ]
    corr2 = sorted({r["ua"] for r in rows_citation_ok if r["family"] == "citation" and r["status"] == 200})
    assert corr2 == ["OAI-SearchBot"], corr2

    # Circuit breaker: a dead connection must stop burning a full timeout per
    # remaining UA, but must never fire on ordinary HTTP error responses (a
    # real 403/404 proves the transport works -- only genuine transport-level
    # failures, status=None, count towards the trip).
    class _FakeTransportFail(Exception):
        pass

    calls = {"n": 0}

    def _fake_fetch(url, ua="browser", timeout=12, max_bytes=0, method="GET"):
        calls["n"] += 1
        return {"status": None, "bytes": 0, "error": "URLError: connection reset",
                "elapsed_ms": 1, "headers": {}}

    real_fetch = A.fetch
    A.fetch = _fake_fetch
    try:
        rows_dead = probe_user_agents("https://dead.example/", "")
    finally:
        A.fetch = real_fetch
    assert calls["n"] == _UA_PROBE_TRIP_AFTER, calls
    assert len(rows_dead) == 2 + len(A.CITATION_BOTS) + len(A.TRAINING_BOTS), len(rows_dead)
    assert all(r["status"] is None for r in rows_dead), rows_dead
    assert "skipped" in rows_dead[-1]["error"], rows_dead[-1]

    # A real 404 (transport worked) must never be mistaken for a dead
    # connection -- status is not None, so the counter must not advance.
    calls2 = {"n": 0}

    def _fake_fetch_404(url, ua="browser", timeout=12, max_bytes=0, method="GET"):
        calls2["n"] += 1
        return {"status": 404, "bytes": 10, "error": None, "elapsed_ms": 50, "headers": {}}

    A.fetch = _fake_fetch_404
    try:
        rows_404 = probe_user_agents("https://has-no-robots.example/", "")
    finally:
        A.fetch = real_fetch
    assert calls2["n"] == 2 + len(A.CITATION_BOTS) + len(A.TRAINING_BOTS), calls2
    assert all(r["status"] == 404 for r in rows_404), rows_404

    print("crawl_probe self-check OK")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _demo()
    else:
        sys.exit(main())
