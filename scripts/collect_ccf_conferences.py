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

def main():
    cfg=yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    venues=cfg["venues"]
    year=cfg["year"]
    ccf=yaml.safe_load(CCF.read_text(encoding="utf-8"))["venues"]
    expected={name for name,v in ccf.items() if v["kind"]=="conference"}
    assert year==2025 and len(expected)==10 and set(venues)==expected
    assert all(venues[name]["field"]==ccf[name]["field"] for name in venues)
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[]; audit=[]
    for venue,settings in venues.items():
        a={"venue":venue,"year":year,"provider":settings["provider"],
           "official_url":settings["official_url"],"status":"CHECKED"}
        try:
            if settings["provider"]=="crossref":
                raw=fetch_crossref(settings,year)
                items=[cq.check_crossref(x,venue,settings,year) for x in raw]
                a["retrieved"]=len(raw)
            else:
                html=fetch_text(settings["official_url"],accept="text/html")
                # Reject a login/challenge page instead of silently claiming no papers.
                if "not a bot" in html.lower() and len(html)<40000:
                    raise RuntimeError("Anti-bot challenge instead of proceedings")
                items=cq.parse_official_listing(html,venue,settings,year)
                a["retrieved"]=len(items)
            rows.extend(items)
            counts=Counter(item["status"] for item in items)
            a["counts"]=dict(counts)
            if not any(c in counts for c in ("CROSSREF_META_MATCH","SPRINGER_BOOK_MATCH","OFFICIAL_LISTED")):
                a["status"]="NEEDS_REVIEW_NO_MATCH"
            print(f"{venue}: {a['status']}; retrieved={a['retrieved']}; statuses={dict(counts)}",flush=True)
        except Exception as exc:
            a["status"]="API_ERROR"
            a["error"]=f"{type(exc).__name__}: {exc}"
            print(f"{venue}: API_ERROR {a['error']}",flush=True)
        audit.append(a)
        sleep(0.6)
    rows=cq.deduplicate(rows)
    matches=[r for r in rows if r["status"] in ("CROSSREF_META_MATCH","SPRINGER_BOOK_MATCH","OFFICIAL_LISTED")]
    reviews=[r for r in rows if r["status"]=="REVIEW"]
    excluded=[r for r in rows if r["status"]=="EXCLUDED_DUPLICATE"]
    selected=[];overflow=[]
    venue_counts=Counter()
    for r in matches:
        if venue_counts[r["venue"]]<10:
            selected.append(r);venue_counts[r["venue"]]+=1
        else:
            overflow.append(r)
    assert len(rows)==sum(map(len,(selected,overflow,reviews,excluded)))
    write_csv("conference_papers_preview.csv",selected)
    write_csv("conference_accepted_overflow.csv",overflow)
    write_csv("conference_review.csv",reviews)
    write_csv("conference_excluded.csv",excluded)
    (OUT/"conference_source_audit.json").write_text(
        json.dumps(audit,ensure_ascii=False,indent=2),encoding="utf-8")
    summary={"year":year,"attempted_venues":len(audit),
             "venues_with_accepted_samples":len(venue_counts),
             "matched_preview":len(selected),"matched_overflow":len(overflow),
             "review":len(reviews),"duplicates":len(excluded),
             "status_counts":dict(Counter(a["status"] for a in audit)),
             "accepted_by_venue":dict(venue_counts),
             "reconciled":len(rows)==sum(map(len,(selected,overflow,reviews,excluded))),
             "scope":"2025 metadata and official-listing preview, NOT 2024-2026 backfill"}
    (OUT/"summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8")
    print("SUMMARY "+json.dumps(summary),flush=True)
    if len(audit)!=10 or not summary["reconciled"]:
        raise SystemExit("Conference audit incomplete")
    if not selected:
        raise SystemExit("No verified metadata or official listing samples; inspect audit.")
    print("PASS: complete 10-venue audit report; review individual venue statuses.",flush=True)

if __name__=="__main__":
    main()
