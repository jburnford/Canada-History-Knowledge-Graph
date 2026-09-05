"""Source preservation and identity migration regression cases."""

import csv
import sqlite3
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_lod_identity_inventory import build_components, continuity_reason, external_roles, area_separations
from stage_1911_reporting_units import column_definition, parse_dls, stage


def pair(**changes):
    row = dict(id_from='A', id_to='B', year_from=1911, year_to=1921,
               name_from='Oakland', name_to='Oakland', province_from='ON', province_to='ON',
               iou=1., frac_from=1., frac_to=1., involves_no_data=False)
    return dict(row, **changes)


def test_matching_geometry_alone_does_not_establish_identity():
    assert continuity_reason(pair()) == 'supported_spatial_name_continuity'
    assert continuity_reason(pair(name_to='Different unit')) == 'name_change_requires_review'
    assert continuity_reason(pair(involves_no_data=True)) == 'coverage_record_not_identity'
    assert continuity_reason(pair(province_to='QC')) == 'province_change_requires_review'


def test_westmeath_typo_exception_is_limited_to_the_audited_record():
    row = pair(id_from='ON114011', year_from=1881, name_from='Wesmeath', name_to='Westmeath')
    assert continuity_reason(row) == 'supported_spatial_name_continuity'
    assert continuity_reason(dict(row, id_from='OTHER')) == 'name_change_requires_review'


def test_components_cannot_conflate_concurrent_units():
    a, b, c = ('A', 1911), ('B', 1911), ('C', 1921)
    with pytest.raises(ValueError, match='same census'):
        build_components([a,b,c], [(a,c),(b,c)])


def test_geographic_township_is_distinguished_from_municipality():
    assert external_roles('geographic township of Ontario') == 'cadastral_area'
    assert external_roles('township municipality in Ontario') == 'administrative_unit'
    assert external_roles('Catholic parish') == 'religious_parish_referent_review'
    assert external_roles('city; single-tier municipality') == 'administrative_unit;settlement_or_municipal_entity'


def test_dls_identifiers_keep_range_meridian_and_direction():
    a = parse_dls('T24 R1 MW3')
    b = parse_dls('T24 R1 ME3')
    assert a['survey_unit_id'] != b['survey_unit_id']
    assert a['township'] == 24 and a['meridian'] == 3
    assert parse_dls('T 24 R 1 M W 3') == a
    assert parse_dls('Part of T24 R1 MW3') is None
    assert parse_dls('T24 R1 MW3 and T25 R1 MW3') is None


def test_previous_year_column_and_density_units_remain_explicit():
    assert column_definition('POP_1901') == ('POP',1901,'persons')
    assert column_definition('POP_PER_SQ_MI_1911') == ('POP_PER_SQ_MI',1911,'persons per square mile')
    with pytest.raises(ValueError):
        column_definition('UNKNOWN_1911')


