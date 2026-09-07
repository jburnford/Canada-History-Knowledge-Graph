"""Independent checks of the analysis against workbook and printed-table readings."""
from pathlib import Path
from decimal import Decimal
import csv
import hashlib
import json
import sqlite3
import openpyxl

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
meta = json.loads((HERE / 'provenance.json').read_text())
source = meta['source']
path = Path(source['path'])
assert hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256']
citations = list(csv.DictReader((HERE / 'main_citations.csv').open()))
wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
ws = wb[source['sheet']]
wanted = {int(r['unit_id'].rsplit('_', 1)[1]) for r in citations}
raw = {row[0].row: row for row in ws.iter_rows() if row[0].row in wanted}
for r in citations:
    rownum = int(r['unit_id'].rsplit('_', 1)[1])
    colnum = openpyxl.utils.column_index_from_string(r['column'])
    assert Decimal(str(raw[rownum][colnum - 1].value)) == Decimal(r['value'])
wb.close()

# Read by eye from the downloaded original print, not copied from the workbook.
# Fields: workbook row, printed page, population, all M/F, Canadian M/F,
# British M/F, foreign M/F. These are a targeted audit of six city rows.
print_readings = [
    [3957, 313, 6766, 3426, 3340, 2350, 2464, 603, 498, 473, 378],
    [3958, 313, 12821, 6323, 6498, 3963, 4243, 1191, 1177, 1169, 1078],
    [3959, 313, 179087, 89737, 89350, 45163, 48691, 26400, 24271, 18174, 16388],
    [4349, 320, 34432, 17801, 16631, 9689, 9723, 4847, 4195, 3265, 2713],
    [5104, 332, 63305, 31826, 31479, 16083, 17014, 10903, 10088, 4840, 4377],
    [5293, 335, 58821, 29609, 29212, 16286, 16406, 8124, 7968, 5199, 4838],
]
cities = {int(r['excel_row']): r for r in csv.DictReader((HERE/'cities.csv').open())}
for rownum, page, *values in print_readings:
    assert [int(cities[rownum][c]) for c in 'GHIJKLMNO'] == values

# Independently calculate the main pooled result, using only raw workbook cells.
pr = [3877, 4086, 4912]
cr = list(cities)
def cell(row, col):
    return int(raw[row][openpyxl.utils.column_index_from_string(col) - 1].value)
city = {c: sum(cell(r,c) for r in cr) for c in 'GHIJKLMNO'}
rest = {c: sum(cell(r,c) for r in pr) - city[c] for c in 'GHIJKLMNO'}
# Direct standardization in two orders, then averaging, independently checks
# the symmetric decomposition used by analyze.py.
within_city_weights = within_rest_weights = 0
for m,f in [('J','K'),('L','M'),('N','O')]:
    nc,nr=city[m]+city[f],rest[m]+rest[f]
    pc,prate=city[m]/nc,rest[m]/nr
    within_city_weights += nc/city['G']*(prate-pc)
    within_rest_weights += nr/rest['G']*(prate-pc)
within = 100*(within_city_weights+within_rest_weights)/2
record = next(r for r in csv.DictReader((HERE/'decomposition.csv').open()) if r['province']=='Prairies')
assert abs(within-float(record['within_pp'])) < 1e-10

# Province-level cross-table check on urban classification. Birthplace blanks
# play no role: only the complete population column is used here.
urban_totals = {}
p = ROOT/'data_quality/lod_census_sources/1921_V1T16_PUB_202306/source_observations.sqlite'
with sqlite3.connect(f'file:{p}?mode=ro',uri=True) as db:
    for province, label, value in db.execute("""SELECT r.province,r.label,o.numeric_value
      FROM reporting_units r JOIN observations o USING(unit_id)
      WHERE r.province IN ('MB','SK','AB')
      AND r.reporting_level='census_subdivision_reporting_unit' AND o.column_key='G'"""):
        if label.endswith((', C', ', T-V', ', VL')):
            urban_totals[province] = urban_totals.get(province, 0) + int(value)
p3 = ROOT/'data_quality/lod_census_sources/1921_V3T3_PUB_202306/source_observations.sqlite'
with sqlite3.connect(f'file:{p3}?mode=ro',uri=True) as db:
    db.row_factory = sqlite3.Row
    p3_source = dict(db.execute('SELECT * FROM source').fetchone())
    published_urban = dict(db.execute("""SELECT r.province,o.numeric_value
      FROM reporting_units r JOIN observations o USING(unit_id)
      WHERE r.province IN ('MB','SK','AB')
      AND r.reporting_level='province_or_territory_total' AND o.source_column='U_POP_TOT_1921'"""))
urban_differences = {p: urban_totals[p]-int(published_urban[p]) for p in urban_totals}
assert all(x==0 for x in urban_differences.values())
report = {'original_workbook_sha256_matches': True, 'workbook_cells_checked': len(citations),
          'printed_cells_visually_checked': len(print_readings)*9,
          'printed_pages': sorted({r[1] for r in print_readings}),
          'printed_audit_mismatches': 0,
          'independent_decomposition_within_pp': within,
          'urban_population_cross_table_differences': urban_differences,
          'urban_population_by_province': urban_totals,
          'urban_crosscheck_source': p3_source,
          'urban_crosscheck_sqlite_sha256': hashlib.sha256(p3.read_bytes()).hexdigest(),
          'external_census_volume_sha256': hashlib.sha256((HERE/'external_sources/census_1921_volume1.pdf').read_bytes()).hexdigest(),
          'limits': '54 printed cells checked; not a complete printed-source audit. No age adjustment or causal identification.'}
(HERE/'independent_validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
