"""Historical retrieval contracts: geography, dates, missingness and citations."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_rdf_site import cell_record, cell_html
from validate_rdf_site import SourceTable
from _site_urls import BASE, page_file, sitemap_paths


def inputs():
    source = dict(source_key='1911_TEST', path='/source/1911_TEST.xlsx', sha256='abc', sheet='Table 1')
    unit = dict(unit_id='REPORTING_1911_ROW_2', label='Township 3', province='SK', source_code='SK216003',
                reporting_level='survey_township', excel_row=2)
    obs = dict(observation_id='CELL_1911_TEST_2_6', unit_id=unit['unit_id'], source_cell='Table 1!F2',
        source_column='POP_1901', variable='POP_1901', reference_year=1901, reporting_geography_vintage=1911,
        unit='count', raw_value_json='9007199254740993', numeric_value='9007199254740993', value_status='numeric',
        excel_number_format='0', column_key='F', unit_status='source_definition', reference_period_kind='explicit_column_year',
        reference_period_text='Population in 1901')
    definition = dict(definition='Population in 1901', definition_source_json='{"row": 3}', column_role='statistical')
    return source, unit, obs, definition


def test_retrospective_value_keeps_year_geography_and_exact_precision():
    c = cell_record(*inputs())
    assert c['reference_year'] == 1901 and c['reporting_geography_vintage'] == 1911
    assert c['rdf_decimal'] == '9007199254740993'
    assert c['source_reporting_unit'].endswith('/source-reporting-unit/REPORTING_1911_ROW_2')
    assert 'snapshot' not in c and 'sameAs' not in c
    assert c['citation_url'].endswith('/sources/1911_TEST/rows/2/#cell-F')
    assert c['rdf_id'].endswith('/source-cell/abc/CELL_1911_TEST_2_6')


@pytest.mark.parametrize('status,raw,text', [('source_blank', 'null', 'Blank in source'),
    ('source_text_requires_interpretation', '".."', 'Source text: ..')])
def test_nonnumeric_cells_are_not_zero_or_observations(status, raw, text):
    s, u, o, d = inputs()
    o.update(value_status=status, raw_value_json=raw, numeric_value=None, reference_year=None, unit=None,
             reference_period_kind='reference_period_not_resolved', unit_status='requires_source_interpretation')
    c = cell_record(s, u, o, d)
    assert c['rdf_decimal'] is None
    page = SourceTable('<table>' + cell_html(c) + '</table>')
    rendered = page.cells[o['observation_id']]
    assert rendered['attributes']['data-value'] == ''
    assert rendered['attributes']['data-year'] == ''
    assert text in ''.join(rendered['text'])
    assert 'Reference year unresolved' in ''.join(rendered['text'])
    assert 'Unit unresolved' in ''.join(rendered['text'])


def test_duplicate_column_labels_remain_distinct_source_cells():
    s, u, o, d = inputs()
    a = cell_record(s, u, o, d)
    o.update(observation_id='CELL_1911_TEST_2_7', column_key='G', source_cell='Table 1!G2')
    b = cell_record(s, u, o, d)
    assert a['source_column'] == b['source_column']
    for field in ['rdf_id', 'variable_iri', 'reference_period_iri', 'citation_url']:
        assert a[field] != b[field]


def test_source_text_cannot_inject_markup():
    s, u, o, d = inputs()
    o.update(value_status='source_text_requires_interpretation', numeric_value=None,
             raw_value_json=json.dumps('<script>alert("bad")</script>'))
    d['definition'] = '<img src=x onerror=alert(1)>'
    text = cell_html(cell_record(s, u, o, d))
    assert '<script>' not in text and '<img' not in text
    assert '&lt;script&gt;' in text


def test_accented_url_maps_to_decoded_static_filename(tmp_path):
    path = BASE + '/snapshots/cd/Gasp%C3%A9/'
    assert page_file(tmp_path, path) == tmp_path / 'snapshots/cd/Gaspé/index.html'


def test_large_site_sitemap_index_resolves_children(tmp_path):
    (tmp_path / 'sitemap.xml').write_text('<sitemapindex><sitemap><loc>https://jimclifford.ca/hgiscanada/sitemap-1.xml</loc></sitemap></sitemapindex>')
    (tmp_path / 'sitemap-1.xml').write_text('<urlset><url><loc>https://jimclifford.ca/hgiscanada/sources/</loc></url></urlset>')
    assert sitemap_paths(tmp_path) == {BASE + '/sources/'}
    (tmp_path / 'sitemap-1.xml').write_text('<sitemapindex><sitemap><loc>https://jimclifford.ca/hgiscanada/sitemap.xml</loc></sitemap></sitemapindex>')
    with pytest.raises(ValueError, match='cyclic'):
        sitemap_paths(tmp_path)
