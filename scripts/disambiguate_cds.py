#!/usr/bin/env python3
"""
Census Division (CD) disambiguation support script.

Manages the queue of CDs needing Wikidata QID verification via MCP vector
search. Used with the /cd-disambig Claude Code skill.

Mirrors disambiguate_csds.py with these adaptations:
  - 579 CDs total (one row per place_id in e53_place_cd.csv).
  - Single priority tier: every CD goes through MCP search + verification.
    The existing cd_wikidata_matches.csv is shown as a SEED hint, never
    adopted without re-verification (REST/SPARQL match rate is unreliable
    for entity disambiguation).
  - GOOD_P31_QIDS targets county / district / regional county municipality
    types, not settlement types.
  - MAX_DISTANCE_KM = 100 (CDs are larger than CSDs; 50 km is too tight).
  - Centroids loaded from e94_space_primitive_cd_1921.csv (with fallback
    to other census years if 1921 row missing).

Usage:
    python3 scripts/disambiguate_cds.py --prepare      Build queue from e53_place_cd.csv + seed CSV
    python3 scripts/disambiguate_cds.py --show-batch N Show next N CDs to process
    python3 scripts/disambiguate_cds.py --verify       Batch-verify all QIDs via Wikidata API
    python3 scripts/disambiguate_cds.py --status       Report progress
"""

import argparse
import csv
import json
import math
import sys
import time
import urllib.request
import urllib.error
from collections import Counter
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
GROUNDING_DIR = REPO_DIR / "wikidata_grounding"
CIDOC_DIR = REPO_DIR / "neo4j_cidoc_crm_v2"

E53_CD = CIDOC_DIR / "e53_place_cd.csv"
SEED_CSV = GROUNDING_DIR / "cd_wikidata_matches.csv"
QUEUE_FILE = GROUNDING_DIR / "cd_disambig_queue.jsonl"
VERIFIED_FILE = GROUNDING_DIR / "cd_verified_matches.jsonl"

CENTROID_YEARS = ["1921", "1911", "1901", "1891", "1881", "1871", "1861", "1851"]

# Acceptable P31 (instance of) types for CDs.
# CDs are mid-level administrative regions: counties, regional county
# municipalities (MRCs), districts, etc. NOT settlements.
GOOD_P31_QIDS = {
    # Generic county / district types
    "Q28575",       # county (generic)
    "Q149621",      # district
    "Q5341295",     # county of Canada (former)
    "Q4116211",     # county of Canada
    "Q18810091",    # census division of Canada (umbrella type for any CD)
    "Q82794",       # region (used by Labrador and other geographic CDs)
    # Ontario
    "Q14763130",    # district of Ontario (actual modern QID)
    "Q14763041",    # county of Ontario (actual modern QID)
    "Q14762890",    # regional municipality of Ontario (actual modern QID)
    "Q14762300",    # single-tier municipality (used by post-amalgamation counties)
    "Q16295254",    # upper-tier municipality (used by Ontario counties)
    "Q1799794",     # district of Ontario (legacy QID, may still appear)
    "Q1647195",     # former county of Ontario (legacy)
    "Q3271856",     # county of Ontario (legacy)
    "Q15640019",    # regional municipality of Ontario (legacy)
    "Q11688081",    # united counties of Ontario
    "Q2576666",     # single-tier municipality (Ontario CDs sometimes)
    "Q15640053",    # lower-tier municipality of Ontario (rare for CD level but possible)
    "Q124367008",   # historical county of Ontario (alternate)
    "Q4204495",     # former county of Ontario (Addington's P31)
    # Quebec
    "Q1191257",     # regional county municipality (MRC)
    "Q2989456",     # historic county of Quebec
    "Q186103",      # administrative region of Quebec
    "Q2989455",     # county of Quebec
    "Q3464914",     # equivalent territory (Quebec MRC-equivalent)
    # Maritimes
    "Q5341295",     # county of Canada (former)
    "Q11774771",    # county of Nova Scotia (current)
    "Q1136208",     # county of Nova Scotia (legacy)
    "Q66096059",    # county of Nova Scotia (alternate)
    "Q603715",      # county of New Brunswick (current)
    "Q1191601",     # county of New Brunswick (legacy)
    "Q499387",      # county of Prince Edward Island
    "Q2006290",     # specific PEI county type
    # Western
    "Q3327878",     # census division of Manitoba
    "Q7656238",     # census division of Saskatchewan
    "Q1334655",     # census division of Alberta
    "Q3271856",     # county of Alberta (alternate)
    "Q1153308",     # municipal district of Alberta (sometimes used as CD)
    # BC
    "Q1779467",     # regional district of British Columbia
    # Territories
    "Q35657",       # territory (NT/YT/NU)
    "Q3504085",     # district of Northwest Territories
    "Q5283563",     # district of the Northwest Territories (pre-1905 provisional districts)
    "Q9357527",     # territory of Canada (modern NT/YT/NU)
    # Islands (NL Newfoundland is an island)
    "Q23442",       # island
    # Province aggregates (TCP CDs that cover the whole province)
    "Q11828004",    # province of Canada
    "Q3750285",     # member state-like NS type (alternate)
    # Regional municipalities used for Halifax NS as a CD
    "Q1388464",     # regional municipality in Canada
    "Q1907114",     # metropolitan area
    # Allow city when CD is coterminous with a single city (Toronto, City—Cité)
    "Q515",         # city
    "Q3957",        # town
    "Q15284",       # municipality
    "Q21507383",    # provincial or territorial capital city in Canada
    "Q1549591",     # big city
    "Q1549591",     # big city (dup ok)
    # Generic admin entity (catch for new types)
    "Q56061",       # administrative territorial entity
    "Q15642541",    # human-geographic territorial entity
}

