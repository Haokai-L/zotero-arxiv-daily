"""R6-1 independent bounded publisher/official proceedings verification. No email."""
import argparse,csv,json,re,time
from collections import Counter,defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote,urlsplit
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
import yaml
import ccf_conference_quality as cq
from ccf_recommend_core import normalize_title

ROOT=Path(__file__).resolve().parents[1]
FIELDS=['paper_key','venue','field','year','publication_date','date_precision','title','doi',
        'paper_url','pdf_url','source_type','source_record_id','source_status','candidate_status',
        'reason','evidence_url','source_file']
EXTRA=['publisher_verification','verification_reason','verification_evidence']
DOI=re.compile(r'^10\.\d{4,9}/\S+$')
PREPRINT=('arxiv.org','biorxiv.org','medrxiv.org','chemrxiv.org','zenodo.org')

def normdoi(value):
    s=str(value or '').strip().lower()
    s=re.sub(r'^https?://(?:dx\.)?doi\.org/','',s)
    return s if DOI.fullmatch(s) else ''

def safe_link(value):
    try:
        parsed=urlsplit(str(value or ''))
        host=(parsed.hostname or '').lower()
        return parsed.scheme=='https' and bool(host) and not any(
            host==x or host.endswith('.'+x) for x in PREPRINT)
    except ValueError:return False

def title_matches(a,b):
    x=normalize_title(a);y=normalize_title(b)
    return len(x)>=10 and len(y)>=10 and SequenceMatcher(None,x,y).ratio()>=0.82

def years(work):
    result=set()
    for field in ('published','published-online','published-print','issued'):
        for parts in (work.get(field) or {}).get('date-parts',[]):
            if parts and isinstance(parts[0],int):result.add(parts[0])
    return result

def crossref(doi):
    url='https://api.crossref.org/works/'+quote(doi,safe='/')
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={'Accept':'application/json',
                 'User-Agent':'CCF-R6-Independent-Verification/1.0'}),timeout=25) as r:
                if 'json' not in r.headers.get('Content-Type','').lower():
                    raise RuntimeError('Crossref non-JSON reply')
                obj=json.load(r)
                if obj.get('status')!='ok':raise RuntimeError('Crossref status')
                return obj['message']
        except HTTPError as e:
            if e.code==404:return None
            if e.code not in (429,500,502,503,504):raise RuntimeError('Crossref HTTP '+str(e.code))
        except (URLError,TimeoutError,OSError):pass
        if attempt<2:time.sleep(attempt+1)
    raise RuntimeError('Crossref retries exhausted')

def fetch_official(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={'Accept':'text/html',
                 'User-Agent':'CCF-R6-Official-List/1.0'}),timeout=25) as r:
                if 'html' not in r.headers.get('Content-Type','').lower():
                    raise RuntimeError('Non-HTML official listing')
                return r.read(5_000_000).decode('utf-8',errors='replace')
        except (HTTPError,URLError,TimeoutError,OSError):
            if attempt<2:time.sleep(attempt+1)
    raise RuntimeError('Official listing retries exhausted')

