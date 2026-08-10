#!/usr/bin/env python3
"""Emit URL-redirect rows for chain ids and presence URLs that changed
between two persistent-place registry states.

The chain builder's own place_chain_redirects.csv only covers bridge-pass
merges computed WITHIN one build. When the builder's rules change (e.g. the
SAME_AS threshold fix), chains merge at the union level and previously
published chain ids disappear with no redirect. This script diffs an OLD
state (the one the live site was rendered from) against the NEW state and
appends rows to two cumulative, git-committed history files that
generate_rag_pages.py consumes alongside the per-build redirect CSVs:

  persistent_places_output/place_chain_redirect_history.csv
  persistent_places_output/place_presence_redirect_history.csv

Usage (typically once per registry-changing release, BEFORE deploying):

  python3 scripts/diff_registry_redirects.py \
      --old-registry /path/to/old/persistent_place_registry.csv \
      --old-mapping  /path/to/old/tcpuid_year_to_place.csv \
      --old-e53      /path/to/old/e53_place_csd.csv \
      --new-registry persistent_places_output/persistent_place_registry.csv \
      --new-mapping  persistent_places_output/tcpuid_year_to_place.csv

The history files are append-and-dedupe: rerunning with the same inputs is
idempotent. Rows whose old id still exists in the new registry are never
emitted (the renderer would also refuse to stub over a live page).
"""

import argparse
import csv
import re
import sys
from pathlib import Path


def slugify(s: str) -> str:
    # Verbatim copy of generate_rag_pages.slugify — presence/place URL slugs
    # must match the renderer exactly.
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def read_rows(path: Path) -> list[dict]:
    with open(path) as f:
        return list(csv.DictReader(f))


def load_state(registry_csv: Path, mapping_csv: Path, e53_csv: Path | None):
    """Return (chain_info, member_map, fallback_names).

    chain_info: pid -> {name, province, years}
    member_map: (tcpuid, year) -> pid   (registry chains only)
    fallback_names: pid -> {name, province} for e53 rows not in the registry
                    (the PLACE_<uid>_<year> singletons minted downstream).
    """
    chain_info = {}
    for r in read_rows(registry_csv):
        chain_info[r["persistent_place_id"]] = {
            "name": r["canonical_name"],
            "province": r["province"],
            "years": r["years_active"],
        }
    member_map = {}
    for r in read_rows(mapping_csv):
        member_map[(r["tcpuid"], int(r["year"]))] = r["persistent_place_id"]
    fallback_names = {}
    if e53_csv and e53_csv.exists():
        for r in read_rows(e53_csv):
            pid = r["place_id:ID"]
            if pid not in chain_info:
                fallback_names[pid] = {
                    "name": r["name"], "province": r["province"],
                    "years": r.get("years_active", ""),
                }
    return chain_info, member_map, fallback_names