# Province → set of accepted Wikidata QIDs (for P131 chain verification).
PROVINCE_QIDS = {
    "AB": {"Q1951"},          # Alberta
    "BC": {"Q1974", "Q1973"}, # British Columbia
    "MB": {"Q1948"},          # Manitoba
    "NB": {"Q1965"},          # New Brunswick
    "NL": {"Q1969", "Q2003"}, # Newfoundland and Labrador (Q2003 is current province; Q1969 is historic)
    "NS": {"Q1952"},          # Nova Scotia
    "ON": {"Q1904"},          # Ontario
    "PE": {"Q1959", "Q1978"},  # Prince Edward Island
    "QC": {"Q176"},           # Quebec
    "SK": {"Q1989"},          # Saskatchewan
    "NT": {"Q2007"},          # Northwest Territories (modern)
    "YT": {"Q2009"},          # Yukon
    "NU": {"Q1880"},          # Nunavut
}

# CDs are larger than CSDs; allow more slack on coordinate distance.
MAX_DISTANCE_KM = 100

# Entity types that are ALWAYS wrong for a CD.
BAD_TYPES = {
    "weather station", "railway station", "river", "lake",
    "mountain", "metro station", "subway station",
    "archaeological site",
}


def haversine(lat1, lon1, lat2, lon2):
    """Haversine distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def load_cds():
    """Load all CDs from e53_place_cd.csv. Returns list of dicts."""
    rows = []
    with open(E53_CD) as f:
        for r in csv.DictReader(f):
            rows.append({
                "cd_id": r["place_id:ID"],
                "name": r["name"],
                "province": r["province"],
            })
    return rows


def load_seed():
    """Load seed QID hints from cd_wikidata_matches.csv. Returns {cd_id: dict}."""
    out = {}
    if not SEED_CSV.exists():
        return out
    with open(SEED_CSV) as f:
        for r in csv.DictReader(f):
            cd_id = r["cd_id"]
            wd_type = r.get("wikidata_type", "") or ""
            qid = (r.get("wikidata_qid", "") or "").strip()
            mint_reason = ""
            if wd_type.startswith("MINTED_URI:"):
                mint_reason = wd_type.split(":", 1)[1].strip()
            out[cd_id] = {
                "seed_qid": qid or None,
                "seed_label": r.get("wikidata_label", "") or None,
                "seed_type": wd_type or None,
                "seed_mint_reason": mint_reason or None,
            }
    return out


def load_centroids():
    """Build {cd_id: (lat, lon)} from e94_space_primitive_cd_<year>.csv files.

    CDs may not have a 1921 presence (e.g., NT districts before 1905), so we
    fall back across years and pick the first available centroid.
    """
    centroids = {}
    for year in CENTROID_YEARS:
        path = CIDOC_DIR / f"e94_space_primitive_cd_{year}.csv"
        if not path.exists():
            continue
        with open(path) as f:
            for r in csv.DictReader(f):
                # space_id format: CD_<prov>_<name>_<year>_SPACE
                space_id = r["space_id:ID"]
                # Strip trailing _<year>_SPACE to recover the cd_id
                suffix = f"_{year}_SPACE"
                if not space_id.endswith(suffix):
                    continue
                cd_id = space_id[: -len(suffix)]
                if cd_id in centroids:
                    continue
                try:
                    centroids[cd_id] = (float(r["latitude:float"]),
                                         float(r["longitude:float"]))
                except (ValueError, KeyError):
                    pass
    return centroids


def load_verified():
    """Load verified matches JSONL."""
    verified = {}
    if VERIFIED_FILE.exists():
        with open(VERIFIED_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    verified[rec["cd_id"]] = rec
    return verified


def load_queue():
    """Load disambiguation queue."""
    queue = []
    if QUEUE_FILE.exists():
        with open(QUEUE_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    queue.append(json.loads(line))
    return queue


def prepare(args):
    """Build the CD disambiguation queue."""
    cds = load_cds()
    seed = load_seed()
    centroids = load_centroids()
    verified = load_verified()

    queue = []
    stats = Counter()
    for cd in cds:
        cd_id = cd["cd_id"]
        if cd_id in verified:
            stats["already_verified"] += 1
            continue
        s = seed.get(cd_id, {})
        lat, lon = centroids.get(cd_id, (None, None))
        item = {
            "cd_id": cd_id,
            "cd_name": cd["name"],
            "province": cd["province"],
            "seed_qid": s.get("seed_qid"),
            "seed_label": s.get("seed_label"),
            "seed_type": s.get("seed_type"),
            "seed_mint_reason": s.get("seed_mint_reason"),
            "lat": lat,
            "lon": lon,
        }
        queue.append(item)
        if s.get("seed_mint_reason"):
            stats["seed_mint_uri"] += 1
        elif s.get("seed_qid"):
            stats["seed_qid"] += 1
        else:
            stats["no_seed"] += 1

    queue.sort(key=lambda x: (x["province"], x["cd_name"]))
    with open(QUEUE_FILE, "w") as f:
        for item in queue:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"Queue built: {len(queue)} CDs to process")
    print(f"  With seed QID (re-verify):    {stats['seed_qid']}")
    print(f"  With seed MINTED_URI hint:    {stats['seed_mint_uri']}")
    print(f"  No seed (full search needed): {stats['no_seed']}")
    print(f"  Already verified (skipped):   {stats['already_verified']}")
    print(f"\nQueue file: {QUEUE_FILE.relative_to(REPO_DIR)}")
    print(f"Centroids loaded: {len(centroids)}")


def show_batch(args):
    """Show next N CDs from the queue that haven't been verified."""
    n = args.count or 25
    queue = load_queue()
    verified = load_verified()

    pending = [q for q in queue if q["cd_id"] not in verified]

    if getattr(args, "provinces", None):
        provs = {p.strip().upper() for p in args.provinces.split(",") if p.strip()}
        pending = [q for q in pending if q["province"] in provs]

    if not pending:
        print("All CDs have been verified!")
        return

    batch = pending[:n]
    print(f"Next {len(batch)} CDs to process (of {len(pending)} remaining):\n")

    current_prov = None
    for item in batch:
        if item["province"] != current_prov:
            current_prov = item["province"]
            print(f"\n--- {current_prov} ---")
        seed_str = ""
        if item.get("seed_mint_reason"):
            seed_str = f"  SEED: MINT_URI ({item['seed_mint_reason']})"
        elif item.get("seed_qid"):
            seed_str = (f"  SEED: {item['seed_qid']} \"{item['seed_label']}\""
                         f" [{item['seed_type']}]")
        else:
            seed_str = "  SEED: (none)"
        coord_str = ""
        if item.get("lat") and item.get("lon"):
            coord_str = f"  centroid=({item['lat']:.4f},{item['lon']:.4f})"
        print(f"  {item['cd_id']}  \"{item['cd_name']}\"{coord_str}")
        print(f"    {seed_str}")


