"""Prioritize *unreserved* CCF papers for fresh publisher verification.

This determines which candidate metadata is checked, NOT their Zotero scores.
No preprint discovery, no SMTP, no writes to the repository candidate file.
"""
from __future__ import annotations
import argparse
import json
from collections import Counter,defaultdict
from datetime import date,datetime
from pathlib import Path
import yaml
from ccf_r63_delivery import SafetyError, PENDING, check_ledger, history_keys, reserved_keys
from ccf_r6_verify import safe_link

ROOT=Path(__file__).resolve().parents[1]

def date_or_none(text):
    try:return date.fromisoformat(str(text))
    except (TypeError,ValueError):return None

def prioritize(state, whitelist, history, ledger, today, per_venue=8):
    if state.get("schema_version")!=1 or not isinstance(state.get("papers"),dict):
        raise SafetyError("Invalid candidate state")
    history_keys(history)
    check_ledger(ledger)
    if any(r["state"] in PENDING for r in ledger["batches"].values()):
        raise SafetyError("An unresolved delivery task blocks further daily selection")
    if len(whitelist)!=16 or not 1<=per_venue<=8:
        raise SafetyError("Unexpected source whitelist or sample bound")
    reserved=reserved_keys(ledger,history)
    groups=defaultdict(list)
    skipped=Counter()
    for key,r in state["papers"].items():
        venue=r.get("venue")
        if key in reserved:
            skipped["SENT_OR_RESERVED"]+=1;continue
        if (venue not in whitelist or r.get("field")!=whitelist[venue]["field"]
            or r.get("candidate_status")!="PRELIMINARY" or key!=r.get("paper_key")
            or not r.get("title") or not safe_link(r.get("paper_url"))):
            skipped["UNSAFE_OR_UNRECOGNIZED"]+=1;continue
        try:year=int(r.get("year"))
        except (TypeError,ValueError):
            skipped["INVALID_YEAR"]+=1;continue
        if not today.year-1<=year<=today.year:
            skipped["OUT_OF_SCOPE_YEAR"]+=1;continue
        pub=date_or_none(r.get("publication_date"))
        if pub and pub>today:
            skipped["FUTURE_PUBLICATION"]+=1;continue
        seen=date_or_none(r.get("first_seen"))
        # Recency changes only WHICH records receive an API lookup, never the
        # original Zotero rank score. Missing date goes behind dated candidates.
        days=(today-pub).days if pub else 999999
        is_recent=days<=120 or (seen is not None and (today-seen).days<=30)
        groups[venue].append((0 if is_recent else 1,days, -(seen.toordinal() if seen else 0),key,r))
    chosen={}
    for venue in sorted(groups):
        items=sorted(groups[venue],key=lambda x:x[:4])[:per_venue]
        for *_,key,row in items:chosen[key]=dict(row)
    selected={"schema_version":1,"papers":chosen,
              "last_successful_check":state.get("last_successful_check",""),
              "coverage":{"mode":"RUNNER_ONLY_LIMITED_FINAL_VERIFICATION",
                          "selected_count":len(chosen)}}
    return selected,dict(skipped)

def run(state_file,history_file,ledger_file,venue_file,output_file,today,per_venue=8):
    original=[Path(p).read_bytes() for p in (state_file,history_file,ledger_file)]
    state,history,ledger=map(json.loads,original)
    whitelist=yaml.safe_load(Path(venue_file).read_text(encoding="utf-8"))["venues"]
    subset,skipped=prioritize(state,whitelist,history,ledger,today,per_venue)
    if not subset["papers"]:
        raise SafetyError("No safely eligible unsent candidate available")
    output_file=Path(output_file);output_file.parent.mkdir(parents=True,exist_ok=True)
    output_file.write_text(json.dumps(subset,ensure_ascii=False),encoding="utf-8")
    if [Path(p).read_bytes() for p in (state_file,history_file,ledger_file)]!=original:
        raise SafetyError("Source candidate/history/ledger unexpectedly changed")
    report={"eligible_for_bounded_checks":len(subset["papers"]),
            "source_venues":len(set(p["venue"] for p in subset["papers"].values())),
            "skipped":skipped,"email_sent":False}
    print("CCF_FRESH_CANDIDATES "+json.dumps(report,ensure_ascii=False),flush=True)
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--state",type=Path,required=True)
    p.add_argument("--history",type=Path,default=ROOT/"data/ccf_sent_history.json")
    p.add_argument("--ledger",type=Path,default=ROOT/"data/ccf_delivery_ledger.json")
    p.add_argument("--venues",type=Path,default=ROOT/"config/ccf_a_venues.yaml")
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--date",type=date.fromisoformat,default=date.today())
    p.add_argument("--per-venue",type=int,default=8)
    a=p.parse_args()
    run(a.state,a.history,a.ledger,a.venues,a.output,a.date,a.per_venue)
if __name__=="__main__":main()
