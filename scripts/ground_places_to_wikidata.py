#!/usr/bin/env python3
"""
Ground census geography (CDs and CSDs) to Wikidata QIDs.

Phase 1: Use Wikidata REST API (wbsearchentities) to find QIDs for Census
         Divisions (counties). Validate with P131 admin hierarchy.
Phase 2: Use Wikidata SPARQL (one query per CD, 5s delay) to find all places
         within each county, then match to CSDs by name + coordinate validation.
         Saves progress so it can resume after interruption.

Disambiguation: CSD name + CD (county) + province + 1921 centroid lat/lon.
No false positives: every match validated by coordinate distance (<50km).
"""

import httpx
import csv
import json
import time
import math
import argparse
import os
import re
from typing import List, Dict, Tuple, Optional

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
QLEVER_SPARQL = "https://qlever.dev/api/wikidata"
USER_AGENT = "CanadaCensusKG/1.0 (jic823@usask.ca; Canadian census knowledge graph)"

PROV_QID = {
    'ON': 'Q1904', 'QC': 'Q176', 'NS': 'Q1952', 'NB': 'Q1965',
    'MB': 'Q1948', 'SK': 'Q1989', 'AB': 'Q1951', 'BC': 'Q1974',
    'PE': 'Q1979', 'NL': 'Q2003', 'YT': 'Q2009', 'NT': 'Q2007',
}
QID_PROV = {v: k for k, v in PROV_QID.items()}

SKIP_CSD_NAMES = {
    'NO DATA', 'Indian reserves', 'Indian Reserves', 'Réserves Indiennes',
    'Other parts—Autres parties', 'Unorganized territory',
    'Territoire non organisé', 'Unorganized', 'Not given',
}

# P31 types to REJECT when matching CDs.
# Electoral districts share county names but are different entities.
# Also reject obviously wrong entity types.
REJECT_P31 = {
    # Electoral districts (federal + provincial, all provinces)
    'Q17202187',   # federal electoral district of Canada
    'Q3248048',    # federal electoral district in Quebec
    'Q19803541',   # former federal electoral district of Canada
    'Q1147778',    # electoral district (generic)
    'Q2973931',    # provincial electoral district of Quebec
    'Q6592593',    # provincial electoral district of Nova Scotia
    'Q6593033',    # provincial electoral district of Ontario
    'Q6593034',    # provincial electoral district of New Brunswick
    'Q6592999',    # provincial electoral district of Manitoba
    'Q6593005',    # provincial electoral district of British Columbia
    'Q6593042',    # provincial electoral district of Saskatchewan
    'Q6593008',    # provincial electoral district of Alberta
    'Q6593040',    # provincial electoral district of Prince Edward Island
    'Q6593037',    # provincial electoral district of Newfoundland and Labrador
    # Natural features
    'Q4022',       # river
    'Q23397',      # lake
    'Q8502',       # mountain
    'Q23442',      # island (but we keep Manitoulin as special case)
    # Modern statistical entities
    'Q18810091',   # census division of Canada (1991+, no historical continuity)
    # Buildings and other wrong types
    'Q3914',       # school
    'Q110857663',  # jailhouse
    'Q33506',      # museum
    'Q16560',      # palace
    'Q12280',      # bridge
}

MAX_DISTANCE_KM = 50.0
REST_DELAY = 2.0    # seconds between REST API calls
SPARQL_DELAY = 5.0  # seconds between SPARQL queries


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_wkt_point(wkt: str) -> Tuple[float, float]:
    wkt = wkt.replace('Point(', '').replace(')', '').strip()
    parts = wkt.split()
    return float(parts[1]), float(parts[0])


