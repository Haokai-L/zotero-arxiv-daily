"""Preview six CCF-A journal sources on OpenAlex without emailing or claiming verified venues.

Run in repository root: python scripts/collect_ccf_journals.py
Requires PyYAML and OPENALEX_API_KEY. Creates artifacts in ccf-preview/.
"""

from __future__ import annotations

import csv
import json
import os
from collections import Counter
from datetime import date
from pathlib import Path
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ccf-preview"
VENUES_PATH = ROOT / "config" / "ccf_a_venues.yaml"
API = "https://api.openalex.org"
PER_VENUE = 10

# Alternate formally used titles; do not use fuzzy matches to confer a CCF-A label.
ALIASES = {
    "TON": {"IEEE Transactions on Networking", "IEEE/ACM Transactions on Networking"},
}


def get_json(path: str, params: dict, api_key: str) -> dict:
    url = f"{API}{path}?{urlencode(params)}"
    request = Request(url, headers={
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": "CCF-Research-Journal-Preview/1.0 (academic metadata audit)",
    })
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                content_type = response.headers.get("Content-Type", "")
                if "json" not in content_type.lower():
                    raise RuntimeError(f"Non-JSON OpenAlex reply (HTTP {response.status}, {content_type})")
                return json.load(response)
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise RuntimeError(f"OpenAlex HTTP {exc.code} for {path}") from exc
        except (URLError, TimeoutError) as exc:
            last_error = exc
        if attempt < 2:
            sleep(2 ** attempt)
    raise RuntimeError(f"OpenAlex request failed after retries: {path}: {last_error}")


def source_matches(source: dict, titles: set[str]) -> bool:
    return source.get("display_name", "").strip().casefold() in {x.casefold() for x in titles}


def inspect_journal(name: str, info: dict, key: str) -> tuple[dict, list[dict]]:
    full_name = info["full_name"].strip()
    titles = {full_name} | ALIASES.get(name, set())
    data = get_json("/sources", {"search": full_name, "per_page": 25}, key)
    candidates = data.get("results", [])
    exact = {item["id"]: item for item in candidates if source_matches(item, titles)}

    report = {
        "venue": name,
        "field": info["field"],
        "expected_title": full_name,
        "status": "REVIEW_NO_EXACT_TITLE_MATCH",
        "candidates": [
            {"id": x.get("id"), "title": x.get("display_name"), "issn": x.get("issn")}
            for x in candidates[:5]
        ],
        "selected_source": None,
        "papers_in_preview": 0,
        "warning": "Title/ISSN and publisher evidence must be checked before assigning CCF-A labels",
    }
    if len(exact) != 1:
        if len(exact) > 1:
            report["status"] = "REVIEW_AMBIGUOUS_SOURCE"
        return report, []

    source = next(iter(exact.values()))
    source_id = source["id"].rsplit("/", 1)[-1]
    report["selected_source"] = {
        "id": source_id,
        "title": source.get("display_name"),
        "issn": source.get("issn"),
        "issn_l": source.get("issn_l"),
        "type": source.get("type"),
    }
    report["status"] = "TITLE_MATCHED_AWAITING_ISSN_REVIEW"
    works = get_json("/works", {
        "filter": f"primary_location.source.id:{source_id},from_publication_date:2024-01-01,to_publication_date:{date.today().isoformat()}",
        "per_page": PER_VENUE,
        "sort": "publication_date:desc",
        "select": "id,title,doi,publication_date,publication_year,primary_location,type",
    }, key).get("results", [])
    rows = []
    for w in works:
        loc = w.get("primary_location") or {}
        loc_source = loc.get("source") or {}
        observed_id = str(loc_source.get("id") or "").rsplit("/", 1)[-1]
        if observed_id != source_id:
            continue
        rows.append({
            "venue_candidate": name,
            "field": info["field"],
            "match_status": "PENDING_MANUAL_SOURCE_REVIEW",
            "source_title": source.get("display_name", ""),
            "source_openalex_id": source_id,
            "paper_title": w.get("title", ""),
            "publication_year": w.get("publication_year", ""),
            "publication_date": w.get("publication_date", ""),
            "doi": w.get("doi") or "",
            "paper_openalex_id": w.get("id") or "",
            "paper_type": w.get("type") or "",
        })
    report["papers_in_preview"] = len(rows)
    if not rows:
        report["status"] = "REVIEW_NO_RECENT_WORKS"
    return report, rows


def main() -> None:
    api_key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing OPENALEX_API_KEY")
    config = yaml.safe_load(VENUES_PATH.read_text(encoding="utf-8"))
    venues = config["venues"]
    kinds = Counter(v.get("kind") for v in venues.values())
    fields = Counter(v.get("field") for v in venues.values())
    if len(venues) != 16 or kinds != {"journal": 6, "conference": 10} or fields != {"networking": 7, "security": 9}:
        raise SystemExit("CCF venue configuration must list 6 journals, 10 conferences, and 7 networking/9 security sources")
    OUT.mkdir(parents=True, exist_ok=True)
    reports, rows = [], []
    for name, info in venues.items():
        if info["kind"] != "journal":
            continue
        print(f"Checking {name}: {info['full_name']}", flush=True)
        try:
            report, papers = inspect_journal(name, info, api_key)
        except Exception as exc:
            report, papers = {"venue": name, "status": "API_ERROR", "reason": str(exc)}, []
        reports.append(report)
        rows.extend(papers)
        print(f"  {report['status']}; preview papers: {len(papers)}", flush=True)
        selected = report.get("selected_source")
        if selected:
            print(f"  Candidate ID: {selected['id']}; ISSNs: {selected.get('issn')}", flush=True)
        sleep(0.7)
    (OUT / "journal_source_audit.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    fields_out = ["venue_candidate", "field", "match_status", "source_title", "source_openalex_id", "paper_title", "publication_year", "publication_date", "doi", "paper_openalex_id", "paper_type"]
    with (OUT / "journal_papers_preview.csv").open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields_out)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCompleted: {len(reports)} journals attempted, {len(rows)} papers in CSV", flush=True)
    print("Output: ccf-preview/journal_source_audit.json and journal_papers_preview.csv", flush=True)
    if len(reports) != 6 or any(r["status"] == "API_ERROR" for r in reports):
        raise SystemExit("Some sources had API errors. Inspect the saved audit artifact.")
    print("PASS: Data collection completed. Source identities still require manual review.", flush=True)


if __name__ == "__main__":
    main()
