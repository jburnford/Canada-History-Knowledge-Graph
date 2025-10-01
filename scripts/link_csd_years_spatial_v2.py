#!/usr/bin/env python3
"""
Link Census Subdivisions (CSDs) across years using spatial overlap analysis.

Compares polygon geometries between consecutive census years to identify:
- SAME_AS: High spatial overlap (IoU > 0.98)
- WITHIN: CSD contained within another (e.g., city split from larger area)
- CONTAINS: CSD contains others (e.g., amalgamation)
- OVERLAPS: Partial overlap (boundary changes, splits, merges)

Uses only GDB polygon layers - no Excel files needed.
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path
from shapely.geometry import Polygon, MultiPolygon
from shapely import make_valid
from rapidfuzz import fuzz
import argparse
import sys
from typing import Tuple, List, Dict


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

    # Calculate areas
    gdf['area'] = gdf.geometry.area

    print(f"  Loaded {len(gdf)} CSDs", file=sys.stderr)
    return gdf


def compute_name_similarity(name1: str, name2: str, cd1: str, cd2: str) -> float:
    """
    Compute name similarity score (0-100) considering CSD and CD names.
    Handles None/NaN values gracefully.
    """
    # Handle missing values
    name1 = str(name1) if pd.notna(name1) else ""
    name2 = str(name2) if pd.notna(name2) else ""
    cd1 = str(cd1) if pd.notna(cd1) else ""
    cd2 = str(cd2) if pd.notna(cd2) else ""

    # Normalize: lowercase, strip whitespace
    name1 = name1.lower().strip()
    name2 = name2.lower().strip()
    cd1 = cd1.lower().strip()
    cd2 = cd2.lower().strip()

    # CSD name similarity (weighted 70%)
    csd_sim = fuzz.ratio(name1, name2)

    # CD name similarity (weighted 30%)
    cd_sim = fuzz.ratio(cd1, cd2)

    # Combined score
    return 0.7 * csd_sim + 0.3 * cd_sim


def analyze_overlap(
    geom1: Polygon,
    geom2: Polygon,
    area1: float,
    area2: float
) -> Tuple[float, float, float]:
    """
    Compute spatial overlap metrics between two polygons.

    Returns:
        (iou, frac1, frac2) where:
        - iou: Intersection over Union
        - frac1: Fraction of geom1 covered by intersection
        - frac2: Fraction of geom2 covered by intersection
    """
    try:
        intersection = geom1.intersection(geom2)
        inter_area = intersection.area

        if inter_area == 0:
            return 0.0, 0.0, 0.0

        union_area = geom1.union(geom2).area
        iou = inter_area / union_area if union_area > 0 else 0.0

        frac1 = inter_area / area1 if area1 > 0 else 0.0
        frac2 = inter_area / area2 if area2 > 0 else 0.0

        return iou, frac1, frac2

    except Exception as e:
        print(f"Warning: Geometry error - {e}", file=sys.stderr)
        return 0.0, 0.0, 0.0


def classify_relationship(
    iou: float,
    frac_from: float,
    frac_to: float,
    name_sim: float,
    iou_same_thresh: float = 0.98,
    frac_same_thresh: float = 0.98,
    iou_overlap_thresh: float = 0.30
) -> str:
    """
    Classify the relationship between two CSDs based on spatial overlap.

    Returns one of: SAME_AS, WITHIN, CONTAINS, OVERLAPS, or None
    """
    # High IoU + high coverage = same CSD
    if iou >= iou_same_thresh and min(frac_from, frac_to) >= frac_same_thresh:
        return "SAME_AS"

    # From CSD is mostly within To CSD (e.g., city split from larger area)
    if frac_from >= 0.95 and frac_to < 0.95:
        return "WITHIN"

    # To CSD is mostly within From CSD (e.g., smaller CSD absorbed)
    if frac_to >= 0.95 and frac_from < 0.95:
        return "CONTAINS"

    # Significant overlap but not containment
    if iou >= iou_overlap_thresh or max(frac_from, frac_to) >= 0.50:
        return "OVERLAPS"

    return None


def link_year_pair(
    gdf_from: gpd.GeoDataFrame,
    gdf_to: gpd.GeoDataFrame,
    year_from: int,
    year_to: int,
    iou_same: float = 0.98,
    frac_same: float = 0.98,
    iou_overlap: float = 0.30,
    name_sim_thresh: float = 80.0
) -> Tuple[List[Dict], List[Dict]]:
    """
    Link CSDs between two years using spatial overlap.

    Returns:
        (high_confidence_links, ambiguous_links)
    """
    print(f"\nLinking {year_from} → {year_to}", file=sys.stderr)
    print(f"  From: {len(gdf_from)} CSDs", file=sys.stderr)
    print(f"  To:   {len(gdf_to)} CSDs", file=sys.stderr)

    # Create spatial index for efficient lookups
    print("  Building spatial index...", file=sys.stderr)
    sindex = gdf_to.sindex

    high_confidence = []
    ambiguous = []

    # Process each FROM CSD
    print("  Computing overlaps...", file=sys.stderr)
    for from_idx, from_row in gdf_from.iterrows():
        from_geom = from_row['geometry']
        from_area = from_row['area']

        # Find potential overlaps using spatial index
        possible_matches_idx = list(sindex.intersection(from_geom.bounds))

        if not possible_matches_idx:
            continue

        # Check actual overlaps
        for to_idx in possible_matches_idx:
            to_row = gdf_to.iloc[to_idx]
            to_geom = to_row['geometry']
            to_area = to_row['area']

            # Quick test: do they actually intersect?
            if not from_geom.intersects(to_geom):
                continue

            # Compute spatial overlap
            iou, frac_from, frac_to = analyze_overlap(from_geom, to_geom, from_area, to_area)

            # Compute name similarity
            name_sim = compute_name_similarity(
                from_row['csd_name'],
                to_row['csd_name'],
                from_row['cd_name'],
                to_row['cd_name']
            )

            # Classify relationship
            rel_type = classify_relationship(iou, frac_from, frac_to, name_sim, iou_same, frac_same, iou_overlap)

            if rel_type is None:
                continue

            # Build link record
            link = {
                f'tcpuid_{year_from}': from_row['tcpuid'],
                f'csd_name_{year_from}': from_row['csd_name'],
                f'cd_name_{year_from}': from_row['cd_name'],
                f'pr_{year_from}': from_row['pr'],
                f'tcpuid_{year_to}': to_row['tcpuid'],
                f'csd_name_{year_to}': to_row['csd_name'],
                f'cd_name_{year_to}': to_row['cd_name'],
                f'pr_{year_to}': to_row['pr'],
                'relationship': rel_type,
                'iou': round(iou, 4),
                'frac_from': round(frac_from, 4),
                'frac_to': round(frac_to, 4),
                'name_similarity': round(name_sim, 2)
            }

            # Classify as high-confidence or ambiguous
            if rel_type == "SAME_AS" and name_sim >= name_sim_thresh:
                high_confidence.append(link)
            elif rel_type == "SAME_AS" and name_sim >= 60:
                # Spatial match good but name mismatch (OCR errors?)
                ambiguous.append(link)
            elif rel_type in ["WITHIN", "CONTAINS"]:
                high_confidence.append(link)
            elif rel_type == "OVERLAPS":
                ambiguous.append(link)

        # Progress indicator
        if (from_idx + 1) % 500 == 0:
            print(f"  Processed {from_idx + 1}/{len(gdf_from)} CSDs...", file=sys.stderr)

    print(f"  High confidence: {len(high_confidence)}", file=sys.stderr)
    print(f"  Ambiguous: {len(ambiguous)}", file=sys.stderr)

    return high_confidence, ambiguous


def main():
    parser = argparse.ArgumentParser(
        description="Link CSDs across years using spatial overlap analysis"
    )
    parser.add_argument(
        '--gdb',
        required=True,
        help='Path to TCP FileGDB'
    )
    parser.add_argument(
        '--year-from',
        type=int,
        required=True,
        help='Starting census year'
    )
    parser.add_argument(
        '--year-to',
        type=int,
        required=True,
        help='Ending census year'
    )
    parser.add_argument(
        '--out',
        default='output',
        help='Output directory'
    )
    parser.add_argument(
        '--iou-same',
        type=float,
        default=0.98,
        help='IoU threshold for SAME_AS classification (default: 0.98)'
    )
    parser.add_argument(
        '--frac-same',
        type=float,
        default=0.98,
        help='Coverage threshold for SAME_AS classification (default: 0.98)'
    )
    parser.add_argument(
        '--iou-overlap',
        type=float,
        default=0.30,
        help='IoU threshold for OVERLAPS classification (default: 0.30)'
    )
    parser.add_argument(
        '--name-sim-thresh',
        type=float,
        default=80.0,
        help='Name similarity threshold for high-confidence SAME_AS (default: 80.0)'
    )

    args = parser.parse_args()

    # Create output directory
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load year layers
    gdf_from = load_year_layer(args.gdb, args.year_from)
    gdf_to = load_year_layer(args.gdb, args.year_to)

    # Compute links
    high_conf, ambiguous = link_year_pair(
        gdf_from,
        gdf_to,
        args.year_from,
        args.year_to,
        args.iou_same,
        args.frac_same,
        args.iou_overlap,
        args.name_sim_thresh
    )

    # Save results
    high_conf_file = out_dir / f"year_links_{args.year_from}_{args.year_to}.csv"
    ambiguous_file = out_dir / f"ambiguous_{args.year_from}_{args.year_to}.csv"
    summary_file = out_dir / f"summary_{args.year_from}_{args.year_to}.txt"

    if high_conf:
        pd.DataFrame(high_conf).to_csv(high_conf_file, index=False)
        print(f"\nWrote {len(high_conf)} high-confidence links to {high_conf_file}")

    if ambiguous:
        pd.DataFrame(ambiguous).to_csv(ambiguous_file, index=False)
        print(f"Wrote {len(ambiguous)} ambiguous links to {ambiguous_file}")

    # Write summary
    with open(summary_file, 'w') as f:
        f.write(f"CSD Linkage Summary: {args.year_from} → {args.year_to}\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Input CSDs ({args.year_from}): {len(gdf_from)}\n")
        f.write(f"Input CSDs ({args.year_to}): {len(gdf_to)}\n\n")
        f.write(f"High-confidence links: {len(high_conf)}\n")
        f.write(f"Ambiguous links: {len(ambiguous)}\n\n")

        # Breakdown by relationship type
        if high_conf:
            rel_counts = pd.DataFrame(high_conf)['relationship'].value_counts()
            f.write("High-confidence breakdown:\n")
            for rel, count in rel_counts.items():
                f.write(f"  {rel}: {count}\n")

        if ambiguous:
            f.write("\nAmbiguous breakdown:\n")
            rel_counts = pd.DataFrame(ambiguous)['relationship'].value_counts()
            for rel, count in rel_counts.items():
                f.write(f"  {rel}: {count}\n")

    print(f"Wrote summary to {summary_file}\n")


if __name__ == '__main__':
    main()