def normalize_name(name: str) -> str:
    name = name.strip().lower()
    # Remove common suffixes
    for suffix in [' parish', ' township', ' county', ' district',
                   ', quebec', ', ontario', ', nova scotia',
                   ' t-v', ', t-v', ' (municipality)']:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    # Remove French prefixes
    for prefix in ['comté de ', "comté d'", 'comté du ']:
        if name.startswith(prefix):
            name = name[len(prefix):]
    # Normalize accents
    name = name.replace('é', 'e').replace('è', 'e').replace('ê', 'e')
    name = name.replace('à', 'a').replace('â', 'a')
    name = name.replace('ô', 'o').replace('î', 'i').replace('û', 'u')
    name = name.replace('ç', 'c').replace('ë', 'e')
    name = name.replace("\u2019", "'").replace("\u2018", "'")
    name = name.replace('st.', 'st').replace('ste.', 'ste')
    # Normalize "saint" variants
    name = name.replace('saint-', 'st ').replace('sainte-', 'ste ')
    name = name.replace('saint ', 'st ').replace('sainte ', 'ste ')
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


# ---------------------------------------------------------------------------
# REST API helpers
# ---------------------------------------------------------------------------

def wikidata_search(query: str, lang: str = 'en', limit: int = 20) -> List[Dict]:
    """Search Wikidata entities by label."""
    resp = httpx.get(WIKIDATA_API, params={
        'action': 'wbsearchentities', 'search': query,
        'language': lang, 'limit': limit, 'format': 'json',
    }, headers={'User-Agent': USER_AGENT}, timeout=30.0)
    resp.raise_for_status()
    return resp.json().get('search', [])


def wikidata_get_entities(qids: List[str]) -> Dict:
    """Fetch entity data for up to 50 QIDs at once."""
    if not qids:
        return {}
    resp = httpx.get(WIKIDATA_API, params={
        'action': 'wbgetentities', 'ids': '|'.join(qids[:50]),
        'props': 'labels|claims|descriptions', 'languages': 'en|fr',
        'format': 'json',
    }, headers={'User-Agent': USER_AGENT}, timeout=30.0)
    resp.raise_for_status()
    return resp.json().get('entities', {})


def entity_p31_types(entity: Dict) -> List[str]:
    """Extract P31 (instance of) QIDs."""
    p31 = entity.get('claims', {}).get('P31', [])
    return [c['mainsnak']['datavalue']['value']['id']
            for c in p31 if c.get('mainsnak', {}).get('datavalue')]


def entity_p131_chain(entity: Dict) -> List[str]:
    """Extract P131 (located in admin entity) QIDs."""
    p131 = entity.get('claims', {}).get('P131', [])
    return [c['mainsnak']['datavalue']['value']['id']
            for c in p131 if c.get('mainsnak', {}).get('datavalue')]


def entity_coords(entity: Dict) -> Tuple[Optional[float], Optional[float]]:
    """Extract P625 coordinates."""
    p625 = entity.get('claims', {}).get('P625', [])
    if p625 and p625[0].get('mainsnak', {}).get('datavalue'):
        v = p625[0]['mainsnak']['datavalue']['value']
        return v['latitude'], v['longitude']
    return None, None


# ---------------------------------------------------------------------------
# SPARQL helper
# ---------------------------------------------------------------------------

