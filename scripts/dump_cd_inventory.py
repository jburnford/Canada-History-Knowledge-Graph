#!/usr/bin/env python3
"""Dump the complete (cd_id, year) inventory from the GDB.

Writes cd_links_output/cd_inventory.csv with one row per (raw CD, census
year): cd_id, year, province, cd_name.

Purpose: build_persistent_cds.py needs the full CD universe to mint
singleton chains for CDs that appear in no cd_links pair. It used to
scrape that universe from neo4j_cidoc_crm_v2/e93_presence_cd_*.csv — a
DOWNSTREAM output whose cd_id column contains canonicalized CHAIN ids on
any rerun, silently injecting duplicate registry rows (the 36e08b607 bug,
and again in the 2026-08-09 rebuild where 424 ghost chains appeared).
This script derives the same universe from the GDB source instead, which
can never contain chain ids. Requires the conda `geo` env (geopandas).

cd_id construction mirrors link_cd_years_spatial.py exactly:
strip cd_name, then 'CD_' + pr + '_' + cd_name.replace(' ', '_').
"""

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _config import CONFIG  # noqa: E402

YEARS = [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921]
OUT = Path("cd_links_output") / "cd_inventory.csv"


def main() -> int:
    rows = []
    for year in YEARS:
        layer = f"CANADA_{year}_CSD"
        print(f"[inventory] {layer} …", file=sys.stderr)
        gdf = gpd.read_file(CONFIG.gdb_path, layer=layer,
                            ignore_geometry=True)
        cd_col = [c for c in gdf.columns
                  if "NAME_CD" in c.upper() and "CSD" not in c.upper()][0]
        pr_col = [c for c in gdf.columns
                  if c.startswith("PR") or c.startswith("pr")][0]
        sub = gdf[[cd_col, pr_col]].rename(
            columns={cd_col: "cd_name", pr_col: "pr"})
        sub["cd_name"] = sub["cd_name"].fillna("").str.strip()
        sub = sub[sub["cd_name"] != ""].drop_duplicates()
        for r in sub.itertuples():
            rows.append({
                "cd_id": f"CD_{r.pr}_{r.cd_name.replace(' ', '_')}",
                "year": year,
                "province": r.pr,
                "cd_name": r.cd_name,
            })
    df = pd.DataFrame(rows).drop_duplicates(subset=["cd_id", "year"])
    OUT.parent.mkdir(exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"[inventory] wrote {len(df)} (cd_id, year) rows → {OUT}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
