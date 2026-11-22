"""R3-2 pure offline journal metadata quality rules; no network or secrets."""
import re
import unicodedata
from datetime import date

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)
NOTICE_RE = re.compile(
    r"^(?:correction(?:\s+to)?|errat(?:a|um)|corrigendum|retraction|"
    r"withdrawal|expression of concern|author correction|publisher correction|"
    r"editorial|comment(?:ary)?\s+on|reply\s+to)\b", re.I
)
def short_id(v):
    return str(v or "").rsplit("/", 1)[-1]

def norm_doi(raw):
    if not raw:
        return ""
    s = str(raw).strip().lower()
    s = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", s)
    return s if DOI_RE.fullmatch(s) else ""

def norm_title(value):
    s = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(ch for ch in s if ch.isalnum())

def validate_source(actual, expected):
    if short_id(actual.get("id")) != expected["id"]:
        return "SOURCE_ID_MISMATCH"
    if str(actual.get("display_name") or "").strip().casefold() != expected["title"].casefold():
        return "SOURCE_TITLE_MISMATCH"
    if actual.get("type") != "journal":
        return "SOURCE_NOT_JOURNAL"
    observed = set(actual.get("issn") or [])
    observed.add(actual.get("issn_l"))
    if not set(expected["issn"]).issubset(observed):
        return "SOURCE_ISSN_MISMATCH"
    return "SOURCE_ID_TITLE_ISSN_MATCH"

def classify(paper, venue, field, expected, cutoff):
    title = str(paper.get("title") or "").strip()
    year = paper.get("publication_year")
    published = str(paper.get("publication_date") or "")
    doi = norm_doi(paper.get("doi"))
    source = (paper.get("primary_location") or {}).get("source") or {}
    reasons = []
    if short_id(source.get("id")) != expected["id"]:
        reasons.append("WRONG_PRIMARY_SOURCE")
    if len(norm_title(title)) < 15:
        reasons.append("MISSING_OR_SHORT_TITLE")
    if paper.get("type") != "article":
        reasons.append("NOT_RESEARCH_ARTICLE_TYPE")
    if NOTICE_RE.search(title):
        reasons.append("NOTICE_OR_CORRECTION_TITLE")
    try:
        pdate = date.fromisoformat(published)
    except ValueError:
        reasons.append("INVALID_DATE")
        pdate = None
    if pdate and not ("2024-01-01" <= published <= cutoff):
        reasons.append("OUT_OF_DATE_RANGE")
    if not isinstance(year, int) or not expected["from_year"] <= year <= expected["to_year"]:
        reasons.append("SOURCE_YEAR_TRANSITION_MISMATCH")
    if pdate and isinstance(year, int) and pdate.year != year:
        reasons.append("YEAR_DATE_INCONSISTENT")
    if not doi:
        reasons.append("MISSING_OR_INVALID_DOI")
    else:
        prefix = "10.1007/" if venue == "JOC" else "10.1109/"
        series = prefix + expected["doi_series"].lower()
        if not doi.startswith(series) or (venue != "JOC" and not doi.startswith(series + ".")):
            reasons.append("WRONG_PUBLISHER_DOI_SERIES")
    status = "REJECT" if reasons else "REVIEW" if expected.get("legacy_review") else "PASS_METADATA_RULES"
    if status == "REVIEW":
        reasons.append("TON_PREDECESSOR_CCF_CONTINUITY_NEEDS_REVIEW")
    return dict(venue=venue, field=field, status=status, reason=";".join(reasons),
                source_openalex_id=expected["id"], source_title=expected["title"],
                title=title, year=year, date=published, doi=doi,
                openalex_id=paper.get("id") or "", paper_type=paper.get("type") or "")

def deduplicate(rows):
    priority = {"PASS_METADATA_RULES":0,"REVIEW":1,"REJECT":2}
    ordered = sorted(rows, key=lambda r: (priority[r["status"]],r["venue"],-(r["year"] or 0),r["doi"]))
    seen_doi, seen_title, output = set(), set(), []
    for row in ordered:
        r = dict(row)
        if r["status"] != "REJECT":
            doi, title = r["doi"], norm_title(r["title"])
            if (doi and doi in seen_doi) or (title and title in seen_title):
                r["status"]="REJECT"
                r["reason"]=(r["reason"]+";" if r["reason"] else "")+"DUPLICATE_DOI_OR_TITLE"
            else:
                if doi: seen_doi.add(doi)
                if title: seen_title.add(title)
        output.append(r)
    return output
