# Census model specimen

Built and validated on 2026-09-05. This is a staged specimen, not the national
submission export. The [rebuild plan](LOD_REBUILD_PLAN.md) tracks the remaining
work. No paper-related files were read.

## Inputs and scope

The specimen includes every positive incoming 1911 spatial correspondence to
three 1921 areas: Westmeath (`ON142032`), Regina (`SK176022`), and the
Saskatchewan township grouping `SK187010`. The polygons come from the repaired
base GDB layers; correspondence metrics use the audited ESRI:102001 tables.
WKT geometry is exported separately in longitude/latitude with an explicit
OGC CRS84 identifier.

The result has 13 census/map representations: 12 E93 census presences and one
E73 coverage record for NO DATA. There are 10 spatial correspondence
assessments, 16 reported population/density assignments, and three retained
Wikidata mapping records. The Turtle graph contains 716 triples.

Westmeath's two snapshots refer to one historical township, following the
curator discussion and stable census sequence. Other units retain separate
census-defined subjects pending migration of their historical identities.
The pilot does not infer a continuing Regina community from the geometry.

NO DATA retains a polygon and reference date without becoming an E93 census
unit or acquiring a population of zero. Its contribution to the Saskatchewan
crosswalk remains visible. Mapping candidates preserve the existing evidence
and source entity types where available; none substitutes a Wikidata URI for
a local identity or asserts owl:sameAs.

## Observation and date qualifications

The pilot uses POP_TOT and POP_PER_SQ_MI from existing derived observation
CSVs. Density is expressed in persons per square mile. Values and source table
metadata are retained. This validates the model pattern, not the completeness
or accuracy of the legacy extraction. Rebuilding from the original source
tables is still required for omitted reporting units and full cell provenance.

E13 assignments link a census representation to its reported value and source.
Numeric quantities use E54/P90; the implementation preserves nonnumeric source
text separately with an interpretation status. Assignment activity dates are
not invented from census reference dates.

The pilot uses June 1 for the 1911 and 1921 reference dates, supported by the
[Canada Year Book](https://www66.statcan.gc.ca/eng/1927-28/192701430101_p.%20101.pdf).
A correspondence carries both reference spans and the later census
configuration date. It does not claim a municipal incorporation event.

## Validation and reproduction

```bash
python3 scripts/build_lod_model_pilot.py
python3 scripts/validate_lod_model.py data_quality/lod_model_pilot/model.ttl
python3 -m pytest -q tests/test_lod_model.py tests/test_gis_connections.py
```

The 37 regression tests pass. Targeted validation of the serialized specimen
reports no errors for presence subjects and ranges, polygon representations,
numeric literals, coverage separation, assignment provenance, census direction,
configuration dates, and excluded legacy P132/P39/P40/sameAs patterns. This is
not a complete CRM inference or SHACL conformance check.

Generated files (under ignored `data_quality/lod_model_pilot/`):

* `model.ttl`: the RDF specimen.
* `manifest.json`: input hashes, counts, and explicit limitations.
* `correspondences.csv`: the exact selected audit evidence.
* `validation.json`: targeted validation results.

Project predicates currently use a provisional namespace beneath the existing
temporary census base URI. Their final vocabulary definitions, national date
configuration, typed identity mappings, survey links, statistical query view,
and database/site migrations remain part of the rebuild. This specimen makes
no claim of LINCS approval.
