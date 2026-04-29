"""Union Strategy 1 (Wikidata) + Strategy 3 (PIP) link rows into a single table.

Dedup key: (person_id, place_id, event_type). When both strategies fire on the same
key, keep one row with strategy='wd+pip' and confidence='high' (both agreed).

Output:
  data/lincs_person_csd_links.csv  — final canonical link table
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
S1 = REPO / "data" / "lincs_strategy1_links.csv"
S3 = REPO / "data" / "lincs_strategy3_links.csv"
REGISTRY = REPO / "persistent_places_output" / "persistent_place_registry.csv"
OUT = REPO / "data" / "lincs_person_csd_links.csv"

# Drop matches that resolved to a placeholder polygon (e.g., PLACE_NT999999) — these
# are GDB stubs for unsurveyed/Indigenous territory rather than real CSDs.
PLACEHOLDER_MARKER = "999999"


def load_registry_names() -> dict[str, str]:
    """persistent_place_id → canonical_name (province-stripped)."""
    out = {}
    with open(REGISTRY) as fh:
        r = csv.DictReader(fh)
        for row in r:
            out[row["persistent_place_id"]] = row.get("canonical_name", "")
    return out

OUT_COLUMNS = [
    "person_id", "person_name", "person_qid", "dcb_url",
    "event_type", "event_year", "census_year",
    "place_id", "place_label",
    "geonames_id", "geonames_name",
    "match_strategy", "confidence",
]


def load_strategy1() -> list[dict]:
    rows = []
    with open(S1) as fh:
        r = csv.DictReader(fh)
        for row in r:
            rows.append({
                "person_id": row["person_id"],
                "person_name": row["person_name"],
                "person_qid": row["person_qid"],
                "dcb_url": row["dcb_url"],
                "event_type": row["event_type"],
                "event_year": row["event_year"],
                "census_year": "",  # WD strategy doesn't carry a census_year directly
                "place_id": row["place_id"],
                "place_label": row["place_label"],
                "geonames_id": "",
                "geonames_name": "",
                "match_strategy": "wd",
                "confidence": "high",
            })
    return rows


def load_strategy3() -> list[dict]:
    rows = []
    with open(S3) as fh:
        r = csv.DictReader(fh)
        for row in r:
            rows.append({
                "person_id": row["person_id"],
                "person_name": row["person_name"],
                "person_qid": row.get("person_qid", ""),
                "dcb_url": row["dcb_url"],
                "event_type": row["event_type"],
                "event_year": row["event_year"],
                "census_year": row["census_year"],
                "place_id": row["place_id"],
                "place_label": row.get("csd_name", ""),
                "geonames_id": row.get("geonames_id", ""),
                "geonames_name": row.get("geonames_name", ""),
                "match_strategy": "pip",
                "confidence": "high",
            })
    return rows


def main() -> int:
    s1 = load_strategy1()
    s3 = load_strategy3()
    registry = load_registry_names()
    print(f"Strategy 1 rows: {len(s1)}", file=sys.stderr)
    print(f"Strategy 3 rows: {len(s3)}", file=sys.stderr)
    print(f"Registry entries: {len(registry):,}", file=sys.stderr)

    n_placeholder_dropped = 0
    n_unnamed_dropped = 0
    bucket: dict[tuple, dict] = {}
    for row in s1 + s3:
        # Filter out placeholder polygon matches (PLACE_NT999999 etc.).
        if PLACEHOLDER_MARKER in row["place_id"]:
            n_placeholder_dropped += 1
            continue
        # Enrich place_label from registry canonical_name when the GDB-sourced label
        # is missing or the placeholder "NO DATA".
        canonical = registry.get(row["place_id"], "")
        cur_label = row.get("place_label", "")
        if canonical and (not cur_label or cur_label == "NO DATA"):
            row["place_label"] = canonical
        # Drop PIP rows whose final place_label is still "NO DATA" — these come from
        # coarse-grained GeoNames sources (province/country centroids) landing on
        # unsurveyed territorial polygons. Strategy 1 catches the real CSD when the
        # cohort person has a Wikidata QID at sub-province grain.
        if row["match_strategy"] == "pip" and \
                (row["place_label"] == "NO DATA" or not row["place_label"]):
            n_unnamed_dropped += 1
            continue
        key = (row["person_id"], row["place_id"], row["event_type"])
        existing = bucket.get(key)
        if existing is None:
            bucket[key] = row
        else:
            # Both strategies fired → mark as agreed.
            existing["match_strategy"] = "wd+pip"
            # Keep PIP's census_year and geonames_id if Strategy 1 was the survivor.
            for k in ("census_year", "geonames_id", "geonames_name"):
                if not existing.get(k) and row.get(k):
                    existing[k] = row[k]
            # Prefer richer place_label.
            if row.get("place_label") and not existing.get("place_label"):
                existing["place_label"] = row["place_label"]

    rows_out = list(bucket.values())
    rows_out.sort(key=lambda r: (r["person_id"], r["event_type"], r["place_id"]))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_COLUMNS)
        w.writeheader()
        for row in rows_out:
            w.writerow({k: row.get(k, "") for k in OUT_COLUMNS})

    # Summary
    by_strategy = defaultdict(int)
    persons = set()
    places = set()
    for row in rows_out:
        by_strategy[row["match_strategy"]] += 1
        persons.add(row["person_id"])
        places.add(row["place_id"])
    print(f"\nFinal output: {OUT}", file=sys.stderr)
    print(f"  placeholder rows dropped:   {n_placeholder_dropped:,}", file=sys.stderr)
    print(f"  unnamed-CSD pip rows dropped: {n_unnamed_dropped:,}", file=sys.stderr)
    print(f"  total rows:                 {len(rows_out):,}", file=sys.stderr)
    print(f"  distinct persons:       {len(persons):,}", file=sys.stderr)
    print(f"  distinct places (CSDs): {len(places):,}", file=sys.stderr)
    print(f"  by strategy:", file=sys.stderr)
    for s, n in sorted(by_strategy.items(), key=lambda kv: -kv[1]):
        print(f"    {s:8}: {n:,}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