def sparql_query(query: str, retries: int = 3) -> List[Dict]:
    """Execute SPARQL with retries and long backoff on rate limit."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    for attempt in range(retries):
        try:
            resp = httpx.get(
                WIKIDATA_SPARQL,
                params={"query": query, "format": "json"},
                headers=headers,
                timeout=120.0,
            )
            if resp.status_code == 429 or resp.status_code == 403:
                wait = 120 * (attempt + 1)
                print(f"    Rate limited ({resp.status_code}). Waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code == 502:
                wait = 30 * (attempt + 1)
                print(f"    Server error (502). Waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["results"]["bindings"]
        except httpx.TimeoutException:
            wait = 30 * (attempt + 1)
            print(f"    Timeout. Waiting {wait}s...")
            time.sleep(wait)
        except Exception as e:
            if attempt < retries - 1:
                wait = 30 * (attempt + 1)
                print(f"    Error: {e}. Waiting {wait}s...")
                time.sleep(wait)
            else:
                raise
    return []


# ---------------------------------------------------------------------------
# QLever SPARQL helper (alternative Wikidata endpoint, no rate limit issues)
# ---------------------------------------------------------------------------

def qlever_query(query: str, retries: int = 3) -> List[Dict]:
    """Execute SPARQL via QLever (needs explicit PREFIXes, no wikibase:label)."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}
    for attempt in range(retries):
        try:
            resp = httpx.get(
                QLEVER_SPARQL, params={"query": query},
                headers=headers, timeout=120.0, follow_redirects=True,
            )
            resp.raise_for_status()
            return resp.json()["results"]["bindings"]
        except Exception as e:
            if attempt < retries - 1:
                wait = 10 * (attempt + 1)
                print(f"    QLever error: {e}. Waiting {wait}s...")
                time.sleep(wait)
            else:
                raise
    return []


# ---------------------------------------------------------------------------
# Phase 1: Bulk-fetch all Canadian counties from QLever, match to our CDs
# ---------------------------------------------------------------------------

