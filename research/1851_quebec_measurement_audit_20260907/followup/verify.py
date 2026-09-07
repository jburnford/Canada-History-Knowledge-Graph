"""Independent follow-up: printed evidence is manually entered, never inferred from sums.

Run from any directory. Reads current sources; writes only beside this script.
The output is a research correction overlay, not a mutation of source assertions.
"""
import csv
import gzip
import hashlib
import json
import sqlite3
from collections import Counter
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PDF_URL = 'https://publications.gc.ca/collections/collection_2012/statcan/rh-hc/CS98-1851-2-eng.pdf'
HASHES = {
    'CD': 'ac90a90f1e0b552a1575f3e88d58c193f79566f0f9ec29cce9f0ba8cd042c8ca',
    'CSD': '042a4d3fe6f6e8e1c8b802706c014d47c2da5d14019129600b0b05a8f607140f',
}

# Independently read from printed pages 130--135 (PDF pages 188--193, one-based).
# Order is workbook F:BI; None means printed dotted/blank return, never zero.
PRINT = {
    'Saguenay': [2453,335,27,348,819,655,269,
        278678,97155,47766,49260,129,181523,12531,70060,4637,54300,
        7559,41690,4241,30808,6497,70668,158,1317,
        None,None,2053,101667,41,1311,6,327,2,6,
        3,1280162,35950,6919,48445,63636,None,34124,36809,24490,
        4131,6071,4849,3568,20268,6013,81217,None,509,3246,443],
    'St. Maurice': [2886,555,97,584,901,598,151,
        250090,107043,63931,42354,758,143047,10217,80711,882,10691,
        811,7120,4978,36245,30262,525543,4484,37363,
        659,5154,1064,59397,239,11248,216,562,654,97,
        13,2796856,91238,19022,44666,247323,None,26307,75536,30221,
        2576,8908,5503,5575,20070,7503,204253,623,1663,5979,19],
}

