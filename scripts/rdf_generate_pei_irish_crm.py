#!/usr/bin/env python3
"""
Generate RDF (Turtle) using CIDOC-CRM for PEI Irish-origin counts per CSD
from a specified year/table inside a provided zip. Defaults target 1911 V2T7.

Mapping (simplified CIDOC-CRM pattern):
- ex:place/<id> a crm:E53_Place ; rdfs:label "<name>" .
- ex:measurement/1911/irish/<id> a crm:E16_Measurement ;
    crm:P39_measured ex:place/<id> ;
    crm:P2_has_type ex:measurementType/irish_population_1911 ;
    crm:P40_observed_dimension ex:dimension/1911/irish/<id> ;
    crm:P4_has_time-span ex:timespan/1911 .
- ex:dimension/1911/irish/<id> a crm:E54_Dimension ;
    crm:P91_has_unit ex:unit/person ;
    crm:P90_has_value "<count>"^^xsd:integer .
- ex:timespan/1911 a crm:E52_Time-Span ; crm:P82a_begin_of_the_begin "1911-01-01"^^xsd:date ; crm:P82b_end_of_the_end "1911-12-31"^^xsd:date .

Assumptions:
- Uses V2T7_1911 codes as stable place identifiers; these align with other 1911 tables.
- Emits only CSD-level rows (CSD_NO != '0') for PR == 'PE'.
"""
import io
import zipfile
import xml.etree.ElementTree as ET
import argparse

def read_v2t7_rows(zip_path):
    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
          'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    with zipfile.ZipFile(zip_path) as oz:
        xbytes = oz.read('1911/1911_V2T7_PUB_202306.xlsx')
    z = zipfile.ZipFile(io.BytesIO(xbytes))
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    name2rid = {s.attrib.get('name'): s.attrib.get('{%s}id' % ns['r']) for s in wb.find('x:sheets', ns)}
    rid = name2rid['CA_V2T7_1911']
    rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    id2t = {r.attrib['Id']: r.attrib['Target'] for r in rels}
    ws = ET.fromstring(z.read('xl/' + id2t[rid]))
    sst = {}
    if 'xl/sharedStrings.xml' in z.namelist():
        sst_xml = ET.fromstring(z.read('xl/sharedStrings.xml'))
        for idx, si in enumerate(sst_xml.findall('x:si', ns)):
            t = si.find('x:t', ns)
            if t is not None and t.text is not None:
                sst[idx] = t.text
            else:
                sst[idx] = ''.join((r.find('x:t', ns).text or '') for r in si.findall('x:r', ns))

    rows = []
    for r in ws.findall('.//x:sheetData/x:row', ns):
        row = []
        for c in r.findall('x:c', ns):
            t = c.attrib.get('t')
            v = c.find('x:v', ns)
            val = v.text if v is not None else ''
            if t == 's':
                try:
                    val = sst.get(int(val), val)
                except Exception:
                    pass
            row.append(val)
        rows.append(row)
    return rows

