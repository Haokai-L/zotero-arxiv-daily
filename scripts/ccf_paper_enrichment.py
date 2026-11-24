"""Bounded abstract enrichment for previously audited CCF formal-source candidates.

Candidate status remains PRELIMINARY. No preprint-source discovery or email.
"""
import argparse
import csv
import json
import os
import time
from collections import Counter,defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import quote,urlparse,urlencode
from urllib.request import Request,urlopen
from ccf_recommend_core import normalize_title
FIELDS=['paper_key','venue','field','year','title','doi','paper_url','pdf_url','candidate_status','source_status','source_record_id','evidence_url','authors','abstract','abstract_status','abstract_evidence_url']
def abstract_from_inverted(index):
    if not isinstance(index,dict):return ''
    pairs=[(p,w) for w,positions in index.items() for p in positions if isinstance(p,int) and 0<=p<2500]
    if not pairs:return ''
    words=['']*(max(p for p,_ in pairs)+1)
    for p,w in pairs:words[p]=w
    return ' '.join(words).strip()
def openalex_work(row,api_key):
    doi=str(row.get('doi') or '').strip()
    oid=str(row.get('source_record_id') or '')
    if oid.startswith('https://openalex.org/W'):
        ident=oid.rsplit('/',1)[-1]
    elif doi:
        ident='https://doi.org/'+doi
    else:
        # DOI-less official proceedings: use exact normalized title and year, never a fuzzy-only match.
        ident=None
    url=('https://api.openalex.org/works/'+quote(ident,safe='/:') if ident else
         'https://api.openalex.org/works?'+urlencode({'search':row['title'], 'filter':'publication_year:'+str(row['year']), 'per_page':10}))
    headers={'Accept':'application/json','User-Agent':'CCF-R41-Abstract-Audit/1.0'}
    if api_key:headers['Authorization']='Bearer '+api_key
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers=headers),timeout=16) as response:
                if 'json' not in response.headers.get('Content-Type','').lower():
                    raise RuntimeError('Unexpected content type')
                data=json.load(response)
                if ident:return data
                matches=[w for w in data.get('results',[]) if normalize_title(w.get('display_name') or w.get('title'))==normalize_title(row['title']) and str(w.get('publication_year'))==str(row['year'])]
                return matches[0] if len(matches)==1 else None
        except HTTPError as exc:
            if exc.code==404:return None
            if exc.code not in (429,500,502,503,504):return None
        except (URLError,TimeoutError,OSError):
            pass
        if attempt<2:time.sleep(attempt+1)
    return None
def enrich_one(row,work):
    item={k:row.get(k,'') for k in FIELDS}
    item.update(abstract='',authors='',abstract_status='NO_OPENALEX_RECORD',abstract_evidence_url='')
    if not work:return item
    source_doi=str(row.get('doi') or '').lower()
    work_doi=str(work.get('doi') or '').lower().removeprefix('https://doi.org/')
    if source_doi and source_doi!=work_doi:
        item['abstract_status']='DOI_MISMATCH';return item
    match=SequenceMatcher(None,normalize_title(row.get('title')),normalize_title(work.get('display_name') or work.get('title'))).ratio()
    if match<0.78:
        item['abstract_status']='TITLE_MISMATCH';return item
    abstract=abstract_from_inverted(work.get('abstract_inverted_index'))
    if len(abstract)<90:
        item['abstract_status']='ABSTRACT_UNAVAILABLE';return item
    item['abstract']=abstract
    item['authors']=json.dumps([a.get('author',{}).get('display_name') for a in work.get('authorships',[]) if a.get('author',{}).get('display_name')],ensure_ascii=False)
    loc=work.get('best_oa_location') or work.get('primary_location') or {}
    pdf=str(loc.get('pdf_url') or '')
    host=urlparse(pdf).hostname or ''
    if pdf.startswith('https://') and not any(t in host for t in ('arxiv.org','biorxiv.org','medrxiv.org','zenodo.org')):
        item['pdf_url']=pdf
    item['abstract_status']='ABSTRACT_VERIFIED_METADATA'
    item['abstract_evidence_url']=str(work.get('id') or '')
    return item
def sample_balanced(rows,per_venue):
    groups=defaultdict(list)
    for row in rows:
        if row.get('candidate_status')=='PRELIMINARY':
            groups[row['venue']].append(row)
    return [row for venue in sorted(groups) for row in groups[venue][:per_venue]]
