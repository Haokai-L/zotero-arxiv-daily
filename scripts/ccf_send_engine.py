"""Safely coordinate a future CCF mail submission with remote CAS persistence.

The engine never imports SMTP and cannot submit unless *explicitly enabled*
by its caller. The consolidated GitHub no-send workflow never invokes it.
A submitted email can be accepted by the server even if the confirmation is
lost: durable ATTEMPTING is treated as UNCERTAIN on restart, never resent.
"""
from __future__ import annotations
import base64
import copy
import json
import re
from dataclasses import dataclass
from urllib.parse import quote

from ccf_r63_delivery import (
    SafetyError, check_ledger, prepare_batch, begin_attempt,
    smtp_accepted, uncertain, recover_after_crash, history_keys
)
from ccf_r64_remote_store import GithubTransport, Snapshot, canonical_bytes, CASConflict, PersistenceError

REPO="Haokai-L/zotero-arxiv-daily"
LEDGER="data/ccf_delivery_ledger.json"
DEV="feature/ccf-a-daily"

class ProductionLedgerStore:
    """Real ledger-path CAS, but disarmed until separate deployment approval."""
    def __init__(self,repo,branch,transport,*,writes_approved=False):
        if repo!=REPO or branch not in (DEV,"main"):
            raise SafetyError("Production storage restricted to reviewed repository/branches")
        self.repo,self.branch,self.transport=repo,branch,transport
        self.writes_approved=writes_approved is True
        self.route="/repos/"+repo+"/contents/"+LEDGER
    def read(self):
        data=self.transport.request("GET",self.route+"?ref="+quote(self.branch,safe=""))
        if not isinstance(data,dict) or data.get("encoding")!="base64":
            raise PersistenceError("Remote production ledger unavailable or content too large")
        sha=data.get("sha")
        if not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{40}",sha):
            raise PersistenceError("Remote ledger SHA invalid")
        try:
            ledger=json.loads(base64.b64decode(data["content"]))
            check_ledger(ledger)
        except (KeyError,TypeError,ValueError,SafetyError) as exc:
            raise PersistenceError("Remote ledger data invalid") from exc
        return Snapshot(ledger,sha)
    def write(self,ledger,expected_sha,reason):
        if not self.writes_approved:
            raise SafetyError("Production writes disabled until separately approved")
        if not isinstance(expected_sha,str) or not re.fullmatch(r"[0-9a-f]{40}",expected_sha):
            raise SafetyError("Remote ledger requires an exact existing SHA")
        content=canonical_bytes(ledger)
        if not isinstance(reason,str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,70}",reason):
            raise SafetyError("Unsafe persistence reason")
        reply=self.transport.request("PUT",self.route,{
            "message":"ccf: "+reason+" [skip ci]",
            "content":base64.b64encode(content).decode("ascii"),
            "branch":self.branch,"sha":expected_sha})
        newsha=(reply or {}).get("content",{}).get("sha")
        latest=self.read()
        if not isinstance(newsha,str) or latest.sha!=newsha or canonical_bytes(latest.ledger)!=content:
            raise PersistenceError("Remote ledger read-after-write confirmation failed")
        return latest

@dataclass(frozen=True)
class SubmitResult:
    batch_id:str
    state:str
    server_accepted:bool

class MailCoordinator:
    """Sender is injected; tests use fake senders and never open SMTP sockets."""
    def __init__(self,store,sender,*,submission_approved=False):
        self.store,self.sender=store,sender
        self.submission_approved=submission_approved is True

    def deliver(self,history,selected,day,final_html):
        if not self.submission_approved:
            raise SafetyError("SMTP submission not approved")
        history_keys(history)
        current=self.store.read()
        # Never send if a previous batch is uncertain or not reconciled.
        check_ledger(current.ledger)
        if any(b["state"] in ("ATTEMPTING","PREPARED","FAILED_BEFORE_HANDOFF","UNCERTAIN")
               for b in current.ledger["batches"].values()):
            raise SafetyError("Unresolved remote mail task: manual reconciliation required")
        ledger=copy.deepcopy(current.ledger)
        task_id=prepare_batch(ledger,history,selected,day,final_html)
        prepared=self.store.write(ledger,current.sha,"PREPARED_"+task_id)
        ledger=copy.deepcopy(prepared.ledger)
        begin_attempt(ledger,task_id)
        # The second durable, read-confirmed commit MUST complete before network handoff.
        attempting=self.store.write(ledger,prepared.sha,"ATTEMPTING_"+task_id)
        if attempting.ledger["batches"][task_id]["state"]!="ATTEMPTING":
            raise PersistenceError("Remote ATTEMPTING was not durably confirmed")
        try:
            accepted=self.sender.submit(final_html,task_id=task_id)
        except Exception:
            # Exceptions after handoff are ambiguous. Try to persist UNCERTAIN;
            # if that fails, remote ATTEMPTING still blocks a new send.
            unknown=copy.deepcopy(attempting.ledger)
            uncertain(unknown,task_id)
            self.store.write(unknown,attempting.sha,"UNCERTAIN_"+task_id)
            return SubmitResult(task_id,"UNCERTAIN",False)
        if accepted is not True:
            unknown=copy.deepcopy(attempting.ledger)
            uncertain(unknown,task_id)
            self.store.write(unknown,attempting.sha,"UNCERTAIN_"+task_id)
            return SubmitResult(task_id,"UNCERTAIN",False)
        done=copy.deepcopy(attempting.ledger)
        smtp_accepted(done,task_id,True)
        self.store.write(done,attempting.sha,"SMTP_ACCEPTED_"+task_id)
        return SubmitResult(task_id,"SMTP_ACCEPTED",True)

    def recover(self):
        """Remote recovery is safe only when separately approved."""
        if not self.submission_approved:
            raise SafetyError("Remote recovery is disabled")
        current=self.store.read()
        ledger=copy.deepcopy(current.ledger)
        n=recover_after_crash(ledger)
        if n:
            self.store.write(ledger,current.sha,"RECOVERED_UNCERTAIN")
        return n
