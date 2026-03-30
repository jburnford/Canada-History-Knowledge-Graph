#!/usr/bin/env python3
"""
Phase 2: Ground CSDs to Wikidata QIDs.

Strategy:
  1. QLever bulk SPARQL — batch CDs ~20 at a time, fetch all P131 places
  2. Name-match + coordinate validation (< 50 km)
  3. Output matched and unmatched CSDs for MCP follow-up
"""

import csv
import math
import re
import time
import httpx
import os
import json
from collections import defaultdict

QLEVER_SPARQL = "https://qlever.dev/api/wikidata"
USER_AGENT = "CanadaCensusKG/1.0 (jic823@usask.ca)"
MAX_DISTANCE_KM = 50.0
BATCH_SIZE = 20  # CDs per QLever query
QLEVER_DELAY = 2.0  # seconds between queries

# Paths
CRM_DIR = "neo4j_cidoc_crm"
GROUNDING_DIR = "wikidata_grounding"
CD_MATCHES = os.path.join(GROUNDING_DIR, "cd_wikidata_matches.csv")
CSD_FILE = os.path.join(CRM_DIR, "e53_place_csd.csv")
P89_FILE = os.path.join(CRM_DIR, "p89_falls_within_1921.csv")
CENTROID_FILE = os.path.join(CRM_DIR, "e94_space_primitive_1921.csv")

OUT_MATCHED = os.path.join(GROUNDING_DIR, "csd_wikidata_matches.csv")
OUT_UNMATCHED = os.path.join(GROUNDING_DIR, "csd_wikidata_unmatched.csv")
OUT_PROGRESS = os.path.join(GROUNDING_DIR, "phase2_qlever_progress.json")

SKIP_CSD_NAMES = {
    'NO DATA', 'Indian reserves', 'Indian Reserves', 'Réserves Indiennes',
    'Other parts—Autres parties', 'Unorganized territory',
    'Territoire non organisé', 'Unorganized', 'Not given',
}


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def normalize_name(name):
    name = name.strip().lower()
    # Remove CSD type suffixes common in TCP data
    for suffix in [', par.', ', vl', ', t-v', ', c', ', mun.', ' tp.-ct.',
                   ' parish', ' township', ' county', ' district',
                   ', quebec', ', ontario', ', nova scotia',
                   ' (municipality)', ', city', ', town']:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    # Remove trailing parenthetical like "(St. Cyrille, par.)"
    name = re.sub(r'\s*\(.*?\)\s*$', '', name)
    # Normalize accents
    for a, b in [('é','e'),('è','e'),('ê','e'),('à','a'),('â','a'),
                 ('ô','o'),('î','i'),('û','u'),('ç','c'),('ë','e')]:
        name = name.replace(a, b)
    name = name.replace('\u2019', "'").replace('\u2018', "'")
    # Normalize saint/sainte variants (period, hyphen, or space after)
    name = re.sub(r'\bste?[\.\-\s]+', 'st ', name)
    name = re.sub(r'\bsainte?[\-\s]+', 'st ', name)
    # Remove hyphens (key for QC: 'saint-albert-de-warwick' -> 'st albert de warwick')
    name = name.replace('-', ' ')
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


def strip_qualifier(norm):
    """Remove 'de X', 'du X', 'des X', \"d'X\" qualifiers for fallback matching."""
    m = re.match(r"^(.+?)\s+(?:de|du|des|d')\s", norm)
    if m:
        return m.group(1).strip()
    return None


def parse_wkt_point(wkt):
    """Parse 'Point(lon lat)' or 'POINT(lon lat)' -> (lat, lon)"""
    wkt = wkt.replace('POINT(', '').replace('Point(', '').replace(')', '').strip()
    parts = wkt.split()
    return float(parts[1]), float(parts[0])


def qlever_query(query, retries=3):
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


