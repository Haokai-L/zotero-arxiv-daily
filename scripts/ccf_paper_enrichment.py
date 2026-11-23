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
from urllib.parse import quote,urlparse
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
        return None
    url='https://api.openalex.org/works/'+quote(ident,safe='/:')
    headers={'Accept':'application/json','User-Agent':'CCF-R41-Abstract-Audit/1.0'}
    if api_key:headers['Authorization']='Bearer '+api_key
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers=headers),timeout=16) as response:
                if 'json' not in response.headers.get('Content-Type','').lower():
                    raise RuntimeError('Unexpected content type')
                return json.load(response)
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
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,default=Path('ccf-r41-preview'))
    p.add_argument('--per-venue',type=int,default=4)
    args=p.parse_args()
    if not 1<=args.per_venue<=10:raise SystemExit('per-venue must be 1..10')
    with args.input.open(encoding='utf-8-sig',newline='') as f:
        sampled=sample_balanced(list(csv.DictReader(f)),args.per_venue)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    results=[];api_key=os.environ.get('OPENALEX_API_KEY','').strip()
    for i,row in enumerate(sampled,1):
        results.append(enrich_one(row,openalex_work(row,api_key)))
        if i%10==0:print(f'Metadata requests {i}/{len(sampled)}',flush=True)
        time.sleep(0.18)
    with (args.output_dir/'enriched_candidates.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(results)
    counts=dict(Counter(r['abstract_status'] for r in results))
    report={'stage':'R4-1','scope':'BOUNDED_ABSTRACT_PREVIEW_NOT_COMPLETE_CCF_CRAWL','sampled':len(sampled),
       'venues_sampled':len({r['venue'] for r in sampled}),'abstract_counts':counts,
       'usable_abstracts':counts.get('ABSTRACT_VERIFIED_METADATA',0),'email_sent':False,
       'caveat':'Source candidates stay PRELIMINARY pending publisher verification.'}
    (args.output_dir/'enrichment_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('ENRICHMENT '+json.dumps(report,ensure_ascii=False),flush=True)
    if report['usable_abstracts']<3:
        raise SystemExit('Insufficient authentic abstracts for three-paper scoring preview')
if __name__=='__main__':
    main()