def test_source_cells_survive_code_collision_aggregates_and_missing_values(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'TEST_1911'
    sheet.append(['ROW_ID','V1T1_1911','PR','CD_NO','CSD_NO','PR_CD_CSD',
                  'AREA_ACRES_1911','AREA_SQ_MI_1911','POP_M_1911','POP_F_1911',
                  'POP_TOT_1911','POP_PER_SQ_MI_1911','POP_1901','NOTES'])
    sheet.append([1,'CA000000','CA',0,0,'Canada',640,1,7,5,12,12,9,'Source note'])
    sheet.append([2,'SK216003','SK',216,3,'T24 R1 MW3',640,1,7,5,12,12,9,None])
    sheet.append([3,'SK999001','SK',999,1,'Unmatched',None,None,None,None,0,None,'.',None])
    sheet.append([4,'SK999002','SK',999,2,'Formula',None,None,None,None,'=1+1',None,None,None])
    path = tmp_path / 'source.xlsx'; workbook.save(path)
    crosswalk = tmp_path / 'crosswalk.csv'
    crosswalk.write_text('v1t1_code,tcpuid,pr\n')
    inventory = tmp_path / 'inventory.csv'
    inventory.write_text('tcpuid,csd_name\nSK216003,Saskatoon c\n')
    out = tmp_path / 'out'
    result = stage(path,crosswalk,inventory,out)
    assert result['reporting_rows'] == 4 and result['preserved_cells'] == 28
    assert result['missing_cells'] == 0 and result['foreign_key_errors'] == []
    assert result['reporting_levels']['country_total'] == 1
    assert result['same_code_different_name_review'] == 1
    connection = sqlite3.connect(out/'source_observations.sqlite')
    row = connection.execute("SELECT candidate_snapshot_id,survey_unit_id FROM reporting_units WHERE source_code='SK216003'").fetchone()
    assert row == ('','DLS_T24_R1_W3')
    previous = connection.execute("SELECT reference_year,reporting_geography_vintage,numeric_value FROM observations WHERE source_cell='TEST_1911!M3'").fetchone()
    assert previous == (1901,1911,'9')
    assert connection.execute("SELECT numeric_value,value_status FROM observations WHERE source_cell='TEST_1911!K4'").fetchone() == ('0','numeric')
    assert connection.execute("SELECT numeric_value,value_status FROM observations WHERE source_cell='TEST_1911!G4'").fetchone() == (None,'source_blank')
    assert connection.execute("SELECT value_status FROM observations WHERE source_cell='TEST_1911!K5'").fetchone()[0] == 'source_formula_requires_evaluation'
    assert connection.execute("SELECT value_status FROM observations WHERE source_cell='TEST_1911!M4'").fetchone()[0] == 'source_text_requires_interpretation'
    connection.close()
    from export_1911_reporting_rdf import export, QB
    from _lod_model import HGIS, CRM
    from rdflib import Graph, RDF, Literal, XSD
    output = out / 'source.nt'
    exported = export(out/'source_observations.sqlite', output)
    graph = Graph().parse(output, format='nt')
    assert exported['source_cells'] == 28
    assert len(set(graph.subjects(RDF.type,QB.Observation))) == 15
    assert len(set(graph.subjects(HGIS.sourceCell,None))) == 28
    previous = next(graph.subjects(HGIS.sourceCell,Literal('TEST_1911!M3')))
    assert graph.value(previous,HGIS.referenceYear) == Literal('1901',datatype=XSD.gYear)
    assert graph.value(previous,HGIS.reportingGeographyVintage) == Literal('1911',datatype=XSD.gYear)
    assert not list(graph.triples((None,CRM.P39_measured,None)))
    from validate_reporting_rdf import validate
    assert validate(out/'source_observations.sqlite',output)['errors'] == []
    quantity = next(graph.subjects(CRM.P90_has_value,None))
    graph.set((quantity,CRM.P90_has_value,Literal(999999,datatype=XSD.integer)))
    graph.serialize(output,format='nt',encoding='utf-8')
    assert any('CRM quantity differs' in error for error in validate(out/'source_observations.sqlite',output)['errors'])


@pytest.mark.parametrize('retained_fraction',[.9,.995])
def test_township_continues_after_separate_town_is_reported(retained_fraction):
    import pandas as pd
    base = dict(year_from=1851,year_to=1861,id_from='TWP',name_from='Saugeen',
                province_from='ON',province_to='ON',involves_no_data=False,
                material_overlap=True,area_crs='ESRI:102001',frac_to=1.)
    remainder = dict(base,id_to='TWP_NEXT',name_to='Saugeen',frac_from=retained_fraction,
                     iou=retained_fraction,overlap_sqm=retained_fraction*1000000)
    town = dict(base,id_to='TOWN',name_to='Southampton, Village',frac_from=1-retained_fraction,
                iou=1-retained_fraction,overlap_sqm=(1-retained_fraction)*1000000)
    accepted, records = area_separations(pd.DataFrame([remainder,town]))
    assert accepted == {('TWP','TWP_NEXT')}
    assert continuity_reason(dict(remainder,partition_supported=True)) == 'supported_continuity_with_area_separation'
    assert records[0]['separate_id_to'] == 'TOWN'
    assert not records[0]['population_apportionment_performed']
    assert records[0]['comparison_status'].startswith('approximately_common_geography')
    # If the receiving town extends outside the former township, its whole
    # population cannot simply be added to the later township population.
    town['frac_to'] = .4
    _, records = area_separations(pd.DataFrame([remainder,town]))
    assert records[0]['comparison_status'] == 'later_totals_require_geographic_reconciliation'
