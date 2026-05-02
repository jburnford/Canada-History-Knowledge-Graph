#!/usr/bin/env python3
"""Per-presence (per-chain) Wikidata disambiguation support script.

Phase C of the per-presence grounding pipeline. Operates on chains that
remain ungrounded after Phase A (inheritance) + Phase B (REST verify):

  - 4,367 NO_EVIDENCE chains from presence_inheritance_unresolved.csv
  - 64 DEMOTED chains from presence_verify_demoted.csv (with carry-over of
    the Wikidata QID that Phase B rejected — useful as a "don't pick this"
    hint for the LLM)

Mirrors disambiguate_csds.py's CLI (--prepare / --show-batch / --status /
--verify) so the existing csd-disambig skill flow ports over with minimal
change. Writes verified results to wikidata_grounding/presence_verified_matches.jsonl
which is shared with Phase A/B (Phase A wrote inheritance matches; Phase B
overwrote with REST-verified passes; Phase C appends MCP-grounded entries).

Usage:
    python3 scripts/disambiguate_presences.py --prepare
    python3 scripts/disambiguate_presences.py --show-batch 100
    python3 scripts/disambiguate_presences.py --status
    python3 scripts/disambiguate_presences.py --verify
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
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
CIDOC_DIR = REPO / "neo4j_cidoc_crm_v2"

INHERITANCE_UNRESOLVED = GROUNDING_DIR / "presence_inheritance_unresolved.csv"
VERIFY_DEMOTED = GROUNDING_DIR / "presence_verify_demoted.csv"
VERIFIED_FILE = GROUNDING_DIR / "presence_verified_matches.jsonl"
QUEUE_FILE = GROUNDING_DIR / "presence_disambig_queue.jsonl"

YEARS = (1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921)


def _load_chain_metadata() -> dict[str, dict]:
    out: dict[str, dict] = {}
    with (CIDOC_DIR / "e53_place_csd.csv").open() as f:
        for row in csv.DictReader(f):
            out[row["place_id:ID"]] = {
                "name": row["name"],
                "province": row["province"],
                "place_type": row["place_type"],
                "years_active": row["years_active"],
            }
    return out


def _load_presence_to_chain() -> tuple[dict, dict]:
    """((tcpuid, year) -> chain, chain -> [(tcpuid, year), ...])."""
    p2c: dict = {}
    c2p: dict = defaultdict(list)
    with (REPO / "persistent_places_output" / "tcpuid_year_to_place.csv").open() as f:
        for row in csv.DictReader(f):
            key = (row["tcpuid"], int(row["year"]))
            chain = row["persistent_place_id"]
            p2c[key] = chain
            c2p[chain].append(key)
    return p2c, c2p


def _load_centroids_per_year() -> dict[tuple[str, int], tuple[float, float]]:
    out: dict = {}
    for year in YEARS:
        path = CIDOC_DIR / f"e94_space_primitive_{year}.csv"
        if not path.exists():
            continue
        with path.open() as f:
            for row in csv.DictReader(f):
                space_id = row["space_id:ID"]
                if not space_id.endswith("_centroid"):
                    continue
                stem = space_id[: -len("_centroid")]
                parts = stem.rsplit("_", 1)
                if len(parts) != 2 or not parts[1].isdigit():
                    continue
                tcpuid, yr = parts[0], int(parts[1])
                try:
                    out[(tcpuid, yr)] = (float(row["latitude:float"]),
                                          float(row["longitude:float"]))
                except (ValueError, TypeError):
                    pass
    return out


def _load_presence_names() -> dict[tuple[str, int], str]:
    """(tcpuid, year) -> presence-specific name (from p166 cd link or e93)."""
    out: dict = {}
    # e93_presence_<year> doesn't store the CSD name (only tcpuid + area).
    # The display name varies per year — pulled from the original year_links
    # files where csd_name_<year> appears. Use those for the most accurate
    # per-year naming.
    YEAR_LINKS_DIR = REPO / "year_links_output"
    for ya, yb in zip(YEARS[:-1], YEARS[1:]):
        for fname in (f"year_links_{ya}_{yb}.csv", f"ambiguous_{ya}_{yb}.csv"):
            path = YEAR_LINKS_DIR / fname
            if not path.exists():
                continue
            with path.open() as f:
                for row in csv.DictReader(f):
                    keys = [k for k in row.keys() if k.startswith("tcpuid_")]
                    name_keys = [k for k in row.keys() if k.startswith("csd_name_")]
                    for tcpk, namek in zip(keys, name_keys):
                        yr = int(tcpk.split("_")[1])
                        tcp = row[tcpk]
                        nm = row[namek]
                        if tcp and nm and (tcp, yr) not in out:
                            out[(tcp, yr)] = nm
    return out


def _load_parent_cd_per_presence() -> dict[tuple[str, int], str]:
    """(tcpuid, year) -> parent CD chain id from p10."""
    out: dict = {}
    for year in YEARS:
        path = CIDOC_DIR / f"p10_csd_within_cd_presence_{year}.csv"
        if not path.exists():
            continue
        with path.open() as f:
            for row in csv.DictReader(f):
                csd_pres = row[":START_ID"]
                cd_pres = row[":END_ID"]
                # csd_pres is "<tcpuid>_<year>"; tcpuid may itself contain _
                stem = csd_pres
                parts = stem.rsplit("_", 1)
                if len(parts) != 2 or not parts[1].isdigit():
                    continue
                tcp, yr = parts[0], int(parts[1])
                out[(tcp, yr)] = cd_pres
    return out


def _load_cd_chain_to_name() -> dict[str, str]:
    out: dict = {}
    with (CIDOC_DIR / "e53_place_cd.csv").open() as f:
        for row in csv.DictReader(f):
            out[row["place_id:ID"]] = row["name"]
    return out


def _strip_cd_year_suffix(cd_pres: str) -> str:
    """Convert "CD_ON_Addington_1921_1921" -> "CD_ON_Addington_1921"
    (presence id has a trailing _YYYY of the census year, the chain id
    sometimes has its own _YYYY anchor suffix already)."""
    parts = cd_pres.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 4:
        return parts[0]
    return cd_pres


def load_processed_chains() -> set[str]:
    """Chains that already have a verified entry in presence_verified_matches.jsonl."""
    seen: set[str] = set()
    if not VERIFIED_FILE.exists():
        return seen
    with VERIFIED_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if "current_chain" in d:
                seen.add(d["current_chain"])
    return seen


def cmd_prepare(args) -> None:
    """Build presence_disambig_queue.jsonl from inheritance unresolved +
    Phase B demoted, excluding chains already in presence_verified_matches.jsonl."""
    metadata = _load_chain_metadata()
    p2c, c2p = _load_presence_to_chain()
    centroids = _load_centroids_per_year()
    presence_names = _load_presence_names()
    parent_cd = _load_parent_cd_per_presence()
    cd_name = _load_cd_chain_to_name()

    processed = load_processed_chains()
    print(f"Already processed (in verified file): {len(processed):,}", file=sys.stderr)

    # Source 1: inheritance unresolved (4,367 NO_EVIDENCE chains)
    unresolved_chains: list[str] = []
    if INHERITANCE_UNRESOLVED.exists():
        with INHERITANCE_UNRESOLVED.open() as f:
            for r in csv.DictReader(f):
                if r["reason"] != "no_inheritance_signal":
                    continue  # skip "no_presences_in_map" data-bug rows
                if r["chain_id"].startswith("CD_"):
                    continue
                unresolved_chains.append(r["chain_id"])

    # Source 2: Phase B demoted (with carry-over QID-to-avoid)
    demoted: dict[str, dict] = {}
    if VERIFY_DEMOTED.exists():
        with VERIFY_DEMOTED.open() as f:
            for r in csv.DictReader(f):
                demoted[r["chain_id"]] = {
                    "phase_b_rejected_qid": r["inherited_qid"],
                    "phase_b_rejected_label": r["inherited_label"],
                    "phase_b_fail_reason": r["fail_reason"],
                }

    candidate_chains = list(set(unresolved_chains) | set(demoted.keys()))
    print(f"Candidate chains: {len(candidate_chains):,} "
          f"({len(unresolved_chains):,} unresolved + {len(demoted):,} demoted)",
          file=sys.stderr)

    written = 0
    skipped_processed = 0
    skipped_no_meta = 0
    queue_rows: list[dict] = []

    for chain in sorted(candidate_chains):
        if chain in processed:
            skipped_processed += 1
            continue
        meta = metadata.get(chain)
        if not meta:
            skipped_no_meta += 1
            continue
        presences = c2p.get(chain, [])
        if not presences:
            # Chain missing from tcpuid map (the 842-chain data bug). Synthesize
            # from chain id year suffix.
            import re
            m = re.match(r"^PLACE_([A-Z]{2}\d+)(?:_(\d{4}))?$", chain)
            if m and m.group(2):
                presences = [(m.group(1), int(m.group(2)))]
        if not presences:
            skipped_no_meta += 1
            continue

        # Pick anchor = latest-year presence
        anchor_tcp, anchor_year = max(presences, key=lambda p: p[1])
        anchor_name = presence_names.get((anchor_tcp, anchor_year)) or meta["name"]
        cd_pres = parent_cd.get((anchor_tcp, anchor_year), "")
        cd_chain = _strip_cd_year_suffix(cd_pres) if cd_pres else ""
        cd_label = cd_name.get(cd_chain, cd_chain)
        coord = centroids.get((anchor_tcp, anchor_year))

        row = {
            "chain_id": chain,
            "chain_canonical_name": meta["name"],
            "anchor_tcpuid": anchor_tcp,
            "anchor_year": anchor_year,
            "anchor_name": anchor_name,
            "province": meta["province"],
            "parent_cd_chain": cd_chain,
            "parent_cd_name": cd_label,
            "place_type": meta["place_type"],
            "years_active": meta["years_active"],
            "lat": coord[0] if coord else None,
            "lon": coord[1] if coord else None,
            "n_presences": len(presences),
            "all_presences": [f"{t}_{y}" for t, y in sorted(presences)],
        }
        # Phase B carry-over (a hint for the LLM: don't pick this QID again)
        if chain in demoted:
            row.update(demoted[chain])

        queue_rows.append(row)
        written += 1

    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE_FILE.open("w") as f:
        for row in queue_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\nQueue written: {written:,} rows -> {QUEUE_FILE.relative_to(REPO)}",
          file=sys.stderr)
    print(f"Skipped (already processed): {skipped_processed:,}", file=sys.stderr)
    print(f"Skipped (no metadata or presences): {skipped_no_meta:,}", file=sys.stderr)

    # Province + carry-over summary
    by_province = Counter(r["province"] for r in queue_rows)
    print(f"\nBy province:", file=sys.stderr)
    for prov, n in by_province.most_common():
        print(f"  {prov}: {n:,}", file=sys.stderr)
    n_demoted = sum(1 for r in queue_rows if "phase_b_rejected_qid" in r)
    print(f"\nWith Phase B demote-hint: {n_demoted:,}", file=sys.stderr)


def cmd_show_batch(args) -> None:
    """Emit next N unprocessed queue rows as pretty JSON for the LLM to chew on."""
    if not QUEUE_FILE.exists():
        print("No queue. Run --prepare first.", file=sys.stderr)
        sys.exit(1)
    processed = load_processed_chains()

    n_target = args.n
    province_filter = set(p.strip() for p in args.provinces.split(",") if p.strip()) \
        if args.provinces else set()

    shown = 0
    with QUEUE_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d["chain_id"] in processed:
                continue
            if province_filter and d["province"] not in province_filter:
                continue
            print(json.dumps(d, ensure_ascii=False))
            shown += 1
            if shown >= n_target:
                break
    if shown == 0:
        print("(queue empty for the requested filter — Phase C is done!)",
              file=sys.stderr)


def cmd_status(args) -> None:
    """Print queue progress: total, processed, remaining, by province."""
    if not QUEUE_FILE.exists():
        print("No queue. Run --prepare first.", file=sys.stderr)
        sys.exit(1)
    processed = load_processed_chains()
    total = 0
    remaining = 0
    by_province_remaining: Counter = Counter()
    by_province_total: Counter = Counter()
    with QUEUE_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            total += 1
            by_province_total[d["province"]] += 1
            if d["chain_id"] not in processed:
                remaining += 1
                by_province_remaining[d["province"]] += 1
    print(f"Queue total:     {total:,}")
    print(f"Processed:       {total - remaining:,}")
    print(f"Remaining:       {remaining:,}")
    print(f"\nBy province (remaining / total):")
    for prov in sorted(by_province_total):
        rem = by_province_remaining[prov]
        tot = by_province_total[prov]
        print(f"  {prov}: {rem:,} / {tot:,}")


def cmd_verify(args) -> None:
    """Reuse Phase B's REST API verifier on Phase C's MCP-grounded entries."""
    if not VERIFIED_FILE.exists():
        print("No verified file yet.", file=sys.stderr)
        return
    centroids = _load_centroids_per_year()

    # Build chain -> (qid, name, province, presences) for entries written by
    # the MCP loop (match_type starts with "mcp_").
    chain_records: dict[str, dict] = {}
    with VERIFIED_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("status") != "matched":
                continue
            mt = d.get("match_type", "")
            if not mt.startswith("mcp_"):
                continue  # only verify MCP-written entries; inheritance was Phase B
            chain = d.get("current_chain")
            if not chain:
                continue
            rec = chain_records.setdefault(chain, {
                "qid": d.get("wikidata_qid"),
                "label": d.get("wikidata_label"),
                "province": d.get("province"),
                "name": d.get("csd_name"),
                "presences": [],
            })
            rec["presences"].append((d["tcpuid"], d["year"]))

    qids = sorted({r["qid"] for r in chain_records.values() if r["qid"]})
    print(f"Verifying {len(qids):,} unique QIDs from {len(chain_records):,} MCP-grounded chains...")
    if not qids:
        return
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

    bad = 0
    warn = 0
    good = 0
    for chain, rec in sorted(chain_records.items()):
        qid = rec["qid"]
        ent = entities.get(qid)
        if not ent:
            print(f"  MISSING: {chain} -> {qid}")
            bad += 1
            continue
        p31_qids = set()
        for claim in ent.get("claims", {}).get("P31", []):
            v = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(v, dict) and "id" in v:
                p31_qids.add(v["id"])
        if p31_qids and not p31_qids & GOOD_P31_QIDS:
            print(f"  BAD TYPE: {chain} \"{rec['name']}\" -> {qid} P31={p31_qids}")
            bad += 1
            continue
        target_set = PROVINCE_QIDS.get(rec["province"], set())
        if target_set and not _reaches_province(qid, target_set, entities):
            p131 = _entity_p131(ent)
            if p131:
                print(f"  WRONG PROVINCE: {chain} \"{rec['name']}\" -> {qid} P131={p131[:3]}")
                bad += 1
                continue
            warn += 1
        coord = _entity_coord(ent)
        if coord and rec["presences"]:
            cents = [centroids.get(p) for p in rec["presences"]]
            cents = [c for c in cents if c]
            if cents:
                cent = cents[-1]  # latest-year presence
                d_km = haversine(cent[0], cent[1], coord[0], coord[1])
                if d_km > MAX_DISTANCE_KM:
                    print(f"  FAR: {chain} \"{rec['name']}\" -> {qid} {d_km:.0f} km")
                    warn += 1
                    continue
        good += 1

    print(f"\nResults: {good} good, {warn} warnings, {bad} bad")
    if bad > 0:
        print("FIX BAD MATCHES before continuing!")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true",
                        help="Build queue from Phase A unresolved + Phase B demoted")
    parser.add_argument("--show-batch", type=int, dest="n", metavar="N",
                        help="Emit next N unprocessed queue rows as JSONL")
    parser.add_argument("--provinces", type=str, default="",
                        help="Comma-separated province filter (e.g. ON,SK)")
    parser.add_argument("--status", action="store_true",
                        help="Print queue progress")
    parser.add_argument("--verify", action="store_true",
                        help="REST-API verify all MCP-written entries in the verified file")
    args = parser.parse_args()

    if args.prepare:
        cmd_prepare(args)
    elif args.n is not None:
        cmd_show_batch(args)
    elif args.status:
        cmd_status(args)
    elif args.verify:
        cmd_verify(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