# Printed locality row, CSD workbook row, printed value. Names checked against
# printed pp. 118 and 124; output values against pp. 120 and 125.
ARITHMETIC = [
    {'county': 'Richelieu', 'code': 'QC070', 'variable': 'OAT_XX_B',
     'cd_row': 66, 'printed_page': 120, 'printed_total': 194297,
     'details': [(298,680,1818),(299,681,46149),(300,682,3342),
         (301,683,34412),(302,684,15888),(303,689,39096),(304,688,17965),
         (305,687,14472),(306,686,33231),(307,685,17924)]},
    {'county': 'Rouville', 'code': 'QC072', 'variable': 'WHT_XX_B',
     'cd_row': 68, 'printed_page': 125, 'printed_total': 156962,
     'details': [(328,720,6304),(329,721,14081),(330,713,14170),
         (331,714,34227),(332,719,8955),(333,717,19724),(334,712,18592),
         (335,716,11220),(336,722,40304),(337,715,8764),(338,718,9270),
         (339,711,1351)]},
    {'county': 'St. Maurice', 'code': 'QC073', 'variable': 'CTL_CH_N',
     'cd_row': 70, 'printed_page': 135, 'printed_total': 5503,
     'expected_workbook_total': 5508,
     'details': [(365,723,76),(366,737,263),(367,724,2),(368,725,13),
         (369,726,371),(370,727,473),(371,728,944),(372,729,1122),
         (373,730,586),(374,731,102),(375,732,27),(376,733,80),
         (377,734,359),(378,735,1090)]},
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def write_json(name, obj):
    (HERE / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')


def write_csv(name, rows):
    with (HERE / name).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def printed_page(index):
    for end, page in [(12,130),(22,131),(30,132),(40,133),(50,134),(61,135)]:
        if index <= end:
            return page
    raise ValueError(index)


def main():
    require(sha(HERE.parent/'external_sources/census_1851_volume2.pdf') ==
        '107eb0c554f8bc7cdec3974e1776d047dfa0596ef2437ec4c06dfdad511a4a65',
        'printed PDF edition changed')
    db, src, sheets, retrieval = {}, {}, {}, {}
    for kind in ('CD', 'CSD'):
        key = f'1851_V2T6_{kind}_202306'
        path = ROOT / 'data_quality/lod_census_sources' / key / 'source_observations.sqlite'
        db[kind] = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        db[kind].row_factory = sqlite3.Row
        src[kind] = dict(db[kind].execute('select * from source').fetchone())
        require(src[kind]['sha256'] == HASHES[kind], f'{kind}: unexpected staged source')
        require(sha(src[kind]['path']) == HASHES[kind], f'{kind}: workbook changed')
        wb = load_workbook(src[kind]['path'], read_only=True, data_only=True)
        sheets[kind] = {i: list(row) for i, row in enumerate(wb[src[kind]['sheet']].values, 1)}
        wb.close()
        retrieval[kind] = {}
        wanted = {66,68,69,70} if kind == 'CD' else {r for a in ARITHMETIC for _,r,_ in a['details']}
        with gzip.open(ROOT / 'data_quality/rdf_site/sources' / key / 'cells.jsonl.gz', 'rt') as f:
            for line in f:
                cell = json.loads(line)
                row = int(cell['unit_id'].rsplit('_',1)[1])
                if row in wanted:
                    retrieval[kind][(row,cell['column_key'])] = cell

    checked = set()
    def get(kind, row, variable=None, col=None):
        query = '''select o.*,r.label,r.source_code,r.excel_row,c.column_index,c.definition
            from observations o join reporting_units r using(unit_id)
            join source_columns c using(column_key) where r.excel_row=? and '''
        query += 'o.source_column=?' if variable else 'o.column_key=?'
        result = db[kind].execute(query, (row, variable or col)).fetchall()
        require(len(result) == 1, f'ambiguous/missing {kind} {row} {variable or col}')
        o = dict(result[0]); cell = retrieval[kind][(row,o['column_key'])]
        raw = sheets[kind][row][o['column_index']-1]
        require(raw == json.loads(o['raw_value_json']), f'workbook/staging {o["source_cell"]}')
        require(cell['workbook_sha256'] == HASHES[kind], 'retrieval edition mismatch')
        require(cell['value_status'] == o['value_status'], 'retrieval status mismatch')
        require(cell['rdf_decimal'] == o['numeric_value'], 'retrieval numeric mismatch')
        require(cell['raw_value_json'] == o['raw_value_json'], 'retrieval raw value mismatch')
        checked.add((kind,row,o['column_key']))
        return o,cell

    evidence, overlay, exceptions = [], [], []
    for label, row, donor in [('St. Maurice',69,70),('Saguenay',70,69)]:
        require(len(PRINT[label]) == 56, 'manual transcription length')
        for i, value in enumerate(PRINT[label], 6):
            col = get_column_letter(i)
            o, cell = get('CD',row,col=col)
            d,_ = get('CD',donor,col=col)
            require(o['label'] == label, 'source identity changed')
            pv = None if value is None else str(value)
            agrees = d['numeric_value'] == pv
            ev = {'county':label, 'workbook_row':row, 'column':col,
                'variable':o['source_column'], 'workbook_value':o['numeric_value'],
                'opposite_workbook_value':d['numeric_value'], 'printed_value':pv,
                'printed_status':'printed_blank' if pv is None else 'numeric',
                'printed_page':printed_page(i), 'pdf_page':printed_page(i)+58,
                'opposite_row_agrees_with_print':agrees,
                'citation_url':cell['citation_url']}
            evidence.append(ev)
            if not agrees:
                exceptions.append(ev)
            # Keep the original record intact. Corrected interpretation is explicitly nested.
            corrected = dict(cell)
            corrected['research_correction'] = {
                'status':'county_assignment_verified', 'reassigned_numeric_value':d['numeric_value'],
                'reassigned_value_status':d['value_status'], 'printed_numeric_value':pv,
                'printed_value_status':ev['printed_status'],
                'value_adjudication':'opposite_row_matches_print' if agrees else 'printed_total_conflicts_with_constituent_sum; unresolved',
                'basis':'county_rows_transposed',
                'donor_workbook_row':donor, 'printed_page':ev['printed_page'],
                'primary_source_url':PDF_URL + '#page=' + str(ev['pdf_page']),
                'limits':'Reassigns the workbook statistical row; does not validate original enumeration or arithmetic. Printed value retained separately.',
            }
            if col == 'AP':
                corrected['research_correction']['unit_warning'] = (
                    'Printed column combines bundles and tons. This numeric total is bundles; '
                    'separate printed ton totals are 9144 (Saguenay) and 19956 (St. Maurice). '
                    'Do not interpret the original HAY_XX_T/unit metadata as a ton value.')
            overlay.append(corrected)
    require(len(exceptions) == 1 and exceptions[0]['column'] == 'BA'
            and exceptions[0]['county'] == 'St. Maurice', 'unexpected opposite-row discrepancy')

    arithmetic, detail = [], []
    for a in ARITHMETIC:
        o,c = get('CD',a['cd_row'],variable=a['variable'])
        require(o['numeric_value'] == str(a.get('expected_workbook_total',a['printed_total'])),
            'unexpected county workbook value')
        for printrow,row,value in a['details']:
            sub,sc = get('CSD',row,variable=a['variable'])
            require(sub['source_code'].startswith(a['code']), 'county membership mismatch')
            require(sub['numeric_value'] == str(value), 'CSD differs from print')
            detail.append({'county':a['county'], 'printed_row':printrow, 'csd_row':row,
                'locality':sub['label'].strip(), 'variable':a['variable'],
                'printed_value':value, 'workbook_value':sub['numeric_value'],
                'printed_page':a['printed_page'], 'citation_url':sc['citation_url']})
        total = sum(v for _,_,v in a['details'])
        arithmetic.append({'county':a['county'], 'variable':a['variable'],
            'printed_county_total':a['printed_total'], 'sum_of_printed_localities':total,
            'workbook_total_in_audited_row':o['numeric_value'],
            'difference':total-a['printed_total'], 'localities':len(a['details']),
            'diagnosis':'printed_internal_arithmetic_discrepancy; underlying erroneous figure unresolved',
            'printed_page':a['printed_page'], 'county_citation':c['citation_url']})
    require([a['difference'] for a in arithmetic] == [30000,30000,5], 'arithmetic result changed')

    with (HERE.parent / 'county_reconciliation.csv').open() as f:
        screen = list(csv.DictReader(f))
    hits = [r for r in screen if Decimal(r['subtotal_minus_county']) != 0]
    swap_hits = [r for r in hits if r['county_code'] in ('QC073','QC074')]
    counts = dict(Counter(r['status'] for r in hits))
    require(len(hits) == 97 and len(swap_hits) == 16, 'original screening changed')
    require(all(r['status']=='partial_observed_subtotal' for r in swap_hits), 'swap completeness changed')
    for r in swap_hits:
        o,_ = get('CD',69 if r['county_code']=='QC073' else 70,variable=r['variable'])
        idx = o['column_index']-6
        require(str(PRINT[r['county']][idx]) == r['subdivision_observed_subtotal'], 'partial sum mismatch')

    write_csv('all_county_cells.csv', evidence)
    write_csv('arithmetic_discrepancies.csv', arithmetic)
    write_csv('printed_localities.csv', detail)
    write_json('manual_print_transcription.json', {'county_totals_F_to_BI':PRINT, 'arithmetic_checks':ARITHMETIC})
    with (HERE / 'corrected_interpretations.jsonl').open('w') as f:
        for c in overlay:
            f.write(json.dumps(c,ensure_ascii=False,sort_keys=True)+'\n')
    summary = {'verified_digital_cells':len(checked), 'county_cells_reviewed':len(evidence),
        'opposite_row_matches_print':len(evidence)-len(exceptions), 'additional_digit_discrepancies':exceptions,
        'nonzero_original_screening':len(hits), 'screening_status_counts':counts,
        'swap_hits':len(swap_hits), 'swap_hits_are_partial':True,
        'arithmetic_discrepancies':arithmetic, 'workbook_sha256':HASHES,
        'printed_pdf_sha256':sha(HERE.parent/'external_sources/census_1851_volume2.pdf'),
        'production_data_modified':False, 'external_messages_sent':False,
        'verification_limit':'Script checks manually transcribed print values; visual readings are not automated proof.'}
    write_json('verification.json', summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('additional_digit_discrepancies','arithmetic_discrepancies')},indent=2))
    for c in db.values():
        c.close()


if __name__ == '__main__':
    main()