def append_dedupe(path: Path, rows: list[dict], key_cols: list[str],
                  all_cols: list[str]) -> int:
    existing = set()
    have_file = path.exists()
    if have_file:
        for r in read_rows(path):
            existing.add(tuple(r.get(c, "") for c in key_cols))
    added = [r for r in rows
             if tuple(str(r.get(c, "")) for c in key_cols) not in existing]
    mode = "a" if have_file else "w"
    with open(path, mode, newline="") as f:
        w = csv.DictWriter(f, fieldnames=all_cols)
        if not have_file:
            w.writeheader()
        for r in added:
            w.writerow({c: r.get(c, "") for c in all_cols})
    return len(added)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-registry", required=True, type=Path)
    ap.add_argument("--old-mapping", required=True, type=Path)
    ap.add_argument("--old-e53", type=Path, default=None,
                    help="OLD e53_place_csd.csv — supplies names for the "
                         "fallback PLACE_<uid>_<year> singleton pages")
    ap.add_argument("--new-registry", required=True, type=Path)
    ap.add_argument("--new-mapping", required=True, type=Path)
    ap.add_argument("--out-dir", type=Path,
                    default=Path("persistent_places_output"))
    args = ap.parse_args()

    old_info, old_map, old_fallbacks = load_state(
        args.old_registry, args.old_mapping, args.old_e53)
    new_info, new_map, _ = load_state(
        args.new_registry, args.new_mapping, None)

    def old_pid_of(uid: str, yr: int) -> str:
        return old_map.get((uid, yr), f"PLACE_{uid}_{yr}")

    def new_pid_of(uid: str, yr: int) -> str:
        return new_map.get((uid, yr), f"PLACE_{uid}_{yr}")

    def old_meta(pid):
        return old_info.get(pid) or old_fallbacks.get(pid)

    # Universe of presences = union of both mappings (fallback singletons
    # that stayed fallback have identical URLs and drop out naturally).
    presences = set(old_map) | set(new_map)

    # ---- chain-id redirects ------------------------------------------------
    # Group members of each disappeared old chain by their new chain.
    from collections import defaultdict
    old_members = defaultdict(list)
    for (uid, yr) in presences:
        old_members[old_pid_of(uid, yr)].append((uid, yr))

    chain_rows = []
    for old_pid, members in sorted(old_members.items()):
        if old_pid in new_info:
            continue  # id survives; live page continues to exist
        meta = old_meta(old_pid)
        if meta is None:
            continue  # never rendered (no page to redirect)
        targets = {new_pid_of(uid, yr) for uid, yr in members}
        targets = {t for t in targets if t in new_info}
        if not targets:
            continue
        if len(targets) == 1:
            target = targets.pop()
        else:
            # Old chain split across several new chains: point the stub at
            # the new chain holding the old chain's latest member.
            latest = max(members, key=lambda m: m[1])
            target = new_pid_of(*latest)
            if target not in new_info:
                target = sorted(targets)[0]
        tmeta = new_info[target]
        chain_rows.append({
            "old_place_id": old_pid,
            "new_place_id": target,
            "province": meta["province"],
            "old_canonical_name": meta["name"],
            "new_canonical_name": tmeta["name"],
            "old_years_active": meta.get("years", ""),
            "new_years_active": tmeta["years"],
            "confidence": "registry_diff",
            "reason": "registry_diff",
        })

    # ---- presence-URL redirects ---------------------------------------------
    presence_rows = []
    for (uid, yr) in sorted(presences):
        opid, npid = old_pid_of(uid, yr), new_pid_of(uid, yr)
        ometa = old_meta(opid)
        nmeta = new_info.get(npid)
        if ometa is None or nmeta is None:
            continue
        if slugify(ometa["name"]) == slugify(nmeta["name"]):
            continue
        presence_rows.append({
            "tcpuid": uid,
            "year": yr,
            "province": nmeta["province"] or ometa["province"],
            "old_canonical_name": ometa["name"],
            "new_canonical_name": nmeta["name"],
            "old_place_id": opid,
            "new_place_id": npid,
        })

    chain_cols = ["old_place_id", "new_place_id", "province",
                  "old_canonical_name", "new_canonical_name",
                  "old_years_active", "new_years_active",
                  "confidence", "reason"]
    presence_cols = ["tcpuid", "year", "province",
                     "old_canonical_name", "new_canonical_name",
                     "old_place_id", "new_place_id"]

    n1 = append_dedupe(args.out_dir / "place_chain_redirect_history.csv",
                       chain_rows, ["old_place_id"], chain_cols)
    n2 = append_dedupe(args.out_dir / "place_presence_redirect_history.csv",
                       presence_rows, ["tcpuid", "year", "old_canonical_name"],
                       presence_cols)
    print(f"chain redirect history: +{n1} rows "
          f"({len(chain_rows)} candidates)", file=sys.stderr)
    print(f"presence redirect history: +{n2} rows "
          f"({len(presence_rows)} candidates)", file=sys.stderr)


if __name__ == "__main__":
    main()
