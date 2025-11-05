#!/usr/bin/env python3
"""
Generate CIDOC-CRM RDF from pre-extracted census CSV files.

Simpler alternative to rdf_generate_census_observations.py that works with
CSV files produced by parse_1911_v1t1_sk.py or similar extraction scripts.

Expected CSV format:
  places.csv: id, name, province_code, cd_no, csd_no, level, year_start, notes
  observations.csv: id, place_id, year, [measurement columns], table_id, notes

Usage:
    # Generate from extracted CSV
    python3 scripts/rdf_from_census_csv.py \
        --places generated/ca_1911/places.csv \
        --observations generated/ca_1911/observations.csv \
        --base https://canada.census.example.org/ \
        --out generated/canada/canada_observations_1911_csv.ttl
"""

import argparse
import csv
from pathlib import Path
from typing import Dict, List, Tuple
import sys


def ttl_escape(s: str) -> str:
    """Escape string for Turtle literals"""
    if not s:
        return ""
    return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')


def infer_unit_from_column(col: str) -> str:
    """Infer measurement unit from column name"""
    c = col.upper()

    if 'POP' in c or 'POPULATION' in c:
        return 'person'
    elif '_ACRES' in c or 'AREA_ACRES' in c:
        return 'acre'
    elif '_SQ_MI' in c or 'SQUARE_MILE' in c:
        return 'square_mile'
    elif '_BU' in c or 'BUSHEL' in c:
        return 'bushel'
    elif '_LB' in c or 'POUND' in c:
        return 'pound'
    elif '_TON' in c in c:
        return 'ton'
    elif 'CATTLE' in c or 'SHEEP' in c or 'SWINE' in c or 'COW' in c:
        return 'head'
    elif 'HOUSE' in c or 'FAMIL' in c:
        return 'count'
    elif 'PER_SQ_MI' in c:
        return 'per_square_mile'
    else:
        return 'count'


def friendly_label(col: str) -> str:
    """Convert column name to friendly label"""
    # Remove year suffix
    parts = col.rsplit('_', 1)
    if len(parts) == 2 and parts[1].isdigit():
        col = parts[0]

    # Convert underscores to spaces and title case
    return col.replace('_', ' ').title()


