"""R4-2: audited CCF formal-source discovery with persistent candidate state.

NO EMAIL. NO PREPRINT SEARCH. NO SENT-HISTORY WRITES.
This module intentionally preserves PRELIMINARY rather than claiming publisher
verification for every record. All 16 sources are audited on each test run.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

import yaml

# Reuse existing R3 validators; do not create a second source-quality algorithm.
import ccf_conference_quality as conference_quality
import ccf_journal_quality as journal_quality
from collect_ccf_conferences import fetch_text
from collect_ccf_journals import get_json

ROOT = Path(__file__).resolve().parents[1]
MAX_PER_PAGE = 100
MAX_PAGES = 4
CONF_ELIGIBLE = {'CROSSREF_META_MATCH', 'SPRINGER_BOOK_MATCH', 'OFFICIAL_LISTED'}
JOURNAL_ELIGIBLE = {'PASS_METADATA_RULES'}
STATE_VERSION = 1
EXPORT_FIELDS = ['paper_key','venue','field','year','publication_date','date_precision',
                 'title','doi','paper_url','pdf_url','source_type','source_record_id',
                 'source_status','candidate_status','reason','evidence_url','source_file']


def paper_key(row):
    doi = str(row.get('doi') or '').lower().strip().removeprefix('https://doi.org/')
    if doi:
        return 'doi:' + doi
    url = str(row.get('paper_url') or '').strip().rstrip('/')
    return 'url:' + url if url.startswith('https://') else ''


def validate_config(whitelist, journals, conferences, year):
    whitelist_names = set(whitelist['venues'])
    journal_names = {k for k,v in whitelist['venues'].items() if v['kind'] == 'journal'}
    conference_names = {k for k,v in whitelist['venues'].items() if v['kind'] == 'conference'}
    if (len(whitelist_names) != 16 or len(journal_names) != 6 or
        len(conference_names) != 10 or set(journals['journals']) != journal_names or
        set(conferences['venues']) != conference_names or conferences['year'] != year):
        raise ValueError('16-venue whitelist/source-map mismatch or conference year not mapped')
    for venue, setting in conferences['venues'].items():
        if setting['field'] != whitelist['venues'][venue]['field']:
            raise ValueError(f'{venue}: field mismatch')
        if setting['provider'] == 'crossref' and venue in ('CRYPTO','EUROCRYPT'):
            if not setting.get('verified_book_dois'):
                raise ValueError(f'{venue}: verified Springer volume DOI whitelist missing')


def empty_state():
    return {'schema_version':STATE_VERSION, 'papers':{}, 'last_successful_check':'',
            'coverage':{'source_status':'BOUNDED_PRELIMINARY_NOT_COMPLETE_BACKFILL'}}


def load_state(path):
    if not path.is_file():
        return empty_state()
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('schema_version') != STATE_VERSION or not isinstance(state.get('papers'), dict):
        raise ValueError('State schema unknown: manual migration required')
    return state


def validate_sent_history(path):
    if not path.is_file():
        raise FileNotFoundError('Persistent sent-history registry is missing')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('sent_keys'),list):
        raise ValueError('Sent-history registry invalid')
    if len(set(data['sent_keys'])) != len(data['sent_keys']):
        raise ValueError('Duplicate sent-history keys')
    return set(data['sent_keys'])


def normalize_seed(row):
    if row.get('candidate_status') != 'PRELIMINARY':
        return None
    item = {key:str(row.get(key) or '') for key in EXPORT_FIELDS}
    item['paper_key'] = paper_key(item)
    if not item['paper_key'] or not item['venue'] or not item['title']:
        return None
    return item


def seed_from_snapshot(state, snapshot, today):
    if state['papers'] or not snapshot or not snapshot.is_file():
        return 0
    count=0
    with snapshot.open(encoding='utf-8-sig', newline='') as fh:
        for r in csv.DictReader(fh):
            item=normalize_seed(r)
            if item and item['paper_key'] not in state['papers']:
                item['first_seen'] = today.isoformat()
                item['last_seen'] = today.isoformat()
                state['papers'][item['paper_key']] = item
                count += 1
    return count


def journal_record(r, venue, field):
    doi=r['doi']; link='https://doi.org/'+doi if doi else str(r.get('openalex_id') or '')
    item={
        'venue':venue,'field':field,'year':str(r['year'] or ''),
        'publication_date':str(r['date'] or ''),'date_precision':'day',
        'title':r['title'],'doi':doi,'paper_url':link,'pdf_url':'',
        'source_type':'OpenAlex journal','source_record_id':r['openalex_id'],
        'source_status':r['status'],'candidate_status':'PRELIMINARY',
        'reason':r['reason'],'evidence_url':r['openalex_id'],
        'source_file':'incremental/2026-journal',
    }
    item['paper_key']=paper_key(item)
    return item


def conference_record(r, venue, field, year):
    doi=r['doi']; link='https://doi.org/'+doi if doi else r['paper_url']
    item={
        'venue':venue,'field':field,'year':str(year),'publication_date':'',
        'date_precision':'year','title':r['title'],'doi':doi,
        'paper_url':link,'pdf_url':'','source_type':r['source'],
        'source_record_id':r['paper_url'],'source_status':r['status'],
        'candidate_status':'PRELIMINARY','reason':r['reason'],
        'evidence_url':r['official_evidence_url'],
        'source_file':f'incremental/{year}-conference',
    }
    item['paper_key']=paper_key(item)
    return item


def crossref_pages(venue, setting, year, as_of, last_check, page_cap=MAX_PAGES):
    """Search current-year records. Index-date overlap after first successful run.

    The query is bounded and reports pagination truncation, never completeness.
    """
    if last_check:
        since=max(date(year,1,1),date.fromisoformat(last_check)-timedelta(days=45))
        filter_value=f'from-index-date:{since},until-index-date:{as_of}'
    else:
        filter_value=f'from-pub-date:{year}-01-01,until-pub-date:{as_of}'
    items=[]; total=None
    for index in range(page_cap):
        params={'query.container-title':setting['query'],'filter':filter_value,
                'rows':MAX_PER_PAGE,'offset':index*MAX_PER_PAGE}
        data=json.loads(fetch_text('https://api.crossref.org/works?'+urlencode(params)))
        if data.get('status')!='ok': raise RuntimeError('Crossref returned non-OK status')
        message=data.get('message') or {}
        chunk=message.get('items') or []
        if total is None: total=int(message.get('total-results') or 0)
        items.extend(chunk)
        if len(chunk)<MAX_PER_PAGE or len(items)>=total: break
        time.sleep(0.12)
    return items, bool(total is not None and total>len(items)), total or 0


def journal_source(venue, info, as_of, key, window_days, page_cap=MAX_PAGES):
    status={'venue':venue,'kind':'journal','status':'CHECKED', 'sources':[]}
    papers=[]; review_count=0
    start=max(date(as_of.year,1,1),as_of-timedelta(days=window_days))
    for mapped in info['sources']:
        if not mapped['from_year']<=as_of.year<=mapped['to_year']:
            continue
        source=get_json('/sources/'+mapped['id'],{},key)
        validation=journal_quality.validate_source(source,mapped)
        entry={'source_id':mapped['id'],'validation':validation}
        if validation!='SOURCE_ID_TITLE_ISSN_MATCH':
            status['status']='SOURCE_IDENTITY_REVIEW'
            status['sources'].append(entry)
            continue
        allworks=[]; truncated=False
        for i in range(page_cap):
            params={'filter':f'primary_location.source.id:{mapped["id"]},from_publication_date:{start},to_publication_date:{as_of}',
                'per_page':MAX_PER_PAGE,'sort':'publication_date:desc',
                'select':'id,title,doi,publication_year,publication_date,primary_location,type',
                'page':i+1}
            response=get_json('/works',params,key)
            block=response.get('results') or []
            allworks.extend(block)
            if len(block)<MAX_PER_PAGE:break
            if i==page_cap-1:truncated=True
        entry.update(retrieved=len(allworks),truncated=truncated)
        for paper in allworks:
            result=journal_quality.classify(paper,venue,info['field'],mapped,as_of.isoformat())
            if result['status'] in JOURNAL_ELIGIBLE:
                item=journal_record(result,venue,info['field'])
                if item['paper_key']: papers.append(item)
            else:review_count+=1
        status['sources'].append(entry)
        if truncated:status['status']='BOUNDED_PAGINATION'
    if not status['sources'] and status['status']=='CHECKED': status['status']='YEAR_NOT_MAPPED'
    status.update(accepted=len(papers),reviewed=review_count)
    return papers,status


def conference_source(venue,setting,year,as_of,last_check,page_cap=MAX_PAGES):
    status={'venue':venue,'kind':'conference','provider':setting['provider'],
            'official_url':setting['official_url'],'status':'CHECKED'}
    if setting['provider']=='official':
        html=fetch_text(setting['official_url'],accept='text/html')
        if len(html)<500 or ('not a bot' in html.lower() and len(html)<40000):
            raise RuntimeError(f'Official page challenge or unexpectedly empty HTML: {venue}')
        original=conference_quality.parse_official_listing(html,venue,setting,year)
        status.update(retrieved=len(original),truncated=False)
    else:
        raw,truncated,total=crossref_pages(venue,setting,year,as_of,last_check,page_cap)
        original=[conference_quality.check_crossref(r,venue,setting,year) for r in raw]
        status.update(retrieved=len(raw),truncated=truncated,provider_total=total)
    accepted=[]
    review=0
    for r in original:
        if r['status'] in CONF_ELIGIBLE:
            item=conference_record(r,venue,setting['field'],year)
            if item['paper_key']:accepted.append(item)
        else:review+=1
    status.update(accepted=len(accepted),reviewed=review)
    if status.get('truncated'):
        status['status']='BOUNDED_PAGINATION'
    elif not accepted:
        status['status']='NEEDS_REVIEW_NO_MATCH'
    return accepted,status


def merge(state, incoming, today, sent_keys):
    """Idempotent upsert preserving sent history and original first-seen date."""
    new=0; updated=0; duplicates=0
    seen_this_run=set()
    for raw in incoming:
        row=dict(raw)
        key=paper_key(row)
        if not key or row.get('candidate_status')!='PRELIMINARY':continue
        if key in seen_this_run:
            duplicates+=1;continue
        seen_this_run.add(key)
        row['paper_key']=key
        old=state['papers'].get(key)
        row['first_seen']=(old or {}).get('first_seen') or today.isoformat()
        row['last_seen']=today.isoformat()
        if old:
            # Keep existing nonempty fields; do not overwrite verified details
            # with a thinner fresh index entry.
            for k,v in old.items():
                if k not in ('last_seen','source_file') and (k not in row or row[k] in ('',None)):
                    row[k]=v
            updated+=1
        else:
            new+=1
        state['papers'][key]=row
    return {'new':new,'previously_known':updated,'duplicate_scan_results':duplicates,
            'total_unique_candidates':len(state['papers']),
            'unsent_candidates':sum(k not in sent_keys for k in state['papers'])}


def write_csv(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=EXPORT_FIELDS,extrasaction='ignore')
        w.writeheader();w.writerows(rows)


def run(state_path, history_path, seed_path, whitelist_path, journal_path,
        conference_path, output_dir, as_of, journal_lookback=60, crossref_page_cap=MAX_PAGES):
    whitelist=yaml.safe_load(whitelist_path.read_text(encoding='utf-8'))
    journals=yaml.safe_load(journal_path.read_text(encoding='utf-8'))
    conf=yaml.safe_load(conference_path.read_text(encoding='utf-8'))
    validate_config(whitelist,journals,conf,as_of.year)
    sent_keys=validate_sent_history(history_path)
    state=load_state(state_path)
    baseline_count=seed_from_snapshot(state,seed_path,as_of)
    output_dir.mkdir(parents=True,exist_ok=True)
    api_key=os.getenv('OPENALEX_API_KEY','').strip()
    incoming=[]; audit=[]; errors=[]
    for venue, setting in journals['journals'].items():
        if not api_key:
            source={'venue':venue,'kind':'journal','status':'API_ERROR','error':'OPENALEX_API_KEY missing'}
            papers=[]
        else:
            try:
                papers,source=journal_source(venue,setting,as_of,api_key,journal_lookback)
            except Exception as exc:
                source={'venue':venue,'kind':'journal','status':'API_ERROR','error':type(exc).__name__+': '+str(exc)}
                papers=[]
        incoming.extend(papers);audit.append(source)
        if source['status'] in ('API_ERROR','SOURCE_IDENTITY_REVIEW','YEAR_NOT_MAPPED'):
            errors.append(venue)
        print('JOURNAL',venue,source['status'],'accepted',len(papers),flush=True)
        time.sleep(0.18)
    for venue,setting in conf['venues'].items():
        try:
            papers,source=conference_source(venue,setting,conf['year'],as_of,
                    state.get('last_successful_check',''),crossref_page_cap)
        except Exception as exc:
            source={'venue':venue,'kind':'conference','status':'API_ERROR','error':type(exc).__name__+': '+str(exc)}
            papers=[]
        incoming.extend(papers);audit.append(source)
        if source['status']=='API_ERROR':errors.append(venue)
        print('CONFERENCE',venue,source['status'],'accepted',len(papers),flush=True)
        time.sleep(0.18)
    assert len(audit)==16
    report={'stage':'R4-2','as_of':as_of.isoformat(), 'coverage':'BOUNDED_INCREMENTAL_NOT_COMPLETE_BACKFILL',
            'source_status_counts':dict(Counter(a['status'] for a in audit)),
            'source_audit':audit,'errors':errors,'seeded_preliminary':baseline_count,
            'incoming_accepted':len(incoming),'sent_history_count':len(sent_keys),
            'email_sent':False,'preview_only':True,
            'caveats':['Only publisher-metadata/official-listing candidates, not fully paper-verified',
                       'Crossref and OpenAlex queries are bounded and can miss late backfilled papers',
                       '2026 conference source map must be updated for a new conference year',
                       'Sent history is read-only; preview is never considered delivered']}
    if not errors:
        merged=merge(state,incoming,as_of,sent_keys)
        state['last_successful_check']=as_of.isoformat()
        state['coverage']={'mode':'bounded 2026 discovery; 2025 historical seed if available',
                           'source_status_counts':report['source_status_counts']}
        report['merge']=merged
        # Do not write durable state on a partial API failure.
        state_path.parent.mkdir(parents=True,exist_ok=True)
        state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        newest=sorted((p for k,p in state['papers'].items() if k not in sent_keys),
                      key=lambda x:(x.get('year',''),x.get('venue',''),x.get('title','')),reverse=True)
        write_csv(output_dir/'unsent_candidates.csv',newest)
    (output_dir/'source_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('SUMMARY',json.dumps({k:v for k,v in report.items() if k!='source_audit'},ensure_ascii=False),flush=True)
    if errors:
        raise SystemExit('Fail closed: API/source verification failures; durable state not updated: '+', '.join(errors))
    return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--state',type=Path,default=ROOT/'data/ccf_candidate_state.json')
    p.add_argument('--history',type=Path,default=ROOT/'data/ccf_sent_history.json')
    p.add_argument('--seed',type=Path)
    p.add_argument('--whitelist',type=Path,default=ROOT/'config/ccf_a_venues.yaml')
    p.add_argument('--journals',type=Path,default=ROOT/'config/journal_source_map.yaml')
    p.add_argument('--conferences',type=Path,default=ROOT/'config/ccf_incremental_2026.yaml')
    p.add_argument('--output',type=Path,default=ROOT/'ccf-r42-preview')
    p.add_argument('--as-of',type=date.fromisoformat,default=date.today())
    p.add_argument('--lookback',type=int,default=60)
    p.add_argument('--crossref-pages',type=int,default=4)
    a=p.parse_args()
    if not 7<=a.lookback<=120 or not 1<=a.crossref_pages<=10:
        raise SystemExit('Unsafe lookback or page cap')
    run(a.state,a.history,a.seed,a.whitelist,a.journals,a.conferences,
        a.output,a.as_of,a.lookback,a.crossref_pages)

if __name__=='__main__':main()
