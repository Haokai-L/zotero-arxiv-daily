import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import ccf_journal_quality as q
JSAC={"id":"S90422530","title":"IEEE Journal on Selected Areas in Communications",
      "issn":["0733-8716","1558-0008"],"doi_series":"jsac","from_year":2024,"to_year":2026}
TMC={"id":"S69141925","title":"IEEE Transactions on Mobile Computing",
     "issn":["1536-1233","1558-0660","2161-9875"],"doi_series":"tmc","from_year":2024,"to_year":2026}
OLD={"id":"S62238642","title":"IEEE/ACM Transactions on Networking",
     "issn":["1063-6692","1558-2566"],"doi_series":"tnet","from_year":2024,"to_year":2024,"legacy_review":True}
NEW={"id":"S5407042750","title":"IEEE Transactions on Networking","issn":["2998-4157"],
     "doi_series":"ton","from_year":2025,"to_year":2026}
def paper(s=JSAC,doi="10.1109/jsac.2026.3736759",
          title="Communication-efficient quantum network research",year=2026,kind="article"):
    return {"id":"https://openalex.org/W1","title":title,"publication_year":year,
      "publication_date":f"{year}-06-12","type":kind,"doi":"https://doi.org/"+doi,
      "primary_location":{"source":{"id":"https://openalex.org/"+s["id"]}}}
class QualityTests(unittest.TestCase):
    def test_valid_source(self):
        s=dict(id="https://openalex.org/S90422530",display_name=JSAC["title"],
               issn=JSAC["issn"],type="journal")
        self.assertEqual(q.validate_source(s,JSAC),"SOURCE_ID_TITLE_ISSN_MATCH")
    def test_invalid_source_issn(self):
        s=dict(id="https://openalex.org/S90422530",display_name=JSAC["title"],
               issn=["0000-0000"],type="journal")
        self.assertEqual(q.validate_source(s,JSAC),"SOURCE_ISSN_MISMATCH")
    def test_real_zenodo_records(self):
        for doi in ("10.5281/zenodo.20171141","10.5281/zenodo.20171142"):
            p=paper(doi=doi,title="QPing: a Quantum Ping Primitive for Quantum Networks")
            self.assertEqual(q.classify(p,"JSAC","networking",JSAC,"2026-11-22")["status"],"REJECT")
    def test_real_tmc_erratum(self):
        p=paper(s=TMC,doi="10.1109/tmc.2026.3723373",
          title="Correction to Optimal Zone Routing Scheme for LEO Mega-Constellation Networks",kind="erratum")
        r=q.classify(p,"TMC","networking",TMC,"2026-11-22")
        self.assertEqual(r["status"],"REJECT")
        self.assertIn("NOTICE_OR_CORRECTION_TITLE",r["reason"])
    def test_valid_tmc(self):
        p=paper(s=TMC,doi="10.1109/tmc.2026.3732290",
          title="Reliability-Security-Efficiency Trade-Offs in Multi-UAV-Assisted MEC for URLLC")
        self.assertEqual(q.classify(p,"TMC","networking",TMC,"2026-11-22")["status"],"PASS_METADATA_RULES")
    def test_old_ton_review(self):
        p=paper(s=OLD,year=2024,doi="10.1109/tnet.2024.3513677")
        self.assertEqual(q.classify(p,"TON","networking",OLD,"2026-11-22")["status"],"REVIEW")
    def test_new_ton(self):
        p=paper(s=NEW,year=2025,doi="10.1109/ton.2025.3616613")
        self.assertEqual(q.classify(p,"TON","networking",NEW,"2026-11-22")["status"],"PASS_METADATA_RULES")
    def test_wrong_transition(self):
        p=paper(s=OLD,year=2025,doi="10.1109/tnet.2024.3513677")
        self.assertEqual(q.classify(p,"TON","networking",OLD,"2026-11-22")["status"],"REJECT")
    def test_duplicate_title(self):
        r=q.classify(paper(),"JSAC","networking",JSAC,"2026-11-22")
        t=dict(r,doi="10.1109/jsac.2026.999999",title=r["title"]+"!")
        self.assertEqual(sum(x["status"]=="REJECT" for x in q.deduplicate([r,t])),1)
    def test_future_date(self):
        p=paper();p["publication_date"]="2026-11-23"
        self.assertEqual(q.classify(p,"JSAC","networking",JSAC,"2026-11-22")["status"],"REJECT")
    def test_wrong_primary_source(self):
        p=paper();p["primary_location"]["source"]["id"]="https://openalex.org/S11111"
        self.assertEqual(q.classify(p,"JSAC","networking",JSAC,"2026-11-22")["status"],"REJECT")
if __name__=="__main__":
    unittest.main()
