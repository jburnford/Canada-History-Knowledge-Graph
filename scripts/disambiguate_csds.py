#!/usr/bin/env python3
"""
Census Subdivision (CSD) disambiguation support script.

Manages the queue of CSDs needing Wikidata QID verification or re-disambiguation.
Used with the /csd-disambig Claude Code skill.

Usage:
    python3 scripts/disambiguate_csds.py --prepare     Build queue from existing matches + unmatched
    python3 scripts/disambiguate_csds.py --show-batch N Show next N CSDs to process
    python3 scripts/disambiguate_csds.py --verify       Batch-verify all QIDs via Wikidata API
    python3 scripts/disambiguate_csds.py --status       Report progress
"""

import argparse
import csv
import json
import math
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from collections import Counter
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
GROUNDING_DIR = REPO_DIR / "wikidata_grounding"
MATCHES_CSV = GROUNDING_DIR / "csd_wikidata_matches.csv"
UNMATCHED_CSV = GROUNDING_DIR / "csd_wikidata_unmatched.csv"
QUEUE_FILE = GROUNDING_DIR / "csd_disambig_queue.jsonl"
VERIFIED_FILE = GROUNDING_DIR / "csd_verified_matches.jsonl"

# Acceptable P31 (instance of) types for CSDs
GOOD_P31_QIDS = {
    # Municipalities and settlements
    "Q515",        # city
    "Q3957",       # town
    "Q532",        # village
    "Q5084",       # hamlet
    "Q486972",     # human settlement
    "Q15284",      # municipality
    "Q3327874",    # rural municipality of Canada
    "Q27676524",   # parish municipality
    "Q27676428",   # municipality (Quebec)
    "Q27676416",   # city or town of Quebec
    "Q27676420",   # village municipality of Quebec
    "Q27676422",   # township municipality of Quebec
    "Q27676424",   # united townships municipality of Quebec
    "Q17143723",   # Catholic parish (can be valid for QC CSDs)
    "Q28203007",   # administrative sector
    "Q188509",     # suburb
    "Q123705",     # neighborhood
    "Q19730508",   # former municipality
    "Q55440238",   # city in Alberta
    "Q55430416",   # town in Alberta
    "Q17366755",   # hamlet in Alberta
    "Q6644696",    # village in Alberta
    "Q3257686",    # locality (used for ghost towns / former settlements)
    "Q6641762",    # summer village in Alberta
    "Q131905118",  # town in Manitoba
    "Q23953065",   # local urban district
    "Q15092400",   # independent city
    # Ontario types
    "Q3012437",    # geographic township of Ontario
    "Q96759164",   # geographic township of Ontario (alternate QID)
    "Q2936646",    # township of Canada (generic)
    "Q102473225",  # geographic township of Quebec
    "Q23019040",   # geographic township of Quebec (alternate QID)
    "Q34763",      # peninsula (some CSDs are peninsulas/islands)
    "Q23442",      # island (some CSDs ARE the island, e.g. Wolfe Island)
    "Q162602",     # river island
    "Q28746",      # township municipality in Ontario
    "Q7209617",    # police village (historic Ontario unincorporated settlement)
    "Q15640053",   # lower-tier municipality of Ontario
    "Q7643933",    # single-tier municipality
    "Q5765388",    # separated municipality in Ontario
    # NB/NS types
    "Q28121225",   # parish of New Brunswick
    "Q107146157",  # municipal district of Nova Scotia
    "Q52132873",   # town in New Brunswick
    "Q6644759",    # village of New Brunswick
    "Q2989457",    # urban-type settlement
    "Q130628050",  # city in New Brunswick
    "Q59341087",   # town in Nova Scotia
    "Q130629307",  # city in Nova Scotia
    "Q15731904",   # municipal district of Nova Scotia
    "Q55774719",   # township municipality in Ontario
    "Q14762300",   # single-tier municipality (Ontario)
    "Q56885635",   # dispersed rural community
    "Q56885310",   # compact rural community
    "Q5154611",    # community
    "Q956318",     # designated place of Canada
    "Q6593035",    # separated municipality in Ontario
    "Q15210668",   # lower-tier municipality of Ontario
    # Western
    "Q14586662",   # organized hamlet of Saskatchewan
    "Q115865269",  # organized hamlet of Saskatchewan (alternate QID)
    "Q6644778",    # village in Saskatchewan
    "Q6643756",    # town in Saskatchewan
    "Q130627673",  # city in Saskatchewan
    "Q23677523",   # designated place of Canada
    "Q50330042",   # improvement district of Alberta
    "Q107150024",  # municipal district of Alberta
    "Q14762205",   # municipal district of Alberta (alternate QID used by Forty Mile, Mountain View, Flagstaff, Sturgeon counties)
    # PEI
    "Q22978485",   # town in Prince Edward Island
    "Q15068900",   # town in Prince Edward Island (alternate QID)
    "Q3788231",    # municipal government in Canada
    "Q115860085",  # fire district of Prince Edward Island
    "Q82794",      # region (used by Wikidata for all PEI Lots / townships)
    "Q3518810",    # unorganized area of Canada (e.g. Unorganized Yukon)
    "Q21507383",   # provincial or territorial capital city in Canada
    # BC types
    "Q60458065",   # city in British Columbia
    "Q1549591",    # big city
    "Q3327871",    # district municipality (BC)
    "Q5532181",    # General Service Area (NS unincorporated community type)
    # Indigenous reserves (valid CSDs in census)
    "Q155239",     # Indian reservation of Canada
    # Other
    "Q15642541",   # human-geographic territorial entity
    "Q131822041",  # parish of New Brunswick (alternate QID)
    "Q3477348",    # urban area (used for some former MB RMs)
    "Q21507948",   # former village
    "Q106071744",  # former town
    "Q130626256",  # city in Canada
    "Q618123",     # geographical feature (also has local urban district)
}

