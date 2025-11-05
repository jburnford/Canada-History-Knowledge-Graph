#!/usr/bin/env python3
"""
Generate RDF (Turtle) from CIDOC-CRM CSV files produced by build_neo4j_cidoc_crm.py

Converts Neo4j CSV format to CIDOC-CRM RDF:
- E53_Place: Canadian census subdivisions and divisions
- E4_Period: Census years (1851-1921)
- E93_Presence: Temporal manifestations of places
- E94_Space_Primitive: Spatial coordinates (centroids)
- Relationships: P166, P164, P161, P89, P122, P132

Optional: Integrate canonical names for OCR corrections

Usage:
    python3 scripts/rdf_from_cidoc_csv.py \
        --csv-dir neo4j_cidoc_crm \
        --canonical canonical_names_final.csv \
        --base https://canada.census.example.org/ \
        --out generated/canada/canada_cidoc_places_1851_1921.ttl
"""

import argparse
import csv
from pathlib import Path
from typing import Dict, Set, List, Tuple
import sys


def ttl_escape(s: str) -> str:
    """Escape string for Turtle literals"""
    if not s:
        return ""
    return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')


def load_canonical_names(csv_path: Path) -> Dict[Tuple[str, str], str]:
    """Load canonical names that should be applied.
    Returns dict: (tcpuid, year) -> canonical_name
    """
    if not csv_path or not csv_path.exists():
        return {}

    canonical = {}
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('should_apply', '').upper() == 'TRUE':
                tcpuid = row.get('tcpuid', '')
                year = row.get('year', '')
                canonical_name = row.get('canonical_name', '')
                if tcpuid and year and canonical_name:
                    canonical[(tcpuid, year)] = canonical_name

    print(f"Loaded {len(canonical)} canonical name corrections", file=sys.stderr)
    return canonical


def read_csv(path: Path) -> List[Dict[str, str]]:
    """Read CSV file and return list of row dictionaries"""
    if not path.exists():
        return []

    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


