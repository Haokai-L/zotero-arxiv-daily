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

