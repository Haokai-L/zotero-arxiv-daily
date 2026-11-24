"""Single CCF execution entrypoint. Preview is the default; TEST requires manual approval.

No publication-age bonus. A bounded title-similarity shortlist limits external
abstract requests; actual abstracts determine the final upstream Zotero scores.
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml
import ccf_incremental as discovery
import ccf_r6_verify as verification
from ccf_paper_enrichment import enrich_one, openalex_work
from ccf_recommend_preview import read_corpus, original_rerank
from ccf_recommend_core import choose, is_anrc_related
from ccf_r63_delivery import SafetyError, PENDING, check_ledger, history_keys, reserved_keys, accepted_keys, source_verified
from ccf_r5_mail import build as make_mail

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/"config"
DATA=ROOT/"data"
DEV="feature/ccf-a-daily"

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def within_window(row,today):
    try:year=int(row.get("year"))
    except (TypeError,ValueError):return False
    if not today.year-2<=year<=today.year:return False
    if row.get("publication_date"):
        try:return date.fromisoformat(row["publication_date"])<=today
        except (TypeError,ValueError):return False
    return True

def eligible(state,whitelist,history,ledger,today):
    check_ledger(ledger);history_keys(history)
    if any(b["state"] in PENDING for b in ledger["batches"].values()):
        raise SafetyError("Unresolved delivery: reconcile before another send")
    blocked=reserved_keys(ledger,history)
    return [dict(r) for key,r in state["papers"].items()
            if key not in blocked and key==r.get("paper_key")
            and r.get("venue") in whitelist
            and r.get("field")==whitelist[r["venue"]]["field"]
            and r.get("candidate_status")=="PRELIMINARY"
            and r.get("title") and verification.safe_link(r.get("paper_url"))
            and within_window(r,today)]

def prune(state,history,ledger,today):
    """Remove expired and accepted candidates; accepted IDs remain in ledger."""
    sent=accepted_keys(ledger,history)
    result=dict(state)
    result["papers"]={k:r for k,r in state["papers"].items()
                      if k not in sent and within_window(r,today)}
    return result

def conference_maps():
    result={}
    for path in [CONFIG/"conference_source_map.yaml",*sorted(CONFIG.glob("ccf_incremental_*.yaml"))]:
        obj=yaml.safe_load(path.read_text(encoding="utf-8"))
        result[int(obj["year"])]=(path,obj)
    return result

def recommend(rows,corpus,whitelist,history,ledger,*,rank,abstract,verify,shortlist=80):
    """Rank every available title first; enrich and rerank a global shortlist.

    Check actual publisher identity in score order, continuing past failed
    proofs. No source quota, and no guaranteed A-NRC slot.
    """
    if not rows:return []
    preliminary=rank(rows,corpus,title_only=True)
    enriched=[]
    for row in preliminary[:shortlist]:
        item=abstract(row)
        if item.get("abstract_status")=="ABSTRACT_VERIFIED_METADATA":
            enriched.append(item)
    if not enriched:return []
    ranked=rank(enriched,corpus)
    valid=[]
    for row in ranked:
        if len(valid)>=3:
            top=choose(valid,limit=3)["selected"]
            if any(is_anrc_related(r["title"],r["abstract"]) for r in top):break
            if float(row["score"]) < float(top[-1]["score"])-0.5:break
            if not is_anrc_related(row["title"],row["abstract"]):continue
        proof=verify(row)
        if source_verified(row,proof):
            valid.append(dict(row,**{k:proof[k] for k in
                ("publisher_verification","verification_evidence","verification_reason") if k in proof}))
    return choose(valid, sent_keys=reserved_keys(ledger,history),limit=3)["selected"]

def checkpoint(state,path,branch):
    if os.environ.get("GITHUB_REF")!="refs/heads/"+branch or branch!=DEV:
        raise SafetyError("Candidate checkpoint restricted to reviewed development branch")
    path.write_text(json.dumps(state,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8")
    def git(*args):
        return subprocess.check_output(["git",*args],cwd=ROOT,text=True).strip()
    relative=str(path.relative_to(ROOT))
    if not git("status","--porcelain","--",relative):return
    git("config","user.name","github-actions[bot]")
    git("config","user.email","41898282+github-actions[bot]@users.noreply.github.com")
    git("add","--",relative)
    if git("diff","--cached","--name-only")!=relative:raise SafetyError("Unexpected staged file")
    git("commit","-m","data(ccf): refresh rolling candidates [skip ci]")
    expected=git("rev-parse","HEAD")
    git("push","origin","HEAD:refs/heads/"+branch)
    if git("ls-remote","origin","refs/heads/"+branch).split()[0]!=expected:
        raise SafetyError("Candidate checkpoint was not confirmed")

def run(mode,out):
    if mode not in ("preview","test"):raise SafetyError("Daily sending not approved")
    if mode=="test" and (os.environ.get("GITHUB_EVENT_NAME")!="workflow_dispatch"
                        or os.environ.get("CCF_SMTP_AUTHORIZATION")!="TEST_ONLY"):
        raise SafetyError("TEST requires a manually dispatched authorized workflow")
    if os.environ.get("GITHUB_REF")!="refs/heads/"+DEV:
        raise SafetyError("Development branch required")
    today=datetime.now(ZoneInfo("Asia/Taipei")).date()
    history=load(DATA/"ccf_sent_history.json")
    ledger=load(DATA/"ccf_delivery_ledger.json")
    check_ledger(ledger)
    if any(b["state"] in PENDING for b in ledger["batches"].values()):
        raise SafetyError("Unresolved delivery: check mailbox and reconcile first")
    if mode=="test" and any(b["day"]==today.isoformat() for b in ledger["batches"].values()):
        print("Already a batch today; no duplicate TEST");return
    whitelist=yaml.safe_load((CONFIG/"ccf_a_venues.yaml").read_text())["venues"]
    maps=conference_maps()
    map_year=max(y for y in maps if y<=today.year)
    with tempfile.TemporaryDirectory(prefix="ccf-") as temp:
        work=Path(temp)
        state_path=work/"candidates.json"
        state_path.write_bytes((DATA/"ccf_candidate_state.json").read_bytes())
        report=discovery.run(state_path,DATA/"ccf_sent_history.json",None,
            CONFIG/"ccf_a_venues.yaml",CONFIG/"journal_source_map.yaml",
            maps[map_year][0],work/"discovery",today)
        state=prune(load(state_path),history,ledger,today)
        checkpoint(state,DATA/"ccf_candidate_state.json",DEV)
        rows=eligible(state,whitelist,history,ledger,today)
        if not rows:
            print("No eligible papers; no email");return
        corpus=sorted(read_corpus(),key=lambda p:p.added_date,reverse=True)[:150]
        if len(corpus)<2:raise SafetyError("A-NRC-Research has fewer than two usable references")
        print("CCF_CORPUS_COUNT",len(corpus),"ELIGIBLE_TITLE_COUNT",len(rows),flush=True)
        journals=yaml.safe_load((CONFIG/"journal_source_map.yaml").read_text())
        confs={y:obj for y,(_,obj) in maps.items()}
        listings={}
        def official(year,venue,setting):
            if (year,venue) not in listings:
                listings[year,venue]=verification.cq.parse_official_listing(
                    verification.fetch_official(setting["official_url"]),venue,setting,year)
            return listings[year,venue]
        def verify(row):
            try:return verification.check(row,journals,confs,verification.crossref,official)
            except Exception as exc:
                print("Source check failed",row["venue"],type(exc).__name__,flush=True)
                return {}
        api_key=os.environ.get("OPENALEX_API_KEY","")
        def abstract(row):
            return enrich_one(row,openalex_work(row,api_key))
        selected=recommend(rows,corpus,whitelist,history,ledger,
            rank=original_rerank,abstract=abstract,verify=verify)
        print("CCF_SELECTED_COUNT",len(selected),flush=True)
        if not selected:return
        cfg=yaml.safe_load((CONFIG/"ccf_r5_mail.yaml").read_text())
        audit=make_mail({"selected":selected,"email_sent":False,"preview_only":True},
                        cfg,whitelist,out,today=today.isoformat(),mode=mode)
        if audit["deepseek_generated"]!=len(selected):
            raise SafetyError("Chinese summary unavailable; no submission")
        if mode=="test":
            from ccf_send_engine import MailCoordinator, ProductionLedgerStore, GithubTransport, REPO
            from ccf_smtp_submission import SmtpSender
            store=ProductionLedgerStore(REPO,DEV,GithubTransport(os.environ["GITHUB_TOKEN"]),writes_approved=True)
            sender=SmtpSender(test_mode=True)
            result=MailCoordinator(store,sender,submission_approved=True).deliver(
                history,selected,today.isoformat(),(out/"email_preview.html").read_bytes())
            print("CCF_TEST_SUBMISSION",result.state,flush=True)
            if not result.server_accepted:raise SafetyError("SMTP acceptance unconfirmed; do not retry")
        else:
            print("CCF_PREVIEW_COMPLETE",len(selected),"SMTP_NOT_CALLED",flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=("preview","test"),default="preview")
    p.add_argument("--out",type=Path,default=Path("ccf-output"))
    a=p.parse_args()
    run(a.mode,a.out)
