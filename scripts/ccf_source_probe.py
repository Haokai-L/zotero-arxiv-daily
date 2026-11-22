
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "ccf_a_venues.yaml"


def validate_venues():
    with CONFIG.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    venues = data["venues"]

    fields = Counter(v["field"] for v in venues.values())
    kinds = Counter(v["kind"] for v in venues.values())

    assert len(venues) == 16
    assert fields == {"networking": 7, "security": 9}
    assert kinds == {"journal": 6, "conference": 10}

    for name, info in venues.items():
        prefix = (
            "journals/"
            if info["kind"] == "journal"
            else "conf/"
        )
        assert info["dblp_stream"].startswith(prefix), name

    print("PASS: 16 CCF A venues validated", flush=True)
    return venues


def check_dblp(name, venue):
    stream = venue["dblp_stream"]

    # Example:
    # stream:streams/journals/ton:
    query = f"stream:streams/{stream}:"

    params = urlencode({
        "q": query,
        "h": 5,
        "format": "json",
        "c": 0,
    })

    url = f"https://dblp.org/search/publ/api?{params}"

    print(f"\nChecking {name}", flush=True)
    print(f"Query: {query}", flush=True)

    request = Request(
        url,
        headers={
            "User-Agent": "CCF-Daily-Research-Probe/0.1",
            "Accept": "application/json",
        },
    )

    with urlopen(request, timeout=30) as response:
        raw = response.read()
        print(
            f"HTTP status: {response.status}",
            flush=True,
        )
        print(
            f"Content-Type: {response.headers.get('Content-Type')}",
            flush=True,
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print("Response preview:", repr(raw[:250]))
        raise RuntimeError(
            f"DBLP did not return valid JSON for {name}"
        ) from exc

    hits = (
        data.get("result", {})
        .get("hits", {})
        .get("hit", [])
    )

    if isinstance(hits, dict):
        hits = [hits]

    if not hits:
        raise RuntimeError(
            f"No DBLP results found for {name}: {query}"
        )

    print(
        f"PASS: {name}, {len(hits)} sample records",
        flush=True,
    )

    for hit in hits[:3]:
        info = hit.get("info", {})
        print("Title:", info.get("title", "N/A"))
        print("Venue:", info.get("venue", "N/A"))
        print("Year:", info.get("year", "N/A"))
        print("DOI:", info.get("doi", "N/A"))
        print("URL:", info.get("url", "N/A"))
        print("---")


def main():
    venues = validate_venues()

    for name in ["TON", "TDSC", "NSDI"]:
        check_dblp(name, venues[name])

    print("\nCCF source probe completed.", flush=True)


if __name__ == "__main__":
    main()
