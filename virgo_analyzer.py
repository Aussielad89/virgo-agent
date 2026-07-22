import json
import os

from _log import OUTDIR


def analyze_search_cache():
    cache_file = str(OUTDIR / "virgo_search_memory.json")
    print("🧠 Virgo Search Memory Analyzer active...")

    if not os.path.exists(cache_file):
        print("⚠️ No search memory found. Run a web search (Option 6) first!")
        return

    with open(cache_file) as f:
        data = json.load(f)

    if data.get("status") == "error":
        print(f"❌ Cannot analyze: Previous search failed with message: {data.get('message')}")
        return

    results = data.get("results", [])
    print(f"📊 Extracted {len(results)} live references from cache:\n")

    for item in results:
        print(f"📌 Title: {item.get('title')}")
        print(f"🔗 URL:   {item.get('url')}")
        print(f"📝 Snippet: {item.get('snippet')}")
        print("-" * 50)


if __name__ == "__main__":
    analyze_search_cache()
    input("\n[PRESS ENTER TO RETURN]")
