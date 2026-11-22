
from collections import Counter
from pathlib import Path
from time import sleep
from urllib.request import Request, urlopen

import feedparser
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "ccf_a_venues.yaml"


def main():
    with CONFIG.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    venues = data["venues"]
    fields = Counter(v["field"] for v in venues.values())
    kinds = Counter(v["kind"] for v in venues.values())

    assert len(venues) == 16, "Expected 16 venues"
    assert fields == {"networking": 7, "security": 9}
    assert kinds == {"journal": 6, "conference": 10}

    for name, info in venues.items():
        prefix = "journals/" if info["kind"] == "journal" else "conf/"
        assert info["dblp_stream"].startswith(prefix), name

    print("PASS: 16 CCF A venues validated", flush=True)

    for name in ["TON", "TDSC", "NSDI"]:
        stream = venues[name]["dblp_stream"]
        url = f"https://dblp.org/feed/streams/{stream}.rss"

        print(f"\nChecking {name}: {url}", flush=True)

        request = Request(
            url,
            headers={"User-Agent": "CCF-Daily-Research-Probe/0.1"},
        )

        with urlopen(request, timeout=30) as response:
            content = response.read()

        feed = feedparser.parse(content)

        if not feed.version:
            raise RuntimeError(f"Invalid RSS response: {name}")

        print(
            f"PASS: {name}, {len(feed.entries)} entries",
            flush=True,
        )

        for paper in feed.entries[:2]:
            print("Title:", paper.get("title", "N/A"))
            print("Link:", paper.get("link", "N/A"))

        sleep(2)

    print("\nCCF source probe completed.", flush=True)


if __name__ == "__main__":
    main()
