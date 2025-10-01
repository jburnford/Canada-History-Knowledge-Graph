#!/usr/bin/env python3
"""
Build Neo4j data using CIDOC-CRM ontology for Canadian Census Subdivisions.

CIDOC-CRM Model:
- E53_Place: Census Subdivision as abstract place concept
- E4_Period: Census enumeration period (year)
- E93_Presence: CSD's manifestation during a census period
- E94_Space_Primitive: Point geometry (centroid lat/lon)

Relationships:
- P7_took_place_at: Presence -> Place
- P164_is_temporally_specified_by: Presence -> Period
- P161_has_spatial_projection: Presence -> Space_Primitive
- P122_borders_with: Place -> Place (during specific period)
- P89_falls_within: CSD Place -> CD Place
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path
from shapely import make_valid
import argparse
import sys
from typing import Dict, List, Tuple


def load_year_layer(gdb_path: str, year: int) -> gpd.GeoDataFrame:
    """Load CSD layer for a specific year from FileGDB."""
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
        elif col in [f'Name_CSD_{year}', f'NAME_CSD_{year}']:
            rename_map[col] = 'csd_name'

    gdf = gdf.rename(columns=rename_map)
    cols_to_keep = ['tcpuid', 'pr', 'cd_name', 'csd_name', 'geometry']
    gdf = gdf[cols_to_keep]

    # Validate geometries
    invalid_mask = ~gdf.is_valid
    if invalid_mask.any():
        print(f"  Fixing {invalid_mask.sum()} invalid geometries...", file=sys.stderr)
        gdf.loc[invalid_mask, 'geometry'] = gdf.loc[invalid_mask, 'geometry'].apply(make_valid)

    # Reproject to EPSG:3347
    if gdf.crs is None or gdf.crs.to_epsg() != 3347:
        print(f"  Reprojecting to EPSG:3347...", file=sys.stderr)
        gdf = gdf.to_crs(epsg=3347)

    gdf['area'] = gdf.geometry.area
    print(f"  Loaded {len(gdf)} CSDs", file=sys.stderr)
    return gdf


def extract_e53_places(gdf: gpd.GeoDataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Extract E53_Place nodes for CSDs and CDs.

    Returns:
        (csd_places, cd_places)
    """
    print(f"  Extracting E53_Place nodes...", file=sys.stderr)

    # CSD Places - use tcpuid as unique identifier across all years
    csd_places = pd.DataFrame({
        'place_id:ID': gdf['tcpuid'],
        'place_type': 'CSD',
        'name': gdf['csd_name'],
        ':LABEL': 'E53_Place'
    }).drop_duplicates(subset=['place_id:ID'])

    # CD Places - extract unique CDs
    cd_data = gdf[['cd_name', 'pr']].drop_duplicates()
    cd_places = pd.DataFrame({
        'place_id:ID': 'CD_' + cd_data['pr'] + '_' + cd_data['cd_name'].str.replace(' ', '_'),
        'place_type': 'CD',
        'name': cd_data['cd_name'],
        'province': cd_data['pr'],
        ':LABEL': 'E53_Place'
    })

    return csd_places, cd_places


def extract_e4_periods(years: List[int]) -> pd.DataFrame:
    """
    Extract E4_Period nodes for census years.
    """
    print(f"  Creating E4_Period nodes...", file=sys.stderr)

    periods = pd.DataFrame({
        'period_id:ID': [f'CENSUS_{y}' for y in years],
        'year:int': years,
        'label': [f'{y} Canadian Census' for y in years],
        ':LABEL': 'E4_Period'
    })

    return periods


def extract_e93_presences(gdf: gpd.GeoDataFrame, year: int) -> pd.DataFrame:
    """
    Extract E93_Presence nodes - CSD manifestations during census year.
    """
    print(f"  Extracting E93_Presence nodes for {year}...", file=sys.stderr)

    presences = pd.DataFrame({
        'presence_id:ID': gdf['tcpuid'] + f'_{year}',
        'csd_tcpuid': gdf['tcpuid'],
        'census_year:int': year,
        'area_sqm:float': gdf['area'].round(2),
        ':LABEL': 'E93_Presence'
    })

    return presences


