"""Standalone check: Python standard library, review archive only, no repository.

Reconstruct the 17 cities and 3 provincial totals from the evidence JSONL and
independently compare the pooled accounting with the reported CSV results.
"""
from pathlib import Path
from decimal import Decimal
import csv
import gzip
import json

here = Path(__file__).resolve().parent
rows = {}
with gzip.open(here/'source_cells.jsonl.gz', 'rt', encoding='utf-8') as f:
    for line in f:
        c = json.loads(line)
        r = rows.setdefault(c['unit_id'], {'label':c['reporting_label'], 'level':c['reporting_level']})
        r[c['column_key']] = None if c['rdf_decimal'] is None else int(Decimal(c['rdf_decimal']))
cities = [r for r in rows.values() if r['level']=='census_subdivision_reporting_unit' and r['label'].endswith(', C')]
provinces = [r for r in rows.values() if r['level']=='province_or_territory_total']
assert len(cities)==17 and len(provinces)==3
a={c:sum(r[c] for r in cities) for c in 'GHIJKLMNO'}
b={c:sum(r[c] for r in provinces)-a[c] for c in 'GHIJKLMNO'}
gap = 100*(b['H']/b['G']-a['H']/a['G'])
within = composition = 0
for m,f in [('J','K'),('L','M'),('N','O')]:
    wa,wb=(a[m]+a[f])/a['G'],(b[m]+b[f])/b['G']
    pa,pb=a[m]/(a[m]+a[f]),b[m]/(b[m]+b[f])
    within += 100*(wa+wb)/2*(pb-pa)
    composition += 100*(pa+pb)/2*(wb-wa)
reported = next(r for r in csv.DictReader((here/'decomposition.csv').open()) if r['province']=='Prairies')
for field,v in [('gap_pp',gap),('within_pp',within),('composition_pp',composition)]:
    assert abs(v-float(reported[field])) < 1e-10
assert abs(gap-within-composition)<1e-10
print(json.dumps({'city_population':a['G'],'remainder_population':b['G'],
                  'gap_pp':gap,'within_pp':within,'composition_pp':composition,
                  'matches_reported_results':True},indent=2))
