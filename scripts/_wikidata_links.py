"""Retain established Wikidata links; review concrete conflicting evidence.

Acceptance is a navigational/reference association, not owl:sameAs between a
Wikidata entity and each census reporting unit. Missing individual review is
not a conflict. Prior verification, historical aliases and overrides survive.
"""
import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path

from _normalize import tier_root, normalize_for_match

PROVINCES = {'ON': 'Ontario', 'QC': 'Quebec', 'NS': 'Nova Scotia', 'NB': 'New Brunswick',
             'MB': 'Manitoba', 'BC': 'British Columbia', 'PE': 'Prince Edward Island',
             'SK': 'Saskatchewan', 'AB': 'Alberta', 'NL': 'Newfoundland',
             'NT': 'Northwest Territories', 'YT': 'Yukon'}
POLICY_VERSION = 'established-links-with-conflict-review-v1'
REASONS = {
    'name_context_conflict': 'The census name differs from the names in the existing Wikidata match.',
    'province_conflict': 'The Wikidata description places the entity in a different province.',
    'township_settlement_conflict': 'The census record describes a township, while Wikidata describes a town or village.',
    'settlement_township_conflict': 'The census record describes a town or village, while Wikidata describes a geographic township.',
    'inherited_identifier_conflict': 'An earlier identifier was linked to different named places; this inherited link needs checking.',
    'geographic_distance_conflict': 'This census area is more than 50 km from the verified location for the linked entity.',
    'historical_date_conflict': 'The Wikidata description gives a founding date later than the census records.',
    'prior_verification_warning': 'The earlier grounding assessment recorded a specific warning for this link.',
}


def root_name(name):
    root = tier_root(str(name or ''))[0]
    root = re.sub(r"\bste?\.?\s+", 'saint ', root)
    root = re.sub(r'\bsainte\b', 'saint', root)
    root = re.sub(r"['’]s\b", '', root)
    root = re.sub(r'[.,]', ' ', root)
    root = re.sub(r'\s+', ' ', root).strip()
    # County qualifiers in Wikidata labels do not distinguish the named county.
    return re.sub(r'\s+(county|census division)$', '', root)


def km(a, b):
    a1, a2, b1, b2 = map(math.radians, (*a, *b))
    h = math.sin((b1-a1)/2)**2 + math.cos(a1)*math.cos(b1)*math.sin((b2-a2)/2)**2
    return 6371 * 2 * math.asin(min(1., math.sqrt(h)))


def province_compatible(source, target, year):
    if source == target:
        return True
    # Historical territory-to-province changes are not namesake conflicts.
    return (source == 'NT' and target in {'AB', 'SK', 'MB', 'YT'} and int(year) < 1912)


def assess(mapping, members, evidence=(), override=None, collision=False, distance=None):
    """Pure decision function; evidence gaps are recorded separately from conflicts."""
    result = dict(mapping_status='accepted_existing_link', link_accepted=True,
                  identity_asserted=False, acceptance_basis='existing_grounding_retained',
                  review_reasons_json='[]', evidence_gaps_json='[]',
                  association_kind='wikidata_reference_link', policy_version=POLICY_VERSION,
                  nearest_verified_location_km='', verification_evidence_json='[]',
                  resolved_reasons_json='[]')
    if str(mapping.get('is_coverage_record', '')).lower() == 'true' or not mapping.get('unit_id'):
        return dict(result, mapping_status='coverage_record_association_not_applied', link_accepted=False,
                    acceptance_basis='coverage_record_not_a_place')
    reasons, gaps = set(), set()
    names = {root_name(r['name']) for r in members} - {''}
    known_names = {root_name(mapping.get('wikidata_label', ''))}
    for e in evidence:
        known_names.update(root_name(e.get(k, '')) for k in ['csd_name', 'cd_name', 'wikidata_label'])
    known_names.discard('')
    direct = [e for e in evidence if e.get('_snapshot_id') in {r['snapshot_id'] for r in members}]
    verified = any(e.get('status') == 'matched' and e.get('match_type', '').startswith('mcp_verified') for e in direct)
    nearby = distance is not None and distance <= 10
    compatible_name = bool(names & known_names)
    if names and known_names and not compatible_name and not nearby:
        reasons.add('name_context_conflict')
    elif names and known_names and not compatible_name:
        gaps.add('historical_name_differs_but_verified_geography_is_nearby')
    if not evidence:
        gaps.add('original_verification_details_unavailable')
    types = mapping.get('external_type_labels', '').lower()
    geographic_township = 'geographic township' in types or 'survey township' in types
    township = geographic_township or 'township municipality' in types
    urban = bool(re.search(r'\b(city|town|village|hamlet)\b', types))
    tiers = {tier_root(r['name'])[1] for r in members}
    if mapping.get('level') == 'csd':
        if 'TOWNSHIP' in tiers and urban and not township:
            reasons.add('township_settlement_conflict')
        if tiers & {'URBAN', 'VILLAGE', 'HAMLET'} and geographic_township and not urban:
            reasons.add('settlement_township_conflict')
    if not types:
        gaps.add('entity_type_unavailable')
    descriptions = ' '.join(e.get('wikidata_desc', '') for e in evidence)
    normalized_description = normalize_for_match(descriptions)
    described_provinces = {code for code, name in PROVINCES.items()
                           if normalize_for_match(name) in normalized_description}
    if described_provinces and not any(province_compatible(r['province'], p, r['year'])
                                      for r in members for p in described_provinces):
        reasons.add('province_conflict')
    if not described_provinces:
        gaps.add('province_not_explicit_in_description')
    # Later municipal incorporation is compatible with an older settlement.
    founding = re.findall(r'\b(?:founded|established)\s+(?:in\s+)?(1[789]\d{2}|20\d{2})\b', descriptions.lower())
    if founding and members and min(map(int, founding)) > max(int(r['year']) for r in members):
        reasons.add('historical_date_conflict')
    if not founding:
        gaps.add('founding_date_not_recorded')
    if collision and not verified and 'name_context_conflict' in reasons:
        reasons.add('inherited_identifier_conflict')
    if distance is not None and distance > 50 and not verified:
        reasons.add('geographic_distance_conflict')
    if distance is None:
        gaps.add('independent_coordinate_comparison_unavailable')
    for e in direct:
        if str(e.get('needs_verify', '')).lower() == 'true' or e.get('match_type') == 'inherit_verified_warn':
            reasons.add('prior_verification_warning')
    # A recorded confirmation applies to this exact unit/QID only. It does not
    # spread through an old chain into unrelated newly separated units.
    if override:
        result.update(mapping_status='accepted_reviewed_link', acceptance_basis=override['evidence'])
        result['resolved_reasons_json'] = json.dumps(sorted(reasons))
    elif reasons:
        result.update(mapping_status='review_specific_conflict', link_accepted=False,
                      acceptance_basis='conflicting_evidence')
    elif verified:
        result.update(mapping_status='accepted_verified_link', acceptance_basis='prior_verification_for_census_member')
    elif evidence and (compatible_name or nearby) and described_provinces and types:
        result.update(mapping_status='accepted_compatible_link', acceptance_basis='existing_verification_and_compatible_context')
    result['review_reasons_json'] = json.dumps(sorted(reasons) if not override else [])
    result['evidence_gaps_json'] = json.dumps(sorted(gaps))
    result['nearest_verified_location_km'] = round(distance, 3) if distance is not None else ''
    result['verification_evidence_json'] = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    return result


