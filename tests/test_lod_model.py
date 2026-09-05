"""Regression cases for the proposed census model's semantic distinctions."""

import sys
from pathlib import Path

import pytest
from rdflib import Graph, Literal, OWL, RDF, XSD
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from _lod_model import CensusModel, CRM, GEO, HGIS, node, number
from validate_lod_model import validate


def sample():
    model = CensusModel()
    source = model.add_document('source/test', 'Synthetic test source')
    return model, source


def add(model, source, uid, year, name='Test unit', shape=None, **kwargs):
    return model.add_snapshot(uid, year, name, box(-101, 50, -100, 51) if shape is None else shape,
                              f'{year}-06-01', 'https://example.org/date-source', source, **kwargs)


def test_same_extent_can_support_distinct_historical_entities():
    model, source = sample()
    a = add(model, source, 'A', 1911, historical_id='township', identity_source=source)
    b = add(model, source, 'B', 1911, historical_id='county', identity_source=source)
    assert model.graph.value(a, CRM.P161_has_spatial_projection) == model.graph.value(b, CRM.P161_has_spatial_projection)
    assert model.graph.value(a, CRM.P166_was_a_presence_of) != model.graph.value(b, CRM.P166_was_a_presence_of)
    assert not validate(model.graph)


def test_continuing_entity_can_have_different_extents_at_two_censuses():
    model, source = sample()
    a = add(model, source, 'A', 1911, historical_id='township', identity_source=source)
    b = add(model, source, 'B', 1921, shape=box(-101, 50, -99, 51),
            historical_id='township', identity_source=source)
    assert model.graph.value(a, CRM.P166_was_a_presence_of) == model.graph.value(b, CRM.P166_was_a_presence_of)
    assert model.graph.value(a, CRM.P161_has_spatial_projection) != model.graph.value(b, CRM.P161_has_spatial_projection)


def test_census_only_unit_does_not_acquire_identity_from_same_name_and_shape():
    model, source = sample()
    a, b = add(model, source, 'A', 1911), add(model, source, 'B', 1921)
    assert model.graph.value(a, CRM.P166_was_a_presence_of) != model.graph.value(b, CRM.P166_was_a_presence_of)
    assert not list(model.graph.subjects(RDF.type, CRM.E4_Period))


def test_no_data_preserves_geometry_without_population_or_historical_identity():
    model, source = sample()
    a = add(model, source, 'A', 1911, name='NO DATA')
    assert (a, RDF.type, CRM.E73_Information_Object) in model.graph
    assert model.graph.value(a, HGIS.hasSpatialExtent)
    assert not model.graph.value(a, CRM.P166_was_a_presence_of)
    with pytest.raises(ValueError, match='coverage record'):
        model.add_observation(('A', 1911), 'POP', '0', 'persons', [source])
    assert not validate(model.graph)


def test_named_coverage_aggregate_cannot_acquire_population_or_identity():
    model, source = sample()
    a = add(model, source, 'CD_NL_Newfoundland', 1911, name='Newfoundland', is_coverage_record=True)
    assert (a, RDF.type, CRM.E73_Information_Object) in model.graph
    assert model.graph.value(a, HGIS.hasSpatialExtent)
    assert not model.graph.value(a, CRM.P166_was_a_presence_of)
    with pytest.raises(ValueError, match='coverage record'):
        model.add_observation(('CD_NL_Newfoundland', 1911), 'POP', '0', 'persons', [source])
    with pytest.raises(ValueError, match='historical identity'):
        add(model, source, 'Other', 1911, is_coverage_record=True,
            historical_id='Newfoundland', identity_source=source)


def test_many_predecessors_and_successors_are_retained_with_census_dates():
    model, source = sample()
    for uid, year in [('A', 1911), ('B', 1911), ('C', 1921), ('D', 1921)]:
        add(model, source, uid, year)
    metrics = dict(iou=1/3, frac_from=.5, frac_to=.5, overlap_sqm=1000,
                   area_crs='ESRI:102001', material_overlap=True)
    assignments = [model.add_correspondence((a, 1911), (b, 1921), metrics, source)
                   for a in ['A', 'B'] for b in ['C', 'D']]
    assert len(set(assignments)) == 4
    assert all(model.graph.value(a, HGIS.newCensusConfigurationDate) == Literal('1921-06-01', datatype=XSD.date)
               for a in assignments)
    assert not validate(model.graph)


def test_wikidata_mapping_cannot_replace_local_identity():
    model, source = sample()
    a = add(model, source, 'A', 1911)
    mapping = model.add_wikidata_candidate(('A', 1911), 'Q123', source, matched_types='township')
    assert model.graph.value(mapping, CRM.P140_assigned_attribute_to) == a
    assert model.graph.value(mapping, HGIS.mappingStatus) == HGIS.ReferentTypeReviewRequired
    assert not list(model.graph.triples((None, OWL.sameAs, None)))
    assert not validate(model.graph)


@pytest.mark.parametrize('raw', ['.', 'I', '£3 2s', 'NaN', 'Infinity'])
def test_nonnumeric_values_survive_without_invalid_numeric_assertions(raw):
    model, source = sample()
    add(model, source, 'A', 1911)
    assignment = model.add_observation(('A', 1911), 'VALUE', raw, 'unresolved', [source])
    assert model.graph.value(assignment, HGIS.originalValueText) == Literal(raw)
    assert model.graph.value(assignment, HGIS.valueStatus) == HGIS.UnparsedSourceValue
    assert not list(model.graph.triples((None, CRM.P90_has_value, None)))
    assert not validate(model.graph)


def test_numeric_values_preserve_precision_and_density_unit():
    assert str(number('9007199254740993.0')) == '9007199254740993'
    model, source = sample()
    add(model, source, 'A', 1911)
    assignment = model.add_observation(('A', 1911), 'POP_PER_SQ_MI', '12.345',
                                        'persons per square mile', [source])
    value = model.graph.value(assignment, CRM.P141_assigned)
    assert model.graph.value(value, CRM.P90_has_value) == Literal('12.345', datatype=XSD.decimal)
    assert model.graph.value(value, CRM.P91_has_unit) == node('unit/persons per square mile')
    assert not validate(model.graph)


def test_validator_rejects_legacy_range_and_value_errors():
    model, source = sample()
    a = add(model, source, 'A', 1911)
    model.graph.set((a, CRM.P166_was_a_presence_of, model.graph.value(a, CRM.P161_has_spatial_projection)))
    model.graph.add((node('bad-value'), CRM.P90_has_value, Literal('I')))
    errors = validate(model.graph)
    assert any('invalid target type' in e for e in errors)
    assert any('P90' in e for e in errors)


def test_rdf_roundtrip_preserves_the_model():
    model, source = sample()
    add(model, source, 'A', 1911)
    model.add_observation(('A', 1911), 'POP', '12', 'persons', [source])
    graph = Graph().parse(data=model.graph.serialize(format='turtle'), format='turtle')
    assert set(graph) == set(model.graph)
    assert not validate(graph)
