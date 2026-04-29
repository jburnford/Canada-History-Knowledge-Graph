#!/usr/bin/env python3
"""Generate p10_csd_within_cd_presence_<year>.csv from the published TCP/HGIS
Excel CSD-level tables (V1T1 / V1T2 / V1T7), which are the authoritative
CD↔CSD membership for the 1851–1901 census series.

Why this exists: the previous build_cd_presences.py route derived CSD-within-CD
relationships from the GDB CSD layer's NAME_CD column (one row per polygon).
That misses cases where the GDB's spatial encoding splits a city CD into one
"city polygon" CSD while the published census table assigns several ward-level
CSDs to that same city CD. Examples found in the 1901 audit:
  - Kingston City: GDB → 1 CSD, Excel → 7 ward CSDs
  - Victoria City: GDB → 1 CSD, Excel → 4 CSDs
  - Renfrew (1861, mis-OCR'd "Renfew"): the GDB has both spellings as separate
    CDs; Excel has only "Renfrew" with 21 CSDs.

Coverage:
  1851, 1861, 1871, 1881 — V1T1 CSD-level
  1891 — V1T2 CSD-level (1891 series uses V1T2 as base table)
  1901 — V1T7 CSD-level (1901 series uses V1T7)
  1911, 1921 — only PUB tables published (code-based, no NAME_CD); falls
               through to existing GDB-derived p10.

Output: writes neo4j_cidoc_crm_v2/p10_csd_within_cd_presence_<year>.csv with
the standard schema (:START_ID, :END_ID, :TYPE) and a sidecar
data_quality/p10_excel_vs_gdb.csv summarising every diff against the
GDB-derived p10 the script would otherwise replace.
"""

import argparse
import csv
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

REPO = Path(__file__).resolve().parents[1]

# Levenshtein-similarity threshold for fuzzy CD name resolution. Excel and the
# GDB occasionally OCR'd the same county differently (Renfew/Renfrew, Outaouais/
# Ottawa, Drummond & Arthabaska / Drummond and Arthabaska). 88+ catches single-
# letter typos and `&`/`and` substitutions without false-merging distinct CDs.
# Verified: "Renfew" vs "Renfrew" = 92.3, "Renfrew" vs "Renfew County" = 78
# (rejected — different units), "Toronto City" vs "Toronto" = 68 (rejected).
FUZZY_MIN_RATIO = 88.0

# Year → published table to use, with the canonical CSD-level workbook path.
# 1851/1861/1871/1881 use V1T1; 1891 uses V1T2; 1901 uses V1T7. These are the
# tables whose CSD/CD breakdowns match the boundary file TCPUIDs.
EXCEL_SOURCES = {
    1851: ("V1T1", "1851/1851_V1T1_CSD_202306.xlsx"),
    1861: ("V1T1", "1861/1861_V1T1_CSD_202306.xlsx"),
    1871: ("V1T1", "1871/1871_V1T1_CSD_202306.xlsx"),
    1881: ("V1T1", "1881/1881_V1T1_CSD_202306.xlsx"),
    1891: ("V1T2", "1891/1891_V1T2_CSD_202306.xlsx"),
    1901: ("V1T7", "1901/1901_V1T7_CSD_202306.xlsx"),
}

CIDOC_DIR = REPO / "neo4j_cidoc_crm_v2"
CHAINS_DIR = REPO / "persistent_cds_output"
DATA_QUALITY_DIR = REPO / "data_quality"


