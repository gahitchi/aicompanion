"""Web tools: DuckDuckGo search + URL fetching."""
import requests
from bs4 import BeautifulSoup


SEARCH_URL = "https://duckduckgo.com/html/"
DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AICompanion/1.0"}


def search_web(query: str) -> str:
    try:
        r = requests.get(SEARCH_URL, params={"q": query},
                         headers=DEFAULT_HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for a in soup.select(".result__a")[:5]:
            title = a.get_text(strip=True)
            link = a.get("href")
            snippet_el = a.find_parent("div", class_="result__body")
            snippet = ""
            if snippet_el:
                sn = snippet_el.select_one(".result__snippet")
                if sn:
                    snippet = sn.get_text(strip=True)[:200]
            results.append(f"- {title}\n  {link}" + (f"\n  {snippet}" if snippet else ""))
        return "\n".join(results) if results else "No results"
    except Exception as e:
        return f"Search error: {e}"


def fetch_url(url: str) -> str:
    """GET a URL and return readable text content. Caps at 8KB."""
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
    except Exception as e:
        return f"Fetch error: {e}"
    if r.status_code >= 400:
        return f"HTTP {r.status_code} from {url}"
    ctype = r.headers.get("content-type", "").lower()
    if "html" in ctype:
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
    else:
        text = r.text
    # Collapse blank lines + cap
    lines = [ln for ln in text.splitlines() if ln.strip()]
    text = "\n".join(lines)
    if len(text) > 8000:
        text = text[:8000] + f"\n...(truncated, full length {len(text)} chars)"
    return text
