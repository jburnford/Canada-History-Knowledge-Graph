#!/usr/bin/env python3
"""Build citable HTML and retrieval records from the validated source RDF inputs.

Source cells remain assertions about source reporting units. The separately
assessed map links, census continuity groups, and external referents never
change those assertion subjects. No legacy Kuzu statistics are read.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import gzip
import hashlib
import html
import itertools
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from urllib.parse import quote

from _config import CONFIG, REPO_ROOT
from _site_urls import BASE, ORIGIN, UrlRegistry, page_file
from _wikidata_links import REASONS

RDF_BASE = 'http://temp.lincsproject.ca/census/'
HGIS = RDF_BASE + 'vocab/'
CRM = 'http://www.cidoc-crm.org/cidoc-crm/'
PROV = 'http://www.w3.org/ns/prov#'
PROVINCES = dict(AB='Alberta', BC='British Columbia', MB='Manitoba', NB='New Brunswick',
                 NL='Newfoundland and Labrador', NS='Nova Scotia', NT='Northwest Territories',
                 ON='Ontario', PE='Prince Edward Island', QC='Quebec', SK='Saskatchewan', YT='Yukon')
STYLE = '''body{margin:0;background:#f7f5ef;color:#202f31;font:17px/1.65 Georgia,serif}
header{background:#193b3c;color:white;padding:1rem max(1.4rem,calc((100% - 1100px)/2))}
header a{color:#fff;margin-right:1.3rem;font:600 15px system-ui;text-decoration:none}
main{max-width:1100px;margin:2.5rem auto;padding:0 1.4rem}h1,h2,h3,th,dt,.eyebrow{font-family:system-ui,sans-serif}
h1{font-size:clamp(1.8rem,4vw,3rem);line-height:1.15;max-width:950px}h2{margin-top:2.5rem;font-size:1.4rem}
a{color:#126267;text-underline-offset:3px}a:hover{color:#9a4420}code,pre{overflow-wrap:anywhere;font-size:.85em}
pre{white-space:pre-wrap}.note{border-left:4px solid #bd8849;background:#eee9db;padding:.8rem 1.2rem}
.eyebrow{font-size:.8rem;letter-spacing:.12em;text-transform:uppercase;color:#647570}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.91rem;background:#fffdf8}
th,td{text-align:left;vertical-align:top;border-bottom:1px solid #d6d8ce;padding:.65rem}th{background:#e7ece5}
small{display:block;color:#526562}dl{display:grid;grid-template-columns:minmax(120px,220px) 1fr;gap:.4rem 1rem}dd{margin:0;overflow-wrap:anywhere}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem}.card{padding:1rem;background:#fffdf8;border:1px solid #d6d8ce}
footer{border-top:1px solid #c4cbc1;margin-top:3rem;padding:1rem 0;font-size:.85rem}li{margin:.25rem 0}
:target{background:#fff1ba} .dcb-persons{margin:1rem 0} @media(max-width:600px){dl{display:block}dd{margin-bottom:.8rem}}
'''


def esc(value):
    return html.escape(str(value if value is not None else ''), quote=True)


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def rows(path):
    with Path(path).open(newline='', encoding='utf-8') as f:
        yield from csv.DictReader(f)


def iri(identifier):
    return RDF_BASE + quote(str(identifier), safe='/_-.')


def source_path(key):
    return f'{BASE}/sources/{quote(key, safe="_-.")}/'


def row_path(key, row):
    return source_path(key) + f'rows/{row}/'


def link(path, label):
    return f'<a href="{esc(path)}">{esc(label)}</a>'


def listing(items):
    return '<ul>' + ''.join('<li>' + item + '</li>' for item in items) + '</ul>'


def fields(record):
    return '<dl>' + ''.join(f'<dt>{esc(k)}</dt><dd>{esc(v)}</dd>' for k, v in record.items()) + '</dl>'


def table(headers, records):
    return '<div class="table-wrap"><table><thead><tr>' + ''.join(f'<th>{esc(x)}</th>' for x in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + x + '</td>' for x in r) + '</tr>' for r in records) + '</tbody></table></div>'


def cell_record(source, unit, observation, definition):
    """Lossless retrieval projection. Numeric strings avoid floating-point loss."""
    o = dict(observation)
    o.update(source_key=source['source_key'], workbook=Path(source['path']).name,
             workbook_sha256=source['sha256'], worksheet=source['sheet'],
             definition=definition['definition'], definition_evidence=json.loads(definition['definition_source_json']),
             column_role=definition['column_role'], reporting_label=unit['label'], province=unit['province'],
             reporting_level=unit['reporting_level'], source_code=unit['source_code'],
             source_reporting_unit=iri('source-reporting-unit/' + unit['unit_id']),
             rdf_id=iri('source-cell/' + source['sha256'] + '/' + observation['observation_id']),
             variable_iri=iri('source-variable/' + source['source_key'] + '/' + observation['column_key']),
             reference_period_iri=iri('reference-period/' + source['source_key'] + '/' + observation['column_key']),
             source_document=iri('source-table/' + source['source_key'] + '/' + source['sha256']),
             citation_url=ORIGIN + row_path(source['source_key'], unit['excel_row']) + '#cell-' + observation['column_key'])
    # Keep the source lexical value too; this is the RDF decimal's lexical form.
    o['rdf_decimal'] = format(Decimal(o['numeric_value']), 'f') if o['value_status'] == 'numeric' else None
    return o


def cell_html(c):
    numeric = c['value_status'] == 'numeric'
    value = c['rdf_decimal'] if numeric else ('Blank in source' if c['value_status'] == 'source_blank' else 'Source text: ' + str(json.loads(c['raw_value_json'])))
    period = (str(c['reference_year']) if c['reference_year'] is not None else 'Reference year unresolved')
    # Data attributes support independent reconciliation of the visible table.
    attrs = {'id': 'cell-' + c['column_key'], 'data-cell': c['observation_id'],
             'data-status': c['value_status'], 'data-value': c['rdf_decimal'] if numeric else '',
             'data-year': c['reference_year'] if c['reference_year'] is not None else '',
             'data-unit': c['unit'] or ''}
    return '<tr ' + ' '.join(f'{k}="{esc(v)}"' for k, v in attrs.items()) + '>' + ''.join('<td>' + x + '</td>' for x in [
        link('#cell-' + c['column_key'], c['source_cell']) + '<small>' + esc(c['source_column']) + '</small>',
        esc(c['definition'] or 'Definition requires source interpretation'),
        esc(value) + '<small>' + esc(c['value_status']) + '</small>',
        esc(c['unit'] or 'Unit unresolved') + '<small>' + esc(c['unit_status']) + '</small>',
        esc(period) + '<small>' + esc(c['reference_period_kind']) + ': ' + esc(c['reference_period_text']) + '</small>'
    ]) + '</tr>'


def wikidata_html(associations):
    """Present accepted reference links plainly; explain only actual conflicts."""
    accepted, review = [], []
    for e in associations:
        if not e['wikidata_qid']:
            continue
        item = link('https://www.wikidata.org/entity/' + e['wikidata_qid'], e['wikidata_label'] or e['wikidata_qid'])
        if e.get('external_type_labels'):
            item += ' — ' + esc(e['external_type_labels'])
        if e.get('link_accepted') == 'True':
            accepted.append(item)
        elif e.get('mapping_status') == 'review_specific_conflict':
            reasons = json.loads(e['review_reasons_json'])
            review.append(item + '<p>' + esc(' '.join(REASONS[r] for r in reasons)) + '</p>')
        else:
            raise ValueError('Unassessed Wikidata link; rebuild the identity inventory')
    body = '<h2>Wikidata</h2>' + listing(accepted) if accepted else ''
    if review:
        body += '<h2>Wikidata links needing clarification</h2>' + listing(review)
    return body


class Builder:
    def __init__(self, out, sources, identity, bindings, published):
        self.out, self.sources, self.identity, self.bindings_dir, self.published = out, sources, identity, bindings, published
        self.registry = UrlRegistry()
        self.handled, self.indexed = set(), set()
        self.bound = {r['unit_id']: r for r in rows(bindings / 'bindings.csv')}
        self.reps = {r['snapshot_id']: r for r in rows(identity / 'representations.csv')}
        self.units = {r['unit_id']: r for r in rows(identity / 'units.csv')}
        self.members, self.legacy, self.source_links = defaultdict(list), defaultdict(set), defaultdict(list)
        self.snapshot_urls, self.unit_urls = {}, {}
        self.province_sources, self.province_maps = defaultdict(list), defaultdict(list)
        self.manifest = dict(format_version=1, sources=[], supplemental_inputs={}, datasets={})
        for r in self.reps.values():
            if r['unit_id']:
                self.members[r['unit_id']].append(r)
            prefix = 'place:' if r['level'] == 'csd' else 'cd:'
            self.legacy[prefix + r['legacy_unit_id']].add(r['snapshot_id'])
            key = 'presence:' + r['snapshot_id'] if r['level'] == 'csd' else 'snapshot:' + r['snapshot_id']
            self.snapshot_urls[r['snapshot_id']] = self.registry.resolve(key, f'{BASE}/snapshots/{r["level"]}/{quote(r["snapshot_id"], safe="_-.")}/')
        for u in self.units.values():
            prefix = 'place:' if u['level'] == 'csd' else 'cd:'
            old_key = prefix + u['unit_id']
            # Reuse only unchanged, explicitly retained identities.
            key = old_key if u['reused_legacy_identifier'] == 'True' and old_key in self.registry.by_entity else 'unit:' + u['unit_id']
            self.unit_urls[u['unit_id']] = self.registry.resolve(key, f'{BASE}/units/{u["level"]}/{quote(u["unit_id"], safe="_-.")}/')

    def write(self, path, title, body, kind='Historical census record', data=None, redirect='', noindex=False):
        if path in self.handled:
            raise ValueError(f'Duplicate output: {path}')
        self.handled.add(path)
        if not redirect and not noindex:
            self.indexed.add(path)
        metadata = ''
        if data is not None:
            metadata = '<script type="application/ld+json">' + dump(data).replace('<', '\\u003c') + '</script>'
        head = ('<meta name="robots" content="noindex,follow">' if noindex else '')
        if redirect:
            head += f'<meta http-equiv="refresh" content="0;url={esc(ORIGIN + redirect)}">'
        text = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | HGIS Canada</title><link rel="canonical" href="{esc(ORIGIN + (redirect or path))}">
<link rel="stylesheet" href="{BASE}/assets/rdf-site.css">{head}{metadata}</head><body>
<header>{link(BASE + '/', 'HGIS Canada')}{link(BASE + '/sources/', 'Census sources')}{link(BASE + '/data/', 'Data for retrieval')}{link(BASE + '/about/', 'About')}</header>
<main><p class="eyebrow">{esc(kind)}</p><h1>{esc(title)}</h1>{body}
<footer>Canadian historical census evidence · {link(BASE + '/about/#interpretation', 'How to interpret these records')} · {link(BASE + '/data/build-manifest.json', 'Data edition and checksums')}</footer></main></body></html>'''
        dest = page_file(self.out, path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding='utf-8')

    def supplements(self, path):
        old = self.registry.rows.get(path)
        if not old or not (old['people_links'] or old['resident_links']):
            return ''
        original = page_file(self.published, path).read_text()
        result = ''
        if old['people_links']:
            tables = re.findall(r'<table\b[^>]*class=["\'][^"\']*dcb-persons[^"\']*["\'][^>]*>.*?</table>', original, re.S | re.I)
            result += '<h2>People and biographical connections</h2><p>These published connections come from the separate LINCS / Dictionary of Canadian Biography layer. A life event or overlapping lifespan does not establish residence at a census date. The association remains attached to this published page; it is not assigned to every revised census group.</p>' + ''.join(tables)
            missing = [u for u in json.loads(old['people_links']) if esc(u) not in ''.join(tables) and u not in ''.join(tables)]
            if missing:
                result += listing(link(u, 'Dictionary of Canadian Biography source') for u in missing)
        if old['resident_links']:
            result += '<h2>Individual records from the 1881 census</h2><p>The individual census transcription is a separate dataset. Existing person citation anchors and the published geographic grouping are preserved. These records are not population totals derived from the rebuilt aggregate tables.</p>'
            result += listing(link(u, 'Browse 1881 census residents') for u in json.loads(old['resident_links']))
        return result

    def prepare(self):
        if self.out.resolve() in {self.published.resolve(), (REPO_ROOT / 'rag_site').resolve()}:
            raise ValueError('Use an isolated RDF-site output, not the publication or legacy build.')
        if self.out.exists() and any(self.out.iterdir()):
            raise ValueError('Output must be empty: use a new --out directory to avoid stale pages.')
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / 'assets').mkdir()
        (self.out / 'assets/rdf-site.css').write_text(STYLE)
        (self.out / 'data').mkdir()
        resident_assets = self.published / 'places/residents-assets'
        if not resident_assets.is_dir():
            raise ValueError('Published resident styles/scripts are missing')
        shutil.copytree(resident_assets, self.out / 'places/residents-assets')
        # Only the distinct resident dataset survives as rendered HTML. All
        # aggregate-statistical and identity pages are built afresh below.
        for old in self.registry.rows.values():
            if old['entity_key'].startswith('residents:'):
                src, dest = page_file(self.published, old['path']), page_file(self.out, old['path'])
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest)
                self.handled.add(old['path'])
                if old['in_sitemap'] == '1':
                    self.indexed.add(old['path'])
        self.manifest['datasets']['residents_1881'] = dict(status='Preserved separate published transcription',
            pages=sum(r['entity_key'].startswith('residents:') for r in self.registry.rows.values()),
            person_anchors=sum(int(r['resident_anchor_count']) for r in self.registry.rows.values()),
            url_inventory_sha256=sha(REPO_ROOT / 'data/published_site_urls.csv'))
        print('Preserved resident pages and person anchors', flush=True)

    def build_sources(self):
        catalog = json.loads((self.sources / 'rdf-catalog.json').read_text())
        binding_manifest = json.loads((self.bindings_dir / 'manifest.json').read_text())
        if json.loads((self.bindings_dir / 'validation.json').read_text())['errors']:
            raise ValueError('Source binding validation failed')
        source_cards = []
        for entry in catalog['sources']:
            key = entry['source']
            folder = self.sources / key
            database, rdf = folder / 'source_observations.sqlite', folder / 'source_observations.nt.gz'
            digest = sha(database)
            manifest = json.loads((folder / 'source_observations.nt.manifest.json').read_text())
            validation = json.loads((folder / 'source_observations.nt.validation.json').read_text())
            if manifest != entry['export'] or validation != entry['validation'] or validation['errors']:
                raise ValueError(f'RDF validation/catalog mismatch: {key}')
            if digest != manifest['database_sha256'] or digest != binding_manifest['source_database_sha256'][key]:
                raise ValueError(f'RDF and spatial assessment input drift: {key}')
            if sha(REPO_ROOT / 'scripts/export_1911_reporting_rdf.py') != manifest['exporter_sha256']:
                raise ValueError('RDF exporter changed: export/validate RDF before building website')
            db = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
            db.row_factory = sqlite3.Row
            source = dict(db.execute('SELECT * FROM source').fetchone())
            columns = {r['column_key']: dict(r) for r in db.execute('SELECT * FROM source_columns')}
            units = {r['unit_id']: dict(r) for r in db.execute('SELECT * FROM reporting_units')}
            source_dir = self.out / 'sources' / key
            source_dir.mkdir(parents=True)
            shutil.copyfile(rdf, source_dir / 'source.nt.gz')
            shutil.copyfile(folder / 'source_observations.nt.validation.json', source_dir / 'rdf-validation.json')
            workbook_links, cell_count, numeric_count = [], 0, 0
            with gzip.open(source_dir / 'cells.jsonl.gz', 'wt', encoding='utf-8', compresslevel=6) as stream:
                # SQLite may sort, but never loads a national observation table in Python.
                query = 'SELECT o.* FROM observations o JOIN source_columns c USING(column_key) ORDER BY o.unit_id, c.column_index'
                for uid, obs in itertools.groupby(db.execute(query), key=lambda r: r['unit_id']):
                    unit = units[uid]
                    cells = [cell_record(source, unit, o, columns[o['column_key']]) for o in obs]
                    for c in cells:
                        stream.write(dump(c) + '\n')
                    cell_count += len(cells)
                    numeric_count += sum(c['value_status'] == 'numeric' for c in cells)
                    path = row_path(key, unit['excel_row'])
                    title = f'{unit["label"] or "Unlabelled reporting row"} — {source["census_vintage"]} · {source["table_key"]}, row {unit["excel_row"]}'
                    binding = self.bound[uid]
                    candidates = json.loads(binding['snapshot_ids_json'])
                    for sid in candidates:
                        if sid not in self.reps or self.reps[sid]['is_coverage_record'] == 'True':
                            raise ValueError(f'Invalid map endpoint: {uid} / {sid}')
                        self.source_links[sid].append(dict(path=path, label=title, status=binding['status']))
                    body = '<p class="note">These are values reported for the unit named in this source row. The census geography vintage does not supply a missing reference year. Blank cells are not zero; repeated column labels remain separate source positions.</p>'
                    body += fields({'Source workbook': Path(source['path']).name, 'Worksheet / row': f'{source["sheet"]} / {unit["excel_row"]}',
                        'Source label': unit['label'], 'Province code in source': unit['province'], 'Source code': unit['source_code'],
                        'Reporting level': unit['reporting_level'], 'Reporting geography vintage': source['census_vintage'],
                        'RDF reporting unit': iri('source-reporting-unit/' + uid), 'RDF row record': iri('source-row/' + source['sha256'] + '/' + str(unit['excel_row'])),
                        'Workbook SHA-256': source['sha256'], 'Spatial binding status in source RDF': unit['spatial_binding_status']})
                    body += '<h2>Reported cells</h2><p>Each cell link is a citation to the exact worksheet position. The downloadable retrieval record also includes its RDF identifier and original value.</p><div class="table-wrap"><table><thead><tr><th>Source cell / column</th><th>Definition</th><th>Reported value</th><th>Unit</th><th>Reference period</th></tr></thead><tbody>' + ''.join(cell_html(c) for c in cells) + '</tbody></table></div>'
                    body += '<h2>Geographic assessment</h2>' + fields({'Assessment status': binding['status'], 'Method': binding['method'], 'Survey designation': unit['survey_unit_id'] or 'Not supplied'})
                    body += '<p>This separately assessed relationship is navigation evidence, not a claim that the source reporting unit, a map polygon, a historical municipality, or a modern Wikidata entity are identical.</p>'
                    body += listing(link(self.snapshot_urls[sid], f'{self.reps[sid]["name"]} ({sid}) — {binding["status"]}') for sid in candidates)
                    if binding['status'] == 'explicit_identifier_context_conflict':
                        body += '<p class="note">The source identifier conflicts with its geographic context. Values on this page must not be attributed to the same-code map area.</p>'
                    body += '<h2>Source metadata</h2><pre>' + esc(json.dumps(json.loads(unit['source_metadata_json']), ensure_ascii=False, indent=2)) + '</pre>'
                    body += '<p>' + link(source_path(key), 'Workbook, definitions, provenance and downloads') + '</p>'
                    data = {'@context': {'schema': 'https://schema.org/', 'prov': PROV}, '@id': ORIGIN + path,
                            '@type': 'schema:WebPage', 'schema:name': title,
                            'schema:mainEntity': {'@id': iri('source-row/' + source['sha256'] + '/' + str(unit['excel_row']))},
                            'prov:wasDerivedFrom': {'@id': iri('source-table/' + key + '/' + source['sha256'])}}
                    self.write(path, title, body, 'Census source row', data)
                    workbook_links.append((unit['excel_row'], link(path, f'{unit["province"]} · {unit["label"] or "Unlabelled row"} · row {unit["excel_row"]}')))
                    self.province_sources[unit['province']].append((key, path, title))
            if cell_count != manifest['source_cells'] or numeric_count != manifest['numeric_observations'] or len(workbook_links) != len(units):
                raise ValueError(f'Source reconciliation failed: {key}')
            db.close()
            body = '<p>Preserved source table from the Canadian Peoples / TCP census collection. Row totals, survey units, missing values and unresolved interpretations remain visible.</p>'
            body += fields({'Workbook': Path(source['path']).name, 'Worksheet': source['sheet'], 'Census vintage': source['census_vintage'],
                            'Reporting rows': len(units), 'Preserved statistical cells': cell_count, 'Numeric observations': numeric_count, 'Workbook SHA-256': source['sha256']})
            body += '<p>' + link(source_path(key) + 'source.nt.gz', 'Download the current RDF (N-Triples, gzip)') + ' · ' + link(source_path(key) + 'cells.jsonl.gz', 'Download citable cells (JSONL, gzip)') + ' · ' + link(source_path(key) + 'rdf-validation.json', 'RDF validation') + '</p>'
            body += '<h2>Column definitions</h2>' + table(['Position', 'Source column', 'Definition', 'Unit / status', 'Reference period'], [
                [esc(c['column_key']), esc(c['source_column']), esc(c['definition'] or 'Unresolved'), esc(c['unit'] or 'Unresolved') + '<small>' + esc(c['unit_status']) + '</small>',
                 esc(c['reference_year'] if c['reference_year'] is not None else 'Reference year unresolved') + '<small>' + esc(c['reference_period_kind']) + ': ' + esc(c['reference_period_text']) + '</small>']
                for c in columns.values() if c['column_role'] != 'metadata'])
            body += '<h2>Reporting rows</h2>' + listing(x[1] for x in sorted(workbook_links))
            data = {'@context': 'https://schema.org', '@type': 'Dataset', '@id': iri('dataset/' + key + '/' + source['sha256']),
                    'name': key, 'description': 'Source census cells with qualified reporting geography, reference periods, units, missingness and workbook provenance.',
                    'url': ORIGIN + source_path(key), 'isAccessibleForFree': True,
                    'distribution': [{'@type': 'DataDownload', 'encodingFormat': fmt, 'contentUrl': ORIGIN + source_path(key) + name}
                                     for name, fmt in [('source.nt.gz', 'application/n-triples'), ('cells.jsonl.gz', 'application/x-ndjson')]]}
            self.write(source_path(key), key, body, 'Census source workbook', data)
            source_cards.append(link(source_path(key), key) + f' — {len(units):,} reporting rows; {numeric_count:,} numeric cells')
            self.manifest['sources'].append(dict(source_key=key, database_sha256=digest, workbook_sha256=source['sha256'],
                rdf_sha256=sha(rdf), retrieval_sha256=sha(source_dir / 'cells.jsonl.gz'), reporting_rows=len(units), source_cells=cell_count, numeric_observations=numeric_count))
            print(f'{key}: {len(units):,} rows / {cell_count:,} cells', flush=True)
        self.write(BASE + '/sources/', 'Census source tables, 1851–1921', '<p>Browse each table as it was reported. Each row has a citable page; every statistical source cell retains its position, value status and provenance.</p>' + listing(source_cards), 'Source catalogue')

    def copy_evidence(self):
        paths = list(self.identity.glob('*.csv')) + [self.identity / 'manifest.json', self.bindings_dir / 'bindings.csv', self.bindings_dir / 'manifest.json', self.bindings_dir / 'validation.json']
        gis = REPO_ROOT / 'data_quality/gis_audit_equal_area'
        paths += sorted(gis.glob('*_correspondences.csv')) + sorted(gis.glob('*_topology_*.csv'))
        expected = json.loads((self.identity / 'manifest.json').read_text())['source_sha256']
        for rel, digest in expected.items():
            if sha(REPO_ROOT / rel) != digest:
                raise ValueError(f'Identity evidence changed: {rel}')
        for src in paths:
            rel = src.relative_to(REPO_ROOT / 'data_quality')
            dest = self.out / 'data' / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            self.manifest['supplemental_inputs'][str(rel)] = sha(src)
        return gis

    def build_maps(self, gis):
        edges, separations, decisions = defaultdict(list), defaultdict(list), defaultdict(list)
        # GIS source IDs are level-specific, and CD IDs already contain a year.
        lookup = {(r['level'], r['source_id'], r['year']): sid for sid, r in self.reps.items()}
        for file in sorted(gis.glob('*_correspondences.csv')):
            level = file.name.split('_')[0]
            for e in rows(file):
                a = lookup[(level, e['id_from'], e['year_from'])]
                b = lookup[(level, e['id_to'], e['year_to'])]
                e = dict(e, from_snapshot=a, to_snapshot=b)
                edges[a].append((e, b)); edges[b].append((e, a))
        for e in rows(self.identity / 'boundary_redistributions.csv'):
            for col, year in [('id_from', 'year_from'), ('continuing_id_to', 'year_to'), ('separate_id_to', 'year_to')]:
                sid = lookup[(e['level'], e[col], e[year])]
                separations[sid].append(e)
        for e in rows(self.identity / 'continuity_decisions.csv'):
            for col, year in [('id_from', 'year_from'), ('id_to', 'year_to')]:
                decisions[lookup[(e['level'], e[col], e[year])]].append(e)
        for sid, r in self.reps.items():
            path = self.snapshot_urls[sid]
            title = f'{r["name"]} — {r["year"]} census geography ({r["province"]})'
            coverage = r['is_coverage_record'] == 'True'
            body = '<p class="note">' + ('This is a NO DATA coverage record. It identifies map coverage, not a historical community or a population of zero.' if coverage else 'This page identifies a census boundary representation. Source-table records below retain their own reporting-unit identity and geographic qualifications.') + '</p>'
            body += fields({'Map snapshot identifier': sid, 'Source boundary identifier': r['source_id'], 'Census vintage': r['year'],
                            'Source label': r['name'], 'Province code': r['province'], 'District label': r['cd_name'], 'Level': r['level'], 'Representation class': r['representation_class']})
            if r['unit_id']:
                body += '<p>' + link(self.unit_urls[r['unit_id']], 'Census continuity group: ' + self.units[r['unit_id']]['canonical_name']) + '</p>'
            # Retain machine-readable legacy identity markers used by the URL audit.
            if r['level'] == 'csd':
                body += '<p><strong>TCP UID:</strong> <code>' + esc(r['source_id']) + '</code></p>'
            body += '<h2>Census source records</h2>'
            associated = self.source_links[sid]
            if associated:
                body += '<p>Each link states the assessment that connected the source row to this map. Name candidates remain candidates; no source statistic is silently assigned to the map.</p>'
                body += listing(link(e['path'], e['label']) + ' <small>' + esc(e['status']) + '</small>' for e in associated)
            else:
                body += '<p>No source row has a supported or candidate endpoint here in the current assessment. This does not mean the population was zero.</p>'
            body += '<h2>Boundary intersections across censuses</h2><p>These are computed polygon intersections in the equal-area CRS ESRI:102001. Fractions describe the area of the earlier and later polygons, respectively. They do not establish historical succession, and population has not been apportioned by area. All positive intersections are retained, including very small contributions.</p>'
            body += table(['Other census representation', 'Years (earlier → later)', 'Overlap (m²)', 'Fraction of earlier area', 'Fraction of later area', 'Evidence'], [
                [link(self.snapshot_urls[other], self.reps[other]['name'] + ' · ' + self.reps[other]['year']), esc(e['year_from'] + ' → ' + e['year_to']), esc(e['overlap_sqm']), esc(e['frac_from']), esc(e['frac_to']), esc(e['spatial_relation']) + '<small>Historical succession verified: ' + esc(e['historical_succession_verified']) + '</small>'] for e, other in edges[sid]])
            if decisions[sid]:
                body += '<h2>Continuity assessments</h2>' + listing(esc(e['name_from'] + ' (' + e['year_from'] + ') → ' + e['name_to'] + ' (' + e['year_to'] + '): ' + e['decision']) for e in decisions[sid])
            if separations[sid]:
                body += '<h2>Area separations</h2>' + table(['Earlier area', 'Continuing area', 'Separate area', 'Retained fraction', 'Separated fraction', 'Comparison status'], [
                    [esc(e['earlier_name'] + ' · ' + e['year_from']), esc(e['continuing_name'] + ' · ' + e['year_to']), esc(e['separate_name']), esc(e['retained_earlier_area_fraction']), esc(e['separate_earlier_area_fraction']), esc(e['comparison_status'])] for e in separations[sid]])
            body += self.supplements(path)
            body += '<p>' + link(BASE + '/data/', 'Download geographic, continuity and source-binding evidence') + '</p>'
            self.write(path, title, body, 'Census boundary evidence')
            self.province_maps[r['province']].append((r['year'], r['name'], path))
        self.build_units()
        print(f'Built {len(self.reps):,} map representations and {len(self.units):,} continuity groups', flush=True)

    def build_units(self):
        external = defaultdict(list)
        for e in rows(self.identity / 'wikidata_associations.csv'):
            if e['unit_id']:
                external[e['unit_id']].append(e)
        for uid, u in self.units.items():
            path = self.unit_urls[uid]
            body = '<p class="note">This grouping records the current assessment of census continuity. A shared group does not by itself establish a historical municipality or make statistics directly comparable across changed boundaries.</p>'
            body += fields({'Identifier': uid, 'Identity scope': u['identity_scope'], 'Identity basis': u['identity_basis'],
                            'CRM class': u['crm_class'], 'Recorded area separation': u['has_recorded_area_separation'], 'Census years': u['years']})
            body += '<h2>Census representations and source evidence</h2>' + listing(link(self.snapshot_urls[r['snapshot_id']], r['name'] + ' · ' + r['year'] + ' · ' + r['province']) for r in sorted(self.members[uid], key=lambda r: r['year']))
            body += wikidata_html(external[uid])
            body += self.supplements(path)
            old = self.registry.rows.get(path, {})
            if old.get('entity_key', '').startswith('place:'):
                body += '<p><strong>Persistent place ID:</strong> <code>' + esc(uid) + '</code></p>'
            elif old.get('entity_key', '').startswith('cd:'):
                body += '<p><strong>HGIS Canada CD ID:</strong> <code>' + esc(uid) + '</code></p>'
            self.write(path, u['canonical_name'] + ' — census continuity group', body, 'Qualified census identity')

    def build_legacy(self):
        for path, old in self.registry.rows.items():
            if path in self.handled or old['redirect_path'] or not old['entity_key']:
                continue
            key = old['entity_key']
            original = page_file(self.published, path).read_text()
            match = re.search(r'<h1[^>]*>(.*?)</h1>', original, re.S | re.I)
            title = html.unescape(re.sub('<[^>]+>', '', match[1])) if match else key.split(':', 1)[-1]
            body = '<p class="note">This published address is retained for citations and search results. Its earlier grouping has been reviewed against the current census inventory. Use the source records and qualified groups linked below for the current data edition.</p>'
            sids = sorted(self.legacy.get(key, set()))
            if key.startswith('presence:') and key[9:] in self.reps:
                sids = [key[9:]]
            groups = sorted({self.reps[sid]['unit_id'] for sid in sids if self.reps[sid]['unit_id']})
            if groups:
                body += '<h2>Current census groups</h2>' + listing(link(self.unit_urls[uid], self.units[uid]['canonical_name'] + ' · ' + self.units[uid]['years']) for uid in groups)
            if sids:
                body += '<h2>Individual census representations</h2>' + listing(link(self.snapshot_urls[sid], self.reps[sid]['name'] + ' · ' + self.reps[sid]['year']) for sid in sids)
            else:
                body += '<p>A correspondence to a current representation has not been established for this earlier grouping. Its former statistical series is not treated as current evidence.</p><p>' + link(BASE + '/sources/', 'Browse the current source tables') + '</p>'
            body += self.supplements(path)
            marker = 'Persistent place ID:' if key.startswith('place:') else 'HGIS Canada CD ID:' if key.startswith('cd:') else ''
            if marker:
                body += '<p><strong>' + marker + '</strong> <code>' + esc(key.split(':', 1)[1]) + '</code></p>'
            self.write(path, title, body, 'Published address and revised interpretation')
        # Resolve already broken published redirects using the inventoried source
        # representation, without copying the archive's obsolete statistics.
        recovery = json.loads((REPO_ROOT / 'data/site_legacy_records.json').read_text())['pages']
        for rec in recovery:
            if rec['path'] in self.handled or rec['kind'] != 'source_record':
                continue
            r = rec['source_record']; sid = r['snapshot_id']
            body = '<p>This address identifies a boundary record referenced by an earlier published redirect.</p>' + fields({'Source label': r['name'], 'Census vintage': r['year'], 'Source boundary identifier': r['source_id']})
            if sid in self.snapshot_urls:
                body += '<p>' + link(self.snapshot_urls[sid], 'Current census representation and source evidence') + '</p>'
            self.write(rec['path'], r['name'] + ' — ' + r['year'] + ' source boundary record', body)
        for path, old in self.registry.rows.items():
            if path in self.handled or not old['redirect_path']:
                continue
            dest, seen = old['redirect_path'], {path}
            while dest in self.registry.rows and self.registry.rows[dest]['redirect_path']:
                if dest in seen:
                    raise ValueError('Published redirect cycle: ' + path)
                seen.add(dest); dest = self.registry.rows[dest]['redirect_path']
            if dest not in self.handled:
                # Some published redirects named intermediary addresses that
                # never existed as pages. Preserve the route and explain it;
                # a code extracted from an old URL is only a search key.
                m = re.search(r'-([a-z]{2}[a-z0-9]+)(?:-(18\d{2}|19\d{2}))?/$', dest, re.I)
                candidates = [r for r in self.reps.values() if m and r['source_id'] == m[1].upper()
                              and (not m[2] or r['year'] == m[2])]
                body = '<p>This address was the target of an earlier published redirect. Its correspondence to the revised census inventory requires interpretation; the former URL does not establish a historical identity.</p>'
                if candidates:
                    body += '<h2>Inventory records matching the identifier in the earlier URL</h2><p>These links are lookup results, not identity assertions.</p>' + listing(link(self.snapshot_urls[r['snapshot_id']], r['name'] + ' · ' + r['year'] + ' · ' + r['province']) for r in candidates)
                body += '<p>' + link(BASE + '/sources/', 'Browse the current source tables') + '</p>'
                self.write(dest, 'Earlier census address — correspondence under review', body, 'Published redirect reference')
            self.write(path, 'Census record', '<p>' + link(dest, 'Continue to the census record') + '</p>', redirect=dest, noindex=True)

    def build_editorial(self):
        # Normalize navigation only. Original province cells (including blanks,
        # formula strings and historical codes) remain untouched in source data.
        province_sources = defaultdict(list)
        for raw, records in self.province_sources.items():
            normalized = str(raw or '').strip().upper()
            normalized = 'PE' if normalized == 'PEI' else normalized
            if normalized in PROVINCES:
                province_sources[normalized].extend(records)
        for prov in sorted(PROVINCES):
            path = BASE + '/places/' + prov.lower() + '/'
            body = '<p>Province and territory codes follow the source inventories. Historical boundaries and reporting units change across censuses.</p>'
            keys = sorted({x[0] for x in province_sources[prov]})
            body += '<h2>Source tables containing this province code</h2>' + listing(link(source_path(k), k) for k in keys)
            for year, group in itertools.groupby(sorted(self.province_maps[prov]), key=lambda r: r[0]):
                body += '<h2>' + esc(year) + ' census geography</h2>' + listing(link(path, name) for _, name, path in group)
            self.write(path, PROVINCES.get(prov, prov) + ' historical census records', body, 'Browse by source geography')
        totals = {field: sum(s[field] for s in self.manifest['sources']) for field in ['reporting_rows', 'source_cells', 'numeric_observations']}
        self.manifest['totals'] = dict(workbooks=len(self.manifest['sources']), **totals,
            map_representations=len(self.reps), continuity_groups=len(self.units), coverage_records=sum(r['is_coverage_record'] == 'True' for r in self.reps.values()))
        body = '<p>Explore Canadian history through citable census tables, geographic evidence, biographies and individual census records.</p>'
        body += f'<div class="grid"><div class="card"><strong>{totals["reporting_rows"]:,} source rows</strong><br>Original labels, reporting levels and workbook provenance.</div><div class="card"><strong>{totals["numeric_observations"]:,} numeric observations</strong><br>Source values with units, reference periods and exact cell citations.</div><div class="card"><strong>1881 residents and biographies</strong><br>Preserved individual records and published biographical connections.</div></div>'
        body += '<h2>Find historical evidence</h2><p>' + link(BASE + '/sources/', 'Browse all census source tables') + ' · ' + link(BASE + '/data/', 'Download data for retrieval and RAG') + '</p>'
        body += '<h2>Browse by province or territory</h2>' + listing(link(BASE + '/places/' + p.lower() + '/', name) for p, name in PROVINCES.items())
        body += '<h2 id="data-edition">Current data edition</h2><p>Aggregate census pages are built from the same validated source-cell databases as the current RDF. Geographic bindings and continuity assessments are provided as separate, qualified evidence. Individual 1881 census records and LINCS biographical associations remain distinct datasets.</p>'
        self.write(BASE + '/', 'Historical evidence, ready to cite', body, 'HGIS Canada · 1851–1921')
        about = '''<p>HGIS Canada makes historical census evidence readable by people and retrievable by language models. A useful answer should be traceable to a particular source, reporting unit, worksheet cell and interpretation.</p>
<h2 id="data-edition">What this edition contains</h2><p>The aggregate census pages and retrieval files use the exact source databases used to export the current national source RDF. Each workbook download preserves the exported RDF bytes. Build checksums identify the database, original workbook and RDF edition.</p>
<p>The website also presents the revised national census representation and continuity inventories, source-to-map assessments, equal-area boundary intersections and area separations. These are qualified supplemental evidence layers; the source RDF does not assert that each candidate map match is an identity.</p>
<h2 id="interpretation">How to interpret and cite the data</h2><ul><li>Cite an individual cell link, including the workbook and worksheet position. A source reporting unit is the subject of a reported value.</li><li>Keep reporting geography vintage separate from the reference year of a value. Unresolved years and units remain unresolved.</li><li>Blank cells are missing source values, not zeros. Text cells require interpretation. Duplicate variable labels remain distinct column positions.</li><li>Do not add CSD rows, district totals and province totals together. They overlap in reporting scope. Repeated statistics across workbooks are separate source statements, not independent populations.</li><li>Name matches and reused source codes do not establish geographic identity. Identifier/context conflicts and survey designations remain visible.</li><li>Census continuity is qualified evidence. A polygon overlap is not proof of municipal succession. Area fractions are not population fractions; no population apportionment has been performed.</li><li>Established Wikidata links are retained using prior verification and automated checks of names, place types, provincial context and available geographic evidence. Links with specific conflicting evidence are labelled for clarification; missing metadata alone does not require individual review. A reproducible sample supports quality checks. These reference links do not assert that every census boundary is identical to the linked entity; detailed assessments and evidence are available in the data downloads.</li></ul>
<h2>People and the 1881 census</h2><p>Prominent-person connections come from the LINCS / Dictionary of Canadian Biography layer. A life-event connection or lifespan overlap does not prove census residence. These associations remain on their published pages without automatic redistribution across revised census identities.</p><p>The individual 1881 transcription is a separate Canadian Peoples dataset. Its published resident pages and person anchors are preserved. Aggregate totals and counts of transcribed residents can differ in coverage and must not be substituted for one another.</p>
<h2>Sources, scope and stewardship</h2><p>The source workbooks and geographic inventories come from the <a href="https://borealisdata.ca/dataverse/canadiansubdivisions">Canadian Peoples / TCP census collection</a>. The individual census deposit is <a href="https://doi.org/10.5683/SP3/FXZEVO">the 1881 Canadian census transcription</a>. Biographical pages cite the <a href="https://www.biographi.ca/">Dictionary of Canadian Biography</a>. Consult the originating deposits for their documentation and reuse terms.</p>
<p>The <a href="https://github.com/jburnford/Canada-History-Knowledge-Graph">pipeline repository</a> contains the build and assessment methods. The <a href="https://github.com/jburnford/hgiscanada">website repository</a> holds the published static files. Earlier URLs are retained; an address may now explain a revised grouping rather than repeat an unsupported historical series.</p>'''
        self.write(BASE + '/about/', 'About the data and methodology', about, 'Sources and interpretation')
        downloads = []
        for rel in self.manifest['supplemental_inputs']:
            downloads.append(link(BASE + '/data/' + rel, rel))
        data = '<p>Use the source-cell JSONL files as retrieval records. Each line is self-contained: a source reporting subject, exact RDF cell identifier, citation URL, workbook checksum, label, reporting geography vintage, variable definition, reference-period status, unit status and original value.</p><p><code>numeric_value</code> retains the staged lexical value; <code>rdf_decimal</code> is the exact decimal string used in the RDF. For blank and text records, <code>rdf_decimal</code> is null. Null years must not be replaced by census vintage.</p><p>Chunk by source row or cell. Retrieve the row context along with each cell, preserve qualifications, and cite the <code>citation_url</code>. Do not join a cell to a map using <code>source_code</code> alone. Candidate map matches are deliberately kept outside the cell assertion.</p>'
        data += '<h2>Aggregate source data</h2>' + listing(link(source_path(s['source_key']) + 'cells.jsonl.gz', s['source_key'] + ' — retrieval cells') + ' · ' + link(source_path(s['source_key']) + 'source.nt.gz', 'RDF') for s in self.manifest['sources'])
        data += '<h2>Qualified geographic and identity evidence</h2><p>These files retain assessment methods and statuses. Same-year topology intersections are not a boundary-adjacency network. Cross-year intersections do not assert historical succession.</p>' + listing(downloads)
        data += '<h2>Wikidata reference links</h2><p>In <code>wikidata_associations.csv</code>, <code>link_accepted</code> identifies retained reference links. The acceptance basis, verification evidence and evidence gaps explain each assessment. Only specific conflicting evidence creates a review flag, with reasons in <code>review_reasons_json</code>. The review queue contains those flagged links; the QA sample supports periodic checks of accepted links. Link acceptance does not assert identical census boundaries or transfer statistics to a Wikidata entity.</p>'
        data += '<h2>Edition and dataset boundaries</h2><p>' + link(BASE + '/data/build-manifest.json', 'Build manifest and SHA-256 checksums') + ' · ' + link(BASE + '/about/', 'Interpretation and original sources') + '</p><p>The preserved 1881 resident pages and biographical tables are separate retrieval sources. They are not included in the aggregate-cell JSONL distributions.</p>'
        self.write(BASE + '/data/', 'Data for retrieval and RAG', data, 'Machine-readable evidence')
        (self.out / 'llms.txt').write_text('# HGIS Canada\n\nCitable Canadian census source evidence, 1851–1921.\n\n'
            f'- [Source catalogue]({ORIGIN}{BASE}/sources/)\n- [Retrieval files and schema notes]({ORIGIN}{BASE}/data/)\n'
            f'- [Interpretation rules]({ORIGIN}{BASE}/about/#interpretation)\n\n'
            'Cite cell URLs. Preserve unknown years, unknown units, blank values, reporting levels and geographic qualifications. '
            'Never equate source-code or name matches with historical identity. Area fractions are not population fractions. '
            'Individual 1881 records and biographies are separate datasets.\n')

    def finish(self):
        missing = set(self.registry.rows) - self.handled
        if missing:
            raise ValueError(f'Unhandled publication addresses: {sorted(missing)[:10]}')
        # The sitemap index stays below the protocol limit; child sitemaps have
        # at most 40,000 canonical URLs, leaving room for longer URL lengths.
        locations = sorted(self.indexed)
        sitemap_files = []
        for start in range(0, len(locations), 40000):
            name = f'sitemap-{start // 40000 + 1}.xml'
            text = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join('<url><loc>' + esc(ORIGIN + p) + '</loc></url>' for p in locations[start:start + 40000]) + '</urlset>'
            if len(text.encode()) > 50 * 1024 * 1024:
                raise ValueError('Sitemap byte limit exceeded')
            (self.out / name).write_text(text)
            sitemap_files.append(name)
        (self.out / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join('<sitemap><loc>' + esc(ORIGIN + BASE + '/' + name) + '</loc></sitemap>' for name in sitemap_files) + '</sitemapindex>')
        (self.out / '.nojekyll').touch()
        (self.out / 'robots.txt').write_text(f'User-agent: *\nAllow: /\nSitemap: {ORIGIN}{BASE}/sitemap.xml\n')
        (self.out / 'README.md').write_text('# HGIS Canada: citable historical census evidence\n\n'
            'This static site is built from the same validated source-cell databases as the current national source RDF. '
            'Geographic bindings, boundary intersections and census continuity groups retain their assessment status. '
            'Candidate matches are not historical-identity assertions.\n\n'
            'Each source workbook provides HTML reporting rows, cell citation anchors, exact RDF downloads and citable JSONL cells. '
            'Published URLs, biographical tables and the separate individual 1881 census pages are preserved.\n\n'
            f'Live site: {ORIGIN}{BASE}/\n\n'
            'Build in the [pipeline repository](https://github.com/jburnford/Canada-History-Knowledge-Graph): '
            '`make rdf-site`, then `make rdf-site-check`. `make deploy` validates the reviewed artifact and publishes this repository.\n\n'
            'See [About](https://jimclifford.ca/hgiscanada/about/) for interpretation and original sources, '
            '[Data](https://jimclifford.ca/hgiscanada/data/) for retrieval guidance, and `data/build-manifest.json` for the edition and checksums.\n')
        self.manifest.update(html_pages=len(self.handled), canonical_indexed_pages=len(self.indexed),
            generator_sha256=self.manifest.get('generator_sha256', sha(Path(__file__))), source_catalog_sha256=sha(self.sources / 'rdf-catalog.json'),
            scope='Source-cell HTML and retrieval records match current source RDF inputs; spatial and identity assessments are qualified supplemental layers; residents and biographies are separate preserved datasets.')
        (self.out / 'data/build-manifest.json').write_text(json.dumps(self.manifest, indent=2) + '\n')
        (self.out / '.site-build-urls.json').write_text(dump(sorted(self.handled)) + '\n')
        print(json.dumps(self.manifest['totals'], indent=2), flush=True)

    def refresh_editorial(self, wikidata=False):
        """Refresh introductions/indexes without rerendering unchanged cells."""
        from _site_urls import sitemap_paths
        self.manifest = json.loads((self.out / 'data/build-manifest.json').read_text())
        if self.manifest['source_catalog_sha256'] != sha(self.sources / 'rdf-catalog.json'):
            raise ValueError('Source RDF edition changed; run a full build')
        if self.manifest['datasets']['residents_1881']['url_inventory_sha256'] != sha(REPO_ROOT / 'data/published_site_urls.csv'):
            raise ValueError('Publication baseline changed; run a full build')
        permitted = {'lod_identity/' + name for name in ['wikidata_associations.csv', 'wikidata_review_queue.csv', 'wikidata_qa_sample.csv', 'manifest.json']} if wikidata else set()
        for rel, expected in self.manifest['supplemental_inputs'].items():
            if rel not in permitted and sha(REPO_ROOT / 'data_quality' / rel) != expected:
                raise ValueError('Supplemental evidence changed; run a full build')
        for e in self.manifest['sources']:
            db_path = self.sources / e['source_key'] / 'source_observations.sqlite'
            if sha(db_path) != e['database_sha256']:
                raise ValueError('Source database changed; run a full build')
            with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True) as db:
                for (prov,) in db.execute('SELECT DISTINCT province FROM reporting_units'):
                    self.province_sources[prov].append((e['source_key'], '', ''))
        for sid, r in self.reps.items():
            self.province_maps[r['province']].append((r['year'], r['name'], self.snapshot_urls[sid]))
        self.handled = set(json.loads((self.out / '.site-build-urls.json').read_text()))
        self.indexed = sitemap_paths(self.out)
        editorial = {p for p in self.handled if p in {BASE + '/', BASE + '/about/', BASE + '/data/'}
                     or (p.startswith(BASE + '/places/') and p.count('/') == 4)}
        refreshed = editorial | (set(self.unit_urls.values()) if wikidata else set())
        self.handled.difference_update(refreshed)
        self.indexed.difference_update(refreshed)
        if wikidata:
            self.copy_evidence()
            self.build_units()
            self.manifest['wikidata_generator_sha256'] = sha(Path(__file__))
            self.manifest['wikidata_policy_sha256'] = sha(REPO_ROOT / 'scripts/_wikidata_links.py')
        self.build_editorial()
        self.manifest['editorial_generator_sha256'] = sha(Path(__file__))
        self.finish()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=REPO_ROOT / 'data_quality/rdf_site')
    ap.add_argument('--sources', type=Path, default=REPO_ROOT / 'data_quality/lod_census_sources')
    ap.add_argument('--identity', type=Path, default=REPO_ROOT / 'data_quality/lod_identity')
    ap.add_argument('--bindings', type=Path, default=REPO_ROOT / 'data_quality/lod_source_bindings')
    ap.add_argument('--published', type=Path, default=CONFIG.hgiscanada_repo)
    refresh = ap.add_mutually_exclusive_group()
    refresh.add_argument('--editorial-only', action='store_true')
    refresh.add_argument('--wikidata-only', action='store_true', help='Refresh Wikidata assessments, unit pages and introductions; require unchanged census and geographic inputs')
    args = ap.parse_args()
    target = args.out.resolve()
    if target in {args.published.resolve(), (REPO_ROOT / 'rag_site').resolve()}:
        raise ValueError('Use an isolated RDF-site output, not the publication or legacy build.')
    if target.exists() and not (target / 'data/build-manifest.json').is_file():
        raise ValueError('Refusing to replace a directory without an RDF-site build manifest')
    if args.editorial_only or args.wikidata_only:
        Builder(target, args.sources, args.identity, args.bindings, args.published).refresh_editorial(wikidata=args.wikidata_only)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=target.name + '.building-', dir=target.parent))
    b = Builder(staging, args.sources, args.identity, args.bindings, args.published)
    b.prepare()
    b.build_sources()
    gis = b.copy_evidence()
    b.build_maps(gis)
    b.build_legacy()
    b.build_editorial()
    b.finish()
    previous = target.with_name(target.name + '.previous')
    if previous.exists():
        if not (previous / 'data/build-manifest.json').is_file():
            raise ValueError('Refusing to remove an unrecognized previous-build directory')
        shutil.rmtree(previous)
    if target.exists():
        target.rename(previous)
    staging.rename(target)
    print(f'Completed isolated build: {target}', flush=True)


if __name__ == '__main__':
    main()