def journal_verdict(row,work,setting):
    if not work:return 'REVIEW','NO_CROSSREF_RECORD'
    if normdoi(work.get('DOI'))!=normdoi(row.get('doi')):return 'REVIEW','DOI_MISMATCH'
    if work.get('type')!='journal-article':return 'REVIEW','WRONG_TYPE'
    if not title_matches(row.get('title'),next(iter(work.get('title') or []),'')):
        return 'REVIEW','TITLE_MISMATCH'
    year=int(row['year'])
    if year not in years(work):return 'REVIEW','YEAR_MISMATCH'
    sources=[s for s in setting['sources'] if s['from_year']<=year<=s['to_year']
             and not s.get('legacy_review')]
    if not sources:return 'REVIEW','HISTORICAL_SOURCE_REVIEW'
    doi=normdoi(row['doi'])
    if not any('/'+s['doi_series'].lower() in doi for s in sources):
        return 'REVIEW','DOI_SERIES_MISMATCH'
    workissn={str(x).upper() for x in work.get('ISSN') or []}
    if not any(workissn.intersection({x.upper() for x in s['issn']}) for s in sources):
        return 'REVIEW','ISSN_MISMATCH'
    publisher=str(work.get('publisher') or '').lower()
    if row['venue']=='JOC':
        if 'springer' not in publisher:return 'REVIEW','PUBLISHER_MISMATCH'
    elif 'ieee' not in publisher and 'electrical and electronics engineers' not in publisher:
        return 'REVIEW','PUBLISHER_MISMATCH'
    if not next(iter(work.get('container-title') or []),''):
        return 'REVIEW','NO_CONTAINER_TITLE'
    return 'VERIFIED_PUBLISHER','DOI_TITLE_TYPE_ISSN_PUBLISHER_YEAR'

def conference_verdict(row,work,setting):
    if not work:return 'REVIEW','NO_CROSSREF_RECORD'
    if normdoi(work.get('DOI'))!=normdoi(row['doi']):return 'REVIEW','DOI_MISMATCH'
    if not title_matches(row['title'],next(iter(work.get('title') or []),'')):
        return 'REVIEW','TITLE_MISMATCH'
    result=cq.check_crossref(work,row['venue'],setting,int(row['year']))
    if result['status'] not in ('CROSSREF_META_MATCH','SPRINGER_BOOK_MATCH'):
        return 'REVIEW',result.get('reason') or 'NOT_MAIN_PROCEEDINGS'
    return 'VERIFIED_PUBLISHER','MAIN_PROCEEDINGS_CROSSREF_MATCH'

def official_verdict(row,listing):
    url=str(row.get('paper_url') or '').rstrip('/')
    match=next((p for p in listing if str(p['paper_url']).rstrip('/')==url),None)
    if match is None:return 'REVIEW','NOT_LISTED_BY_OFFICIAL_CONFERENCE'
    if not title_matches(row['title'],match['title']):return 'REVIEW','OFFICIAL_TITLE_MISMATCH'
    return 'VERIFIED_OFFICIAL','EXACT_OFFICIAL_URL_AND_TITLE'

def sample(state,venues,count):
    if state.get('schema_version')!=1 or not isinstance(state.get('papers'),dict):
        raise ValueError('Unexpected candidate-state schema')
    groups=defaultdict(list)
    for key,row in state['papers'].items():
        venue=row.get('venue')
        if venue not in venues or row.get('field')!=venues[venue]['field']:continue
        if row.get('candidate_status')!='PRELIMINARY' or row.get('paper_key')!=key:continue
        if str(row.get('year')) not in ('2025','2026') or not safe_link(row.get('paper_url')):continue
        if not str(row.get('title') or '').strip():continue
        groups[venue].append(row)
    return [r for venue in sorted(groups)
            for r in sorted(groups[venue],key=lambda x:(-int(x['year']),x['paper_key']))[:count]]

def check(row,journals,confs,crossref_get,official_get):
    result={key:str(row.get(key) or '') for key in FIELDS}
    venue=row['venue'];year=int(row['year']);doi=normdoi(row.get('doi'))
    setting=confs.get(year,{}).get('venues',{}).get(venue)
    if doi:
        work=crossref_get(doi)
        if venue in journals['journals']:
            status,reason=journal_verdict(row,work,journals['journals'][venue])
        elif setting:
            status,reason=conference_verdict(row,work,setting)
        else:status,reason='REVIEW','UNMAPPED_CONFERENCE_YEAR'
        evidence='https://api.crossref.org/works/'+quote(doi,safe='/')
    elif setting and setting.get('provider')=='official':
        listing=official_get(year,venue,setting)
        status,reason=official_verdict(row,listing)
        evidence=setting['official_url']
    else:status,reason,evidence='REVIEW','NO_VERIFIABLE_SOURCE',''
    result.update(publisher_verification=status,verification_reason=reason,
                  verification_evidence=evidence)
    # Status remains PRELIMINARY; verified is a separate evidence column.
    return result

