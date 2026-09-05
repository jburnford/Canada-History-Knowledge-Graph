# National identity staging and 1911 reporting-unit preservation

2026-09-05. These are staged migration artifacts. National source-table
preservation is described in [the source rebuild](LOD_SOURCE_TABLE_REBUILD.md).
Geographic observation integration, final vocabulary, survey geometries, and
database/site integration remain outstanding. Research-paper files are excluded.

## Continuing identity with changing census area

A township can retain its identity while losing a village or town to a
separate census reporting unit. Its population series then has a boundary
break. The migration now records both the continuing unit and contributions
to separate later units, including changes involving less than 2% of the
earlier area. A small area can contain a large population.

The automatic candidate rule requires an unambiguous same-name successor in
the same province and name tier, retaining at least half the earlier area,
with at least 98% of the successor inside the earlier area. Other material
counterparts and at least 99% summed source coverage must account for the
remaining geography. These thresholds are explicit evidence rules for staged
census continuity, not definitions of historical identity. Cases outside the
rule remain unresolved; rejection is not an assertion that identity ended.

For each configuration, `boundary_redistributions.csv` records the continuing
CSD and each separate later counterpart, the directional fractions, area,
CRS, census years, and a population-comparison qualification. The complete
audit crosswalk still retains all smaller positive intersections.

An actual example is Saugeen in 1851 (`ON003011`):

| 1861 reporting area | Share of earlier mapped area |
| --- | ---: |
| Continuing Saugeen (`ON066014`) | 92.6735% |
| Southampton Village (`ON066015`) | 7.3265% |

The migration puts the two Saugeen snapshots in the same continuing unit and
records Southampton separately. Recombining later population totals is a
candidate comparison only when the later areas collectively approximate the
earlier geography and variable definitions/source units agree. If a receiving
town extends outside the old township, adding its entire population is not
valid without further geographic reconciliation. No population is estimated
from area fractions, and a census-area separation does not establish a
municipal incorporation date.

## National identity inventory

The staged inventory contains all 22,522 CSD/CD map representations, including
350 NO DATA coverage records (327 CSDs and 23 named CD aggregates composed
entirely of NO DATA children). It has 13,401 qualified continuing units and
preserves 4,858 legacy unit identifiers where membership is unchanged.
There are no missing legacy members, duplicate snapshot identifiers, or
non-coverage representations without a subject.

It records 7,519 near-equal-extent/name continuity edges and 1,252 continuing
configurations with area separation (1,474 separate-area contributions).
There are 3,917 near-equal-extent name changes requiring further evidence,
one province-change case, and 157 coverage-record pairs excluded from identity
inference. Coverage geometry remains in the crosswalk.

Continuing-unit rows also carry `has_recorded_area_separation`, so population
series can expose a boundary-comparability break while retaining the same
unit identity.

Westmeath retains `PLACE_ON142032` across all eight census representations,
including the audited 1881 spelling variant. Its historical-township typing
follows the curator discussion. Other units remain E92 census-reporting
subjects until their historical referents are established; this inventory
does not assign every census polygon an administrative or community identity.

The 7,498 retained Wikidata associations have cached type labels and review
categories distinguishing cadastral areas, administrative units, settlements,
organizations, statistical units, religious-parish referents, and geographic
features. These categories are evidence-management hints, not automatic CRM
types. For example, a geographic township is kept distinct from a township
municipality. No mapping replaces a local URI or asserts owl:sameAs.

## Complete preservation of 1911 V1T1

The source workbook has 10,240 reporting rows and seven statistical columns.
All 71,680 cells are preserved with sheet, Excel coordinate, original value,
number format, variable, reference year, unit, reporting level, and row notes.

| Reporting level | Rows |
| --- | ---: |
| Country total | 1 |
| Province/territory total | 9 |
| Census division total | 219 |
| Survey-township reporting unit | 5,960 |
| Other CSD reporting unit | 4,051 |

The survey rows yield 5,892 distinct parsed DLS designations. Repeated survey
designations do not collapse reporting rows. Township, range, meridian, and
east/west direction are retained; no survey polygon is invented. Partial or
compound descriptions remain in source text for subsequent interpretation.

The table's `POP_1901` column retains reference year 1901, separately from the
1911 reporting-geography vintage. The export does not assume that historical
values have been adjusted to a common geography. Notes distinguishing land
area from land-and-water totals, and notes about corrected published values,
remain attached to the source rows.

Source table codes do not identify GDB polygons automatically. In particular,
table code `SK216003` describes `T24 R1 MW3`, while the same GDB code labels
Saskatoon c. The survey row remains an independent reporting unit. The staging
also retains 589 nonaggregate, nonparsed-survey rows without a candidate GIS
binding and preserves 3,462 legacy name-match candidates as qualified links.

## RDF and checks

The source graph has 61,715 numeric observations and 9,965 blank-cell records.
Numeric records are both E73 source information and RDF Data Cube observations.
E13 assignments connect source reporting subjects to E54 quantities. Both
views derive from the same staged cells. Blank cells do not become numeric
zero or invalid P90 literals. Reporting-level attributes distinguish totals
from constituent observations.

The initial 1,744,194-triple N-Triples graph parsed, and every cell reconciled
with its staged source value, year, status, reporting level, and numeric unit.
Its validation reported zero errors. The newer national source export adds
qualified reference periods and column definitions. This is source-cell and model validation, not
a complete ontology reasoner or a claim of historical boundary accuracy.

```bash
python3 scripts/build_lod_identity_inventory.py
python3 scripts/stage_1911_reporting_units.py
python3 scripts/export_1911_reporting_rdf.py
python3 scripts/validate_reporting_rdf.py \
  --database data_quality/lod_1911_reporting/source_observations.sqlite \
  --rdf data_quality/lod_1911_reporting/source_observations.nt.gz
python3 -m pytest -q tests/test_lod_migration.py tests/test_lod_model.py tests/test_gis_connections.py
```

The Makefile provides `lod-identities`, `lod-1911-reporting`, and
`lod-model-check`. Generated outputs are under ignored `data_quality/`:

* `lod_identity/`: representations, units, continuity decisions, boundary
  redistribution contributions, legacy-ID crosswalk, Wikidata associations,
  and a hashed input manifest.
* `lod_1911_reporting/`: source-cell SQLite database, reporting/survey CSVs,
  compressed RDF, reconciliation report, and manifests.
