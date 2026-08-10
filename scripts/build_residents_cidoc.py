#!/usr/bin/env python3
"""Stage 5b.4 — Mint stable URIs for every 1881 resident and assert
within-page fragment uniqueness.

This is the CIDOC build step. Rather than emitting one CSV per CRM class
(which would mean ~30 M rows across 7 classes), we emit a single
**URI manifest** that the renderer consumes to:
  - construct the per-CSD residents pages
  - emit inline schema.org JSON-LD per resident
  - emit per-leaf residents.ttl sidecars (CIDOC-CRM serialisation)
  - feed an optional bulk Turtle export downstream

The manifest is the contract between this stage and the renderer.

Output: residents_1881_output/residents_1881_uri_manifest.parquet
Columns:
  unique_identifier         str   stable per-row Borealis ID
  persistent_place_id       str   chain id (FK to E53_Place)
  province_code             str   2-letter
  bucket_sdistlet           str   pagination bucket (sdistlet or '-')
  surname_initial           str   pagination bucket secondary
  needs_split               bool  True if leaf page = …/<sdistlet>/<letter>/
  csd_slug                  str   slugified canonical_name from registry
  csd_url                   str   /places/<prov>/<csd_slug>-<tcpuid>-1881/
  leaf_url                  str   csd_url + 'residents/' or
                                  csd_url + 'residents/<sdistlet>/<letter>/'
  person_uri                str   leaf_url + '#p-' + unique_identifier
  page_full_url             str   site_url + leaf_url   (absolute)
  person_full_uri           str   site_url + person_uri (absolute)

Build-time invariants:
  - person_uri is unique across the entire dataset (asserts no two
    residents would resolve to the same fragment on the same page).
  - Every persistent_place_id in the residents parquets resolves to a
    chain in persistent_place_registry.csv (otherwise we can't mint a slug).
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "residents_1881_output"
PROVINCE_DIR = OUT_DIR / "by_province"
REGISTRY = REPO / "persistent_places_output" / "persistent_place_registry.csv"
TCPUID_TO_PLACE = REPO / "persistent_places_output" / "tcpuid_year_to_place.csv"
SPLIT_CSV = OUT_DIR / "sdistlet_buckets_split.csv"
LEAF_COUNTS = OUT_DIR / "leaf_row_counts.csv"

DEFAULT_SITE_URL = "https://jimclifford.ca"
DEFAULT_BASE_PATH = "/hgiscanada"

# Tertiary split: when a (chain, sdistlet, surname-letter) bucket exceeds
# this row count, chunk it by (pageno, line) into sub-pages of
# ~CHUNK_TARGET_SIZE rows each. URL gains a -<chunk> suffix on the surname
# segment: …/residents/<sdistlet>/<letter>-<chunk>/.
LEAF_CHUNK_THRESHOLD = 1000
CHUNK_TARGET_SIZE = 750

SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(s: str) -> str:
    """Match scripts/generate_rag_pages.py:slugify exactly so URIs align with
    the actual rendered pages."""
    return SLUG_RE.sub("-", s.lower()).strip("-")


def load_registry_slugs() -> dict[str, tuple[str, str]]:
    """{persistent_place_id -> (canonical_name, province_2letter)}."""
    out: dict[str, tuple[str, str]] = {}
    with REGISTRY.open() as f:
        rd = csv.DictReader(f)
        for row in rd:
            out[row["persistent_place_id"]] = (
                row["canonical_name"], row["province"].upper(),
            )
    return out


def load_tcpuid_for_1881(chain_ids: set[str]) -> dict[str, str]:
    """{persistent_place_id -> tcpuid (1881 enumeration)}.

    The chain registry's anchor_tcpuid is whatever year the chain anchors on,
    not necessarily 1881. Residents URLs need the 1881 TCPUID specifically
    to match the existing per-presence URL convention
    /places/<prov>/<slug>-<tcpuid>-1881/. Read tcpuid_year_to_place.csv and
    invert: for each (chain_id, year=1881) pick the tcpuid."""
    out: dict[str, str] = {}
    with TCPUID_TO_PLACE.open() as f:
        rd = csv.DictReader(f)
        for row in rd:
            if row["year"] != "1881":
                continue
            pid = row["persistent_place_id"]
            if pid in chain_ids:
                out[pid] = row["tcpuid"]
    return out


def load_split_set() -> set[tuple[str, str]]:
    """{(persistent_place_id, sdistlet)} for sdistlet buckets that exceed
    PAGINATION_ROW_CAP (1000) and need surname-letter sub-pagination."""
    if not SPLIT_CSV.exists():
        return set()
    df = pd.read_csv(SPLIT_CSV)
    return set(zip(df["persistent_place_id"], df["sdistlet"]))


def load_oversized_leaves() -> dict[tuple[str, str, str], int]:
    """{(persistent_place_id, sdistlet, surname_letter) -> row_count} for
    leaf buckets that exceed LEAF_CHUNK_THRESHOLD. These need a tertiary
    chunk split so no leaf page exceeds CHUNK_TARGET_SIZE rows."""
    out: dict[tuple[str, str, str], int] = {}
    if not LEAF_COUNTS.exists():
        return out
    df = pd.read_csv(LEAF_COUNTS)
    for _, r in df.iterrows():
        n = int(r["row_count"])
        if n > LEAF_CHUNK_THRESHOLD:
            out[(r["persistent_place_id"], str(r["sdistlet"]),
                 str(r["surname_initial"]))] = n
    return out


def assign_chunks_for_oversized(df: pd.DataFrame,
                                 oversized: dict) -> pd.Series:
    """Return a Series of chunk-ids (str) aligned with df.index. Empty string
    for non-oversized rows. For oversized buckets, sort within bucket by
    (pageno, line) and assign chunk indices "1", "2", ... at
    CHUNK_TARGET_SIZE-row boundaries.

    Stable order: pyarrow CSV output preserves insertion order across chunks
    but per-chain ordering within a province parquet is not guaranteed, so
    we explicitly sort by (pageno, line) before chunking."""
    chunk_col = pd.Series([""] * len(df), index=df.index)
    if not oversized:
        return chunk_col
    # Coerce pageno/line to integers for stable ordering. Missing → 0.
    pageno_int = pd.to_numeric(df.get("pageno"), errors="coerce").fillna(0).astype(int)
    line_int = pd.to_numeric(df.get("line"), errors="coerce").fillna(0).astype(int)
    bucket_keys = list(zip(df["persistent_place_id"], df["bucket_sdistlet"],
                            df["surname_initial"]))
    df_sortkeys = pd.DataFrame({
        "_pid": df["persistent_place_id"].values,
        "_sd":  df["bucket_sdistlet"].values,
        "_li":  df["surname_initial"].values,
        "_p":   pageno_int.values,
        "_l":   line_int.values,
    }, index=df.index)
    # Process each oversized bucket independently.
    for (pid, sd, ltr), _n in oversized.items():
        mask = ((df_sortkeys["_pid"] == pid)
                & (df_sortkeys["_sd"] == sd)
                & (df_sortkeys["_li"] == ltr))
        if not mask.any():
            continue
        sub = df_sortkeys[mask].sort_values(["_p", "_l"], kind="stable")
        # Assign chunk index 1, 2, 3, ... at CHUNK_TARGET_SIZE boundaries.
        chunk_indices = ((pd.RangeIndex(len(sub)) // CHUNK_TARGET_SIZE) + 1
                          ).astype(str)
        chunk_col.loc[sub.index] = chunk_indices.tolist()
    return chunk_col


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site-url", default=DEFAULT_SITE_URL)
    ap.add_argument("--base-path", default=DEFAULT_BASE_PATH)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    province_paths = sorted(PROVINCE_DIR.glob("*.parquet"))
    if not province_paths:
        sys.exit(f"No per-province parquets in {PROVINCE_DIR}; run prepare first.")

    registry = load_registry_slugs()
    chains_in_data: set[str] = set()
    for p in province_paths:
        for batch in pq.ParquetFile(p).iter_batches(
                batch_size=200_000, columns=["persistent_place_id"]):
            chains_in_data.update(batch.column(0).to_pylist())
    print(f"[cidoc] {len(chains_in_data):,} chains have residents",
          file=sys.stderr)

    missing = chains_in_data - set(registry)
    if missing:
        sys.exit(f"[cidoc] FATAL: {len(missing)} chain ids in residents have "
                 f"no entry in persistent_place_registry.csv. Sample: "
                 f"{sorted(missing)[:5]}")

    tcpuid_for_1881 = load_tcpuid_for_1881(chains_in_data)
    no_tcpuid = chains_in_data - set(tcpuid_for_1881)
    if no_tcpuid:
        # Should not happen — every chain with residents was matched via
        # tcpuid_year_to_place.csv at prepare time, so reverse lookup must
        # find them. Fail loudly if not.
        sys.exit(f"[cidoc] FATAL: {len(no_tcpuid)} chains lack a 1881 TCPUID "
                 f"in tcpuid_year_to_place.csv. Sample: "
                 f"{sorted(no_tcpuid)[:5]}")

    split_set = load_split_set()
    oversized = load_oversized_leaves()
    print(f"[cidoc] {len(split_set):,} sdistlet buckets need surname-letter split",
          file=sys.stderr)
    print(f"[cidoc] {len(oversized):,} (sdistlet, surname-letter) leaves "
          f"oversized (>{LEAF_CHUNK_THRESHOLD} rows); chunking at "
          f"{CHUNK_TARGET_SIZE} rows", file=sys.stderr)

    base = args.base_path
    out_rows = []
    seen_person_uris: set[str] = set()
    duplicate_uris: list[str] = []

    for pp in province_paths:
        cols = ["unique_identifier", "persistent_place_id",
                "province_code", "bucket_sdistlet", "surname_initial",
                "TCPUID_CSD_1881", "pageno", "line"]
        df = pq.read_table(pp, columns=cols).to_pandas()
        df = df.dropna(subset=["unique_identifier"])
        df = df[df["unique_identifier"].astype(str) != ""]

        # Tertiary chunk assignment for oversized (chain, sdistlet, letter)
        # buckets. Empty-string for buckets that don't need a chunk split.
        df["bucket_chunk"] = assign_chunks_for_oversized(df, oversized)

        # Per-row URL minting.
        cd_slug_arr = []
        csd_url_arr = []
        leaf_url_arr = []
        needs_split_arr = []
        for pid, sdistlet, surname_letter, chunk in zip(
                df["persistent_place_id"], df["bucket_sdistlet"],
                df["surname_initial"], df["bucket_chunk"]):
            canonical, _prov = registry[pid]
            tcpuid = tcpuid_for_1881[pid].lower()
            csd_slug = slugify(canonical)
            csd_url = f"{base}/places/{_prov.lower()}/{csd_slug}-{tcpuid}-1881/"
            split = (pid, sdistlet) in split_set
            if split:
                letter_seg = surname_letter.lower()
                if chunk:
                    letter_seg = f"{letter_seg}-{chunk}"
                leaf_url = f"{csd_url}residents/{sdistlet}/{letter_seg}/"
            else:
                leaf_url = f"{csd_url}residents/"
            cd_slug_arr.append(csd_slug)
            csd_url_arr.append(csd_url)
            leaf_url_arr.append(leaf_url)
            needs_split_arr.append(split)

        df["csd_slug"] = cd_slug_arr
        df["csd_url"] = csd_url_arr
        df["leaf_url"] = leaf_url_arr
        df["needs_split"] = needs_split_arr
        df["person_uri"] = df["leaf_url"] + "#p-" + df["unique_identifier"].astype(str)
        df["page_full_url"] = args.site_url + df["leaf_url"]
        df["person_full_uri"] = args.site_url + df["person_uri"]

        # Uniqueness check (within this province; we re-check globally below).
        local_dup = df[df["person_uri"].duplicated(keep=False)]
        if not local_dup.empty:
            duplicate_uris.extend(local_dup["person_uri"].head(10).tolist())

        out_rows.append(df[[
            "unique_identifier", "persistent_place_id", "province_code",
            "bucket_sdistlet", "surname_initial", "bucket_chunk",
            "needs_split",
            "csd_slug", "csd_url", "leaf_url",
            "person_uri", "page_full_url", "person_full_uri",
            "TCPUID_CSD_1881",
        ]])
        print(f"[cidoc] {pp.name}: {len(df):,} rows manifested", file=sys.stderr)

    manifest = pd.concat(out_rows, ignore_index=True)
    print(f"[cidoc] total manifest rows: {len(manifest):,}", file=sys.stderr)

    # Global uniqueness check.
    dup_mask = manifest["person_uri"].duplicated(keep=False)
    if dup_mask.any():
        dup_count = int(dup_mask.sum())
        sample = manifest.loc[dup_mask, "person_uri"].head(10).tolist()
        sys.exit(f"[cidoc] FATAL: {dup_count} duplicate person_uris detected. "
                 f"Sample: {sample}")

    # Write parquet.
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / "residents_1881_uri_manifest.parquet"
    manifest.to_parquet(out_path, compression="zstd")
    print(f"[cidoc] wrote {out_path} ({len(manifest):,} rows)", file=sys.stderr)

    # Mark CIDOC stamp file for Makefile dependency tracking.
    (args.out_dir / "cidoc.stamp").write_text(
        f"residents_1881_uri_manifest rows={len(manifest)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