def fetch_wikidata_entities(qids):
    """Fetch entity data from Wikidata API in batches of 50."""
    results = {}
    for i in range(0, len(qids), 50):
        batch = qids[i:i + 50]
        ids_str = "|".join(batch)
        url = (f"https://www.wikidata.org/w/api.php?"
               f"action=wbgetentities&ids={ids_str}"
               f"&props=labels|descriptions|claims&languages=en&format=json")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CD-Disambig/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                if "entities" in data:
                    results.update(data["entities"])
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            print(f"  API error for batch {i}: {e}", file=sys.stderr)
        if i + 50 < len(qids):
            time.sleep(1)
    return results


def _entity_p131(entity):
    out = []
    for claim in entity.get("claims", {}).get("P131", []):
        v = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(v, dict) and "id" in v:
            out.append(v["id"])
    return out


def _entity_coord(entity):
    for claim in entity.get("claims", {}).get("P625", []):
        v = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(v, dict) and "latitude" in v:
            return float(v["latitude"]), float(v["longitude"])
    return None


def _reaches_province(start_qid, target_prov_qids, all_entities, max_depth=5):
    seen = set()
    stack = [(start_qid, 0)]
    while stack:
        qid, depth = stack.pop()
        if qid in target_prov_qids:
            return True
        if depth >= max_depth or qid in seen:
            continue
        seen.add(qid)
        ent = all_entities.get(qid)
        if not ent:
            continue
        for parent in _entity_p131(ent):
            stack.append((parent, depth + 1))
    return False


