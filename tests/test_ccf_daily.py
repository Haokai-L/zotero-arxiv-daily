import sys,unittest
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import ccf_daily as d
from ccf_recommend_preview import in_research_collection

H={"schema_version":1,"sent_keys":[]}
L={"schema_version":1,"batches":{}}
W={"TMC":{"field":"networking"}}
def row(i,year="2026"):
    doi="10.1109/tmc."+year+"."+str(i)
    return dict(paper_key="doi:"+doi,doi=doi,venue="TMC",field="networking",year=year,
        title="Network research paper "+str(i),paper_url="https://doi.org/"+doi,
        candidate_status="PRELIMINARY",score=float(i))
def proof(r):
    return dict(r,publisher_verification="VERIFIED_PUBLISHER",
                verification_evidence="https://api.crossref.org/works/"+r["doi"],
                verification_reason="TEST")
def abstract(r):
    return dict(r,abstract="A genuine networking systems abstract with detailed methodology and experimental evaluation. "*3,
                abstract_status="ABSTRACT_VERIFIED_METADATA")
def rank(rows,corpus,title_only=False):
    return sorted(rows,key=lambda x:-x["score"])
class Daily(unittest.TestCase):
    def test_collection_scope(self):
        self.assertTrue(in_research_collection(["A-NRC-Research"]))
        self.assertTrue(in_research_collection(["A-NRC-Research/child/deep"]))
        self.assertFalse(in_research_collection(["A-NRC-Research-old","Other/A-NRC-Research"]))
    def test_window_and_cleanup(self):
        papers=[row(1,"2024"),row(2,"2023"),row(3),row(4,"2027")]
        state={"papers":{r["paper_key"]:r for r in papers}}
        hist=dict(H,sent_keys=[papers[2]["paper_key"]])
        today=date(2026,11,24)
        self.assertEqual([r["year"] for r in d.eligible(state,W,hist,L,today)],["2024"])
        self.assertEqual(len(d.prune(state,hist,L,today)["papers"]),1)
    def test_no_venue_or_date_quota(self):
        papers=[row(i,"2024" if i==12 else "2026") for i in range(1,13)]
        selected=d.recommend(papers,[object()],W,H,L,rank=rank,abstract=abstract,verify=proof)
        self.assertEqual([r["score"] for r in selected],[12,11,10])
    def test_falls_through_unverified(self):
        papers=[row(i) for i in range(1,6)]
        selected=d.recommend(papers,[object()],W,H,L,rank=rank,abstract=abstract,
            verify=lambda r:{} if r["score"]==5 else proof(r))
        self.assertEqual([r["score"] for r in selected],[4,3,2])
    def test_no_fake_papers(self):
        self.assertEqual(d.recommend([row(1)],[object()],W,H,L,rank=rank,
            abstract=lambda r:{},verify=proof),[])
    def test_future_publication(self):
        self.assertFalse(d.within_window(dict(row(1),publication_date="2026-12-30"),date(2026,11,24)))
if __name__=="__main__":unittest.main()