def extract_e94_space_primitives(gdf: gpd.GeoDataFrame, year: int) -> pd.DataFrame:
    """
    Extract E94_Space_Primitive nodes - centroid coordinates.
    """
    print(f"  Computing E94_Space_Primitive (centroids) for {year}...", file=sys.stderr)

    # Compute centroids in EPSG:3347, convert to WGS84
    centroids_3347 = gdf.geometry.centroid
    centroids_latlon = centroids_3347.to_crs(epsg=4326)

    space_primitives = pd.DataFrame({
        'space_id:ID': gdf['tcpuid'] + f'_{year}_centroid',
        'latitude:float': centroids_latlon.y.round(6),
        'longitude:float': centroids_latlon.x.round(6),
        'crs': 'EPSG:4326',
        ':LABEL': 'E94_Space_Primitive'
    })

    return space_primitives


def extract_p7_took_place_at(gdf: gpd.GeoDataFrame, year: int) -> pd.DataFrame:
    """
    P7_took_place_at: E93_Presence -> E53_Place (CSD)
    """
    print(f"  Creating P7_took_place_at relationships...", file=sys.stderr)

    relationships = pd.DataFrame({
        ':START_ID': gdf['tcpuid'] + f'_{year}',  # presence_id
        ':END_ID': gdf['tcpuid'],  # place_id (CSD)
        ':TYPE': 'P7_took_place_at'
    })

    return relationships


def extract_p164_temporally_specified_by(gdf: gpd.GeoDataFrame, year: int) -> pd.DataFrame:
    """
    P164_is_temporally_specified_by: E93_Presence -> E4_Period
    """
    print(f"  Creating P164_is_temporally_specified_by relationships...", file=sys.stderr)

    relationships = pd.DataFrame({
        ':START_ID': gdf['tcpuid'] + f'_{year}',  # presence_id
        ':END_ID': f'CENSUS_{year}',  # period_id
        ':TYPE': 'P164_is_temporally_specified_by'
    })

    return relationships


def extract_p161_spatial_projection(gdf: gpd.GeoDataFrame, year: int) -> pd.DataFrame:
    """
    P161_has_spatial_projection: E93_Presence -> E94_Space_Primitive
    """
    print(f"  Creating P161_has_spatial_projection relationships...", file=sys.stderr)

    relationships = pd.DataFrame({
        ':START_ID': gdf['tcpuid'] + f'_{year}',  # presence_id
        ':END_ID': gdf['tcpuid'] + f'_{year}_centroid',  # space_id
        ':TYPE': 'P161_has_spatial_projection'
    })

    return relationships


def extract_p89_falls_within(gdf: gpd.GeoDataFrame, year: int) -> pd.DataFrame:
    """
    P89_falls_within: E53_Place (CSD) -> E53_Place (CD)
    Time-scoped with during_period property to track changing CD membership.
    """
    print(f"  Creating P89_falls_within relationships for {year}...", file=sys.stderr)

    relationships = pd.DataFrame({
        ':START_ID': gdf['tcpuid'],  # CSD place_id
        ':END_ID': 'CD_' + gdf['pr'] + '_' + gdf['cd_name'].str.replace(' ', '_'),  # CD place_id
        'during_period': f'CENSUS_{year}',
        ':TYPE': 'P89_falls_within'
    }).drop_duplicates()

    return relationships