def ttl_escape(s: str) -> str:
    return (s or '').replace('"', '\"')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', default='1911Tables.zip', help='Zip file containing the XLSX')
    ap.add_argument('--xlsx-in-zip', default='1911/1911_V2T7_PUB_202306.xlsx', help='Path to XLSX within the zip')
    ap.add_argument('--sheet', default='CA_V2T7_1911', help='Worksheet name inside the XLSX')
    ap.add_argument('--place-col', default='V2T7_1911', help='Column holding the place ID for the year')
    ap.add_argument('--name-col', default='PR_CD_CSD', help='Column with the place label')
    ap.add_argument('--irish-col', default='BRIT_IRISH_1911', help='Column with Irish counts for the year')
    ap.add_argument('--year', default='1911', help='Year string, e.g., 1911')
    ap.add_argument('--base', default='https://example.org/', help='Base URI (will append year paths)')
    ap.add_argument('--out', default='generated/rdf/pei_irish_1911_crm.ttl')
    args = ap.parse_args()

    # Read selected workbook/sheet
    import io, zipfile, xml.etree.ElementTree as ET
    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
          'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    with zipfile.ZipFile(args.zip) as oz:
        xbytes = oz.read(args.xlsx_in_zip)
    z = zipfile.ZipFile(io.BytesIO(xbytes))
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    name2rid = {s.attrib.get('name'): s.attrib.get('{%s}id' % ns['r']) for s in wb.find('x:sheets', ns)}
    if args.sheet not in name2rid:
        raise SystemExit(f"Sheet '{args.sheet}' not found. Available: {sorted(name2rid)}")
    rid = name2rid[args.sheet]
    rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    id2t = {r.attrib['Id']: r.attrib['Target'] for r in rels}
    ws = ET.fromstring(z.read('xl/' + id2t[rid]))
    sst = {}
    if 'xl/sharedStrings.xml' in z.namelist():
        sst_xml = ET.fromstring(z.read('xl/sharedStrings.xml'))
        for idx, si in enumerate(sst_xml.findall('x:si', ns)):
            t = si.find('x:t', ns)
            if t is not None and t.text is not None:
                sst[idx] = t.text
            else:
                sst[idx] = ''.join((r.find('x:t', ns).text or '') for r in si.findall('x:r', ns))
    rows = []
    for r in ws.findall('.//x:sheetData/x:row', ns):
        row = []
        for c in r.findall('x:c', ns):
            t = c.attrib.get('t')
            v = c.find('x:v', ns)
            val = v.text if v is not None else ''
            if t == 's':
                try:
                    val = sst.get(int(val), val)
                except Exception:
                    pass
            row.append(val)
        rows.append(row)
    header = rows[0]
    idx = {h: i for i, h in enumerate(header)}
    required = [args.place_col, 'PR', 'CD_NO', 'CSD_NO', args.name_col, args.irish_col]
    for c in required:
        if c not in idx:
            raise SystemExit(f"Missing column in V2T7: {c}")

    # Base: year-scoped to avoid accidental cross-year identity
    year = str(args.year)
    base = args.base.rstrip('/') + f'/{year}/'
    lines = []
    add = lines.append
    add('@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .')
    add('@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .')
    add('@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .')
    add('')

    # Global timespan for 1911
    add(f'<{base}timespan/1911> a crm:E52_Time-Span ;')
    add('  crm:P82a_begin_of_the_begin "1911-01-01"^^xsd:date ;')
    add('  crm:P82b_end_of_the_end "1911-12-31"^^xsd:date .\n')

    add(f'<{base}unit/person> a crm:E58_Measurement_Unit ; rdfs:label "person" .')
    add(f'<{base}measurementType/irish_population_{year}> a crm:E55_Type ; rdfs:label "Irish origin population ({year})" .\n')

    count=0
    for r in rows[1:]:
        if r[idx['PR']] != 'PE':
            continue
        if r[idx['CSD_NO']] == '0':
            continue  # focus on CSD level
        pid = r[idx[args.place_col]]
        name = ttl_escape(r[idx[args.name_col]])
        val = (r[idx[args.irish_col]] or '').strip()
        if not val:
            continue
        # Place
        add(f"<{base}place/{pid}> a crm:E53_Place ; rdfs:label \"{name}\" .")
        # Measurement + Dimension per place
        meas = f"<{base}measurement/{year}/irish/{pid}>"
        dim = f"<{base}dimension/{year}/irish/{pid}>"
        add(f"{meas} a crm:E16_Measurement ;")
        add(f"  crm:P39_measured <{base}place/{pid}> ;")
        add(f"  crm:P2_has_type <{base}measurementType/irish_population_{year}> ;")
        add(f"  crm:P40_observed_dimension {dim} ;")
        add(f"  crm:P4_has_time-span <{base}timespan/1911> .")
        add(f"{dim} a crm:E54_Dimension ; crm:P91_has_unit <{base}unit/person> ; crm:P90_has_value \"{val}\"^^xsd:integer .\n")
        count+=1

    out = args.out
    from pathlib import Path
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text('\n'.join(lines)+"\n", encoding='utf-8')
    print(f"Wrote {out} with {count} Irish measurements.")

if __name__ == '__main__':
    main()