def normalize_for_match(name: str) -> str:
    """Match key for resolving Excel NAME_CD to a chain in the registry.

    Folds diacritics, unifies apostrophe variants, treats `&` as "and",
    strips/normalizes whitespace and the common punctuation the two sources
    use inconsistently — so "Renfrew, North—Nord" (GDB) and "Renfrew
    (North-Nord.)" (Excel) both reduce to "renfrew north nord".

    Critical: em-dashes/hyphens/parens become SPACES (not deletions). Earlier
    versions stripped them outright, which collapsed "North—Nord" → "NorthNord"
    and dropped directional content from parenthesised qualifiers."""
    if not name:
        return ""
    s = name.replace("’", "'").replace("‘", "'").replace("`", "'")
    s = s.replace("&", " and ")
    # Punctuation the two sources differ on — to space, not deletion. Em/en
    # dashes are not ASCII so the encode step below would strip them silently.
    for ch in "—–-(),.":
        s = s.replace(ch, " ")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def load_chain_map(path: Path) -> dict:
    """raw_cd_id × year → chain_place_id (post-Phase-1 chain collapse)."""
    if not path.exists():
        print(f"  WARNING: {path} not found; chains won't collapse",
              file=sys.stderr)
        return {}
    out = {}
    with path.open() as f:
        for r in csv.DictReader(f):
            out[(r["raw_cd_id"], int(r["year"]))] = r["chain_place_id"]
    return out


def build_chain_name_index(chain_map: dict) -> dict:
    """(year, province, normalized_name) → list of chain_place_id.

    Indexes the chain registry by (year, province, normalized name) so Excel
    rows whose NAME_CD doesn't directly match a raw_cd_id can still be routed
    to the right chain via fuzzy lookup."""
    index = defaultdict(set)
    for (raw_cd_id, year), chain_id in chain_map.items():
        # raw_cd_id is "CD_<PR>_<name with underscores>"
        parts = raw_cd_id.split("_", 2)
        if len(parts) < 3 or parts[0] != "CD":
            continue
        prov = parts[1]
        name = parts[2].replace("_", " ")
        norm = normalize_for_match(name)
        if norm:
            index[(year, prov, norm)].add(chain_id)
    return index


def resolve_chain_for_excel(year: int, prov: str, name_cd: str,
                             chain_map: dict, name_index: dict,
                             fuzzy_pool: dict) -> tuple[str, str]:
    """Return (chain_id, resolution_method).

    1. Exact: raw_cd_id is in chain_map.
    2. Normalized: same (year, prov, normalized_name) is in chain_map.
    3. Fuzzy: rapidfuzz best match in same (year, prov) above FUZZY_MIN_RATIO.
    4. Fall through: synthesize chain_id from raw_cd_id (caller can drop)."""
    raw_cd_id = f"CD_{prov}_{name_cd.replace(' ', '_')}"
    if (raw_cd_id, year) in chain_map:
        return chain_map[(raw_cd_id, year)], "exact"

    norm = normalize_for_match(name_cd)
    if norm:
        candidates = name_index.get((year, prov, norm), set())
        if len(candidates) == 1:
            return next(iter(candidates)), "normalized"
        if len(candidates) > 1:
            # Multiple chains share this normalized name; prefer the
            # alphabetically-first chain id for determinism.
            return sorted(candidates)[0], "normalized_multi"

    pool_key = (year, prov)
    pool = fuzzy_pool.get(pool_key)
    if pool:
        match = process.extractOne(norm, pool.keys(),
                                    scorer=fuzz.ratio,
                                    score_cutoff=FUZZY_MIN_RATIO)
        if match:
            best_norm, score, _ = match
            chain_ids = pool[best_norm]
            if len(chain_ids) == 1:
                return next(iter(chain_ids)), f"fuzzy:{score:.0f}"

    return raw_cd_id, "unmatched"


def build_fuzzy_pool(name_index: dict) -> dict:
    """(year, prov) → {normalized_name: set(chain_ids)} — used as the
    candidate pool for fuzzy matching."""
    pool = defaultdict(lambda: defaultdict(set))
    for (year, prov, norm), chains in name_index.items():
        pool[(year, prov)][norm] |= chains
    return {k: dict(v) for k, v in pool.items()}


def load_csd_presence_ids(year: int) -> set[str]:
    """Read e93_presence_<year>.csv to know which CSD presences exist.
    Excel rows whose TCPUID has no matching presence in the GDB layer are
    dropped from p10 (no point pointing at a non-existent node)."""
    path = CIDOC_DIR / f"e93_presence_{year}.csv"
    if not path.exists():
        print(f"  WARNING: {path} not found", file=sys.stderr)
        return set()
    out = set()
    with path.open() as f:
        for r in csv.DictReader(f):
            pid = r.get("presence_id:ID") or r.get(":ID") or ""
            if pid:
                out.add(pid)
    return out


