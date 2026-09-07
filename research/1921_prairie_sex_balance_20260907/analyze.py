"""Reproduce an exploratory historical analysis from current census source cells.

Run from any directory. Reads only the specified current sources, never older
research outputs. Python standard library; matplotlib is optional for figures.
"""
from pathlib import Path
from decimal import Decimal
from fractions import Fraction as F
import csv
import gzip
import hashlib
import json
import platform
import re
import sqlite3

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KEY = '1921_V1T16_PUB_202306'
SOURCE = ROOT / 'data_quality/lod_census_sources' / KEY
COLS = list('GHIJKLMNO')
GROUPS = {'All': ('H', 'I'), 'Canadian-born': ('J', 'K'),
          'British-born': ('L', 'M'), 'Foreign-born': ('N', 'O')}
PRAIRIES = ('MB', 'SK', 'AB')


def dump(name, value):
    (HERE / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def csvout(name, rows):
    if not rows:
        return
    with (HERE / name).open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def aggregate(rows):
    assert rows and all(r[c] is not None for r in rows for c in COLS)
    return {c: sum(r[c] for r in rows) for c in COLS}


def subtract(a, b):
    result = {c: a[c] - b[c] for c in COLS}
    assert min(result.values()) >= 0
    return result


def identities(r):
    return (r['G'] == r['H'] + r['I'] and
            r['H'] == r['J'] + r['L'] + r['N'] and
            r['I'] == r['K'] + r['M'] + r['O'])


def decomposition(a, b):
    """Exact symmetric decomposition of male share B minus A (Kitagawa form)."""
    within = composition = F(0)
    contributions = {}
    for group, (m, f) in list(GROUPS.items())[1:]:
        na, nb = a[m] + a[f], b[m] + b[f]
        assert na and nb
        wa, wb = F(na, a['G']), F(nb, b['G'])
        pa, pb = F(a[m], na), F(b[m], nb)
        w = (wa + wb) * (pb - pa) / 2
        c = (pa + pb) * (wb - wa) / 2
        within += w
        composition += c
        contributions[group + '_within_pp'] = float(100 * w)
    gap = F(b['H'], b['G']) - F(a['H'], a['G'])
    assert within + composition == gap
    return {'gap_pp': float(100 * gap), 'within_pp': float(100 * within),
            'composition_pp': float(100 * composition),
            'within_percent_of_gap': float(100 * within / gap), **contributions}


def main():
    dbpath = SOURCE / 'source_observations.sqlite'
    with sqlite3.connect(f'file:{dbpath}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        source = dict(db.execute('SELECT * FROM source').fetchone())
        rows = {r['unit_id']: dict(r) for r in db.execute('SELECT * FROM reporting_units')}
        observations = [dict(r) for r in db.execute('SELECT * FROM observations')]
    for o in observations:
        val = Decimal(o['numeric_value']) if o['value_status'] == 'numeric' else None
        assert val is None or (val == val.to_integral_value() and val >= 0)
        rows[o['unit_id']][o['column_key']] = int(val) if val is not None else None
    local = [r for r in rows.values() if r['province'] in PRAIRIES and
             r['reporting_level'] == 'census_subdivision_reporting_unit']
    provinces = [r for r in rows.values() if r['province'] in PRAIRIES and
                 r['reporting_level'] == 'province_or_territory_total']
    cities = [r for r in local if r['label'].endswith(', C')]
    assert len(cities) == 17 and len(local) == 1519
    assert all(identities(r) for r in cities + provinces)
    total = aggregate(provinces)
    main_totals, ratios, decomps, sensitivities = [], [], [], []
    for p in (*PRAIRIES, 'Prairies'):
        ps = provinces if p == 'Prairies' else [r for r in provinces if r['province'] == p]
        cs = cities if p == 'Prairies' else [r for r in cities if r['province'] == p]
        a, t = aggregate(cs), aggregate(ps)
        b = subtract(t, a)
        assert identities(a) and identities(b)
        decomps.append({'province': p, **decomposition(a, b)})
        for area, r in [('Cities', a), ('Remainder', b), ('Province total', t)]:
            main_totals.append({'province': p, 'area': area, **r})
            for group, (m, f) in GROUPS.items():
                ratios.append({'province': p, 'area': area, 'birthplace': group,
                               'males': r[m], 'females': r[f], 'male_surplus': r[m] - r[f],
                               'males_per_100_females': 100 * r[m] / r[f],
                               'male_percent': 100 * r[m] / (r[m] + r[f])})

    # Remainder always means provincial total minus the explicit selected units.
    # Excluding a city from the entire comparison also subtracts it from the total.
    def sensitivity(label, selected, excluded=()):
        adjusted = subtract(total, aggregate(list(excluded))) if excluded else total
        a = aggregate(selected)
        b = subtract(adjusted, a)
        sensitivities.append({'comparison': label, 'selected_units': len(selected),
                              'selected_population': a['G'], 'remainder_population': b['G'],
                              **decomposition(a, b)})

    sensitivity('17 cities versus remainder', cities)
    sensitivity('Cities population >= 10000 versus remainder', [r for r in cities if r['G'] >= 10000])
    winnipeg = [r for r in cities if r['label'] == 'Winnipeg, C']
    sensitivity('Exclude Winnipeg from both sides', [r for r in cities if r not in winnipeg], winnipeg)
    for r in cities:
        sensitivity('Leave out ' + r['label'], [x for x in cities if x != r], [r])

    # Complete-record urban sensitivity never converts blanks into zero.
    urban = [r for r in local if re.search(r', (C|T-V|VL)$', r['label'])]
    complete_urban = [r for r in urban if all(r[c] is not None for c in COLS)]
    sensitivity('All complete-record cities towns villages versus remainder', complete_urban)
    sensitivity('Complete-record urban units >=1000 versus remainder',
                [r for r in complete_urban if r['G'] >= 1000])

    # Local audit: numeric subtotals and within-row accounting constraints.
    reconciliation, incomplete, failed = [], [], []
    for p in PRAIRIES:
        pr = next(r for r in provinces if r['province'] == p)
        ls = [r for r in local if r['province'] == p]
        for c in COLS:
            numeric_sum = sum(r[c] for r in ls if r[c] is not None)
            reconciliation.append({'province': p, 'column': c,
                                   'numeric_subtotal': numeric_sum, 'province_total': pr[c],
                                   'difference': numeric_sum-pr[c],
                                   'blank_cells': sum(r[c] is None for r in ls)})
            assert numeric_sum == pr[c]
    derived_local = []
    for r in local:
        z = dict(r)
        missing = [c for c in COLS if r[c] is None]
        if missing:
            # Only for an explicitly labelled sensitivity: nonnegative missing
            # components are uniquely zero if known components exhaust each sex.
            # A few one-sex units leave the female total itself blank.
            for parent, parts in [('G', 'HI'), ('H', 'JLN'), ('I', 'KMO')]:
                if z[parent] is not None and sum(z[c] for c in parts if z[c] is not None) == z[parent]:
                    for c in parts:
                        if z[c] is None:
                            z[c] = 0
            uniquely_zero = all(z[c] is not None for c in COLS) and identities(z)
            incomplete.append({'excel_row': r['excel_row'], 'province': r['province'],
                               'label': r['label'], 'missing_columns': ','.join(missing),
                               'uniquely_zero_by_nonnegative_accounting': uniquely_zero})
            if not uniquely_zero:
                failed.append(r['excel_row'])
                continue
            for c in missing:
                z[c] = 0
        if not identities(z):
            failed.append(r['excel_row'])
            continue
        derived_local.append(z)
    derived_urban = [r for r in derived_local if re.search(r', (C|T-V|VL)$', r['label'])]
    if not failed:
        sensitivity('All urban; accounting-derived zeros sensitivity', derived_urban)
        sensitivity('Urban >=1000; accounting-derived zeros sensitivity',
                    [r for r in derived_urban if r['G'] >= 1000])

    # Same-table CD comparisons: hierarchy from PR/CD_NO, never a GIS code join.
    divisions = [r for r in rows.values() if r['province'] in PRAIRIES and
                 r['reporting_level'] == 'census_division_total']
    cdcomparisons = []
    for d in divisions:
        md = json.loads(d['source_metadata_json'])
        cs = [r for r in cities if r['province'] == d['province'] and
              json.loads(r['source_metadata_json'])['CD_NO'] == md['CD_NO']]
        if cs and all(d[c] is not None for c in COLS):
            a, b = aggregate(cs), subtract(d, aggregate(cs))
            if b['G'] and all(b[m]+b[f] for m, f in list(GROUPS.values())[1:]):
                cdcomparisons.append({'province': d['province'], 'cd_label': d['label'],
                                      'cd_row': d['excel_row'], 'cities': '; '.join(r['label'] for r in cs),
                                      **decomposition(a, b)})

    city_rows = []
    for r in cities:
        city_rows.append({k: r[k] for k in ['excel_row', 'province', 'label', 'unit_id', *COLS]})
        for group, (m, f) in GROUPS.items():
            city_rows[-1][group + '_ratio'] = 100 * r[m] / r[f]
    main_ids = {r['unit_id'] for r in cities + provinces}
    selected_ids = {r['unit_id'] for r in local + provinces + divisions}
    evidence = []
    jp = ROOT / 'data_quality/rdf_site/sources' / KEY / 'cells.jsonl.gz'
    with gzip.open(jp, 'rt', encoding='utf-8') as f:
        for line in f:
            cell = json.loads(line)
            if cell['unit_id'] in selected_ids:
                evidence.append(cell)
    assert len(evidence) == len(selected_ids) * 9
    with gzip.open(HERE / 'source_cells.jsonl.gz', 'wt', encoding='utf-8') as f:
        for cell in evidence:
            f.write(json.dumps(cell, ensure_ascii=False) + '\n')
    citations = []
    for c in evidence:
        interpreted = None if c['rdf_decimal'] is None else int(Decimal(c['rdf_decimal']))
        assert interpreted == rows[c['unit_id']][c['column_key']]
        if c['unit_id'] in main_ids:
            citations.append({'unit_id': c['unit_id'], 'label': c['reporting_label'],
                              'column': c['column_key'], 'value': c['rdf_decimal'],
                              'citation_url': c['citation_url'], 'rdf_id': c['rdf_id'],
                              'workbook_sha256': c['workbook_sha256']})
    csvout('cities.csv', city_rows)
    csvout('main_totals.csv', main_totals)
    csvout('ratios.csv', ratios)
    csvout('decomposition.csv', decomps)
    csvout('sensitivity.csv', sensitivities)
    csvout('within_divisions.csv', cdcomparisons)
    csvout('reconciliation.csv', reconciliation)
    csvout('blank_cell_audit.csv', incomplete)
    csvout('main_citations.csv', citations)
    dump('validation.json', {'main_city_count': len(cities), 'local_rows': len(local),
                            'city_and_province_cells_complete': True,
                            'main_accounting_identities_exact': True,
                            'decomposition_identities_exact_rational_arithmetic': True,
                            'numeric_subtotals_equal_provinces_all_27_checks': True,
                            'incomplete_local_rows': len(incomplete),
                            'failed_local_accounting_rows': failed,
                            'urban_rows': len(urban), 'complete_urban_rows': len(complete_urban),
                            'same_division_comparisons': len(cdcomparisons),
                            'same_division_positive_gaps': sum(r['gap_pp'] > 0 for r in cdcomparisons),
                            'extracted_cells': len(evidence), 'main_citation_cells': len(citations),
                            'jsonl_sqlite_values_match': True})
    dump('provenance.json', {'analysis_date': '2026-09-07', 'python': platform.python_version(),
                             'source': source, 'sqlite_sha256': digest(dbpath),
                             'public_jsonl_sha256': digest(jp),
                             'catalog_sha256': digest(SOURCE.parent / 'catalog.json'),
                             'research_status': 'Exploratory; not preregistered; no past repo research read',
                             'primary_partition': 'Exact source label suffix , C in MB/SK/AB; remainder by provincial subtraction',
                             'no_age_adjustment': True})
    print(json.dumps({'pooled_decomposition': decomps[-1],
                      'sensitivity_comparisons': len(sensitivities),
                      'within_divisions': len(cdcomparisons),
                      'failed_local_rows': failed}, indent=2))


if __name__ == '__main__':
    main()
