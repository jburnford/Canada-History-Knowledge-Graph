#!/usr/bin/env python3
"""
Extract Canada-wide rows from 1911 Volume 1 Table 1 into normalized CSVs.

Inputs:
  - 1911Tables.zip in repo root (contains 1911/1911_V1T1_PUB_202306.xlsx)

Outputs (to files via --out-dir):
  - places.csv: unique Place rows
  - observations.csv: Observation rows

Options:
  --province-filter: two-letter PR code (e.g., SK, AB). Default: ALL (no filter).

Note: minimal XLSX reader implemented using stdlib (zipfile + xml.etree) to avoid external deps.
"""
import argparse
import csv
import io
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

XLSX_PATH_IN_ZIP = '1911/1911_V1T1_PUB_202306.xlsx'
SHEET_NAME = 'CA_V1T1_1911'


def read_sheet_rows(xlsx_bytes, sheet_name):
    z = zipfile.ZipFile(io.BytesIO(xlsx_bytes))
    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
          'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}

    wb = ET.fromstring(z.read('xl/workbook.xml'))
    # Map sheet name -> rel id
    name_to_rid = {}
    for s in wb.find('x:sheets', ns):
        name = s.attrib.get('name')
        rid = s.attrib.get('{%s}id' % ns['r'])
        name_to_rid[name] = rid
    rid = name_to_rid.get(sheet_name)
    if not rid:
        raise SystemExit(f"Sheet '{sheet_name}' not found. Available: {sorted(name_to_rid)}")

    # Map rel id -> target
    rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    id2target = {r.attrib['Id']: r.attrib['Target'] for r in rels}
    target = id2target[rid]

    # Shared strings
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        sst = ET.fromstring(z.read('xl/sharedStrings.xml'))
        for si in sst.findall('x:si', ns):
            t = si.find('x:t', ns)
            if t is not None and t.text is not None:
                shared.append(t.text)
            else:
                # Rich text run fallback
                txt = ''.join((r.find('x:t', ns).text or '') for r in si.findall('x:r', ns))
                shared.append(txt)

    ws = ET.fromstring(z.read('xl/' + target))
    rows = []
    for r in ws.findall('.//x:sheetData/x:row', ns):
        row = []
        for c in r.findall('x:c', ns):
            t = c.attrib.get('t')
            v = c.find('x:v', ns)
            val = v.text if v is not None else ''
            if t == 's':
                try:
                    idx = int(val)
                    val = shared[idx] if 0 <= idx < len(shared) else val
                except Exception:
                    pass
            row.append(val)
        rows.append(row)
    return rows


def derive_level(pr, cd_no, csd_no, name):
    if pr == 'CA':
        return 'country'
    if cd_no == '0' and csd_no == '0':
        return 'province'
    if csd_no == '0':
        return 'division'
    if re.search(r"T\d+\s+R\d+", name or ''):
        return 'township'
    return 'subdivision'


def parse_rows(rows, province_filter="ALL"):
    # First row is header
    header = rows[0]
    idx = {name: i for i, name in enumerate(header)}

    def g(r, col):
        i = idx.get(col)
        return r[i].strip() if i is not None and i < len(r) else ''

    places = {}
    observations = []

    province_filter = (province_filter or 'ALL').upper()

    for r in rows[1:]:
        pr = g(r, 'PR')
        if province_filter != 'ALL':
            # Keep country row (CA) and matching province
            if pr not in (province_filter, 'CA'):
                continue

        row_id = g(r, 'ROW_ID') or ''
        place_id = g(r, 'V1T1_1911')
        name = g(r, 'PR_CD_CSD')
        cd_no = g(r, 'CD_NO')
        csd_no = g(r, 'CSD_NO')
        level = derive_level(pr, cd_no, csd_no, name)

        # Place
        if place_id and place_id not in places:
            places[place_id] = {
                'id': place_id,
                'name': name,
                'province_code': pr,
                'cd_no': cd_no,
                'csd_no': csd_no,
                'level': level,
                'year_start': '1911',
                'notes': ''
            }

        # Observation
        obs = {
            'id': f"V1T1_1911:{row_id}" if row_id else f"V1T1_1911:{place_id}",
            'place_id': place_id,
            'year': '1911',
            'area_acres_1911': g(r, 'AREA_ACRES_1911'),
            'area_sq_mi_1911': g(r, 'AREA_SQ_MI_1911'),
            'pop_m_1911': g(r, 'POP_M_1911'),
            'pop_f_1911': g(r, 'POP_F_1911'),
            'pop_total_1911': g(r, 'POP_TOT_1911'),
            'pop_per_sq_mi_1911': g(r, 'POP_PER_SQ_MI_1911'),
            'pop_1901': g(r, 'POP_1901'),
            'table_id': 'V1T1_1911',
            'notes': g(r, 'NOTES'),
        }
        observations.append(obs)

    return places, observations


def write_csv(path, rows, fieldnames):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, '') for k in fieldnames})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', default='1911Tables.zip', help='Path to 1911 tables zip')
    ap.add_argument('--out-dir', default='generated/sk_1911', help='Output directory for CSVs')
    args = ap.parse_args()

    outer = Path(args.zip)
    if not outer.exists():
        print(f"ERROR: Zip not found: {outer}", file=sys.stderr)
        sys.exit(2)

    with zipfile.ZipFile(outer) as oz:
        try:
            xlsx_bytes = oz.read(XLSX_PATH_IN_ZIP)
        except KeyError:
            print(f"ERROR: XLSX '{XLSX_PATH_IN_ZIP}' not found in {outer}", file=sys.stderr)
            sys.exit(2)

    rows = read_sheet_rows(xlsx_bytes, SHEET_NAME)
    places, observations = parse_rows(rows, province_filter='ALL')

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    places_path = out_dir / 'places.csv'
    obs_path = out_dir / 'observations.csv'

    write_csv(places_path, places.values(), [
        'id', 'name', 'province_code', 'cd_no', 'csd_no', 'level', 'year_start', 'notes'
    ])
    write_csv(obs_path, observations, [
        'id', 'place_id', 'year', 'area_acres_1911', 'area_sq_mi_1911',
        'pop_m_1911', 'pop_f_1911', 'pop_total_1911', 'pop_per_sq_mi_1911', 'pop_1901', 'table_id', 'notes'
    ])

    print(f"Wrote {len(places)} places -> {places_path}")
    print(f"Wrote {len(observations)} observations -> {obs_path}")

    # Preview top 5 rows by population
    def safe_int(x):
        try:
            return int(float(str(x).replace(',', '.')))
        except Exception:
            return -1

    subs = [o for o in observations if o['place_id'] in places]
    subs.sort(key=lambda o: safe_int(o['pop_total_1911']), reverse=True)
    print("Top 5 SK rows by pop_total_1911:")
    for o in subs[:5]:
        p = places[o['place_id']]
        print(f"  {p['name']} [{p['province_code']}] ({p['level']}): {o['pop_total_1911']}")

    # Summary by province
    by_pr = {}
    for p in places.values():
        pr = p['province_code']
        by_pr.setdefault(pr, 0)
        by_pr[pr] += 1
    print("\nPlace counts by province_code:")
    for pr, cnt in sorted(by_pr.items(), key=lambda x: (x[0] != 'CA', x[0])):
        print(f"  {pr}: {cnt}")

if __name__ == '__main__':
    main()
