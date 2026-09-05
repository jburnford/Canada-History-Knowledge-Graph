#!/usr/bin/env python3
"""Targeted acceptance checks for the staged census model, not a full CRM reasoner."""

import argparse
import json
from decimal import Decimal
from pathlib import Path

from rdflib import Graph, Literal, OWL, RDF, XSD
from shapely import from_wkt

from _lod_model import CRM, GEO, HGIS


def validate(graph):
    errors = []
    def require(condition, message):
        if not condition:
            errors.append(message)

    for presence in graph.subjects(RDF.type, CRM.E93_Presence):
        for predicate, types in [
            (CRM.P166_was_a_presence_of, {CRM.E92_Spacetime_Volume, CRM.E4_Period}),
            (CRM.P164_is_temporally_specified_by, {CRM['E52_Time-Span']}),
            (CRM.P161_has_spatial_projection, {CRM.E53_Place}),
        ]:
            values = set(graph.objects(presence, predicate))
            require(len(values) == 1, f'{presence}: expected one {predicate}')
            for value in values:
                require(bool(types & set(graph.objects(value, RDF.type))),
                        f'{presence}: invalid target type for {predicate}')
    for extent in graph.subjects(RDF.type, CRM.E53_Place):
        geometries = set(graph.objects(extent, GEO.hasGeometry))
        require(bool(geometries), f'{extent}: missing polygon geometry')
        for geometry in geometries:
            literals = list(graph.objects(geometry, GEO.asWKT))
            require(len(literals) == 1, f'{geometry}: expected one WKT representation')
            for literal in literals:
                try:
                    shape = from_wkt(str(literal).split('> ', 1)[-1])
                    require(literal.datatype == GEO.wktLiteral and shape.is_valid and not shape.is_empty
                            and shape.geom_type in {'Polygon', 'MultiPolygon'}, f'{geometry}: invalid polygon')
                except Exception:
                    errors.append(f'{geometry}: unparseable geometry')
    for subject, value in graph.subject_objects(CRM.P90_has_value):
        numeric = isinstance(value, Literal) and value.datatype in {XSD.integer, XSD.decimal, XSD.double, XSD.float}
        if numeric:
            try:
                numeric = Decimal(str(value)).is_finite()
            except Exception:
                numeric = False
        require(numeric, f'{subject}: P90 requires a finite numeric literal')
    for subject in graph.subjects(CRM.P2_has_type, HGIS.CoverageRecord):
        require((subject, RDF.type, CRM.E93_Presence) not in graph,
                f'{subject}: coverage record misclassified as census presence')
        require(not list(graph.objects(subject, CRM.P166_was_a_presence_of)),
                f'{subject}: unsupported persistent identity on coverage record')
    for assignment in graph.subjects(RDF.type, CRM.E13_Attribute_Assignment):
        for predicate in [CRM.P140_assigned_attribute_to, CRM.P141_assigned,
                          CRM.P177_assigned_property_of_type]:
            require(len(set(graph.objects(assignment, predicate))) == 1,
                    f'{assignment}: expected one {predicate} in this model')
        require(bool(list(graph.objects(assignment, CRM.P16_used_specific_object))),
                f'{assignment}: missing source provenance')
        if list(graph.objects(assignment, HGIS.originalValueText)):
            targets = list(graph.objects(assignment, CRM.P140_assigned_attribute_to))
            require(all((t, RDF.type, CRM.E93_Presence) in graph for t in targets),
                    f'{assignment}: observation targets a non-census coverage record')
    for assignment in graph.subjects(CRM.P177_assigned_property_of_type, HGIS.HasSpatialCounterpartInLaterCensus):
        earlier = list(graph.objects(assignment, CRM.P140_assigned_attribute_to))
        later = list(graph.objects(assignment, CRM.P141_assigned))
        if len(earlier) == len(later) == 1:
            y1 = graph.value(earlier[0], HGIS.censusVintage)
            y2 = graph.value(later[0], HGIS.censusVintage)
            require(y1 is not None and y2 is not None and int(str(y1)) < int(str(y2)),
                    f'{assignment}: invalid census direction')
            later_span = graph.value(later[0], HGIS.referenceTimespan)
            expected = graph.value(later_span, CRM.P82a_begin_of_the_begin) if later_span else None
            require(expected is not None and graph.value(assignment, HGIS.newCensusConfigurationDate) == expected,
                    f'{assignment}: new configuration date does not match the later census')
    for predicate in [CRM.P132_spatiotemporally_overlaps_with, CRM.P39_measured,
                      CRM.P40_observed_dimension, OWL.sameAs]:
        require(not list(graph.triples((None, predicate, None))), f'Unexpected legacy assertion: {predicate}')
    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('rdf', type=Path)
    args = ap.parse_args()
    graph = Graph().parse(args.rdf, format='turtle')
    errors = validate(graph)
    result = {'triples': len(graph), 'errors': errors,
              'scope': 'Targeted census model checks; not complete ontology or source-data validation'}
    (args.rdf.parent / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