def load_places(places_csv: Path) -> Dict[str, Dict]:
    """Load places from CSV"""
    places = {}
    with open(places_csv, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            place_id = row.get('id', '')
            if place_id:
                places[place_id] = row
    return places


def load_observations(obs_csv: Path) -> List[Dict]:
    """Load observations from CSV"""
    observations = []
    with open(obs_csv, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            observations.append(row)
    return observations


def extract_tcpuid(place_id: str) -> str:
    """Extract TCPUID (first 8 chars: 2-letter province + 6 digits)"""
    if len(place_id) >= 8 and place_id[:2].isalpha() and place_id[2:8].isdigit():
        return place_id[:8]
    return place_id


class CSVObservationsRDFGenerator:
    """Generate CIDOC-CRM observation RDF from CSV files"""

    def __init__(self, base_uri: str):
        self.base = base_uri.rstrip('/') + '/'
        self.lines = []
        self.units_declared = set()
        self.measurement_types = set()
        self.stats = {'measurements': 0, 'dimensions': 0}

    def add(self, line: str):
        self.lines.append(line)

    def generate_prefixes(self):
        self.add("@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .")
        self.add("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .")
        self.add("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .")
        self.add(f"@prefix ex: <{self.base}> .")
        self.add("")

    def declare_unit(self, unit: str):
        if unit in self.units_declared:
            return
        self.add(f'ex:unit/{unit} a crm:E58_Measurement_Unit ; rdfs:label "{unit}" .')
        self.units_declared.add(unit)

    def declare_measurement_type(self, code: str, label: str, year: str):
        key = f"{code}_{year}"
        if key in self.measurement_types:
            return
        self.add(f'ex:measurementType/{key} a crm:E55_Type ; rdfs:label "{ttl_escape(label)} ({year})" .')
        self.measurement_types.add(key)

    def generate(self, places: Dict, observations: List[Dict]) -> str:
        """Generate complete RDF document"""
        self.generate_prefixes()

        # Identify measurement columns (skip metadata columns)
        skip_cols = {'id', 'place_id', 'year', 'table_id', 'notes'}
        measurement_cols = set()

        for obs in observations:
            for col in obs.keys():
                if col not in skip_cols and obs.get(col, '').strip():
                    measurement_cols.add(col)

        self.add("# Measurement Units")
        units = {infer_unit_from_column(col) for col in measurement_cols}
        for unit in sorted(units):
            self.declare_unit(unit)
        self.add("")

        # Group observations by year
        by_year = {}
        for obs in observations:
            year = obs.get('year', '')
            if year:
                by_year.setdefault(year, []).append(obs)

        # Generate RDF for each year
        for year in sorted(by_year.keys()):
            self.add(f"# Observations for {year}")

            # Declare measurement types for this year
            for col in sorted(measurement_cols):
                label = friendly_label(col)
                code = col.lower()
                self.declare_measurement_type(code, label, year)
            self.add("")

            # Generate measurements
            for obs in by_year[year]:
                place_id = obs.get('place_id', '')
                if not place_id:
                    continue

                tcpuid = extract_tcpuid(place_id)
                presence_id = f"{tcpuid}_{year}"

                for col in measurement_cols:
                    val = obs.get(col, '').strip()
                    if not val:
                        continue

                    # Parse numeric value
                    vtxt = val.replace(',', '').replace(' ', '')
                    try:
                        float(vtxt)
                    except:
                        continue

                    code = col.lower()
                    unit = infer_unit_from_column(col)

                    meas_id = f"{presence_id}_{code}"
                    dim_id = f"{meas_id}_dim"

                    self.add(f'ex:measurement/{meas_id} a crm:E16_Measurement ;')
                    self.add(f'  crm:P39_measured ex:presence/{presence_id} ;')
                    self.add(f'  crm:P2_has_type ex:measurementType/{code}_{year} ;')
                    self.add(f'  crm:P40_observed_dimension ex:dimension/{dim_id} ;')
                    self.add(f'  crm:P4_has_time-span ex:period/CENSUS_{year} .')

                    # Determine datatype
                    lit_type = 'xsd:integer'
                    if '.' in vtxt or 'e' in vtxt.lower():
                        lit_type = 'xsd:decimal'

                    self.add(f'ex:dimension/{dim_id} a crm:E54_Dimension ;')
                    self.add(f'  crm:P91_has_unit ex:unit/{unit} ;')
                    self.add(f'  crm:P90_has_value "{vtxt}"^^{lit_type} .')

                    self.stats['measurements'] += 1
                    self.stats['dimensions'] += 1

            self.add("")

        return '\n'.join(self.lines) + '\n'


def main():
    parser = argparse.ArgumentParser(
        description='Generate CIDOC-CRM observation RDF from pre-extracted CSV files'
    )
    parser.add_argument('--places', type=Path, required=True,
                        help='Path to places.csv')
    parser.add_argument('--observations', type=Path, required=True,
                        help='Path to observations.csv')
    parser.add_argument('--base', default='https://canada.census.example.org/',
                        help='Base URI for RDF resources')
    parser.add_argument('--out', type=Path, required=True,
                        help='Output TTL file path')

    args = parser.parse_args()

    if not args.places.exists():
        print(f"ERROR: Places CSV not found: {args.places}", file=sys.stderr)
        sys.exit(1)

    if not args.observations.exists():
        print(f"ERROR: Observations CSV not found: {args.observations}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading places from {args.places}...", file=sys.stderr)
    places = load_places(args.places)

    print(f"Loading observations from {args.observations}...", file=sys.stderr)
    observations = load_observations(args.observations)

    print(f"Generating RDF...", file=sys.stderr)
    generator = CSVObservationsRDFGenerator(args.base)
    ttl_content = generator.generate(places, observations)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(ttl_content, encoding='utf-8')

    print(f"\nWrote {args.out}", file=sys.stderr)
    print(f"Size: {len(ttl_content):,} bytes", file=sys.stderr)
    print(f"Lines: {len(ttl_content.splitlines()):,}", file=sys.stderr)
    print(f"Places: {len(places):,}", file=sys.stderr)
    print(f"Observations: {len(observations):,}", file=sys.stderr)
    print(f"Measurements: {generator.stats['measurements']:,}", file=sys.stderr)
    print(f"Dimensions: {generator.stats['dimensions']:,}", file=sys.stderr)


if __name__ == '__main__':
    main()
