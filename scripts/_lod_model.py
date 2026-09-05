"""Small CRM/GeoSPARQL model used to validate the staged census migration.

This module does not infer identity, survey boundaries, or missing values.
Project predicates describe census evidence, not municipal change events.
"""

import hashlib
import math
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD
import shapely

CRM = Namespace('http://www.cidoc-crm.org/cidoc-crm/')
GEO = Namespace('http://www.opengis.net/ont/geosparql#')
BASE = Namespace('http://temp.lincsproject.ca/census/')
HGIS = Namespace('http://temp.lincsproject.ca/census/vocab/')
PROV = Namespace('http://www.w3.org/ns/prov#')


def node(identifier):
    return BASE[quote(str(identifier), safe='/_-.' )]


def token(*parts):
    return hashlib.sha256('\0'.join(map(str, parts)).encode()).hexdigest()[:24]


def number(raw):
    """Parse a finite numeric value without repairing ambiguous source text."""
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    if value == value.to_integral_value():
        return Literal(int(value), datatype=XSD.integer)
    return Literal(format(value, 'f'), datatype=XSD.decimal)


class CensusModel:
    def __init__(self):
        self.graph = Graph()
        for prefix, ns in [('crm', CRM), ('geo', GEO), ('base', BASE),
                           ('hgis', HGIS), ('prov', PROV)]:
            self.graph.bind(prefix, ns)
        self.snapshots = {}

    def add_type(self, value, label):
        self.graph.add((value, RDF.type, CRM.E55_Type))
        self.graph.add((value, RDFS.label, Literal(label)))

    def add_document(self, identifier, label):
        subject = node(identifier)
        self.graph.add((subject, RDF.type, CRM.E31_Document))
        self.graph.add((subject, RDFS.label, Literal(label)))
        return subject

    def add_snapshot(self, uid, year, name, geometry, reference_date, date_source,
                     source, *, historical_id=None, historical_label=None,
                     identity_source=None, historical_type='HistoricalAdministrativeUnit',
                     is_coverage_record=False):
        """geometry is an unsimplified polygon in OGC CRS84 (longitude, latitude)."""
        key = (uid, year)
        if key in self.snapshots:
            raise ValueError(f'Duplicate census snapshot: {key}')
        if geometry.geom_type not in {'Polygon', 'MultiPolygon'} or not geometry.is_valid or geometry.is_empty:
            raise ValueError('A census extent requires a valid nonempty polygon')
        if historical_id and not identity_source:
            raise ValueError('Historical identity requires an explicit evidence source')
        no_data = is_coverage_record or name.strip().upper() == 'NO DATA'
        if no_data and historical_id:
            raise ValueError('NO DATA cannot acquire historical identity by default')
        g = self.graph
        subject = node(f'{uid}_{year}')
        geometry = shapely.normalize(geometry)
        extent = node('extent/' + token(shapely.to_wkb(geometry).hex(), 'OGC:CRS84'))
        geom_node = URIRef(str(extent) + '/geometry')
        g.add((extent, RDF.type, CRM.E53_Place))
        g.add((extent, RDF.type, GEO.Feature))
        g.add((extent, GEO.hasGeometry, geom_node))
        g.add((geom_node, RDF.type, GEO.Geometry))
        wkt = Literal('<http://www.opengis.net/def/crs/OGC/1.3/CRS84> ' +
                      shapely.to_wkt(geometry, rounding_precision=-1), datatype=GEO.wktLiteral)
        g.add((geom_node, GEO.asWKT, wkt))
        g.add((extent, CRM.P168_place_is_defined_by, wkt))
        g.add((geom_node, PROV.wasDerivedFrom, source))
        g.add((subject, RDFS.label, Literal(f'{name} ({year} census representation)')))
        g.add((subject, HGIS.censusVintage, Literal(year, datatype=XSD.gYear)))
        g.add((subject, HGIS.hasSpatialExtent, extent))
        g.add((subject, PROV.wasDerivedFrom, source))
        timespan = node('reference-date/' + reference_date)
        g.add((timespan, RDF.type, CRM['E52_Time-Span']))
        g.add((timespan, CRM.P82a_begin_of_the_begin, Literal(reference_date, datatype=XSD.date)))
        g.add((timespan, CRM.P82b_end_of_the_end, Literal(reference_date, datatype=XSD.date)))
        g.add((timespan, PROV.wasDerivedFrom, URIRef(date_source)))
        g.add((subject, HGIS.referenceTimespan, timespan))
        if no_data:
            g.add((subject, RDF.type, CRM.E73_Information_Object))
            g.add((subject, CRM.P67_refers_to, extent))
            g.add((subject, CRM.P2_has_type, HGIS.CoverageRecord))
            self.add_type(HGIS.CoverageRecord, 'Source map coverage record')
            g.add((subject, HGIS.coverageStatus, HGIS.UnresolvedNoData))
        else:
            phenomenon = node(historical_id or f'reporting-unit/{uid}_{year}')
            g.add((phenomenon, RDF.type, CRM.E4_Period if historical_id else CRM.E92_Spacetime_Volume))
            g.add((phenomenon, RDFS.label, Literal(historical_label or name)))
            kind = HGIS[historical_type] if historical_id else HGIS.CensusDefinedUnit
            g.add((phenomenon, CRM.P2_has_type, kind))
            self.add_type(kind, historical_type if historical_id else 'Census-defined reporting unit')
            if identity_source:
                g.add((phenomenon, PROV.wasDerivedFrom, identity_source))
                g.add((subject, HGIS.identityEvidence, identity_source))
            g.add((subject, RDF.type, CRM.E93_Presence))
            g.add((subject, CRM.P166_was_a_presence_of, phenomenon))
            g.add((subject, CRM.P164_is_temporally_specified_by, timespan))
            g.add((subject, CRM.P161_has_spatial_projection, extent))
        self.snapshots[key] = dict(subject=subject, extent=extent, timespan=timespan,
                                   no_data=no_data, reference_date=reference_date)
        return subject

    def add_correspondence(self, earlier, later, metrics, source):
        if earlier[1] >= later[1]:
            raise ValueError('Census correspondence must point to a later census')
        a, b = self.snapshots[earlier], self.snapshots[later]
        values = {key: float(metrics[key]) for key in ['iou', 'frac_from', 'frac_to', 'overlap_sqm']}
        if not all(math.isfinite(v) and v > 0 for v in values.values()):
            raise ValueError('Correspondence requires finite positive evidence')
        if any(values[k] > 1 + 1e-9 for k in ['iou', 'frac_from', 'frac_to']):
            raise ValueError('Overlap fractions cannot exceed one')
        if not metrics.get('area_crs'):
            raise ValueError('Correspondence requires its area CRS')
        g = self.graph
        assessment = node('correspondence/' + token(*earlier, *later, metrics['area_crs']))
        g.add((assessment, RDF.type, CRM.E13_Attribute_Assignment))
        g.add((assessment, CRM.P2_has_type, HGIS.ComputedCensusCorrespondence))
        self.add_type(HGIS.ComputedCensusCorrespondence, 'Computed correspondence between census configurations')
        g.add((assessment, CRM.P140_assigned_attribute_to, a['subject']))
        g.add((assessment, CRM.P141_assigned, b['subject']))
        g.add((assessment, CRM.P177_assigned_property_of_type, HGIS.HasSpatialCounterpartInLaterCensus))
        self.add_type(HGIS.HasSpatialCounterpartInLaterCensus, 'Has spatial counterpart in later census')
        g.add((assessment, CRM.P16_used_specific_object, source))
        g.add((assessment, HGIS.earlierReferenceTimespan, a['timespan']))
        g.add((assessment, HGIS.laterReferenceTimespan, b['timespan']))
        g.add((assessment, HGIS.newCensusConfigurationDate,
               Literal(b['reference_date'], datatype=XSD.date)))
        for key, predicate in [('iou', HGIS.intersectionOverUnion), ('frac_from', HGIS.earlierAreaFraction),
                               ('frac_to', HGIS.laterAreaFraction), ('overlap_sqm', HGIS.intersectionSquareMetres)]:
            g.add((assessment, predicate, number(metrics[key])))
        g.add((assessment, HGIS.areaCRS, Literal(metrics['area_crs'])))
        g.add((assessment, HGIS.materialOverlap, Literal(bool(metrics['material_overlap']))))
        g.add((assessment, HGIS.involvesCoverageRecord, Literal(a['no_data'] or b['no_data'])))
        return assessment

    def add_wikidata_candidate(self, key, qid, source, *, matched_types=''):
        """Retain existing grounding evidence without asserting entity identity."""
        import re
        if not re.fullmatch(r'Q[1-9][0-9]*', qid):
            raise ValueError('Invalid Wikidata QID')
        subject = self.snapshots[key]['subject']
        assignment = node('mapping/' + token(subject, qid))
        g = self.graph
        g.add((assignment, RDF.type, CRM.E13_Attribute_Assignment))
        g.add((assignment, CRM.P140_assigned_attribute_to, subject))
        g.add((assignment, CRM.P141_assigned, URIRef('http://www.wikidata.org/entity/' + qid)))
        g.add((assignment, CRM.P177_assigned_property_of_type, HGIS.CandidateExternalAssociation))
        self.add_type(HGIS.CandidateExternalAssociation, 'Candidate association to an external entity')
        g.add((assignment, CRM.P16_used_specific_object, source))
        g.add((assignment, HGIS.mappingStatus, HGIS.ReferentTypeReviewRequired))
        if matched_types:
            g.add((assignment, HGIS.sourceEntityTypes, Literal(matched_types)))
        return assignment

    def add_observation(self, key, variable, raw, unit, sources, *, label=None):
        snapshot = self.snapshots[key]
        if snapshot['no_data']:
            raise ValueError('A coverage record is not a census observation subject')
        if not sources:
            raise ValueError('A reported census value requires source provenance')
        g = self.graph
        assignment = node('assertion/' + token(*key, variable, *sorted(map(str, sources))))
        value = URIRef(str(assignment) + '/value')
        var_type = node('variable/' + variable)
        self.add_type(var_type, label or variable)
        g.add((assignment, RDF.type, CRM.E13_Attribute_Assignment))
        g.add((assignment, CRM.P140_assigned_attribute_to, snapshot['subject']))
        g.add((assignment, CRM.P141_assigned, value))
        g.add((assignment, CRM.P177_assigned_property_of_type, var_type))
        g.add((assignment, HGIS.referenceTimespan, snapshot['timespan']))
        g.add((assignment, HGIS.originalValueText, Literal(str(raw))))
        for source in sources:
            g.add((assignment, CRM.P16_used_specific_object, source))
        numeric = number(raw)
        if numeric is None:
            g.add((value, RDF.type, CRM.E73_Information_Object))
            g.add((value, CRM.P190_has_symbolic_content, Literal(str(raw))))
            g.add((assignment, HGIS.valueStatus, HGIS.UnparsedSourceValue))
        else:
            g.add((value, RDF.type, CRM.E54_Dimension))
            g.add((value, CRM.P90_has_value, numeric))
            unit_node = node('unit/' + unit)
            g.add((unit_node, RDF.type, CRM.E58_Measurement_Unit))
            g.add((unit_node, RDFS.label, Literal(unit)))
            g.add((value, CRM.P91_has_unit, unit_node))
            g.add((assignment, HGIS.valueStatus, HGIS.NumericReportedValue))
        return assignment
