"""R6-4 mock-CAS and write-allowlist tests; no GitHub network required."""
import base64,copy,hashlib,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import ccf_r64_remote_store as remote
import ccf_r64_probe as probe
from ccf_r63_delivery import (empty_ledger,prepare_batch,begin_attempt,
                              recover_after_crash,SafetyError,check_ledger)

class FakeTransport:
    def __init__(self):
        self.doc=None
        self.version=0
        self.fail=False
        self.tamper_read=False
    def request(self,method,route,payload=None):
        if self.fail:
            raise remote.PersistenceError("mock outage")
        if method=="GET":
            if self.doc is None:return None
            contents=self.doc
            if self.tamper_read:contents=b'{"schema_version":2}'
            return {"sha":hashlib.sha1(b"blob "+str(len(self.doc)).encode()+b"\0"+self.doc).hexdigest(),
                "content":base64.b64encode(contents).decode("ascii"),"encoding":"base64"}
        if method=="PUT":
            expected=payload.get("sha")
            current=self.request("GET",route)
            if (current is None and expected is not None) or (current is not None and
                expected != current["sha"]):
                raise remote.CASConflict("mock conflict")
            self.doc=base64.b64decode(payload["content"])
            self.version+=1
            return {"content":{"sha":self.request("GET",route)["sha"]}}
        raise AssertionError("Unsupported method")

class RemoteSafety(unittest.TestCase):
    def setUp(self):
        self.transport=FakeTransport()
        self.store=remote.ProbeStore("Haokai-L/zotero-arxiv-daily",
             "feature/ccf-a-daily","data/r64_probes/45153022186-1.json",self.transport)
    def prepare(self):
        s=self.store.write(empty_ledger(),None,"initialize")
        prepared=copy.deepcopy(s.ledger)
        prepare_batch(prepared,{"schema_version":1,"sent_keys":[]},
            [{"paper_key":"synthetic:a"}],"2026-11-23",b"<html/>")
        return self.store.write(prepared,s.sha,"prepare")
    def test_allowlisted_path(self):
        self.assertEqual(self.store.path,"data/r64_probes/45153022186-1.json")
    def test_reject_main_branch(self):
        with self.assertRaises(SafetyError):remote.ProbeStore("Haokai-L/zotero-arxiv-daily","main",self.store.path,self.transport)
    def test_reject_production_ledger(self):
        with self.assertRaises(SafetyError):remote.ProbeStore("Haokai-L/zotero-arxiv-daily","feature/ccf-a-daily",
              "data/ccf_delivery_ledger.json",self.transport)
    def test_reject_legacy_sent_history(self):
        with self.assertRaises(SafetyError):remote.ProbeStore("Haokai-L/zotero-arxiv-daily","feature/ccf-a-daily",
              "data/ccf_sent_history.json",self.transport)
    def test_reject_path_traversal(self):
        with self.assertRaises(SafetyError):remote.ProbeStore("Haokai-L/zotero-arxiv-daily","feature/ccf-a-daily",
              "data/r64_probes/../../main.yml",self.transport)
    def test_reject_other_repo_name(self):
        with self.assertRaises(SafetyError):remote.ProbeStore("https://github.com/evil","feature/ccf-a-daily",
              self.store.path,self.transport)
    def test_initial_create_and_readback(self):
        snap=self.store.write(empty_ledger(),None,"initialize")
        self.assertEqual(self.store.read().sha,snap.sha)
        self.assertEqual(self.store.read().ledger,empty_ledger())
    def test_create_does_not_overwrite(self):
        self.store.write(empty_ledger(),None,"first")
        with self.assertRaises(remote.CASConflict):self.store.write(empty_ledger(),None,"duplicate-create")
    def test_stale_write_conflict(self):
        prepared=self.prepare()
        ledger=copy.deepcopy(prepared.ledger)
        task=next(iter(ledger["batches"]))
        begin_attempt(ledger,task)
        newer=self.store.write(ledger,prepared.sha,"attempt")
        with self.assertRaises(remote.CASConflict):
            self.store.write(prepared.ledger,prepared.sha,"rollback-should-fail")
        self.assertEqual(self.store.read().sha,newer.sha)
        self.assertEqual(self.store.read().ledger["batches"][task]["state"],"ATTEMPTING")
    def test_crash_recovery_remote_persistent(self):
        prepared=self.prepare()
        ledger=copy.deepcopy(prepared.ledger)
        task=next(iter(ledger["batches"]))
        begin_attempt(ledger,task)
        attempt=self.store.write(ledger,prepared.sha,"attempt")
        restart=copy.deepcopy(self.store.read().ledger)
        self.assertEqual(recover_after_crash(restart),1)
        recovered=self.store.write(restart,attempt.sha,"uncertain")
        self.assertEqual(self.store.read().ledger["batches"][task]["state"],"UNCERTAIN")
    def test_duplicate_version_refused(self):
        s=self.store.write(empty_ledger(),None,"initialize")
        with self.assertRaises(remote.CASConflict):self.store.write(empty_ledger(),"0"*40,"stale")
    def test_read_corruption_fails(self):
        self.store.write(empty_ledger(),None,"initialize")
        self.transport.tamper_read=True
        with self.assertRaises(remote.PersistenceError):self.store.read()
    def test_network_error_fails(self):
        self.transport.fail=True
        with self.assertRaises(remote.PersistenceError):self.store.read()
    def test_invalid_schema_cannot_be_written(self):
        with self.assertRaises(SafetyError):self.store.write({"schema_version":77,"batches":{}},None,"invalid")
    def test_invalid_expected_sha(self):
        with self.assertRaises(SafetyError):self.store.write(empty_ledger(),"not-a-sha","invalid")
    def test_read_after_write_rejected_on_mismatch(self):
        class Tamper(FakeTransport):
            def request(self,method,route,payload=None):
                result=super().request(method,route,payload)
                if method=="PUT":self.doc=b'{"schema_version":1,"batches":{},"tampered":true}'
                return result
        s=remote.ProbeStore("Haokai-L/zotero-arxiv-daily","feature/ccf-a-daily",
             self.store.path,Tamper())
        with self.assertRaises(remote.PersistenceError):s.write(empty_ledger(),None,"test")
    def test_probe_state_is_synthetic(self):
        self.assertTrue(all(x["paper_key"].startswith("synthetic:r64:")
            for x in probe.synthetic_rows("45153022186")))
    def test_no_smtp_import(self):
        for path in (remote.__file__,probe.__file__):
            data=Path(path).read_text()
            self.assertNotIn("import smtplib",data)
            self.assertNotIn("send_message(",data)
    def test_serialization_determinism(self):
        self.assertEqual(remote.canonical_bytes(empty_ledger()),remote.canonical_bytes(copy.deepcopy(empty_ledger())))
    def test_probe_id_allowlist_bounds(self):
        for bad in ("data/r64_probes/123.json","data/r64_probes/123456-.json",
                    "data/r64_probes/x-1.json","data/r64_probes/123456-0.yaml"):
            with self.assertRaises(SafetyError):remote.ProbeStore("Haokai-L/zotero-arxiv-daily",
                "feature/ccf-a-daily",bad,self.transport)
if __name__=="__main__":unittest.main()
