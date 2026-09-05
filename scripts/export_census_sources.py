#!/usr/bin/env python3
"""Export and fully reconcile each staged canonical source workbook graph."""

import argparse
import json
from pathlib import Path

from _config import REPO_ROOT
from export_1911_reporting_rdf import export
from validate_reporting_rdf import validate


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-root', type=Path, default=REPO_ROOT/'data_quality/lod_census_sources')
    ap.add_argument('--only', help='Only source directories containing this string')
    args = ap.parse_args()
    catalog = json.loads((args.source_root/'catalog.json').read_text())
    results = []
    # Use the manifest, not a directory glob that could include obsolete files.
    for source in catalog['sources']:
        if args.only and args.only not in source['source_key']:
            continue
        directory = args.source_root/source['source_key']
        database = directory/'source_observations.sqlite'
        target = directory/'source_observations.nt.gz'
        result = export(database, target)
        print(json.dumps(dict(source=source['source_key'], phase='exported', **result)), flush=True)
        validation = validate(database, target)
        target.with_suffix('.validation.json').write_text(json.dumps(validation, indent=2)+'\n')
        if validation['errors']:
            raise ValueError(validation)
        results.append(dict(source=source['source_key'], export=result, validation=validation))
        print(json.dumps(dict(source=source['source_key'], phase='validated', **validation)), flush=True)
    if not results:
        raise ValueError('No source graphs selected')
    result = dict(workbooks=len(results), source_cells=sum(r['export']['source_cells'] for r in results),
                  numeric_observations=sum(r['export']['numeric_observations'] for r in results),
                  parsed_triples=sum(r['validation']['parsed_triples'] for r in results), sources=results)
    filename = 'rdf-catalog.json' if not args.only else 'selected-rdf-catalog.json'
    (args.source_root/filename).write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
