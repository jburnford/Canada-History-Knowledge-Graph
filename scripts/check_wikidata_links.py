#!/usr/bin/env python3
"""Reconcile every published Wikidata association with its public unit page."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path

from _config import CONFIG, REPO_ROOT
from _site_urls import page_file
from build_rdf_site import Builder, wikidata_html, sha


def read(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--site', type=Path, default=REPO_ROOT / 'data_quality/rdf_site')
    args = ap.parse_args()
    root = REPO_ROOT / 'data_quality'
    identity = root / 'lod_identity'
    b = Builder(args.site, root / 'lod_census_sources', identity, root / 'lod_source_bindings', CONFIG.hgiscanada_repo)
    for rel, digest in json.loads((identity / 'manifest.json').read_text())['source_sha256'].items():
        if sha(REPO_ROOT / rel) != digest:
            raise ValueError(f'Changed assessment input: {rel}')
    associations = read(identity / 'wikidata_associations.csv')
    expected_review = []
    counts = Counter()
    by_unit = defaultdict(list)
    for r in associations:
        by_unit[r['unit_id']].append(r)
        accepted = r['mapping_status'].startswith('accepted_')
        if accepted != (r['link_accepted'] == 'True') or r['identity_asserted'] != 'False':
            raise ValueError(f'Inconsistent acceptance/identity: {r["unit_id"]}')
        if r['mapping_status'] == 'review_specific_conflict':
            if not json.loads(r['review_reasons_json']):
                raise ValueError('Review flag without a specific reason')
            expected_review.append(r)
        elif accepted and json.loads(r['review_reasons_json']):
            raise ValueError('Accepted link with unresolved review reasons')
        counts[r['mapping_status']] += 1
    if read(identity / 'wikidata_review_queue.csv') != expected_review:
        raise ValueError('Review queue differs from full assessment')
    for uid, path in b.unit_urls.items():
        records = by_unit[uid]
        text = page_file(args.site, path).read_text()
        expected = wikidata_html(records)
        if expected and expected not in text:
            raise ValueError(f'Public Wikidata presentation differs: {path}')
        if 'External referent candidates' in text or 'candidate_association_referent_review' in text:
            raise ValueError(f'Obsolete blanket candidate presentation: {path}')
    result = dict(unit_pages=len(b.unit_urls), associations=len(associations), statuses=dict(counts), errors=[])
    (root / 'wikidata_site_validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
