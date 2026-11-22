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
import ccf_journal_quality as quality

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ccf-preview"
VENUES_PATH = ROOT / "config" / "ccf_a_venues.yaml"
API = "https://api.openalex.org"
PER_VENUE = 30

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



MAP_PATH = ROOT / "config" / "journal_source_map.yaml"
COLUMNS = ["venue","field","status","reason","source_openalex_id",
           "source_title","title","year","date","doi","openalex_id","paper_type"]

def write_csv(filename, rows):
    with (OUT / filename).open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

def main():
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if not key:
        raise SystemExit("OPENALEX_API_KEY is missing")
    venues = yaml.safe_load(VENUES_PATH.read_text(encoding="utf-8"))["venues"]
    names = {n for n,v in venues.items() if v["kind"]=="journal"}
    mapping = yaml.safe_load(MAP_PATH.read_text(encoding="utf-8"))["journals"]
    if len(venues)!=16 or len(names)!=6 or set(mapping)!=names:
        raise SystemExit("Source-map and CCF whitelist mismatch")
    OUT.mkdir(parents=True, exist_ok=True)
    cutoff = min(date.today().isoformat(), "2026-11-22")
    audits, rows = [], []
    for name, info in mapping.items():
        audit={"venue":name,"status":"CHECKED","sources":[]}
        for mapped in info["sources"]:
            record={"id":mapped["id"],"title":mapped["title"]}
            print(f"Checking {name}/{mapped['id']}", flush=True)
            try:
                source = get_json("/sources/"+mapped["id"], {}, key)
                check = quality.validate_source(source, mapped)
                record["source_validation"]=check
                record["observed_issn"]=source.get("issn")
                if check != "SOURCE_ID_TITLE_ISSN_MATCH":
                    audit["status"]="REVIEW_SOURCE"
                    audit["sources"].append(record)
                    continue
                lo=f"{mapped['from_year']}-01-01"
                hi=min(cutoff, f"{mapped['to_year']}-12-31")
                if hi < lo:
                    record["sample_count"]=0
                    audit["sources"].append(record)
                    continue
                works = get_json("/works", {
                    "filter":f"primary_location.source.id:{mapped['id']},from_publication_date:{lo},to_publication_date:{hi}",
                    "per_page":PER_VENUE, "sort":"publication_date:desc",
                    "select":"id,title,doi,publication_date,publication_year,primary_location,type",
                }, key).get("results",[])
                record["sample_count"]=len(works)
                rows.extend(quality.classify(w,name,info["field"],mapped,cutoff) for w in works)
            except Exception as exc:
                record["source_validation"]="API_ERROR"
                record["error"]=str(exc)
                audit["status"]="API_ERROR"
            audit["sources"].append(record)
            sleep(0.4)
        audits.append(audit)
    records = quality.deduplicate(rows)
    accepted, overflow, review, excluded, per_venue = [], [], [], [], Counter()
    for row in records:
        if row["status"]=="PASS_METADATA_RULES":
            if per_venue[row["venue"]] < 10:
                accepted.append(row)
                per_venue[row["venue"]]+=1
            else:
                overflow.append(row)
        elif row["status"]=="REVIEW":
            review.append(row)
        else:
            excluded.append(row)
    assert len(records) == sum(map(len, (accepted, overflow, review, excluded))), "Audit count mismatch"
    write_csv("journal_papers_preview.csv",accepted)
    write_csv("journal_accepted_overflow.csv",overflow)
    write_csv("journal_review.csv",review)
    write_csv("journal_excluded.csv",excluded)
    (OUT/"journal_source_audit.json").write_text(
        json.dumps(audits,ensure_ascii=False,indent=2),encoding="utf-8")
    summary={"note":"Preview only; PASS_METADATA_RULES is not publisher/Crossref verification.",
             "sampled":len(rows),"accepted_preview":len(accepted),
             "accepted_overflow":len(overflow),"review":len(review),
             "excluded":len(excluded),"accepted_by_venue":dict(per_venue),
             "reconciled":len(rows)==len(accepted)+len(overflow)+len(review)+len(excluded)}
    (OUT/"summary.json").write_text(
        json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("SUMMARY "+json.dumps(summary),flush=True)
    if any(a["status"]!="CHECKED" for a in audits):
        raise SystemExit("Source mismatch or API error. Inspect audit artifact.")
    if any(per_venue[v]==0 for v in mapping):
        raise SystemExit("At least one journal has no accepted metadata preview.")
    print("PASS: six-journal preview; publisher verification still pending.",flush=True)
if __name__ == "__main__":
    main()
