"""
virgo_web_search — multi-engine web search (DuckDuckGo, Google, YouTube).

Usage:
    python virgo_web_search.py 1    # DuckDuckGo
    python virgo_web_search.py 2    # Google (scrape)
    python virgo_web_search.py 3    # YouTube (scrape)

Results are printed to stdout and saved to virgo_search_memory_*.json.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _console import icon
from _log import OUTDIR

SEARCH_MEMORY_DIR = OUTDIR


def web_search(query: str) -> dict:
    """Search DuckDuckGo (no API key needed)."""
    print(f"{icon('web')} Virgo searching DuckDuckGo for: '{query}'...")
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8")

        links = re.findall(r'<a class="result__url" href="([^"]+)"', html)
        snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)

        results = []
        for i in range(min(3, len(links))):
            clean_snippet = (
                re.sub(r"<[^>]+>", "", snippets[i]).strip()
                if i < len(snippets)
                else "No description."
            )
            actual_url = links[i]
            if "//duckduckgo.com/l/?" in actual_url:
                parsed = urllib.parse.urlparse(actual_url)
                actual_url = urllib.parse.parse_qs(parsed.query).get("uddg", [actual_url])[0]
            results.append(
                {"title": f"Result {i + 1}", "url": actual_url, "snippet": clean_snippet}
            )

        if not results:
            return {
                "status": "success",
                "results": [
                    {
                        "title": "Search completed",
                        "url": url,
                        "snippet": "Click link to view results directly.",
                    }
                ],
            }
        return {"status": "success", "results": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def google_search(query: str) -> dict:
    """Search Google by scraping HTML results."""
    print(f"{icon('search')} Virgo searching Google for: '{query}'...")
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://www.google.com/search?q={encoded_query}&hl=en"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8", errors="replace")

        links = re.findall(r'<a[^>]*href="(https?://[^"]*)"[^>]*>(.*?)</a>', html, re.DOTALL)
        snippets = re.findall(
            r'<div[^>]*class="[^"]*VwiC3b[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL
        )

        results = []
        seen: set[str] = set()
        for url_match, title_html in links:
            href = url_match
            if href in seen or not href.startswith("http"):
                continue
            seen.add(href)
            title_clean = re.sub(r"<[^>]+>", "", title_html).strip()
            snippet = snippets[len(results)].strip() if len(results) < len(snippets) else ""
            snippet_clean = re.sub(r"<[^>]+>", "", snippet)
            results.append({"title": title_clean[:80], "url": href, "snippet": snippet_clean[:200]})
            if len(results) >= 5:
                break

        return {"status": "success", "engine": "google", "results": results}
    except urllib.error.HTTPError as e:
        return {"status": "error", "message": f"HTTP {e.code}: Google blocked the request."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def youtube_search(query: str) -> dict:
    """Search YouTube by scraping HTML results."""
    print(f"{icon('video')} Virgo searching YouTube for: '{query}'...")
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://www.youtube.com/results?search_query={encoded_query}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8", errors="replace")

        video_ids = re.findall(r"/watch\?v=([a-zA-Z0-9_-]{11})", html)
        titles = re.findall(r'"title":{"runs":\[{"text":"([^"]+)"', html)

        results = []
        seen_ids: set[str] = set()
        for i, vid in enumerate(video_ids):
            if vid in seen_ids:
                continue
            seen_ids.add(vid)
            title = titles[len(results)].strip() if len(results) < len(titles) else f"Video {i + 1}"
            results.append(
                {
                    "title": title[:80],
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "video_id": vid,
                }
            )
            if len(results) >= 5:
                break

        return {"status": "success", "engine": "youtube", "results": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def save_results(data: dict, query: str, engine: str) -> None:
    """Save search results to a timestamped JSON file in the output dir."""
    import time

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = str(SEARCH_MEMORY_DIR / f"virgo_search_memory_{timestamp}.json")
    data["query"] = query
    data["engine"] = engine
    data["timestamp"] = timestamp
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)
    print(f"{icon('save')} Search memory saved to: {filename}")


if __name__ == "__main__":
    engines = {"1": "duckduckgo", "2": "google", "3": "youtube"}
    engine_id = sys.argv[1] if len(sys.argv) > 1 else "1"
    engine_name = engines.get(engine_id, "duckduckgo")
    query = input("  Enter search query: ").strip() if len(sys.argv) < 3 else " ".join(sys.argv[2:])

    if not query:
        query = "virgo agent framework"
        print(f"  Using default query: '{query}'")

    if engine_name == "google":
        result = google_search(query)
    elif engine_name == "youtube":
        result = youtube_search(query)
    else:
        result = web_search(query)

    if result.get("status") == "error":
        print(f"  {icon('error')} Search failed: {result.get('message')}")
    else:
        for r in result.get("results", []):
            print(f"\n  {r.get('title', '')}")
            print(f"  {r.get('url', '')}")
            if r.get("snippet"):
                print(f"  {r.get('snippet', '')[:200]}")

    save_results(result, query, engine_name)
