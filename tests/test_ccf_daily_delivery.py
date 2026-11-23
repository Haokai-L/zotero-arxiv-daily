"""CCF final pipeline integration: fake sender, fake remote CAS, no live SMTP."""
import base64
import copy
import json
import hashlib
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import ccf_daily_candidates as candidate
import ccf_send_engine as engine
import ccf_smtp_submission as smtp
import ccf_r63_delivery as core
from ccf_r64_remote_store import Snapshot,CASConflict,PersistenceError

def sample(i=1):
    doi=f"10.1109/tmc.2026.{i}"
    return {"paper_key":"doi:"+doi,"year":"2026","venue":"TMC",
        "field":"networking","title":"Reliable network recovery and deadlines",
        "doi":doi,"paper_url":"https://doi.org/"+doi,
        "candidate_status":"PRELIMINARY","publication_date":"2026-11-20",
        "first_seen":"2026-11-23"}

def allowed():
    return {"TMC":{"field":"networking"},**{f"V{i}":{"field":"networking"} for i in range(15)}}

class FakeStore:
    def __init__(self):
        self.ledger=core.empty_ledger()
        self.n=0
        self.fail_writes=set()
        self.persisted=[]
    def read(self):
        return Snapshot(copy.deepcopy(self.ledger),f"{self.n:040x}")
    def write(self,ledger,expected_sha,reason):
        if expected_sha!=f"{self.n:040x}":
            raise CASConflict("version mismatch")
        if len(self.persisted) in self.fail_writes:
            raise PersistenceError("Injected GitHub outage")
        core.check_ledger(ledger)
        self.ledger=copy.deepcopy(ledger)
        self.n+=1
        self.persisted.append(reason)
        return self.read()

class FakeSender:
    def __init__(self,outcome=True):
        self.outcome=outcome
        self.calls=[]
    def submit(self,html_bytes,*,task_id):
        self.calls.append((task_id,bytes(html_bytes)))
        if isinstance(self.outcome,Exception):
            raise self.outcome
        return self.outcome

HISTORY={"schema_version":1,"sent_keys":[]}
ROWS=[{"paper_key":"doi:10.1109/tmc.2026.100","venue":"TMC"}]

