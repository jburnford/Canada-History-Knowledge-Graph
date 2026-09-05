"""Established links survive; independent conflicting evidence is actionable."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from _wikidata_links import assess, km
from build_rdf_site import wikidata_html


def fixture(name='Westmeath', types='geographic township of Ontario'):
    mapping = dict(unit_id='PLACE_ON142032', legacy_unit_id='PLACE_ON142032', level='csd',
                   wikidata_qid='Q115263132', wikidata_label='Westmeath', external_type_labels=types)
    members = [dict(snapshot_id='ON142032_1921', name=name, province='ON', year='1921')]
    evidence = [dict(_snapshot_id='ON142032_1921', csd_name='Westmeath', wikidata_label='Westmeath',
                     wikidata_desc='geographic township in Ontario, Canada', status='matched', match_type='mcp_verified')]
    return mapping, members, evidence


def test_prior_verification_and_repeated_census_links_remain_accepted():
    m, group, evidence = fixture()
    for year in ['1851', '1921']:
        group[0]['year'] = year
        result = assess(m, group, evidence, collision=True)
        assert result['mapping_status'] == 'accepted_verified_link'
        assert result['link_accepted'] and not result['identity_asserted']


def test_missing_metadata_is_an_evidence_gap_not_a_conflict():
    m, group, _ = fixture(types='')
    result = assess(m, group)
    assert result['mapping_status'] == 'accepted_existing_link'
    assert json.loads(result['evidence_gaps_json'])
    assert result['review_reasons_json'] == '[]'


def test_verified_alias_is_not_a_name_collision():
    m, group, evidence = fixture(name='Old Name')
    evidence[0].update(csd_name='Old Name', _snapshot_id='another_1921')
    result = assess(m, group, evidence, collision=True)
    assert result['mapping_status'] == 'accepted_compatible_link'


def test_historical_spelling_or_rename_with_nearby_grounding_is_retained():
    m, group, evidence = fixture(name='Wesmeath')
    evidence[0]['_snapshot_id'] = 'another_1921'
    result = assess(m, group, evidence, collision=True, distance=.2)
    assert result['mapping_status'] == 'accepted_compatible_link'
    assert 'historical_name_differs_but_verified_geography_is_nearby' in result['evidence_gaps_json']


def test_incorporation_and_historical_province_changes_are_compatible():
    m, group, evidence = fixture()
    group[0].update(province='NT', year='1891')
    evidence[0]['wikidata_desc'] = 'town in Alberta, incorporated in 1950'
    assert assess(m, group, evidence)['link_accepted']


def test_town_and_geographic_township_conflict_is_explained():
    m, group, evidence = fixture(name='Westmeath Village')
    result = assess(m, group, evidence)
    assert not result['link_accepted']
    assert 'settlement_township_conflict' in json.loads(result['review_reasons_json'])
    page = wikidata_html([dict(m, **{k: str(v) for k, v in result.items()})])
    assert 'needing clarification' in page and 'geographic township' in page
    assert 'settlement_township_conflict' not in page


def test_inherited_distant_namesake_requires_review():
    m, group, evidence = fixture()
    evidence[0]['_snapshot_id'] = 'another_1921'
    result = assess(m, group, evidence, distance=250)
    assert result['mapping_status'] == 'review_specific_conflict'
    assert 'geographic_distance_conflict' in json.loads(result['review_reasons_json'])
    assert 110 < km((0, 0), (1, 0)) < 112


def test_confirmation_keeps_resolved_evidence_and_plain_public_link():
    m, group, evidence = fixture(name='Westmeath Village')
    result = assess(m, group, evidence, override={'evidence': 'Confirmed for this unit/QID'})
    assert result['mapping_status'] == 'accepted_reviewed_link'
    assert json.loads(result['resolved_reasons_json'])
    page = wikidata_html([dict(m, **{k: str(v) for k, v in result.items()})])
    assert '<h2>Wikidata</h2>' in page and 'Q115263132' in page
    assert all(term not in page for term in ['candidate', 'False', 'accepted_reviewed_link', 'sameAs'])
    assert not assess(m, group, evidence)['link_accepted']


def test_public_wikidata_labels_are_escaped():
    m, group, evidence = fixture()
    m['wikidata_label'] = '<script>bad</script>'
    page = wikidata_html([dict(m, link_accepted='True')])
    assert '<script>' not in page and '&lt;script&gt;' in page
