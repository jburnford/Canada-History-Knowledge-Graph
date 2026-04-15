#!/usr/bin/env python3
"""Join verified Wikidata matches onto E53_Place nodes as a URI sidecar.

Produces neo4j_cidoc_crm_v2/e53_place_uri.csv — one row per E53_Place with the
URI the RDF exporter should use as the subject. LINCS policy (per Susan, LINCS
team): use existing authority URIs where possible, temporary URIs under
http://temp.lincsproject.ca/ otherwise. Permanent minting happens at publication
time, not here.

URI assignment:
  - status=matched  -> http://www.wikidata.org/entity/{QID}
  - status=mint_uri -> http://temp.lincsproject.ca/census/place/{tcpuid}
  - status=skip     -> http://temp.lincsproject.ca/census/place/{tcpuid}
  - ungrounded      -> http://temp.lincsproject.ca/census/place/{tcpuid}

The Neo4j :ID column stays as PLACE_{tcpuid}; this sidecar only supplies the
URI property so the RDF exporter can emit the right subject. No existing CSVs
are rewritten.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
JSONL = REPO / "wikidata_grounding" / "csd_verified_matches.jsonl"
E53_CSD = REPO / "neo4j_cidoc_crm_v2" / "e53_place_csd.csv"
OUT = REPO / "neo4j_cidoc_crm_v2" / "e53_place_uri.csv"
UNPLACED = REPO / "neo4j_cidoc_crm_v2" / "e53_place_uri_unplaced.csv"

WIKIDATA_PREFIX = "http://www.wikidata.org/entity/"
TEMP_PREFIX = "http://temp.lincsproject.ca/census/place/"
GROUNDING_YEAR = "1921"  # JSONL grounding was done against the 1921 CSD snapshot
SUFFIX_RE = re.compile(r"_(\d{4})$")


def load_grounding(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            out[r["csd_id"]] = r
    return out


def uri_for(tcpuid: str, record: dict | None) -> tuple[str, str, str]:
    """Return (uri, uri_source, wikidata_qid_or_empty)."""
    if record and record.get("status") == "matched":
        qid = record["wikidata_qid"]
        return f"{WIKIDATA_PREFIX}{qid}", "wikidata", qid
    return f"{TEMP_PREFIX}{tcpuid}", "temp_lincs", ""


def base_tcpuid(tcpuid: str) -> str:
    """Strip a trailing _YYYY disambiguation suffix."""
    return SUFFIX_RE.sub("", tcpuid)


def main() -> None:
    grounding = load_grounding(JSONL)
    print(f"Loaded {len(grounding):,} verified records from {JSONL.name}")

    # Grounding keys refer to the 1921 snapshot. The CSV uses place_id
    # PLACE_{tcpuid} sometimes with a _YYYY disambiguation suffix. For each
    # grounding key, pick the CSV row whose base tcpuid matches AND whose
    # years_active includes 1921.
    status_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()
    province_source: dict[str, Counter[str]] = {}
    grounding_used: set[str] = set()

    rows_out = []
    with E53_CSD.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            place_id = row["place_id:ID"]
            assert place_id.startswith("PLACE_"), place_id
            tcpuid = place_id[len("PLACE_"):]
            base = base_tcpuid(tcpuid)
            province = row["province"]
            years = row["years_active"].split(";") if row["years_active"] else []

            # Only consume grounding when this CSV row is the 1921-active one.
            record = None
            if GROUNDING_YEAR in years and base in grounding:
                record = grounding[base]
                grounding_used.add(base)

            uri, source, qid = uri_for(base, record)
            status = record["status"] if record else "ungrounded"
            mint_reason = (record or {}).get("mint_reason", "") if record else ""
            wd_label = (record or {}).get("wikidata_label", "") if record else ""

            rows_out.append(
                {
                    "place_id:ID": place_id,
                    "uri": uri,
                    "uri_source": source,
                    "wikidata_qid": qid,
                    "wikidata_label": wd_label,
                    "grounding_status": status,
                    "mint_reason": mint_reason,
                }
            )
            status_counter[status] += 1
            source_counter[source] += 1
            province_source.setdefault(province, Counter())[source] += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "place_id:ID",
                "uri",
                "uri_source",
                "wikidata_qid",
                "wikidata_label",
                "grounding_status",
                "mint_reason",
            ],
        )
        writer.writeheader()
        writer.writerows(rows_out)

    total = len(rows_out)
    print(f"\nWrote {total:,} rows -> {OUT.relative_to(REPO)}")

    unused = set(grounding) - grounding_used
    if unused:
        print(
            f"\nWARNING: {len(unused)} grounding records could not be placed "
            f"(no 1921-active CSV row for base tcpuid). Written to "
            f"{UNPLACED.relative_to(REPO)}"
        )
        with UNPLACED.open("w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["csd_id", "status", "csd_name", "wikidata_qid", "wikidata_label"],
            )
            writer.writeheader()
            for cid in sorted(unused):
                rec = grounding[cid]
                writer.writerow(
                    {
                        "csd_id": cid,
                        "status": rec["status"],
                        "csd_name": rec.get("csd_name", ""),
                        "wikidata_qid": rec.get("wikidata_qid", ""),
                        "wikidata_label": rec.get("wikidata_label", ""),
                    }
                )

    print("\nGrounding status:")
    for status, n in sorted(status_counter.items(), key=lambda x: -x[1]):
        print(f"  {status:12s} {n:6,}  ({n / total:5.1%})")
    print("\nURI source:")
    for source, n in sorted(source_counter.items(), key=lambda x: -x[1]):
        print(f"  {source:12s} {n:6,}  ({n / total:5.1%})")
    print("\nPer-province URI source (wikidata / temp_lincs):")
    for prov in sorted(province_source):
        c = province_source[prov]
        wd = c.get("wikidata", 0)
        tmp = c.get("temp_lincs", 0)
        tot = wd + tmp
        pct = wd / tot if tot else 0.0
        print(f"  {prov:3s}  wikidata={wd:5,}  temp={tmp:5,}  total={tot:5,}  ({pct:5.1%} grounded)")


if __name__ == "__main__":
    main()
