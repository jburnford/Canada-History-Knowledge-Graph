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
    "Q102473225",  # geographic township of Quebec
    "Q34763",      # peninsula (some CSDs are peninsulas/islands)
    "Q28746",      # township municipality in Ontario
    "Q15640053",   # lower-tier municipality of Ontario
    "Q7643933",    # single-tier municipality
    "Q5765388",    # separated municipality in Ontario
    # NB/NS types
    "Q28121225",   # parish of New Brunswick
    "Q107146157",  # municipal district of Nova Scotia
    # Western
    "Q14586662",   # organized hamlet of Saskatchewan
    "Q6644778",    # village in Saskatchewan
    "Q6643756",    # town in Saskatchewan
    "Q130627673",  # city in Saskatchewan
    "Q23677523",   # designated place of Canada
    "Q50330042",   # improvement district of Alberta
    "Q107150024",  # municipal district of Alberta
    # PEI
    "Q22978485",   # town in Prince Edward Island
    # BC types
    "Q60458065",   # city in British Columbia
    "Q1549591",    # big city
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


def verify(args):
    """Batch-verify all verified matches against Wikidata API."""
    verified = load_verified()
    if not verified:
        print("No verified matches to check.")
        return

    qids = list(set(v["wikidata_qid"] for v in verified.values() if v.get("wikidata_qid")))
    print(f"Verifying {len(qids)} unique QIDs from {len(verified)} matches...")

    entities = fetch_wikidata_entities(qids)

    good = 0
    warnings = 0
    bad = 0

    for csd_id, match in sorted(verified.items()):
        qid = match.get("wikidata_qid")
        if not qid or match.get("status") == "ungrounded":
            continue

        if qid not in entities:
            print(f"  MISSING: {csd_id} → {qid} (not found in Wikidata)")
            bad += 1
            continue

        entity = entities[qid]

        # Check label match
        wd_label = entity.get("labels", {}).get("en", {}).get("value", "")
        our_label = match.get("wikidata_label", "")

        if wd_label.lower() != our_label.lower():
            # Allow substring matching
            if wd_label.lower() in our_label.lower() or our_label.lower() in wd_label.lower():
                pass  # Close enough
            else:
                print(f"  LABEL MISMATCH: {csd_id} → {qid}: "
                      f"we have \"{our_label}\", Wikidata has \"{wd_label}\"")
                warnings += 1

        # Check P31 types
        claims = entity.get("claims", {})
        p31_claims = claims.get("P31", [])
        p31_qids = set()
        for claim in p31_claims:
            mainsnak = claim.get("mainsnak", {})
            datavalue = mainsnak.get("datavalue", {})
            value = datavalue.get("value", {})
            if isinstance(value, dict) and "id" in value:
                p31_qids.add(value["id"])

        if p31_qids and not p31_qids.intersection(GOOD_P31_QIDS):
            wd_desc = entity.get("descriptions", {}).get("en", {}).get("value", "")
            print(f"  BAD TYPE: {csd_id} \"{match['csd_name']}\" → {qid} \"{wd_label}\" "
                  f"({wd_desc}) P31={p31_qids}")
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


def main():
    parser = argparse.ArgumentParser(description="CSD disambiguation queue manager")
    parser.add_argument("--prepare", action="store_true", help="Build queue from matches + unmatched")
    parser.add_argument("--show-batch", type=int, dest="count", nargs="?", const=50,
                        help="Show next N CSDs to process (default 50)")
    parser.add_argument("--verify", action="store_true", help="Batch-verify all QIDs via Wikidata API")
    parser.add_argument("--status", action="store_true", help="Report progress")
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
