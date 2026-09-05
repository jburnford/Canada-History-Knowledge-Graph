#!/usr/bin/env python3
"""Independently reconcile every retrieval cell and HTML row against RDF inputs.

RDF validation stream-parses the complete published RDF and checks cube/CRM
assertions against SQLite. HTML/retrieval checks independently inspect rendered
values, definitions, periods, source subjects, and exact citation anchors.
"""
import argparse
from collections import Counter
from decimal import Decimal
import gzip
import hashlib
from html.parser import HTMLParser
import itertools
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote, urlsplit

from _config import REPO_ROOT
from _site_urls import BASE, ORIGIN, page_file, sitemap_paths
from validate_reporting_rdf import validate as validate_rdf

RDF_BASE = 'http://temp.lincsproject.ca/census/'

if not __debug__:
    raise RuntimeError('Run this validator without Python optimization; reconciliation checks must be enabled')


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def uri(identifier):
    return RDF_BASE + quote(identifier, safe='/_-.')


class SourceTable(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.cells, self.current, self.visible, self.links = {}, None, [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'tr' and 'data-cell' in a:
            if a['data-cell'] in self.cells:
                raise ValueError('Duplicate HTML cell')
            self.current = a['data-cell']
            self.cells[self.current] = dict(attributes=a, text=[])
        if tag in {'a', 'link', 'script', 'img'}:
            href = a.get('href') or a.get('src')
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag == 'tr':
            self.current = None

    def handle_data(self, text):
        if self.current:
            self.cells[self.current]['text'].append(text)
        self.visible.append(text)


def check_source(site, sources, entry):
    key = entry['source_key']
    folder = site / 'sources' / key
    database = sources / key / 'source_observations.sqlite'
    assert digest(database) == entry['database_sha256'], (key, 'database drift')
    assert digest(folder / 'source.nt.gz') == entry['rdf_sha256'], (key, 'RDF drift')
    assert digest(sources / key / 'source_observations.nt.gz') == entry['rdf_sha256'], (key, 'current staged RDF differs')
    assert digest(folder / 'cells.jsonl.gz') == entry['retrieval_sha256'], (key, 'retrieval drift')
    db = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    src = dict(db.execute('SELECT * FROM source').fetchone())
    units = {r['unit_id']: dict(r) for r in db.execute('SELECT * FROM reporting_units')}
    cols = {r['column_key']: dict(r) for r in db.execute('SELECT * FROM source_columns')}
    count, numeric, page_count = 0, 0, 0
    status = Counter()
    seen_units = set()
    with gzip.open(folder / 'cells.jsonl.gz', 'rt') as stream:
        records = (json.loads(line) for line in stream)
        expected = db.execute('SELECT o.* FROM observations o JOIN source_columns c USING(column_key) ORDER BY o.unit_id, c.column_index')
        actual_rows = itertools.groupby(records, lambda c: c['unit_id'])
        expected_rows = itertools.groupby(expected, lambda c: c['unit_id'])
        for actual_group, expected_group in itertools.zip_longest(actual_rows, expected_rows):
            assert actual_group and expected_group, (key, 'different row count')
            uid, actual = actual_group
            expected_uid, staged = expected_group
            assert uid == expected_uid, (key, 'different row identity')
            seen_units.add(uid)
            u = units[uid]
            path = f'{BASE}/sources/{quote(key, safe="_-.")}/rows/{u["excel_row"]}/'
            text = page_file(site, path).read_text()
            page = SourceTable(text)
            visible = ' '.join(page.visible)
            ids = set()
            for fact, raw in itertools.zip_longest(actual, staged):
                assert fact is not None and raw is not None, (key, uid, 'different cell count')
                for field, value in dict(raw).items():
                    assert fact[field] == value, (key, raw['source_cell'], field)
                col = cols[raw['column_key']]
                extra = dict(source_key=key, workbook=Path(src['path']).name,
                    workbook_sha256=src['sha256'], worksheet=src['sheet'], definition=col['definition'],
                    definition_evidence=json.loads(col['definition_source_json']), column_role=col['column_role'],
                    reporting_label=u['label'], province=u['province'], reporting_level=u['reporting_level'], source_code=u['source_code'],
                    source_reporting_unit=uri('source-reporting-unit/' + uid),
                    rdf_id=uri('source-cell/' + src['sha256'] + '/' + raw['observation_id']),
                    variable_iri=uri('source-variable/' + key + '/' + raw['column_key']),
                    reference_period_iri=uri('reference-period/' + key + '/' + raw['column_key']),
                    source_document=uri('source-table/' + key + '/' + src['sha256']),
                    citation_url=ORIGIN + path + '#cell-' + raw['column_key'],
                    rdf_decimal=format(Decimal(raw['numeric_value']), 'f') if raw['value_status'] == 'numeric' else None)
                for field, value in extra.items():
                    assert fact[field] == value, (key, raw['source_cell'], field)
                rendered = page.cells[raw['observation_id']]
                a, cell_text = rendered['attributes'], ' '.join(rendered['text'])
                assert a['id'] == urlsplit(fact['citation_url']).fragment
                for name, value in [('data-status', raw['value_status']), ('data-value', extra['rdf_decimal'] or ''),
                                    ('data-year', raw['reference_year'] if raw['reference_year'] is not None else ''), ('data-unit', raw['unit'] or '')]:
                    assert a[name] == str(value), (key, raw['source_cell'], name)
                for value in [raw['source_cell'], raw['source_column'], col['definition'], raw['unit_status'], raw['reference_period_kind'], raw['reference_period_text']]:
                    assert str(value) in cell_text, (key, raw['source_cell'], 'visible text', value)
                if raw['value_status'] == 'numeric':
                    assert extra['rdf_decimal'] in cell_text
                    numeric += 1
                elif raw['value_status'] == 'source_blank':
                    assert 'Blank in source' in cell_text
                else:
                    assert str(json.loads(raw['raw_value_json'])) in cell_text
                if raw['reference_year'] is None:
                    assert 'Reference year unresolved' in cell_text
                if not raw['unit']:
                    assert 'Unit unresolved' in cell_text
                ids.add(raw['observation_id']); count += 1; status[raw['value_status']] += 1
            assert ids == set(page.cells), (key, uid, 'HTML cell set differs')
            for value in [u['label'], u['reporting_level'], str(src['census_vintage']), src['sha256'], uri('source-reporting-unit/' + uid)]:
                assert value in visible, (key, uid, 'missing visible context', value)
            page_count += 1
    assert seen_units == set(units), (key, 'missing reporting unit')
    assert (count, numeric, page_count) == (entry['source_cells'], entry['numeric_observations'], entry['reporting_rows'])
    db.close()
    return dict(source_key=key, cells=count, numeric_observations=numeric, reporting_rows=page_count, statuses=dict(status))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--site', type=Path, default=REPO_ROOT / 'data_quality/rdf_site')
    ap.add_argument('--sources', type=Path, default=REPO_ROOT / 'data_quality/lod_census_sources')
    ap.add_argument('--report', type=Path, default=REPO_ROOT / 'data_quality/rdf_site_validation.json')
    ap.add_argument('--rdf-only', action='store_true')
    ap.add_argument('--html-only', action='store_true')
    ap.add_argument('--rdf-cache', type=Path, help='Reuse complete RDF validation only for identical RDF/database/parser hashes')
    ap.add_argument('--shard', help='RDF-only independent partition, for example 0/4')
    args = ap.parse_args()
    if args.rdf_only and args.html_only:
        ap.error('Choose at most one validation partition')
    manifest_path = args.site / 'data/build-manifest.json'
    if args.rdf_only and not manifest_path.exists():
        catalog = json.loads((args.sources / 'rdf-catalog.json').read_text())
        manifest = dict(sources=[dict(source_key=e['source'], database_sha256=e['export']['database_sha256'],
            rdf_sha256=digest(args.site / 'sources' / e['source'] / 'source.nt.gz')) for e in catalog['sources']])
    else:
        manifest = json.loads(manifest_path.read_text())
    if args.shard:
        if not args.rdf_only:
            ap.error('--shard requires --rdf-only; HTML checks always cover the complete site')
        part, total = map(int, args.shard.split('/'))
        if not 0 <= part < total:
            ap.error('Invalid shard number')
        manifest['sources'] = [s for i, s in enumerate(manifest['sources']) if i % total == part]
    parser_sha256 = digest(REPO_ROOT / 'scripts/validate_reporting_rdf.py')
    cached = {}
    if args.rdf_cache and args.rdf_cache.exists():
        prior = json.loads(args.rdf_cache.read_text())
        if not prior['errors'] and prior.get('parser_sha256') == parser_sha256:
            cached = {s['source_key']: s for s in prior['sources'] if 'rdf' in s and not s['rdf']['errors']}
    result = dict(scope='RDF only' if args.rdf_only else 'HTML and retrieval only' if args.html_only else 'Complete RDF, HTML and retrieval reconciliation', parser_sha256=parser_sha256, sources=[], errors=[])
    try:
        for entry in manifest['sources']:
            key = entry['source_key']
            item = dict(source_key=key, rdf_sha256=entry['rdf_sha256'], database_sha256=entry['database_sha256'])
            if not args.rdf_only:
                item.update(check_source(args.site, args.sources, entry))
            if not args.html_only:
                rdf = args.site / 'sources' / key / 'source.nt.gz'
                assert digest(rdf) == entry['rdf_sha256'], (key, 'published RDF checksum')
                assert digest(args.sources / key / 'source_observations.nt.gz') == entry['rdf_sha256'], (key, 'current staged RDF checksum')
                database = args.sources / key / 'source_observations.sqlite'
                assert digest(database) == entry['database_sha256'], (key, 'source database checksum')
                prior = cached.get(key, {})
                if prior.get('rdf_sha256') == item['rdf_sha256'] and prior.get('database_sha256') == item['database_sha256']:
                    item['rdf'] = prior['rdf']
                    item['rdf_validation_reused_for_identical_bytes'] = True
                else:
                    item['rdf'] = validate_rdf(database, rdf)
                assert not item['rdf']['errors'], (key, item['rdf']['errors'])
            result['sources'].append(item)
            # A report marked incomplete can provide progress diagnostics but
            # cannot be used as a successful cache if the run is interrupted.
            args.report.parent.mkdir(parents=True, exist_ok=True)
            checkpoint = dict(result, errors=['Validation incomplete'])
            args.report.write_text(json.dumps(checkpoint, indent=2) + '\n')
            print(key + ': passed', flush=True)
        if not args.rdf_only:
            assert digest(args.sources / 'rdf-catalog.json') == manifest['source_catalog_sha256'], 'Source catalogue changed since build'
            for rel, expected in manifest['supplemental_inputs'].items():
                assert digest(args.site / 'data' / rel) == expected, ('supplemental evidence drift', rel)
                assert digest(REPO_ROOT / 'data_quality' / rel) == expected, ('current supplemental evidence differs', rel)
            sitemap = sitemap_paths(args.site)
            assert len(sitemap) == manifest['canonical_indexed_pages']
            assert all(page_file(args.site, p).exists() for p in sitemap)
    except Exception as e:
        result['errors'].append(repr(e))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(workbooks=len(result['sources']), errors=result['errors']), indent=2))
    raise SystemExit(bool(result['errors']))


if __name__ == '__main__':
    main()
