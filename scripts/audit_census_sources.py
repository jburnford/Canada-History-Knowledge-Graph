#!/usr/bin/env python3
"""Write review inventories for staged source identifiers and cell semantics."""

import argparse
import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path

from _config import REPO_ROOT


def audit(root):
    catalog = json.loads((root/'catalog.json').read_text())
    variables, identities, texts = [], [], []
    statuses = Counter()
    for source in catalog['sources']:
        key = source['source_key']
        db = sqlite3.connect(root/key/'source_observations.sqlite')
        db.row_factory = sqlite3.Row
        duplicate_codes = set(source['duplicate_source_codes'])
        duplicate_headers = set(source['duplicate_statistical_headers'])
        for row in db.execute("SELECT * FROM source_columns WHERE column_role!='metadata' ORDER BY column_index"):
            issues = []
            if not row['definition']: issues.append('missing_variable_definition')
            if row['unit'] is None: issues.append('unit_requires_interpretation')
            if row['source_column'] in duplicate_headers: issues.append('repeated_header_separate_column')
            variables.append(dict(source=key, column=row['column_key'], variable=row['source_column'],
                                  definition=row['definition'], unit=row['unit'], unit_status=row['unit_status'],
                                  reference_year=row['reference_year'], reference_period_kind=row['reference_period_kind'],
                                  issues=';'.join(issues), definition_evidence=row['definition_source_json']))
        for row in db.execute('SELECT * FROM reporting_units ORDER BY excel_row'):
            issues = []
            if row['source_code'] in duplicate_codes: issues.append('duplicate_code_distinct_reporting_rows')
            if row['reporting_level'] == 'unresolved_reporting_level': issues.append('reporting_level_requires_interpretation')
            metadata = json.loads(row['source_metadata_json'])
            year = metadata.get('YEAR')
            if year is not None and str(year) not in {str(source['census_vintage']), str(float(source['census_vintage']))}:
                issues.append('source_year_metadata_requires_interpretation')
            if issues:
                identities.append(dict(source=key, excel_row=row['excel_row'], source_code=row['source_code'],
                                       label=row['label'], issues=';'.join(issues), metadata=row['source_metadata_json']))
        query = """SELECT source_column,column_key,raw_value_json,COUNT(*) AS cells,MIN(source_cell) AS example_cell
                   FROM observations WHERE value_status='source_text_requires_interpretation'
                   GROUP BY source_column,column_key,raw_value_json ORDER BY column_key,raw_value_json"""
        for row in db.execute(query):
            raw = json.loads(row['raw_value_json'])
            kind = 'whitespace_or_empty_string' if isinstance(raw, str) and not raw.strip() else 'non_numeric_source_text'
            texts.append(dict(source=key, column=row['column_key'], variable=row['source_column'],
                              original_value_json=row['raw_value_json'], cells=row['cells'],
                              example_cell=row['example_cell'], review_category=kind))
            statuses[kind] += row['cells']
        db.close()
    for name, records, fields in [
        ('variable_inventory.csv', variables, ['source','column','variable','definition','unit','unit_status',
                                               'reference_year','reference_period_kind','issues','definition_evidence']),
        ('source_identity_review.csv', identities, ['source','excel_row','source_code','label','issues','metadata']),
        ('text_value_review.csv', texts, ['source','column','variable','original_value_json','cells','example_cell','review_category'])]:
        with (root/name).open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader(); writer.writerows(records)
    result = dict(source_variables=len(variables), variable_columns_with_review_flags=sum(bool(r['issues']) for r in variables),
                  reporting_rows_with_review_flags=len(identities), text_cells_by_category=dict(statuses),
                  source_data_modified=False)
    (root/'review-summary.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-root', type=Path, default=REPO_ROOT/'data_quality/lod_census_sources')
    args = ap.parse_args()
    print(json.dumps(audit(args.source_root), indent=2))
