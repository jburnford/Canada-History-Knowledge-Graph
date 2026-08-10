#!/usr/bin/env python3
"""Stage 5b.1 — Prepare 1881 Borealis residents CSV for the residents pipeline.

Input: TCP/Dillon 1881 Canadian Census individual-level deposit
(doi:10.5683/SP3/FXZEVO), staged at CONFIG.borealis_1881_csv (1.1 GB CSV).
4,277,810 records across 52 columns.

Output:
  residents_1881_output/residents_1881.parquet              kept rows
  residents_1881_output/residents_1881_quarantine.parquet   removed/unmatched
  residents_1881_output/residents_1881_report.json          row counts + audit

Steps:
  1. Stream-read CSV in chunks (pyarrow CSV reader → pandas).
  2. Filter remove_TCP=0 (TCP flagged duplicates / blanks / non-persons).
  3. Decode _TCP coded fields via 1881_value_labels.json.
  4. Join TCPUID_CSD_1881 → persistent_place_id via the chain registry.
  5. Compute pagination buckets:
        bucket_sdistlet      = sdistlet (lowercased a-z, '-' for missing)
        bucket_surname_letter = first ASCII letter of namlast (or '-')
     Identify CSDs whose largest sdistlet > 1000 rows so the renderer
     knows to do surname-letter sub-pagination.
  6. Write kept rows to parquet (one shard per province for downstream
     parallelism and bounded memory).

The pipeline is single-pass: we never load the whole 4.28M-row table into a
single DataFrame; chunks accumulate per-province via incremental ParquetWriter.
"""
from __future__ import annotations

import argparse
import csv
import gc
import json
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterator

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _config import CONFIG  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "residents_1881_output"
TCPUID_TO_PLACE = REPO / "persistent_places_output" / "tcpuid_year_to_place.csv"
REGISTRY = REPO / "persistent_places_output" / "persistent_place_registry.csv"

# Sub-pagination threshold: when a single (persistent_place_id, sdistlet)
# bucket exceeds this, the renderer splits further by surname initial.
PAGINATION_ROW_CAP = 1000

# Columns kept in the residents parquet. See doc/CLAUDE.md for field
# semantics. We keep both the raw text and the _TCP coded values plus
# decoded labels, so downstream consumers can choose precision vs
# readability per query. Drop columns not needed for the residents page or
# the LOD layer (comment, *_2_TCP secondary codes, *_evaluation_flag_TCP).
KEEP_COLS = [
    # Identity / linkage
    "unique_identifier", "TCPUID_CSD_1881", "serial",
    # Geography
    "province", "distnam", "distno", "divnam", "divno",
    "sdistnam", "sdistlet",
    # Household
    "hhnbr", "pageno", "line",
    # Names
    "namlast", "namfrst",
    # Demographics
    "sex", "age", "agemonth",
    "marst", "marst_TCP",
    # Birthplace, origin, religion, occupation: raw + TCP code
    "dbirthpl", "dbirthpl_TCP",
    "dorigin", "dorigin_TCP",
    "drelign", "drelign_TCP",
    "doccup",  "doccup_TCP",
    # Provenance
    "url", "reel_nac", "folder", "jpg_num",
    # QA
    "remove_TCP", "remove_why_TCP",
]

# Columns we'll decode via value-labels JSON. Decoded label is stored in
# `<col>_label` so consumers can choose code (joinable) or label (display).
DECODE_COLS = [
    "marst_TCP", "dbirthpl_TCP", "dorigin_TCP", "drelign_TCP", "doccup_TCP",
    "remove_TCP", "remove_why_TCP",
]

# 2-letter province code from the registry. The Borealis CSV's `province`
# column is the bilingual long form ("British Columbia/Colombie Britannique");
# we want the 2-letter code that matches our existing URL slug convention.
# Mapping is keyed on the English half of the bilingual string.
PROV_LONG_TO_CODE = {
    "Alberta": "AB",
    "British Columbia": "BC",
    "Manitoba": "MB",
    "New Brunswick": "NB",
    "Newfoundland": "NL",
    "Newfoundland and Labrador": "NL",
    "Northwest Territories": "NT",
    "Nova Scotia": "NS",
    "Ontario": "ON",
    "Prince Edward Island": "PE",
    "Quebec": "QC",
    "Saskatchewan": "SK",
    "Yukon": "YT",
}