def load_existing_gdb_p10(year: int) -> pd.DataFrame:
    """Read the GDB-derived p10 file for diff reporting."""
    path = CIDOC_DIR / f"p10_csd_within_cd_presence_{year}.csv"
    if not path.exists():
        return pd.DataFrame(columns=[":START_ID", ":END_ID", ":TYPE"])
    return pd.read_csv(path)


def build_excel_p10(year: int, excel_path: Path,
                    chain_map: dict, name_index: dict, fuzzy_pool: dict,
                    valid_csd_presences: set[str],
                    valid_chain_ids: set[str]
                    ) -> tuple[pd.DataFrame, list[dict], dict]:
    """Build Excel-derived p10 for one year.

    Returns:
      p10 dataframe (only rows that resolve to an existing chain in the
                     registry AND a valid CSD presence)
      orphan rows (TCPUID_CSD with no presence, OR chain unresolved)
      method_counts ({exact, normalized, fuzzy:NN, unmatched} → count)"""
    df = pd.read_excel(excel_path)
    cd_col = f"NAME_CD_{year}"
    csd_col = f"NAME_CSD_{year}"
    tcpuid_csd = f"TCPUID_CSD_{year}"
    for c in ("PR", cd_col, tcpuid_csd):
        if c not in df.columns:
            raise RuntimeError(f"{year}: missing column {c} in {excel_path}")

    df = df.dropna(subset=["PR", cd_col, tcpuid_csd]).copy()
    df["PR"] = df["PR"].astype(str).str.strip()
    df[cd_col] = df[cd_col].astype(str).str.strip()
    df[tcpuid_csd] = df[tcpuid_csd].astype(str).str.strip()

    method_counts = defaultdict(int)
    chain_resolutions = []
    for _, r in df.iterrows():
        chain_id, method = resolve_chain_for_excel(
            year, r["PR"], r[cd_col],
            chain_map, name_index, fuzzy_pool,
        )
        chain_resolutions.append((chain_id, method))
        # Coarse bucket (collapse "fuzzy:88","fuzzy:91" into "fuzzy") for stats.
        method_counts[method.split(":", 1)[0]] += 1
    df["chain_id"] = [c[0] for c in chain_resolutions]
    df["resolution"] = [c[1] for c in chain_resolutions]

    df["csd_presence"] = df[tcpuid_csd] + f"_{year}"
    df["cd_presence"] = df["chain_id"] + f"_{year}"
    df["valid_csd"] = df["csd_presence"].isin(valid_csd_presences)
    df["valid_chain"] = df["chain_id"].isin(valid_chain_ids)

    orphans = df.loc[~(df["valid_csd"] & df["valid_chain"]), [
        "PR", cd_col, csd_col, tcpuid_csd, "csd_presence", "chain_id",
        "resolution", "valid_csd", "valid_chain",
    ]].rename(columns={cd_col: "name_cd", csd_col: "name_csd",
                        tcpuid_csd: "tcpuid_csd"})
    orphans["year"] = year
    orphan_rows = orphans.to_dict("records")

    valid = df[df["valid_csd"] & df["valid_chain"]].copy()
    p10 = pd.DataFrame({
        ":START_ID": valid["csd_presence"],
        ":END_ID": valid["cd_presence"],
        ":TYPE": "P10_falls_within",
    })
    return p10, orphan_rows, dict(method_counts)


