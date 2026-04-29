#!/usr/bin/env python3
"""Build a V1T1 ↔ GDB TCPUID crosswalk for one census year.

Background: the existing pipeline naively joins V1T1 census Excel rows to GDB
polygons by `V1T1_<year> == TCPUID_CSD_<year>` string equality (see
build_census_observations_v2.py:286–292). The two columns share strings but
encode different entities — most acutely on the prairies in 1911, where V1T1
includes ~5,972 township-level rows (T## R## M(E|W)# pattern) that have no GDB
counterpart, but their codes collide with real GDB CSD codes (e.g. V1T1
SK216003="T24 R1 MW3" vs GDB SK216003="Saskatoon c").

This script builds a deterministic crosswalk by:
  1. Filtering OUT V1T1 township-pattern rows (no GDB polygon for them).
  2. Filtering OUT V1T1 CD-level aggregate rows (CSD_NO=0).
  3. Matching the remaining settlement/aggregate V1T1 rows to GDB TCPUIDs by
     (PR, _aggressive_base_normalize(name)) key.
  4. (Optional, requires Wikidata grounding to be complete) QID-anchor disambiguation
     for any name collisions: search Wikidata for the V1T1 name, look up the QID
     in csd_verified_matches.jsonl, walk to the persistent_place_id and pick the
     year-N TCPUID member. Flag --use-qid to enable.

Output: wikidata_grounding/v1t1_<year>_crosswalk.csv with columns:
  v1t1_code, pr_cd_csd, pr, cd_no, csd_no, tcpuid, match_method, confidence, notes
plus wikidata_grounding/v1t1_<year>_unmatched.csv for V1T1 rows we couldn't bind.

Usage:
    conda run -n geo python3 scripts/build_v1t1_crosswalk.py --year 1911
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from csd_name_normalize import grouping_key
from _config import CONFIG

REPO = Path(__file__).resolve().parents[1]
GDB_PATH = str(CONFIG.gdb_path)

V1T1_FILES = {
    1911: CONFIG.data_root / "1911Tables" / "1911" / "1911_V1T1_PUB_202306.xlsx",
}

# Township-pattern detector: e.g. "T24 R1 MW3", "T 13 R 3 ME 1". Prairie-only.
TOWNSHIP_RE = re.compile(r"^\s*T\s?\d+\s+R\s?\d+\s+M[EW]\s?\d", re.IGNORECASE)


def is_township_pattern(name: str) -> bool:
    return bool(TOWNSHIP_RE.match(name or ""))


def load_v1t1(year: int):
    import pandas as pd
    df = pd.read_excel(V1T1_FILES[year])
    id_col = f"V1T1_{year}"
    return df, id_col


def load_gdb_layer(year: int):
    import geopandas as gpd
    layer = f"CANADA_{year}_CSD"
    gdf = gpd.read_file(GDB_PATH, layer=layer)
    return gdf


def build_gdb_index(gdf, year: int):
    """Build (PR, normalized_name) → list[(TCPUID, tier)] index. Multi-value
    entries flag name collisions within a province; tier is stored so V1T1's
    tier info can disambiguate at match time."""
    name_col = f"NAME_CSD_{year}"
    pr_col = f"PR_{year}"
    id_col = f"TCPUID_CSD_{year}"
    cd_name_col = f"NAME_CD_{year}"

    by_key = defaultdict(list)
    meta = {}
    for _, row in gdf.iterrows():
        tcpuid = row.get(id_col)
        name = row.get(name_col)
        pr = row.get(pr_col)
        cd_name = row.get(cd_name_col, "")
        if not tcpuid or not name or not pr:
            continue
        gk = grouping_key(str(name))
        if not gk[0]:
            continue
        key = (str(pr).strip(), gk[0])
        by_key[key].append((tcpuid, gk[1]))
        meta[tcpuid] = {"name": str(name), "pr": str(pr), "cd_name": str(cd_name) if cd_name else ""}
    return by_key, meta


def match_v1t1_to_gdb(df, id_col: str, year: int, gdb_index, gdb_meta):
    """Yield matched rows + unmatched + ambiguous rows."""
    matched, unmatched, ambiguous = [], [], []
    for _, row in df.iterrows():
        v1t1_code = row.get(id_col)
        name = str(row.get("PR_CD_CSD", "")).strip()
        pr = str(row.get("PR", "")).strip()
        cd_no = row.get("CD_NO")
        csd_no = row.get("CSD_NO")

        if not v1t1_code or not name or not pr:
            continue

        # Filter township-pattern rows (no GDB counterpart).
        if is_township_pattern(name):
            continue

        # Filter CD-level aggregates (CSD_NO=0); they aggregate already-counted
        # rows and would double-count if joined.
        try:
            if int(csd_no) == 0:
                continue
        except (ValueError, TypeError):
            pass  # non-zero / non-numeric CSD_NO is fine

        v1t1_gk = grouping_key(name)
        norm_name = v1t1_gk[0]
        v1t1_tier = v1t1_gk[1]
        if not norm_name:
            continue
        key = (pr, norm_name)
        candidates = gdb_index.get(key, [])  # list of (tcpuid, tier)

        common = {
            "v1t1_code": v1t1_code,
            "pr_cd_csd": name,
            "pr": pr,
            "cd_no": str(cd_no) if cd_no is not None and not _isnan(cd_no) else "",
            "csd_no": str(csd_no) if csd_no is not None and not _isnan(csd_no) else "",
        }

        if len(candidates) == 1:
            tcpuid, _gtier = candidates[0]
            matched.append({
                **common,
                "tcpuid": tcpuid,
                "match_method": "name_pr",
                "confidence": "high",
                "notes": "",
            })
        elif len(candidates) == 0:
            unmatched.append({**common, "tcpuid": "", "reason": "no_gdb_name_match"})
        else:
            # Multiple GDB matches share (PR, canonical_name). Tiebreak by tier:
            # find candidates whose tier matches V1T1's tier. If exactly one,
            # accept it. Otherwise log as ambiguous for QID-anchor / human review.
            tier_matches = [(t, gt) for t, gt in candidates if gt == v1t1_tier]
            if len(tier_matches) == 1:
                tcpuid, _gtier = tier_matches[0]
                matched.append({
                    **common,
                    "tcpuid": tcpuid,
                    "match_method": "name_pr_tier",
                    "confidence": "high",
                    "notes": f"name_collision_resolved_by_tier ({v1t1_tier})",
                })
            else:
                ambiguous.append({
                    **common,
                    "tcpuid_candidates": ",".join(t for t, _ in candidates),
                    "reason": f"name_collision ({len(candidates)} GDB rows, "
                              f"tier_matches={len(tier_matches)})",
                })
    return matched, unmatched, ambiguous


def _isnan(v) -> bool:
    try:
        import math
        return isinstance(v, float) and math.isnan(v)
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=1911)
    ap.add_argument(
        "--out-dir",
        default=str(REPO / "wikidata_grounding"),
        help="Where to write the crosswalk + unmatched CSVs",
    )
    args = ap.parse_args()
    year = args.year
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading V1T1 {year}...", file=sys.stderr)
    df, id_col = load_v1t1(year)
    print(f"  {len(df)} V1T1 rows", file=sys.stderr)

    print(f"Loading GDB layer for {year}...", file=sys.stderr)
    gdf = load_gdb_layer(year)
    print(f"  {len(gdf)} GDB CSDs", file=sys.stderr)

    print("Building GDB (PR, name) index...", file=sys.stderr)
    gdb_index, gdb_meta = build_gdb_index(gdf, year)
    collisions = sum(1 for vs in gdb_index.values() if len(vs) > 1)
    print(f"  {len(gdb_index)} unique (PR, name) keys; {collisions} with collisions",
          file=sys.stderr)

    print("Matching V1T1 to GDB...", file=sys.stderr)
    matched, unmatched, ambiguous = match_v1t1_to_gdb(df, id_col, year, gdb_index, gdb_meta)
    print(f"  matched: {len(matched)}", file=sys.stderr)
    print(f"  unmatched: {len(unmatched)}", file=sys.stderr)
    print(f"  ambiguous (name collisions): {len(ambiguous)}", file=sys.stderr)

    cw_path = out_dir / f"v1t1_{year}_crosswalk.csv"
    um_path = out_dir / f"v1t1_{year}_unmatched.csv"
    am_path = out_dir / f"v1t1_{year}_ambiguous.csv"

    if matched:
        with cw_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "v1t1_code", "pr_cd_csd", "pr", "cd_no", "csd_no",
                "tcpuid", "match_method", "confidence", "notes",
            ])
            w.writeheader()
            w.writerows(matched)
        print(f"Wrote {cw_path}", file=sys.stderr)

    if unmatched:
        with um_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "v1t1_code", "pr_cd_csd", "pr", "cd_no", "csd_no", "tcpuid", "reason",
            ])
            w.writeheader()
            w.writerows(unmatched)
        print(f"Wrote {um_path}", file=sys.stderr)

    if ambiguous:
        with am_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "v1t1_code", "pr_cd_csd", "pr", "cd_no", "csd_no",
                "tcpuid_candidates", "reason",
            ])
            w.writeheader()
            w.writerows(ambiguous)
        print(f"Wrote {am_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