def verify(args):
    """Batch-verify all verified matches against Wikidata API."""
    verified = load_verified()
    if not verified:
        print("No verified matches to check.")
        return

    centroids = load_centroids()

    qids = list(set(v["wikidata_qid"] for v in verified.values()
                    if v.get("wikidata_qid") and v.get("status") == "matched"))
    print(f"Verifying {len(qids)} unique QIDs from {len(verified)} matches...")

    entities = fetch_wikidata_entities(qids)

    province_qid_set = set()
    for s in PROVINCE_QIDS.values():
        province_qid_set.update(s)
    for hop in range(1, 5):
        needed = set()
        for ent in list(entities.values()):
            for parent in _entity_p131(ent):
                if parent not in entities and parent not in province_qid_set:
                    needed.add(parent)
        if not needed:
            break
        print(f"Resolving {len(needed)} P131 parents (hop {hop})...")
        entities.update(fetch_wikidata_entities(sorted(needed)))

    good = 0
    warnings = 0
    bad = 0
    bad_records = []

    for cd_id, match in sorted(verified.items()):
        if match.get("status") != "matched":
            continue
        qid = match.get("wikidata_qid")
        if not qid:
            continue

        if qid not in entities:
            msg = f"MISSING: {cd_id} → {qid} (not found in Wikidata)"
            print(f"  {msg}")
            bad += 1
            bad_records.append(msg)
            continue

        entity = entities[qid]
        wd_label = entity.get("labels", {}).get("en", {}).get("value", "")
        wd_desc = entity.get("descriptions", {}).get("en", {}).get("value", "")
        our_label = match.get("wikidata_label", "")

        is_bad = False

        # Label sanity check
        if wd_label.lower() != our_label.lower():
            if not (wd_label.lower() in our_label.lower()
                    or our_label.lower() in wd_label.lower()):
                print(f"  LABEL MISMATCH: {cd_id} → {qid}: "
                      f"we have \"{our_label}\", Wikidata has \"{wd_label}\"")
                warnings += 1

        # P31 type check
        p31_qids = set()
        for claim in entity.get("claims", {}).get("P31", []):
            v = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(v, dict) and "id" in v:
                p31_qids.add(v["id"])
        if p31_qids and not p31_qids.intersection(GOOD_P31_QIDS):
            msg = (f"BAD TYPE: {cd_id} \"{match['cd_name']}\" → {qid} "
                   f"\"{wd_label}\" ({wd_desc}) P31={p31_qids}")
            print(f"  {msg}")
            is_bad = True
            bad_records.append(msg)

        # P131 province check
        prov = match.get("province") or cd_id.split("_")[1]
        target_set = PROVINCE_QIDS.get(prov)
        if target_set:
            if not _reaches_province(qid, target_set, entities):
                p131 = _entity_p131(entity)
                if not p131:
                    print(f"  STUB (empty P131): {cd_id} \"{match['cd_name']}\""
                          f" → {qid} \"{wd_label}\" ({wd_desc})")
                    warnings += 1
                else:
                    msg = (f"WRONG PROVINCE: {cd_id} \"{match['cd_name']}\" "
                           f"→ {qid} \"{wd_label}\" — expected {prov} "
                           f"({sorted(target_set)}); P131={p131}")
                    print(f"  {msg}")
                    is_bad = True
                    bad_records.append(msg)

        # P625 distance check
        coord = _entity_coord(entity)
        cent = centroids.get(cd_id)
        if coord and cent:
            dist = haversine(cent[0], cent[1], coord[0], coord[1])
            if dist > MAX_DISTANCE_KM:
                msg = (f"FAR: {cd_id} \"{match['cd_name']}\" → {qid} "
                       f"\"{wd_label}\" {dist:.1f} km from centroid")
                print(f"  {msg}")
                warnings += 1

        if is_bad:
            bad += 1
        else:
            good += 1

    print(f"\nResults: {good} good, {warnings} warnings, {bad} bad")
    if bad > 0:
        print("FIX BAD MATCHES before continuing!")
        sys.exit(1)
    else:
        print("All verified matches pass.")


