#!/usr/bin/env python3
"""Rescue 1881 Borealis residents whose TCPUID didn't match our chain
registry. Most are city wards (Quebec City, Toronto, Montreal sub-areas)
where Borealis enumerates at finer granularity than our registry — e.g.
Borealis has TCPUID `QC079003` for "St-Roch (Sud/South)" but our 1881
registry only has QC079001/QC079002, both rolling up to one
PLACE_QC183xxx ward chain.

Strategy: for each unmatched (tcpuid, province, distno, sdistnam) tuple,
find a chain in the SAME (province, distno) whose 1881 canonical_name
text-matches the Borealis sdistnam after normalization. Auto-accept
exact and high-confidence partial matches; flag the rest for manual review.

Inputs:
  residents_1881_output/quarantine/unmatched_chain.parquet
  persistent_places_output/tcpuid_year_to_place.csv
  persistent_places_output/persistent_place_registry.csv

Outputs:
  residents_1881_output/unmatched_tcpuid_rescue.csv      (auto-accepted)
  residents_1881_output/unmatched_tcpuid_review.csv      (needs human review)

The rescue CSV is then consumed by prepare_1881_residents.py as a fallback
join. Chains rescued this way share an existing chain_id with another
TCPUID, which is correct: Borealis's split city wards are sub-units of our
single-ward chains.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _normalize import normalize_for_match, bridge_normalize  # noqa: E402
from _fix_mojibake import fix_mojibake  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "residents_1881_output"
QUARANTINE = OUT_DIR / "quarantine" / "unmatched_chain.parquet"
TCPUID_TO_PLACE = REPO / "persistent_places_output" / "tcpuid_year_to_place.csv"
REGISTRY = REPO / "persistent_places_output" / "persistent_place_registry.csv"

TCPUID_RE = re.compile(r"^([A-Z]{2})(\d{3})(\d{3})$")
SUFFIX_PARENS_RE = re.compile(r"\s*\([^)]+\)\s*$")


def parse_tcpuid(t: str) -> tuple[str, str, str] | None:
    m = TCPUID_RE.match(t or "")
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


def strip_borealis_suffix(name: str) -> str:
    """Strip Borealis sub-area suffixes like '(Sud/South)', '(Town/Ville)',
    '(Quartier/Ward)' that aren't in our registry's canonical_names."""
    if not name:
        return ""
    s = fix_mojibake(name)
    # Remove parenthetical bilingual qualifiers ((Sud/South), (Town/Ville)).
    while True:
        new = SUFFIX_PARENS_RE.sub("", s).strip()
        if new == s:
            break
        s = new
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    args = ap.parse_args()

    # Load 1881 chains from the per-year mapping.
    # chains_by_distno: {(prov, distno): [(tcpuid, chain_id), ...]}
    chains_by_distno: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    with TCPUID_TO_PLACE.open() as f:
        rd = csv.DictReader(f)
        for row in rd:
            if row["year"] != "1881":
                continue
            parsed = parse_tcpuid(row["tcpuid"])
            if not parsed:
                continue
            prov, distno, _ = parsed
            chains_by_distno[(prov, distno)].append(
                (row["tcpuid"], row["persistent_place_id"]))

    # Load chain canonical names.
    chain_name: dict[str, str] = {}
    with REGISTRY.open() as f:
        rd = csv.DictReader(f)
        for row in rd:
            chain_name[row["persistent_place_id"]] = row["canonical_name"]

    # Build unmatched-TCPUID summary from quarantine parquet.
    print(f"[rescue] reading {QUARANTINE} …", file=sys.stderr)
    cols = ["TCPUID_CSD_1881", "province", "distnam", "distno",
            "sdistnam", "sdistlet"]
    df = pq.read_table(QUARANTINE, columns=cols).to_pandas()
    # Distinct (tcpuid, sdistnam) tuples — many of the 136K rows share these.
    distinct = df.drop_duplicates(subset=["TCPUID_CSD_1881", "sdistnam"]).copy()
    print(f"[rescue] {len(df):,} quarantined rows → "
          f"{distinct['TCPUID_CSD_1881'].nunique()} distinct TCPUIDs, "
          f"{len(distinct)} (TCPUID, sdistnam) combos",
          file=sys.stderr)

    # Per-row matching.
    rescue_rows = []
    review_rows = []
    for _, r in distinct.iterrows():
        bor_tcpuid = r["TCPUID_CSD_1881"]
        bor_sdistnam = strip_borealis_suffix(r["sdistnam"] or "")
        parsed = parse_tcpuid(bor_tcpuid)
        if not parsed:
            review_rows.append({
                "borealis_tcpuid": bor_tcpuid,
                "province": r["province"], "distnam": r["distnam"],
                "sdistnam": r["sdistnam"],
                "match_status": "tcpuid_unparseable",
                "candidate_chains": "",
            })
            continue
        prov, distno, _ = parsed
        candidates = chains_by_distno.get((prov, distno), [])
        if not candidates:
            review_rows.append({
                "borealis_tcpuid": bor_tcpuid,
                "province": r["province"], "distnam": r["distnam"],
                "sdistnam": r["sdistnam"],
                "match_status": "no_chain_in_district",
                "candidate_chains": "",
            })
            continue

        # Match by normalized canonical_name vs Borealis sdistnam.
        bor_norm = bridge_normalize(bor_sdistnam)
        # Score each candidate.
        scored = []
        for cand_tcpuid, cand_chain in candidates:
            cand_name = chain_name.get(cand_chain, "")
            cand_norm = bridge_normalize(cand_name)
            if not cand_norm or not bor_norm:
                continue
            score = 0.0
            # Exact normalized match → score 1.0
            if cand_norm == bor_norm:
                score = 1.0
            # Substring match either direction → score 0.7
            elif bor_norm in cand_norm or cand_norm in bor_norm:
                score = 0.7
            # Word-set overlap → score = jaccard
            else:
                bw = set(bor_norm.split())
                cw = set(cand_norm.split())
                if bw and cw:
                    j = len(bw & cw) / len(bw | cw)
                    if j >= 0.5:
                        score = 0.5 * j
            if score > 0:
                scored.append((score, cand_chain, cand_name, cand_tcpuid))

        scored.sort(reverse=True)
        if not scored:
            review_rows.append({
                "borealis_tcpuid": bor_tcpuid,
                "province": r["province"], "distnam": r["distnam"],
                "sdistnam": r["sdistnam"],
                "match_status": "no_name_match",
                "candidate_chains": "; ".join(
                    f"{c}[{n}]" for _, c, n, _ in []
                ) or "; ".join(
                    f"{cc}[{chain_name.get(cc,'')}]"
                    for _, cc in candidates[:5]
                ),
            })
            continue

        top_score, top_chain, top_name, top_cand_tcpuid = scored[0]
        if top_score >= 0.95:
            rescue_rows.append({
                "borealis_tcpuid": bor_tcpuid,
                "province": r["province"], "distnam": r["distnam"],
                "sdistnam": r["sdistnam"],
                "matched_chain": top_chain,
                "matched_chain_canonical": top_name,
                "match_score": f"{top_score:.2f}",
                "match_method": "exact_normalized",
            })
        elif top_score >= 0.7 and (len(scored) == 1 or scored[1][0] < top_score - 0.1):
            # Unambiguous high-confidence partial.
            rescue_rows.append({
                "borealis_tcpuid": bor_tcpuid,
                "province": r["province"], "distnam": r["distnam"],
                "sdistnam": r["sdistnam"],
                "matched_chain": top_chain,
                "matched_chain_canonical": top_name,
                "match_score": f"{top_score:.2f}",
                "match_method": "substring_unambiguous",
            })
        else:
            review_rows.append({
                "borealis_tcpuid": bor_tcpuid,
                "province": r["province"], "distnam": r["distnam"],
                "sdistnam": r["sdistnam"],
                "match_status": "ambiguous",
                "candidate_chains": "; ".join(
                    f"{c}[{n}]({s:.2f})" for s, c, n, _ in scored[:5]
                ),
            })

    # Compute rescue coverage in row-count terms.
    rescue_tcpuids = {r["borealis_tcpuid"] for r in rescue_rows}
    rescued_rows = int(df[df["TCPUID_CSD_1881"].isin(rescue_tcpuids)].shape[0])
    review_rows_count = int(df[~df["TCPUID_CSD_1881"].isin(rescue_tcpuids)].shape[0])
    print(f"[rescue] {len(rescue_rows)} TCPUIDs auto-rescued "
          f"({rescued_rows:,} of {len(df):,} quarantined rows = "
          f"{100*rescued_rows/max(1,len(df)):.1f}%)", file=sys.stderr)
    print(f"[rescue] {len(review_rows)} TCPUIDs flagged for manual review",
          file=sys.stderr)

    # Write outputs.
    rescue_path = OUT_DIR / "unmatched_tcpuid_rescue.csv"
    if rescue_rows:
        # Dedup on borealis_tcpuid (one entry per TCPUID — sdistnam may have
        # variants like "St-Roch (Sud/South)" vs "St-Roch (Sud)" but the
        # mapping is the same).
        seen = set()
        with rescue_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "borealis_tcpuid", "province", "distnam", "sdistnam",
                "matched_chain", "matched_chain_canonical",
                "match_score", "match_method",
            ])
            w.writeheader()
            for row in rescue_rows:
                if row["borealis_tcpuid"] in seen:
                    continue
                seen.add(row["borealis_tcpuid"])
                w.writerow(row)
        print(f"[rescue] wrote {rescue_path} ({len(seen)} unique TCPUIDs)",
              file=sys.stderr)
    else:
        rescue_path.write_text(
            "borealis_tcpuid,province,distnam,sdistnam,matched_chain,"
            "matched_chain_canonical,match_score,match_method\n")

    review_path = OUT_DIR / "unmatched_tcpuid_review.csv"
    if review_rows:
        seen = set()
        with review_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "borealis_tcpuid", "province", "distnam", "sdistnam",
                "match_status", "candidate_chains",
            ])
            w.writeheader()
            for row in review_rows:
                if row["borealis_tcpuid"] in seen:
                    continue
                seen.add(row["borealis_tcpuid"])
                w.writerow(row)
        print(f"[rescue] wrote {review_path} ({len(seen)} TCPUIDs for review)",
              file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
