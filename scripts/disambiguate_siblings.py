#!/usr/bin/env python3
"""Sibling-review disambiguation support script.

Operates on chains the centroid gate in `join_wikidata_to_places.py`
rejected — same-name siblings whose donor chain centroid was >50 km from
the candidate's chain centroid (so the donor's QID is the wrong place).
The 167 rejected chains live in `wikidata_grounding/sibling_review_queue.jsonl`
and need MCP re-search to either find the correct QID or accept that
no separate WD entity exists (mint URI).

Mirrors disambiguate_presences.py's CLI:

    python3 scripts/disambiguate_siblings.py --status
    python3 scripts/disambiguate_siblings.py --show-batch 30
    python3 scripts/disambiguate_siblings.py --verify
    python3 scripts/disambiguate_siblings.py --commit-overrides

Outputs append to `wikidata_grounding/sibling_resolved_matches.jsonl`
(one record per chain). `--commit-overrides` merges status=matched
results into `wikidata_grounding/csd_chain_qid_xrefs.csv` as `force`
overrides, which `join_wikidata_to_places.py` reads natively.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from disambiguate_csds import (  # noqa: E402
    GOOD_P31_QIDS,
    PROVINCE_QIDS,
    MAX_DISTANCE_KM,
    fetch_wikidata_entities,
    haversine,
    _entity_p131,
    _entity_coord,
    _reaches_province,
)

REPO = Path(__file__).resolve().parent.parent
GROUNDING_DIR = REPO / "wikidata_grounding"

QUEUE_FILE = GROUNDING_DIR / "sibling_review_queue.jsonl"
RESOLVED_FILE = GROUNDING_DIR / "sibling_resolved_matches.jsonl"
OVERRIDES_FILE = GROUNDING_DIR / "csd_chain_qid_xrefs.csv"


def load_queue() -> list[dict]:
    if not QUEUE_FILE.exists():
        return []
    out = []
    with QUEUE_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def load_resolved() -> dict[str, dict]:
    """place_id -> resolved record (latest wins if duplicates appended)."""
    out: dict[str, dict] = {}
    if not RESOLVED_FILE.exists():
        return out
    with RESOLVED_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            out[r["place_id"]] = r
    return out


def cmd_status(args) -> None:
    queue = load_queue()
    resolved = load_resolved()
    print(f"Queue total: {len(queue):,}")
    print(f"Resolved:    {len(resolved):,}")
    print(f"Remaining:   {len(queue) - len(resolved):,}")
    if not resolved:
        return
    by_status = Counter(r["status"] for r in resolved.values())
    print("\nResolved by status:")
    for st in ("matched", "mint_uri", "skip"):
        print(f"  {st:10s} {by_status.get(st, 0):,}")
    by_prov = Counter()
    for r in resolved.values():
        by_prov[r.get("province", "?")] += 1
    print("\nBy province:")
    for prov, n in by_prov.most_common():
        print(f"  {prov:3s} {n:,}")


def cmd_show_batch(args) -> None:
    queue = load_queue()
    resolved = load_resolved()
    n = args.n
    emitted = 0
    for entry in queue:
        if entry["place_id"] in resolved:
            continue
        if args.provinces and entry["province"] not in args.provinces.split(","):
            continue
        sys.stdout.write(json.dumps(entry, ensure_ascii=False) + "\n")
        emitted += 1
        if emitted >= n:
            break
    if emitted == 0:
        print("# queue exhausted", file=sys.stderr)


def cmd_verify(args) -> None:
    resolved = load_resolved()
    matched = {p: r for p, r in resolved.items() if r["status"] == "matched"}
    if not matched:
        print("No matched records to verify.")
        return
    qids = sorted({r["wikidata_qid"] for r in matched.values()
                   if r.get("wikidata_qid")})
    print(f"Verifying {len(qids):,} unique QIDs across {len(matched):,} matched chains...")
    entities = fetch_wikidata_entities(qids)
    province_qid_set: set[str] = set()
    for s in PROVINCE_QIDS.values():
        province_qid_set.update(s)
    for hop in range(1, 5):
        needed: set[str] = set()
        for ent in list(entities.values()):
            for parent in _entity_p131(ent):
                if parent not in entities and parent not in province_qid_set:
                    needed.add(parent)
        if not needed:
            break
        print(f"  Resolving {len(needed)} P131 parents (hop {hop})...")
        entities.update(fetch_wikidata_entities(sorted(needed)))

    bad = warn = good = 0
    for place_id, rec in sorted(matched.items()):
        qid = rec["wikidata_qid"]
        ent = entities.get(qid)
        if not ent:
            print(f"  MISSING: {place_id} -> {qid}")
            bad += 1
            continue
        p31 = set()
        for claim in ent.get("claims", {}).get("P31", []):
            v = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(v, dict) and "id" in v:
                p31.add(v["id"])
        if p31 and not p31 & GOOD_P31_QIDS:
            print(f"  BAD TYPE: {place_id} \"{rec['name']}\" -> {qid} P31={p31}")
            bad += 1
            continue
        target_set = PROVINCE_QIDS.get(rec.get("province", ""), set())
        if target_set and not _reaches_province(qid, target_set, entities):
            p131 = _entity_p131(ent)
            if p131:
                print(f"  WRONG PROV: {place_id} \"{rec['name']}\" -> {qid} P131={p131[:3]}")
                bad += 1
                continue
            warn += 1
        coord = _entity_coord(ent)
        c_lat = rec.get("candidate_lat")
        c_lon = rec.get("candidate_lon")
        if coord and c_lat is not None and c_lon is not None:
            d_km = haversine(c_lat, c_lon, coord[0], coord[1])
            if d_km > MAX_DISTANCE_KM:
                print(f"  FAR: {place_id} \"{rec['name']}\" -> {qid} {d_km:.0f} km")
                warn += 1
                continue
        good += 1
    print(f"\nResults: {good} good, {warn} warnings, {bad} bad")
    if bad > 0:
        print("FIX BAD MATCHES before continuing!")
        sys.exit(1)


def cmd_commit_overrides(args) -> None:
    """Merge matched sibling resolutions into csd_chain_qid_xrefs.csv as
    `force` overrides. Existing override rows are preserved."""
    resolved = load_resolved()
    matched = {p: r for p, r in resolved.items() if r["status"] == "matched"}
    if not matched:
        print("No matched records to commit.")
        return
    existing: dict[str, dict] = {}
    if OVERRIDES_FILE.exists():
        with OVERRIDES_FILE.open() as f:
            for row in csv.DictReader(f):
                pid = (row.get("place_id") or "").strip()
                if pid:
                    existing[pid] = row
    fieldnames = ["place_id", "qid", "label", "decision", "reason"]
    for place_id, rec in matched.items():
        existing[place_id] = {
            "place_id": place_id,
            "qid": rec["wikidata_qid"],
            "label": rec.get("wikidata_label", ""),
            "decision": "force",
            "reason": f"sibling-review: replaces wrong sibling {rec.get('rejected_qid','')}",
        }
    OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OVERRIDES_FILE.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for pid in sorted(existing):
            row = existing[pid]
            # Normalize fields (existing rows may have extras)
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    print(f"Wrote {len(existing):,} override rows -> {OVERRIDES_FILE.relative_to(REPO)}")
    print(f"  ({len(matched):,} from sibling-review matched results)")
    print("\nNext steps:")
    print("  python3 scripts/join_wikidata_to_places.py")
    print("  python3 scripts/build_qid_xref.py")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true",
                        help="Print queue progress")
    parser.add_argument("--show-batch", type=int, dest="n", metavar="N",
                        help="Emit next N unprocessed queue rows as JSONL")
    parser.add_argument("--provinces", type=str, default="",
                        help="Comma-separated province filter (e.g. QC,ON)")
    parser.add_argument("--verify", action="store_true",
                        help="REST-API verify all matched entries")
    parser.add_argument("--commit-overrides", action="store_true",
                        help="Merge matched results into csd_chain_qid_xrefs.csv")
    args = parser.parse_args()

    if args.status:
        cmd_status(args)
    elif args.n is not None:
        cmd_show_batch(args)
    elif args.verify:
        cmd_verify(args)
    elif args.commit_overrides:
        cmd_commit_overrides(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
