#!/usr/bin/env python3
"""Emit neo4j_cidoc_crm_v2/e53_qid_xref.csv — the cross-reference of E53 chains
that share a Wikidata QID.

The renderer (scripts/generate_rag_pages.py) joins this onto each per-chain
page to render a "Same Wikidata entity, other presences" section. This is the
mechanism that links e.g. NT 1901 Calgary Centre / AB 1911 Calgary c via Q36312
without merging the chains (chain IDs and URLs stay stable).

Inputs:
  neo4j_cidoc_crm_v2/e53_place_uri.csv  (place_id, wikidata_qid, ...)
  neo4j_cidoc_crm_v2/e53_place_csd.csv  (place_id, name, province, years_active)
  neo4j_cidoc_crm_v2/e53_place_cd.csv   (place_id, name, province, years_active)

Output:
  neo4j_cidoc_crm_v2/e53_qid_xref.csv
    columns: wikidata_qid, wikidata_label, place_id, place_type, name, province,
             year_min, year_max, num_years, num_chains_for_qid

Filter: only QIDs that map to ≥2 chains (singletons need no cross-link).
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
URI_CSV = REPO / "neo4j_cidoc_crm_v2" / "e53_place_uri.csv"
CSD_CSV = REPO / "neo4j_cidoc_crm_v2" / "e53_place_csd.csv"
CD_CSV = REPO / "neo4j_cidoc_crm_v2" / "e53_place_cd.csv"
OUT = REPO / "neo4j_cidoc_crm_v2" / "e53_qid_xref.csv"


def load_place_attrs() -> dict[str, dict]:
    """place_id → {name, province, place_type, years_active}."""
    attrs: dict[str, dict] = {}
    for path, kind in [(CSD_CSV, "CSD"), (CD_CSV, "CD")]:
        if not path.exists():
            continue
        with path.open() as f:
            for row in csv.DictReader(f):
                pid = row["place_id:ID"]
                years_str = row.get("years_active") or ""
                years = [int(y) for y in years_str.split(";") if y.strip().isdigit()]
                attrs[pid] = {
                    "name": row.get("name", ""),
                    "province": row.get("province", ""),
                    "place_type": row.get("place_type") or kind,
                    "year_min": min(years) if years else None,
                    "year_max": max(years) if years else None,
                    "num_years": len(years),
                }
    return attrs


def main() -> None:
    attrs = load_place_attrs()
    print(f"Loaded {len(attrs):,} E53 places (CSD + CD)")

    # Group chains by QID
    qid_to_rows: dict[str, list[dict]] = defaultdict(list)
    qid_label: dict[str, str] = {}
    n_grounded = 0
    with URI_CSV.open() as f:
        for row in csv.DictReader(f):
            qid = (row.get("wikidata_qid") or "").strip()
            if not qid:
                continue
            n_grounded += 1
            pid = row["place_id:ID"]
            attr = attrs.get(pid)
            if not attr:
                # CSD/CD CSV missing this place; skip (warning printed)
                continue
            qid_to_rows[qid].append({
                "wikidata_qid": qid,
                "wikidata_label": (row.get("wikidata_label") or "").strip(),
                "place_id": pid,
                "place_type": attr["place_type"],
                "name": attr["name"],
                "province": attr["province"],
                "year_min": attr["year_min"] or "",
                "year_max": attr["year_max"] or "",
                "num_years": attr["num_years"],
            })
            label = (row.get("wikidata_label") or "").strip()
            if label and qid not in qid_label:
                qid_label[qid] = label

    print(f"Grounded chains (with QID): {n_grounded:,}")
    print(f"Unique QIDs across grounded chains: {len(qid_to_rows):,}")

    # Filter to QIDs with ≥2 chains
    multi_qids = {q: rows for q, rows in qid_to_rows.items() if len(rows) >= 2}
    print(f"QIDs with ≥2 chains (cross-link candidates): {len(multi_qids):,}")
    total_xref_rows = sum(len(rows) for rows in multi_qids.values())
    print(f"Cross-link rows to emit: {total_xref_rows:,}")

    # Stats: chain-count distribution
    size_hist = Counter(len(rows) for rows in multi_qids.values())
    print("\nQID → chain-count distribution:")
    for size in sorted(size_hist):
        print(f"  {size} chains: {size_hist[size]:,} QIDs")

    # Province-pair stats (e.g., NT/AB cross-links — the headline win)
    cross_prov = Counter()
    for rows in multi_qids.values():
        provs = sorted({r["province"] for r in rows if r["province"]})
        if len(provs) > 1:
            cross_prov[tuple(provs)] += 1
    if cross_prov:
        print("\nCross-province QID groupings:")
        for provs, n in cross_prov.most_common():
            print(f"  {'/'.join(provs):10s} {n:,} QIDs")

    # Write output
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "wikidata_qid", "wikidata_label", "place_id", "place_type",
            "name", "province", "year_min", "year_max", "num_years",
            "num_chains_for_qid",
        ])
        writer.writeheader()
        # Sort: by QID, then by year_min, then place_id
        for qid in sorted(multi_qids):
            rows = multi_qids[qid]
            rows.sort(key=lambda r: (r["year_min"] or 9999, r["place_id"]))
            n = len(rows)
            for r in rows:
                writer.writerow({**r, "num_chains_for_qid": n})

    print(f"\nWrote {total_xref_rows:,} rows -> {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
