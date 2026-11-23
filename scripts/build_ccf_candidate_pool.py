"""R3-4a: consolidate *bounded previews* (not a complete 3-year harvest).

Purely offline: two R3-2/R3-3 artifacts in, provenance-preserving candidate,
review, excluded and duplicate reports out. No network, secrets or emailing.
"""
import argparse
import csv
import hashlib
from html import unescape
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import yaml

JOURNAL_FILES = {
    'journal_papers_preview.csv', 'journal_accepted_overflow.csv',
    'journal_review.csv', 'journal_excluded.csv',
}
CONFERENCE_FILES = {
    'conference_papers_preview.csv', 'conference_accepted_overflow.csv',
    'conference_review.csv', 'conference_excluded.csv',
}
ELIGIBLE = {'PASS_METADATA_RULES', 'CROSSREF_META_MATCH', 'SPRINGER_BOOK_MATCH', 'OFFICIAL_LISTED'}
REVIEW = {'REVIEW'}
EXCLUDED = {'REJECT', 'EXCLUDED_DUPLICATE'}
DOI_RX = re.compile(r'^10\.\d{4,9}/\S+$', re.I)
COLUMNS = [
    'paper_key', 'venue', 'field', 'year', 'publication_date', 'date_precision',
    'title', 'doi', 'paper_url', 'pdf_url', 'source_type', 'source_record_id',
    'source_status', 'candidate_status', 'reason', 'evidence_url', 'source_file',
]


def norm_doi(value):
    v = str(value or '').strip().lower()
    v = re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', '', v)
    return v if DOI_RX.fullmatch(v) else ''


def norm_title(value):
    v = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return ''.join(ch for ch in v if ch.isalnum())


def canonical_url(raw):
    p = urlsplit(str(raw or '').strip())
    if p.scheme not in {'https', 'http'} or not p.hostname:
        return ''
    if p.hostname.lower() in {'doi.org', 'dx.doi.org'}:
        d = norm_doi(p.path.lstrip('/'))
        return 'https://doi.org/' + d if d else ''
    return urlunsplit(('https', p.netloc.lower(), p.path.rstrip('/') or '/', '', ''))


def read_rows(directory, names):
    entries = []
    for name in sorted(names):
        path = directory / name
        if not path.is_file():
            raise FileNotFoundError(f'Required source artifact missing: {path}')
        with path.open(encoding='utf-8-sig', newline='') as fh:
            rows = list(csv.DictReader(fh))
        entries.extend((name, row) for row in rows)
    return entries


def map_record(row, origin, filename, whitelist, as_of):
    venue = str(row.get('venue') or '').strip()
    expected = whitelist.get(venue)
    status = str(row.get('status') or '').strip()
    reasons = []
    if not expected:
        reasons.append('NOT_IN_CCF_SOURCE_WHITELIST')
        field = str(row.get('field') or '')
    else:
        field = expected['field']
        if expected['kind'] != ('journal' if origin == 'journals' else 'conference'):
            reasons.append('VENUE_KIND_MISMATCH')
        # Journal artifact includes `field`; the conference artifact does not.
        # A nonempty field must agree; an absent field inherits the whitelist.
        if row.get('field') and row.get('field') != field:
            reasons.append('VENUE_FIELD_MISMATCH')
    if status not in (ELIGIBLE | REVIEW | EXCLUDED):
        reasons.append('UNRECOGNIZED_SOURCE_STATUS')

    # Crossref often embeds JATS tags such as <scp> in titles.
    title = ' '.join(unescape(re.sub(r'</?[^>]+>', '', str(row.get('title') or ''))).split())
    # Official paper pages occasionally use short legitimate titles (e.g. Move2EVM).
    min_length = 8 if status == 'OFFICIAL_LISTED' else 14
    if len(norm_title(title)) < min_length:
        reasons.append('INVALID_OR_MISSING_TITLE')
    try:
        year = int(row.get('year') or 0)
    except (ValueError, TypeError):
        year = 0
    if year not in {2024, 2025, 2026} or year > as_of.year:
        reasons.append('YEAR_OUTSIDE_TARGET_WINDOW')
    date_value = str(row.get('date') or '').strip() if origin == 'journals' else ''
    precision = 'day' if date_value else 'year'
    if date_value:
        try:
            if date.fromisoformat(date_value) > as_of or date_value[:4] != str(year):
                reasons.append('PUBLICATION_DATE_INCONSISTENT_OR_FUTURE')
        except ValueError:
            reasons.append('INVALID_PUBLICATION_DATE')
    doi = norm_doi(row.get('doi'))
    if row.get('doi') and not doi:
        reasons.append('INVALID_DOI')
    url = canonical_url(row.get('paper_url') if origin == 'conferences' else '')
    if doi:
        url = 'https://doi.org/' + doi
    if not url:
        url = canonical_url(row.get('openalex_id') if origin == 'journals' else '')
    if not url:
        reasons.append('MISSING_PAPER_LINK')
    evidence = canonical_url(row.get('official_evidence_url') if origin == 'conferences' else row.get('openalex_id'))
    if not evidence:
        reasons.append('MISSING_PROVENANCE_URL')
    if origin == 'journals' and not doi:
        reasons.append('NO_JOURNAL_DOI')

    uid = 'doi:' + doi if doi else ('url:' + url if url else 'title:' + hashlib.sha256(f'{venue}:{year}:{norm_title(title)}'.encode()).hexdigest()[:20])
    if reasons or status in EXCLUDED:
        candidate_status = 'EXCLUDED'
    elif status in REVIEW:
        candidate_status = 'REVIEW'
    else:
        candidate_status = 'PRELIMINARY'
    why = ';'.join(filter(None, (row.get('reason') or '', *reasons)))
    return {
        'paper_key': uid, 'venue': venue, 'field': field,
        'year': year, 'publication_date': date_value,
        'date_precision': precision, 'title': title, 'doi': doi, 'paper_url': url,
        'pdf_url': '',  # Not present in these auditable input artifacts.
        'source_type': ('OpenAlex journal' if origin == 'journals' else row.get('source') or 'Crossref conference'),
        'source_record_id': (row.get('openalex_id') or row.get('paper_url') or ''),
        'source_status': status, 'candidate_status': candidate_status,
        'reason': why, 'evidence_url': evidence, 'source_file': f'{origin}/{filename}',
    }


