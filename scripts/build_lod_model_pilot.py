#!/usr/bin/env python3
"""Build a reviewable 1911–1921 model specimen from audited project inputs.

Includes every positive incoming correspondence to three 1921 areas:
Westmeath, Regina, and SK187010 (the many-predecessor GIS example).
Observations use existing derived CSVs for this specimen only. A source-table
rebuild and national identity migration remain required before submission.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd
from rdflib import Literal, RDF

from _config import CONFIG, REPO_ROOT
from _gis import load_csd_layer
from _lod_model import CensusModel, CRM, HGIS, PROV, node

DATE_SOURCE = 'https://www66.statcan.gc.ca/eng/1927-28/192701430101_p.%20101.pdf'
TARGETS = {'ON142032', 'SK176022', 'SK187010'}
WESTMEATH = {('ON116013', 1911), ('ON142032', 1921)}


def csv_rows(path):
    with path.open() as stream:
        yield from csv.DictReader(stream)


def add_observations(model, inputs):
    obs = REPO_ROOT / 'neo4j_census_v2'
    definitions_path = obs / 'e55_variable_types.csv'
    inputs.add(definitions_path)
    definitions = {r['type_id:ID']: r for r in csv_rows(definitions_path)}
    documents_path = obs / 'e73_information_objects.csv'
    inputs.add(documents_path)
    documents = {r['info_object_id:ID']: r for r in csv_rows(documents_path)}
    count = 0
    for year in [1911, 1921]:
        eligible = {f'MEAS_{uid}_{year}_{var}': ((uid, year), var)
                    for uid, yr in model.snapshots if yr == year and not model.snapshots[(uid, yr)]['no_data']
                    for var in ['POP_TOT', 'POP_PER_SQ_MI']}
        dimensions_path = obs / f'e54_dimensions_{year}.csv'
        sources_path = obs / f'p70_documents_{year}.csv'
        inputs.update([dimensions_path, sources_path])
        provenance = {}
        for row in csv_rows(sources_path):
            if row[':END_ID'] in eligible:
                provenance.setdefault(row[':END_ID'], set()).add(row[':START_ID'])
        for row in csv_rows(dimensions_path):
            mid = row['dimension_id:ID'].replace('DIM_', 'MEAS_', 1)
            if mid not in eligible:
                continue
            key, variable = eligible[mid]
            sources = []
            for sid in sorted(provenance.get(mid, [])):
                metadata = documents[sid]
                source = model.add_document(sid, metadata['label'])
                model.graph.add((source, HGIS.sourceTable, Literal(metadata['source_table'])))
                model.graph.add((source, HGIS.sourceMetadata, Literal(json.dumps(metadata, sort_keys=True))))
                sources.append(source)
            unit = 'persons per square mile' if variable == 'POP_PER_SQ_MI' else 'persons'
            assignment = model.add_observation(key, variable, row['value:float'] or row['value_string'],
                                               unit, sources,
                                               label=definitions['VAR_' + variable]['label'])
            model.graph.add((assignment, HGIS.provenanceStatus, HGIS.LegacyDerivedTableProvenance))
            model.graph.add((assignment, HGIS.legacyObservationIdentifier, Literal(mid)))
            count += 1
    return count


def add_mappings(model, inputs):
    count = 0
    for filename, year in [('csd_verified_matches.jsonl', 1921),
                           ('presence_verified_matches.jsonl', None)]:
        path = REPO_ROOT / 'wikidata_grounding' / filename
        inputs.add(path)
        source = model.add_document('source/' + filename, filename)
        with path.open() as stream:
            for line in stream:
                row = json.loads(line)
                key = (row.get('csd_id') or row.get('tcpuid'), year or int(row['year']))
                if key not in model.snapshots or not row.get('wikidata_qid') or row.get('status') != 'matched':
                    continue
                assignment = model.add_wikidata_candidate(key, row['wikidata_qid'], source,
                                                          matched_types=row.get('wikidata_types', ''))
                model.graph.add((assignment, HGIS.sourceMappingMetadata, Literal(json.dumps(row, sort_keys=True))))
                count += 1
    return count


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=REPO_ROOT / 'data_quality/lod_model_pilot')
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    audit_path = REPO_ROOT / 'data_quality/gis_audit_equal_area/csd_1911_1921_correspondences.csv'
    audit_report = audit_path.parent / 'report.json'
    inputs = {audit_path, audit_report, Path(__file__), REPO_ROOT / 'scripts/_lod_model.py',
              REPO_ROOT / 'scripts/_gis.py'}
    table = pd.read_csv(audit_path)
    table = table[table.id_to.isin(TARGETS)].copy()
    if set(table.id_to) != TARGETS:
        raise ValueError('Pilot target is absent from the audited correspondence table')
    selected = set(zip(table.id_from, table.year_from)) | set(zip(table.id_to, table.year_to))
    model = CensusModel()
    geometry_source = model.add_document('source/TCP_CANADA_CSD_202306', 'TCP Canada census subdivision geodatabase, 202306')
    identity_source = model.add_document('source/westmeath-pilot-identity-decision',
                                         'Project curator discussion and stable census sequence: Westmeath Township')
    model.graph.add((identity_source, CRM.P3_has_note, Literal(
        'Pilot modelling decision, 2026-09-05: Westmeath is represented as the continuing township; '
        'its census representations have stable names and mapped extents.')))
    print(f'Building {len(selected)} source representations', flush=True)
    for year in [1911, 1921]:
        frame, _ = load_csd_layer(CONFIG.gdb_path, year, 'ESRI:102001')
        ids = {uid for uid, yr in selected if yr == year}
        frame = frame[frame.tcpuid.isin(ids)].to_crs('OGC:CRS84')
        if set(frame.tcpuid) != ids:
            raise ValueError(f'Missing source polygon in {year}')
        for row in frame.itertuples():
            historical = dict(historical_id='historical-unit/westmeath-township',
                              historical_label='Westmeath Township', identity_source=identity_source,
                              historical_type='HistoricalTownship') if (row.tcpuid, year) in WESTMEATH else {}
            model.add_snapshot(row.tcpuid, year, row.csd_name, row.geometry, f'{year}-06-01',
                               DATE_SOURCE, geometry_source, **historical)
    evidence_source = model.add_document('source/albers-csd-1911-1921-audit',
                                         'Audited equal-area CSD correspondences, 1911–1921')
    for row in table.to_dict('records'):
        model.add_correspondence((row['id_from'], row['year_from']),
                                  (row['id_to'], row['year_to']), row, evidence_source)
    observations = add_observations(model, inputs)
    mappings = add_mappings(model, inputs)
    target = args.out / 'model.ttl'
    model.graph.serialize(target, format='turtle')
    table.to_csv(args.out / 'correspondences.csv', index=False)
    manifest = {
        'status': 'model_pilot_not_submission_export',
        'scope': 'All positive incoming spatial correspondences to three selected 1921 CSDs',
        'targets_1921': sorted(TARGETS), 'representations': len(model.snapshots),
        'presences': len(set(model.graph.subjects(RDF.type, CRM.E93_Presence))),
        'coverage_records': sum(r['no_data'] for r in model.snapshots.values()),
        'correspondences': len(table), 'observations': observations, 'mapping_records': mappings,
        'triples': len(model.graph),
        'source_table_rebuild_complete': False,
        'source_sha256': {str(p.relative_to(REPO_ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(inputs)},
        'limitations': ['Legacy derived observations are used only to exercise the model.',
                        'Wikidata associations retain evidence and require referent-type review.',
                        'DLS survey geometries and the national identity migration are not yet included.'],
    }
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({k: v for k, v in manifest.items() if k not in {'source_sha256', 'limitations'}}, indent=2))


if __name__ == '__main__':
    main()