def assess_all(mapped, members, repo):
    evidence_by_qid, coordinates = defaultdict(list), {}
    inputs = {Path(__file__), repo / 'data/wikidata_link_confirmations.csv'}
    for filename in ['csd_verified_matches.jsonl', 'cd_verified_matches.jsonl', 'presence_verified_matches.jsonl']:
        path = repo / 'wikidata_grounding' / filename
        inputs.add(path)
        for line in path.open():
            e = json.loads(line)
            if e.get('status') != 'matched' or not e.get('wikidata_qid'):
                continue
            e['_source_file'] = str(path.relative_to(repo))
            e['_snapshot_id'] = e.get('presence_id') or (e.get('csd_id', '') + '_1921' if 'csd_id' in e else '')
            evidence_by_qid[e['wikidata_qid']].append(e)
    for path in sorted((repo / 'neo4j_cidoc_crm_v2').glob('e94_space_primitive_*.csv')):
        inputs.add(path)
        with path.open() as f:
            for r in csv.DictReader(f):
                sid = r.get('space_id:ID', '')
                if sid.endswith('_centroid'):
                    try:
                        coordinates[sid[:-9]] = (float(r['latitude:float']), float(r['longitude:float']))
                    except (KeyError, ValueError):
                        pass
    path = repo / 'wikidata_grounding/qid_collision_audit.csv'
    inputs.add(path)
    with path.open() as f:
        collisions = {r['wikidata_qid'] for r in csv.DictReader(f) if r['verdict'] == 'CONFLICTING-NAMES'}
    with (repo / 'data/wikidata_link_confirmations.csv').open() as f:
        confirmations = {(r['unit_id'], r['wikidata_qid']): r for r in csv.DictReader(f)}
    path = repo / 'wikidata_grounding/csd_chain_qid_xrefs.csv'
    inputs.add(path)
    with path.open() as f:
        prior_overrides = {(r['place_id'], r['qid']): dict(evidence=r['reason'])
                           for r in csv.DictReader(f) if r['decision'] == 'force'}
    grouped = {uid: g.to_dict('records') for uid, g in members[members.unit_id.ne('')].groupby('unit_id')}
    output = []
    for m in mapped.to_dict('records'):
        group = grouped.get(m['unit_id'], [])
        evidence = evidence_by_qid[m['wikidata_qid']]
        # CD verification is attached to the source district identifier, whose
        # historical representations may span several census years.
        attached = []
        for e in evidence:
            if e.get('cd_id') and m['level'] == 'cd':
                attached.extend(dict(e, _snapshot_id=r['snapshot_id']) for r in group if r['source_id'] == e['cd_id'])
            else:
                attached.append(e)
        a = [coordinates[r['snapshot_id']] for r in group if r['snapshot_id'] in coordinates]
        b = [coordinates[e['_snapshot_id']] for e in evidence
             if e.get('match_type', '').startswith('mcp_verified') and e['_snapshot_id'] in coordinates]
        distance = min((km(x, y) for x in a for y in b), default=None)
        confirmation = confirmations.get((m['unit_id'], m['wikidata_qid']))
        # Earlier corrections remain authoritative for unchanged identities;
        # a split-off group receives the ordinary contextual assessment.
        if m['unit_id'] == m['legacy_unit_id']:
            confirmation = confirmation or prior_overrides.get((m['unit_id'], m['wikidata_qid']))
        evaluated = assess(m, group, attached, confirmation,
                           m['wikidata_qid'] in collisions, distance)
        output.append(dict(m, **evaluated))
    return output, inputs


def sample_key(row):
    """Stable sampling for quality control, independent of CSV row order."""
    return hashlib.sha256((row['unit_id'] + '|' + row['wikidata_qid']).encode()).hexdigest()
