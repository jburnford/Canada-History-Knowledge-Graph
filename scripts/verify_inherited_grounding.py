"""Phase B: REST-API verification of Phase A inheritance candidates.

Reuses fetch_wikidata_entities + P31/P131/P625 logic from disambiguate_csds.py
to validate that each inherited QID is at least:
  - A real Wikidata entity (not deleted/redirected)
  - Of an acceptable settlement/municipality type (P31)
  - Located in the expected province (P131 chain)
  - (warning only) within reasonable distance of a per-year CSD centroid

Limitations: cannot distinguish two valid-looking entities that both pass these
checks. Phase A's tier_root + spatial-link discrimination handles that case.
This pass is a safety net for "obviously wrong" inheritances (railway stations,
electoral districts, wrong-province matches).

Outputs (in wikidata_grounding/):
  presence_verified_matches.jsonl  — passing matches, status=matched
  presence_verify_audit.csv        — per-chain decision + evidence
  presence_verify_demoted.csv      — failing matches → input for Phase C
"""

from __future__ import annotations

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
AUDIT_IN = GROUNDING_DIR / "presence_inheritance_audit.csv"
MATCHES_IN = GROUNDING_DIR / "presence_inheritance_matches.jsonl"
CIDOC_DIR = REPO / "neo4j_cidoc_crm_v2"

OUT_VERIFIED = GROUNDING_DIR / "presence_verified_matches.jsonl"
OUT_AUDIT = GROUNDING_DIR / "presence_verify_audit.csv"
OUT_DEMOTED = GROUNDING_DIR / "presence_verify_demoted.csv"

YEARS = (1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921)


def load_centroids() -> dict[tuple[str, int], tuple[float, float]]:
    """(tcpuid, year) -> (lat, lon) from e94_space_primitive_<year>.csv."""
    out: dict[tuple[str, int], tuple[float, float]] = {}
    for year in YEARS:
        path = CIDOC_DIR / f"e94_space_primitive_{year}.csv"
        if not path.exists():
            continue
        with path.open() as f:
            for row in csv.DictReader(f):
                space_id = row["space_id:ID"]
                # Format: <tcpuid>_<year>_centroid
                if not space_id.endswith("_centroid"):
                    continue
                stem = space_id[: -len("_centroid")]
                # split off the trailing _<year>
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


def chain_centroid(presences, centroids) -> tuple[float, float] | None:
    """Pick a representative centroid for a chain — prefer the latest year
    that has a centroid (matches Phase A's anchor preference)."""
    candidates = [(yr, centroids[(tcp, yr)])
                  for tcp, yr in presences if (tcp, yr) in centroids]
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


def load_inheritance_audit() -> list[dict]:
    """Load Phase A audit rows where decision is INHERIT_QID (we don't verify
    INHERIT_MINT — those are propagated curated decisions, not new groundings)."""
    rows: list[dict] = []
    with AUDIT_IN.open() as f:
        for r in csv.DictReader(f):
            if r["decision"] != "INHERIT_QID":
                continue
            if not r["inherited_qid"]:
                continue
            rows.append(r)
    return rows


def load_inheritance_matches() -> dict[str, list[dict]]:
    """chain_id -> list of presence-level match records (one per presence)."""
    out: dict[str, list[dict]] = defaultdict(list)
    with MATCHES_IN.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("status") != "matched":
                continue
            out[d["current_chain"]].append(d)
    return out


