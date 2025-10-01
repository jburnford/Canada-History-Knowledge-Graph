#!/usr/bin/env python3
import argparse
import csv
import io
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

NS = {
    'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
}

def read_csd_records(zip_path: Path, xlsx_in_zip: str, sheet: str, year: str):
    with zipfile.ZipFile(zip_path) as oz:
        xbytes = oz.read(xlsx_in_zip)
    z = zipfile.ZipFile(io.BytesIO(xbytes))
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    name2rid = {s.attrib.get('name'): s.attrib.get('{%s}id' % NS['r']) for s in wb.find('x:sheets', NS)}
    rid = name2rid[sheet]
    rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    id2t = {r.attrib['Id']: r.attrib['Target'] for r in rels}
    ws = ET.fromstring(z.read('xl/' + id2t[rid]))
    sst = {}
    if 'xl/sharedStrings.xml' in z.namelist():
        sst_xml = ET.fromstring(z.read('xl/sharedStrings.xml'))
        for idx, si in enumerate(sst_xml.findall('x:si', NS)):
            t = si.find('x:t', NS)
            if t is not None and t.text is not None:
                sst[idx] = t.text
            else:
                sst[idx] = ''.join((r.find('x:t', NS).text or '') for r in si.findall('x:r', NS))
    rows = []
    for r in ws.findall('.//x:sheetData/x:row', NS):
        row = []
        for c in r.findall('x:c', NS):
            t = c.attrib.get('t')
            v = c.find('x:v', NS)
            val = v.text if v is not None else ''
            if t == 's':
                try:
                    val = sst.get(int(val), val)
                except Exception:
                    pass
            row.append(val)
        rows.append(row)
    hdr = rows[0]
    idx = {h: i for i, h in enumerate(hdr)}
    name_col = f'NAME_CSD_{year}'
    tcp_col = f'TCPUID_CSD_{year}'
    recs = []
    for r in rows[1:]:
        if len(r) <= max(idx.values()):
            continue
        pr = r[idx.get('PR', 0)]
        name = r[idx.get(name_col, 0)]
        tcp = r[idx.get(tcp_col, 0)]
        if not pr or not name or not tcp:
            continue
        recs.append({'pr': pr, 'name': name, 'tcp': tcp})
    return recs

def normalize_name(s: str) -> str:
    if not s:
        return ''
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

def lev_distance(a: str, b: str, max_cutoff: int = 2) -> int:
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > max_cutoff:
        return max_cutoff + 1
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        min_row = i
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            cur.append(v)
            if v < min_row:
                min_row = v
        prev = cur
        if min_row > max_cutoff:
            return max_cutoff + 1
    return prev[-1]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip-from', default='1851Tables.zip')
    ap.add_argument('--zip-to', default='1861Tables.zip')
    ap.add_argument('--xlsx-from', default='1851/1851_V1T1_CSD_202306.xlsx')
    ap.add_argument('--xlsx-to', default='1861/1861_V1T1_CSD_202306.xlsx')
    ap.add_argument('--sheet', default='Sheet1')
    ap.add_argument('--year-from', default='1851')
    ap.add_argument('--year-to', default='1861')
    ap.add_argument('--provinces', default='ON,QC')
    ap.add_argument('--out', default='out_crosswalk/candidates_1851_1861_by_name.csv')
    args = ap.parse_args()

    zf = Path(args.zip_from); zt = Path(args.zip_to)
    recs_from = read_csd_records(zf, args.xlsx_from, args.sheet, args.year_from)
    recs_to = read_csd_records(zt, args.xlsx_to, args.sheet, args.year_to)

    provs = {p.strip().upper() for p in args.provinces.split(',') if p.strip()}
    recs_from = [r for r in recs_from if r['pr'] in provs]
    recs_to = [r for r in recs_to if r['pr'] in provs]

    by_pr_from = {}
    for r in recs_from:
        r['name_norm'] = normalize_name(r['name'])
        by_pr_from.setdefault(r['pr'], []).append(r)
    by_pr_to = {}
    for r in recs_to:
        r['name_norm'] = normalize_name(r['name'])
        by_pr_to.setdefault(r['pr'], []).append(r)

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    with outp.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['year_from', 'pr', 'tcp_from', 'name_from', 'year_to', 'tcp_to', 'name_to', 'match_type', 'name_distance'])
        total = exact = near = 0
        for pr in sorted(provs):
            src = by_pr_from.get(pr, [])
            dst = by_pr_to.get(pr, [])
            idx_to = {}
            for r in dst:
                idx_to.setdefault(r['name_norm'], []).append(r)
            for a in src:
                total += 1
                matches = idx_to.get(a['name_norm'])
                if matches:
                    for b in matches:
                        w.writerow([args.year_from, pr, a['tcp'], a['name'], args.year_to, b['tcp'], b['name'], 'exact_norm', 0])
                        exact += 1
                    continue
                token = a['name_norm'].split(' ')[0] if a['name_norm'] else ''
                cands = [b for b in dst if (b['name_norm'].split(' ')[0] if b['name_norm'] else '') == token]
                best = None; bestd = 999
                for b in cands:
                    d = lev_distance(a['name_norm'], b['name_norm'], max_cutoff=2)
                    if d < bestd:
                        best, bestd = b, d
                if best and bestd <= 2:
                    w.writerow([args.year_from, pr, a['tcp'], a['name'], args.year_to, best['tcp'], best['name'], 'near_norm', bestd])
                    near += 1
        print(f"Wrote {outp} | total_from={total} exact={exact} near={near}")

if __name__ == '__main__':
    main()

