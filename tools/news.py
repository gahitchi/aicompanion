"""News headlines via RSS — stdlib XML parser, no API key, no extra deps.

Feeds come from JADE_NEWS_FEEDS (comma-separated RSS/Atom URLs); a small default
set is used otherwise. SAFE — read only.
"""
import os
import xml.etree.ElementTree as ET

import requests

_ATOM = "{http://www.w3.org/2005/Atom}"
_DEFAULT_FEEDS = {
    "top": ["https://feeds.bbci.co.uk/news/rss.xml"],
    "world": ["https://feeds.bbci.co.uk/news/world/rss.xml"],
    "tech": ["https://feeds.arstechnica.com/arstechnica/index"],
}
_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Jade/1.0"}


def _feeds(topic: str):
    env = os.environ.get("JADE_NEWS_FEEDS")
    if env:
        return [u.strip() for u in env.split(",") if u.strip()]
    return _DEFAULT_FEEDS.get((topic or "top").lower(), _DEFAULT_FEEDS["top"])


def get_headlines(topic: str = "top", n: int = 5) -> str:
    """Top news headlines (topic = top/world/tech, or whatever your feeds cover). SAFE."""
    titles = []
    for url in _feeds(topic):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=10)
            root = ET.fromstring(r.content)
            items = root.findall(".//item") or root.findall(f".//{_ATOM}entry")
            for it in items:
                t = it.find("title")
                if t is None:
                    t = it.find(f"{_ATOM}title")
                if t is not None and t.text:
                    titles.append(t.text.strip())
        except Exception:
            continue
        if len(titles) >= n:
            break
    titles = titles[:max(1, int(n))]
    if not titles:
        return "Couldn't fetch headlines right now."
    return "Headlines:\n" + "\n".join(f"- {t}" for t in titles)
