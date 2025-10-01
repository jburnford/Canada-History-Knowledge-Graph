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
from shapely import make_valid


def load_cd_layer(gdb_path: str, year: int) -> gpd.GeoDataFrame:
    """Load and aggregate CSD layer to CD level."""
    layer_name = f"CANADA_{year}_CSD"
    print(f"Loading {layer_name}...", file=sys.stderr)

    gdf = gpd.read_file(gdb_path, layer=layer_name)

    # Standardize column names
    rename_map = {}
    for col in gdf.columns:
        if col == f'TCPUID_CSD_{year}':
            rename_map[col] = 'tcpuid'
        elif col == f'PR_{year}':
            rename_map[col] = 'pr'
        elif col in [f'Name_CD_{year}', f'NAME_CD_{year}']:
            rename_map[col] = 'cd_name'

    gdf = gdf.rename(columns=rename_map)

    # Validate geometries
    invalid_mask = ~gdf.is_valid
    if invalid_mask.any():
        print(f"  Fixing {invalid_mask.sum()} invalid geometries...", file=sys.stderr)
        gdf.loc[invalid_mask, 'geometry'] = gdf.loc[invalid_mask, 'geometry'].apply(make_valid)

    # Reproject to EPSG:3347
    if gdf.crs is None or gdf.crs.to_epsg() != 3347:
        print(f"  Reprojecting to EPSG:3347...", file=sys.stderr)
        gdf = gdf.to_crs(epsg=3347)

    # Dissolve CSDs to CD level
    print(f"  Dissolving CSDs to CD level...", file=sys.stderr)
    cd_gdf = gdf[['pr', 'cd_name', 'geometry']].dissolve(by=['pr', 'cd_name'], as_index=False)

    # Create CD ID
    cd_gdf['cd_id'] = 'CD_' + cd_gdf['pr'] + '_' + cd_gdf['cd_name'].str.replace(' ', '_')
    cd_gdf['area'] = cd_gdf.geometry.area

    print(f"  Loaded {len(cd_gdf)} CDs", file=sys.stderr)
    return cd_gdf


def compute_overlap(gdf_from: gpd.GeoDataFrame, gdf_to: gpd.GeoDataFrame) -> pd.DataFrame:
    """Compute spatial overlap between CD layers."""
    print(f"Computing overlaps between {len(gdf_from)} and {len(gdf_to)} CDs...", file=sys.stderr)

    links = []
    sindex = gdf_to.sindex

    for idx, row_from in gdf_from.iterrows():
        geom_from = row_from['geometry']
        cd_from = row_from['cd_id']
        area_from = row_from['area']

        # Find potential overlaps
        possible_matches_idx = list(sindex.intersection(geom_from.bounds))
        possible_matches = gdf_to.iloc[possible_matches_idx]

        for idx_to, row_to in possible_matches.iterrows():
            geom_to = row_to['geometry']
            cd_to = row_to['cd_id']
            area_to = row_to['area']

            # Compute intersection
            if geom_from.intersects(geom_to):
                intersection = geom_from.intersection(geom_to)
                overlap_area = intersection.area

                if overlap_area > 1000:  # >1000 sq m threshold
                    # Compute IoU and containment fractions
                    union_area = geom_from.union(geom_to).area
                    iou = overlap_area / union_area if union_area > 0 else 0

                    from_fraction = overlap_area / area_from if area_from > 0 else 0
                    to_fraction = overlap_area / area_to if area_to > 0 else 0

                    # Classify relationship
                    if iou > 0.98:
                        relationship = 'SAME_AS'
                    elif from_fraction > 0.95:
                        relationship = 'WITHIN'  # CD_from is within CD_to
                    elif to_fraction > 0.95:
                        relationship = 'CONTAINS'  # CD_from contains CD_to
                    else:
                        relationship = 'OVERLAPS'

                    links.append({
                        'cd_from': cd_from,
                        'cd_to': cd_to,
                        'relationship': relationship,
                        'iou': round(iou, 4),
                        'from_fraction': round(from_fraction, 4),
                        'to_fraction': round(to_fraction, 4),
                        'overlap_sqm': round(overlap_area, 2)
                    })

    links_df = pd.DataFrame(links)
    print(f"  Found {len(links_df)} spatial overlaps", file=sys.stderr)
    return links_df


def classify_links(links_df: pd.DataFrame, gdf_from: gpd.GeoDataFrame, gdf_to: gpd.GeoDataFrame) -> tuple:
    """Classify links into high-confidence and ambiguous."""

    if len(links_df) == 0:
        return pd.DataFrame(), pd.DataFrame()

    # High-confidence: SAME_AS with name match, WITHIN, CONTAINS
    high_confidence = links_df[
        ((links_df['relationship'] == 'SAME_AS')) |
        (links_df['relationship'] == 'WITHIN') |
        (links_df['relationship'] == 'CONTAINS')
    ].copy()

    # Ambiguous: SAME_AS with name mismatch, OVERLAPS
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
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True, parents=True)

    # Load both years
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Linking CDs: {args.year_from} → {args.year_to}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    gdf_from = load_cd_layer(args.gdb, args.year_from)
    gdf_to = load_cd_layer(args.gdb, args.year_to)

    # Compute overlaps
    links_df = compute_overlap(gdf_from, gdf_to)

    # Classify
    high_conf, ambiguous = classify_links(links_df, gdf_from, gdf_to)

    # Write outputs
    year_pair = f"{args.year_from}_{args.year_to}"

    if len(high_conf) > 0:
        high_conf_file = out_dir / f'cd_links_{year_pair}.csv'
        high_conf.to_csv(high_conf_file, index=False)
        print(f"\n✓ High-confidence links: {len(high_conf)} → {high_conf_file}", file=sys.stderr)

    if len(ambiguous) > 0:
        ambiguous_file = out_dir / f'cd_ambiguous_{year_pair}.csv'
        ambiguous.to_csv(ambiguous_file, index=False)
        print(f"✓ Ambiguous links: {len(ambiguous)} → {ambiguous_file}", file=sys.stderr)

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