class RDFGenerator:
    """Generate CIDOC-CRM RDF Turtle from Neo4j CSV files"""

    def __init__(self, csv_dir: Path, base_uri: str, canonical_names: Dict[Tuple[str, str], str]):
        self.csv_dir = csv_dir
        self.base = base_uri.rstrip('/') + '/'
        self.canonical = canonical_names
        self.lines = []
        self.declared_places = set()  # Track E53_Place nodes to avoid duplicates

    def add(self, line: str):
        """Add a line to output"""
        self.lines.append(line)

    def generate_prefixes(self):
        """Generate RDF prefix declarations"""
        self.add("@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .")
        self.add("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .")
        self.add("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .")
        self.add("@prefix geo: <http://www.w3.org/2003/01/geo/wgs84_pos#> .")
        self.add(f"@prefix ex: <{self.base}> .")
        self.add("")

    def generate_e53_places(self):
        """Generate E53_Place nodes for CSDs and CDs"""
        self.add("# E53_Place - Census Subdivisions and Divisions")

        # CSD places
        csd_rows = read_csv(self.csv_dir / 'e53_place_csd.csv')
        for row in csd_rows:
            place_id = row.get('place_id:ID', '')
            if not place_id:
                continue

            place_type = row.get('place_type', 'CSD')
            name = ttl_escape(row.get('name', 'NO DATA'))

            self.add(f'ex:place/{place_id} a crm:E53_Place ;')
            self.add(f'  rdfs:label "{name}" ;')
            self.add(f'  ex:placeType "{place_type}" .')
            self.declared_places.add(place_id)

        # CD places
        cd_rows = read_csv(self.csv_dir / 'e53_place_cd.csv')
        for row in cd_rows:
            place_id = row.get('place_id:ID', '')
            if not place_id:
                continue

            place_type = row.get('place_type', 'CD')
            name = ttl_escape(row.get('name', 'NO DATA'))
            province = row.get('province', '')

            self.add(f'ex:place/{place_id} a crm:E53_Place ;')
            self.add(f'  rdfs:label "{name}" ;')
            self.add(f'  ex:placeType "{place_type}" ;')
            if province:
                self.add(f'  ex:province "{province}" ;')
            self.add(f'  .')
            self.declared_places.add(place_id)

        self.add("")
        print(f"Generated {len(csd_rows)} CSD places, {len(cd_rows)} CD places", file=sys.stderr)

    def generate_e4_periods(self, years: List[str]):
        """Generate E4_Period nodes for census years"""
        self.add("# E4_Period - Census Years")

        # Generate periods for all specified years
        for year in years:
            period_id = f'CENSUS_{year}'
            label = f'{year} Canadian Census'

            self.add(f'ex:period/{period_id} a crm:E4_Period ;')
            self.add(f'  rdfs:label "{label}" ;')
            self.add(f'  ex:year "{year}"^^xsd:gYear ;')
            self.add(f'  crm:P82a_begin_of_the_begin "{year}-01-01"^^xsd:date ;')
            self.add(f'  crm:P82b_end_of_the_end "{year}-12-31"^^xsd:date .')

        self.add("")
        print(f"Generated {len(years)} period nodes", file=sys.stderr)

    def generate_e93_presences(self, years: List[str]):
        """Generate E93_Presence nodes for all years"""
        self.add("# E93_Presence - Temporal Manifestations of Places")

        total = 0
        for year in years:
            rows = read_csv(self.csv_dir / f'e93_presence_{year}.csv')
            for row in rows:
                presence_id = row.get('presence_id:ID', '')
                csd_tcpuid = row.get('csd_tcpuid', '')
                census_year = row.get('census_year:int', '')
                area_sqm = row.get('area_sqm:float', '')

                if not presence_id or not csd_tcpuid:
                    continue

                # Check for canonical name override
                canonical_name = self.canonical.get((csd_tcpuid, year))

                self.add(f'ex:presence/{presence_id} a crm:E93_Presence ;')
                self.add(f'  ex:csdTcpuid "{csd_tcpuid}" ;')
                if census_year:
                    self.add(f'  ex:censusYear {census_year} ;')
                if area_sqm:
                    self.add(f'  ex:areaSqM "{area_sqm}"^^xsd:decimal ;')
                if canonical_name:
                    self.add(f'  ex:canonicalName "{ttl_escape(canonical_name)}" ;')
                self.add(f'  .')
                total += 1

        self.add("")
        print(f"Generated {total} presence nodes", file=sys.stderr)

    def generate_e94_space_primitives(self, years: List[str]):
        """Generate E94_Space_Primitive nodes with coordinates"""
        self.add("# E94_Space_Primitive - Spatial Coordinates")

        total = 0
        for year in years:
            rows = read_csv(self.csv_dir / f'e94_space_primitive_{year}.csv')
            for row in rows:
                space_id = row.get('space_id:ID', '')
                lat = row.get('latitude:float', '')
                lon = row.get('longitude:float', '')
                crs = row.get('crs', 'EPSG:4326')

                if not space_id or not lat or not lon:
                    continue

                self.add(f'ex:space/{space_id} a crm:E94_Space_Primitive ;')
                self.add(f'  geo:lat "{lat}"^^xsd:decimal ;')
                self.add(f'  geo:long "{lon}"^^xsd:decimal ;')
                self.add(f'  ex:crs "{crs}" .')
                total += 1

        self.add("")
        print(f"Generated {total} space primitive nodes", file=sys.stderr)

    def generate_p166_was_presence_of(self, years: List[str]):
        """Generate P166_was_a_presence_of relationships"""
        self.add("# P166_was_a_presence_of - Presence to Place")

        total = 0
        for year in years:
            rows = read_csv(self.csv_dir / f'p166_was_presence_of_{year}.csv')
            for row in rows:
                start_id = row.get(':START_ID', '')
                end_id = row.get(':END_ID', '')

                if not start_id or not end_id:
                    continue

                self.add(f'ex:presence/{start_id} crm:P166_was_a_presence_of ex:place/{end_id} .')
                total += 1

        self.add("")
        print(f"Generated {total} P166 relationships", file=sys.stderr)

    def generate_p164_temporally_specified_by(self, years: List[str]):
        """Generate P164_is_temporally_specified_by relationships"""
        self.add("# P164_is_temporally_specified_by - Presence to Period")

        total = 0
        for year in years:
            rows = read_csv(self.csv_dir / f'p164_temporally_specified_by_{year}.csv')
            for row in rows:
                start_id = row.get(':START_ID', '')
                end_id = row.get(':END_ID', '')

                if not start_id or not end_id:
                    continue

                self.add(f'ex:presence/{start_id} crm:P164_is_temporally_specified_by ex:period/{end_id} .')
                total += 1

        self.add("")
        print(f"Generated {total} P164 relationships", file=sys.stderr)

    def generate_p161_spatial_projection(self, years: List[str]):
        """Generate P161_has_spatial_projection relationships"""
        self.add("# P161_has_spatial_projection - Presence to Space")

        total = 0
        for year in years:
            rows = read_csv(self.csv_dir / f'p161_spatial_projection_{year}.csv')
            for row in rows:
                start_id = row.get(':START_ID', '')
                end_id = row.get(':END_ID', '')

                if not start_id or not end_id:
                    continue

                self.add(f'ex:presence/{start_id} crm:P161_has_spatial_projection ex:space/{end_id} .')
                total += 1

        self.add("")
        print(f"Generated {total} P161 relationships", file=sys.stderr)

    def generate_p89_falls_within(self, years: List[str]):
        """Generate P89_falls_within relationships (CSD within CD)"""
        self.add("# P89_falls_within - CSD within Census Division")

        total = 0
        for year in years:
            path = self.csv_dir / f'p10_csd_within_cd_presence_{year}.csv'
            if not path.exists():
                continue

            rows = read_csv(path)
            for row in rows:
                start_id = row.get(':START_ID', '')
                end_id = row.get(':END_ID', '')

                if not start_id or not end_id:
                    continue

                self.add(f'ex:presence/{start_id} crm:P89_falls_within ex:presence/{end_id} .')
                total += 1

        self.add("")
        print(f"Generated {total} P89 relationships", file=sys.stderr)

    def generate_p122_borders_with(self, years: List[str]):
        """Generate P122_borders_with relationships"""
        self.add("# P122_borders_with - Spatial Adjacency")

        total = 0
        for year in years:
            rows = read_csv(self.csv_dir / f'p122_borders_with_{year}.csv')
            for row in rows:
                start_id = row.get(':START_ID', '')
                end_id = row.get(':END_ID', '')
                border_length = row.get('shared_border_length_m:float', '')
                during_period = row.get('during_period', '')

                if not start_id or not end_id:
                    continue

                self.add(f'ex:place/{start_id} crm:P122_borders_with ex:place/{end_id} ;')
                if border_length:
                    self.add(f'  ex:sharedBorderLengthM "{border_length}"^^xsd:decimal ;')
                if during_period:
                    self.add(f'  ex:duringPeriod ex:period/{during_period} ;')
                self.add(f'  .')
                total += 1

        self.add("")
        print(f"Generated {total} P122 relationships", file=sys.stderr)

    def generate_p132_spatiotemporally_overlaps(self):
        """Generate P132_spatiotemporally_overlaps_with relationships"""
        self.add("# P132_spatiotemporally_overlaps_with - Temporal Continuity")

        rows = read_csv(self.csv_dir / 'p132_spatiotemporally_overlaps_with_csd.csv')
        for row in rows:
            start_id = row.get(':START_ID', '')
            end_id = row.get(':END_ID', '')
            overlap_type = row.get('overlap_type', '')
            iou = row.get('iou:float', '')
            from_frac = row.get('from_fraction:float', '')
            to_frac = row.get('to_fraction:float', '')
            year_from = row.get('year_from:int', '')
            year_to = row.get('year_to:int', '')

            if not start_id or not end_id:
                continue

            self.add(f'ex:presence/{start_id} crm:P132_spatiotemporally_overlaps_with ex:presence/{end_id} ;')
            if overlap_type:
                self.add(f'  ex:overlapType "{overlap_type}" ;')
            if iou:
                self.add(f'  ex:intersectionOverUnion "{iou}"^^xsd:decimal ;')
            if from_frac:
                self.add(f'  ex:fromFraction "{from_frac}"^^xsd:decimal ;')
            if to_frac:
                self.add(f'  ex:toFraction "{to_frac}"^^xsd:decimal ;')
            if year_from:
                self.add(f'  ex:yearFrom {year_from} ;')
            if year_to:
                self.add(f'  ex:yearTo {year_to} ;')
            self.add(f'  .')

        self.add("")
        print(f"Generated {len(rows)} P132 relationships", file=sys.stderr)

    def generate(self, years: List[str]) -> str:
        """Generate complete RDF document"""
        self.generate_prefixes()
        self.generate_e53_places()
        self.generate_e4_periods(years)
        self.generate_e93_presences(years)
        self.generate_e94_space_primitives(years)
        self.generate_p166_was_presence_of(years)
        self.generate_p164_temporally_specified_by(years)
        self.generate_p161_spatial_projection(years)
        self.generate_p89_falls_within(years)
        self.generate_p122_borders_with(years)
        self.generate_p132_spatiotemporally_overlaps()

        return '\n'.join(self.lines) + '\n'


