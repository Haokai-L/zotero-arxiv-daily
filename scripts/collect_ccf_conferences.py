"""R3-3 bounded 2025 main-conference audit; no Zotero, DeepSeek, or email."""
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from time import sleep
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

import yaml
import ccf_conference_quality as cq

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/"config"/"conference_source_map.yaml"
CCF=ROOT/"config"/"ccf_a_venues.yaml"
OUT=ROOT/"ccf-conference-preview"
COLUMNS=["venue","year","title","doi","paper_url","container","publisher",
         "record_type","source","official_evidence_url","status","reason"]

def fetch_text(url,accept="application/json"):
    req=Request(url,headers={
        "Accept":accept,"User-Agent":"CCF-Research-Conference-Audit/1.0 (research; metadata verification)"
    })
    error=None
    for attempt in range(3):
        try:
            with urlopen(req,timeout=28) as response:
                data=response.read(4_000_000)
                ctype=response.headers.get("Content-Type","")
                if accept=="application/json" and "json" not in ctype.lower():
                    raise RuntimeError(f"Non-JSON response ({response.status}: {ctype})")
                if accept=="text/html" and "html" not in ctype.lower():
                    raise RuntimeError(f"Non-HTML response ({response.status}: {ctype})")
                return data.decode("utf-8",errors="replace")
        except HTTPError as exc:
            error=f"HTTP {exc.code}"
            if exc.code not in (429,500,502,503,504):
                raise RuntimeError(error) from exc
        except (URLError,TimeoutError) as exc:
            error=repr(exc)
        if attempt<2: sleep(2**attempt)
    raise RuntimeError(f"Request failed after retries: {error}")

def fetch_crossref(setting,year):
    params={
        "query.container-title":setting["query"],
        "filter":f"from-pub-date:{year}-01-01,until-pub-date:{year}-12-31",
        "rows":40,
        "mailto":"research-audit@example.org",
    }
    url="https://api.crossref.org/works?"+urlencode(params)
    data=json.loads(fetch_text(url))
    if data.get("status")!="ok": raise RuntimeError("Unexpected Crossref status")
    return data.get("message",{}).get("items",[])

def write_csv(name,items):
    with (OUT/name).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(items)

