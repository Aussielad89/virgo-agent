import csv
import json
import urllib.request


def export_top_llm_repos(
    topic="llm", limit=20, output_file="top_llm_repos.csv"
):
    url = f"https://api.github.com/search/repositories?q=topic:{topic}&sort=stars&order=desc&per_page={limit}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "Virgo-Repo-Fetcher"}
    )

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            items = data.get("items", [])

        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["Name", "Stars", "Forks", "Language", "URL", "Description"]
            )

            for item in items:
                writer.writerow(
                    [
                        item["full_name"],
                        item["stargazers_count"],
                        item["forks_count"],
                        item.get("language") or "N/A",
                        item["html_url"],
                        item["description"] or "",
                    ]
                )

        print(
            f"Successfully saved top {len(items)} '{topic}' repositories to {output_file}"
        )

    except Exception as e:
        print(f"Error fetching data: {e}")


if __name__ == "__main__":
    export_top_llm_repos()