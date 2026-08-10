#!/usr/bin/env python3
"""Stage 5b.3 — Aggregate 1881 residents to per-CSD demographic summaries.

Reads:  residents_1881_output/by_province/*.parquet
Writes: residents_1881_output/csd_1881_summary.parquet
        residents_1881_output/csd_1881_summary.csv (human-readable)

Per persistent_place_id we compute:
  - total_residents
  - sex_male, sex_female, sex_other (best-effort from raw `sex`)
  - age buckets: 0-4, 5-9, 10-14, 15-19, 20-24, 25-34, 35-44,
                 45-54, 55-64, 65-74, 75+, unknown
  - top-N religion / origin / occupation labels with row counts
  - top-N birthplace labels (using dbirthpl_TCP_label)

The output drives both the demographic summary panel on the residents
overview page AND can be plumbed into the existing E93_Presence node
properties downstream (out of scope here).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import pandas as pd
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "residents_1881_output"
PROVINCE_DIR = OUT_DIR / "by_province"

AGE_BUCKETS = [
    (0, 4, "0-4"),
    (5, 9, "5-9"),
    (10, 14, "10-14"),
    (15, 19, "15-19"),
    (20, 24, "20-24"),
    (25, 34, "25-34"),
    (35, 44, "35-44"),
    (45, 54, "45-54"),
    (55, 64, "55-64"),
    (65, 74, "65-74"),
    (75, 200, "75+"),
]
TOP_N_RELIGION = 10
TOP_N_ORIGIN = 10
TOP_N_OCCUPATION = 20
TOP_N_BIRTHPLACE = 10


def age_bucket(age: object) -> str:
    if age is None or pd.isna(age):
        return "unknown"
    try:
        a = int(age)
    except (TypeError, ValueError):
        return "unknown"
    for lo, hi, label in AGE_BUCKETS:
        if lo <= a <= hi:
            return label
    return "unknown"


def normalise_sex(s: object) -> str:
    """Borealis CSV uses 'Male' / 'Female' / blank. Normalise to a small set."""
    if s is None or pd.isna(s):
        return "unknown"
    v = str(s).strip().lower()
    if v in ("m", "male"):
        return "male"
    if v in ("f", "female"):
        return "female"
    if not v:
        return "unknown"
    return "other"


def aggregate_one_parquet(path: Path,
                          per_csd: dict[str, dict]) -> None:
    """Stream a single per-province parquet, accumulate per-place stats into
    the shared per_csd dict. Reading column subsets keeps memory bounded."""
    cols = [
        "persistent_place_id",
        "sex", "age",
        "drelign_TCP_label", "dorigin_TCP_label",
        "doccup_TCP_label", "dbirthpl_TCP_label",
    ]
    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(batch_size=200_000, columns=cols):
        df = batch.to_pandas()
        for pid, grp in df.groupby("persistent_place_id", sort=False):
            slot = per_csd.setdefault(pid, {
                "total": 0,
                "sex": Counter(),
                "age_bucket": Counter(),
                "religion": Counter(),
                "origin": Counter(),
                "occupation": Counter(),
                "birthplace": Counter(),
            })
            slot["total"] += len(grp)
            slot["sex"].update(grp["sex"].map(normalise_sex))
            slot["age_bucket"].update(grp["age"].map(age_bucket))
            # Religion / origin / occupation: skip empty labels (rows where
            # the _TCP code didn't decode to anything).
            for col, key in (
                ("drelign_TCP_label", "religion"),
                ("dorigin_TCP_label", "origin"),
                ("doccup_TCP_label", "occupation"),
                ("dbirthpl_TCP_label", "birthplace"),
            ):
                vals = grp[col].dropna()
                vals = vals[vals != ""]
                slot[key].update(vals)


def per_csd_to_rows(per_csd: dict[str, dict]) -> list[dict]:
    """Flatten the in-memory aggregate into a list of records suitable for
    parquet/CSV output."""
    rows = []
    for pid, slot in per_csd.items():
        sex = slot["sex"]
        ages = slot["age_bucket"]
        rec = {
            "persistent_place_id": pid,
            "total_residents": slot["total"],
            "sex_male": int(sex.get("male", 0)),
            "sex_female": int(sex.get("female", 0)),
            "sex_other": int(sex.get("other", 0)),
            "sex_unknown": int(sex.get("unknown", 0)),
        }
        for _, _, lbl in AGE_BUCKETS:
            rec[f"age_{lbl}"] = int(ages.get(lbl, 0))
        rec["age_unknown"] = int(ages.get("unknown", 0))

        # Top-N as JSON-serialisable list of [label, count].
        rec["top_religion"] = json.dumps(slot["religion"].most_common(TOP_N_RELIGION))
        rec["top_origin"] = json.dumps(slot["origin"].most_common(TOP_N_ORIGIN))
        rec["top_occupation"] = json.dumps(slot["occupation"].most_common(TOP_N_OCCUPATION))
        rec["top_birthplace"] = json.dumps(slot["birthplace"].most_common(TOP_N_BIRTHPLACE))
        rows.append(rec)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    province_paths = sorted(PROVINCE_DIR.glob("*.parquet"))
    if not province_paths:
        sys.exit(f"No per-province parquets in {PROVINCE_DIR}; run prepare first.")

    per_csd: dict[str, dict] = {}
    for p in province_paths:
        print(f"[aggregate] reading {p.name} …", file=sys.stderr)
        aggregate_one_parquet(p, per_csd)
    print(f"[aggregate] aggregated {len(per_csd):,} CSDs", file=sys.stderr)

    rows = per_csd_to_rows(per_csd)
    df = pd.DataFrame(rows)
    df = df.sort_values("total_residents", ascending=False).reset_index(drop=True)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = args.out_dir / "csd_1881_summary.parquet"
    csv_path = args.out_dir / "csd_1881_summary.csv"
    df.to_parquet(parquet_path, compression="zstd")
    df.to_csv(csv_path, index=False)

    print(f"[aggregate] wrote {parquet_path} ({len(df):,} rows)", file=sys.stderr)
    print(f"[aggregate] top-5 CSDs by population:", file=sys.stderr)
    for _, r in df.head(5).iterrows():
        print(f"  {r['persistent_place_id']:30s} {r['total_residents']:>7,}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