def extract_p122_borders_with(gdf: gpd.GeoDataFrame, year: int) -> pd.DataFrame:
    """
    P122_borders_with: E53_Place (CSD) -> E53_Place (CSD)
    With properties: during_period, shared_border_length_m
    """
    print(f"  Computing P122_borders_with relationships for {year}...", file=sys.stderr)

    borders = []
    sindex = gdf.sindex

    for idx, row in gdf.iterrows():
        geom = row['geometry']
        tcpuid = row['tcpuid']

        possible_neighbors = list(sindex.intersection(geom.bounds))

        for neighbor_idx in possible_neighbors:
            if neighbor_idx == idx:
                continue

            neighbor_row = gdf.iloc[neighbor_idx]
            neighbor_geom = neighbor_row['geometry']
            neighbor_tcpuid = neighbor_row['tcpuid']

            # Avoid duplicates (only A->B, not B->A)
            if tcpuid >= neighbor_tcpuid:
                continue

            if not geom.touches(neighbor_geom):
                continue

            try:
                intersection = geom.boundary.intersection(neighbor_geom.boundary)
                border_length = intersection.length

                if border_length > 1.0:
                    borders.append({
                        ':START_ID': tcpuid,
                        ':END_ID': neighbor_tcpuid,
                        'during_period': f'CENSUS_{year}',
                        'shared_border_length_m:float': round(border_length, 2),
                        ':TYPE': 'P122_borders_with'
                    })
            except Exception as e:
                print(f"  Warning: Border computation error: {e}", file=sys.stderr)
                continue

        if (idx + 1) % 500 == 0:
            print(f"    Processed {idx + 1}/{len(gdf)} CSDs...", file=sys.stderr)

    print(f"  Found {len(borders)} border relationships", file=sys.stderr)
    return pd.DataFrame(borders)