def fetch_places_for_cds(cd_qids):
    """Fetch all places with P131 in the given CD QIDs, with labels + coords."""
    values = " ".join(f"wd:{qid}" for qid in cd_qids)
    query = f"""
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?item ?itemLabelEn ?itemLabelFr ?container ?coord ?typeLabel WHERE {{
  VALUES ?container {{ {values} }}
  ?item wdt:P131 ?container .
  ?item wdt:P625 ?coord .
  ?item rdfs:label ?itemLabelEn . FILTER(LANG(?itemLabelEn) = "en")
  OPTIONAL {{ ?item rdfs:label ?itemLabelFr . FILTER(LANG(?itemLabelFr) = "fr") }}
  OPTIONAL {{
    ?item wdt:P31 ?type .
    ?type rdfs:label ?typeLabel . FILTER(LANG(?typeLabel) = "en")
  }}
}}
"""
    bindings = qlever_query(query)
    places = {}
    for r in bindings:
        qid = r['item']['value'].split('/')[-1]
        container_qid = r['container']['value'].split('/')[-1]
        label_en = r.get('itemLabelEn', {}).get('value', '')
        label_fr = r.get('itemLabelFr', {}).get('value', '')
        coord = r.get('coord', {}).get('value', '')
        type_label = r.get('typeLabel', {}).get('value', '')

        key = (qid, container_qid)
        if key not in places:
            places[key] = {
                'qid': qid, 'label_en': label_en, 'label_fr': label_fr,
                'container_qid': container_qid, 'coord': coord, 'types': set(),
            }
        if type_label:
            places[key]['types'].add(type_label)

    return list(places.values())


def load_data():
    """Load all CSD, CD, centroid, and hierarchy data."""
    # CSDs
    csds = {}
    with open(CSD_FILE) as f:
        for row in csv.DictReader(f):
            csds[row['place_id:ID']] = row['name']

    # CD QIDs
    cd_qids = {}  # cd_id -> {qid, name}
    qid_to_cd = {}  # wikidata_qid -> cd_id
    with open(CD_MATCHES) as f:
        for row in csv.DictReader(f):
            if row['wikidata_qid']:
                cd_qids[row['cd_id']] = {
                    'qid': row['wikidata_qid'], 'name': row['cd_name'],
                }
                qid_to_cd[row['wikidata_qid']] = row['cd_id']

    # CSD -> CD hierarchy (1921)
    csd_to_cd = {}
    with open(P89_FILE) as f:
        for row in csv.DictReader(f):
            csd_to_cd[row[':START_ID']] = row[':END_ID']

    # Centroids (1921)
    centroids = {}
    with open(CENTROID_FILE) as f:
        for row in csv.DictReader(f):
            sid = row['space_id:ID'].replace('_1921_centroid', '')
            centroids[sid] = (float(row['latitude:float']), float(row['longitude:float']))

    # Group CSDs by CD
    cd_to_csds = defaultdict(list)
    for csd_id, cd_id in csd_to_cd.items():
        cd_to_csds[cd_id].append(csd_id)

    return csds, cd_qids, qid_to_cd, csd_to_cd, centroids, cd_to_csds


def load_progress():
    if os.path.exists(OUT_PROGRESS):
        with open(OUT_PROGRESS) as f:
            return json.load(f)
    return {"done_cds": [], "matched": [], "unmatched": []}


def save_progress(progress):
    with open(OUT_PROGRESS, 'w') as f:
        json.dump(progress, f, indent=2)


def build_name_index(wd_places):
    """Build name lookup from Wikidata places, including qualifier-stripped variants."""
    wd_by_name = defaultdict(list)
    for wp in wd_places:
        for label in [wp.get('label_en', ''), wp.get('label_fr', '')]:
            if label:
                norm = normalize_name(label)
                wd_by_name[norm].append(wp)
                stripped = strip_qualifier(norm)
                if stripped:
                    wd_by_name[stripped].append(wp)
    return wd_by_name


