"""No-send consolidated entrypoint adversarial tests, with fake local corpus."""
import csv
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ccf_daily_preview as daily
from ccf_r63_delivery import SafetyError


class Reference:
    added_date = datetime(2026, 11, 1)


def row(index=1):
    doi="10.1109/tmc.2026." + str(index)
    return {"paper_key":"doi:"+doi,"doi":doi,"venue":"TMC",
        "field":"networking","year":"2026","title":"Trustworthy network service recovery "+str(index),
        "paper_url":"https://doi.org/"+doi,"candidate_status":"PRELIMINARY",
        "abstract_status":"ABSTRACT_VERIFIED_METADATA",
        "abstract":"The paper presents a comprehensive study of reliable network services "
             "under deadline constraints with experiments on recovery and optimization."*2,
        "score":"4.2","authors":"[]","pdf_url":""}


def evidence(r):
    return {**r,"publisher_verification":"VERIFIED_PUBLISHER",
        "verification_evidence":"https://api.crossref.org/works/"+r["doi"]}


def write_csv(path,rows):
    fields=sorted({k for r in rows for k in r})
    with open(path,"w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader();writer.writerows(rows)


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.rows=[row(i) for i in range(1,5)]
        self.proofs=[evidence(r) for r in self.rows]
        self.verified=self.root/"verified.csv"
        self.enriched=self.root/"enriched.csv"
        self.history=self.root/"history.json"
        self.ledger=self.root/"ledger.json"
        self.whitelist=self.root/"whitelist.yaml"
        self.cfg=self.root/"mail.yaml"
        self.out=self.root/"out"
        write_csv(self.verified,self.proofs)
        write_csv(self.enriched,self.rows)
        self.history.write_text(json.dumps({"schema_version":1,"sent_keys":[]}))
        self.ledger.write_text(json.dumps({"schema_version":1,"batches":{}}))
        venues="".join("  V"+str(i)+":\n    field: networking\n" for i in range(15))
        self.whitelist.write_text("venues:\n  TMC:\n    field: networking\n"+venues)
        self.cfg.write_text("daily_max: 3\nsend_enabled: false\npreview_only: true\nmodel: deepseek-chat\n")
        self.corpus=[Reference(),Reference()]
    def runit(self):
        with patch.object(daily,"original_rerank",
                          side_effect=lambda rows,corpus:[dict(x,score=float(x["score"])) for x in rows]):
            return daily.assemble(self.verified,self.enriched,self.history,self.ledger,
                    self.whitelist,self.cfg,self.out,corpus=self.corpus,env={})
    def test_end_to_end_three_verified_and_no_send(self):
        before_h=self.history.read_bytes();before_l=self.ledger.read_bytes()
        audit=self.runit()
        self.assertEqual(audit["selected_count"],3)
        self.assertTrue(audit["simulated_auto_retry_blocked"])
        self.assertFalse(audit["email_sent"])
        self.assertEqual(self.history.read_bytes(),before_h)
        self.assertEqual(self.ledger.read_bytes(),before_l)
        self.assertTrue((self.out/"email_preview.html").is_file())
    def test_mismatched_publisher_proof_fails_closed(self):
        bad=[dict(x,title="Unrelated conference paper") for x in self.proofs]
        write_csv(self.verified,bad)
        with self.assertRaises(SafetyError):self.runit()
    def test_missing_verified_status_fails_closed(self):
        write_csv(self.verified,[dict(x,publisher_verification="REVIEW") for x in self.proofs])
        with self.assertRaises(SafetyError):self.runit()
    def test_production_send_enabled_fails_closed(self):
        self.cfg.write_text("daily_max: 3\nsend_enabled: true\npreview_only: false\n")
        with self.assertRaises(SafetyError):self.runit()
    def test_empty_corpus_fails_closed(self):
        self.corpus=[]
        with self.assertRaises(SafetyError):self.runit()
    def test_no_abstract_fails_closed(self):
        write_csv(self.enriched,[dict(x,abstract="",abstract_status="ABSTRACT_UNAVAILABLE") for x in self.rows])
        with self.assertRaises(SafetyError):self.runit()
    def test_only_one_proof_yields_one_paper(self):
        write_csv(self.verified,self.proofs[:1])
        result=self.runit()
        self.assertEqual(result["selected_count"],1)


if __name__=="__main__":
    unittest.main()