# Province → set of accepted Wikidata QIDs (for P131 chain verification).
# Some provinces have multiple QIDs in active use (e.g. Q1973 and Q1974 for BC).
PROVINCE_QIDS = {
    "AB": {"Q1951"},          # Alberta
    "BC": {"Q1974", "Q1973"}, # British Columbia (two QIDs in use)
    "MB": {"Q1948"},          # Manitoba
    "NB": {"Q1965"},          # New Brunswick
    "NL": {"Q1969"},          # Newfoundland and Labrador
    "NS": {"Q1952"},          # Nova Scotia
    "ON": {"Q1904"},          # Ontario
    "PE": {"Q1959", "Q1978"},  # Prince Edward Island (both QIDs in use)
    "QC": {"Q176"},           # Quebec
    "SK": {"Q1989"},          # Saskatchewan
    "NT": {"Q2007"},          # Northwest Territories
    "YT": {"Q2009"},          # Yukon
    "NU": {"Q1880"},          # Nunavut
}

# Maximum allowed distance (km) between CSD centroid and Wikidata coordinate
MAX_DISTANCE_KM = 50

# Entity types that are ALWAYS wrong for a CSD
BAD_TYPES = {
    "weather station", "railway station", "railway point",
    "railroad switch", "river", "watercourse", "creek", "lake",
    "cape", "peninsula", "hill", "hill group", "mountain",
    "archaeological site", "electoral district",
    "provincial electoral district", "federal electoral district",
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


def load_matches():
    """Load current matches CSV."""
    rows = []
    if MATCHES_CSV.exists():
        with open(MATCHES_CSV) as f:
            rows = list(csv.DictReader(f))
    return rows


def load_verified():
    """Load verified matches JSONL."""
    verified = {}
    if VERIFIED_FILE.exists():
        with open(VERIFIED_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    verified[rec["csd_id"]] = rec
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


def is_bad_type(types_str):
    """Check if entity type string contains known-bad types."""
    types_lower = types_str.lower()
    for bad in BAD_TYPES:
        if bad in types_lower:
            return True
    return False


def prepare(args):
    """Build the disambiguation queue from matches + unmatched."""
    matches = load_matches()
    verified = load_verified()

    queue = []
    stats = Counter()

    for row in matches:
        csd_id = row["csd_id"]

        # Skip already verified
        if csd_id in verified:
            stats["already_verified"] += 1
            continue

        # Check for known-bad types
        if is_bad_type(row["wikidata_types"]):
            queue.append({
                "csd_id": csd_id,
                "csd_name": row["csd_name"],
                "cd_name": row["cd_name"],
                "province": csd_id[:2],
                "current_qid": row["wikidata_qid"],
                "current_label": row["wikidata_label"],
                "current_types": row["wikidata_types"],
                "distance_km": row["distance_km"],
                "lat": row["our_lat"],
                "lon": row["our_lon"],
                "reason": "bad_entity_type",
                "priority": 1,  # Fix first
            })
            stats["bad_type"] += 1
        elif "catholic parish" in row["wikidata_types"].lower():
            # Catholic parishes need individual review
            queue.append({
                "csd_id": csd_id,
                "csd_name": row["csd_name"],
                "cd_name": row["cd_name"],
                "province": csd_id[:2],
                "current_qid": row["wikidata_qid"],
                "current_label": row["wikidata_label"],
                "current_types": row["wikidata_types"],
                "distance_km": row["distance_km"],
                "lat": row["our_lat"],
                "lon": row["our_lon"],
                "reason": "catholic_parish_review",
                "priority": 2,  # Review second
            })
            stats["catholic_parish"] += 1
        else:
            # Existing match needs verification
            queue.append({
                "csd_id": csd_id,
                "csd_name": row["csd_name"],
                "cd_name": row["cd_name"],
                "province": csd_id[:2],
                "current_qid": row["wikidata_qid"],
                "current_label": row["wikidata_label"],
                "current_types": row["wikidata_types"],
                "distance_km": row["distance_km"],
                "lat": row["our_lat"],
                "lon": row["our_lon"],
                "reason": "needs_verification",
                "priority": 3,  # Verify last
            })
            stats["needs_verification"] += 1

    # Add unmatched CSDs
    if UNMATCHED_CSV.exists():
        with open(UNMATCHED_CSV) as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for row_raw in reader:
                if len(row_raw) < 4:
                    continue
                csd_id = row_raw[0]
                if csd_id in verified:
                    stats["already_verified"] += 1
                    continue
                queue.append({
                    "csd_id": csd_id,
                    "csd_name": row_raw[1],
                    "cd_name": row_raw[3] if len(row_raw) > 3 else "",
                    "province": csd_id[:2],
                    "current_qid": None,
                    "current_label": None,
                    "current_types": None,
                    "distance_km": None,
                    "lat": None,
                    "lon": None,
                    "reason": "unmatched",
                    "priority": 4,  # New matches last
                })
                stats["unmatched"] += 1

    # Sort by priority, then province, then name
    queue.sort(key=lambda x: (x["priority"], x["province"], x["csd_name"]))

    # Write queue
    with open(QUEUE_FILE, "w") as f:
        for item in queue:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"Queue built: {len(queue)} CSDs to process")
    print(f"  Bad entity types (priority 1): {stats['bad_type']}")
    print(f"  Catholic parishes to review (priority 2): {stats['catholic_parish']}")
    print(f"  Existing matches to verify (priority 3): {stats['needs_verification']}")
    print(f"  Unmatched CSDs (priority 4): {stats['unmatched']}")
    print(f"  Already verified (skipped): {stats['already_verified']}")
    print(f"\nQueue file: {QUEUE_FILE}")


def show_batch(args):
    """Show next N CSDs from the queue that haven't been verified."""
    n = args.count or 50
    queue = load_queue()
    verified = load_verified()

    pending = [q for q in queue if q["csd_id"] not in verified]

    if getattr(args, "provinces", None):
        provs = {p.strip().upper() for p in args.provinces.split(",") if p.strip()}
        pending = [q for q in pending if q["province"] in provs]

    if not pending:
        print("All CSDs have been verified!")
        return

    batch = pending[:n]
    print(f"Next {len(batch)} CSDs to process (of {len(pending)} remaining):\n")

    current_reason = None
    for item in batch:
        if item["reason"] != current_reason:
            current_reason = item["reason"]
            print(f"\n--- {current_reason.upper()} ---")

        if item["current_qid"]:
            print(f"  {item['csd_id']}  \"{item['csd_name']}\" ({item['cd_name']})")
            print(f"    Current: {item['current_qid']} \"{item['current_label']}\" "
                  f"[{item['current_types']}] dist={item['distance_km']}km")
        else:
            print(f"  {item['csd_id']}  \"{item['csd_name']}\" ({item['cd_name']})")
            print(f"    No current match")


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
            req = urllib.request.Request(url, headers={"User-Agent": "CSD-Disambig/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                if "entities" in data:
                    results.update(data["entities"])
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            print(f"  API error for batch {i}: {e}", file=sys.stderr)
        if i + 50 < len(qids):
            time.sleep(1)  # Be polite
    return results


def _entity_p131(entity):
    """Extract P131 (located in admin entity) QIDs from an entity."""
    out = []
    for claim in entity.get("claims", {}).get("P131", []):
        v = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(v, dict) and "id" in v:
            out.append(v["id"])
    return out


def _entity_coord(entity):
    """Extract P625 (coordinate location) lat/lon from an entity."""
    for claim in entity.get("claims", {}).get("P625", []):
        v = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(v, dict) and "latitude" in v:
            return float(v["latitude"]), float(v["longitude"])
    return None


def _load_centroids_and_provinces():
    """Build {csd_id: (lat, lon)} and {csd_id: province} from queue + matches."""
    centroids = {}
    provinces = {}
    queue = load_queue()
    for r in queue:
        provinces[r["csd_id"]] = r.get("province") or r["csd_id"][:2]
        try:
            if r.get("lat") and r.get("lon"):
                centroids[r["csd_id"]] = (float(r["lat"]), float(r["lon"]))
        except (ValueError, TypeError):
            pass
    for row in load_matches():
        cid = row["csd_id"]
        provinces.setdefault(cid, cid[:2])
        if cid not in centroids:
            try:
                centroids[cid] = (float(row["our_lat"]), float(row["our_lon"]))
            except (ValueError, TypeError):
                pass
    return centroids, provinces


def _reaches_province(start_qid, target_prov_qids, all_entities, max_depth=5):
    """Walk the P131 chain from start_qid looking for any target_prov_qids."""
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
    """Batch-verify all verified matches against Wikidata API.

    Checks every matched QID for:
      - entity exists
      - label is consistent
      - P31 (instance of) is a settlement/municipality type
      - P131 chain reaches the expected province
      - P625 coordinate is within MAX_DISTANCE_KM of CSD centroid
    """
    verified = load_verified()
    if not verified:
        print("No verified matches to check.")
        return

    centroids, provinces = _load_centroids_and_provinces()

    qids = list(set(v["wikidata_qid"] for v in verified.values() if v.get("wikidata_qid")))
    print(f"Verifying {len(qids)} unique QIDs from {len(verified)} matches...")

    entities = fetch_wikidata_entities(qids)

    # Iteratively resolve P131 parents until the chain bottoms out (or hits
    # max depth). Quebec municipalities typically need 3 hops:
    # municipality → MRC → administrative region → Quebec.
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

    for csd_id, match in sorted(verified.items()):
        qid = match.get("wikidata_qid")
        if not qid or match.get("status") == "ungrounded":
            continue

        if qid not in entities:
            msg = f"MISSING: {csd_id} → {qid} (not found in Wikidata)"
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
            if (wd_label.lower() in our_label.lower()
                    or our_label.lower() in wd_label.lower()):
                pass
            else:
                print(f"  LABEL MISMATCH: {csd_id} → {qid}: "
                      f"we have \"{our_label}\", Wikidata has \"{wd_label}\"")
                warnings += 1

        # P31 type check
        p31_qids = set()
        for claim in entity.get("claims", {}).get("P31", []):
            v = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(v, dict) and "id" in v:
                p31_qids.add(v["id"])
        if p31_qids and not p31_qids.intersection(GOOD_P31_QIDS):
            msg = (f"BAD TYPE: {csd_id} \"{match['csd_name']}\" → {qid} "
                   f"\"{wd_label}\" ({wd_desc}) P31={p31_qids}")
            print(f"  {msg}")
            is_bad = True
            bad_records.append(msg)

        # P131 province check
        prov = provinces.get(csd_id, csd_id[:2])
        target_set = PROVINCE_QIDS.get(prov)
        if target_set:
            if not _reaches_province(qid, target_set, entities):
                p131 = _entity_p131(entity)
                if not p131:
                    # Empty P131: probably a stub entity. Can't prove wrong
                    # province but worth flagging.
                    print(f"  STUB (empty P131): {csd_id} \"{match['csd_name']}\""
                          f" → {qid} \"{wd_label}\" ({wd_desc})")
                    warnings += 1
                else:
                    msg = (f"WRONG PROVINCE: {csd_id} \"{match['csd_name']}\" "
                           f"→ {qid} \"{wd_label}\" — expected {prov} "
                           f"({sorted(target_set)}); P131={p131}")
                    print(f"  {msg}")
                    is_bad = True
                    bad_records.append(msg)

        # P625 distance check
        coord = _entity_coord(entity)
        cent = centroids.get(csd_id)
        if coord and cent:
            dist = haversine(cent[0], cent[1], coord[0], coord[1])
            if dist > MAX_DISTANCE_KM:
                msg = (f"FAR: {csd_id} \"{match['csd_name']}\" → {qid} "
                       f"\"{wd_label}\" {dist:.1f} km from centroid "
                       f"(centroid={cent}, wd={coord})")
                print(f"  {msg}")
                # Distance > 50 km is a warning, not auto-fail: Wikidata
                # coordinates are sometimes stale (especially SK RMs). The
                # P131 + label + P31 checks above are the hard gates.
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
    done = sum(1 for q in queue if q["csd_id"] in verified)
    remaining = total - done

    print(f"CSD Disambiguation Progress")
    print(f"  Total in queue: {total}")
    print(f"  Verified:       {done}")
    print(f"  Remaining:      {remaining}")
    print()

    # Breakdown by reason
    reasons = Counter()
    done_reasons = Counter()
    for q in queue:
        reasons[q["reason"]] += 1
        if q["csd_id"] in verified:
            done_reasons[q["reason"]] += 1

    print(f"  {'Category':<30s} {'Done':>6s} {'Total':>6s} {'%':>6s}")
    print(f"  {'-'*30} {'-'*6} {'-'*6} {'-'*6}")
    for reason in ["bad_entity_type", "catholic_parish_review", "needs_verification", "unmatched"]:
        t = reasons.get(reason, 0)
        d = done_reasons.get(reason, 0)
        pct = f"{d/t*100:.0f}%" if t > 0 else "n/a"
        print(f"  {reason:<30s} {d:>6d} {t:>6d} {pct:>6s}")

    # Verified match stats
    if verified:
        statuses = Counter(v.get("status", "matched") for v in verified.values())
        print(f"\n  Verified match outcomes:")
        for s, c in statuses.most_common():
            print(f"    {s}: {c}")


def _entity_inception_years(entity):
    """Extract all P571 (inception) years from an entity. Returns sorted list of ints."""
    years = []
    for claim in entity.get("claims", {}).get("P571", []):
        v = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(v, dict) and "time" in v:
            # Format: "+1855-07-01T00:00:00Z" or "-0500-01-01T00:00:00Z"
            t = v["time"]
            if t.startswith("+") or t.startswith("-"):
                try:
                    sign = 1 if t.startswith("+") else -1
                    year_str = t[1:].split("-")[0]
                    years.append(sign * int(year_str))
                except (ValueError, IndexError):
                    pass
    return sorted(years)


def _entity_replaces(entity):
    """Extract P1365 (replaces) QIDs — historic predecessor entities."""
    out = []
    for claim in entity.get("claims", {}).get("P1365", []):
        v = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(v, dict) and "id" in v:
            out.append(v["id"])
    return out


def review_anachronism(args):
    """Flag matched QIDs whose Wikidata entity didn't exist before the cutoff year.

    The 1921 census predates many modern Quebec/Ontario municipalities formed
    by post-1980 mergers. Entities with all P571 (inception) values after the
    cutoff are likely territorial successors rather than the actual 1921 CSD,
    and should be reviewed manually — preferably by substituting the historic
    predecessor entity referenced via P1365 (replaces).
    """
    cutoff = args.cutoff_year
    print(f"Loading matched entries with QIDs (inception cutoff: {cutoff})...")

    verified = load_verified()
    matched = [(cid, m) for cid, m in verified.items()
               if m.get("status") == "matched" and m.get("wikidata_qid")]
    print(f"  {len(matched)} matched entries")

    qids = sorted({m["wikidata_qid"] for _, m in matched})
    print(f"  Fetching {len(qids)} unique entities for P571/P1365...")
    entities = fetch_wikidata_entities(qids)

    flagged = []  # (csd_id, csd_name, qid, label, min_inception, replaces_qids)
    no_inception = []

    for csd_id, m in matched:
        qid = m["wikidata_qid"]
        ent = entities.get(qid)
        if not ent:
            continue
        years = _entity_inception_years(ent)
        if not years:
            no_inception.append((csd_id, m["csd_name"], qid, m.get("wikidata_label", "")))
            continue
        if min(years) > cutoff:
            replaces = _entity_replaces(ent)
            flagged.append((csd_id, m["csd_name"], qid, m.get("wikidata_label", ""),
                            min(years), max(years), replaces))

    # Resolve P1365 predecessor entities so we can show their info
    pred_qids = sorted({q for f in flagged for q in f[6]})
    pred_entities = {}
    if pred_qids:
        print(f"  Fetching {len(pred_qids)} predecessor entities (P1365)...")
        pred_entities = fetch_wikidata_entities(pred_qids)

    out_path = REPO_DIR / "wikidata_grounding" / f"csd_anachronism_review_{cutoff}.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["csd_id", "csd_name", "matched_qid", "matched_label",
                    "min_inception", "max_inception",
                    "predecessor_qids", "predecessor_labels",
                    "predecessor_inception_min"])
        for csd_id, name, qid, label, min_y, max_y, preds in sorted(flagged):
            pred_labels = []
            pred_min_year = ""
            for p in preds:
                ent = pred_entities.get(p)
                if ent:
                    plabel = ent.get("labels", {}).get("en", {}).get("value", "")
                    pred_labels.append(f"{p}={plabel}")
                    pyears = _entity_inception_years(ent)
                    if pyears:
                        pmin = min(pyears)
                        if pred_min_year == "" or pmin < pred_min_year:
                            pred_min_year = pmin
                else:
                    pred_labels.append(p)
            w.writerow([csd_id, name, qid, label, min_y, max_y,
                        ";".join(preds), ";".join(pred_labels), pred_min_year])

    # Summary
    print(f"\nResults:")
    print(f"  {len(matched) - len(flagged) - len(no_inception)} matched entities with pre-{cutoff} inception")
    print(f"  {len(no_inception)} matched entities with no P571 inception in Wikidata")
    print(f"  {len(flagged)} matched entities with all inceptions post-{cutoff} -- FLAGGED")
    print(f"\nReport written to: {out_path}")

    # Show counts by inception decade
    from collections import Counter
    decade_counts = Counter((y // 10) * 10 for _, _, _, _, y, _, _ in flagged)
    if decade_counts:
        print(f"\nFlagged entity inception by decade:")
        for decade in sorted(decade_counts):
            print(f"  {decade}s: {decade_counts[decade]}")

    # Show top-10 flagged with predecessors available
    with_preds = [f for f in flagged if f[6]]
    if with_preds:
        print(f"\n{len(with_preds)}/{len(flagged)} flagged entities have P1365 predecessors")
        print("Sample (first 10):")
        for csd_id, name, qid, label, min_y, _, preds in with_preds[:10]:
            preds_str = ";".join(preds)
            print(f"  {csd_id} \"{name}\" → {qid} \"{label}\" ({min_y}); replaces: {preds_str}")


def main():
    parser = argparse.ArgumentParser(description="CSD disambiguation queue manager")
    parser.add_argument("--prepare", action="store_true", help="Build queue from matches + unmatched")
    parser.add_argument("--show-batch", type=int, dest="count", nargs="?", const=50,
                        help="Show next N CSDs to process (default 50)")
    parser.add_argument("--verify", action="store_true", help="Batch-verify all QIDs via Wikidata API")
    parser.add_argument("--status", action="store_true", help="Report progress")
    parser.add_argument("--review-anachronism", action="store_true",
                        help="Flag matched QIDs whose Wikidata entity didn't exist before --cutoff-year")
    parser.add_argument("--cutoff-year", type=int, default=1930,
                        help="Inception cutoff for --review-anachronism (default 1930)")
    parser.add_argument("--provinces", type=str, default=None,
                        help="Comma-separated province codes to filter show-batch (e.g. ON,SK)")
    args = parser.parse_args()

    if args.prepare:
        prepare(args)
    elif args.count is not None:
        show_batch(args)
    elif args.verify:
        verify(args)
    elif args.review_anachronism:
        review_anachronism(args)
    elif args.status:
        status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
