"""Shared, auditable preparation and overlap calculations for census polygons.

Geometric correspondence is evidence, not an assertion of historical identity.
Areas are planar square metres in the explicitly selected projected CRS.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely


def polygonal(geometry):
    """Repair a geometry and retain its polygonal components; reject data loss."""
    if geometry is None or geometry.is_empty:
        raise ValueError("Missing or empty census geometry")
    fixed = shapely.make_valid(geometry) if not geometry.is_valid else geometry
    if fixed.geom_type in {"Polygon", "MultiPolygon"}:
        result = fixed
    else:
        parts = []
        pending = list(shapely.get_parts(fixed))
        while pending:
            part = pending.pop()
            if part.geom_type == "Polygon":
                parts.append(part)
            elif part.geom_type in {"MultiPolygon", "GeometryCollection"}:
                pending.extend(shapely.get_parts(part))
        if not parts:
            raise ValueError("Census geometry has no polygonal area after repair")
        result = shapely.union_all(parts)
    if result.is_empty or not result.is_valid or result.area <= 0:
        raise ValueError("Invalid or zero-area polygon after repair")
    return result


def prepare_csd_layer(raw, year, crs="EPSG:3347"):
    """Normalize a source layer, returning (polygons, preparation audit).

    Repeated IDs are dissolved only when descriptive attributes agree. This
    preserves the two source pieces of QC053009 (Chantiers) in 1851. Conflicting
    attributes are an error requiring an explicit source correction.
    """
    if raw.crs is None:
        raise ValueError(f"{year}: source CRS is missing")
    rename = {f"TCPUID_CSD_{year}": "tcpuid", f"PR_{year}": "pr"}
    for prefix in ["Name", "NAME"]:
        rename[f"{prefix}_CD_{year}"] = "cd_name"
        rename[f"{prefix}_CSD_{year}"] = "csd_name"
    frame = raw.rename(columns=rename).copy()
    columns = ["tcpuid", "pr", "cd_name", "csd_name"]
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{year}: missing source columns {sorted(missing)}")
    frame = frame[columns + ["geometry"]]
    for col in columns:
        if col in {"tcpuid", "pr"} and frame[col].isna().any():
            raise ValueError(f"{year}: missing {col}")
        frame[col] = frame[col].fillna("").astype(str).str.strip()
    if (frame.tcpuid == "").any() or (frame.pr == "").any():
        raise ValueError(f"{year}: empty identifier or province")
    audit = []
    for index, row in frame.iterrows():
        geom = row.geometry
        repaired = polygonal(geom)
        if not geom.is_valid or geom.geom_type != repaired.geom_type:
            audit.append({"year": year, "tcpuid": row.tcpuid,
                          "action": "repair_geometry",
                          "detail": shapely.is_valid_reason(geom),
                          "area_before": geom.area, "area_after": repaired.area,
                          "area_crs": raw.crs.to_string()})
        frame.at[index, "geometry"] = repaired
    for uid, group in frame[frame.tcpuid.duplicated(False)].groupby("tcpuid"):
        if any(group[col].nunique() != 1 for col in columns):
            raise ValueError(f"{year}: duplicate ID {uid} has conflicting metadata")
        audit.append({"year": year, "tcpuid": uid,
                      "action": "dissolve_duplicate_id",
                      "detail": f"{len(group)} source records with matching metadata",
                      "area_before": group.geometry.area.sum(),
                      "area_after": shapely.union_all(group.geometry.values).area,
                      "area_crs": raw.crs.to_string()})
    if frame.tcpuid.duplicated().any():
        frame = frame.dissolve(by=columns, as_index=False)
    frame = frame.to_crs(crs).sort_values("tcpuid").reset_index(drop=True)
    for index in frame.index[~frame.is_valid]:
        geom = frame.at[index, "geometry"]
        repaired = polygonal(geom)
        audit.append({"year": year, "tcpuid": frame.at[index, "tcpuid"],
                      "action": "repair_after_projection",
                      "detail": shapely.is_valid_reason(geom),
                      "area_before": geom.area, "area_after": repaired.area,
                      "area_crs": frame.crs.to_string()})
        frame.at[index, "geometry"] = repaired
    if not frame.crs.is_projected or any(a.unit_name != "metre" for a in frame.crs.axis_info):
        raise ValueError("Area calculations require a projected CRS in metres")
    frame["area"] = frame.geometry.area
    if not np.isfinite(frame.area).all() or (frame.area <= 0).any():
        raise ValueError(f"{year}: nonfinite or zero polygon area")
    return frame, audit


def load_csd_layer(path, year, crs="EPSG:3347"):
    return prepare_csd_layer(gpd.read_file(path, layer=f"CANADA_{year}_CSD"), year, crs)


def dissolve_cds(csds):
    if (csds.cd_name == "").any():
        raise ValueError("Cannot create a census division from an empty CD name")
    cds = csds[["pr", "cd_name", "geometry"]].dissolve(
        by=["pr", "cd_name"], as_index=False)
    # A named parent such as "Newfoundland" can still be only a coverage
    # placeholder. Preserve that fact when NO DATA children are dissolved.
    coverage = csds.assign(is_coverage_record=csds.csd_name.str.strip().str.upper().eq("NO DATA"))
    coverage = coverage.groupby(["pr", "cd_name"], as_index=False).is_coverage_record.all()
    cds = cds.merge(coverage, on=["pr", "cd_name"], validate="one_to_one")
    cds["cd_id"] = "CD_" + cds.pr + "_" + cds.cd_name.str.replace(" ", "_", regex=False)
    if cds.cd_id.duplicated().any():
        raise ValueError("CD ID encoding collision")
    cds["area"] = cds.geometry.area
    return cds.sort_values("cd_id").reset_index(drop=True)


def overlap_table(earlier, later, *, same_layer=False, batch_size=256):
    """All positive-area intersections, without a significance filter.

    Positional spatial-index results must index geometry arrays, never pandas
    index labels. Geometry failures propagate instead of masquerading as zero.
    """
    if earlier.crs is None or earlier.crs != later.crs:
        raise ValueError("Overlap inputs must use the same known CRS")
    if not earlier.crs.is_projected:
        raise ValueError("Overlap areas require a projected CRS")
    pairs = later.sindex.query(earlier.geometry, predicate="intersects")
    if same_layer:
        pairs = pairs[:, pairs[0] < pairs[1]]
    chunks = []
    ga, gb = earlier.geometry.values, later.geometry.values
    aa, ab = earlier.geometry.area.to_numpy(), later.geometry.area.to_numpy()
    for start in range(0, pairs.shape[1], batch_size):
        left, right = pairs[:, start:start + batch_size]
        inter = shapely.area(shapely.intersection(ga[left], gb[right]))
        if not np.isfinite(inter).all() or (inter < 0).any():
            raise ValueError("Invalid intersection area")
        keep = inter > 0
        left, right, inter = left[keep], right[keep], inter[keep]
        if not len(left):
            continue
        union = aa[left] + ab[right] - inter
        chunks.append(pd.DataFrame({
            "from_index": left, "to_index": right, "overlap_sqm": inter,
            "area_from_sqm": aa[left], "area_to_sqm": ab[right],
            "iou": inter / union, "frac_from": inter / aa[left],
            "frac_to": inter / ab[right],
        }))
    columns = ["from_index", "to_index", "overlap_sqm", "area_from_sqm",
               "area_to_sqm", "iou", "frac_from", "frac_to"]
    if not chunks:
        return pd.DataFrame(columns=columns)
    result = pd.concat(chunks, ignore_index=True).sort_values(["from_index", "to_index"])
    if (result[["iou", "frac_from", "frac_to"]] > 1 + 1e-9).any().any():
        raise ValueError("Intersection exceeds a source polygon's area")
    return result.reset_index(drop=True)
