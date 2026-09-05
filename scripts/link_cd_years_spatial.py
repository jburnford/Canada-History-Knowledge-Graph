#!/usr/bin/env python3
"""
Link Census Divisions (CDs) across years using spatial overlap analysis.

Similar to CSD linking but for CD-level aggregation units.
Tracks boundary changes in administrative divisions over time.

Author: Claude Code
Date: September 30, 2025
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path
import argparse
import sys


def load_cd_layer(gdb_path: str, year: int, crs="EPSG:3347") -> gpd.GeoDataFrame:
    """Aggregate the same repaired CSD geometries used by the CSD linker."""
    from _gis import dissolve_cds, load_csd_layer
    csds, audit = load_csd_layer(gdb_path, year, crs)
    frame = dissolve_cds(csds)
    print(f"Loaded {year}: {len(frame)} CDs; {len(audit)} CSD preparation actions", file=sys.stderr)
    return frame


def compute_overlap(gdf_from: gpd.GeoDataFrame, gdf_to: gpd.GeoDataFrame) -> pd.DataFrame:
    """Every positive-area CD correspondence, with unrounded evidence."""
    from _gis import overlap_table
    rows = []
    for row in overlap_table(gdf_from, gdf_to).itertuples():
        if row.iou > .98:
            relation = "SAME_AS"
        elif row.frac_from > .95:
            relation = "WITHIN"
        elif row.frac_to > .95:
            relation = "CONTAINS"
        else:
            relation = "OVERLAPS"
        rows.append({"cd_from": gdf_from.iloc[row.from_index].cd_id,
                     "cd_to": gdf_to.iloc[row.to_index].cd_id,
                     "relationship": relation, "iou": row.iou,
                     "from_fraction": row.frac_from, "to_fraction": row.frac_to,
                     "overlap_sqm": row.overlap_sqm,
                     "area_from_sqm": row.area_from_sqm, "area_to_sqm": row.area_to_sqm,
                     "area_crs": gdf_from.crs.to_string(),
                     "evidence_kind": "computed_polygon_intersection",
                     "historical_succession_verified": False,
                     "involves_no_data": bool(gdf_from.iloc[row.from_index].get('is_coverage_record', False) or
                                              gdf_to.iloc[row.to_index].get('is_coverage_record', False))})
    return pd.DataFrame(rows, columns=["cd_from", "cd_to", "relationship", "iou",
                        "from_fraction", "to_fraction", "overlap_sqm", "area_from_sqm",
                        "area_to_sqm", "area_crs", "evidence_kind", "historical_succession_verified", "involves_no_data"])


def classify_links(links_df: pd.DataFrame, gdf_from: gpd.GeoDataFrame, gdf_to: gpd.GeoDataFrame) -> tuple:
    """Classify links into high-confidence and ambiguous."""

    if len(links_df) == 0:
        return links_df.copy(), links_df.copy()

    # Strong geometric candidates only; no historical identity is established.
    high_confidence = links_df[
        ((links_df['relationship'] == 'SAME_AS')) |
        (links_df['relationship'] == 'WITHIN') |
        (links_df['relationship'] == 'CONTAINS')
    ].copy()

    # Remaining geometric candidates (no name filter is applied here).
    ambiguous = links_df[
        ~links_df.index.isin(high_confidence.index)
    ].copy()

    return high_confidence, ambiguous


def main():
    parser = argparse.ArgumentParser(description='Link CDs across census years using spatial overlap')
    parser.add_argument('--gdb', required=True, help='Path to FileGDB')
    parser.add_argument('--year-from', type=int, required=True, help='Source year')
    parser.add_argument('--year-to', type=int, required=True, help='Target year')
    parser.add_argument('--out', required=True, help='Output directory')
    parser.add_argument('--crs', default='EPSG:3347',
                        help='Area CRS: EPSG:3347 for legacy comparison; ESRI:102001 for equal-area evidence')
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True, parents=True)

    # Load both years
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Linking CDs: {args.year_from} → {args.year_to}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    gdf_from = load_cd_layer(args.gdb, args.year_from, args.crs)
    gdf_to = load_cd_layer(args.gdb, args.year_to, args.crs)

    # Compute overlaps
    all_links = compute_overlap(gdf_from, gdf_to)
    # Preserve the legacy partitions for existing consumers; the complete
    # evidence table also includes intersections below the old 1000 m² cutoff.
    links_df = all_links[all_links.overlap_sqm > 1000].copy()

    # Classify
    high_conf, ambiguous = classify_links(links_df, gdf_from, gdf_to)

    # Write outputs
    year_pair = f"{args.year_from}_{args.year_to}"

    high_conf.to_csv(out_dir / f"cd_links_{year_pair}.csv", index=False)
    ambiguous.to_csv(out_dir / f"cd_ambiguous_{year_pair}.csv", index=False)
    all_links.to_csv(out_dir / f"cd_correspondences_{year_pair}.csv", index=False)

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SUMMARY: {args.year_from} → {args.year_to}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"CDs ({args.year_from}): {len(gdf_from)}", file=sys.stderr)
    print(f"CDs ({args.year_to}): {len(gdf_to)}", file=sys.stderr)
    print(f"Total overlaps: {len(links_df)}", file=sys.stderr)
    print(f"  High-confidence: {len(high_conf)}", file=sys.stderr)
    if len(high_conf) > 0:
        for rel in ['SAME_AS', 'CONTAINS', 'WITHIN']:
            count = len(high_conf[high_conf['relationship'] == rel])
            if count > 0:
                print(f"    {rel}: {count}", file=sys.stderr)
    print(f"  Ambiguous: {len(ambiguous)}", file=sys.stderr)
    if len(ambiguous) > 0:
        for rel in ['SAME_AS', 'OVERLAPS']:
            count = len(ambiguous[ambiguous['relationship'] == rel])
            if count > 0:
                print(f"    {rel}: {count}", file=sys.stderr)

    print(f"\nDone!\n", file=sys.stderr)


if __name__ == '__main__':
    main()
