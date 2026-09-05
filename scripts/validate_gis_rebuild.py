#!/usr/bin/env python3
"""Validate staged GIS links and summarize projection and source-coverage issues."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from _config import REPO_ROOT


def validate_tables(audit, rebuilt):
    metrics = ["iou", "frac_from", "frac_to", "overlap_sqm", "area_from_sqm", "area_to_sqm"]
    metadata = ["area_crs", "evidence_kind", "historical_succession_verified"]
    if 'involves_no_data' in audit:
        metadata.append('involves_no_data')
    fields = ["id_from", "id_to"] + metrics + metadata
    joined = audit[fields].merge(rebuilt[fields], on=fields[:2], how="outer",
                                 suffixes=("_audit", "_rebuilt"), indicator=True,
                                 validate="one_to_one")
    errors = int((joined._merge != "both").sum())
    for col in metrics:
        errors += int((~np.isclose(joined[col + "_audit"], joined[col + "_rebuilt"],
                                  rtol=1e-9, atol=1e-9)).sum())
    for col in metadata:
        errors += int((joined[col + "_audit"] != joined[col + "_rebuilt"]).sum())
    return {"rows": len(joined), "errors": errors}


def compare_projections(audit, equal_area):
    joined = audit.merge(equal_area, on=["id_from", "id_to"], how="outer",
                         suffixes=("_lambert", "_albers"), indicator=True,
                         validate="one_to_one")
    flags = joined[["material_overlap_lambert", "material_overlap_albers"]].eq(True)
    joined = joined[flags.any(axis=1)].copy()
    missing = joined._merge != "both"
    changed = (joined.spatial_relation_lambert != joined.spatial_relation_albers) | missing
    deltas = pd.concat([(joined[f"{col}_lambert"] - joined[f"{col}_albers"]).abs()
                        for col in ["frac_from", "frac_to"]])
    summary = {
        "material_pairs": len(joined),
        "material_pairs_missing_in_one_projection": int(missing.sum()),
        "max_fraction_delta": float(deltas.max()) if deltas.notna().any() else None,
        "relation_changes": int(changed.sum()),
        "material_flag_changes": int((joined.material_overlap_lambert.eq(True) !=
                                      joined.material_overlap_albers.eq(True)).sum()),
    }
    return summary, joined[changed]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audit", type=Path, default=REPO_ROOT / "data_quality/gis_audit")
    ap.add_argument("--staged", type=Path, default=REPO_ROOT / "data_quality/gis_rebuild")
    ap.add_argument("--equal-area", type=Path, default=None)
    args = ap.parse_args()
    checks, sensitivity, coverage_review, threshold_review = [], [], [], []
    for y1 in range(1851, 1912, 10):
        y2 = y1 + 10
        for level in ["csd", "cd"]:
            name = f"{level}_{y1}_{y2}_correspondences.csv"
            audit = pd.read_csv(args.audit / name)
            stage_name = (f"correspondences_{y1}_{y2}.csv" if level == "csd"
                          else f"cd_correspondences_{y1}_{y2}.csv")
            rebuilt = pd.read_csv(args.staged / level / stage_name).rename(columns={
                f"tcpuid_{y1}": "id_from", f"tcpuid_{y2}": "id_to",
                "cd_from": "id_from", "cd_to": "id_to",
                "from_fraction": "frac_from", "to_fraction": "frac_to"})
            result = validate_tables(audit, rebuilt)
            result.update(level=level, year_from=y1, year_to=y2)
            checks.append(result)
            if args.equal_area:
                equal_area = pd.read_csv(args.equal_area / name)
                summary, changes = compare_projections(audit, equal_area)
                changes = changes.assign(level=level, comparison_year_from=y1,
                                         comparison_year_to=y2)
                threshold_review.extend(changes.to_dict("records"))
                sensitivity.append(dict(summary, level=level, year_from=y1, year_to=y2))
            if level == "csd":
                coverage = pd.read_csv(args.audit / f"csd_{y1}_{y2}_coverage.csv")
                for row in coverage[coverage.less_than_99_percent_coverage].to_dict("records"):
                    year = y1 if row["direction"] == "from" else y2
                    inventory = pd.read_csv(args.audit / f"csd_inventory_{year}.csv").set_index("tcpuid")
                    row.update(year=year, comparison_year_from=y1, comparison_year_to=y2,
                               csd_name=inventory.loc[row["id"], "csd_name"],
                               cd_name=inventory.loc[row["id"], "cd_name"],
                               review_status="source_coverage_difference_requires_interpretation")
                    coverage_review.append(row)
    pd.DataFrame(checks).to_csv(args.staged / "validation.csv", index=False)
    pd.DataFrame(coverage_review).to_csv(args.audit / "coverage_review.csv", index=False)
    if args.equal_area:
        pd.DataFrame(sensitivity).to_csv(args.audit / "projection_sensitivity.csv", index=False)
        pd.DataFrame(threshold_review).to_csv(args.audit / "projection_threshold_review.csv", index=False)
    print(pd.DataFrame(checks).to_string(index=False))
    if any(row["errors"] for row in checks):
        raise SystemExit("Staged GIS correspondence verification failed")
    print("All staged GIS correspondences match the audit.")


if __name__ == "__main__":
    main()
