#!/usr/bin/env python3
"""
List XLSX sheets and first-row headers for files inside a zip.

Usage:
  python3 scripts/xlsx_inspect_in_zip.py --zip 1901Tables.zip --xlsx 1901/1911_V2T7_PUB_202306.xlsx
If --xlsx is omitted, prints all .xlsx entries.
"""
import argparse
import io
import zipfile
import xml.etree.ElementTree as ET

NS = {
    'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
}

def list_xlsx(zip_path):
    with zipfile.ZipFile(zip_path) as oz:
        return [n for n in oz.namelist() if n.lower().endswith('.xlsx')]

def headers_for_sheet(xlsx_bytes, sheet_name):
    z = zipfile.ZipFile(io.BytesIO(xlsx_bytes))
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    name2rid = {s.attrib.get('name'): s.attrib.get('{%s}id' % NS['r']) for s in wb.find('x:sheets', NS)}
    if sheet_name not in name2rid:
        return None, sorted(name2rid)
    rid = name2rid[sheet_name]
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
    row = ws.find('.//x:sheetData/x:row', NS)
    if row is None:
        return [], []
    header = []
    for c in row.findall('x:c', NS):
        t = c.attrib.get('t')
        v = c.find('x:v', NS)
        val = v.text if v is not None else ''
        if t == 's':
            try:
                val = sst.get(int(val), val)
            except Exception:
                pass
        header.append(val)
    return header, []

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', required=True, help='Zip file path')
    ap.add_argument('--xlsx', help='Path to XLSX within the zip; if omitted, list all .xlsx')
    ap.add_argument('--sheet', help='Sheet name to inspect (prints headers)')
    args = ap.parse_args()

    if not args.xlsx:
        files = list_xlsx(args.zip)
        print('XLSX files found:')
        for f in files:
            print(' ', f)
        return

    with zipfile.ZipFile(args.zip) as oz:
        xbytes = oz.read(args.xlsx)

    if not args.sheet:
        # list sheets
        z = zipfile.ZipFile(io.BytesIO(xbytes))
        wb = ET.fromstring(z.read('xl/workbook.xml'))
        sheets = [s.attrib.get('name') for s in wb.find('x:sheets', NS)]
        print('Sheets:', sheets)
        return

    header, alts = headers_for_sheet(xbytes, args.sheet)
    if header is None:
        print('Sheet not found. Available:', alts)
    else:
        print('Header columns:', len(header))
        print('Header sample:', header[:40])

if __name__ == '__main__':
    main()

