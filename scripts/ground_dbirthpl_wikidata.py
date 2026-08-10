#!/usr/bin/env python3
"""Stage 5b.2 — Ground 1881 dbirthpl_TCP codes to Wikidata QIDs.

The Borealis deposit codes 215 distinct birthplaces (US states, Canadian
provinces/cities, foreign countries, "Native American", etc.) into the
`dbirthpl_TCP` integer column. To make the residents pages link to clickable
Wikidata-grounded place pages and to emit `crm:P7_took_place_at` triples
with proper authority IRIs, we need a once-and-done crosswalk:

    code (int) -> label -> wikidata_qid

Workflow (two-pass, mirrors scripts/join_wikidata_to_places.py):

  Pass A: emit residents_1881_output/dbirthpl_grounding_queue.jsonl
          One row per distinct code that actually occurs in the residents
          parquet. Includes: code, label, occurrence_count.

  Pass B: consume wikidata_grounding/dbirthpl_qid_matches.jsonl (manually
          curated via WikidataMCP vector search per ~/.claude/CLAUDE.md;
          rate-limited 5 req/sec, do NOT use the REST wbsearchentities API)
          and emit residents_1881_output/dbirthpl_qid_xref.csv.

The MCP-driven match step happens out-of-band — same pattern used for CSD
grounding (`csd_verified_matches.jsonl`). This script prepares the queue,
records what's already been matched, and writes the consumable xref.

Match JSONL row shape (one per line):
  {"code": "27000000", "label": "Ireland", "qid": "Q27",
   "qid_label": "Ireland", "confidence": "high",
   "status": "matched"|"ambiguous"|"no_match"|"skip",
   "notes": "optional human note"}
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterator

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _config import CONFIG  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "residents_1881_output"
PROVINCE_DIR = OUT_DIR / "by_province"
QUEUE_PATH = OUT_DIR / "dbirthpl_grounding_queue.jsonl"
XREF_PATH = OUT_DIR / "dbirthpl_qid_xref.csv"
MATCHES_PATH = REPO / "wikidata_grounding" / "dbirthpl_qid_matches.jsonl"


def load_value_labels() -> dict[str, str]:
    with CONFIG.borealis_1881_value_labels.open() as f:
        all_labels = json.load(f)
    return all_labels.get("dbirthpl_TCP", {})


def count_birthplace_codes() -> Counter:
    """Stream the per-province residents parquets, count occurrences of
    each dbirthpl_TCP code (string). Codes are stored as strings post-prepare."""
    counts: Counter = Counter()
    parquets = sorted(PROVINCE_DIR.glob("*.parquet"))
    if not parquets:
        sys.exit(f"No residents parquets in {PROVINCE_DIR}; run "
                 "scripts/prepare_1881_residents.py first.")
    for p in parquets:
        for batch in pq.ParquetFile(p).iter_batches(
                batch_size=200_000, columns=["dbirthpl_TCP"]):
            for v in batch.column(0).to_pylist():
                if v is None or v == "":
                    continue
                # Strip trailing ".0" if pyarrow rendered it as a float string.
                code = v.removesuffix(".0") if v.endswith(".0") else v
                counts[code] += 1
    return counts


def write_queue(counts: Counter, labels: dict[str, str]) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE_PATH.open("w") as f:
        # Sort by occurrence count descending — most-used codes first so the
        # MCP-driven grounder can prioritize.
        for code, n in counts.most_common():
            row = {
                "code": code,
                "label": labels.get(code, ""),
                "occurrence_count": int(n),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[ground] wrote {len(counts)} codes to {QUEUE_PATH}", file=sys.stderr)


def load_matches() -> dict[str, dict]:
    """Read manually-curated MCP matches if present. Missing file = no
    matches yet (xref will only contain entries for codes we've grounded)."""
    if not MATCHES_PATH.exists():
        return {}
    out: dict[str, dict] = {}
    with MATCHES_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            row = json.loads(line)
            out[str(row["code"])] = row
    return out


def write_xref(counts: Counter, labels: dict[str, str],
               matches: dict[str, dict]) -> None:
    XREF_PATH.parent.mkdir(parents=True, exist_ok=True)
    with XREF_PATH.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "code", "label", "occurrence_count",
            "qid", "qid_label", "confidence", "status", "notes",
        ])
        for code, n in counts.most_common():
            m = matches.get(code, {})
            w.writerow([
                code,
                labels.get(code, ""),
                int(n),
                m.get("qid", ""),
                m.get("qid_label", ""),
                m.get("confidence", ""),
                m.get("status", "ungrounded"),
                m.get("notes", ""),
            ])
    grounded = sum(1 for c in counts if matches.get(c, {}).get("qid"))
    rows_grounded = sum(
        n for c, n in counts.items() if matches.get(c, {}).get("qid")
    )
    rows_total = sum(counts.values())
    pct_codes = grounded / max(1, len(counts)) * 100
    pct_rows = rows_grounded / max(1, rows_total) * 100
    print(f"[ground] xref: {grounded}/{len(counts)} codes grounded "
          f"({pct_codes:.1f}%), covering {rows_grounded:,}/{rows_total:,} "
          f"residents rows ({pct_rows:.1f}%) -> {XREF_PATH}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--queue-only", action="store_true",
        help="Only write the grounding queue; skip xref generation. Use "
             "before the MCP-driven matching pass.")
    args = ap.parse_args()

    labels = load_value_labels()
    print(f"[ground] {len(labels)} dbirthpl_TCP labels in value_labels.json",
          file=sys.stderr)

    counts = count_birthplace_codes()
    print(f"[ground] {len(counts)} distinct codes appear in residents data; "
          f"{sum(counts.values()):,} total non-null rows", file=sys.stderr)

    write_queue(counts, labels)

    if args.queue_only:
        return 0

    matches = load_matches()
    print(f"[ground] {len(matches)} matches loaded from {MATCHES_PATH}",
          file=sys.stderr)
    write_xref(counts, labels, matches)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
