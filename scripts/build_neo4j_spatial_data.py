#!/usr/bin/env python3
"""
Build Neo4j spatial data: CSD nodes with centroids + BORDERS relationships.

Extracts for each census year:
1. CSD nodes: tcpuid, name, cd_name, province, year, area, centroid (lat/lon)
2. BORDERS relationships: adjacency + shared border length

Output: CSV files ready for Neo4j LOAD CSV
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path
from shapely import make_valid
import argparse
import sys
from typing import Tuple


def load_year_layer(gdb_path: str, year: int) -> gpd.GeoDataFrame:
    """Load CSD layer for a specific year from FileGDB."""
    layer_name = f"CANADA_{year}_CSD"
    print(f"Loading {layer_name}...", file=sys.stderr)

    gdf = gpd.read_file(gdb_path, layer=layer_name)

    # Standardize column names (handle both Name_ and NAME_ variants)
    rename_map = {}
    for col in gdf.columns:
        if col == f'TCPUID_CSD_{year}':
            rename_map[col] = 'tcpuid'
        elif col == f'PR_{year}':
            rename_map[col] = 'pr'
        elif col in [f'Name_CD_{year}', f'NAME_CD_{year}']:
            rename_map[col] = 'cd_name'
        elif col in [f'Name_CSD_{year}', f'NAME_CSD_{year}']:
            rename_map[col] = 'csd_name'

    gdf = gdf.rename(columns=rename_map)

    # Keep only needed columns
    cols_to_keep = ['tcpuid', 'pr', 'cd_name', 'csd_name', 'geometry']
    gdf = gdf[cols_to_keep]

    # Validate geometries
    invalid_mask = ~gdf.is_valid
    if invalid_mask.any():
        print(f"  Fixing {invalid_mask.sum()} invalid geometries...", file=sys.stderr)
        gdf.loc[invalid_mask, 'geometry'] = gdf.loc[invalid_mask, 'geometry'].apply(make_valid)

    # Reproject to EPSG:3347 for accurate area calculations
    if gdf.crs is None or gdf.crs.to_epsg() != 3347:
        print(f"  Reprojecting to EPSG:3347...", file=sys.stderr)
        gdf = gdf.to_crs(epsg=3347)

    # Calculate areas (in square meters)
    gdf['area'] = gdf.geometry.area

    print(f"  Loaded {len(gdf)} CSDs", file=sys.stderr)
    return gdf


def extract_csd_nodes(gdf: gpd.GeoDataFrame, year: int) -> pd.DataFrame:
    """
    Extract CSD node data with centroids in lat/lon.

    Returns DataFrame with columns:
    - tcpuid:ID
    - name
    - cd_name
    - province
    - year:int
    - area_sqm:float
    - centroid_lat:float
    - centroid_lon:float
    """
    print(f"  Computing centroids...", file=sys.stderr)

    # Compute centroids in projected CRS (EPSG:3347)
    centroids_3347 = gdf.geometry.centroid

    # Convert centroids to lat/lon (EPSG:4326 - WGS84)
    centroids_latlon = centroids_3347.to_crs(epsg=4326)

    # Build node dataframe
    nodes = pd.DataFrame({
        'tcpuid:ID': gdf['tcpuid'],
        'name': gdf['csd_name'],
        'cd_name': gdf['cd_name'],
        'province': gdf['pr'],
        'year:int': year,
        'area_sqm:float': gdf['area'].round(2),
        'centroid_lat:float': centroids_latlon.y.round(6),
        'centroid_lon:float': centroids_latlon.x.round(6)
    })

    return nodes


def compute_borders(gdf: gpd.GeoDataFrame, year: int) -> pd.DataFrame:
    """
    Compute BORDERS relationships between adjacent CSDs.

    Returns DataFrame with columns:
    - :START_ID (tcpuid)
    - :END_ID (tcpuid)
    - year:int
    - shared_border_length_m:float
    """
    print(f"  Computing border adjacencies...", file=sys.stderr)

    borders = []

    # Use spatial index for efficiency
    sindex = gdf.sindex

    for idx, row in gdf.iterrows():
        geom = row['geometry']
        tcpuid = row['tcpuid']

        # Find potential neighbors using bounding box
        possible_neighbors = list(sindex.intersection(geom.bounds))

        for neighbor_idx in possible_neighbors:
            # Skip self
            if neighbor_idx == idx:
                continue

            neighbor_row = gdf.iloc[neighbor_idx]
            neighbor_geom = neighbor_row['geometry']
            neighbor_tcpuid = neighbor_row['tcpuid']

            # Avoid duplicate pairs (only add A->B, not B->A)
            # Use string comparison to maintain consistent ordering
            if tcpuid >= neighbor_tcpuid:
                continue

            # Check if they actually touch (share a border)
            if not geom.touches(neighbor_geom):
                continue

            # Compute shared border length
            try:
                intersection = geom.boundary.intersection(neighbor_geom.boundary)
                border_length = intersection.length

                # Only add if there's meaningful shared border (> 1m)
                if border_length > 1.0:
                    borders.append({
                        ':START_ID': tcpuid,
                        ':END_ID': neighbor_tcpuid,
                        'year:int': year,
                        'shared_border_length_m:float': round(border_length, 2)
                    })
            except Exception as e:
                print(f"  Warning: Border computation error between {tcpuid} and {neighbor_tcpuid}: {e}",
                      file=sys.stderr)
                continue

        # Progress indicator
        if (idx + 1) % 500 == 0:
            print(f"    Processed {idx + 1}/{len(gdf)} CSDs...", file=sys.stderr)

    print(f"  Found {len(borders)} border relationships", file=sys.stderr)

    return pd.DataFrame(borders)


def process_year(gdb_path: str, year: int, out_dir: Path):
    """Process a single census year: extract nodes and borders."""
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Processing year {year}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # Load data
    gdf = load_year_layer(gdb_path, year)

    # Extract CSD nodes
    print(f"\nExtracting CSD nodes for {year}...", file=sys.stderr)
    nodes = extract_csd_nodes(gdf, year)
    nodes_file = out_dir / f"csd_nodes_{year}.csv"
    nodes.to_csv(nodes_file, index=False)
    print(f"  Wrote {len(nodes)} nodes to {nodes_file}")

    # Compute borders
    print(f"\nComputing BORDERS relationships for {year}...", file=sys.stderr)
    borders = compute_borders(gdf, year)
    borders_file = out_dir / f"csd_borders_{year}.csv"
    borders.to_csv(borders_file, index=False)
    print(f"  Wrote {len(borders)} borders to {borders_file}")

    return len(nodes), len(borders)


def main():
    parser = argparse.ArgumentParser(
        description="Build Neo4j spatial data: CSD nodes + BORDERS relationships"
    )
    parser.add_argument(
        '--gdb',
        required=True,
        help='Path to TCP FileGDB'
    )
    parser.add_argument(
        '--years',
        default='1851,1861,1871,1881,1891,1901,1911,1921',
        help='Comma-separated list of census years (default: all)'
    )
    parser.add_argument(
        '--out',
        default='neo4j_import',
        help='Output directory for CSV files'
    )

    args = parser.parse_args()

    # Parse years
    years = [int(y.strip()) for y in args.years.split(',')]

    # Create output directory
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Process each year
    total_nodes = 0
    total_borders = 0

    for year in years:
        nodes_count, borders_count = process_year(args.gdb, year, out_dir)
        total_nodes += nodes_count
        total_borders += borders_count

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"Total nodes: {total_nodes:,}", file=sys.stderr)
    print(f"Total borders: {total_borders:,}", file=sys.stderr)
    print(f"\nOutput files in {out_dir}/:", file=sys.stderr)
    print(f"  csd_nodes_YYYY.csv - Node data with centroids", file=sys.stderr)
    print(f"  csd_borders_YYYY.csv - BORDERS relationships", file=sys.stderr)


if __name__ == '__main__':
    main()