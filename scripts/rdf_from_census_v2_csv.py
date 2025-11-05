#!/usr/bin/env python3
"""
Generate RDF from neo4j_census_v2/ CIDOC-CRM CSV files.

Converts 666,423 census measurements (1851-1901) from Neo4j CSV format to RDF Turtle.
Complements the spatial/temporal RDF from rdf_from_cidoc_csv.py.

Usage:
    python3 scripts/rdf_from_census_v2_csv.py \
        --csv-dir neo4j_census_v2 \
        --base https://canada.census.example.org/ \
        --out generated/canada/canada_observations_1851_1901.ttl
"""

import argparse
import csv
from pathlib import Path
from typing import Dict, List
import sys


def ttl_escape(s: str) -> str:
    """Escape string for Turtle literals"""
    if not s:
        return ""
    return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')


def read_csv(path: Path) -> List[Dict[str, str]]:
    """Read CSV file and return list of row dictionaries"""
    if not path.exists():
        print(f"WARNING: File not found: {path}", file=sys.stderr)
        return []

    rows = []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


class CensusV2RDFGenerator:
    """Generate CIDOC-CRM RDF from neo4j_census_v2 CSV files"""

    def __init__(self, csv_dir: Path, base_uri: str):
        self.csv_dir = csv_dir
        self.base = base_uri.rstrip('/') + '/'
        self.lines = []
        self.stats = {
            'measurements': 0,
            'dimensions': 0,
            'units': 0,
            'types': 0,
            'timespans': 0,
            'info_objects': 0
        }

    def add(self, line: str):
        self.lines.append(line)

    def generate_prefixes(self):
        self.add("@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .")
        self.add("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .")
        self.add("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .")
        self.add(f"@prefix ex: <{self.base}> .")
        self.add("")
        self.add("# Census Observations 1851-1901 (666,423 measurements)")
        self.add("")

    def generate_e58_units(self):
        """Generate E58_Measurement_Unit nodes"""
        self.add("# E58_Measurement_Unit - Units of Measurement")

        rows = read_csv(self.csv_dir / 'e58_measurement_units.csv')
        for row in rows:
            unit_id = row.get('unit_id:ID', '')
            label = row.get('label', '')
            symbol = row.get('symbol', '')

            if not unit_id:
                continue

            self.add(f'ex:unit/{unit_id} a crm:E58_Measurement_Unit ;')
            self.add(f'  rdfs:label "{ttl_escape(label)}" ;')
            if symbol:
                self.add(f'  ex:symbol "{ttl_escape(symbol)}" ;')
            self.add(f'  .')
            self.stats['units'] += 1

        self.add("")
        print(f"Generated {len(rows)} measurement units", file=sys.stderr)

    def generate_e55_types(self):
        """Generate E55_Type nodes (variable taxonomy)"""
        self.add("# E55_Type - Variable Types (490 census variables)")

        rows = read_csv(self.csv_dir / 'e55_variable_types.csv')
        for row in rows:
            type_id = row.get('type_id:ID', '')
            label = row.get('label', '')
            category = row.get('category', '')
            unit = row.get('unit', '')
            variable_name = row.get('variable_name', '')

            if not type_id:
                continue

            self.add(f'ex:variableType/{type_id} a crm:E55_Type ;')
            self.add(f'  rdfs:label "{ttl_escape(label)}" ;')
            if category:
                self.add(f'  ex:category "{category}" ;')
            if unit:
                self.add(f'  ex:unit "{unit}" ;')
            if variable_name:
                self.add(f'  ex:variableName "{variable_name}" ;')
            self.add(f'  .')
            self.stats['types'] += 1

        self.add("")
        print(f"Generated {len(rows)} variable types", file=sys.stderr)

    def generate_e52_timespans(self):
        """Generate E52_Time-Span nodes"""
        self.add("# E52_Time-Span - Temporal Extents")

        rows = read_csv(self.csv_dir / 'e52_timespans.csv')
        for row in rows:
            timespan_id = row.get('timespan_id:ID', '')
            label = row.get('label', '')
            begin = row.get('begin_of_begin', '')
            end = row.get('end_of_end', '')

            if not timespan_id:
                continue

            self.add(f'ex:timespan/{timespan_id} a crm:E52_Time-Span ;')
            self.add(f'  rdfs:label "{ttl_escape(label)}" ;')
            if begin:
                self.add(f'  crm:P82a_begin_of_the_begin "{begin}"^^xsd:date ;')
            if end:
                self.add(f'  crm:P82b_end_of_the_end "{end}"^^xsd:date ;')
            self.add(f'  .')
            self.stats['timespans'] += 1

        self.add("")
        print(f"Generated {len(rows)} timespans", file=sys.stderr)

    def generate_e73_info_objects(self):
        """Generate E73_Information_Object nodes (source files)"""
        self.add("# E73_Information_Object - Source Data Files")

        rows = read_csv(self.csv_dir / 'e73_information_objects.csv')
        for row in rows:
            obj_id = row.get('info_object_id:ID', '')
            label = row.get('label', '')
            year = row.get('year:int', '')
            landing_page = row.get('landing_page', '')
            access_uri = row.get('access_uri', '')

            if not obj_id:
                continue

            self.add(f'ex:infoObject/{obj_id} a crm:E73_Information_Object ;')
            self.add(f'  rdfs:label "{ttl_escape(label)}" ;')
            if year:
                self.add(f'  ex:year {year} ;')
            if landing_page:
                self.add(f'  ex:landingPage <{landing_page}> ;')
            if access_uri:
                self.add(f'  ex:accessURI <{access_uri}> ;')
            self.add(f'  .')
            self.stats['info_objects'] += 1

        self.add("")
        print(f"Generated {len(rows)} information objects", file=sys.stderr)

    def generate_measurements_and_dimensions(self):
        """Generate E16_Measurement and E54_Dimension nodes with relationships"""
        self.add("# E16_Measurement + E54_Dimension (666,423 measurements)")
        self.add("# Includes relationships: P2_has_type, P39_measured, P40_observed_dimension, P4_has_time_span")

        # Read all CSV files
        measurements = read_csv(self.csv_dir / 'e16_measurements_all.csv')
        dimensions = read_csv(self.csv_dir / 'e54_dimensions_all.csv')

        # Index dimensions by ID for quick lookup
        dim_by_id = {d.get('dimension_id:ID'): d for d in dimensions}

        # Read relationships
        p2_rels = {}  # measurement_id -> type_id
        p39_rels = {}  # measurement_id -> presence_id
        p40_rels = {}  # measurement_id -> dimension_id
        p4_rels = {}  # measurement_id -> timespan_id
        p91_rels = {}  # dimension_id -> unit_id

        print("Loading relationships...", file=sys.stderr)
        for row in read_csv(self.csv_dir / 'p2_has_type_all.csv'):
            p2_rels[row.get(':START_ID')] = row.get(':END_ID')

        for row in read_csv(self.csv_dir / 'p39_measured_all.csv'):
            p39_rels[row.get(':START_ID')] = row.get(':END_ID')

        for row in read_csv(self.csv_dir / 'p40_observed_dimension_all.csv'):
            p40_rels[row.get(':START_ID')] = row.get(':END_ID')

        for row in read_csv(self.csv_dir / 'p4_measurement_timespan_all.csv'):
            p4_rels[row.get(':START_ID')] = row.get(':END_ID')

        for row in read_csv(self.csv_dir / 'p91_has_unit_all.csv'):
            p91_rels[row.get(':START_ID')] = row.get(':END_ID')

        print(f"Processing {len(measurements)} measurements...", file=sys.stderr)

        # Process in batches for progress reporting
        batch_size = 50000
        for i, meas in enumerate(measurements):
            meas_id = meas.get('measurement_id:ID', '')
            if not meas_id:
                continue

            label = meas.get('label', '')

            # Get relationships
            type_id = p2_rels.get(meas_id)
            presence_id = p39_rels.get(meas_id)
            dim_id = p40_rels.get(meas_id)
            timespan_id = p4_rels.get(meas_id)

            # Generate E16_Measurement
            self.add(f'ex:measurement/{meas_id} a crm:E16_Measurement ;')
            if label:
                self.add(f'  rdfs:label "{ttl_escape(label)}" ;')
            if type_id:
                self.add(f'  crm:P2_has_type ex:variableType/{type_id} ;')
            if presence_id:
                self.add(f'  crm:P39_measured ex:presence/{presence_id} ;')
            if dim_id:
                self.add(f'  crm:P40_observed_dimension ex:dimension/{dim_id} ;')
            if timespan_id:
                self.add(f'  crm:P4_has_time-span ex:timespan/{timespan_id} ;')
            self.add(f'  .')

            # Generate E54_Dimension
            if dim_id and dim_id in dim_by_id:
                dim = dim_by_id[dim_id]
                value = dim.get('value:float', '')
                value_string = dim.get('value_string', '')
                unit_id = p91_rels.get(dim_id)

                self.add(f'ex:dimension/{dim_id} a crm:E54_Dimension ;')
                if value:
                    lit_type = 'xsd:decimal' if '.' in value else 'xsd:integer'
                    self.add(f'  crm:P90_has_value "{value}"^^{lit_type} ;')
                if value_string:
                    self.add(f'  ex:valueString "{ttl_escape(value_string)}" ;')
                if unit_id:
                    self.add(f'  crm:P91_has_unit ex:unit/{unit_id} ;')
                self.add(f'  .')

                self.stats['dimensions'] += 1

            self.stats['measurements'] += 1

            # Progress reporting
            if (i + 1) % batch_size == 0:
                print(f"  Processed {i+1:,} measurements...", file=sys.stderr)

        self.add("")
        print(f"Generated {self.stats['measurements']:,} measurements and {self.stats['dimensions']:,} dimensions", file=sys.stderr)

    def generate(self) -> str:
        """Generate complete RDF document"""
        self.generate_prefixes()
        self.generate_e58_units()
        self.generate_e55_types()
        self.generate_e52_timespans()
        self.generate_e73_info_objects()
        self.generate_measurements_and_dimensions()

        return '\n'.join(self.lines) + '\n'