def process_year(gdb_path: str, year: int, out_dir: Path, all_csd_places: dict, all_cd_places: set):
    """
    Process a single census year.

    Returns:
        Stats dict with counts
    """
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Processing year {year}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    gdf = load_year_layer(gdb_path, year)

    stats = {}

    # E93_Presence nodes
    presences = extract_e93_presences(gdf, year)
    presences.to_csv(out_dir / f'e93_presence_{year}.csv', index=False)
    stats['presences'] = len(presences)
    print(f"✓ Wrote {len(presences)} E93_Presence nodes")

    # E94_Space_Primitive nodes
    space_primitives = extract_e94_space_primitives(gdf, year)
    space_primitives.to_csv(out_dir / f'e94_space_primitive_{year}.csv', index=False)
    stats['space_primitives'] = len(space_primitives)
    print(f"✓ Wrote {len(space_primitives)} E94_Space_Primitive nodes")

    # Collect unique places for later (keep most recent name for each TCPUID)
    for _, row in gdf[['tcpuid', 'csd_name']].iterrows():
        tcpuid = row['tcpuid']
        csd_name = row['csd_name']
        # Update with most recent year's name (processing in chronological order)
        all_csd_places[tcpuid] = csd_name

    for _, row in gdf[['cd_name', 'pr']].drop_duplicates().iterrows():
        cd_id = f"CD_{row['pr']}_{row['cd_name'].replace(' ', '_')}"
        all_cd_places.add((cd_id, row['cd_name'], row['pr']))

    # Relationships
    p7 = extract_p7_took_place_at(gdf, year)
    p7.to_csv(out_dir / f'p7_took_place_at_{year}.csv', index=False)
    stats['p7'] = len(p7)
    print(f"✓ Wrote {len(p7)} P7_took_place_at relationships")

    p164 = extract_p164_temporally_specified_by(gdf, year)
    p164.to_csv(out_dir / f'p164_temporally_specified_by_{year}.csv', index=False)
    stats['p164'] = len(p164)
    print(f"✓ Wrote {len(p164)} P164_is_temporally_specified_by relationships")

    p161 = extract_p161_spatial_projection(gdf, year)
    p161.to_csv(out_dir / f'p161_spatial_projection_{year}.csv', index=False)
    stats['p161'] = len(p161)
    print(f"✓ Wrote {len(p161)} P161_has_spatial_projection relationships")

    p89 = extract_p89_falls_within(gdf, year)
    p89.to_csv(out_dir / f'p89_falls_within_{year}.csv', index=False)
    stats['p89'] = len(p89)
    print(f"✓ Wrote {len(p89)} P89_falls_within relationships")

    p122 = extract_p122_borders_with(gdf, year)
    p122.to_csv(out_dir / f'p122_borders_with_{year}.csv', index=False)
    stats['p122'] = len(p122)
    print(f"✓ Wrote {len(p122)} P122_borders_with relationships")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Build Neo4j CIDOC-CRM data for Canadian Census Subdivisions"
    )
    parser.add_argument('--gdb', required=True, help='Path to TCP FileGDB')
    parser.add_argument(
        '--years',
        default='1851,1861,1871,1881,1891,1901,1911,1921',
        help='Comma-separated census years'
    )
    parser.add_argument('--out', default='neo4j_cidoc_crm', help='Output directory')

    args = parser.parse_args()

    years = [int(y.strip()) for y in args.years.split(',')]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Create E4_Period nodes
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Creating E4_Period nodes", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    periods = extract_e4_periods(years)
    periods.to_csv(out_dir / 'e4_period.csv', index=False)
    print(f"✓ Wrote {len(periods)} E4_Period nodes")

    # Process each year
    all_csd_places = {}  # dict: tcpuid -> name (most recent)
    all_cd_places = set()
    total_stats = {
        'presences': 0,
        'space_primitives': 0,
        'p7': 0,
        'p164': 0,
        'p161': 0,
        'p89': 0,
        'p122': 0
    }

    for year in years:
        stats = process_year(args.gdb, year, out_dir, all_csd_places, all_cd_places)
        for key in total_stats:
            total_stats[key] += stats[key]

    # Create E53_Place nodes (after collecting all unique places)
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Creating E53_Place nodes", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # CSD Places (with names from most recent year)
    csd_places_df = pd.DataFrame([
        {'place_id:ID': tcpuid, 'name': name, 'place_type': 'CSD', ':LABEL': 'E53_Place'}
        for tcpuid, name in all_csd_places.items()
    ])
    csd_places_df.to_csv(out_dir / 'e53_place_csd.csv', index=False)
    print(f"✓ Wrote {len(csd_places_df)} E53_Place (CSD) nodes")

    # CD Places
    cd_places_df = pd.DataFrame([
        {'place_id:ID': cd_id, 'place_type': 'CD', 'name': name, 'province': prov, ':LABEL': 'E53_Place'}
        for cd_id, name, prov in all_cd_places
    ])
    cd_places_df.to_csv(out_dir / 'e53_place_cd.csv', index=False)
    print(f"✓ Wrote {len(cd_places_df)} E53_Place (CD) nodes")

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"E53_Place (CSD): {len(csd_places_df):,}", file=sys.stderr)
    print(f"E53_Place (CD): {len(cd_places_df):,}", file=sys.stderr)
    print(f"E4_Period: {len(periods):,}", file=sys.stderr)
    print(f"E93_Presence: {total_stats['presences']:,}", file=sys.stderr)
    print(f"E94_Space_Primitive: {total_stats['space_primitives']:,}", file=sys.stderr)
    print(f"\nRelationships:", file=sys.stderr)
    print(f"P7_took_place_at: {total_stats['p7']:,}", file=sys.stderr)
    print(f"P164_is_temporally_specified_by: {total_stats['p164']:,}", file=sys.stderr)
    print(f"P161_has_spatial_projection: {total_stats['p161']:,}", file=sys.stderr)
    print(f"P89_falls_within: {total_stats['p89']:,}", file=sys.stderr)
    print(f"P122_borders_with: {total_stats['p122']:,}", file=sys.stderr)
    print(f"\n✓ Output files in {out_dir}/", file=sys.stderr)


if __name__ == '__main__':
    main()