# All known P31 types for Canadian counties/districts (real admin entities)
COUNTY_TYPES_QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?item ?labelEn ?labelFr ?provinceQid ?coord ?typeLabel WHERE {
  VALUES ?type {
    wd:Q14763041     # county of Ontario
    wd:Q4204495      # former county of Ontario
    wd:Q13415354     # regional municipality of Ontario
    wd:Q15700461     # district municipality of Ontario
    wd:Q14763130     # district of Ontario (Nipissing, Parry Sound, etc.)
    wd:Q2991491      # historic county of Quebec
    wd:Q2914578      # county of New Brunswick
    wd:Q603715       # county of New Brunswick (alt type)
    wd:Q11774771     # county of Nova Scotia
    wd:Q3518228      # county of Prince Edward Island
  }
  ?item wdt:P31 ?type .
  ?item wdt:P17 wd:Q16 .
  ?item rdfs:label ?labelEn . FILTER(LANG(?labelEn) = "en")
  ?type rdfs:label ?typeLabel . FILTER(LANG(?typeLabel) = "en")
  OPTIONAL { ?item rdfs:label ?labelFr . FILTER(LANG(?labelFr) = "fr") }
  OPTIONAL { ?item wdt:P131 ?provinceQid . }
  OPTIONAL { ?item wdt:P625 ?coord . }
}
"""


def fetch_all_counties_qlever() -> List[Dict]:
    """Fetch all Canadian counties in ONE query via QLever."""
    print("  Querying QLever for all Canadian counties...")
    bindings = qlever_query(COUNTY_TYPES_QUERY)
    print(f"  Got {len(bindings)} rows")

    counties = {}
    for r in bindings:
        qid = r['item']['value'].split('/')[-1]
        label_en = r.get('labelEn', {}).get('value', '')
        label_fr = r.get('labelFr', {}).get('value', '')
        coord = r.get('coord', {}).get('value', '')
        prov_uri = r.get('provinceQid', {}).get('value', '')
        prov_qid = prov_uri.split('/')[-1] if prov_uri else ''
        prov_code = QID_PROV.get(prov_qid, '')
        type_label = r.get('typeLabel', {}).get('value', '')

        if qid not in counties:
            counties[qid] = {
                'qid': qid, 'label_en': label_en, 'label_fr': label_fr,
                'province': prov_code, 'coord': coord, 'type': type_label,
            }

    return list(counties.values())


def run_phase1(cd_csv: str, out_csv: str):
    """Match our CD names to Wikidata counties fetched via QLever."""
    our_cds = []
    with open(cd_csv) as f:
        for row in csv.DictReader(f):
            our_cds.append(row)

    named_cds = [cd for cd in our_cds if not cd['name'].startswith('Division No')]
    print(f"Phase 1: Resolving {len(named_cds)} named CDs")
    print(f"  (Skipping {len(our_cds) - len(named_cds)} numbered divisions)")

    wd_counties = fetch_all_counties_qlever()
    print(f"  Found {len(wd_counties)} county entities in Wikidata\n")

    # Build lookup: normalized name -> Wikidata items, keyed by province
    # Try matching with and without "County"/"District" suffix
    wd_lookup = {}  # (normalized_name, province_code) -> [items]
    for wc in wd_counties:
        prov = wc['province']
        for label in [wc['label_en'], wc['label_fr']]:
            if not label:
                continue
            norm = normalize_name(label)
            key = (norm, prov)
            wd_lookup.setdefault(key, []).append(wc)
            # Also index without province for items with empty province
            if not prov:
                wd_lookup.setdefault((norm, ''), []).append(wc)

    results = []
    matched = 0

    for cd in named_cds:
        cd_id = cd['place_id:ID']
        cd_name = cd['name']
        prov = cd['province']
        norm_cd = normalize_name(cd_name)

        # Try exact match with province
        candidates = wd_lookup.get((norm_cd, prov), [])

        # Try without province (some items have empty P131)
        if not candidates:
            candidates = wd_lookup.get((norm_cd, ''), [])

        # Try matching county names that include "County" in the Wikidata label
        # e.g., our "Frontenac" should match "Frontenac County"
        if not candidates:
            for key, items in wd_lookup.items():
                key_name, key_prov = key
                if key_prov == prov and key_name.startswith(norm_cd + ' '):
                    candidates = items
                    break

        if candidates:
            best = candidates[0]
            results.append({
                'cd_id': cd_id, 'cd_name': cd_name, 'province': prov,
                'wikidata_qid': best['qid'],
                'wikidata_label': best['label_en'],
                'wikidata_type': best['type'],
            })
            matched += 1
            print(f"  {cd_name}, {prov} -> {best['qid']} ({best['label_en']}) [{best['type']}]")
        else:
            results.append({
                'cd_id': cd_id, 'cd_name': cd_name, 'province': prov,
                'wikidata_qid': '', 'wikidata_label': '', 'wikidata_type': '',
            })
            print(f"  {cd_name}, {prov} -> NO MATCH")

    with open(out_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'cd_id', 'cd_name', 'province', 'wikidata_qid',
            'wikidata_label', 'wikidata_type',
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"\nPhase 1 complete: {matched}/{len(named_cds)} CDs matched")
    print(f"Output: {out_csv}")


# ---------------------------------------------------------------------------
# Phase 2: For each CD, SPARQL for places within it, match to CSDs
# ---------------------------------------------------------------------------

def get_places_in_cd(cd_qid: str) -> List[Dict]:
    """QLever SPARQL: all places with P131 = this CD, with coordinates."""
    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?item ?itemLabel ?coord ?instanceLabel WHERE {{
  ?item wdt:P131 wd:{cd_qid} .
  ?item wdt:P625 ?coord .
  ?item rdfs:label ?itemLabel . FILTER(LANG(?itemLabel) = "en")
  OPTIONAL {{
    ?item wdt:P31 ?instance .
    ?instance rdfs:label ?instanceLabel . FILTER(LANG(?instanceLabel) = "en")
  }}
}}
LIMIT 500
"""
    bindings = qlever_query(query)
    places = {}
    for r in bindings:
        qid = r['item']['value'].split('/')[-1]
        label = r.get('itemLabel', {}).get('value', '')
        coord = r.get('coord', {}).get('value', '')
        inst = r.get('instanceLabel', {}).get('value', '')
        if qid not in places:
            places[qid] = {'qid': qid, 'label': label, 'coord': coord, 'types': set()}
        places[qid]['types'].add(inst)
    return list(places.values())


def load_progress(progress_file: str) -> set:
    """Load set of already-processed CD IDs."""
    if os.path.exists(progress_file):
        with open(progress_file) as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def save_progress(progress_file: str, cd_id: str):
    """Append a processed CD ID."""
    with open(progress_file, 'a') as f:
        f.write(cd_id + '\n')


