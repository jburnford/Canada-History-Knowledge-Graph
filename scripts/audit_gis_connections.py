#!/usr/bin/env python3
"""Recompute GIS evidence and compare it with the legacy census crosswalks.

Writes every positive-area correspondence, source preparation and topology
audits, endpoint coverage, and differences from the committed crosswalks.
These are geometric assessments, not verified administrative successions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from _config import CONFIG, REPO_ROOT
from _gis import dissolve_cds, load_csd_layer, overlap_table


def spatial_relation(row):
    if row.iou >= .98 and min(row.frac_from, row.frac_to) >= .98:
        return "APPROXIMATELY_EQUAL_EXTENT"
    if row.frac_from >= .95 and row.frac_to < .95:
        return "EARLIER_WITHIN_LATER"
    if row.frac_to >= .95 and row.frac_from < .95:
        return "LATER_WITHIN_EARLIER"
    return "PARTIAL_OVERLAP"


def attach_metadata(table, earlier, later, level, y1, y2):
    table = table.copy()
    id_col = "tcpuid" if level == "csd" else "cd_id"
    name_col = "csd_name" if level == "csd" else "cd_name"
    for direction, frame in [("from", earlier), ("to", later)]:
        indices = table[f"{direction}_index"].astype(int).to_numpy()
        for output, column in [("id", id_col), ("name", name_col), ("province", "pr")]:
            table[f"{output}_{direction}"] = frame[column].to_numpy()[indices]
        coverage = (frame.is_coverage_record if "is_coverage_record" in frame
                    else frame[name_col].str.strip().str.upper().eq("NO DATA"))
        table[f"coverage_record_{direction}"] = coverage.to_numpy()[indices]
    table["year_from"], table["year_to"] = y1, y2
    table["spatial_relation"] = [spatial_relation(r) for r in table.itertuples()]
    table["evidence_kind"] = "computed_polygon_intersection"
    table["historical_succession_verified"] = False
    table["involves_no_data"] = table.coverage_record_from | table.coverage_record_to
    table["cross_province"] = table.province_from != table.province_to
    table["area_crs"] = earlier.crs.to_string()
    # A review threshold, not a deletion filter or an identity rule.
    table["material_overlap"] = ((table.overlap_sqm >= 1000) &
                                  (table[["frac_from", "frac_to"]].max(axis=1) >= .01))
    return table


def read_legacy(root, level, y1, y2):
    paths = ([root / "year_links_output" / f"year_links_{y1}_{y2}.csv",
              root / "year_links_output" / f"ambiguous_{y1}_{y2}.csv"] if level == "csd" else
             [root / "cd_links_output" / f"cd_links_{y1}_{y2}.csv",
              root / "cd_links_output" / f"cd_ambiguous_{y1}_{y2}.csv"])
    frames = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        frame = pd.read_csv(path, keep_default_na=False)
        frame["legacy_file"] = str(path.relative_to(root))
        if level == "csd":
            frame = frame.rename(columns={f"tcpuid_{y1}": "id_from", f"tcpuid_{y2}": "id_to"})
        else:
            frame = frame.rename(columns={"cd_from": "id_from", "cd_to": "id_to",
                                          "from_fraction": "frac_from", "to_fraction": "frac_to"})
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def compare_legacy(current, legacy, earlier, later, level):
    keys = ["id_from", "id_to"]
    id_col = "tcpuid" if level == "csd" else "cd_id"
    missing_ids = legacy[~legacy.id_from.isin(earlier[id_col]) |
                         ~legacy.id_to.isin(later[id_col])]
    duplicates = legacy[legacy.duplicated(keys, keep=False)]
    joined = legacy.merge(current[keys + ["iou", "frac_from", "frac_to"]],
                          on=keys, how="left", suffixes=("_old", "_new"))
    for metric in ["iou", "frac_from", "frac_to"]:
        joined[f"delta_{metric}"] = joined[f"{metric}_new"] - joined[f"{metric}_old"]
    joined["max_delta"] = joined[["delta_iou", "delta_frac_from", "delta_frac_to"]].abs().max(axis=1)
    differences = joined[(joined.max_delta > .000051) | joined.iou_new.isna()]
    old_keys = set(map(tuple, legacy[keys].to_numpy()))
    omitted = current.loc[np.array([tuple(x) not in old_keys for x in current[keys].to_numpy()], dtype=bool)]
    summary = {"legacy_rows": len(legacy), "duplicate_legacy_rows": len(duplicates),
               "legacy_rows_with_missing_endpoint": len(missing_ids),
               "legacy_metric_mismatches": len(differences),
               "all_positive_correspondences": len(current),
               "omitted_positive_correspondences": len(omitted),
               "omitted_material_correspondences": int(omitted.material_overlap.sum()),
               "material_correspondences": int(current.material_overlap.sum()),
               "material_cross_province": int((current.material_overlap & current.cross_province).sum())}
    return summary, differences, omitted, duplicates, missing_ids


def endpoint_coverage(table, frame, direction, level):
    id_col = "tcpuid" if level == "csd" else "cd_id"
    key = f"id_{direction}"
    frac = f"frac_{direction}"
    all_sum = table.groupby(key)[frac].sum()
    material_sum = table[table.material_overlap].groupby(key)[frac].sum()
    counts = table[table.material_overlap].groupby(key).size()
    rows = frame[[id_col, "pr", "area"]].rename(columns={id_col: "id", "area": "area_sqm"}).copy()
    rows["direction"] = direction
    rows["sum_overlap_fractions"] = rows.id.map(all_sum).fillna(0)
    rows["sum_material_fractions"] = rows.id.map(material_sum).fillna(0)
    rows["material_counterparts"] = rows.id.map(counts).fillna(0).astype(int)
    # Sums expose overlapping source polygons; they are not union coverage.
    rows["possible_double_coverage"] = rows.sum_overlap_fractions > 1.0001
    rows["less_than_99_percent_coverage"] = rows.sum_overlap_fractions < .99
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gdb", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "data_quality/gis_audit")
    ap.add_argument("--years", default="1851,1861,1871,1881,1891,1901,1911,1921")
    ap.add_argument("--levels", default="csd,cd")
    ap.add_argument("--crs", default="EPSG:3347", help="3347 reproduces the legacy area basis")
    args = ap.parse_args()
    years = [int(y) for y in args.years.split(",")]
    if years != sorted(set(years)) or len(years) < 2:
        ap.error("Supply at least two distinct years in ascending order")
    levels = args.levels.split(",")
    if not set(levels) <= {"csd", "cd"}:
        ap.error("levels must be csd and/or cd")
    gdb = args.gdb or CONFIG.gdb_path
    args.out.mkdir(parents=True, exist_ok=True)
    inventory, repairs, frames = [], [], {}
    for year in years:
        print(f"Preparing {year}", flush=True)
        csds, actions = load_csd_layer(gdb, year, args.crs)
        repairs.extend(actions)
        frames[year] = {"csd": csds}
        if "cd" in levels:
            frames[year]["cd"] = dissolve_cds(csds)
        for level in levels:
            frame = frames[year][level]
            print(f"  {level}: {len(frame)} polygons; checking same-year overlaps", flush=True)
            self_overlaps = attach_metadata(overlap_table(frame, frame, same_layer=True),
                                           frame, frame, level, year, year)
            self_overlaps.to_csv(args.out / f"{level}_topology_{year}.csv", index=False)
            inventory.append({"year": year, "level": level, "polygons": len(frame),
                              "positive_self_overlaps": len(self_overlaps),
                              "material_self_overlaps": int(self_overlaps.material_overlap.sum())})
            frame.drop(columns="geometry").to_csv(args.out / f"{level}_inventory_{year}.csv", index=False)
    pd.DataFrame(repairs, columns=["year", "tcpuid", "action", "detail", "area_before",
                                   "area_after", "area_crs"]).to_csv(args.out / "geometry_preparation.csv", index=False)
    results = []
    for y1, y2 in zip(years[:-1], years[1:]):
        for level in levels:
            print(f"Comparing {level} {y1} → {y2}", flush=True)
            a, b = frames[y1][level], frames[y2][level]
            table = attach_metadata(overlap_table(a, b), a, b, level, y1, y2)
            stem = f"{level}_{y1}_{y2}"
            table.to_csv(args.out / f"{stem}_correspondences.csv", index=False)
            legacy = read_legacy(REPO_ROOT, level, y1, y2)
            summary, diffs, omitted, duplicates, missing_ids = compare_legacy(table, legacy, a, b, level)
            for label, df in [("metric_differences", diffs), ("omitted", omitted),
                              ("legacy_duplicates", duplicates), ("missing_endpoints", missing_ids)]:
                df.to_csv(args.out / f"{stem}_{label}.csv", index=False)
            coverage = pd.concat([endpoint_coverage(table, a, "from", level),
                                  endpoint_coverage(table, b, "to", level)], ignore_index=True)
            coverage.to_csv(args.out / f"{stem}_coverage.csv", index=False)
            examples = table[(table.province_from == "SK") | (table.province_to == "SK") |
                             table.name_from.str.contains("Westmeath", case=False) |
                             table.name_to.str.contains("Westmeath", case=False)]
            examples.to_csv(args.out / f"{stem}_case_studies.csv", index=False)
            summary.update(year_from=y1, year_to=y2, level=level,
                           endpoints_with_double_coverage=int(coverage.possible_double_coverage.sum()),
                           endpoints_below_99_percent_coverage=int(coverage.less_than_99_percent_coverage.sum()))
            results.append(summary)
            print(json.dumps(summary), flush=True)
    hashes = {}
    for path in sorted(gdb.iterdir()):
        if path.is_file() and not path.name.endswith(".lock"):
            with path.open("rb") as source:
                hashes[path.name] = hashlib.file_digest(source, "sha256").hexdigest()
    report = {"source_gdb": str(gdb), "source_sha256": hashes, "area_crs": args.crs,
              "geopandas": gpd.__version__, "shapely": shapely.__version__,
              "geos": shapely.geos_version_string, "source_inventory": inventory,
              "geometry_preparation_actions": len(repairs), "comparisons": results,
              "notes": ["Every positive-area intersection is retained, including numerical slivers.",
                        "Material is a review flag: >=1000 square metres and >=1% of either polygon.",
                        "Coverage sums can exceed one when source polygons overlap.",
                        "Spatial correspondences do not establish historical succession or identity.",
                        "EPSG:3347 is conformal, not equal-area; it reproduces the legacy area basis."]}
    (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Audit complete: {args.out / 'report.json'}", flush=True)


if __name__ == "__main__":
    main()