class IntegratedTests(unittest.TestCase):
    def setUp(self):
        self.store=FakeStore()
        self.sender=FakeSender()
        self.coordinator=engine.MailCoordinator(self.store,self.sender,submission_approved=True)
    def test_stays_disabled_by_default(self):
        with self.assertRaises(core.SafetyError):
            engine.MailCoordinator(self.store,self.sender).deliver(HISTORY,ROWS,"2026-11-23",b"HTML")
        self.assertFalse(self.sender.calls)
    def test_durable_prepare_and_attempt_before_send(self):
        class ObservingSender:
            def __init__(self,store):self.store=store;self.seen=[]
            def submit(self,html_bytes,*,task_id):
                self.seen.append(self.store.read().ledger["batches"][task_id]["state"])
                return True
        sender=ObservingSender(self.store)
        r=engine.MailCoordinator(self.store,sender,submission_approved=True).deliver(
            HISTORY,ROWS,"2026-11-23",b"<html>sample</html>")
        self.assertEqual(sender.seen,["ATTEMPTING"])
        self.assertEqual(r.state,"SMTP_ACCEPTED")
        self.assertEqual(self.store.read().ledger["batches"][r.batch_id]["state"],"SMTP_ACCEPTED")
        self.assertEqual(len(self.store.persisted),3)
    def test_repeated_paper_cannot_submit(self):
        self.coordinator.deliver(HISTORY,ROWS,"2026-11-23",b"x")
        with self.assertRaises(core.SafetyError):
            self.coordinator.deliver(HISTORY,ROWS,"2026-11-24",b"x")
        self.assertEqual(len(self.sender.calls),1)
    def test_prepare_write_error_prevents_submission(self):
        self.store.fail_writes={0}
        with self.assertRaises(PersistenceError):
            self.coordinator.deliver(HISTORY,ROWS,"2026-11-23",b"x")
        self.assertEqual(self.sender.calls,[])
    def test_attempt_write_error_prevents_submission(self):
        self.store.fail_writes={1}
        with self.assertRaises(PersistenceError):
            self.coordinator.deliver(HISTORY,ROWS,"2026-11-23",b"x")
        self.assertEqual(self.sender.calls,[])
        self.assertEqual(next(iter(self.store.ledger["batches"].values()))["state"],"PREPARED")
    def test_sender_failure_unknown_and_blocked(self):
        self.sender.outcome=RuntimeError("simulated lost ACK")
        r=self.coordinator.deliver(HISTORY,ROWS,"2026-11-23",b"x")
        self.assertEqual(r.state,"UNCERTAIN")
        with self.assertRaises(core.SafetyError):
            self.coordinator.deliver(HISTORY,[{"paper_key":"new"}],"2026-11-24",b"y")
        self.assertEqual(len(self.sender.calls),1)
    def test_sender_returns_false_unknown(self):
        self.sender.outcome=False
        r=self.coordinator.deliver(HISTORY,ROWS,"2026-11-23",b"x")
        self.assertEqual(r.state,"UNCERTAIN")
        self.assertEqual(len(self.sender.calls),1)
    def test_unknown_ack_commit_failure_keeps_attempting(self):
        self.store.fail_writes={2}
        with self.assertRaises(PersistenceError):
            self.coordinator.deliver(HISTORY,ROWS,"2026-11-23",b"x")
        task=next(iter(self.store.ledger["batches"]))
        self.assertEqual(self.store.ledger["batches"][task]["state"],"ATTEMPTING")
        with self.assertRaises(core.SafetyError):
            self.coordinator.deliver(HISTORY,[{"paper_key":"another"}],"2026-11-24",b"x")
    def test_recovery_blocks_retry(self):
        self.sender.outcome=True
        self.store.fail_writes={2}
        with self.assertRaises(PersistenceError):
            self.coordinator.deliver(HISTORY,ROWS,"2026-11-23",b"x")
        self.store.fail_writes=set()
        self.assertEqual(self.coordinator.recover(),1)
        self.assertEqual(next(iter(self.store.ledger["batches"].values()))["state"],"UNCERTAIN")
    def test_recover_requires_auth(self):
        with self.assertRaises(core.SafetyError):
            engine.MailCoordinator(self.store,self.sender).recover()
    def test_readonly_production_store_rejects_put(self):
        transport=object()
        store=engine.ProductionLedgerStore(engine.REPO,engine.DEV,transport)
        with self.assertRaises(core.SafetyError):
            store.write(core.empty_ledger(),"0"*40,"TEST")
    def test_production_store_wrong_repo_rejected(self):
        with self.assertRaises(core.SafetyError):
            engine.ProductionLedgerStore("other/repo",engine.DEV,object())
    def test_smtp_requires_separate_authorization(self):
        with self.assertRaises(core.SafetyError):
            smtp.SmtpSender(env={"SENDER":"test@example.com","RECEIVER":"to@example.com",
                "SENDER_PASSWORD":"notreal"},test_mode=True)
    def test_smtp_does_not_connect_during_construction(self):
        with patch.object(smtp.smtplib,"SMTP_SSL",side_effect=AssertionError("socket opened")):
            sender=smtp.SmtpSender(env={
                "CCF_SMTP_AUTHORIZATION":"TEST_ONLY",
                "SENDER":"test@example.com","RECEIVER":"to@example.com",
                "SENDER_PASSWORD":"fake"},test_mode=True)
        self.assertTrue(sender.test_mode)
    def test_smtp_strict_invalid_mailbox(self):
        for value in ("Fake <a@b.com>","evil@b.com\\nBcc:victim@b.com","noatsign"):
            with self.assertRaises(core.SafetyError):smtp.valid_mailbox(value)
    def test_2026_fresh_candidates_prefer_recent(self):
        old=sample(1);old["publication_date"]="2026-01-02"
        new=sample(2)
        state={"schema_version":1,"papers":{r["paper_key"]:r for r in (old,new)}}
        chosen,_=candidate.prioritize(state,allowed(),HISTORY,core.empty_ledger(),
                                     date(2026,11,23),1)
        self.assertEqual(set(chosen["papers"]),{new["paper_key"]})
    def test_selection_skips_reserved_and_sent(self):
        a,b=sample(1),sample(2)
        state={"schema_version":1,"papers":{r["paper_key"]:r for r in (a,b)}}
        chosen,_=candidate.prioritize(state,allowed(),
             {"schema_version":1,"sent_keys":[a["paper_key"]]},core.empty_ledger(),
             date(2026,11,23),8)
        self.assertEqual(set(chosen["papers"]),{b["paper_key"]})
    def test_selection_never_modifies_original(self):
        a=sample(1);state={"schema_version":1,"papers":{a["paper_key"]:a}}
        before=json.dumps(state,sort_keys=True)
        candidate.prioritize(state,allowed(),HISTORY,core.empty_ledger(),date(2026,11,23),8)
        self.assertEqual(json.dumps(state,sort_keys=True),before)
    def test_no_preprints_in_candidate_subset(self):
        a=sample(1);a["paper_url"]="https://arxiv.org/abs/1234"
        state={"schema_version":1,"papers":{a["paper_key"]:a}}
        picked,_=candidate.prioritize(state,allowed(),HISTORY,core.empty_ledger(),
                                     date(2026,11,23),8)
        self.assertFalse(picked["papers"])
    def test_uncertain_ledger_stops_candidate_selection(self):
        a=sample(1);state={"schema_version":1,"papers":{a["paper_key"]:a}}
        ledger=core.empty_ledger()
        task=core.prepare_batch(ledger,HISTORY,[{"paper_key":"other"}],"2026-11-21",b"x")
        core.begin_attempt(ledger,task);core.uncertain(ledger,task)
        with self.assertRaises(core.SafetyError):
            candidate.prioritize(state,allowed(),HISTORY,ledger,date(2026,11,23),8)
    def test_dates_do_not_change_zotero_scores(self):
        a=sample(1);b=sample(2)
        self.assertNotIn("score",candidate.prioritize(
             {"schema_version":1,"papers":{r["paper_key"]:r for r in (a,b)}},
             allowed(),HISTORY,core.empty_ledger(),date(2026,11,23),8)[0]["papers"][a["paper_key"]])
if __name__=="__main__":unittest.main()