def rank(row):
    return (0 if row['candidate_status'] == 'PRELIMINARY' else 1 if row['candidate_status'] == 'REVIEW' else 2,
            0 if row['source_status'] == 'OFFICIAL_LISTED' else 1,
            -len(row['doi']), row['venue'], row['title'], row['paper_url'])


def combine(rows):
    """Stable exact-DOI or no-DOI exact-venue/year/title dedup; retain audit trail."""
    uniq = []
    duplicates = []
    seen = {}
    for record in sorted(rows, key=rank):
        row = dict(record)
        key = row['paper_key']
        if row['doi']:
            dedup_key = 'doi:' + row['doi']
        else:
            dedup_key = f"nodoi:{row['venue']}:{row['year']}:{norm_title(row['title'])}"
        if dedup_key in seen:
            row['candidate_status'] = 'DUPLICATE'
            row['reason'] = ';'.join(x for x in [row['reason'], 'DUPLICATE_OF:' + seen[dedup_key]] if x)
            duplicates.append(row)
        else:
            seen[dedup_key] = key
            uniq.append(row)
    # Same title/year with different DOIs is possible versioning, not safe to auto-merge.
    by_title = defaultdict(set)
    for row in uniq:
        by_title[(row['year'], norm_title(row['title']))].add(row['paper_key'])
    for row in uniq:
        if len(by_title[(row['year'], norm_title(row['title']))]) > 1 and row['candidate_status'] == 'PRELIMINARY':
            row['candidate_status'] = 'REVIEW'
            row['reason'] = ';'.join(x for x in [row['reason'], 'SAME_TITLE_YEAR_DIFFERENT_IDENTIFIER'] if x)
    return uniq, duplicates


def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def build(journal_dir, conference_dir, whitelist_path, output_dir, as_of):
    venues = yaml.safe_load(whitelist_path.read_text(encoding='utf-8'))['venues']
    if len(venues) != 16 or sum(v['kind'] == 'journal' for v in venues.values()) != 6:
        raise ValueError('Unexpected CCF source whitelist; expected 6 journals + 10 conferences')
    inputs = ([(name, row, 'journals') for name, row in read_rows(journal_dir, JOURNAL_FILES)] +
              [(name, row, 'conferences') for name, row in read_rows(conference_dir, CONFERENCE_FILES)])
    mapped = [map_record(row, origin, name, venues, as_of) for name, row, origin in inputs]
    uniq, dupes = combine(mapped)
    selected = sorted((r for r in uniq if r['candidate_status'] == 'PRELIMINARY'),
                      key=lambda r: (-r['year'], r['field'], r['venue'], r['title']))
    review = [r for r in uniq if r['candidate_status'] == 'REVIEW']
    excluded = [r for r in uniq if r['candidate_status'] == 'EXCLUDED']
    assert sum(map(len, [selected, review, excluded, dupes])) == len(inputs)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / 'candidates_preliminary.csv', selected)
    write_csv(output_dir / 'candidates_review.csv', review)
    write_csv(output_dir / 'candidates_excluded.csv', excluded)
    write_csv(output_dir / 'candidates_duplicates.csv', dupes)
    with (output_dir / 'candidates_preliminary.jsonl').open('w', encoding='utf-8') as fh:
        for row in selected:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
    source_counts = Counter(r['venue'] for r in selected)
    summary = {
        'stage': 'R3-4a', 'as_of': as_of.isoformat(), 'scope': 'BOUNDED_PREVIEWS_NOT_COMPLETE_3_YEAR_BACKFILL',
        'venue_whitelist_size': len(venues),
        'input_records': len(inputs), 'preliminary': len(selected),
        'review': len(review), 'excluded': len(excluded), 'duplicates': len(dupes),
        'counts_reconciled': len(inputs) == sum(map(len, [selected, review, excluded, dupes])),
        'preliminary_by_venue': dict(sorted(source_counts.items())),
        'coverage': {
            'journals': '2024-2026 bounded to latest <=30 works per OpenAlex source; NOT exhaustive',
            'conferences': '2025 only; Crossref search first 40 results per venue or official 2025 listing; NOT exhaustive',
            'conference_2024_2026': 'NOT_COLLECTED',
            'date_precision': 'journal day if supplied; conference year only',
        },
        'constraints': [
            'PRELIMINARY means metadata matched; NOT publisher-by-publisher CCF paper verification',
            'no guaranteed abstracts, authors or PDF links in source artifacts',
            'no persistent sent history; no daily email',
            'GitHub Actions artifacts expire; this output is not a durable backfill database',
        ],
    }
    (output_dir / 'coverage_audit.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--journals', type=Path, required=True)
    ap.add_argument('--conferences', type=Path, required=True)
    ap.add_argument('--whitelist', type=Path, default=Path('config/ccf_a_venues.yaml'))
    ap.add_argument('--output', type=Path, default=Path('ccf-unified-preview'))
    ap.add_argument('--as-of', type=date.fromisoformat, default=date.today())
    args = ap.parse_args()
    print(json.dumps(build(args.journals, args.conferences, args.whitelist, args.output, args.as_of), ensure_ascii=False, indent=2))