def main() -> None:
    print("Loading Phase A audit + matches...", file=sys.stderr)
    audit_rows = load_inheritance_audit()
    matches_by_chain = load_inheritance_matches()
    print(f"  {len(audit_rows):,} INHERIT_QID chains to verify", file=sys.stderr)

    print("Loading per-presence centroids...", file=sys.stderr)
    centroids = load_centroids()
    print(f"  {len(centroids):,} centroids loaded", file=sys.stderr)

    qids = sorted({r["inherited_qid"] for r in audit_rows})
    print(f"Fetching {len(qids):,} unique QIDs from Wikidata...", file=sys.stderr)
    entities = fetch_wikidata_entities(qids)
    print(f"  {len(entities):,} entities returned", file=sys.stderr)

    # Walk P131 parents until province-resolvable or max depth
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
        print(f"Resolving {len(needed):,} P131 parents (hop {hop})...", file=sys.stderr)
        entities.update(fetch_wikidata_entities(sorted(needed)))

    audit_out: list[dict] = []
    verified_matches: list[dict] = []
    demoted: list[dict] = []
    decision_counter: Counter = Counter()
    fail_reasons: Counter = Counter()

    for r in audit_rows:
        chain = r["chain_id"]
        qid = r["inherited_qid"]
        province = r["province"]
        confidence = r["confidence"]
        signals = r["signals"]
        name = r["name"]

        notes: list[str] = []
        is_fail = False
        is_warn = False

        ent = entities.get(qid)
        if not ent:
            notes.append("MISSING from Wikidata")
            is_fail = True
            fail_reasons["missing_entity"] += 1
        else:
            # P31 check
            p31_qids: set[str] = set()
            for claim in ent.get("claims", {}).get("P31", []):
                v = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                if isinstance(v, dict) and "id" in v:
                    p31_qids.add(v["id"])
            if not p31_qids:
                notes.append("no P31 (instance of) claims")
                is_warn = True
            elif not p31_qids & GOOD_P31_QIDS:
                notes.append(f"P31={sorted(p31_qids)[:3]} not in allowed settlement types")
                is_fail = True
                fail_reasons["bad_p31"] += 1

            # P131 province check
            target_set = PROVINCE_QIDS.get(province, set())
            if target_set:
                if not _reaches_province(qid, target_set, entities):
                    p131 = _entity_p131(ent)
                    if not p131:
                        notes.append("STUB: empty P131")
                        is_warn = True
                    else:
                        notes.append(
                            f"WRONG PROVINCE: expected {province} {sorted(target_set)}; "
                            f"P131={p131[:3]}"
                        )
                        is_fail = True
                        fail_reasons["wrong_province"] += 1

            # Coordinate distance check. For high-confidence inheritance
            # (S1/S2 strict spatial year-link), the link IS the proof — a
            # shifted modern Wikidata coord is just data drift, warning only.
            # For low/medium (S3/S4, name-based), distance >50km usually
            # means tier_root picked the wrong same-named entity (e.g., the
            # "St. Laurent" Q3462701 problem: 326 km from the actual CSD).
            coord = _entity_coord(ent)
            chain_presences = [(m["tcpuid"], m["year"])
                               for m in matches_by_chain.get(chain, [])]
            cent = chain_centroid(chain_presences, centroids)
            if coord and cent:
                d_km = haversine(cent[0], cent[1], coord[0], coord[1])
                if d_km > MAX_DISTANCE_KM:
                    note = f"FAR: {d_km:.0f} km from chain centroid"
                    if confidence == "high":
                        notes.append(note + " (spatial link is proof)")
                        is_warn = True
                    else:
                        notes.append(note)
                        is_fail = True
                        fail_reasons["far_distance_no_spatial_proof"] += 1

        if is_fail:
            decision = "DEMOTED"
            decision_counter[decision] += 1
            demoted.append({
                "chain_id": chain,
                "name": name,
                "province": province,
                "inherited_qid": qid,
                "inherited_label": r["inherited_label"],
                "phase_a_signals": signals,
                "phase_a_confidence": confidence,
                "fail_reason": "; ".join(notes),
            })
        else:
            decision = "VERIFIED_WARN" if is_warn else "VERIFIED"
            decision_counter[decision] += 1
            for m in matches_by_chain.get(chain, []):
                vm = dict(m)
                vm["match_type"] = (
                    "inherit_verified_warn" if is_warn else "inherit_verified"
                )
                vm["verify_notes"] = "; ".join(notes) if notes else ""
                vm["needs_verify"] = False
                verified_matches.append(vm)

        audit_out.append({
            "chain_id": chain,
            "name": name,
            "province": province,
            "inherited_qid": qid,
            "inherited_label": r["inherited_label"],
            "phase_a_signals": signals,
            "phase_a_confidence": confidence,
            "decision": decision,
            "notes": "; ".join(notes),
        })

    GROUNDING_DIR.mkdir(parents=True, exist_ok=True)

    with OUT_VERIFIED.open("w") as f:
        for m in verified_matches:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    audit_fields = [
        "chain_id", "name", "province",
        "inherited_qid", "inherited_label",
        "phase_a_signals", "phase_a_confidence",
        "decision", "notes",
    ]
    with OUT_AUDIT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=audit_fields)
        w.writeheader()
        w.writerows(audit_out)

    demoted_fields = [
        "chain_id", "name", "province",
        "inherited_qid", "inherited_label",
        "phase_a_signals", "phase_a_confidence",
        "fail_reason",
    ]
    with OUT_DEMOTED.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=demoted_fields)
        w.writeheader()
        w.writerows(demoted)

    print("\n=== Phase B verification summary ===", file=sys.stderr)
    for k, v in decision_counter.most_common():
        print(f"  {k:<16} {v:>6,}", file=sys.stderr)
    if fail_reasons:
        print("Fail reasons:", file=sys.stderr)
        for k, v in fail_reasons.most_common():
            print(f"  {k:<20} {v:>6,}", file=sys.stderr)
    print(f"\nPresence-level verified matches: {len(verified_matches):,}", file=sys.stderr)
    print(f"  → {OUT_VERIFIED.relative_to(REPO)}", file=sys.stderr)
    print(f"  → {OUT_AUDIT.relative_to(REPO)} ({len(audit_out):,} chains)", file=sys.stderr)
    print(f"  → {OUT_DEMOTED.relative_to(REPO)} ({len(demoted):,} chains)", file=sys.stderr)


if __name__ == "__main__":
    main()
