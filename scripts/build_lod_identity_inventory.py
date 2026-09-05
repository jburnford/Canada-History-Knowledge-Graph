#!/usr/bin/env python3
"""Stage national census identities using explicit spatial/name evidence.

Geometric/name continuity establishes a qualified census reporting chain.
It does not assert that a chain is a historical community or a Wikidata item.
All source areas, including NO DATA, survive in the representation inventory.
"""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from _config import REPO_ROOT
from _normalize import normalize_for_match, suffix_tier
from _wikidata_links import assess_all, sample_key, POLICY_VERSION

YEARS = list(range(1851, 1922, 10))


def external_roles(type_labels):
    """Review categories from cached labels, never automatic CRM/OWL typing."""
    text = type_labels.lower()
    roles = set()
    if 'geographic township' in text or 'survey township' in text:
        roles.add('cadastral_area')
    if any(t in text for t in ['municipality', 'county', 'parish of new brunswick',
                               'province of canada', 'territory of canada']):
        roles.add('administrative_unit')
    if any(re.search(r'\b' + t + r'\b', text) for t in ['city', 'town', 'village', 'hamlet',
                                                       'settlement', 'community', 'locality']):
        roles.add('settlement_or_municipal_entity')
    if 'census division' in text or 'census subdivision' in text:
        roles.add('statistical_unit')
    if 'catholic parish' in text or 'ecclesiastical' in text:
        roles.add('religious_parish_referent_review')
    if any(t in text for t in ['government', 'organization', 'organisation', 'corporation']):
        roles.add('organization')
    if any(re.search(r'\b' + t + r'\b', text) for t in ['island', 'lake', 'river', 'mountain']):
        roles.add('geographic_feature')
    return ';'.join(sorted(roles)) or 'unclassified_referent_review'


def continuity_reason(row):
    if row['involves_no_data']:
        return 'coverage_record_not_identity'
    if row['province_from'] != row['province_to']:
        return 'province_change_requires_review'
    names = [normalize_for_match(row['name_from']), normalize_for_match(row['name_to'])]
    # The audit established this specific spelling variant in Westmeath's
    # stable sequence; do not generalize fuzzy matching to every unit.
    for index, direction in enumerate(['from', 'to']):
        if row[f'id_{direction}'] == 'ON114011' and row[f'year_{direction}'] == 1881 and names[index] == 'wesmeath':
            names[index] = 'westmeath'
    if not names[0] or names[0] != names[1]:
        return 'name_change_requires_review'
    if suffix_tier(row['name_from']) != suffix_tier(row['name_to']):
        return 'entity_tier_change_requires_review'
    if row.get('partition_supported', False):
        return 'supported_continuity_with_area_separation'
    if row['iou'] < .98 or min(row['frac_from'], row['frac_to']) < .98:
        return 'extent_change_requires_review'
    return 'supported_spatial_name_continuity'


def area_separations(table):
    """Evidence for a continuing named unit with separate later reporting areas.

    A majority-retention threshold is an explicit candidate acceptance rule,
    not a definition of historical identity. Loss of less than 2% is still
    recorded: a small town can contain much of the earlier population.
    """
    accepted, records = set(), []
    for _, group in table.groupby('id_from', sort=False):
        candidates = []
        for row in group.to_dict('records'):
            if (row['province_from'] == row['province_to'] and not row['involves_no_data']
                    and normalize_for_match(row['name_from']) == normalize_for_match(row['name_to'])
                    and suffix_tier(row['name_from']) == suffix_tier(row['name_to'])
                    and .5 <= row['frac_from'] < 1 - 1e-6 and row['frac_to'] >= .98):
                candidates.append(row)
        if len(candidates) != 1:
            continue
        retained = candidates[0]
        separate = group[group.id_to.ne(retained['id_to']) & group.material_overlap]
        coverage = float(group.frac_from.sum())
        if separate.empty or not .99 <= coverage <= 1.0001:
            continue
        accepted.add((retained['id_from'], retained['id_to']))
        all_later_inside = bool((group.loc[group.material_overlap, 'frac_to'] >= .9999).all())
        no_coverage_records = not bool(group.involves_no_data.any())
        comparison = ('approximately_common_geography_subject_to_variable_and_source_review'
                      if all_later_inside and no_coverage_records and abs(coverage-1) <= .0001
                      else 'later_totals_require_geographic_reconciliation')
        for part in separate.to_dict('records'):
            records.append(dict(
                id_from=retained['id_from'], continuing_id_to=retained['id_to'],
                separate_id_to=part['id_to'], year_from=retained['year_from'], year_to=retained['year_to'],
                earlier_name=retained['name_from'], continuing_name=retained['name_to'],
                separate_name=part['name_to'], separate_name_tier_hint=suffix_tier(part['name_to']),
                retained_earlier_area_fraction=retained['frac_from'],
                separate_earlier_area_fraction=part['frac_from'],
                separate_later_area_fraction=part['frac_to'],
                overlap_sqm=part['overlap_sqm'], area_crs=part['area_crs'],
                sum_earlier_area_fractions=coverage, involves_coverage_record=bool(part['involves_no_data']),
                comparison_status=comparison, population_apportionment_performed=False,
                evidence_kind='computed_census_area_separation'))
    return accepted, records


