"""Shared, dependency-free helpers for the brand-ai-readiness-audit marketplace.

Standard library only (urllib, html.parser, json, re). No pip install required.
Every function here collects EVIDENCE. Nothing here decides severity or writes
prose -- interpretation belongs to the skill instructions, not to the script.
"""

import gzip
import io
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser

# --- User agents -----------------------------------------------------------
# Two families matter and they are NOT interchangeable:
#   "training"  -> corpus collection. Blocking these does not stop citation.
#   "citation"  -> fetches at answer time. Blocking these makes the site
#                  permanently unciteable by that assistant, no matter how good
#                  the content is.
UAS = {
    "browser": ("control", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
    "Googlebot": ("search", "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"),
    "GPTBot": ("training", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
                           "GPTBot/1.1; +https://openai.com/gptbot"),
    "OAI-SearchBot": ("citation", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
                                  "OAI-SearchBot/1.0; +https://openai.com/searchbot"),
    "ChatGPT-User": ("citation", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
                                 "ChatGPT-User/1.0; +https://openai.com/bot"),
    "ClaudeBot": ("training", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
                              "ClaudeBot/1.0; +claudebot@anthropic.com"),
    "Claude-SearchBot": ("citation", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
                                     "Claude-SearchBot/1.0; +https://www.anthropic.com/searchbot"),
    "Claude-User": ("citation", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
                                "Claude-User/1.0; +Claude-User@anthropic.com"),
    "PerplexityBot": ("citation", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
                                  "PerplexityBot/1.0; +https://perplexity.ai/perplexitybot"),
    "Perplexity-User": ("citation", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
                                    "Perplexity-User/1.0; +https://perplexity.ai/perplexity-user"),
    "Google-Extended": ("training", "Mozilla/5.0 (compatible; Google-Extended/1.0)"),
    "Applebot-Extended": ("training", "Mozilla/5.0 (compatible; Applebot-Extended/1.0)"),
    "Bingbot": ("search", "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)"),
    "CCBot": ("training", "CCBot/2.0 (https://commoncrawl.org/faq/)"),
    "meta-externalagent": ("training", "meta-externalagent/1.1"),
}

CITATION_BOTS = [k for k, v in UAS.items() if v[0] == "citation"]
TRAINING_BOTS = [k for k, v in UAS.items() if v[0] == "training"]

DEFAULT_TIMEOUT = 12
_LAST_HIT = {}
_MIN_GAP = 0.4  # politeness: >= 400ms between requests to the same host


def _throttle(url):
    host = urllib.parse.urlsplit(url).netloc
    now = time.monotonic()
    prev = _LAST_HIT.get(host)
    if prev is not None:
        wait = _MIN_GAP - (now - prev)
        if wait > 0:
            time.sleep(wait)
    _LAST_HIT[host] = time.monotonic()


def fetch(url, ua="browser", timeout=DEFAULT_TIMEOUT, max_bytes=3_000_000, method="GET"):
    """Fetch a URL as a named agent. Never raises -- errors come back as data."""
    ua_string = UAS.get(ua, (None, ua))[1]
    _throttle(url)
    req = urllib.request.Request(url, method=method, headers={
        "User-Agent": ua_string,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip",
    })
    out = {"url": url, "ua": ua, "ua_string": ua_string, "status": None, "final_url": url,
           "headers": {}, "body": "", "bytes": 0, "elapsed_ms": None, "error": None}
    ctx = ssl.create_default_context()
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read(max_bytes)
            out["status"] = resp.status
            out["final_url"] = resp.url
            out["headers"] = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        raw = b""
        try:
            raw = e.read(max_bytes)
        except Exception:
            pass
        out["status"] = e.code
        out["final_url"] = e.url or url
        out["headers"] = {k.lower(): v for k, v in (e.headers or {}).items()}
    except Exception as e:  # DNS, TLS, timeout, connection reset
        out["error"] = f"{type(e).__name__}: {e}"
        out["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        return out

    if out["headers"].get("content-encoding", "").lower() == "gzip":
        try:
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        except Exception:
            pass
    out["bytes"] = len(raw)
    charset = "utf-8"
    m = re.search(r"charset=([\w\-]+)", out["headers"].get("content-type", ""), re.I)
    if m:
        charset = m.group(1)
    try:
        out["body"] = raw.decode(charset, errors="replace")
    except LookupError:
        out["body"] = raw.decode("utf-8", errors="replace")
    out["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return out


def robots_for(base_url, timeout=DEFAULT_TIMEOUT):
    """Fetch and return raw robots.txt text plus the fetch result."""
    robots_url = urllib.parse.urljoin(base_url, "/robots.txt")
    r = fetch(robots_url, ua="browser", timeout=timeout)
    return robots_url, r


def robots_allows(robots_text, ua_token, url):
    """True/False/None -- None means robots.txt was unavailable or unparseable."""
    if not robots_text:
        return None
    rp = urllib.robotparser.RobotFileParser()
    try:
        rp.parse(robots_text.splitlines())
        return rp.can_fetch(ua_token, url)
    except Exception:
        return None


# --- HTML -------------------------------------------------------------------
_DROP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in _DROP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            s = data.strip()
            if s:
                self.parts.append(s)


def visible_text(html):
    p = _Text()
    try:
        p.feed(html)
    except Exception:
        pass
    return re.sub(r"\s+", " ", " ".join(p.parts)).strip()


class _Tags(HTMLParser):
    """Collect tags of interest with attributes and inner text."""

    def __init__(self, wanted):
        super().__init__(convert_charrefs=True)
        self.wanted = set(wanted)
        self.found = []
        self._stack = []

    def handle_starttag(self, tag, attrs):
        if tag in self.wanted:
            self._stack.append({"tag": tag, "attrs": dict(attrs), "text": []})

    def handle_startendtag(self, tag, attrs):
        if tag in self.wanted:
            self.found.append({"tag": tag, "attrs": dict(attrs), "text": ""})

    def handle_data(self, data):
        if self._stack:
            self._stack[-1]["text"].append(data)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i]["tag"] == tag:
                node = self._stack.pop(i)
                node["text"] = re.sub(r"\s+", " ", "".join(node["text"])).strip()
                self.found.append(node)
                break


def tags(html, wanted):
    p = _Tags(wanted)
    try:
        p.feed(html)
    except Exception:
        pass
    return p.found


def jsonld_blocks(html):
    """Return (parsed_objects, parse_errors). Flattens @graph."""
    objs, errors = [], []
    for m in re.finditer(
        r'<script[^>]+type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.I | re.S,
    ):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except Exception as e:
            errors.append({"error": f"{type(e).__name__}: {e}", "excerpt": raw[:200]})
            continue
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, dict) and "@graph" in item and isinstance(item["@graph"], list):
                objs.extend([g for g in item["@graph"] if isinstance(g, dict)])
            elif isinstance(item, dict):
                objs.append(item)
    return objs, errors


def types_of(obj):
    t = obj.get("@type")
    if isinstance(t, list):
        return [str(x) for x in t]
    return [str(t)] if t else []


def internal_links(html, base_url, limit=400):
    """Absolute, same-registrable-host links, de-duplicated, fragments stripped."""
    host = urllib.parse.urlsplit(base_url).netloc.lower().removeprefix("www.")
    seen, out = set(), []
    for a in tags(html, ["a"]):
        href = a["attrs"].get("href")
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absu = urllib.parse.urljoin(base_url, href)
        sp = urllib.parse.urlsplit(absu)
        if sp.scheme not in ("http", "https"):
            continue
        if sp.netloc.lower().removeprefix("www.") != host:
            continue
        clean = urllib.parse.urlunsplit((sp.scheme, sp.netloc, sp.path or "/", sp.query, ""))
        if clean in seen:
            continue
        seen.add(clean)
        out.append({"url": clean, "anchor": a["text"][:120]})
        if len(out) >= limit:
            break
    return out


def norm_base(target):
    """Accept 'example.com', 'https://example.com/x' -> scheme://host root."""
    t = target.strip()
    if not re.match(r"^https?://", t, re.I):
        t = "https://" + t
    sp = urllib.parse.urlsplit(t)
    return urllib.parse.urlunsplit((sp.scheme, sp.netloc, "/", "", ""))


def emit(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _demo():
    """Self-check: no network. Fails loudly if the parsing logic breaks."""
    html = """<html><head><title> Hi </title>
    <script type="application/ld+json">{"@graph":[{"@type":"Organization","name":"Acme"}]}</script>
    <script type="application/ld+json">{bad json}</script></head>
    <body><div id="root"></div><script>var x='invisible words here';</script>
    <h1>Real  Heading</h1><p>Body text.</p>
    <a href="/a">A</a><a href="https://other.example/b">B</a><a href="#frag">C</a></body></html>"""
    txt = visible_text(html)
    assert "invisible words here" not in txt, txt
    assert "Real Heading" in txt and "Body text." in txt, txt
    objs, errs = jsonld_blocks(html)
    assert len(objs) == 1 and objs[0]["name"] == "Acme", objs
    assert len(errs) == 1, errs
    assert types_of(objs[0]) == ["Organization"]
    links = internal_links(html, "https://site.example/")
    assert [l["url"] for l in links] == ["https://site.example/a"], links
    assert norm_base("example.com") == "https://example.com/"
    assert norm_base("http://x.example/deep/path?q=1") == "http://x.example/"
    h1 = [t for t in tags(html, ["h1"])]
    assert h1 and h1[0]["text"] == "Real Heading", h1
    assert set(CITATION_BOTS) >= {"OAI-SearchBot", "Claude-SearchBot", "PerplexityBot"}
    assert "GPTBot" in TRAINING_BOTS and "GPTBot" not in CITATION_BOTS
    print("auditlib self-check OK")


if __name__ == "__main__":
    _demo()
