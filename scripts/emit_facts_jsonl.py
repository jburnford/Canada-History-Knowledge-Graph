#!/usr/bin/env python3
"""Emit facts.jsonl + vocab/variables.jsonl from the Ladybug pilot DB.

Two artifacts for programmatic consumers (RAG pipelines, JSON-LD ingestors,
LOD tooling) sitting alongside the rendered HTML pages:

  rag_site/facts/<year>.jsonl
    One fact per (presence, measurement) tuple. Subject URI matches the
    canonical page URL emitted by generate_rag_pages.py so consumers can
    follow the link to the human-readable page. Split per-year so each
    file stays under GitHub's 100 MB per-file commit limit; a sibling
    rag_site/facts/index.json lists all parts.

  rag_site/vocab/variables.jsonl
    One row per CensusVariable. Full vocabulary index keyed on the same
    URI scheme used by the per-page JSON-LD additionalProperty entries.

LINCS coverage of the same data is provided by the existing CIDOC-CRM
Turtle export (scripts/export_rdf.py); this script targets the
Schema.org / consumer-facing layer instead.

Usage:
    python3 scripts/emit_facts_jsonl.py
    python3 scripts/emit_facts_jsonl.py --out rag_site --site-url https://...
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Reuse the canonical URL helpers from generate_rag_pages.py so subject
# URIs are guaranteed to match the page slugs.
sys.path.insert(0, str(REPO / "scripts"))
from generate_rag_pages import (  # noqa: E402
    DEFAULT_SITE_URL,
    DEFAULT_BASE_PATH,
    slugify,
    url_for_presence,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(REPO / "pilot/on_kuzu/on.kuzu"))
    ap.add_argument("--out", default=str(REPO / "rag_site"))
    ap.add_argument("--site-url", default=DEFAULT_SITE_URL)
    ap.add_argument("--base-path", default=DEFAULT_BASE_PATH)
    args = ap.parse_args()

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "vocab").mkdir(parents=True, exist_ok=True)

    import ladybug as kuzu
    db = kuzu.Database(args.db)
    conn = kuzu.Connection(db)

    # ----- Vocabulary -----
    # One JSONL row per CensusVariable, full enrichment.
    print("[vocab] reading CensusVariable...", flush=True)
    vocab_path = out_root / "vocab" / "variables.jsonl"
    res = conn.execute(
        "MATCH (v:CensusVariable) "
        "RETURN v.var_code, v.label, v.category, v.unit, v.source_tables, "
        "v.year_count, v.comparable_across_years, v.presence_count, v.quality;"
    )
    n_vocab = 0
    with vocab_path.open("w") as f:
        while res.has_next():
            r = res.get_next()
            (var_code, label, category, unit, source_tables,
             year_count, comparable, presence_count, quality) = r
            bare = (var_code or "").removeprefix("VAR_")
            entry = {
                "id": f"{args.site_url}{args.base_path}/vocab/var/{bare}",
                "var_code": var_code,
                "label": label,
                "category": category,
                "unit": unit,
                "year_count": year_count,
                "comparable_across_years": bool(comparable),
                "presence_count": presence_count,
                "quality": quality,
            }
            if source_tables:
                # Parse "1851:V2T6,1861:V2T11,..." into {year: table}
                src_map = {}
                for piece in source_tables.split(","):
                    y, _, t = piece.partition(":")
                    if y.strip().isdigit() and t.strip():
                        src_map[int(y.strip())] = t.strip()
                if src_map:
                    entry["sources"] = src_map
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            n_vocab += 1
    print(f"[vocab] wrote {n_vocab} rows -> {vocab_path}", flush=True)

    # ----- Facts -----
    # One JSONL row per (presence, measurement), split per-year so each part
    # stays under GitHub's 100 MB single-file commit limit. Single streaming
    # query plus per-year output handles to keep memory flat.
    print("[facts] streaming measurements...", flush=True)
    facts_dir = out_root / "facts"
    facts_dir.mkdir(parents=True, exist_ok=True)
    # Clear any stale year-files from a previous run.
    for old in facts_dir.glob("*.jsonl"):
        old.unlink()

    handles: dict = {}
    counts: dict = {}

    def _open_year(year: int):
        if year not in handles:
            p = facts_dir / f"{year}.jsonl"
            handles[year] = p.open("w")
            counts[year] = 0
        return handles[year]

    res = conn.execute(
        "MATCH (pr:Presence)-[:OBSERVED_IN]->(p:Place) "
        "MATCH (pr)-[:MEASURED_AT]->(m:Measurement)-[:OF_VARIABLE]->(v:CensusVariable) "
        "RETURN p.name, p.province, pr.tcpuid, pr.year, "
        "v.var_code, v.label, v.category, v.unit, v.source_tables, "
        "v.comparable_across_years, v.quality, "
        "m.value_float, m.value_string;"
    )
    n_facts = 0
    while res.has_next():
        r = res.get_next()
        (place_name, province, tcpuid, year, var_code, label, category,
         unit, src_tables, comparable, quality, fval, sval) = r

        # Subject URI matches generate_rag_pages.py's page slug.
        subj = f"{args.site_url}{url_for_presence(place_name or '', tcpuid or '', year, args.base_path, province or 'on')}"

        # Numeric value when present, else string.
        value = sval if (sval is not None and sval != "") else fval
        if isinstance(value, float) and value == int(value):
            value = int(value)
        if value is None:
            continue

        bare = (var_code or "").removeprefix("VAR_")

        # Source for this (var, year) — parse the per-year provenance map.
        source_for_year = None
        if src_tables:
            for piece in src_tables.split(","):
                y, _, t = piece.partition(":")
                if y.strip() == str(year):
                    source_for_year = f"{year}_{t.strip()}"
                    break

        entry = {
            "subject": subj,
            "var": var_code,
            "var_uri": f"{args.site_url}{args.base_path}/vocab/var/{bare}",
            "label": label,
            "category": category,
            "unit": unit,
            "value": value,
            "year": year,
            "tcpuid": tcpuid,
            "province": province,
            "quality": quality,
            "comparable": bool(comparable),
        }
        if source_for_year:
            entry["source"] = source_for_year

        f = _open_year(year)
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        counts[year] += 1
        n_facts += 1
        if n_facts % 100000 == 0:
            print(f"[facts]   {n_facts} rows...", flush=True)

    for f in handles.values():
        f.close()

    # ----- Index -----
    index = {
        "files": [],
        "total_facts": n_facts,
        "vocab": f"{args.base_path}/vocab/variables.jsonl",
    }
    for year in sorted(counts):
        size = (facts_dir / f"{year}.jsonl").stat().st_size
        index["files"].append({
            "year": year,
            "path": f"{args.base_path}/facts/{year}.jsonl",
            "facts": counts[year],
            "size_bytes": size,
        })
    (facts_dir / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n"
    )

    print(f"[facts] wrote {n_facts} rows across {len(counts)} year-files -> {facts_dir}/")
    for year in sorted(counts):
        size_mb = (facts_dir / f"{year}.jsonl").stat().st_size / 1e6
        print(f"[facts]   {year}: {counts[year]:>7,} rows  {size_mb:>5.1f} MB")


if __name__ == "__main__":
    main()
