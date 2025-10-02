#!/usr/bin/env python3
"""
Convert 1921 census spatial data to Linked Open Data (LOD) format.
Add proper URIs and attempt to link to Wikidata community entities.
"""

import csv
import re
from typing import Dict, List, Optional, Tuple
from rapidfuzz import fuzz, process
import math

def normalize_name(name: str) -> str:
    """Normalize place names for matching."""
    if not name:
        return ""
    # Remove common suffixes and prefixes
    name = name.strip()
    name = re.sub(r',.*$', '', name)  # Remove everything after comma
    name = re.sub(r'\(.*\)', '', name)  # Remove parenthetical
    name = name.replace('Saint', 'St.')
    name = name.replace('Sainte', 'Ste.')
    name = name.lower().strip()
    return name

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in km between two lat/lon points."""
    R = 6371  # Earth radius in km

    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))

    return R * c

def load_1921_csds() -> List[Dict]:
    """Load 1921 CSD presences with coordinates."""
    csds = []

    # Read E93 presences
    presence_data = {}
    with open('neo4j_cidoc_crm/e93_presence_1921.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            presence_data[row['presence_id:ID']] = row

    # Read E53 places
    place_data = {}
    with open('neo4j_cidoc_crm/e53_place_csd.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            place_data[row['place_id:ID']] = row

    # Read E94 space primitives (coordinates)
    space_data = {}
    with open('neo4j_cidoc_crm/e94_space_primitive_1921.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            space_data[row['space_id:ID']] = row

    # Combine data
    for presence_id, presence in presence_data.items():
        tcpuid = presence['csd_tcpuid']
        place = place_data.get(tcpuid, {})
        space = space_data.get(f"{tcpuid}_1921", {})

        csds.append({
            'presence_id': presence_id,
            'tcpuid': tcpuid,
            'name': place.get('name', ''),
            'province': place.get('province', ''),
            'area_sqm': presence.get('area_sqm:float', ''),
            'latitude': space.get('latitude:float', ''),
            'longitude': space.get('longitude:float', '')
        })

    print(f"Loaded {len(csds)} 1921 CSDs")
    return csds

def load_wikidata_communities() -> List[Dict]:
    """Load Wikidata community entities."""
    communities = []

    with open('neo4j_communities/e53_communities.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            communities.append(row)

    print(f"Loaded {len(communities)} Wikidata communities")
    return communities

def match_csd_to_community(csd: Dict, communities: List[Dict]) -> Optional[Tuple[Dict, float]]:
    """
    Match a 1921 CSD to a Wikidata community.

    Returns: (matched_community, confidence_score) or None
    """
    csd_name_norm = normalize_name(csd['name'])
    csd_lat = float(csd['latitude']) if csd['latitude'] else None
    csd_lon = float(csd['longitude']) if csd['longitude'] else None

    # Build list of candidates
    candidates = []
    for comm in communities:
        comm_name_norm = normalize_name(comm['name'])

        # Name similarity
        name_score = fuzz.ratio(csd_name_norm, comm_name_norm) / 100.0

        # Province match
        province_match = 0.0
        if csd['province'] and comm['province']:
            if csd['province'].lower() in comm['province'].lower() or \
               comm['province'].lower() in csd['province'].lower():
                province_match = 1.0

        # Coordinate distance
        coord_score = 0.0
        if csd_lat and csd_lon and comm['latitude:float'] and comm['longitude:float']:
            try:
                comm_lat = float(comm['latitude:float'])
                comm_lon = float(comm['longitude:float'])
                distance_km = haversine_distance(csd_lat, csd_lon, comm_lat, comm_lon)

                # Score: 1.0 if within 1km, 0.0 if beyond 50km
                if distance_km < 1:
                    coord_score = 1.0
                elif distance_km < 50:
                    coord_score = 1.0 - (distance_km / 50.0)
            except:
                pass

        # Combined score
        # Name is most important (50%), then coordinates (30%), then province (20%)
        total_score = (name_score * 0.5) + (coord_score * 0.3) + (province_match * 0.2)

        candidates.append((comm, total_score, name_score, coord_score, province_match))

    # Find best match
    if candidates:
        best = max(candidates, key=lambda x: x[1])
        comm, total_score, name_score, coord_score, province_match = best

        # Require minimum thresholds
        if total_score >= 0.6 and name_score >= 0.7:
            return (comm, total_score)

    return None

def convert_to_lod():
    """Convert 1921 census data to LOD format with community linkages."""

    print("=" * 60)
    print("Converting 1921 Census Data to Linked Open Data")
    print("=" * 60)

    # Load data
    print("\n1. Loading data...")
    csds_1921 = load_1921_csds()
    communities = load_wikidata_communities()

    # Match CSDs to communities
    print("\n2. Matching CSDs to Wikidata communities...")
    matches = []
    unmatched = []

    for i, csd in enumerate(csds_1921):
        if (i + 1) % 500 == 0:
            print(f"   Processed {i + 1}/{len(csds_1921)} CSDs...")

        match_result = match_csd_to_community(csd, communities)
        if match_result:
            community, score = match_result
            matches.append({
                'csd': csd,
                'community': community,
                'score': score
            })
        else:
            unmatched.append(csd)

    print(f"\n   Matched: {len(matches)} ({len(matches)/len(csds_1921)*100:.1f}%)")
    print(f"   Unmatched: {len(unmatched)} ({len(unmatched)/len(csds_1921)*100:.1f}%)")

    # Write LOD census subdivision file
    print("\n3. Writing LOD census subdivision file...")
    with open('neo4j_communities/e53_census_subdivisions_1921_lod.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'csd_id:ID', ':LABEL', 'tcpuid', 'name', 'province',
            'census_year:int', 'area_sqm:float', 'latitude:float', 'longitude:float',
            'uri', 'matched_community_id', 'match_confidence:float'
        ])

        for match in matches:
            csd = match['csd']
            comm = match['community']

            writer.writerow([
                f"CSD_1921_{csd['tcpuid']}",
                'E53_Place',
                csd['tcpuid'],
                csd['name'],
                csd['province'],
                1921,
                csd['area_sqm'],
                csd['latitude'],
                csd['longitude'],
                f"http://census.ca/csd/{csd['tcpuid']}/1921",  # LOD URI
                comm['place_id:ID'],
                match['score']
            ])

        for csd in unmatched:
            writer.writerow([
                f"CSD_1921_{csd['tcpuid']}",
                'E53_Place',
                csd['tcpuid'],
                csd['name'],
                csd['province'],
                1921,
                csd['area_sqm'],
                csd['latitude'],
                csd['longitude'],
                f"http://census.ca/csd/{csd['tcpuid']}/1921",  # LOD URI
                '',  # No community match
                ''
            ])

    # Write linkage relationships
    print("4. Writing community linkage relationships...")
    with open('neo4j_communities/census_to_community_links.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            ':START_ID', ':END_ID', ':TYPE', 'match_confidence:float',
            'match_method', 'census_year:int'
        ])

        for match in matches:
            csd = match['csd']
            comm = match['community']

            writer.writerow([
                comm['place_id:ID'],  # Community
                f"CSD_1921_{csd['tcpuid']}",  # Census subdivision
                'was_enumerated_as',
                match['score'],
                'automated_fuzzy_match',
                1921
            ])

    # Statistics
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total 1921 CSDs: {len(csds_1921)}")
    print(f"Matched to communities: {len(matches)} ({len(matches)/len(csds_1921)*100:.1f}%)")
    print(f"Unmatched: {len(unmatched)} ({len(unmatched)/len(csds_1921)*100:.1f}%)")

    # Match confidence distribution
    if matches:
        high_conf = sum(1 for m in matches if m['score'] >= 0.9)
        med_conf = sum(1 for m in matches if 0.7 <= m['score'] < 0.9)
        low_conf = sum(1 for m in matches if m['score'] < 0.7)

        print(f"\nMatch confidence:")
        print(f"  High (≥0.9): {high_conf} ({high_conf/len(matches)*100:.1f}%)")
        print(f"  Medium (0.7-0.9): {med_conf} ({med_conf/len(matches)*100:.1f}%)")
        print(f"  Low (<0.7): {low_conf} ({low_conf/len(matches)*100:.1f}%)")

    # Sample matches
    print(f"\nSample high-confidence matches:")
    for match in sorted(matches, key=lambda x: x['score'], reverse=True)[:10]:
        csd = match['csd']
        comm = match['community']
        print(f"  {csd['name']} → {comm['name']} ({comm['wikidata_id']}) - {match['score']:.2f}")

    print(f"\nOutput files:")
    print(f"  - neo4j_communities/e53_census_subdivisions_1921_lod.csv")
    print(f"  - neo4j_communities/census_to_community_links.csv")
    print("\n✅ Done!")

if __name__ == "__main__":
    convert_to_lod()