def main():
    parser = argparse.ArgumentParser(
        description='Generate CIDOC-CRM RDF from Neo4j CSV files'
    )
    parser.add_argument('--csv-dir', type=Path, default=Path('neo4j_cidoc_crm'),
                        help='Directory containing CIDOC-CRM CSV files')
    parser.add_argument('--canonical', type=Path, default=Path('canonical_names_final.csv'),
                        help='CSV file with canonical name corrections')
    parser.add_argument('--base', default='https://canada.census.example.org/',
                        help='Base URI for RDF resources')
    parser.add_argument('--years', default='1851,1861,1871,1881,1891,1901,1911,1921',
                        help='Comma-separated list of census years')
    parser.add_argument('--out', type=Path, required=True,
                        help='Output TTL file path')

    args = parser.parse_args()

    if not args.csv_dir.exists():
        print(f"ERROR: CSV directory not found: {args.csv_dir}", file=sys.stderr)
        sys.exit(1)

    years = [y.strip() for y in args.years.split(',')]
    canonical = load_canonical_names(args.canonical)

    generator = RDFGenerator(args.csv_dir, args.base, canonical)
    ttl_content = generator.generate(years)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(ttl_content, encoding='utf-8')

    print(f"\nWrote {args.out}")
    print(f"Size: {len(ttl_content):,} bytes")
    print(f"Lines: {len(ttl_content.splitlines()):,}")


if __name__ == '__main__':
    main()
