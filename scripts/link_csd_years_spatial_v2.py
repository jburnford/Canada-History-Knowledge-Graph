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
from shapely.geometry import Polygon
from rapidfuzz import fuzz
import argparse
import sys
from typing import Tuple, List, Dict


def load_year_layer(gdb_path: str, year: int, crs="EPSG:3347") -> gpd.GeoDataFrame:
    """Load the base CSD layer using the shared audited preparation rules."""
    from _gis import load_csd_layer
    frame, audit = load_csd_layer(gdb_path, year, crs)
    print(f"Loaded {year}: {len(frame)} CSDs; {len(audit)} preparation actions", file=sys.stderr)
    return frame


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

        union_area = area1 + area2 - inter_area
        iou = inter_area / union_area if union_area > 0 else 0.0

        frac1 = inter_area / area1 if area1 > 0 else 0.0
        frac2 = inter_area / area2 if area2 > 0 else 0.0

        return iou, frac1, frac2

    except Exception as e:
        raise ValueError("Unable to calculate polygon overlap; no link output is safe") from e


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
    # Legacy SAME_AS means approximately equal mapped extent, not identity.
    if iou >= iou_same_thresh and min(frac_from, frac_to) >= frac_same_thresh:
        return "SAME_AS"

    # Earlier CSD is within later CSD: spatial evidence for expansion/merger.
    if frac_from >= 0.95 and frac_to < 0.95:
        return "WITHIN"

    # Later CSD is within earlier CSD: spatial evidence for contraction/split.
    if frac_to >= 0.95 and frac_from < 0.95:
        return "CONTAINS"

    # Significant overlap but not containment
    if iou >= iou_overlap_thresh or max(frac_from, frac_to) >= 0.50:
        return "OVERLAPS"

    return None


def all_link_records(gdf_from, gdf_to, year_from, year_to,
                     iou_same=.98, frac_same=.98, iou_overlap=.30):
    """Keep every positive spatial correspondence, before legacy filtering."""
    from _gis import overlap_table
    records = []
    for row in overlap_table(gdf_from, gdf_to).itertuples():
        a, b = gdf_from.iloc[row.from_index], gdf_to.iloc[row.to_index]
        name_sim = compute_name_similarity(a.csd_name, b.csd_name, a.cd_name, b.cd_name)
        relation = classify_relationship(row.iou, row.frac_from, row.frac_to,
                                         name_sim, iou_same, frac_same, iou_overlap)
        record = {}
        for year, item in [(year_from, a), (year_to, b)]:
            for field in ["tcpuid", "csd_name", "cd_name", "pr"]:
                record[f"{field}_{year}"] = item[field]
        record.update(relationship=relation or "LOW_OVERLAP", iou=row.iou,
                      frac_from=row.frac_from, frac_to=row.frac_to,
                      name_similarity=name_sim, overlap_sqm=row.overlap_sqm,
                      area_from_sqm=row.area_from_sqm, area_to_sqm=row.area_to_sqm,
                      area_crs=gdf_from.crs.to_string(),
                      evidence_kind="computed_polygon_intersection",
                      historical_succession_verified=False,
                      involves_no_data=(a.csd_name.upper() == "NO DATA" or b.csd_name.upper() == "NO DATA"))
        records.append(record)
    return records


def link_year_pair(gdf_from, gdf_to, year_from, year_to,
                   iou_same=.98, frac_same=.98, iou_overlap=.30,
                   name_sim_thresh=80., *, records=None):
    """Legacy candidate partitions; unfiltered evidence is written separately.

    SAME_AS is a legacy geometric category, not verified historical identity.
    """
    if records is None:
        records = all_link_records(gdf_from, gdf_to, year_from, year_to,
                                   iou_same, frac_same, iou_overlap)
    high_confidence, ambiguous = [], []
    for record in records:
        relation = record["relationship"]
        if relation == "LOW_OVERLAP":
            continue
        if relation in {"WITHIN", "CONTAINS"} or (
                relation == "SAME_AS" and record["name_similarity"] >= name_sim_thresh):
            high_confidence.append(record)
        else:
            ambiguous.append(record)
    print(f"Spatial candidates {year_from} → {year_to}: "
          f"{len(high_confidence)} strong, {len(ambiguous)} ambiguous, "
          f"{len(records)} total positive overlaps", file=sys.stderr)
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

    parser.add_argument('--crs', default='EPSG:3347',
                        help='Area CRS: EPSG:3347 for legacy comparison; ESRI:102001 for equal-area evidence')
    args = parser.parse_args()

    # Create output directory
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load year layers
    gdf_from = load_year_layer(args.gdb, args.year_from, args.crs)
    gdf_to = load_year_layer(args.gdb, args.year_to, args.crs)

    # Compute once, retaining the evidence below legacy classification thresholds.
    records = all_link_records(gdf_from, gdf_to, args.year_from, args.year_to,
                               args.iou_same, args.frac_same, args.iou_overlap)
    high_conf, ambiguous = link_year_pair(
        gdf_from,
        gdf_to,
        args.year_from,
        args.year_to,
        args.iou_same,
        args.frac_same,
        args.iou_overlap,
        args.name_sim_thresh,
        records=records,
    )

    # Save results
    high_conf_file = out_dir / f"year_links_{args.year_from}_{args.year_to}.csv"
    ambiguous_file = out_dir / f"ambiguous_{args.year_from}_{args.year_to}.csv"
    summary_file = out_dir / f"summary_{args.year_from}_{args.year_to}.txt"

    columns = [f"{field}_{year}" for year in [args.year_from, args.year_to]
               for field in ["tcpuid", "csd_name", "cd_name", "pr"]]
    columns += ["relationship", "iou", "frac_from", "frac_to", "name_similarity",
                "overlap_sqm", "area_from_sqm", "area_to_sqm", "area_crs",
                "evidence_kind", "historical_succession_verified", "involves_no_data"]
    # Always replace empty outputs too, so an earlier run cannot leave stale links.
    pd.DataFrame(high_conf, columns=columns).to_csv(high_conf_file, index=False)
    pd.DataFrame(ambiguous, columns=columns).to_csv(ambiguous_file, index=False)
    pd.DataFrame(records, columns=columns).to_csv(
        out_dir / f"correspondences_{args.year_from}_{args.year_to}.csv", index=False)
    for year, frame in [(args.year_from, gdf_from), (args.year_to, gdf_to)]:
        frame.drop(columns="geometry").to_csv(out_dir / f"csd_inventory_{year}.csv", index=False)

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
