import requests
from bs4 import BeautifulSoup

def search_web(query: str):

    url = "https://duckduckgo.com/html/"

    params = {"q": query}

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)

        soup = BeautifulSoup(r.text, "html.parser")

        results = []

        for a in soup.select(".result__a")[:5]:
            title = a.get_text()
            link = a.get("href")
            results.append(f"{title} - {link}")

        if not results:
            return "No results found"

        return "\n".join(results)

    except Exception as e:
        return f"Search error: {str(e)}"