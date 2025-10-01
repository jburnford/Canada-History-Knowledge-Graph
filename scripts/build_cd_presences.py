#!/usr/bin/env python3
"""
Generate E93_Presence nodes for Census Divisions with P132 temporal overlap relationships.

Creates CD-year presences parallel to CSD presences, enabling:
- CD temporal evolution tracking (1851-1921)
- Administrative hierarchy queries (CSD within CD by year)
- P132_spatiotemporally_overlaps_with relationships for CDs

Author: Claude Code
Date: October 1, 2025
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path
import argparse
import sys
from typing import List, Dict, Set, Tuple


def load_gdb_cd_layer(gdb_path: str, year: int) -> gpd.GeoDataFrame:
    """
    Load Census Division layer from GDB for a specific year.

    CDs are aggregated from CSDs, so we need to extract unique CD geometries
    from the CSD layer by dissolving on CD identifiers.
    """
    print(f"  Loading GDB layer for {year}...", file=sys.stderr)

    # Load CSD layer
    layer_name = f'CANADA_{year}_CSD'
    gdf = gpd.read_file(gdb_path, layer=layer_name)

    # Standardize column names (columns have year suffixes like Name_CD_1851)
    cd_col = [col for col in gdf.columns if 'NAME_CD' in col.upper() and 'CSD' not in col.upper()][0]
    pr_col = [col for col in gdf.columns if col.startswith('PR') or col.startswith('pr')][0]

    gdf = gdf.rename(columns={cd_col: 'cd_name', pr_col: 'pr'})

    # Check required columns
    required = ['cd_name', 'pr', 'geometry']
    missing = [col for col in required if col not in gdf.columns]
    if missing:
        raise ValueError(f"Missing columns in {year}: {missing}")

    # Fix invalid geometries before dissolving
    gdf['geometry'] = gdf['geometry'].buffer(0)

    # Dissolve CSDs to create CD polygons
    print(f"  Dissolving {len(gdf)} CSDs into CD polygons...", file=sys.stderr)
    try:
        cd_gdf = gdf.dissolve(by=['cd_name', 'pr'], as_index=False)
    except Exception as e:
        print(f"  Warning: Dissolve failed, trying with make_valid...", file=sys.stderr)
        gdf['geometry'] = gdf['geometry'].make_valid()
        cd_gdf = gdf.dissolve(by=['cd_name', 'pr'], as_index=False)

    # Calculate area in square meters (use projected CRS for accuracy)
    cd_gdf_proj = cd_gdf.to_crs('EPSG:3347')  # Statistics Canada Lambert
    cd_gdf['area'] = cd_gdf_proj.geometry.area

    # Calculate centroids (in WGS84 for lat/lon)
    cd_gdf_wgs84 = cd_gdf.to_crs('EPSG:4326')
    centroids = cd_gdf_wgs84.geometry.centroid
    cd_gdf['centroid_lat'] = centroids.y
    cd_gdf['centroid_lon'] = centroids.x

    # Count CSDs per CD
    csd_counts = gdf.groupby(['cd_name', 'pr']).size().reset_index(name='num_csds')
    cd_gdf = cd_gdf.merge(csd_counts, on=['cd_name', 'pr'])

    # Create CD identifier (matches E53_Place ID format)
    cd_gdf['cd_id'] = 'CD_' + cd_gdf['pr'] + '_' + cd_gdf['cd_name'].str.replace(' ', '_')

    print(f"  ✓ Found {len(cd_gdf)} unique CDs", file=sys.stderr)
    return cd_gdf


def extract_e93_cd_presences(gdf: gpd.GeoDataFrame, year: int) -> pd.DataFrame:
    """
    Extract E93_Presence nodes for CD-year combinations.
    """
    print(f"  Creating E93_Presence (CD) nodes for {year}...", file=sys.stderr)

    presences = pd.DataFrame({
        'presence_id:ID': gdf['cd_id'] + f'_{year}',
        'cd_id': gdf['cd_id'],
        'census_year:int': year,
        'area_sqm:float': gdf['area'].round(2),
        'num_csds:int': gdf['num_csds'],
        ':LABEL': 'E93_Presence'
    })

    return presences


def extract_e94_cd_space_primitives(gdf: gpd.GeoDataFrame, year: int) -> pd.DataFrame:
    """
    Extract E94_Space_Primitive nodes for CD centroids.
    """
    print(f"  Creating E94_Space_Primitive (CD) nodes for {year}...", file=sys.stderr)

    space_primitives = pd.DataFrame({
        'space_id:ID': gdf['cd_id'] + f'_{year}_SPACE',
        'latitude:float': gdf['centroid_lat'].round(6),
        'longitude:float': gdf['centroid_lon'].round(6),
        'crs': 'EPSG:4326',
        ':LABEL': 'E94_Space_Primitive'
    })

    return space_primitives


def extract_p166_cd_was_presence_of(gdf: gpd.GeoDataFrame, year: int) -> pd.DataFrame:
    """
    P166_was_a_presence_of: E93_Presence (CD) -> E53_Place (CD)
    """
    print(f"  Creating P166_was_a_presence_of (CD) relationships...", file=sys.stderr)

    relationships = pd.DataFrame({
        ':START_ID': gdf['cd_id'] + f'_{year}',  # presence_id
        ':END_ID': gdf['cd_id'],  # place_id (CD)
        ':TYPE': 'P166_was_a_presence_of'
    })

    return relationships


def extract_p164_cd_temporally_specified_by(gdf: gpd.GeoDataFrame, year: int) -> pd.DataFrame:
    """
    P164_is_temporally_specified_by: E93_Presence (CD) -> E4_Period
    """
    print(f"  Creating P164_is_temporally_specified_by (CD) relationships...", file=sys.stderr)

    relationships = pd.DataFrame({
        ':START_ID': gdf['cd_id'] + f'_{year}',
        ':END_ID': f'CENSUS_{year}',
        ':TYPE': 'P164_is_temporally_specified_by'
    })

    return relationships


def extract_p161_cd_spatial_projection(gdf: gpd.GeoDataFrame, year: int) -> pd.DataFrame:
    """
    P161_has_spatial_projection: E93_Presence (CD) -> E94_Space_Primitive
    """
    print(f"  Creating P161_has_spatial_projection (CD) relationships...", file=sys.stderr)

    relationships = pd.DataFrame({
        ':START_ID': gdf['cd_id'] + f'_{year}',
        ':END_ID': gdf['cd_id'] + f'_{year}_SPACE',
        ':TYPE': 'P161_has_spatial_projection'
    })

    return relationships


def extract_p10_csd_within_cd(csd_gdf: gpd.GeoDataFrame, cd_gdf: gpd.GeoDataFrame, year: int) -> pd.DataFrame:
    """
    P10_falls_within: E93_Presence (CSD) -> E93_Presence (CD)

    This creates temporal administrative hierarchy linking CSD presences to CD presences.
    """
    print(f"  Creating P10_falls_within (CSD presence → CD presence) relationships...", file=sys.stderr)

    # Add CD identifiers to CSD dataframe
    csd_gdf = csd_gdf.copy()
    csd_gdf['cd_id'] = 'CD_' + csd_gdf['pr'] + '_' + csd_gdf['cd_name'].str.replace(' ', '_')

    relationships = pd.DataFrame({
        ':START_ID': csd_gdf['tcpuid'] + f'_{year}',  # CSD presence
        ':END_ID': csd_gdf['cd_id'] + f'_{year}',  # CD presence
        'during_period': f'CENSUS_{year}',
        ':TYPE': 'P10_falls_within'
    })

    return relationships


def load_cd_temporal_links(links_dir: Path) -> pd.DataFrame:
    """
    Load CD temporal links from cd_links_output directory.
    """
    all_links = []

    year_pairs = [
        (1851, 1861), (1861, 1871), (1871, 1881),
        (1881, 1891), (1891, 1901), (1901, 1911),
        (1911, 1921)
    ]

    for year_from, year_to in year_pairs:
        link_file = links_dir / f'cd_links_{year_from}_{year_to}.csv'
        if link_file.exists():
            print(f"  Loading {link_file.name}...", file=sys.stderr)
            df = pd.read_csv(link_file)

            # Filter for high-confidence links
            suitable = df[df['relationship'].isin(['SAME_AS', 'CONTAINS', 'WITHIN'])].copy()

            for _, row in suitable.iterrows():
                all_links.append({
                    ':START_ID': row['cd_from'] + f'_{year_from}',
                    ':END_ID': row['cd_to'] + f'_{year_to}',
                    'overlap_type': row['relationship'],
                    'iou:float': row['iou'],
                    'from_fraction:float': row['from_fraction'],
                    'to_fraction:float': row['to_fraction'],
                    'year_from:int': year_from,
                    'year_to:int': year_to,
                    ':TYPE': 'P132_spatiotemporally_overlaps_with'
                })

    return pd.DataFrame(all_links)


def process_year(gdb_path: str, year: int, out_dir: Path) -> Tuple[gpd.GeoDataFrame, Dict[str, int]]:
    """
    Process a single census year for CD presences.
    """
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Processing {year}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # Load CD geometries
    cd_gdf = load_gdb_cd_layer(gdb_path, year)

    # Also load CSD layer for P10 relationships
    layer_name = f'CANADA_{year}_CSD'
    csd_gdf = gpd.read_file(gdb_path, layer=layer_name)

    # Standardize CSD column names (columns have year suffixes like Name_CD_1851)
    cd_col = [col for col in csd_gdf.columns if 'NAME_CD' in col.upper() and 'CSD' not in col.upper()][0]
    pr_col = [col for col in csd_gdf.columns if col.startswith('PR') or col.startswith('pr')][0]

    csd_gdf = csd_gdf.rename(columns={cd_col: 'cd_name', pr_col: 'pr'})

    # Get TCPUID column name (varies by year)
    tcpuid_col = [col for col in csd_gdf.columns if 'TCPUID' in col.upper()][0]
    csd_gdf['tcpuid'] = csd_gdf[tcpuid_col]

    # Extract nodes
    presences = extract_e93_cd_presences(cd_gdf, year)
    space_prims = extract_e94_cd_space_primitives(cd_gdf, year)

    # Extract relationships
    p166 = extract_p166_cd_was_presence_of(cd_gdf, year)
    p164 = extract_p164_cd_temporally_specified_by(cd_gdf, year)
    p161 = extract_p161_cd_spatial_projection(cd_gdf, year)
    p10 = extract_p10_csd_within_cd(csd_gdf, cd_gdf, year)

    # Write files
    presences.to_csv(out_dir / f'e93_presence_cd_{year}.csv', index=False)
    space_prims.to_csv(out_dir / f'e94_space_primitive_cd_{year}.csv', index=False)
    p166.to_csv(out_dir / f'p166_was_presence_of_cd_{year}.csv', index=False)
    p164.to_csv(out_dir / f'p164_temporally_specified_by_cd_{year}.csv', index=False)
    p161.to_csv(out_dir / f'p161_spatial_projection_cd_{year}.csv', index=False)
    p10.to_csv(out_dir / f'p10_csd_within_cd_presence_{year}.csv', index=False)

    print(f"\n✓ Wrote {len(presences)} E93_Presence (CD) nodes")
    print(f"✓ Wrote {len(space_prims)} E94_Space_Primitive (CD) nodes")
    print(f"✓ Wrote {len(p166)} P166 relationships")
    print(f"✓ Wrote {len(p164)} P164 relationships")
    print(f"✓ Wrote {len(p161)} P161 relationships")
    print(f"✓ Wrote {len(p10)} P10 relationships (CSD→CD presences)")

    stats = {
        'presences': len(presences),
        'space_primitives': len(space_prims),
        'p166': len(p166),
        'p164': len(p164),
        'p161': len(p161),
        'p10': len(p10)
    }

    return cd_gdf, stats


def main():
    parser = argparse.ArgumentParser(description='Generate CD E93_Presence nodes and relationships')
    parser.add_argument('--gdb', required=True, help='Path to TCP GDB file')
    parser.add_argument('--years', required=True, help='Comma-separated years (e.g., 1851,1861,1871)')
    parser.add_argument('--cd-links', default='cd_links_output', help='CD temporal links directory')
    parser.add_argument('--out', required=True, help='Output directory for CSV files')
    args = parser.parse_args()

    # Parse years
    years = [int(y.strip()) for y in args.years.split(',')]

    # Create output directory
    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True, parents=True)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"CD Presence Generation", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"GDB: {args.gdb}", file=sys.stderr)
    print(f"Years: {years}", file=sys.stderr)
    print(f"Output: {out_dir}/", file=sys.stderr)

    # Process each year
    total_stats = {
        'presences': 0,
        'space_primitives': 0,
        'p166': 0,
        'p164': 0,
        'p161': 0,
        'p10': 0
    }

    all_cd_ids = set()

    for year in years:
        cd_gdf, stats = process_year(args.gdb, year, out_dir)
        for key in total_stats:
            total_stats[key] += stats[key]
        all_cd_ids.update(cd_gdf['cd_id'].unique())

    # Load and export P132 temporal overlap relationships
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Processing CD temporal overlap relationships", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    links_dir = Path(args.cd_links)
    cd_temporal_links = load_cd_temporal_links(links_dir)

    if len(cd_temporal_links) > 0:
        cd_temporal_links.to_csv(out_dir / 'p132_spatiotemporally_overlaps_with_cd.csv', index=False)
        print(f"\n✓ CD P132 relationships: {len(cd_temporal_links)}", file=sys.stderr)

        # Summary by relationship type
        print(f"\n  CD P132 by type:", file=sys.stderr)
        for rel_type in ['SAME_AS', 'CONTAINS', 'WITHIN']:
            count = len(cd_temporal_links[cd_temporal_links['overlap_type'] == rel_type])
            if count > 0:
                print(f"    {rel_type}: {count}", file=sys.stderr)

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"Unique CDs across all years: {len(all_cd_ids)}", file=sys.stderr)
    print(f"E93_Presence (CD): {total_stats['presences']:,}", file=sys.stderr)
    print(f"E94_Space_Primitive (CD): {total_stats['space_primitives']:,}", file=sys.stderr)
    print(f"\nRelationships:", file=sys.stderr)
    print(f"P166_was_a_presence_of: {total_stats['p166']:,}", file=sys.stderr)
    print(f"P164_is_temporally_specified_by: {total_stats['p164']:,}", file=sys.stderr)
    print(f"P161_has_spatial_projection: {total_stats['p161']:,}", file=sys.stderr)
    print(f"P10_falls_within (CSD→CD presences): {total_stats['p10']:,}", file=sys.stderr)
    print(f"P132_spatiotemporally_overlaps_with (CD): {len(cd_temporal_links):,}", file=sys.stderr)
    print(f"\n✓ Output files in {out_dir}/", file=sys.stderr)


if __name__ == '__main__':
    main()
