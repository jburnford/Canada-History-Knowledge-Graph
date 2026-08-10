#!/usr/bin/env python3
"""Post-process the persistent CD registry to merge same-province chain pairs
whose canonical names look like OCR typos of each other.

Why this is a separate tool (not a step in build_persistent_cds.py): the
chain-builder reads e93_presence_cd_<year>.csv via augment_node_meta_from_e53
to add singletons. Once that file has been regenerated downstream (writing
chain_ids as cd_ids), re-running build_persistent_cds doubles the registry
because it treats chain_ids as fresh raw_cd_ids. This tool side-steps the
feedback loop by operating on the registry + lineage CSVs directly.

Detection rule (twin safeguards against false positives):
  1. Levenshtein edit distance ≤ 1: catches Renfew/Renfrew (1) and
     Glengary/Glengarry (1); rejects different ward names (Montréal,
     Ste. Anne / Montréal, St. Antoine, distance 5).
  2. Identical numeric tokens: rejects "Division No. 1" / "Division No. 10"
     and similar series, where edit distance is 1 but the numbers carry
     meaning.
  3. Year-overlap required: don't fuse a 1861 chain with a genuinely
     different 1921 chain that happens to share a name.

Winner = chain with more years_active, ties broken by membership count.
The loser's chain id is replaced everywhere (registry, member map, lineage)
by the winner's. Loser's years_active are merged into the winner.

Reads + writes:
  persistent_cds_output/persistent_cd_registry.csv
  persistent_cds_output/cd_id_year_to_chain.csv
  persistent_cds_output/cd_lineage.csv
  persistent_cds_output/typo_merges.csv  (audit)
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
from rapidfuzz.distance import Levenshtein

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DIR = REPO / "persistent_cds_output"

TYPO_MAX_DISTANCE = 1

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _normalize import normalize_for_match  # noqa: E402 (shared, was a drift-prone copy)


def numeric_tokens(s: str) -> tuple:
    return tuple(re.findall(r"\d+", s or ""))


def find_typo_pairs(registry_df: pd.DataFrame) -> list[dict]:
    """Return one record per (loser, winner) merge to apply."""
    pairs = []
    by_prov = registry_df.groupby("province")
    for prov, sub in by_prov:
        rows = sub.to_dict("records")
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                a_name = str(a["canonical_name"] or "")
                b_name = str(b["canonical_name"] or "")
                if not a_name or not b_name:
                    continue
                if normalize_for_match(a_name) == normalize_for_match(b_name):
                    continue  # already handled by chain-builder normalization
                if numeric_tokens(a_name) != numeric_tokens(b_name):
                    continue
                dist = Levenshtein.distance(a_name, b_name)
                if dist > TYPO_MAX_DISTANCE:
                    continue
                a_years = {int(y) for y in str(a["years_active"]).split(";") if y}
                b_years = {int(y) for y in str(b["years_active"]).split(";") if y}
                if not (a_years & b_years):
                    continue
                if a["num_years"] >= b["num_years"]:
                    winner, loser = a, b
                else:
                    winner, loser = b, a
                pairs.append({
                    "loser_chain_id": loser["place_id"],
                    "loser_canonical": loser["canonical_name"],
                    "winner_chain_id": winner["place_id"],
                    "winner_canonical": winner["canonical_name"],
                    "edit_distance": dist,
                    "province": prov,
                    "loser_years": loser["years_active"],
                    "winner_years": winner["years_active"],
                })
    return pairs


def resolve_redirect(redirect: dict, cid: str) -> str:
    """Follow redirect chain to the final winner."""
    seen = set()
    while cid in redirect and cid not in seen:
        seen.add(cid)
        cid = redirect[cid]
    return cid


def apply_merges(registry_df, member_df, lineage_df, pairs):
    """Apply the typo merges. Returns (new_registry, new_member, new_lineage)."""
    redirect = {p["loser_chain_id"]: p["winner_chain_id"] for p in pairs}
    losers = set(redirect)

    # Sum loser years into winner.
    winner_year_additions = defaultdict(set)
    for p in pairs:
        target = resolve_redirect(redirect, p["winner_chain_id"])
        for y in str(p["loser_years"]).split(";"):
            if y.strip():
                winner_year_additions[target].add(int(y))

    new_registry = registry_df[~registry_df["place_id"].isin(losers)].copy()
    for idx, row in new_registry.iterrows():
        cid = row["place_id"]
        if cid in winner_year_additions:
            existing = {int(y) for y in str(row["years_active"]).split(";") if y}
            merged = sorted(existing | winner_year_additions[cid])
            new_registry.at[idx, "years_active"] = ";".join(str(y) for y in merged)
            new_registry.at[idx, "num_years"] = len(merged)

    new_member = member_df.copy()
    new_member["chain_place_id"] = new_member["chain_place_id"].apply(
        lambda c: resolve_redirect(redirect, c) if c in redirect else c
    )

    new_lineage = lineage_df.copy()
    new_lineage[":START_ID"] = new_lineage[":START_ID"].apply(
        lambda c: resolve_redirect(redirect, c) if c in redirect else c
    )
    new_lineage[":END_ID"] = new_lineage[":END_ID"].apply(
        lambda c: resolve_redirect(redirect, c) if c in redirect else c
    )
    # Drop self-loops + duplicates created by the remap.
    new_lineage = new_lineage[
        new_lineage[":START_ID"] != new_lineage[":END_ID"]
    ].drop_duplicates(subset=["lineage_type", ":START_ID", ":END_ID",
                              "change_year:int"])

    return new_registry, new_member, new_lineage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    reg_path = args.dir / "persistent_cd_registry.csv"
    mem_path = args.dir / "cd_id_year_to_chain.csv"
    lin_path = args.dir / "cd_lineage.csv"
    audit_path = args.dir / "typo_merges.csv"

    registry = pd.read_csv(reg_path)
    member = pd.read_csv(mem_path)
    lineage = pd.read_csv(lin_path)
    print(f"Loaded {len(registry)} chains, {len(member)} memberships, "
          f"{len(lineage)} lineage edges", file=sys.stderr)

    pairs = find_typo_pairs(registry)
    print(f"Detected {len(pairs)} typo-pair merges:", file=sys.stderr)
    for p in pairs:
        print(f"  {p['loser_canonical']!r} ({p['loser_years']}) -> "
              f"{p['winner_canonical']!r} ({p['winner_years']}) "
              f"[{p['province']}, dist={p['edit_distance']}]", file=sys.stderr)

    if not pairs:
        return

    new_reg, new_mem, new_lin = apply_merges(registry, member, lineage, pairs)
    print(f"After merge: {len(new_reg)} chains "
          f"(was {len(registry)}, dropped {len(registry) - len(new_reg)})",
          file=sys.stderr)

    if args.dry_run:
        print("Dry-run: no files written.", file=sys.stderr)
        return

    new_reg.to_csv(reg_path, index=False)
    new_mem.to_csv(mem_path, index=False)
    new_lin.to_csv(lin_path, index=False)
    pd.DataFrame(pairs).to_csv(audit_path, index=False)
    print(f"Wrote {reg_path}, {mem_path}, {lin_path}, {audit_path}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
