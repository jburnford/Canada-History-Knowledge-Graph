#!/usr/bin/env python3
"""
Fetch Canadian communities from Wikidata with founding dates and PIDs.
Creates nodes for real-world communities (cities, towns, villages) separate from census geography.
"""

import httpx
import json
import csv
import time
from typing import List, Dict, Optional
from datetime import datetime

WIKIDATA_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "CanadianCensusProject/1.0 (census knowledge graph)"

def execute_sparql_query(query: str) -> List[Dict]:
    """Execute SPARQL query against Wikidata endpoint."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json"
    }
    params = {
        "query": query,
        "format": "json"
    }

    print(f"Executing SPARQL query...")
    response = httpx.get(WIKIDATA_SPARQL_ENDPOINT, headers=headers, params=params, timeout=60.0)
    response.raise_for_status()

    data = response.json()
    results = data.get("results", {}).get("bindings", [])
    print(f"Retrieved {len(results)} results")
    return results

def fetch_canadian_municipalities() -> List[Dict]:
    """
    Fetch Canadian municipalities, cities, towns, villages from Wikidata.

    Returns:
        List of dicts with entity ID, name, type, founding date, coordinates, etc.
    """

    # SPARQL query for Canadian municipalities
    # P31 = instance of
    # P17 = country (Q16 = Canada)
    # P571 = inception/founding date
    # P625 = coordinate location
    # P1566 = GeoNames ID
    # P131 = located in administrative territorial entity (province)

    query = """
    SELECT DISTINCT ?place ?placeLabel ?typeLabel ?inception ?coords ?geonames ?provinceLabel
    WHERE {
      # Canadian municipalities, cities, towns, villages
      VALUES ?type {
        wd:Q15284     # municipality (general)
        wd:Q515       # city
        wd:Q3957      # town
        wd:Q532       # village
        wd:Q1549591   # big city
        wd:Q3957      # small town
        wd:Q484170    # commune (French Canadian)
        wd:Q3327873   # municipality of Canada
        wd:Q3504868   # city of Canada
        wd:Q17343829  # census-designated place
        wd:Q1907114   # metropolitan area
        wd:Q5084       # hamlet
      }

      ?place wdt:P31 ?type ;        # instance of municipality/city/town/etc
             wdt:P17 wd:Q16 .        # country = Canada

      # Optional properties
      OPTIONAL { ?place wdt:P571 ?inception . }       # founding/inception date
      OPTIONAL { ?place wdt:P625 ?coords . }          # coordinates
      OPTIONAL { ?place wdt:P1566 ?geonames . }       # GeoNames ID
      OPTIONAL { ?place wdt:P131 ?province . }        # located in province

      # Get labels in English
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en,fr" . }
    }
    LIMIT 5000
    """

    results = execute_sparql_query(query)

    # Parse results
    places = []
    for result in results:
        place_uri = result.get("place", {}).get("value", "")
        place_id = place_uri.split("/")[-1] if place_uri else ""

        place_data = {
            "wikidata_id": place_id,
            "name": result.get("placeLabel", {}).get("value", ""),
            "type": result.get("typeLabel", {}).get("value", ""),
            "inception_date": result.get("inception", {}).get("value", ""),
            "coordinates": result.get("coords", {}).get("value", ""),
            "geonames_id": result.get("geonames", {}).get("value", ""),
            "province": result.get("provinceLabel", {}).get("value", ""),
            "wikidata_uri": place_uri
        }
        places.append(place_data)

    return places

def fetch_detailed_entity_data(entity_id: str) -> Dict:
    """
    Fetch detailed information for a specific Wikidata entity.

    Retrieves:
    - P571: inception/founding date
    - P576: dissolved/abolished date
    - P1082: population
    - P1448: official name
    - P1813: short name
    - P625: coordinate location
    - P1566: GeoNames ID
    - P402: OpenStreetMap relation ID
    """

    query = f"""
    SELECT ?property ?value ?valueLabel
    WHERE {{
      wd:{entity_id} ?property ?value .

      # Filter to properties we care about
      FILTER(?property IN (
        wdt:P571,   # inception
        wdt:P576,   # dissolved
        wdt:P1082,  # population
        wdt:P1448,  # official name
        wdt:P1813,  # short name
        wdt:P625,   # coordinates
        wdt:P1566,  # GeoNames ID
        wdt:P402,   # OpenStreetMap relation ID
        wdt:P131    # located in
      ))

      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,fr" . }}
    }}
    """

    results = execute_sparql_query(query)

    entity_data = {"entity_id": entity_id}
    for result in results:
        prop = result.get("property", {}).get("value", "").split("/")[-1]
        value = result.get("value", {}).get("value", "")
        entity_data[prop] = value

    return entity_data

def write_community_nodes_csv(places: List[Dict], output_file: str):
    """Write E53_Place nodes for real-world communities."""

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        # Header
        writer.writerow([
            'place_id:ID', ':LABEL', 'name', 'place_type', 'community_type',
            'wikidata_id', 'wikidata_uri', 'geonames_id',
            'inception_date', 'province', 'latitude:float', 'longitude:float'
        ])

        for place in places:
            # Parse coordinates if available
            coords = place.get('coordinates', '')
            lat, lon = None, None
            if coords and coords.startswith('Point('):
                # Format: "Point(-75.6919 45.4215)"
                coords_clean = coords.replace('Point(', '').replace(')', '')
                try:
                    lon, lat = coords_clean.split()
                    lat = float(lat)
                    lon = float(lon)
                except ValueError:
                    pass

            place_id = f"COMMUNITY_{place['wikidata_id']}"

            writer.writerow([
                place_id,
                'E53_Place',
                place['name'],
                'COMMUNITY',  # Distinguishes from census CSD/CD
                place['type'],
                place['wikidata_id'],
                place['wikidata_uri'],
                place.get('geonames_id', ''),
                place.get('inception_date', ''),
                place.get('province', ''),
                lat if lat else '',
                lon if lon else ''
            ])

    print(f"Wrote {len(places)} community nodes to {output_file}")

def write_external_identifiers_csv(places: List[Dict], output_file: str):
    """Write E42_Identifier nodes for Wikidata and GeoNames PIDs."""

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        # Header
        writer.writerow([
            'identifier_id:ID', ':LABEL', 'identifier_value', 'identifier_type',
            'uri', 'label', 'retrieved_date'
        ])

        retrieved_date = datetime.now().strftime('%Y-%m-%d')

        for place in places:
            # Wikidata identifier
            if place.get('wikidata_id'):
                writer.writerow([
                    f"IDENT_WIKIDATA_{place['wikidata_id']}",
                    'E42_Identifier',
                    place['wikidata_id'],
                    'WIKIDATA',
                    place['wikidata_uri'],
                    f"Wikidata ID for {place['name']}",
                    retrieved_date
                ])

            # GeoNames identifier
            if place.get('geonames_id'):
                writer.writerow([
                    f"IDENT_GEONAMES_{place['geonames_id']}",
                    'E42_Identifier',
                    place['geonames_id'],
                    'GEONAMES',
                    f"https://www.geonames.org/{place['geonames_id']}",
                    f"GeoNames ID for {place['name']}",
                    retrieved_date
                ])

    print(f"Wrote external identifiers to {output_file}")

def write_identifier_relationships_csv(places: List[Dict], output_file: str):
    """Write P1_is_identified_by relationships between communities and identifiers."""

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        # Header
        writer.writerow([
            ':START_ID', ':END_ID', ':TYPE', 'identifier_type'
        ])

        for place in places:
            place_id = f"COMMUNITY_{place['wikidata_id']}"

            # Wikidata identifier relationship
            if place.get('wikidata_id'):
                writer.writerow([
                    place_id,
                    f"IDENT_WIKIDATA_{place['wikidata_id']}",
                    'P1_is_identified_by',
                    'WIKIDATA'
                ])

            # GeoNames identifier relationship
            if place.get('geonames_id'):
                writer.writerow([
                    place_id,
                    f"IDENT_GEONAMES_{place['geonames_id']}",
                    'P1_is_identified_by',
                    'GEONAMES'
                ])

    print(f"Wrote identifier relationships to {output_file}")

def main():
    print("=" * 60)
    print("Fetching Canadian Communities from Wikidata")
    print("=" * 60)

    # Create output directory
    import os
    output_dir = "neo4j_communities"
    os.makedirs(output_dir, exist_ok=True)

    # Fetch data
    print("\n1. Fetching Canadian municipalities from Wikidata...")
    places = fetch_canadian_municipalities()

    print(f"\n2. Retrieved {len(places)} communities")
    print(f"   Sample: {places[0]['name']} ({places[0]['wikidata_id']}) - {places[0]['type']}")

    # Write CSV files
    print("\n3. Writing CSV files...")
    write_community_nodes_csv(places, f"{output_dir}/e53_communities.csv")
    write_external_identifiers_csv(places, f"{output_dir}/e42_identifiers.csv")
    write_identifier_relationships_csv(places, f"{output_dir}/p1_community_identifiers.csv")

    # Summary statistics
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total communities: {len(places)}")
    print(f"With founding dates: {sum(1 for p in places if p.get('inception_date'))}")
    print(f"With coordinates: {sum(1 for p in places if p.get('coordinates'))}")
    print(f"With GeoNames IDs: {sum(1 for p in places if p.get('geonames_id'))}")
    print(f"\nCommunity types:")
    from collections import Counter
    types = Counter(p['type'] for p in places)
    for ctype, count in types.most_common(10):
        print(f"  {ctype}: {count}")

    print(f"\nOutput files written to {output_dir}/")
    print("  - e53_communities.csv")
    print("  - e42_identifiers.csv")
    print("  - p1_community_identifiers.csv")

    print("\n✅ Done!")

if __name__ == "__main__":
    main()