def _strip_diacritics(s: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", s)
        if unicodedata.category(ch) != "Mn"
    )


def surname_initial(name: object) -> str:
    """First A-Z letter of the surname after diacritic folding. Returns '-'
    for missing/non-letter — those rows render in the '-' bucket."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return "-"
    s = _strip_diacritics(str(name)).upper()
    for ch in s:
        if "A" <= ch <= "Z":
            return ch
    return "-"


def normalize_sdistlet(v: object) -> str:
    """sdistlet lowercased and stripped; '-' for missing."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    s = str(v).strip().lower()
    return s if s else "-"


def long_province_to_code(v: object) -> str:
    """British Columbia/Colombie Britannique -> BC. Returns '' on miss so
    the join with the registry can drive any leftover assignment."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    eng = str(v).split("/", 1)[0].strip()
    return PROV_LONG_TO_CODE.get(eng, "")


def load_value_labels(path: Path) -> dict[str, dict[str, str]]:
    """Returns {col_name: {code_str: label}}. Codes stay as strings to avoid
    float coercion problems — pandas will read coded columns as floats when
    NA is present, so we coerce to "Int64.astype(str)" before the lookup."""
    with path.open() as f:
        return json.load(f)


def load_chain_map() -> dict[str, str]:
    """{tcpuid -> persistent_place_id} restricted to year=1881.

    After the primary 1881 join, also consume scripts/rescue_unmatched_1881.py's
    output (residents_1881_output/unmatched_tcpuid_rescue.csv) which rescues
    Borealis-CSV TCPUIDs that don't appear in the 1881 layer of our chain
    registry. These are typically city wards (Quebec City, Toronto sub-areas)
    where Borealis enumerates at finer granularity than our registry — the
    rescue routes them to the parent ward chain. Auto-accepted matches only;
    ambiguous ones stay quarantined.
    """
    out: dict[str, str] = {}
    with TCPUID_TO_PLACE.open() as f:
        rd = csv.DictReader(f)
        for row in rd:
            if row["year"] != "1881":
                continue
            out[row["tcpuid"]] = row["persistent_place_id"]
    rescue_path = OUT_DIR / "unmatched_tcpuid_rescue.csv"
    if rescue_path.exists():
        added = 0
        with rescue_path.open() as f:
            rd = csv.DictReader(f)
            for row in rd:
                t = row.get("borealis_tcpuid", "")
                c = row.get("matched_chain", "")
                if t and c and t not in out:
                    out[t] = c
                    added += 1
        if added:
            print(f"[prepare] applied unmatched_tcpuid_rescue.csv "
                  f"(+{added} TCPUIDs)", file=sys.stderr)
    return out


def load_chain_province() -> dict[str, str]:
    """{persistent_place_id -> province (2-letter)} from the registry."""
    out: dict[str, str] = {}
    with REGISTRY.open() as f:
        rd = csv.DictReader(f)
        for row in rd:
            out[row["persistent_place_id"]] = row["province"].upper()
    return out


# ---- Streaming -------------------------------------------------------------

# pyarrow CSV reader: faster than pandas, and we can request only KEEP_COLS.
# Most coded columns may be empty in places where the original lacked the
# value; pyarrow will infer them as int64 with nulls or as string. Force
# everything to string to keep the value-label join simple.
PYARROW_READ_OPTS = pacsv.ReadOptions(block_size=64 << 20)  # 64 MB blocks
PYARROW_PARSE_OPTS = pacsv.ParseOptions(delimiter=",", newlines_in_values=False)


def chunked_csv(path: Path, columns: list[str]) -> Iterator[pd.DataFrame]:
    """Yield 64 MB-block chunks of the CSV restricted to `columns`, all as
    pandas-strings (pyarrow string -> pandas object), no inference."""
    convert_opts = pacsv.ConvertOptions(
        include_columns=columns,
        column_types={c: pa.string() for c in columns},
        strings_can_be_null=True,
        null_values=[""],
    )
    with pacsv.open_csv(
        path,
        read_options=PYARROW_READ_OPTS,
        parse_options=PYARROW_PARSE_OPTS,
        convert_options=convert_opts,
    ) as reader:
        for batch in reader:
            yield batch.to_pandas(types_mapper=None)


def _table_from_pandas_string_safe(df: pd.DataFrame,
                                    int_cols: tuple[str, ...] = (
                                        "age", "agemonth")) -> pa.Table:
    """pa.Table.from_pandas can infer `null` type for all-NA columns, which
    breaks subsequent casts when the next chunk has strings. Force every
    object column to pa.string(); coerce known integer columns to Int32."""
    fields = []
    arrays = []
    for col in df.columns:
        if col in int_cols:
            arr = pa.array(df[col].astype("Int32"), type=pa.int32())
            fields.append(pa.field(col, pa.int32()))
        else:
            # Treat everything else as string. Replace NaN/None with None.
            ser = df[col]
            if ser.dtype.name == "object":
                vals = ser.where(ser.notna(), None)
            else:
                # Numeric/bool — stringify but keep nulls.
                vals = ser.astype(object).where(ser.notna(), None)
                vals = vals.map(lambda v: None if v is None else str(v))
            arr = pa.array(vals, type=pa.string())
            fields.append(pa.field(col, pa.string()))
        arrays.append(arr)
    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


# ---- Decoding --------------------------------------------------------------

def decode_chunk(df: pd.DataFrame, value_labels: dict) -> pd.DataFrame:
    """Add `<col>_label` columns by lookup against value_labels JSON."""
    for col in DECODE_COLS:
        if col not in df.columns:
            continue
        # Codes were read as strings (per ConvertOptions), but pyarrow may
        # render them as "61110" or "61110.0" depending on source — strip
        # any trailing ".0" defensively.
        codes = df[col].fillna("").astype(str)
        codes = codes.str.replace(r"\.0$", "", regex=True)
        labels_map = value_labels.get(col, {})
        df[f"{col}_label"] = codes.map(labels_map).fillna("")
    return df


# ---- Pagination bucket assignment -----------------------------------------

def assign_buckets(df: pd.DataFrame) -> pd.DataFrame:
    """Add bucket_sdistlet, surname_initial, bucket_split_needed columns."""
    df["bucket_sdistlet"] = df["sdistlet"].map(normalize_sdistlet)
    df["surname_initial"] = df["namlast"].map(surname_initial)
    return df


def compute_split_decisions(parquet_paths: list[Path]) -> dict:
    """Read just (persistent_place_id, bucket_sdistlet, surname_initial) from
    each per-province parquet to decide which (place, sdistlet) buckets need
    surname-letter sub-pagination.

    Returns:
      {
        "split_needed": set[(place_id, sdistlet)],   # > PAGINATION_ROW_CAP
        "csd_total":    dict[place_id -> int],
        "leaf_counts":  dict[(place_id, sdistlet, surname_letter) -> int],
      }
    """
    split_needed: set[tuple[str, str]] = set()
    csd_total: Counter = Counter()
    leaf_counts: Counter = Counter()
    sdistlet_counts: Counter = Counter()

    for ppath in parquet_paths:
        cols = ["persistent_place_id", "bucket_sdistlet", "surname_initial"]
        for batch in pq.ParquetFile(ppath).iter_batches(batch_size=200_000, columns=cols):
            df = batch.to_pandas()
            for (pid, sdl), grp in df.groupby(["persistent_place_id", "bucket_sdistlet"], sort=False):
                sdistlet_counts[(pid, sdl)] += len(grp)
                csd_total[pid] += len(grp)
                for letter, sub in grp.groupby("surname_initial", sort=False):
                    leaf_counts[(pid, sdl, letter)] += len(sub)

    for key, n in sdistlet_counts.items():
        if n > PAGINATION_ROW_CAP:
            split_needed.add(key)

    return {
        "split_needed": split_needed,
        "csd_total": dict(csd_total),
        "leaf_counts": dict(leaf_counts),
        "sdistlet_counts": dict(sdistlet_counts),
    }


# ---- Main ------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0,
                    help="Stop after N rows read (dev only; 0 = no limit)")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR,
                    help="Output directory (default: residents_1881_output/)")
    args = ap.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    province_dir = out_dir / "by_province"
    province_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir = out_dir / "quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    print(f"[prepare] reading {CONFIG.borealis_1881_csv}", file=sys.stderr)
    print(f"[prepare] value labels: {CONFIG.borealis_1881_value_labels}",
          file=sys.stderr)

    value_labels = load_value_labels(CONFIG.borealis_1881_value_labels)
    chain_map = load_chain_map()
    chain_prov = load_chain_province()
    print(f"[prepare] loaded {len(chain_map):,} 1881 chain mappings, "
          f"{len(chain_prov):,} chain→province entries", file=sys.stderr)

    # Per-province incremental writers. Keyed by province code; '__' for
    # rows whose chain isn't in the registry (quarantine_unmatched_chain).
    writers: dict[str, pq.ParquetWriter] = {}
    quarantine_writers: dict[str, pq.ParquetWriter] = {}
    schema_cache: pa.Schema | None = None
    quarantine_schema_cache: pa.Schema | None = None

    counters = Counter()
    rows_read = 0

    for chunk in chunked_csv(CONFIG.borealis_1881_csv, KEEP_COLS):
        rows_read += len(chunk)
        counters["read"] += len(chunk)

        # remove_TCP filter: '0' = keep, '1' = remove. Quarantine the rest.
        keep_mask = chunk["remove_TCP"].fillna("").astype(str).str.replace(
            r"\.0$", "", regex=True) == "0"
        kept = chunk[keep_mask].copy()
        removed = chunk[~keep_mask].copy()
        counters["removed_tcp"] += len(removed)

        # Decode TCP codes to labels.
        kept = decode_chunk(kept, value_labels)
        removed = decode_chunk(removed, value_labels)

        # Type coercions: age/agemonth → Int32 nullable.
        for col in ("age", "agemonth"):
            if col in kept.columns:
                kept[col] = pd.to_numeric(kept[col], errors="coerce").astype("Int32")

        # Join chain_id.
        kept["persistent_place_id"] = kept["TCPUID_CSD_1881"].map(chain_map).fillna("")
        unmatched_mask = kept["persistent_place_id"] == ""
        unmatched = kept[unmatched_mask].copy()
        kept = kept[~unmatched_mask].copy()
        counters["unmatched_chain"] += len(unmatched)

        # Province from registry; fall back to long-name parse if missing.
        kept["province_code"] = kept["persistent_place_id"].map(chain_prov)
        missing_prov = kept["province_code"].isna() | (kept["province_code"] == "")
        if missing_prov.any():
            kept.loc[missing_prov, "province_code"] = kept.loc[
                missing_prov, "province"
            ].map(long_province_to_code)
        # If we still don't have a province code, route to '__' (rare).
        kept["province_code"] = kept["province_code"].fillna("__").replace("", "__")

        # Pagination bucket prep.
        kept = assign_buckets(kept)

        # Cast to arrow table and write per-province. _table_from_pandas_string_safe
        # forces a stable schema across chunks so the ParquetWriter never sees
        # an all-null column inferred as pa.null() type.
        for prov_code, sub in kept.groupby("province_code", sort=False):
            tbl = _table_from_pandas_string_safe(sub)
            if schema_cache is None:
                schema_cache = tbl.schema
            elif tbl.schema != schema_cache:
                tbl = tbl.cast(schema_cache, safe=False)
            wpath = province_dir / f"{prov_code}.parquet"
            if prov_code not in writers:
                writers[prov_code] = pq.ParquetWriter(wpath, schema_cache,
                                                     compression="zstd")
            writers[prov_code].write_table(tbl)
            counters[f"kept_{prov_code}"] += len(sub)
            counters["kept_total"] += len(sub)

        # Quarantine: removed_tcp + unmatched_chain. Keep them in case audit
        # needs them, but flag separately.
        if len(removed):
            removed["quarantine_reason"] = "remove_tcp"
            qtbl = _table_from_pandas_string_safe(removed)
            if quarantine_schema_cache is None:
                quarantine_schema_cache = qtbl.schema
            elif qtbl.schema != quarantine_schema_cache:
                qtbl = qtbl.cast(quarantine_schema_cache, safe=False)
            wpath = quarantine_dir / "remove_tcp.parquet"
            if "remove_tcp" not in quarantine_writers:
                quarantine_writers["remove_tcp"] = pq.ParquetWriter(
                    wpath, quarantine_schema_cache, compression="zstd")
            quarantine_writers["remove_tcp"].write_table(qtbl)

        if len(unmatched):
            unmatched["quarantine_reason"] = "unmatched_chain"
            qtbl = _table_from_pandas_string_safe(unmatched)
            wpath = quarantine_dir / "unmatched_chain.parquet"
            if "unmatched_chain" not in quarantine_writers:
                quarantine_writers["unmatched_chain"] = pq.ParquetWriter(
                    wpath, qtbl.schema, compression="zstd")
            else:
                qtbl = qtbl.cast(
                    quarantine_writers["unmatched_chain"].schema, safe=False)
            quarantine_writers["unmatched_chain"].write_table(qtbl)

        if rows_read % 500_000 < len(chunk):  # print every ~500k
            print(f"[prepare] read={rows_read:,} kept={counters['kept_total']:,} "
                  f"removed_tcp={counters['removed_tcp']:,} "
                  f"unmatched={counters['unmatched_chain']:,}",
                  file=sys.stderr)

        if args.limit and rows_read >= args.limit:
            print(f"[prepare] --limit={args.limit:,} reached, stopping",
                  file=sys.stderr)
            break

        del chunk, kept, removed, unmatched
        gc.collect()

    for w in writers.values():
        w.close()
    for w in quarantine_writers.values():
        w.close()

    # Pagination split decisions.
    parquet_paths = sorted(province_dir.glob("*.parquet"))
    print(f"[prepare] computing pagination buckets across {len(parquet_paths)} "
          f"per-province parquets …", file=sys.stderr)
    decisions = compute_split_decisions(parquet_paths)

    # Persist the bucket-decision artefacts so the renderer + cidoc builder
    # can read them without re-scanning the full residents parquet.
    split_rows = [
        {"persistent_place_id": pid, "sdistlet": sdl}
        for (pid, sdl) in sorted(decisions["split_needed"])
    ]
    pd.DataFrame(split_rows).to_csv(
        out_dir / "sdistlet_buckets_split.csv", index=False)

    leaf_rows = [
        {"persistent_place_id": pid, "sdistlet": sdl,
         "surname_initial": ltr, "row_count": n}
        for (pid, sdl, ltr), n in sorted(decisions["leaf_counts"].items())
    ]
    pd.DataFrame(leaf_rows).to_csv(
        out_dir / "leaf_row_counts.csv", index=False)

    csd_total_rows = [
        {"persistent_place_id": pid, "row_count": n}
        for pid, n in sorted(decisions["csd_total"].items())
    ]
    pd.DataFrame(csd_total_rows).to_csv(
        out_dir / "csd_total_counts.csv", index=False)

    # Build report.
    n_chains_with_residents = len(decisions["csd_total"])
    n_split_buckets = len(decisions["split_needed"])
    largest_csd = max(decisions["csd_total"].items(), key=lambda kv: kv[1],
                      default=("", 0))
    report = {
        "rows_read": int(counters["read"]),
        "rows_kept": int(counters["kept_total"]),
        "rows_removed_tcp": int(counters["removed_tcp"]),
        "rows_unmatched_chain": int(counters["unmatched_chain"]),
        "chains_with_residents_1881": n_chains_with_residents,
        "sdistlet_buckets_needing_split": n_split_buckets,
        "largest_csd": {
            "persistent_place_id": largest_csd[0],
            "row_count": int(largest_csd[1]),
        },
        "per_province_kept": {
            k.removeprefix("kept_"): int(v) for k, v in counters.items()
            if k.startswith("kept_") and k != "kept_total"
        },
        "pagination_row_cap": PAGINATION_ROW_CAP,
        "source_csv": str(CONFIG.borealis_1881_csv),
        "value_labels_json": str(CONFIG.borealis_1881_value_labels),
    }
    (out_dir / "residents_1881_report.json").write_text(
        json.dumps(report, indent=2))
    print(f"[prepare] {json.dumps(report, indent=2)}", file=sys.stderr)
    print(f"[prepare] outputs in {out_dir}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