def run_phase2(
    csd_csv: str, cd_matches_csv: str, p89_dir: str,
    centroid_csv: str, out_dir: str,
):
    """Phase 2: SPARQL per county, match CSDs, resume-safe."""
    out_csv = os.path.join(out_dir, 'csd_wikidata_matches.csv')
    unmatched_csv = os.path.join(out_dir, 'csd_wikidata_unmatched.csv')
    progress_file = os.path.join(out_dir, 'phase2_progress.txt')

    # Load data
    csds = {}
    with open(csd_csv) as f:
        for row in csv.DictReader(f):
            csds[row['place_id:ID']] = row['name']

    cd_qids = {}
    with open(cd_matches_csv) as f:
        for row in csv.DictReader(f):
            if row['wikidata_qid']:
                cd_qids[row['cd_id']] = {
                    'qid': row['wikidata_qid'], 'name': row['cd_name'],
                }

    csd_to_cd = {}
    p89_file = os.path.join(p89_dir, 'p89_falls_within_1921.csv')
    with open(p89_file) as f:
        for row in csv.DictReader(f):
            csd_to_cd[row[':START_ID']] = row[':END_ID']

    centroids = {}
    with open(centroid_csv) as f:
        for row in csv.DictReader(f):
            sid = row['space_id:ID'].replace('_1921_centroid', '')
            centroids[sid] = (float(row['latitude:float']), float(row['longitude:float']))

    cd_to_csds = {}
    for csd_id, cd_id in csd_to_cd.items():
        cd_to_csds.setdefault(cd_id, []).append(csd_id)

    # Resume support
    done = load_progress(progress_file)
    todo = sorted(cd_id for cd_id in cd_qids if cd_id in cd_to_csds and cd_id not in done)

    # Open output files in append mode if resuming
    write_mode = 'a' if done else 'w'
    matched_f = open(out_csv, write_mode, newline='')
    unmatched_f = open(unmatched_csv, write_mode, newline='')
    matched_w = csv.DictWriter(matched_f, fieldnames=[
        'csd_id', 'csd_name', 'cd_id', 'cd_name', 'wikidata_qid',
        'wikidata_label', 'wikidata_types', 'distance_km', 'our_lat', 'our_lon',
    ])
    unmatched_w = csv.DictWriter(unmatched_f, fieldnames=[
        'csd_id', 'csd_name', 'cd_id', 'cd_name', 'reason',
    ])
    if not done:
        matched_w.writeheader()
        unmatched_w.writeheader()

    print(f"\nPhase 2: {len(todo)} CDs to process ({len(done)} already done)")
    print(f"  Estimated time: ~{len(todo) * 8 // 60} minutes")
    print(f"  Progress saved to {progress_file} (resume-safe)\n")

    total_matched = 0
    total_unmatched = 0

    for idx, cd_id in enumerate(todo):
        cd_info = cd_qids[cd_id]
        cd_qid = cd_info['qid']
        csd_ids = cd_to_csds.get(cd_id, [])

        try:
            wd_places = get_places_in_cd(cd_qid)
        except Exception as e:
            print(f"  [{idx+1}/{len(todo)}] {cd_info['name']}: SPARQL ERROR: {e}")
            for csd_id in csd_ids:
                name = csds.get(csd_id, '')
                if name not in SKIP_CSD_NAMES and 'reserve' not in name.lower():
                    unmatched_w.writerow({
                        'csd_id': csd_id, 'csd_name': name,
                        'cd_id': cd_id, 'cd_name': cd_info['name'],
                        'reason': f'SPARQL error: {e}',
                    })
            save_progress(progress_file, cd_id)
            time.sleep(SPARQL_DELAY * 3)
            continue

        # Build name lookup
        wd_by_name = {}
        for wp in wd_places:
            norm = normalize_name(wp['label'])
            wd_by_name.setdefault(norm, []).append(wp)

        cd_matched = 0
        cd_unmatched = 0

        for csd_id in csd_ids:
            csd_name = csds.get(csd_id, '')
            if csd_name in SKIP_CSD_NAMES or 'reserve' in csd_name.lower():
                continue

            norm_csd = normalize_name(csd_name)
            candidates = wd_by_name.get(norm_csd, [])

            our_lat, our_lon = centroids.get(csd_id, (None, None))
            if our_lat is None:
                unmatched_w.writerow({
                    'csd_id': csd_id, 'csd_name': csd_name,
                    'cd_id': cd_id, 'cd_name': cd_info['name'],
                    'reason': 'No 1921 centroid',
                })
                cd_unmatched += 1
                continue

            best_match = None
            best_distance = float('inf')
            for cand in candidates:
                if not cand['coord']:
                    continue
                try:
                    wd_lat, wd_lon = parse_wkt_point(cand['coord'])
                    dist = haversine_km(our_lat, our_lon, wd_lat, wd_lon)
                    if dist < best_distance:
                        best_distance = dist
                        best_match = cand
                except (ValueError, IndexError):
                    continue

            if best_match and best_distance <= MAX_DISTANCE_KM:
                matched_w.writerow({
                    'csd_id': csd_id, 'csd_name': csd_name,
                    'cd_id': cd_id, 'cd_name': cd_info['name'],
                    'wikidata_qid': best_match['qid'],
                    'wikidata_label': best_match['label'],
                    'wikidata_types': '; '.join(best_match['types']),
                    'distance_km': round(best_distance, 2),
                    'our_lat': our_lat, 'our_lon': our_lon,
                })
                cd_matched += 1
            else:
                reason = 'No name match in Wikidata'
                if best_match:
                    reason = f'Coord too far: {best_distance:.1f}km'
                unmatched_w.writerow({
                    'csd_id': csd_id, 'csd_name': csd_name,
                    'cd_id': cd_id, 'cd_name': cd_info['name'],
                    'reason': reason,
                })
                cd_unmatched += 1

        total_matched += cd_matched
        total_unmatched += cd_unmatched
        save_progress(progress_file, cd_id)
        matched_f.flush()
        unmatched_f.flush()

        print(f"[{idx+1}/{len(todo)}] {cd_info['name']}: "
              f"{cd_matched} matched, {cd_unmatched} unmatched "
              f"({len(wd_places)} WD places)")
        time.sleep(SPARQL_DELAY)

    matched_f.close()
    unmatched_f.close()

    print(f"\nPhase 2 complete: {total_matched} matched, {total_unmatched} unmatched")
    print(f"Matched:   {out_csv}")
    print(f"Unmatched: {unmatched_csv}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Ground census places to Wikidata QIDs')
    parser.add_argument('--phase', choices=['1', '2', 'both'], default='both')
    parser.add_argument('--crm-dir', default='neo4j_cidoc_crm')
    parser.add_argument('--out-dir', default='wikidata_grounding')
    args = parser.parse_args()

    crm = args.crm_dir
    out = args.out_dir
    os.makedirs(out, exist_ok=True)

    cd_csv = os.path.join(crm, 'e53_place_cd.csv')
    csd_csv = os.path.join(crm, 'e53_place_csd.csv')
    centroid_csv = os.path.join(crm, 'e94_space_primitive_1921.csv')
    cd_matches = os.path.join(out, 'cd_wikidata_matches.csv')

    if args.phase in ('1', 'both'):
        run_phase1(cd_csv, cd_matches)

    if args.phase in ('2', 'both'):
        if not os.path.exists(cd_matches):
            print(f"ERROR: {cd_matches} not found. Run --phase 1 first.")
            return
        run_phase2(csd_csv, cd_matches, crm, centroid_csv, out)


if __name__ == '__main__':
    main()
