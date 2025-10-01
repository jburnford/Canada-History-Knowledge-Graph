#!/usr/bin/env python3
"""
Generate RDF (Turtle) with CIDOC-CRM measurements for PEI CSDs for a given year,
including all available measures we have tables for in the provided zips.

Years supported out of the box (based on files present in repo root):
- 1891: population (V1T3), agriculture (V4T2), livestock/dairy (V4T3)
- 1901: population (V1T7)

Usage examples:
  python3 scripts/rdf_generate_pei_all_crm.py --year 1891 --out generated/rdf/pei_all_1891_crm.ttl
  python3 scripts/rdf_generate_pei_all_crm.py --year 1901 --out generated/rdf/pei_all_1901_crm.ttl

Notes:
- Uses year-scoped URIs to avoid cross-year identity.
- Emits one crm:E16_Measurement per (place, measure), linked to a crm:E54_Dimension with value+unit.
- Only includes PEI (PR == 'PE') and CSD-level rows (CSD_NO != '0').
"""
import argparse
import io
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


NS = {
    'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
}


def read_sheet_rows_from_zip(zip_path: Path, xlsx_in_zip: str, sheet_name: str):
    with zipfile.ZipFile(zip_path) as oz:
        xbytes = oz.read(xlsx_in_zip)
    z = zipfile.ZipFile(io.BytesIO(xbytes))
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    name2rid = {s.attrib.get('name'): s.attrib.get('{%s}id' % NS['r']) for s in wb.find('x:sheets', NS)}
    if sheet_name not in name2rid:
        raise SystemExit(f"Sheet '{sheet_name}' not found in {xlsx_in_zip}. Available: {sorted(name2rid)}")
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
    return rows


def ttl_escape(s: str) -> str:
    return (s or '').replace('"', '\"')


