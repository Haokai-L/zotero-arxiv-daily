"""Conservative R3-3 classification for *2025* main-conference evidence only.

A Crossref DOI/title/year match or official paper listing is independently auditable
metadata; neither constitutes automatic CCF A acceptance for other years.
"""
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

BAD_CONTAINER = re.compile(r"\b(workshops?|posters?|demos?|demonstrations?|tutorials?|doctoral\s+symposium|adjunct)\b", re.I)
BAD_TITLE = re.compile(r"^(?:poster|demo(?:nstration)?|workshop|tutorial|errat(?:um|a)|correction|retraction)\b", re.I)
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)

def normalize(s):
    s=unicodedata.normalize("NFKC", str(s or "")).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+"," ",s).split())

def doi_of(s):
    raw=str(s or "").strip().lower()
    raw=re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)","",raw)
    return raw if DOI_RE.fullmatch(raw) else ""

def published_year(item):
    for field in ("published","published-online","published-print","issued"):
        parts=(item.get(field) or {}).get("date-parts") or []
        if parts and parts[0] and isinstance(parts[0][0],int):
            return parts[0][0]
    return None

def check_crossref(record, venue, settings, year=2025):
    title=next(iter(record.get("title") or []),"").strip()
    containers=record.get("container-title") or []
    container=next(iter(containers),"")
    doi=doi_of(record.get("DOI"))
    typ=str(record.get("type") or "")
    pub=published_year(record)
    reasons=[]
    if pub!=year:
        reasons.append("PUBLICATION_YEAR_MISMATCH")
    if not title or len(normalize(title))<14:
        reasons.append("EMPTY_OR_SHORT_TITLE")
    if BAD_TITLE.search(title):
        reasons.append("POSTER_DEMO_OR_NOTICE_TITLE")
    if BAD_CONTAINER.search(container):
        reasons.append("WORKSHOP_POSTER_DEMO_CONTAINER")
    ncontainer=normalize(container)
    springer_parent_doi=""
    if venue in ("CRYPTO","EUROCRYPT"):
        # Springer deposits chapter titles under generic "Lecture Notes in Computer Science".
        # Check the *exact* verified 2025 volume DOI instead of the generic series title.
        parents=settings.get("verified_book_dois") or []
        if "lecture notes in computer science" not in ncontainer:
            reasons.append("WRONG_SPRINGER_SERIES")
        if not any(doi.startswith(book_doi.lower()+"_") and doi[len(book_doi)+1:].isdigit()
                   for book_doi in parents):
            reasons.append("UNVERIFIED_SPRINGER_BOOK_DOI")
        else:
            springer_parent_doi=next(book for book in parents if doi.startswith(book.lower()+"_"))
    elif not ncontainer or not any(normalize(a) in ncontainer for a in settings["aliases"]):
        reasons.append("NON_MAIN_PROCEEDINGS_TITLE")
    expected_type="book-chapter" if venue in ("CRYPTO","EUROCRYPT") else "proceedings-article"
    if typ!=expected_type:
        reasons.append("WRONG_CROSSREF_TYPE")
    if not doi:
        reasons.append("MISSING_OR_INVALID_DOI")
    elif not doi.startswith(settings["doi_prefix"]):
        reasons.append("WRONG_DOI_REGISTRANT")
    publisher=normalize(record.get("publisher") or "")
    expected=settings.get("publisher")
    if expected=="ACM" and "computing machinery" not in publisher and publisher!="acm":
        reasons.append("PUBLISHER_MISMATCH")
    if expected=="IEEE" and "ieee" not in publisher and "electrical and electronics engineers" not in publisher:
        reasons.append("PUBLISHER_MISMATCH")
    if expected=="Springer" and "springer" not in publisher:
        reasons.append("PUBLISHER_MISMATCH")
    return {
        "venue":venue,"year":year,"title":title,"doi":doi,
        "paper_url":record.get("URL") or ("https://doi.org/"+doi if doi else ""),
        "container":container,"publisher":record.get("publisher") or "",
        "record_type":typ,"source":"Crossref","official_evidence_url":("https://link.springer.com/book/"+springer_parent_doi if springer_parent_doi else settings["official_url"]),
        "status":"REVIEW" if reasons else
            "SPRINGER_BOOK_MATCH" if venue in ("CRYPTO","EUROCRYPT") else "CROSSREF_META_MATCH",
        "reason":";".join(reasons)
    }

def official_link_allowed(url,settings):
    parsed=urlparse(url)
    path=parsed.path.rstrip("/")
    if settings["official_type"]=="usenix":
        return parsed.hostname in {"www.usenix.org","usenix.org"} and (
            re.fullmatch(r"/conference/"+re.escape(settings["slug"])+r"/presentation/[a-zA-Z0-9_-]+",path) is not None
        )
    if settings["official_type"]=="ndss":
        return parsed.hostname in {"ndss-symposium.org","www.ndss-symposium.org"} and path.startswith("/ndss-paper/") and len(path)>len("/ndss-paper/")
    return False

class LinkParser(HTMLParser):
    def __init__(self,base,settings):
        super().__init__(convert_charrefs=True)
        self.base=base; self.settings=settings
        self.current=None; self.text=[]; self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=="a":
            url=urljoin(self.base,dict(attrs).get("href") or "")
            if official_link_allowed(url,self.settings):
                self.current=url
                self.text=[]
    def handle_data(self,data):
        if self.current:
            self.text.append(data)
    def handle_endtag(self,tag):
        if tag=="a" and self.current:
            label=" ".join("".join(self.text).split())
            if len(normalize(label))>=14 and not BAD_TITLE.search(label):
                self.links.append((label,self.current))
            self.current=None
            self.text=[]
def parse_official_listing(html,venue,settings,year=2025):
    parser=LinkParser(settings["official_url"],settings)
    parser.feed(html)
    seen=set(); result=[]
    for title,url in parser.links:
        if url in seen: continue
        seen.add(url)
        result.append({
            "venue":venue,"year":year,"title":title,"doi":"",
            "paper_url":url,"container":venue+" "+str(year),
            "publisher":"USENIX Association" if settings["official_type"]=="usenix" else "Internet Society",
            "record_type":"official-paper-page","source":"Official conference listing",
            "official_evidence_url":settings["official_url"],
            "status":"OFFICIAL_LISTED","reason":"NO_DOI_REQUIRED_OFFICIAL_SOURCE"
        })
    return result

def deduplicate(rows):
    preferred={"OFFICIAL_LISTED":0,"CROSSREF_META_MATCH":0,"SPRINGER_BOOK_MATCH":0,"REVIEW":1}
    seen_doi=set();seen_title=set();out=[]
    for row in sorted(rows,key=lambda r:(preferred.get(r["status"],2),r["venue"],normalize(r["title"]))):
        item=dict(row)
        doi=item.get("doi") or ""
        title=(item["venue"],normalize(item["title"]))
        if (doi and doi in seen_doi) or title in seen_title:
            item["status"]="EXCLUDED_DUPLICATE"
            item["reason"]="DUPLICATE_DOI_OR_VENUE_TITLE"
        else:
            if doi: seen_doi.add(doi)
            seen_title.add(title)
        out.append(item)
    return out
