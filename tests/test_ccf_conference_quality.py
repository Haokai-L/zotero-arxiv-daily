import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import ccf_conference_quality as q

def settings(venue="CCS"):
    prefix={"CCS":"10.1145/","EUROCRYPT":"10.1007/","INFOCOM":"10.1109/"}
    title={"CCS":"Proceedings of the 2025 ACM SIGSAC Conference on Computer and Communications Security",
           "EUROCRYPT":"Advances in Cryptology – EUROCRYPT 2025",
           "INFOCOM":"2025 IEEE International Conference on Computer Communications (INFOCOM)"}
    publisher={"CCS":"ACM","EUROCRYPT":"Springer","INFOCOM":"IEEE"}
    return {"aliases":[title[venue]],"doi_prefix":prefix[venue],
            "publisher":publisher[venue],"official_url":"https://example.org/2025"}
def record(venue="CCS",title="A Security Paper With Trusted Conference Provenance"):
    conf=settings(venue)
    return {"title":[title],"container-title":[conf["aliases"][0]],"type":
            "book-chapter" if venue=="EUROCRYPT" else "proceedings-article",
            "published":{"date-parts":[[2025,9,1]]},"DOI":
            conf["doi_prefix"]+"3719027.3765206",
            "publisher":{"CCS":"Association for Computing Machinery (ACM)",
                         "EUROCRYPT":"Springer Science and Business Media LLC",
                         "INFOCOM":"Institute of Electrical and Electronics Engineers (IEEE)"}[venue]}
class R33Tests(unittest.TestCase):
    def test_acm_main(self):
        self.assertEqual(q.check_crossref(record(),"CCS",settings())["status"],"CROSSREF_META_MATCH")
    def test_ieee_main(self):
        self.assertEqual(q.check_crossref(record("INFOCOM"),"INFOCOM",settings("INFOCOM"))["status"],"CROSSREF_META_MATCH")
    def test_springer_book_chapter(self):
        self.assertEqual(q.check_crossref(record("EUROCRYPT"),"EUROCRYPT",settings("EUROCRYPT"))["status"],"CROSSREF_META_MATCH")
    def test_workshop_not_main(self):
        r=record();r["container-title"]=["Workshop on ACM Conference on Computer and Communications Security 2025"]
        self.assertEqual(q.check_crossref(r,"CCS",settings())["status"],"REVIEW")
    def test_poster_excluded(self):
        self.assertEqual(q.check_crossref(record(title="Poster: An interesting finding"),"CCS",settings())["status"],"REVIEW")
    def test_wrong_doi(self):
        r=record();r["DOI"]="10.5281/zenodo.12345"
        self.assertIn("WRONG_DOI_REGISTRANT",q.check_crossref(r,"CCS",settings())["reason"])
    def test_wrong_year(self):
        r=record();r["published"]={"date-parts":[[2024,1,1]]}
        self.assertEqual(q.check_crossref(r,"CCS",settings())["status"],"REVIEW")
    def test_wrong_document_type(self):
        r=record();r["type"]="journal-article"
        self.assertEqual(q.check_crossref(r,"CCS",settings())["status"],"REVIEW")
    def test_verified_crypto_book_chapter(self):
        s=settings("EUROCRYPT")
        s["verified_book_dois"]=["10.1007/978-3-031-91107-1"]
        r=record("EUROCRYPT")
        r["container-title"]=["Lecture Notes in Computer Science"]
        r["DOI"]="10.1007/978-3-031-91107-1_7"
        p=q.check_crossref(r,"EUROCRYPT",s)
        self.assertEqual(p["status"],"SPRINGER_BOOK_MATCH")
        self.assertEqual(p["official_evidence_url"],
                         "https://link.springer.com/book/10.1007/978-3-031-91107-1")
    def test_unverified_lncs_rejected(self):
        s=settings("EUROCRYPT")
        s["verified_book_dois"]=["10.1007/978-3-031-91107-1"]
        r=record("EUROCRYPT")
        r["container-title"]=["Lecture Notes in Computer Science"]
        r["DOI"]="10.1007/978-3-031-99999-9_1"
        p=q.check_crossref(r,"EUROCRYPT",s)
        self.assertEqual(p["status"],"REVIEW")
        self.assertIn("UNVERIFIED_SPRINGER_BOOK_DOI",p["reason"])
    def test_crypto_book_chapter(self):
        s=settings("EUROCRYPT")
        s["verified_book_dois"]=["10.1007/978-3-032-01901-1"]
        r=record("EUROCRYPT")
        r["container-title"]=["Lecture Notes in Computer Science"]
        r["DOI"]="10.1007/978-3-032-01901-1_18"
        p=q.check_crossref(r,"CRYPTO",s)
        self.assertEqual(p["status"],"SPRINGER_BOOK_MATCH")
    def test_official_usenix_valid(self):
        cfg={"official_type":"usenix","slug":"nsdi25","official_url":"https://www.usenix.org/conference/nsdi25/technical-sessions"}
        html='<a href="/conference/nsdi25/presentation/smith">Deadline-Aware Fault Recovery for Networked Services</a>'
        items=q.parse_official_listing(html,"NSDI",cfg)
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]["status"],"OFFICIAL_LISTED")
    def test_official_usenix_wrong_event_blocked(self):
        cfg={"official_type":"usenix","slug":"nsdi25","official_url":"https://www.usenix.org/conference/nsdi25/technical-sessions"}
        html='<a href="/conference/nsdi26/presentation/smith">Paper from Different Year</a>'
        self.assertEqual(q.parse_official_listing(html,"NSDI",cfg),[])
    def test_official_ndss(self):
        cfg={"official_type":"ndss","official_url":"https://www.ndss-symposium.org/ndss2025/accepted-papers/"}
        html='<h2><a href="/ndss-paper/some-good-paper/">A Legitimate Accepted NDSS Research Paper</a></h2>'
        self.assertEqual(q.parse_official_listing(html,"NDSS",cfg)[0]["status"],"OFFICIAL_LISTED")
    def test_ndss_poster_blocked(self):
        cfg={"official_type":"ndss","official_url":"https://www.ndss-symposium.org/ndss2025/accepted-papers/"}
        html='<a href="/ndss-paper/poster-track/">Poster: Special Poster</a>'
        self.assertEqual(q.parse_official_listing(html,"NDSS",cfg),[])
    def test_external_link_blocked(self):
        cfg={"official_type":"ndss","official_url":"https://www.ndss-symposium.org/ndss2025/accepted-papers/"}
        html='<a href="https://evil.example/ndss-paper/example/">Fake NDSS Paper Entry</a>'
        self.assertEqual(q.parse_official_listing(html,"NDSS",cfg),[])
    def test_duplicate(self):
        r=q.check_crossref(record(),"CCS",settings())
        items=q.deduplicate([r,dict(r,paper_url="https://crossref.example/other")])
        self.assertEqual(sum(x["status"]=="EXCLUDED_DUPLICATE" for x in items),1)
if __name__=="__main__":
    unittest.main()
