#!/usr/bin/env python3
"""
Compute cross-year CSD links (e.g., 1851 -> 1861) using TCP polygons + year CSD workbooks.

Requires: GeoPandas, Shapely (2.x), Fiona, PyProj, Pandas, RapidFuzz.

Inputs:
  - --gdb: path to the unzipped FileGDB directory, e.g.
      tcp_csd/TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306.gdb
  - --year-from / --year-to: e.g., 1851 and 1861
  - --xlsx-from / --xlsx-to: year CSD workbooks with TCPUID_CSD_YYYY and PR/NAME_CSD_YYYY
  - --provinces: comma-separated province codes to include (e.g., ON,QC)
  - --layer: optional; if omitted the script will auto-detect a layer containing both TCPUID columns
  - --out: output directory for CSVs

Outputs:
  - year_links_<Y1>_<Y2>.csv: high-confidence links (SAME_AS, WITHIN, CONTAINS, OVERLAPS)
  - ambiguous_<Y1>_<Y2>.csv: unresolved/multi-candidate cases for manual QA
  - summary_<Y1>_<Y2>.txt: quick stats

Notes:
  - Reprojects to EPSG:3347 for area/IoU computations
  - Name similarity based on normalized strings; used as a supporting signal
  - Thresholds are tunable via CLI
"""
import argparse
import sys
from pathlib import Path
import warnings

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon, MultiPolygon
from shapely.validation import make_valid
from shapely.ops import unary_union
from rapidfuzz.distance import Levenshtein as _lev


