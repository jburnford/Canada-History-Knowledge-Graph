#!/usr/bin/env python3
"""Export staged census source cells as CRM assertions and a data cube.

This source-table graph does not claim that a table unit equals its candidate
GIS match. Numeric observations and blank/text cell records remain distinct.
"""

import argparse
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

from rdflib import Literal, Namespace, RDF, RDFS, XSD

from _config import REPO_ROOT
from _lod_model import CRM, HGIS, PROV, node, number

QB = Namespace('http://purl.org/linked-data/cube#')


def export(database, target):
    db = sqlite3.connect(database)
    db.row_factory = sqlite3.Row
    source = db.execute('SELECT * FROM source').fetchone()
    general = 'source_key' in source.keys()
    scope = source['source_key'] if general else '1911/V1T1'
    document = node('source-table/' + scope + '/' + source['sha256'])
    dataset = node('dataset/' + scope + '/' + source['sha256'])
    structure = node('structure/source-census-observations-v2')
    definitions = {r['column_key']: r for r in db.execute('SELECT * FROM source_columns')} if general else {}
    triple_count = numeric_count = cell_count = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if target.suffix == '.gz' else open
    with opener(target, 'wt', encoding='utf-8') as stream:
        def emit(s, p, o):
            nonlocal triple_count
            stream.write(f'{s.n3()} {p.n3()} {o.n3()} .\n')
            triple_count += 1

        emit(document, RDF.type, CRM.E31_Document)
        emit(document, RDFS.label, Literal(scope + ' source workbook: ' + source['sheet']))
        emit(document, HGIS.sha256, Literal(source['sha256']))
        emit(document, HGIS.sourceWorksheet, Literal(source['sheet']))
        emit(dataset, RDF.type, QB.DataSet)
        emit(dataset, QB.structure, structure)
        emit(dataset, PROV.wasDerivedFrom, document)
        emit(structure, RDF.type, QB.DataStructureDefinition)
        for predicate in [HGIS.reportingUnit, HGIS.variable, HGIS.referencePeriod, HGIS.reportingGeographyVintage]:
            emit(predicate, RDF.type, QB.DimensionProperty)
            component = node('component/' + str(predicate).rsplit('/',1)[-1])
            emit(structure, QB.component, component)
            emit(component, RDF.type, QB.ComponentSpecification)
            emit(component, QB.dimension, predicate)
        emit(HGIS.reportedValue, RDF.type, QB.MeasureProperty)
        component = node('component/reportedValue')
        emit(structure, QB.component, component)
        emit(component, RDF.type, QB.ComponentSpecification)
        emit(component, QB.measure, HGIS.reportedValue)
        for predicate in [HGIS.measurementUnit, HGIS.reportingLevel]:
            emit(predicate, RDF.type, QB.AttributeProperty)
            component = node('component/' + str(predicate).rsplit('/',1)[-1])
            emit(structure, QB.component, component)
            emit(component, RDF.type, QB.ComponentSpecification)
            emit(component, QB.attribute, predicate)
            emit(component, QB.componentRequired, Literal(predicate == HGIS.reportingLevel))
        declared_units, declared_variables, declared_levels = set(), set(), set()
        for row in db.execute('SELECT * FROM survey_units ORDER BY survey_unit_id'):
            survey = node('survey-unit/' + row['survey_unit_id'])
            # This is the source's survey designation. No polygon or modern
            # legal parcel is inferred from its township/range notation.
            emit(survey, RDF.type, CRM.E42_Identifier)
            emit(survey, CRM.P190_has_symbolic_content, Literal(row['survey_unit_id']))
            emit(survey, PROV.wasDerivedFrom, document)
            for col, predicate in [('township', HGIS.surveyTownship), ('range_number', HGIS.surveyRange),
                                   ('meridian', HGIS.surveyMeridian)]:
                emit(survey, predicate, Literal(row[col], datatype=XSD.integer))
            emit(survey, HGIS.meridianDirection, Literal(row['meridian_direction']))
        for row in db.execute('SELECT * FROM reporting_units ORDER BY unit_id'):
            unit = node('source-reporting-unit/' + row['unit_id'])
            record = node('source-row/' + source['sha256'] + '/' + str(row['excel_row']))
            emit(unit, RDF.type, CRM.E92_Spacetime_Volume)
            emit(unit, CRM.P2_has_type, HGIS.SourceReportingUnit)
            emit(unit, RDFS.label, Literal(row['label']))
            emit(unit, HGIS.reportingGeographyVintage, Literal(source['census_vintage'], datatype=XSD.gYear))
            emit(unit, HGIS.spatialBindingStatus, Literal(row['spatial_binding_status']))
            emit(record, RDF.type, CRM.E73_Information_Object)
            emit(record, CRM.P67_refers_to, unit)
            emit(record, PROV.wasDerivedFrom, document)
            emit(record, HGIS.sourceRow, Literal(row['excel_row'], datatype=XSD.integer))
            emit(record, HGIS.sourceMetadata, Literal(row['source_metadata_json']))
            emit(record, HGIS.sourceCode, Literal(row['source_code']))
            if general:
                raw = db.execute('SELECT raw_values_json FROM source_rows WHERE excel_row=?', (row['excel_row'],)).fetchone()
                emit(record, HGIS.originalRowValuesJSON, Literal(raw[0]))
            if row['survey_unit_id']:
                emit(record, HGIS.usesSurveyDesignation, node('survey-unit/' + row['survey_unit_id']))
            if row['candidate_snapshot_id']:
                emit(record, HGIS.candidateCensusSnapshot, node(row['candidate_snapshot_id']))
            level = node('reporting-level/' + row['reporting_level'])
            emit(unit, HGIS.reportingLevel, level)
            if level not in declared_levels:
                emit(level, RDF.type, CRM.E55_Type)
                emit(level, RDFS.label, Literal(row['reporting_level']))
                declared_levels.add(level)
        emit(HGIS.SourceReportingUnit, RDF.type, CRM.E55_Type)
        emit(HGIS.SourceReportingUnit, RDFS.label, Literal('Reporting unit as defined in a census source table'))
        query = '''SELECT o.*, r.reporting_level FROM observations o
                   JOIN reporting_units r USING(unit_id) ORDER BY observation_id'''
        for row in db.execute(query):
            cell_count += 1
            record = node('source-cell/' + source['sha256'] + '/' + row['observation_id'])
            unit = node('source-reporting-unit/' + row['unit_id'])
            column_key = row['column_key'] if general else row['source_column']
            variable = node('source-variable/' + scope + '/' + column_key)
            period = node('reference-period/' + scope + '/' + column_key)
            if variable not in declared_variables:
                emit(variable, RDF.type, CRM.E55_Type)
                emit(variable, RDFS.label, Literal(row['source_column']))
                emit(variable, HGIS.sourceColumn, Literal(row['source_column']))
                emit(variable, PROV.wasDerivedFrom, document)
                emit(period, RDF.type, CRM.E55_Type)
                emit(period, HGIS.referencePeriodKind, Literal(row['reference_period_kind'] if general else 'explicit_column_year'))
                if row['reference_year'] is not None:
                    emit(period, HGIS.referenceYear, Literal(row['reference_year'], datatype=XSD.gYear))
                if general:
                    definition = definitions[column_key]
                    emit(variable, HGIS.sourceColumnPosition, Literal(column_key))
                    emit(variable, HGIS.definitionStatus, Literal('source_definition' if definition['definition'] else 'requires_source_interpretation'))
                    emit(variable, HGIS.unitStatus, Literal(row['unit_status']))
                    emit(variable, HGIS.columnRole, Literal(definition['column_role']))
                    emit(variable, RDFS.comment, Literal(definition['definition']))
                    emit(variable, HGIS.definitionEvidenceJSON, Literal(definition['definition_source_json']))
                    emit(period, HGIS.sourcePeriodDescription, Literal(row['reference_period_text']))
                declared_variables.add(variable)
            emit(record, RDF.type, CRM.E73_Information_Object)
            emit(record, PROV.wasDerivedFrom, document)
            emit(record, HGIS.sourceCell, Literal(row['source_cell']))
            emit(record, HGIS.originalValueJSON, Literal(row['raw_value_json']))
            emit(record, HGIS.valueStatus, Literal(row['value_status']))
            emit(record, HGIS.reportingUnit, unit)
            emit(record, HGIS.variable, variable)
            emit(record, HGIS.referencePeriod, period)
            if row['reference_year'] is not None:
                emit(record, HGIS.referenceYear, Literal(row['reference_year'], datatype=XSD.gYear))
            emit(record, HGIS.reportingGeographyVintage, Literal(row['reporting_geography_vintage'], datatype=XSD.gYear))
            emit(record, HGIS.reportingLevel, node('reporting-level/' + row['reporting_level']))
            if row['value_status'] != 'numeric':
                continue
            numeric_count += 1
            quantity = node('quantity/' + source['sha256'] + '/' + row['observation_id'])
            assignment = node('reported-attribute/' + source['sha256'] + '/' + row['observation_id'])
            measurement_unit = node('unit/' + row['unit']) if row['unit'] else None
            value = number(row['numeric_value'])
            if value is None:
                raise ValueError(f'Numeric source cell is not finite: {row["source_cell"]}')
            if measurement_unit is not None and measurement_unit not in declared_units:
                emit(measurement_unit, RDF.type, CRM.E58_Measurement_Unit)
                emit(measurement_unit, RDFS.label, Literal(row['unit']))
                declared_units.add(measurement_unit)
            emit(record, RDF.type, QB.Observation)
            emit(record, QB.dataSet, dataset)
            emit(record, HGIS.reportedValue, value)
            if measurement_unit is not None:
                emit(record, HGIS.measurementUnit, measurement_unit)
            emit(record, HGIS.documentsAttributeAssignment, assignment)
            emit(assignment, RDF.type, CRM.E13_Attribute_Assignment)
            emit(assignment, CRM.P140_assigned_attribute_to, unit)
            emit(assignment, CRM.P141_assigned, quantity)
            emit(assignment, CRM.P177_assigned_property_of_type, variable)
            emit(assignment, CRM.P16_used_specific_object, record)
            emit(assignment, HGIS.referencePeriod, period)
            if row['reference_year'] is not None:
                emit(assignment, HGIS.referenceYear, Literal(row['reference_year'], datatype=XSD.gYear))
            emit(quantity, RDF.type, CRM.E54_Dimension)
            emit(quantity, CRM.P90_has_value, value)
            if measurement_unit is not None:
                emit(quantity, CRM.P91_has_unit, measurement_unit)
    expected = dict(db.execute('SELECT value_status,COUNT(*) FROM observations GROUP BY value_status').fetchall())
    db.close()
    if numeric_count != expected.get('numeric',0) or cell_count != sum(expected.values()):
        raise ValueError('RDF/source cell reconciliation failed')
    result = dict(source_cells=cell_count, numeric_observations=numeric_count,
                  nonnumeric_cell_records=cell_count-numeric_count, emitted_triples=triple_count,
                  database_sha256=hashlib.sha256(database.read_bytes()).hexdigest(),
                  exporter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  source_scope=scope,
                  status='Staged source graph; candidate GIS bindings are not identity assertions')
    target.with_suffix('.manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',type=Path,default=REPO_ROOT/'data_quality/lod_1911_reporting/source_observations.sqlite')
    ap.add_argument('--out',type=Path,default=REPO_ROOT/'data_quality/lod_1911_reporting/source_observations.nt.gz')
    args = ap.parse_args()
    print(json.dumps(export(args.input,args.out),indent=2))


if __name__ == '__main__':
    main()