def hybrid_merge(excel_p10: pd.DataFrame,
                 gdb_p10: pd.DataFrame,
                 valid_chain_presences: set[str]) -> pd.DataFrame:
    """For each chain (`:END_ID`), Excel wins if it has any rows; otherwise
    fall through to GDB. This preserves GDB-only chains (e.g., 1911/1921 PUB
    years that don't have CSD-level Excel) while replacing GDB membership
    for the chains where Excel has authoritative data.

    Why per-chain (not per-CSD): when Excel says "Kingston has 7 wards"
    and GDB-p10 already had "Kingston: 1 CSD (the city polygon itself)",
    we want Excel's 7 to fully replace GDB's 1 — not append.

    valid_chain_presences gates ALL rows — Excel and GDB. The on-disk GDB p10
    may reference stutter chain ids (e.g. CD_QC_Champlain_1891_1891_1891_1891)
    that don't exist after a fresh chain-builder run; those stale rows would
    otherwise survive the merge as broken FKs."""
    chains_in_excel = set(excel_p10[":END_ID"].unique())
    excel_keep = excel_p10[excel_p10[":END_ID"].isin(valid_chain_presences)]
    gdb_keep = gdb_p10[(~gdb_p10[":END_ID"].isin(chains_in_excel))
                       & (gdb_p10[":END_ID"].isin(valid_chain_presences))]
    return pd.concat([excel_keep, gdb_keep], ignore_index=True)


def load_chain_registry_ids() -> set[str]:
    """Set of chain place_ids for FK validation."""
    path = CHAINS_DIR / "persistent_cd_registry.csv"
    if not path.exists():
        return set()
    df = pd.read_csv(path)
    return set(df["place_id"].dropna())


def load_valid_cd_presences() -> set[str]:
    """Synthesize the set of valid <chain_id>_<year> presence ids from
    persistent_cd_registry.csv's years_active column. We can't read the
    on-disk e93_presence_cd_<year>.csv directly because it may be stale
    (generated against an older chain registry with stutter chains)."""
    path = CHAINS_DIR / "persistent_cd_registry.csv"
    if not path.exists():
        return set()
    df = pd.read_csv(path)
    out = set()
    for _, r in df.iterrows():
        cid = r["place_id"]
        years = str(r.get("years_active", "")).split(";")
        for y in years:
            y = y.strip()
            if y.isdigit():
                out.add(f"{cid}_{y}")
    return out


def diff_excel_vs_gdb(year: int, excel_p10: pd.DataFrame,
                      gdb_p10: pd.DataFrame) -> list[dict]:
    """Per-edge diff. Returns rows for data_quality report."""
    excel_pairs = set(zip(excel_p10[":START_ID"], excel_p10[":END_ID"]))
    gdb_pairs = set(zip(gdb_p10[":START_ID"], gdb_p10[":END_ID"]))
    only_excel = excel_pairs - gdb_pairs
    only_gdb = gdb_pairs - excel_pairs

    # Aggregate by CD for legibility.
    rows = []
    excel_by_cd = defaultdict(set)
    gdb_by_cd = defaultdict(set)
    for s, e in excel_pairs:
        excel_by_cd[e].add(s)
    for s, e in gdb_pairs:
        gdb_by_cd[e].add(s)
    all_cds = set(excel_by_cd) | set(gdb_by_cd)
    for cd in sorted(all_cds):
        ex = excel_by_cd[cd]
        gd = gdb_by_cd[cd]
        if ex == gd:
            continue
        rows.append({
            "year": year,
            "cd_presence": cd,
            "excel_csds": len(ex),
            "gdb_csds": len(gd),
            "only_in_excel": ";".join(sorted(ex - gd)) if ex - gd else "",
            "only_in_gdb": ";".join(sorted(gd - ex)) if gd - ex else "",
        })
    return rows