def normalize_name(s: str) -> str:
    if not isinstance(s, str):
        return ''
    import unicodedata, re
    s = unicodedata.normalize('NFD', s)
    s = ''.join(ch for ch in s if unicodedata.category(ch) != 'Mn')
    s = s.upper()
    s = re.sub(r'\bSTE?\.?\b', 'SAINTE', s)
    s = re.sub(r'\bST\.?\b', 'SAINT', s)
    s = s.replace('TOWNSHIP', 'TWP').replace('TWNSHIP', 'TWP').replace('TOWNSH', 'TWP')
    s = re.sub(r'\bTW\b', 'TWP', s)
    s = re.sub(r'[^A-Z0-9 ]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def read_year_table(xlsx_path: Path, year: int, provinces: set[str]) -> pd.DataFrame:
    # Load via pandas; require openpyxl engine
    try:
        df = pd.read_excel(xlsx_path, sheet_name='Sheet1')
    except Exception:
        # fallback: try first sheet
        df = pd.read_excel(xlsx_path)
    # expected columns
    name_col = f'NAME_CSD_{year}'
    tcp_col = f'TCPUID_CSD_{year}'
    pr_col = 'PR'
    missing = [c for c in [name_col, tcp_col, pr_col] if c not in df.columns]
    if missing:
        raise SystemExit(f"Missing columns in {xlsx_path}: {missing}")
    df = df[[pr_col, name_col, tcp_col]].dropna()
    df = df[df[pr_col].astype(str).str.upper().isin(provinces)].copy()
    df.rename(columns={pr_col: 'PR', name_col: 'NAME', tcp_col: 'TCP'}, inplace=True)
    df['NAME_NORM'] = df['NAME'].apply(normalize_name)
    df['TCP'] = df['TCP'].astype(str)
    return df


def list_layers(gdb_path: Path) -> list[str]:
    import fiona
    return list(fiona.listlayers(gdb_path))


def load_year_polys(gdb_path: Path, layer: str, year: int, provinces: set[str], tcp_col: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(gdb_path, layer=layer)
    # Filter to features that have a TCPUID for the target year
    if tcp_col not in gdf.columns:
        raise SystemExit(f"Layer '{layer}' does not contain {tcp_col}")
    gdf = gdf[gdf[tcp_col].notna()].copy()
    # Some datasets include province field; if available filter; else rely on table join
    # Standardize geometry
    gdf['geometry'] = gdf['geometry'].apply(lambda geom: make_valid(geom) if geom is not None else None)
    gdf = gdf.set_geometry('geometry', crs=gdf.crs)
    # Keep only necessary columns
    gdf['TCP'] = gdf[tcp_col].astype(str)
    return gdf[['TCP', 'geometry']]


def classify_pair(area_a, area_b, area_int, iou_same=0.98, frac_same=0.98, iou_overlap=0.30):
    if area_a <= 0 or area_b <= 0:
        return 'AMBIG'
    frac_a = area_int / area_a
    frac_b = area_int / area_b
    iou = area_int / (area_a + area_b - area_int) if (area_a + area_b - area_int) > 0 else 0
    if iou >= iou_same and min(frac_a, frac_b) >= frac_same:
        rel = 'SAME_AS'
    elif frac_a >= frac_same:
        rel = 'WITHIN'   # A within B (year-from within year-to)
    elif frac_b >= frac_same:
        rel = 'CONTAINS' # A contains B
    elif iou >= iou_overlap:
        rel = 'OVERLAPS'
    else:
        rel = 'AMBIG'
    return rel, iou, frac_a, frac_b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--gdb', required=True, help='Path to FileGDB directory (.gdb)')
    ap.add_argument('--layer', help='Feature class name in the GDB; if omitted, auto-detect')
    ap.add_argument('--year-from', type=int, required=True)
    ap.add_argument('--year-to', type=int, required=True)
    ap.add_argument('--xlsx-from', required=True)
    ap.add_argument('--xlsx-to', required=True)
    ap.add_argument('--provinces', default='ON,QC')
    ap.add_argument('--out', default='out_links')
    ap.add_argument('--iou-same', type=float, default=0.98)
    ap.add_argument('--frac-same', type=float, default=0.98)
    ap.add_argument('--iou-overlap', type=float, default=0.30)
    args = ap.parse_args()

    gdb_path = Path(args.gdb)
    if not gdb_path.exists():
        raise SystemExit(f"GDB not found: {gdb_path}")
    provinces = {p.strip().upper() for p in args.provinces.split(',') if p.strip()}

    # Detect layer if needed
    layer = args.layer
    if not layer:
        layers = list_layers(gdb_path)
        # pick first layer that has both year TCPUID columns present
        picked = None
        for lyr in layers:
            try:
                gdf_head = gpd.read_file(gdb_path, layer=lyr, rows=1)
            except Exception:
                continue
            cols = set(gdf_head.columns)
            if f'TCPUID_CSD_{args.year_from}' in cols and f'TCPUID_CSD_{args.year_to}' in cols:
                picked = lyr
                break
        if not picked:
            raise SystemExit(f"Could not find a layer in {gdb_path} with TCPUID_CSD_{args.year_from} and TCPUID_CSD_{args.year_to}")
        layer = picked

    # Load year tables
    df_from = read_year_table(Path(args.xlsx_from), args.year_from, provinces)
    df_to = read_year_table(Path(args.xlsx_to), args.year_to, provinces)

    # Load year polygons and merge attributes by TCP
    tcp_from_col = f'TCPUID_CSD_{args.year_from}'
    tcp_to_col = f'TCPUID_CSD_{args.year_to}'
    gdf_from = load_year_polys(gdb_path, layer, args.year_from, provinces, tcp_from_col)
    gdf_to = load_year_polys(gdb_path, layer, args.year_to, provinces, tcp_to_col)

    gdf_from = gdf_from.merge(df_from[['PR', 'NAME', 'NAME_NORM', 'TCP']], on='TCP', how='left')
    gdf_to = gdf_to.merge(df_to[['PR', 'NAME', 'NAME_NORM', 'TCP']], on='TCP', how='left')

    # Filter to selected provinces (some polygons may lack PR; rely on table join above)
    gdf_from = gdf_from[gdf_from['PR'].isin(provinces)].copy()
    gdf_to = gdf_to[gdf_to['PR'].isin(provinces)].copy()

    # Reproject to equal-area CRS
    try:
        gdf_from = gdf_from.to_crs(3347)
        gdf_to = gdf_to.to_crs(3347)
    except Exception as e:
        warnings.warn(f"CRS reprojection failed: {e}")

    # Build spatial index and compute intersections
    from shapely import area
    gdf_to_sindex = gdf_to.sindex

    rows = []
    ambig = []
    for idx_a, a in gdf_from.iterrows():
        geom_a = a.geometry
        if geom_a is None or geom_a.is_empty:
            continue
        area_a = geom_a.area
        # candidate to features (same PR, first by bbox intersect)
        possible = list(gdf_to_sindex.intersection(geom_a.bounds))
        best = []
        for j in possible:
            b = gdf_to.iloc[j]
            if b['PR'] != a['PR']:
                continue
            geom_b = b.geometry
            if geom_b is None or geom_b.is_empty:
                continue
            if not geom_a.intersects(geom_b):
                continue
            inter = geom_a.intersection(geom_b)
            if inter.is_empty:
                continue
            area_b = geom_b.area
            area_int = inter.area
            rel, iou, frac_a, frac_b = classify_pair(area_a, area_b, area_int, args.iou_same, args.frac_same, args.iou_overlap)
            # name similarity: small Levenshtein distance on normalized names
            name_sim = 1.0 - (_lev.normalized_distance(a['NAME_NORM'] or '', b['NAME_NORM'] or ''))
            best.append((rel, iou, frac_a, frac_b, name_sim, b))

        if not best:
            ambig.append((a['PR'], a['TCP'], a['NAME'], None, None, 'NO_CANDIDATE'))
            continue

        # pick highest by relation priority then IoU then name_sim
        priority = {'SAME_AS': 3, 'WITHIN': 2, 'CONTAINS': 2, 'OVERLAPS': 1, 'AMBIG': 0}
        best.sort(key=lambda x: (priority.get(x[0], 0), x[1], x[4]), reverse=True)
        top_rel, iou, frac_a, frac_b, name_sim, btop = best[0]

        row = {
            'year_from': args.year_from,
            'pr': a['PR'],
            'tcp_from': a['TCP'],
            'name_from': a['NAME'],
            'year_to': args.year_to,
            'tcp_to': btop['TCP'],
            'name_to': btop['NAME'],
            'rel_type': top_rel,
            'iou': round(iou, 6),
            'frac_from': round(frac_a, 6),
            'frac_to': round(frac_b, 6),
            'name_sim': round(name_sim, 6),
        }
        rows.append(row)

        # log second-best if also strong to ambiguous
        if len(best) > 1:
            second = best[1]
            if second[1] > 0.5 and second[4] > 0.8:
                sb = second[5]
                ambig.append((a['PR'], a['TCP'], a['NAME'], sb['TCP'], sb['NAME'], 'SECOND_CANDIDATE'))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    links_path = out_dir / f"year_links_{args.year_from}_{args.year_to}.csv"
    ambig_path = out_dir / f"ambiguous_{args.year_from}_{args.year_to}.csv"
    summary_path = out_dir / f"summary_{args.year_from}_{args.year_to}.txt"

    pd.DataFrame(rows).to_csv(links_path, index=False)
    pd.DataFrame(ambig, columns=['pr','tcp_from','name_from','tcp_to','name_to','note']).to_csv(ambig_path, index=False)

    # summary
    df_links = pd.DataFrame(rows)
    counts = df_links['rel_type'].value_counts().to_dict() if not df_links.empty else {}
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(f"Layer: {layer}\n")
        f.write(f"Features from: {len(gdf_from)}  to: {len(gdf_to)}\n")
        f.write(f"Links: {len(rows)}  Ambiguous: {len(ambig)}\n")
        f.write("Counts by class:\n")
        for k, v in counts.items():
            f.write(f"  {k}: {v}\n")

    print(f"Wrote {links_path} and {ambig_path}. See {summary_path} for stats.")


if __name__ == '__main__':
    main()