def match_csd(csd_name, wd_by_name, our_lat, our_lon):
    """Try to match a CSD name against Wikidata name index. Returns (match, distance) or (None, None)."""
    norm_csd = normalize_name(csd_name)
    candidates = wd_by_name.get(norm_csd, [])

    # Fallback: strip qualifier from our name too
    if not candidates:
        stripped = strip_qualifier(norm_csd)
        if stripped:
            candidates = wd_by_name.get(stripped, [])

    if not candidates or our_lat is None:
        return None, None

    best_match = None
    best_distance = float('inf')
    for cand in candidates:
        if not cand.get('coord'):
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
        return best_match, best_distance
    return None, best_distance if best_match else None


QC_PLACE_TYPES_QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?item ?labelEn ?labelFr ?coord ?typeLabel WHERE {
  VALUES ?type {
    wd:Q27676428   wd:Q27676416   wd:Q27676524
    wd:Q23019040   wd:Q81066200   wd:Q17143723
  }
  ?item wdt:P31 ?type .
  ?item wdt:P625 ?coord .
  ?item wdt:P17 wd:Q16 .
  ?item rdfs:label ?labelEn . FILTER(LANG(?labelEn) = "en")
  OPTIONAL { ?item rdfs:label ?labelFr . FILTER(LANG(?labelFr) = "fr") }
  ?type rdfs:label ?typeLabel . FILTER(LANG(?typeLabel) = "en")
}
"""


def fetch_qc_places():
    """Fetch all QC municipalities/townships/parishes from QLever in one query."""
    print("  Fetching all QC places from QLever...")
    bindings = qlever_query(QC_PLACE_TYPES_QUERY)
    places = {}
    for r in bindings:
        qid = r['item']['value'].split('/')[-1]
        if qid not in places:
            places[qid] = {
                'qid': qid,
                'label_en': r.get('labelEn', {}).get('value', ''),
                'label_fr': r.get('labelFr', {}).get('value', ''),
                'coord': r.get('coord', {}).get('value', ''),
                'types': set(),
            }
        type_label = r.get('typeLabel', {}).get('value', '')
        if type_label:
            places[qid]['types'].add(type_label)
    print(f"  Got {len(places)} unique QC places")
    return list(places.values())


def main():
    os.makedirs(GROUNDING_DIR, exist_ok=True)
    csds, cd_qids, qid_to_cd, csd_to_cd, centroids, cd_to_csds = load_data()
    progress = load_progress()

    done_cds = set(progress["done_cds"])
    matched_csd_ids = set(m['csd_id'] for m in progress["matched"])

    # =====================================================================
    # Path A: CDs with QIDs (non-QC) — P131 queries batched by CD
    # =====================================================================
    non_qc_cds = sorted(
        cd_id for cd_id in cd_qids
        if cd_id in cd_to_csds and cd_id not in done_cds
        and not cd_id.startswith('CD_QC_')
    )

    if non_qc_cds:
        print(f"Path A: {len(non_qc_cds)} non-QC CDs to process via P131")
        print(f"  CSDs in scope: {sum(len(cd_to_csds[cd]) for cd in non_qc_cds)}")

        batches = [non_qc_cds[i:i+BATCH_SIZE] for i in range(0, len(non_qc_cds), BATCH_SIZE)]
        print(f"  QLever batches: {len(batches)}")

        for batch_idx, batch_cds in enumerate(batches):
            batch_qids = [cd_qids[cd_id]['qid'] for cd_id in batch_cds]
            batch_names = [cd_qids[cd_id]['name'] for cd_id in batch_cds]
            print(f"Batch {batch_idx+1}/{len(batches)}: {', '.join(batch_names[:5])}{'...' if len(batch_names) > 5 else ''}")

            try:
                wd_places = fetch_places_for_cds(batch_qids)
            except Exception as e:
                print(f"  ERROR: {e}")
                for cd_id in batch_cds:
                    for csd_id in cd_to_csds.get(cd_id, []):
                        name = csds.get(csd_id, '')
                        if name not in SKIP_CSD_NAMES and 'reserve' not in name.lower():
                            progress["unmatched"].append({
                                'csd_id': csd_id, 'csd_name': name,
                                'cd_id': cd_id, 'cd_name': cd_qids[cd_id]['name'],
                                'reason': f'QLever error: {e}',
                            })
                    progress["done_cds"].append(cd_id)
                save_progress(progress)
                time.sleep(QLEVER_DELAY * 3)
                continue

            print(f"  Got {len(wd_places)} Wikidata places")

            wd_by_container = defaultdict(list)
            for wp in wd_places:
                wd_by_container[wp['container_qid']].append(wp)

            batch_matched = 0
            batch_unmatched = 0

            for cd_id in batch_cds:
                cd_qid = cd_qids[cd_id]['qid']
                cd_name = cd_qids[cd_id]['name']
                cd_places = wd_by_container.get(cd_qid, [])
                wd_by_name = build_name_index(cd_places)

                for csd_id in cd_to_csds.get(cd_id, []):
                    csd_name = csds.get(csd_id, '')
                    if csd_name in SKIP_CSD_NAMES or 'reserve' in csd_name.lower():
                        continue

                    our_lat, our_lon = centroids.get(csd_id, (None, None))
                    if our_lat is None:
                        progress["unmatched"].append({
                            'csd_id': csd_id, 'csd_name': csd_name,
                            'cd_id': cd_id, 'cd_name': cd_name,
                            'reason': 'No 1921 centroid',
                        })
                        batch_unmatched += 1
                        continue

                    best, dist = match_csd(csd_name, wd_by_name, our_lat, our_lon)
                    if best:
                        progress["matched"].append({
                            'csd_id': csd_id, 'csd_name': csd_name,
                            'cd_id': cd_id, 'cd_name': cd_name,
                            'wikidata_qid': best['qid'],
                            'wikidata_label': best.get('label_en') or best.get('label_fr', ''),
                            'wikidata_types': '; '.join(sorted(best.get('types', set()))),
                            'distance_km': round(dist, 2),
                            'our_lat': our_lat, 'our_lon': our_lon,
                        })
                        matched_csd_ids.add(csd_id)
                        batch_matched += 1
                    else:
                        reason = 'No name match in Wikidata'
                        if dist is not None:
                            reason = f'Coord too far: {dist:.1f}km'
                        progress["unmatched"].append({
                            'csd_id': csd_id, 'csd_name': csd_name,
                            'cd_id': cd_id, 'cd_name': cd_name,
                            'reason': reason,
                        })
                        batch_unmatched += 1

                progress["done_cds"].append(cd_id)

            save_progress(progress)
            print(f"  Matched: {batch_matched}, Unmatched: {batch_unmatched}")
            time.sleep(QLEVER_DELAY)

    # =====================================================================
    # Path B: Quebec CSDs — province-level query (P131 -> RCMs, not counties)
    # =====================================================================
    qc_cds = sorted(
        cd_id for cd_id in cd_to_csds
        if cd_id.startswith('CD_QC_') and cd_id not in done_cds
    )

    if qc_cds:
        qc_csd_ids = []
        for cd_id in qc_cds:
            for csd_id in cd_to_csds[cd_id]:
                name = csds.get(csd_id, '')
                if name not in SKIP_CSD_NAMES and 'reserve' not in name.lower():
                    qc_csd_ids.append((csd_id, cd_id))

        print(f"\nPath B: {len(qc_cds)} QC CDs, {len(qc_csd_ids)} CSDs to match via province query")

        try:
            qc_places = fetch_qc_places()
            wd_by_name = build_name_index(qc_places)

            qc_matched = 0
            qc_unmatched = 0

            for csd_id, cd_id in qc_csd_ids:
                csd_name = csds.get(csd_id, '')
                cd_name = cd_qids.get(cd_id, {}).get('name', cd_id)
                our_lat, our_lon = centroids.get(csd_id, (None, None))

                if our_lat is None:
                    progress["unmatched"].append({
                        'csd_id': csd_id, 'csd_name': csd_name,
                        'cd_id': cd_id, 'cd_name': cd_name,
                        'reason': 'No 1921 centroid',
                    })
                    qc_unmatched += 1
                    continue

                best, dist = match_csd(csd_name, wd_by_name, our_lat, our_lon)
                if best:
                    progress["matched"].append({
                        'csd_id': csd_id, 'csd_name': csd_name,
                        'cd_id': cd_id, 'cd_name': cd_name,
                        'wikidata_qid': best['qid'],
                        'wikidata_label': best.get('label_en') or best.get('label_fr', ''),
                        'wikidata_types': '; '.join(sorted(best.get('types', set()))),
                        'distance_km': round(dist, 2),
                        'our_lat': our_lat, 'our_lon': our_lon,
                    })
                    matched_csd_ids.add(csd_id)
                    qc_matched += 1
                else:
                    reason = 'No name match in Wikidata'
                    if dist is not None:
                        reason = f'Coord too far: {dist:.1f}km'
                    progress["unmatched"].append({
                        'csd_id': csd_id, 'csd_name': csd_name,
                        'cd_id': cd_id, 'cd_name': cd_name,
                        'reason': reason,
                    })
                    qc_unmatched += 1

            for cd_id in qc_cds:
                progress["done_cds"].append(cd_id)
            save_progress(progress)
            print(f"  QC matched: {qc_matched}, unmatched: {qc_unmatched}")

        except Exception as e:
            print(f"  QC ERROR: {e}")

    # =====================================================================
    # Path C: Prairie + BC CSDs — province-level query (minted-URI CDs)
    # =====================================================================
    PRAIRIE_BC_PROVS = {'SK', 'AB', 'MB', 'BC'}
    prairie_bc_cds = sorted(
        cd_id for cd_id in cd_to_csds
        if cd_id not in done_cds
        and any(cd_id.startswith(f'CD_{p}_') for p in PRAIRIE_BC_PROVS)
        and cd_id not in cd_qids  # minted-URI CDs only
    )

    if prairie_bc_cds:
        # Collect all CSDs from these CDs
        pbc_csd_ids = []
        for cd_id in prairie_bc_cds:
            for csd_id in cd_to_csds[cd_id]:
                name = csds.get(csd_id, '')
                if name not in SKIP_CSD_NAMES and 'reserve' not in name.lower():
                    pbc_csd_ids.append((csd_id, cd_id))

        print(f"\nPath C: {len(prairie_bc_cds)} prairie/BC CDs, {len(pbc_csd_ids)} CSDs")

        # Load pre-fetched Wikidata places
        pbc_places = []
        for fname in ['prairie_bc_wikidata_places.json', 'bc_wikidata_places.json']:
            fpath = os.path.join(GROUNDING_DIR, fname)
            if os.path.exists(fpath):
                with open(fpath) as f:
                    data = json.load(f)
                    # Convert types back to sets
                    for p in data:
                        if isinstance(p.get('types'), list):
                            p['types'] = set(p['types'])
                    pbc_places.extend(data)
                    print(f"  Loaded {len(data)} places from {fname}")

        if pbc_places:
            # Index by province + normalized name (including RM-stripped)
            wd_by_prov = defaultdict(lambda: defaultdict(list))
            for wp in pbc_places:
                prov = wp.get('province', '')
                for label in [wp.get('label_en', ''), wp.get('label_fr', '')]:
                    if label:
                        norm = normalize_name(label)
                        wd_by_prov[prov][norm].append(wp)
                        # RM-stripped: "Rural Municipality of X No. Y" -> "x"
                        low = label.lower()
                        rm_norm = re.sub(r'^(rural municipality of|municipality of|municipal district of)\s+', '', low)
                        rm_norm = re.sub(r'\s+no\.\s*\d+$', '', rm_norm)
                        rm_norm = rm_norm.replace('-', ' ').strip()
                        if rm_norm != norm:
                            wd_by_prov[prov][rm_norm].append(wp)

            pbc_matched = 0
            pbc_unmatched = 0

            for csd_id, cd_id in pbc_csd_ids:
                csd_name = csds.get(csd_id, '')
                cd_name = cd_id  # minted CDs don't have a nice name in cd_qids
                prov = csd_id[:2]
                our_lat, our_lon = centroids.get(csd_id, (None, None))

                if our_lat is None:
                    progress["unmatched"].append({
                        'csd_id': csd_id, 'csd_name': csd_name,
                        'cd_id': cd_id, 'cd_name': cd_name,
                        'reason': 'No 1921 centroid',
                    })
                    pbc_unmatched += 1
                    continue

                wd_names = wd_by_prov[prov]
                norm_csd = normalize_name(csd_name)
                candidates = wd_names.get(norm_csd, [])

                # SK RM fallback: strip leading number "5. Estevan" -> "estevan"
                if not candidates and prov == 'SK':
                    m = re.match(r'^\d+\.\s*(.+)', csd_name)
                    if m:
                        rm_norm = normalize_name(m.group(1))
                        candidates = wd_names.get(rm_norm, [])

                # Qualifier fallback
                if not candidates:
                    stripped = strip_qualifier(norm_csd)
                    if stripped:
                        candidates = wd_names.get(stripped, [])

                best, dist = None, None
                best_distance = float('inf')
                for cand in candidates:
                    if not cand.get('coord'):
                        continue
                    try:
                        wd_lat, wd_lon = parse_wkt_point(cand['coord'])
                        d = haversine_km(our_lat, our_lon, wd_lat, wd_lon)
                        if d < best_distance:
                            best_distance = d
                            best = cand
                    except (ValueError, IndexError):
                        continue

                if best and best_distance <= MAX_DISTANCE_KM:
                    progress["matched"].append({
                        'csd_id': csd_id, 'csd_name': csd_name,
                        'cd_id': cd_id, 'cd_name': cd_name,
                        'wikidata_qid': best['qid'],
                        'wikidata_label': best.get('label_en') or best.get('label_fr', ''),
                        'wikidata_types': '; '.join(sorted(best.get('types', set()))),
                        'distance_km': round(best_distance, 2),
                        'our_lat': our_lat, 'our_lon': our_lon,
                    })
                    matched_csd_ids.add(csd_id)
                    pbc_matched += 1
                else:
                    reason = 'No name match in Wikidata'
                    if best:
                        reason = f'Coord too far: {best_distance:.1f}km'
                    progress["unmatched"].append({
                        'csd_id': csd_id, 'csd_name': csd_name,
                        'cd_id': cd_id, 'cd_name': cd_name,
                        'reason': reason,
                    })
                    pbc_unmatched += 1

            for cd_id in prairie_bc_cds:
                progress["done_cds"].append(cd_id)
            save_progress(progress)
            print(f"  Prairie/BC matched: {pbc_matched}, unmatched: {pbc_unmatched}")

    # =====================================================================
    # Write final CSVs
    # =====================================================================
    with open(OUT_MATCHED, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'csd_id', 'csd_name', 'cd_id', 'cd_name', 'wikidata_qid',
            'wikidata_label', 'wikidata_types', 'distance_km', 'our_lat', 'our_lon',
        ])
        writer.writeheader()
        writer.writerows(progress["matched"])

    with open(OUT_UNMATCHED, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'csd_id', 'csd_name', 'cd_id', 'cd_name', 'reason',
        ])
        writer.writeheader()
        writer.writerows(progress["unmatched"])

    print(f"\nPhase 2 complete:")
    print(f"  Matched:   {len(progress['matched'])} -> {OUT_MATCHED}")
    print(f"  Unmatched: {len(progress['unmatched'])} -> {OUT_UNMATCHED}")


if __name__ == '__main__':
    main()