def write_csv(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS+EXTRA,extrasaction='ignore')
        w.writeheader();w.writerows(rows)

def run(args):
    if not 1<=args.per_venue<=8:raise ValueError('Unsafe per-venue sample')
    whitelist=yaml.safe_load(args.whitelist.read_text(encoding='utf-8'))['venues']
    journals=yaml.safe_load(args.journals.read_text(encoding='utf-8'))
    confs={}
    for file in (args.conf25,args.conf26):
        obj=yaml.safe_load(file.read_text(encoding='utf-8'));confs[obj['year']]=obj
    if len(whitelist)!=16 or len(journals['journals'])!=6:raise ValueError('Wrong whitelist')
    rows=sample(json.loads(args.state.read_text(encoding='utf-8')),whitelist,args.per_venue)
    if not rows:raise ValueError('No source candidates')
    listing_cache={}
    def get_list(year,venue,setting):
        key=(year,venue)
        if key not in listing_cache:
            html=fetch_official(setting['official_url'])
            listing_cache[key]=cq.parse_official_listing(html,venue,setting,year)
        return listing_cache[key]
    checked=[]
    for i,row in enumerate(rows):
        try:result=check(row,journals,confs,crossref,get_list)
        except Exception as e:
            result={key:str(row.get(key) or '') for key in FIELDS}
            result.update(publisher_verification='API_ERROR',
                  verification_reason='EXTERNAL_'+type(e).__name__,verification_evidence='')
        checked.append(result)
        if (i+1)%10==0:print('SOURCE_VERIFY_PROGRESS '+str(i+1)+'/'+str(len(rows)),flush=True)
        time.sleep(.08)
    verified=[r for r in checked if r['publisher_verification'].startswith('VERIFIED_')]
    review=[r for r in checked if r['publisher_verification']=='REVIEW']
    errors=[r for r in checked if r['publisher_verification']=='API_ERROR']
    args.output.mkdir(parents=True,exist_ok=True)
    write_csv(args.output/'verified_candidates.csv',verified)
    write_csv(args.output/'review_candidates.csv',review+errors)
    report={'stage':'R6-1','scope':'BOUNDED_NOT_FULL_DATABASE_VERIFICATION',
        'checked':len(checked),'venues_sampled':len({r['venue'] for r in checked}),
        'verified':len(verified),'review':len(review),'api_error':len(errors),
        'verified_by_venue':dict(Counter(r['venue'] for r in verified)),
        'reasons':dict(Counter(r['verification_reason'] for r in review)),
        'reconciled':len(checked)==len(verified)+len(review)+len(errors),
        'email_sent':False,'sent_history_modified':False,
        'caveat':'Verified means independently matching publisher metadata or official listing, not a full-text or full-catalog audit'}
    (args.output/'verification_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('R6_SOURCE_AUDIT '+json.dumps(report,ensure_ascii=False),flush=True)
    if not verified:raise SystemExit('No independently verified candidates; fail closed.')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--state',type=Path,default=ROOT/'data/ccf_candidate_state.json')
    p.add_argument('--whitelist',type=Path,default=ROOT/'config/ccf_a_venues.yaml')
    p.add_argument('--journals',type=Path,default=ROOT/'config/journal_source_map.yaml')
    p.add_argument('--conf25',type=Path,default=ROOT/'config/conference_source_map.yaml')
    p.add_argument('--conf26',type=Path,default=ROOT/'config/ccf_incremental_2026.yaml')
    p.add_argument('--output',type=Path,default=ROOT/'ccf-r6-audit')
    p.add_argument('--per-venue',type=int,default=5)
    run(p.parse_args())
if __name__=='__main__':main()
