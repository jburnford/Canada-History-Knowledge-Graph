#!/usr/bin/env python3
"""
Assign canonical CD names per chain, distinguishing OCR variants from
intentional name changes. Mirror of assign_canonical_names_simple.py
adapted for Census Divisions.

For each persistent CD chain (from persistent_cds_output/persistent_cd_registry.csv):
  1. Collect the raw NAME_CD strings used by every (cd_id, year) member.
  2. Find consensus name (most common across years).
  3. Compute string similarity of all variants to consensus.
  4. Apply canonical name only if names are similar (avg >= 70%, min >= 60%) -
     these are OCR variants. Otherwise treat as intentional name change.

Spatial sanity check is INHERENT: chains were built via spatial overlap
(Rule 1 IoU >= 0.95 / Rule 2-3 with name match), so a chain member's
polygon is by construction spatially equivalent to the chain anchor's.
This avoids the false-OCR-merge of small slivers like CD_ON_Renfew (3.4
km² sliver inside Renfrew that the chain pipeline correctly kept as a
singleton chain).

Output: canonical_cd_names.csv with one row per (raw_cd_id, year). Used
downstream by the CIDOC builder to emit E33_E41_Linguistic_Appellation
nodes with type=canonical vs type=variant for OCR-corrected entries.
"""

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz


def main():
    ap = argparse.ArgumentParser(
        description="Assign canonical CD names per chain (OCR detection)"
    )
    ap.add_argument("--registry", type=Path,
                    default="persistent_cds_output/persistent_cd_registry.csv")
    ap.add_argument("--mapping", type=Path,
                    default="persistent_cds_output/cd_id_year_to_chain.csv")
    ap.add_argument("--cidoc-dir", type=Path, default="neo4j_cidoc_crm_v2",
                    help="Source for e53_place_cd.csv (raw cd_id -> name lookup)")
    ap.add_argument("--out", type=Path, default="canonical_cd_names.csv")
    ap.add_argument("--min-avg-similarity", type=float, default=70.0)
    ap.add_argument("--min-min-similarity", type=float, default=60.0)
    args = ap.parse_args()

    print("Loading chain registry + mapping...", file=sys.stderr)
    chain_canonical = {}
    chain_province = {}
    with args.registry.open() as f:
        for r in csv.DictReader(f):
            chain_canonical[r["place_id"]] = r["canonical_name"]
            chain_province[r["place_id"]] = r["province"]

    chain_to_members = defaultdict(list)  # chain_id -> list of (raw_cd_id, year)
    with args.mapping.open() as f:
        for r in csv.DictReader(f):
            chain_to_members[r["chain_place_id"]].append(
                (r["raw_cd_id"], int(r["year"]))
            )

    raw_cd_name = {}
    e53 = args.cidoc_dir / "e53_place_cd.csv"
    with e53.open() as f:
        for r in csv.DictReader(f):
            raw_cd_name[r["place_id:ID"]] = r["name"]

    print(f"  {len(chain_canonical):,} chains, "
          f"{sum(len(v) for v in chain_to_members.values()):,} members",
          file=sys.stderr)

    print("\nAnalyzing chains for canonical names...", file=sys.stderr)
    results = []
    applied = 0
    skipped_single = 0
    skipped_change = 0

    for chain_id, members in chain_to_members.items():
        if len(members) < 2:
            skipped_single += 1
            continue
        members_sorted = sorted(members, key=lambda x: x[1])
        # Per-(year) name; multiple members might share a year if the chain
        # absorbed siblings (rare).
        year_name = []
        for cd_id, yr in members_sorted:
            name = raw_cd_name.get(cd_id, "")
            if name:
                year_name.append((yr, name, cd_id))
        if not year_name:
            continue
        names = [n for _, n, _ in year_name]
        consensus_name, consensus_count = Counter(names).most_common(1)[0]

        # Similarity of each non-consensus variant to consensus.
        sims = [
            fuzz.ratio(n.lower(), consensus_name.lower())
            for n in set(names) if n != consensus_name
        ]
        if not sims:
            avg_sim = 100.0
            min_sim = 100.0
            should_apply = True
            reason = "unanimous"
        else:
            avg_sim = sum(sims) / len(sims)
            min_sim = min(sims)
            if (avg_sim >= args.min_avg_similarity
                    and min_sim >= args.min_min_similarity):
                should_apply = True
                reason = "ocr_variants"
                applied += 1
            else:
                should_apply = False
                reason = "name_change"
                skipped_change += 1

        for yr, name, cd_id in year_name:
            results.append({
                "chain_place_id": chain_id,
                "raw_cd_id": cd_id,
                "year": yr,
                "original_name": name,
                "canonical_name": consensus_name if should_apply else name,
                "should_apply": should_apply,
                "consensus_count": consensus_count,
                "total_years": len(year_name),
                "avg_similarity": round(avg_sim, 1),
                "min_similarity": round(min_sim, 1) if min_sim != 100 else 100,
                "reason": reason,
                "all_names": " | ".join(sorted(set(names))),
                "province": chain_province.get(chain_id, ""),
            })

    if not results:
        print("No chain has >1 member; nothing to write.", file=sys.stderr)
        return

    df = pd.DataFrame(results).sort_values(["chain_place_id", "year"])
    df.to_csv(args.out, index=False)
    print(f"\nWrote {len(results)} records → {args.out}")
    print(f"\nSummary:")
    print(f"  Chains analyzed (multi-member):  {applied + skipped_change}")
    print(f"  OCR canonical applied:           {applied}")
    print(f"  Name-change preserved:           {skipped_change}")
    print(f"  Single-member chains (skipped):  {skipped_single}")

    applied_df = df[df["should_apply"] & (df["original_name"] != df["canonical_name"])]
    if not applied_df.empty:
        print(f"\nSample OCR corrections:")
        sample = applied_df.groupby("chain_place_id").first().reset_index().head(10)
        print(sample[[
            "chain_place_id", "original_name", "canonical_name",
            "avg_similarity", "all_names"
        ]].to_string(index=False))

    changed_df = df[~df["should_apply"]]
    if not changed_df.empty:
        print(f"\nSample preserved name changes (within-chain variants too dissimilar to merge):")
        sample = changed_df.groupby("chain_place_id").first().reset_index().head(5)
        print(sample[[
            "chain_place_id", "year", "original_name",
            "min_similarity", "all_names"
        ]].to_string(index=False))


if __name__ == "__main__":
    main()