def build_config(year: str):
    """Return list of dataset configs for the given year.
    Each config: dict(zip, xlsx, sheet, id_col, name_col, measures: {col: (code, label, unit)})
    """
    y = str(year)
    if y == '1901':
        return [
            {
                'zip': Path('1901Tables.zip'),
                'xlsx': '1901/1901_V1T7_PUB_202306.xlsx',
                'sheet': 'CA_V1T7_1901',
                'id_col': 'V1T7_1901',
                'name_col': 'PR_CD_CSD',
                'measures': {
                    'POP_TOT_1901': ('population_total', 'Population Total', 'person'),
                    'POP_M_1901': ('population_male', 'Population Male', 'person'),
                    'POP_F_1901': ('population_female', 'Population Female', 'person'),
                    'HOUSES_1901': ('houses', 'Houses', 'count'),
                    'FAMILIES_1901': ('families', 'Families', 'count'),
                }
            }
        ]
    if y == '1891':
        return [
            {
                'zip': Path('1891Tables.zip'),
                'xlsx': '1891/1891_V1T3_PUB_202306.xlsx',
                'sheet': 'CA_V1T3_1891',
                'id_col': 'V1T3_1891',
                'name_col': 'PR_CD_CSD',
                'measures': {
                    'POP_TOT_1891': ('population_total', 'Population Total', 'person'),
                    'POP_M_1891': ('population_male', 'Population Male', 'person'),
                    'POP_F_1891': ('population_female', 'Population Female', 'person'),
                    'FAMILIES_1891': ('families', 'Families', 'count'),
                }
            },
            {
                'zip': Path('1891Tables.zip'),
                'xlsx': '1891/1891_V4T2_PUB_202306.xlsx',
                'sheet': 'CA_V4T2_1891',
                'id_col': 'V4T2_1891',
                'name_col': 'PR_CD_CSD',
                'measures': {
                    'WHT_AC': ('wheat_area_acres', 'Wheat Area', 'acre'),
                    'WHT_SP_BU': ('wheat_spring_bushels', 'Wheat Spring', 'bushel'),
                    'WHT_FALL_BU': ('wheat_fall_bushels', 'Wheat Fall', 'bushel'),
                    'OAT_AC': ('oats_area_acres', 'Oats Area', 'acre'),
                    'OAT_BU': ('oats_bushels', 'Oats Production', 'bushel'),
                    'HAY_AC': ('hay_area_acres', 'Hay Area', 'acre'),
                    'HAY_TONS': ('hay_tons', 'Hay Production', 'ton'),
                    'POT_AC': ('potatoes_area_acres', 'Potatoes Area', 'acre'),
                    'POT_BU': ('potatoes_bushels', 'Potatoes Production', 'bushel'),
                }
            },
            {
                'zip': Path('1891Tables.zip'),
                'xlsx': '1891/1891_V4T3_PUB_202306.xlsx',
                'sheet': 'CA_V4T3_1891',
                'id_col': 'V4T3_1891',
                'name_col': 'PR_CD_CSD',
                'measures': {
                    'MILK_COWS': ('milk_cows', 'Milk Cows', 'head'),
                    'OTHER_HRN_CATTLE': ('other_cattle', 'Other Horned Cattle', 'head'),
                    'SHEEP': ('sheep', 'Sheep', 'head'),
                    'SWINE': ('swine', 'Swine', 'head'),
                    'BUTTER_LB': ('butter_lb', 'Butter', 'pound'),
                    'CHEESE_LB': ('cheese_lb', 'Cheese', 'pound'),
                }
            }
        ]
    if y == '1911':
        return [
            {
                'zip': Path('1911Tables.zip'),
                'xlsx': '1911/1911_V1T1_PUB_202306.xlsx',
                'sheet': 'CA_V1T1_1911',
                'id_col': 'V1T1_1911',
                'name_col': 'PR_CD_CSD',
                'measures': 'AUTO',
                'var_sheet': 'Variables'
            },
            {
                'zip': Path('1911Tables.zip'),
                'xlsx': '1911/1911_V1T2_PUB_202306.xlsx',
                'sheet': 'CA_V1T2_1911',
                'id_col': 'V1T2_1911',
                'name_col': 'PR_CD_CSD',
                'measures': 'AUTO',
                'var_sheet': 'Variables'
            },
            {
                'zip': Path('1911Tables.zip'),
                'xlsx': '1911/1911_V2T2_PUB_202306.xlsx',
                'sheet': 'CA_V2T2_1911',
                'id_col': 'V2T2_1911',
                'name_col': 'PR_CD_CSD',
                'measures': 'AUTO',
                'var_sheet': 'Variables'
            },
            {
                'zip': Path('1911Tables.zip'),
                'xlsx': '1911/1911_V2T7_PUB_202306.xlsx',
                'sheet': 'CA_V2T7_1911',
                'id_col': 'V2T7_1911',
                'name_col': 'PR_CD_CSD',
                'measures': 'AUTO',
                'var_sheet': 'Variables'
            }
        ]
    raise SystemExit(f"Year not supported: {year}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--year', required=True, help='Year to generate for (e.g., 1891, 1901)')
    ap.add_argument('--base', default='https://example.org/', help='Base URI (year will be appended)')
    ap.add_argument('--out', required=True, help='Output TTL path')
    ap.add_argument('--province', default='PE', help='Province code to include (e.g., PE, SK) or ALL for entire Canada')
    args = ap.parse_args()

    year = str(args.year)
    base = args.base.rstrip('/') + f'/{year}/'

    datasets = build_config(year)
    lines = []
    add = lines.append
    add('@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .')
    add('@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .')
    add('@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .')
    add('')

    # Year timespan
    add(f'<{base}timespan/{year}> a crm:E52_Time-Span ;')
    add(f'  crm:P82a_begin_of_the_begin "{year}-01-01"^^xsd:date ;')
    add(f'  crm:P82b_end_of_the_end "{year}-12-31"^^xsd:date .\n')

    # Measurement units (basic set)
    add(f'<{base}unit/person> a crm:E58_Measurement_Unit ; rdfs:label "person" .')
    add(f'<{base}unit/count> a crm:E58_Measurement_Unit ; rdfs:label "count" .')
    add(f'<{base}unit/acre> a crm:E58_Measurement_Unit ; rdfs:label "acre" .')
    add(f'<{base}unit/bushel> a crm:E58_Measurement_Unit ; rdfs:label "bushel" .')
    add(f'<{base}unit/ton> a crm:E58_Measurement_Unit ; rdfs:label "ton" .')
    add(f'<{base}unit/head> a crm:E58_Measurement_Unit ; rdfs:label "head" .')
    add(f'<{base}unit/pound> a crm:E58_Measurement_Unit ; rdfs:label "pound" .')
    add(f'<{base}unit/square_mile> a crm:E58_Measurement_Unit ; rdfs:label "square mile" .')
    add('')

    # For deduping place declarations across datasets
    declared_places = set()

    province_filter = (args.province or 'PE').upper()

    for ds in datasets:
        rows = read_sheet_rows_from_zip(ds['zip'], ds['xlsx'], ds['sheet'])
        hdr = rows[0]
        idx = {h: i for i, h in enumerate(hdr)}

        required = [ds['id_col'], 'PR', 'CD_NO', 'CSD_NO', ds['name_col']]
        for c in required:
            if c not in idx:
                raise SystemExit(f"Missing required column {c} in {ds['xlsx']}:{ds['sheet']}")

        # Determine measures: explicit dict or AUTO detection
        measures = ds['measures']
        if measures == 'AUTO':
            # Optional variables sheet to get friendly labels
            var_labels = {}
            try:
                vrows = read_sheet_rows_from_zip(ds['zip'], ds['xlsx'], ds.get('var_sheet', 'Variables'))
                for vr in vrows[1:]:
                    if len(vr) >= 2 and vr[0] and vr[1]:
                        var_labels[vr[0]] = vr[1]
            except Exception:
                var_labels = {}

            skip = set([ds['id_col'], ds['name_col'], 'ROW_ID', 'PR', 'CD_NO', 'CSD_NO', 'CSD_TYPE', 'NOTES'])
            def unit_for(col: str, label: str):
                u = 'count'
                c = col.upper()
                L = (label or '').upper()
                if 'POP' in c or 'POPULATION' in L:
                    u = 'person'
                elif 'ACRE' in c or 'ACRE' in L:
                    u = 'acre'
                elif 'SQ_MI' in c or 'SQUARE MILE' in L:
                    u = 'square_mile'
                elif c.endswith('_BU') or 'BUSHEL' in L:
                    u = 'bushel'
                elif c.endswith('_LB') or 'POUND' in L:
                    u = 'pound'
                elif 'TON' in c or 'TON' in L:
                    u = 'ton'
                elif 'HOUSE' in c or 'FAMIL' in c:
                    u = 'count'
                return u
            measures = {}
            for col in hdr:
                if col in skip:
                    continue
                # leave out empty/metadata columns by checking a few data rows
                # find at least one non-empty numeric-like value in PEI rows
                col_idx = idx[col]
                numeric_like = False
                for r in rows[1:50]:
                    if len(r) <= col_idx:
                        continue
                    val = (r[col_idx] or '').strip()
                    if not val:
                        continue
                    vtxt = val.replace(',', '')
                    try:
                        float(vtxt)
                        numeric_like = True
                        break
                    except Exception:
                        pass
                if not numeric_like:
                    continue
                label = var_labels.get(col, col)
                code = col.lower()
                u = unit_for(col, label)
                measures[col] = (code, label, u)

        # declare measurement type node per dataset/measure in this year
        for col, (code, label, unit) in measures.items():
            add(f'<{base}measurementType/{code}_{year}> a crm:E55_Type ; rdfs:label "{label} ({year})" .')

        for r in rows[1:]:
            pr = r[idx['PR']]
            if province_filter != 'ALL' and pr != province_filter:
                continue
            if r[idx['CSD_NO']] == '0':
                continue
            pid = r[idx[ds['id_col']]]
            pname = ttl_escape(r[idx[ds['name_col']]])
            # Place
            if pid not in declared_places:
                add(f'<{base}place/{pid}> a crm:E53_Place ; rdfs:label "{pname}" .')
                declared_places.add(pid)

            # Emit measurements for available numeric values
            for col, (code, label, unit) in measures.items():
                if col not in idx:
                    continue
                col_i = idx[col]
                if len(r) <= col_i:
                    continue
                val = (r[col_i] or '').strip()
                if not val:
                    continue
                # Simple numeric check (allow ints/floats)
                vtxt = val.replace(',', '')
                try:
                    float(vtxt)
                except Exception:
                    continue
                muri = f'<{base}measurement/{year}/{code}/{pid}>'
                dim = f'<{base}dimension/{year}/{code}/{pid}>'
                add(f'{muri} a crm:E16_Measurement ;')
                add(f'  crm:P39_measured <{base}place/{pid}> ;')
                add(f'  crm:P2_has_type <{base}measurementType/{code}_{year}> ;')
                add(f'  crm:P40_observed_dimension {dim} ;')
                add(f'  crm:P4_has_time-span <{base}timespan/{year}> .')
                # Choose unit node
                unit_node = {
                    'person': f'<{base}unit/person>',
                    'count': f'<{base}unit/count>',
                    'acre': f'<{base}unit/acre>',
                    'bushel': f'<{base}unit/bushel>',
                    'ton': f'<{base}unit/ton>',
                    'head': f'<{base}unit/head>',
                    'pound': f'<{base}unit/pound>',
                    'square_mile': f'<{base}unit/square_mile>',
                }.get(unit, f'<{base}unit/count>')
                # Integer if whole number, else decimal
                lit_type = 'xsd:integer'
                if ('.' in vtxt) or ('e' in vtxt.lower()):
                    lit_type = 'xsd:decimal'
                add(f'{dim} a crm:E54_Dimension ; crm:P91_has_unit {unit_node} ; crm:P90_has_value "{vtxt}"^^{lit_type} .')
        add('')

    # Add stable anchors for Canada and PEI for this year (no measurements attached here)
    add(f'<{base}place/CA000000> a crm:E53_Place ; rdfs:label "Canada" .')
    add(f'<{base}place/PE000000> a crm:E53_Place ; rdfs:label "Prince Edward Island" .')
    add('')

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"Wrote {out} | places={len(declared_places)} | datasets={len(datasets)}")


if __name__ == '__main__':
    main()