def status(args):
    """Report progress."""
    queue = load_queue()
    verified = load_verified()

    if not queue:
        print("No queue built yet. Run --prepare first.")
        return

    total = len(queue)
    done = sum(1 for q in queue if q["cd_id"] in verified)
    remaining = total - done

    print(f"CD Disambiguation Progress")
    print(f"  Total in queue: {total}")
    print(f"  Verified:       {done}")
    print(f"  Remaining:      {remaining}")
    print()

    by_prov_total = Counter(q["province"] for q in queue)
    by_prov_done = Counter(q["province"] for q in queue if q["cd_id"] in verified)
    print(f"  {'Province':<10s} {'Done':>6s} {'Total':>6s} {'%':>6s}")
    print(f"  {'-'*10} {'-'*6} {'-'*6} {'-'*6}")
    for prov in sorted(by_prov_total):
        t = by_prov_total[prov]
        d = by_prov_done[prov]
        pct = f"{d/t*100:.0f}%" if t > 0 else "n/a"
        print(f"  {prov:<10s} {d:>6d} {t:>6d} {pct:>6s}")

    if verified:
        statuses = Counter(v.get("status", "matched") for v in verified.values())
        print(f"\n  Verified outcomes:")
        for s, c in statuses.most_common():
            print(f"    {s}: {c}")


def main():
    parser = argparse.ArgumentParser(description="CD disambiguation queue manager")
    parser.add_argument("--prepare", action="store_true",
                        help="Build queue from e53_place_cd.csv + seed CSV")
    parser.add_argument("--show-batch", type=int, dest="count", nargs="?", const=25,
                        help="Show next N CDs to process (default 25)")
    parser.add_argument("--verify", action="store_true",
                        help="Batch-verify all QIDs via Wikidata API")
    parser.add_argument("--status", action="store_true", help="Report progress")
    parser.add_argument("--provinces", type=str, default=None,
                        help="Comma-separated province codes to filter show-batch")
    args = parser.parse_args()

    if args.prepare:
        prepare(args)
    elif args.count is not None:
        show_batch(args)
    elif args.verify:
        verify(args)
    elif args.status:
        status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