def main():
    parser = argparse.ArgumentParser(
        description='Generate CIDOC-CRM RDF from neo4j_census_v2 CSV files'
    )
    parser.add_argument('--csv-dir', type=Path, default=Path('neo4j_census_v2'),
                        help='Directory containing census v2 CSV files')
    parser.add_argument('--base', default='https://canada.census.example.org/',
                        help='Base URI for RDF resources')
    parser.add_argument('--out', type=Path, required=True,
                        help='Output TTL file path')

    args = parser.parse_args()

    if not args.csv_dir.exists():
        print(f"ERROR: CSV directory not found: {args.csv_dir}", file=sys.stderr)
        sys.exit(1)

    generator = CensusV2RDFGenerator(args.csv_dir, args.base)
    ttl_content = generator.generate()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(ttl_content, encoding='utf-8')

    print(f"\nWrote {args.out}", file=sys.stderr)
    print(f"Size: {len(ttl_content):,} bytes", file=sys.stderr)
    print(f"Lines: {len(ttl_content.splitlines()):,}", file=sys.stderr)
    print(f"\nStatistics:", file=sys.stderr)
    print(f"  Measurements: {generator.stats['measurements']:,}", file=sys.stderr)
    print(f"  Dimensions: {generator.stats['dimensions']:,}", file=sys.stderr)
    print(f"  Variable Types: {generator.stats['types']:,}", file=sys.stderr)
    print(f"  Units: {generator.stats['units']:,}", file=sys.stderr)
    print(f"  Timespans: {generator.stats['timespans']:,}", file=sys.stderr)
    print(f"  Info Objects: {generator.stats['info_objects']:,}", file=sys.stderr)


if __name__ == '__main__':
    main()