def build_components(keys, accepted):
    parent = {key: key for key in keys}
    years = {key: {key[1]} for key in keys}
    def root(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key
    for a, b in accepted:
        ra, rb = root(a), root(b)
        if ra == rb:
            continue
        if years[ra] & years[rb]:
            raise ValueError('Continuity would merge different units in the same census')
        parent[rb] = ra
        years[ra] |= years[rb]
    grouped = defaultdict(list)
    for key in sorted(keys):
        grouped[root(key)].append(key)
    return list(grouped.values())


def read_legacy(level):
    path = REPO_ROOT / ('persistent_places_output/tcpuid_year_to_place.csv' if level == 'csd'
                        else 'persistent_cds_output/cd_id_year_to_chain.csv')
    frame = pd.read_csv(path, keep_default_na=False).rename(columns={
        'tcpuid': 'source_id', 'raw_cd_id': 'source_id',
        'persistent_place_id': 'legacy_unit_id', 'chain_place_id': 'legacy_unit_id'})
    if frame.duplicated(['source_id', 'year']).any():
        raise ValueError(f'Duplicate legacy membership: {path}')
    return frame, path


def stage_level(audit, level):
    legacy, legacy_path = read_legacy(level)
    inventory = []
    inputs = {legacy_path}
    for year in YEARS:
        path = audit / f'{level}_inventory_{year}.csv'
        inputs.add(path)
        frame = pd.read_csv(path, keep_default_na=False).rename(columns={
            'tcpuid' if level == 'csd' else 'cd_id': 'source_id',
            'csd_name' if level == 'csd' else 'cd_name': 'name', 'pr': 'province'})
        if level == 'cd' and 'is_coverage_record' not in frame:
            raise ValueError('CD inventory lacks child-derived coverage status; rerun the GIS audit')
        frame['is_coverage_record'] = (frame['is_coverage_record'].astype(str).str.lower().eq('true')
                                       if 'is_coverage_record' in frame else frame.name.str.strip().str.upper().eq('NO DATA'))
        inventory.extend(frame.assign(year=year, level=level).to_dict('records'))
    members = pd.DataFrame(inventory).merge(legacy, on=['source_id', 'year'], how='left', validate='one_to_one')
    members['legacy_unit_id'] = members.legacy_unit_id.fillna('')
    keys = set(zip(members.loc[~members.is_coverage_record, 'source_id'], members.loc[~members.is_coverage_record, 'year']))
    decisions, accepted, separations = [], [], []
    for y1, y2 in zip(YEARS[:-1], YEARS[1:]):
        path = audit / f'{level}_{y1}_{y2}_correspondences.csv'
        inputs.add(path)
        table = pd.read_csv(path)
        coverage_keys = set(zip(members.loc[members.is_coverage_record, 'source_id'],
                                members.loc[members.is_coverage_record, 'year']))
        table['involves_no_data'] = [((row.id_from, y1) in coverage_keys or (row.id_to, y2) in coverage_keys)
                                      for row in table.itertuples()]
        partition_pairs, partition_records = area_separations(table)
        separations.extend(dict(r, level=level) for r in partition_records)
        for row in table.to_dict('records'):
            # The full GIS crosswalk is retained elsewhere. This table records
            # potential near-equal-extent identity links, including rejections.
            row['partition_supported'] = (row['id_from'], row['id_to']) in partition_pairs
            if row['iou'] < .98 and not row['partition_supported']:
                continue
            reason = continuity_reason(row)
            decisions.append(dict(row, decision=reason, level=level))
            if reason in {'supported_spatial_name_continuity', 'supported_continuity_with_area_separation'}:
                accepted.append(((row['id_from'], y1), (row['id_to'], y2)))
    components = build_components(keys, accepted)
    legacy_groups = {key: set(zip(g.source_id, g.year)) for key, g in legacy.groupby('legacy_unit_id')}
    metadata = members.set_index(['source_id', 'year']).to_dict('index')
    changed_members = {(r['id_from'], r['year_from']) for r in separations} | {
        (r['continuing_id_to'], r['year_to']) for r in separations}
    unit_rows, assignment = [], {}
    for group in components:
        group.sort(key=lambda k: (k[1], k[0]))
        old = {metadata[key]['legacy_unit_id'] for key in group} - {''}
        reused = next(iter(old)) if len(old) == 1 and legacy_groups[next(iter(old))] == set(group) else None
        uid = reused or f'CENSUS_UNIT_{level.upper()}_{group[0][0]}_{group[0][1]}'
        for key in group:
            assignment[key] = uid
        unit_rows.append(dict(unit_id=uid, level=level, canonical_name=metadata[group[-1]]['name'],
                              crm_class='E92_Spacetime_Volume', identity_scope='census_reporting_continuity',
                              identity_basis='spatial_name_continuity' if len(group) > 1 else 'single_census_occurrence',
                              has_recorded_area_separation=bool(set(group) & changed_members),
                              years=';'.join(str(k[1]) for k in group), num_presences=len(group),
                              reused_legacy_identifier=bool(reused)))
        westmeath = {('ON033008', 1851), ('ON096020', 1861), ('ON082003', 1871),
                     ('ON114011', 1881), ('ON114011', 1891), ('ON110012', 1901),
                     ('ON116013', 1911), ('ON142032', 1921)}
        if level == 'csd' and set(group) == westmeath:
            unit_rows[-1].update(crm_class='E4_Period', identity_scope='historical_township',
                                 identity_basis='project_curator_discussion_and_stable_census_sequence')
    members['snapshot_id'] = members.source_id + '_' + members.year.astype(str)
    members['unit_id'] = [assignment.get(k, '') for k in zip(members.source_id, members.year)]
    members['representation_class'] = members.is_coverage_record.map({True: 'E73_Information_Object', False: 'E93_Presence'})
    members['source_name_tier_hint'] = members.name.map(suffix_tier)
    existing_keys = set(zip(members.source_id, members.year))
    missing_legacy = legacy[[key not in existing_keys for key in zip(legacy.source_id, legacy.year)]].assign(level=level)
    return members, pd.DataFrame(unit_rows), pd.DataFrame(decisions), missing_legacy, inputs, separations


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audit', type=Path, default=REPO_ROOT / 'data_quality/gis_audit_equal_area')
    ap.add_argument('--out', type=Path, default=REPO_ROOT / 'data_quality/lod_identity')
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    member_frames, unit_frames, decisions, missing, separations, inputs = [], [], [], [], [], {Path(__file__), REPO_ROOT / 'scripts/_normalize.py'}
    for level in ['csd', 'cd']:
        m, u, d, absent, paths, changes = stage_level(args.audit, level)
        member_frames.append(m); unit_frames.append(u); decisions.append(d); missing.append(absent); inputs |= paths
        separations.extend(changes)
    members, units = pd.concat(member_frames, ignore_index=True), pd.concat(unit_frames, ignore_index=True)
    if units.unit_id.duplicated().any():
        raise ValueError('CSD/CD unit identifier collision')
    members.to_csv(args.out / 'representations.csv', index=False)
    units.to_csv(args.out / 'units.csv', index=False)
    pd.concat(decisions, ignore_index=True).to_csv(args.out / 'continuity_decisions.csv', index=False)
    pd.DataFrame(separations).to_csv(args.out / 'boundary_redistributions.csv', index=False)
    pd.concat(missing, ignore_index=True).to_csv(args.out / 'legacy_members_not_in_gis.csv', index=False)
    redirects = members[members.legacy_unit_id.ne('')][['level', 'legacy_unit_id', 'unit_id', 'snapshot_id', 'is_coverage_record']]
    redirects.to_csv(args.out / 'legacy_identity_crosswalk.csv', index=False)
    by_qid = defaultdict(set)
    for filename in ['csd_verified_matches.jsonl', 'cd_verified_matches.jsonl']:
        path = REPO_ROOT / 'wikidata_grounding' / filename
        inputs.add(path)
        for line in path.open():
            row = json.loads(line)
            if row.get('wikidata_qid') and row.get('status') == 'matched':
                by_qid[row['wikidata_qid']].add(row.get('wikidata_types', ''))
    mapping_path = REPO_ROOT / 'neo4j_cidoc_crm_v2/e53_place_uri.csv'
    inputs.add(mapping_path)
    mappings = pd.read_csv(mapping_path, keep_default_na=False).rename(columns={'place_id:ID': 'legacy_unit_id'})
    mappings = mappings[mappings.wikidata_qid.ne('')]
    mapped = redirects[['level', 'legacy_unit_id', 'unit_id', 'is_coverage_record']].drop_duplicates().merge(
        mappings, on='legacy_unit_id', how='inner', validate='many_to_one')
    mapped['external_type_labels'] = mapped.wikidata_qid.map(lambda q: '; '.join(sorted(by_qid[q] - {''})))
    mapped['referent_roles'] = mapped.external_type_labels.map(external_roles)
    assessments, assessment_inputs = assess_all(mapped, members, REPO_ROOT)
    inputs |= assessment_inputs
    mapped = pd.DataFrame(assessments)
    mapped.to_csv(args.out / 'wikidata_associations.csv', index=False)
    review = mapped[mapped.mapping_status.eq('review_specific_conflict')]
    review.to_csv(args.out / 'wikidata_review_queue.csv', index=False)
    # A bounded, reproducible sample supports QA without requiring individual
    # review of every accepted link. Include each acceptance basis and province.
    provinces = members.drop_duplicates('unit_id').set_index('unit_id').province.to_dict()
    strata = defaultdict(list)
    for row in mapped[mapped.link_accepted].to_dict('records'):
        strata[(row['mapping_status'], provinces.get(row['unit_id'], ''))].append(row)
    sample = [r for key in sorted(strata) for r in sorted(strata[key], key=sample_key)[:3]]
    pd.DataFrame(sample, columns=mapped.columns).to_csv(args.out / 'wikidata_qa_sample.csv', index=False)
    validation = dict(representations=len(members), units=len(units),
                      coverage_records=int(members.is_coverage_record.sum()),
                      duplicate_snapshot_ids=int(members.snapshot_id.duplicated().sum()),
                      missing_identity_subjects=int((~members.is_coverage_record & members.unit_id.eq('')).sum()),
                      legacy_members_not_in_gis=sum(len(f) for f in missing),
                      wikidata_associations=len(mapped),
                      wikidata_link_policy=POLICY_VERSION,
                      wikidata_link_statuses=dict(Counter(mapped.mapping_status)),
                      wikidata_conflict_reasons=dict(Counter(reason for raw in review.review_reasons_json for reason in json.loads(raw))),
                      wikidata_qa_sample=len(sample),
                      reused_legacy_unit_ids=int(units.reused_legacy_identifier.sum()),
                      boundary_redistribution_contributions=len(separations),
                      continuity_decisions=dict(Counter(pd.concat(decisions).decision)),
                      external_referent_roles=dict(Counter(mapped.referent_roles)),
                      scope='Staged census continuity inventory; historical and external referents remain qualified',
                      source_sha256={str(p.relative_to(REPO_ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)})
    (args.out / 'manifest.json').write_text(json.dumps(validation, indent=2) + '\n')
    print(json.dumps({k: v for k, v in validation.items() if k != 'source_sha256'}, indent=2))
    if validation['duplicate_snapshot_ids'] or validation['missing_identity_subjects']:
        raise SystemExit('Identity migration validation failed')


if __name__ == '__main__':
    main()
