#!/usr/bin/env python3
"""Stream-parse the complete source RDF and reconcile each cell with SQLite."""

import argparse
import gzip
import json
import sqlite3
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from rdflib import Literal, OWL, RDF, XSD
from rdflib.plugins.parsers.ntriples import W3CNTriplesParser

from _lod_model import CRM, HGIS, node
from export_1911_reporting_rdf import QB


def validate(database, rdf):
    tracked = {HGIS.sourceCell:'cell', HGIS.referenceYear:'year',
               HGIS.reportingGeographyVintage:'vintage', HGIS.reportedValue:'value',
               HGIS.measurementUnit:'unit', HGIS.reportingLevel:'level',
               HGIS.valueStatus:'status', HGIS.originalValueJSON:'raw',
               HGIS.reportingUnit:'area', HGIS.documentsAttributeAssignment:'assignment',
               HGIS.variable:'variable', HGIS.referencePeriod:'period'}
    records = defaultdict(dict)
    types, predicates = Counter(), Counter()
    cube_ids, dimension_ids, p90_ids = set(), set(), set()
    quantities, assignment_values, assignment_targets, assignment_sources = {}, {}, {}, {}
    quantity_units, assignment_variables = {}, {}
    period_kinds, period_descriptions = {}, {}
    errors, triple_count = [], 0
    class Sink:
        def triple(self,s,p,o):
            nonlocal triple_count
            triple_count += 1
            predicates[p] += 1
            if p == RDF.type:
                types[o] += 1
                if o == QB.Observation: cube_ids.add(s)
                if o == CRM.E54_Dimension: dimension_ids.add(s)
            # Only source-cell records are retained in memory.
            if '/source-cell/' in str(s) and p in tracked:
                key = tracked[p]
                if key in records[s]:
                    errors.append(f'Duplicate {key} for {s}')
                records[s][key] = str(o)
            if p == CRM.P90_has_value:
                p90_ids.add(s)
                quantities[s] = str(o)
                if not isinstance(o,Literal) or o.datatype not in {XSD.integer,XSD.decimal} or not Decimal(str(o)).is_finite():
                    errors.append(f'Invalid numeric quantity {s}')
            if p == CRM.P141_assigned: assignment_values[s] = o
            if p == CRM.P140_assigned_attribute_to: assignment_targets[s] = o
            if p == CRM.P16_used_specific_object: assignment_sources[s] = o
            if p == CRM.P91_has_unit: quantity_units[s] = o
            if p == CRM.P177_assigned_property_of_type: assignment_variables[s] = o
            if p == HGIS.referencePeriodKind: period_kinds[s] = str(o)
            if p == HGIS.sourcePeriodDescription: period_descriptions[s] = str(o)
    opener = gzip.open if rdf.suffix == '.gz' else open
    with opener(rdf, 'rb') as stream:
        W3CNTriplesParser(Sink()).parse(stream)
    by_cell = {}
    for subject, data in records.items():
        cell = data.get('cell')
        if not cell or cell in by_cell:
            errors.append(f'Missing or duplicate source cell: {cell}')
        by_cell[cell] = (subject, data)
    db = sqlite3.connect(database)
    db.row_factory = sqlite3.Row
    source = db.execute('SELECT * FROM source').fetchone()
    general = 'source_key' in source.keys()
    scope = source['source_key'] if general else '1911/V1T1'
    numeric_count, source_cells = 0, set()
    for row in db.execute('SELECT o.*,r.reporting_level FROM observations o JOIN reporting_units r USING(unit_id)'):
        source_cells.add(row['source_cell'])
        if row['source_cell'] not in by_cell:
            errors.append(f'Missing RDF cell {row["source_cell"]}')
            continue
        subject, data = by_cell[row['source_cell']]
        column_key = row['column_key'] if general else row['source_column']
        expected_period = node('reference-period/' + scope + '/' + column_key)
        expected = {'year':str(row['reference_year']) if row['reference_year'] is not None else None,
                    'vintage':str(row['reporting_geography_vintage']),
                    'status':row['value_status'], 'raw':row['raw_value_json'],
                    'area':str(node('source-reporting-unit/' + row['unit_id'])),
                    'variable':str(node('source-variable/' + scope + '/' + column_key)),
                    'period':str(expected_period)}
        for key,value in expected.items():
            if data.get(key) != value:
                errors.append(f'{row["source_cell"]}: {key} differs from source staging')
        if not data.get('level','').endswith('/' + row['reporting_level']):
            errors.append(f'{row["source_cell"]}: missing reporting level')
        if period_kinds.get(expected_period) != (row['reference_period_kind'] if general else 'explicit_column_year'):
            errors.append(f'{row["source_cell"]}: reference period kind mismatch')
        if general and period_descriptions.get(expected_period) != row['reference_period_text']:
            errors.append(f'{row["source_cell"]}: reference period description mismatch')
        if row['value_status'] == 'numeric':
            numeric_count += 1
            if subject not in cube_ids or 'value' not in data or Decimal(data['value']) != Decimal(row['numeric_value']):
                errors.append(f'{row["source_cell"]}: numeric observation mismatch')
            expected_unit = str(node('unit/' + row['unit'])) if row['unit'] else None
            if data.get('unit') != expected_unit:
                errors.append(f'{row["source_cell"]}: incorrect unit')
            from rdflib import URIRef
            assignment = URIRef(data.get('assignment',''))
            quantity = assignment_values.get(assignment)
            actual_unit = quantity_units.get(quantity)
            if (str(actual_unit) if actual_unit is not None else None) != expected_unit:
                errors.append(f'{row["source_cell"]}: CRM quantity unit mismatch')
            if str(assignment_variables.get(assignment, '')) != expected['variable']:
                errors.append(f'{row["source_cell"]}: CRM variable mismatch')
            if quantity not in quantities or Decimal(quantities[quantity]) != Decimal(row['numeric_value']):
                errors.append(f'{row["source_cell"]}: CRM quantity differs from source/cube value')
            if str(assignment_targets.get(assignment,'')) != expected['area'] or assignment_sources.get(assignment) != subject:
                errors.append(f'{row["source_cell"]}: CRM subject or provenance mismatch')
        elif subject in cube_ids or 'value' in data:
            errors.append(f'{row["source_cell"]}: nonnumeric cell asserted as numeric observation')
    db.close()
    if set(by_cell) != source_cells:
        errors.append('RDF/source cell sets differ')
    if len(cube_ids) != numeric_count or dimension_ids != p90_ids or len(dimension_ids) != numeric_count:
        errors.append('Numeric observation/quantity counts differ')
    if types[CRM.E13_Attribute_Assignment] != numeric_count:
        errors.append('Attribute assignment count differs from numeric observations')
    for forbidden in [CRM.P39_measured,CRM.P132_spatiotemporally_overlaps_with,OWL.sameAs]:
        if predicates[forbidden]: errors.append(f'Unexpected legacy predicate: {forbidden}')
    return dict(parsed_triples=triple_count,source_cells=len(source_cells),
                numeric_observations=numeric_count,errors=errors,
                scope='Complete N-Triples parse and source-cell reconciliation; not full ontology reasoning')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--database',type=Path,required=True)
    ap.add_argument('--rdf',type=Path,required=True)
    args = ap.parse_args()
    result = validate(args.database,args.rdf)
    args.rdf.with_suffix('.validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    if result['errors']: raise SystemExit(1)


if __name__ == '__main__':
    main()