def main():
    # Resolve default data root from config; fall through to a CLI override.
    sys.path.insert(0, str(REPO / "scripts"))
    from _config import CONFIG  # noqa: E402

    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root",
                    default=str(CONFIG.data_root),
                    help="Root containing 1851/, 1861/, ... per-year folders "
                         "(default from config.toml [paths].data_root)")
    ap.add_argument("--years", default=",".join(str(y) for y in EXCEL_SOURCES),
                    help="Comma-separated subset of years to process")
    ap.add_argument("--dry-run", action="store_true",
                    help="Compute and report; don't overwrite p10 files")
    args = ap.parse_args()

    DATA_QUALITY_DIR.mkdir(exist_ok=True)
    chain_map = load_chain_map(CHAINS_DIR / "cd_id_year_to_chain.csv")
    name_index = build_chain_name_index(chain_map)
    fuzzy_pool = build_fuzzy_pool(name_index)
    valid_chain_ids = load_chain_registry_ids()
    valid_chain_presences = load_valid_cd_presences()
    print(f"Loaded {len(chain_map)} chain mappings, "
          f"{len(name_index)} (year,prov,name) keys, "
          f"{len(valid_chain_ids)} chain IDs, "
          f"{len(valid_chain_presences)} chain×year presences",
          file=sys.stderr)

    years = [int(y) for y in args.years.split(",") if y.strip()]
    all_diffs = []
    all_orphans = []
    for yr in years:
        if yr not in EXCEL_SOURCES:
            print(f"\n{yr}: no Excel CSD-level table available "
                  f"(PUB-only year); keeping GDB-derived p10",
                  file=sys.stderr)
            continue
        _table, rel_path = EXCEL_SOURCES[yr]
        excel_path = Path(args.data_root) / rel_path
        if not excel_path.exists():
            print(f"\n{yr}: Excel not found at {excel_path}", file=sys.stderr)
            continue

        print(f"\n=== {yr} ({_table}) ===", file=sys.stderr)
        valid_presences = load_csd_presence_ids(yr)
        print(f"  {len(valid_presences)} CSD presences in e93_presence_{yr}.csv",
              file=sys.stderr)
        excel_p10, orphans, methods = build_excel_p10(
            yr, excel_path, chain_map, name_index, fuzzy_pool,
            valid_presences, valid_chain_ids,
        )
        gdb_p10 = load_existing_gdb_p10(yr)
        merged = hybrid_merge(excel_p10, gdb_p10, valid_chain_presences)

        diffs = diff_excel_vs_gdb(yr, merged, gdb_p10)
        all_diffs.extend(diffs)
        all_orphans.extend(orphans)

        method_str = ", ".join(f"{k}={v}" for k, v in sorted(methods.items()))
        print(f"  Excel resolution methods: {method_str}", file=sys.stderr)
        print(f"  Excel-derived: {len(excel_p10)} rows "
              f"({excel_p10[':END_ID'].nunique()} CDs)", file=sys.stderr)
        print(f"  GDB-derived:   {len(gdb_p10)} rows "
              f"({gdb_p10[':END_ID'].nunique()} CDs)", file=sys.stderr)
        print(f"  Hybrid merged: {len(merged)} rows "
              f"({merged[':END_ID'].nunique()} CDs)", file=sys.stderr)
        print(f"  CDs differing (merged vs gdb-only): {len(diffs)}", file=sys.stderr)
        print(f"  Orphans (CSD presence missing OR chain unresolved): "
              f"{len(orphans)}", file=sys.stderr)

        if not args.dry_run:
            out_path = CIDOC_DIR / f"p10_csd_within_cd_presence_{yr}.csv"
            merged.to_csv(out_path, index=False)
            print(f"  Wrote {out_path}", file=sys.stderr)

    # Sidecar reports.
    if all_diffs:
        diff_df = pd.DataFrame(all_diffs)
        diff_df.to_csv(DATA_QUALITY_DIR / "p10_excel_vs_gdb.csv", index=False)
        print(f"\nWrote {DATA_QUALITY_DIR / 'p10_excel_vs_gdb.csv'} "
              f"({len(diff_df)} CDs differ)", file=sys.stderr)
    if all_orphans:
        orphan_df = pd.DataFrame(all_orphans)
        orphan_df.to_csv(DATA_QUALITY_DIR / "p10_excel_orphans.csv", index=False)
        print(f"Wrote {DATA_QUALITY_DIR / 'p10_excel_orphans.csv'} "
              f"({len(orphan_df)} unmatched Excel CSDs)", file=sys.stderr)


if __name__ == "__main__":
    main()
