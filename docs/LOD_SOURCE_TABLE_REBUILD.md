# Census source-table rebuild

2026-09-05. This staging rebuild reads the census source workbooks and their
variable dictionaries. Research-paper files are excluded. It preserves source
observations before geographic reconciliation; it does not promote the old
database or site to the new model.

## Source coverage

The canonical input selection contains 47 workbooks: the CD and CSD editions
for 1851–1901, including the separate 1871 PEI tables, and the nine PUB
workbooks for 1911/1921. Alternative older OCR/PUB editions are not counted
as additional independent observations. Input paths, hashes, selected sheets,
header rows and alternative worksheet names remain in the manifests.

| Preserved source content | Count |
| --- | ---: |
| Reporting rows | 77,856 |
| Statistical cells | 1,783,554 |
| Numeric cells | 1,138,818 |
| Blank cells | 627,591 |
| Text cells retained without numeric interpretation | 17,145 |
| Source column positions representing variables | 1,879 |

These counts include country, province and CD totals, CSD rows, 11,885 survey
township rows, and 58 rows with unresolved reporting levels. Source totals
must not be summed with their constituent observations. Observations in
different tables and repeated source columns remain distinct even when the
variable labels agree.

Every staged worksheet is independently reread to check reporting-row sets,
original values, cell coordinates, numeric classifications and number
formats. Metadata and row notes are retained as well as statistical cells.
Only completely empty, unnamed columns are ignored; any unlabelled column
with content is retained and flagged.

## Corrected ingestion errors

* Both 1871 V3T23 workbooks place an OCR worksheet before the structured
  worksheet. Selection now uses identifier/header structure and fails if
  more than one structured candidate exists. The selected agricultural data
  contains 206 CD rows and 1,703 CSD rows, each with 17 statistical columns.
* The 1851 V1T3 and 1861 V1T5 CD/CSD sheets repeat the population headers
  `POP_MX_N`, `POP_FX_N` and `POP_XX_N`. Excel column positions distinguish
  these occurrences; neither occurrence is overwritten or merged.
* In 1911 V1T2, `ON071003` labels both Gower S and Kemptville. In 1911 V2T7,
  `SK207001` labels both “209 townships” and White Bear I R. Each reporting
  row has its own table-scoped subject; duplicate codes remain visible for
  correction, without combining populations.
* PUB table identifiers are not assumed to be GDB TCPUIDs, and the 1911 V1T1
  crosswalk is not applied to other tables. In particular, survey-township
  codes cannot become city polygon identifiers through an accidental join.
* The 1911 V2T28 and 1921 V3T3 tables report at CD level. They do not acquire
  invented CSD subjects merely because other workbooks use CSD rows.

The 1851 manufacturing CSD workbook's filename says V2T7 while its worksheet
title says V2T13-14. Both identifiers are preserved; this rebuild does not
silently resolve the discrepancy.

## Units, reference periods and missing values

Local `Variables` sheets take precedence over the supplied master variable
dictionary. Definitions retain their source path, hash, cell and original
row. Two identical master definitions for `FRMSZ_0to10_N` have different year
availability columns; both evidence rows are retained. Conflicting duplicate
definitions would stop ingestion.

The RDF keeps source variables scoped to their workbook and column position.
It does not claim semantic equivalence between similarly labelled columns in
different tables. Historical labels are source terminology, not newly
assigned categories for individuals.

Density, family size, families, dwellings and households have distinct units.
Older `_N` variables use a count with the counted entity described by the
source definition. Pounds sterling remain distinct from pounds of mass.
Historical bushels, barrels, gallons, tons, dollars and lumber feet are
retained as reported, without an unsupported modern conversion. Fourteen
column positions need unit interpretation; two also lack a definition in
the supplied dictionary (`HRS_ov03_V` in the 1861 CD and CSD tables).

A source's explicit year, such as `POP_1901`, remains separate from the
reporting-geography vintage. Descriptions such as “in the past year,” annual
production, daily production and weekly production retain distinct period
qualifications. They are not assigned the preceding calendar year or an
invented census reference day. Other columns whose reference period has not
been established retain that uncertainty. RDF Data Cube uses a qualified
reference-period dimension; an exact reference year is optional.

Of the 17,145 text cells, 16,992 contain whitespace or empty strings. The
other 153 include punctuation, letter-like digits and pounds/shillings/pence
strings. Original JSON values are retained in every case. No text or blank
cell becomes zero, and no unresolved currency string becomes a P90 value.
One 1851 agricultural row has a formula in its YEAR metadata; the formula
is preserved and flagged while the workbook's census vintage stays explicit.

## RDF and reproducible checks

Numeric source records are both E73 information objects and Data Cube
observations. Each is evidence for an E13 assignment to its source reporting
unit, with an E54 numeric quantity. P90 values are finite numeric literals;
P91 is supplied only when the measurement unit is established. Unknown units
remain explicit on the variable and are not minted as fictitious units.
Blank and text cells remain E73 records without numeric cube assertions.

The exporter emits one compressed N-Triples file per workbook. The validator
parses every triple and reconciles every source cell, reference-period link,
variable, value, reporting level, quantity, unit and assignment provenance.
It rejects legacy P39/P132 assertions and automatic owl:sameAs. These are
targeted data/model checks, not a complete ontology reasoner.

The completed 47-workbook export contains 36,001,307 parsed triples. All
1,783,554 source cells reconcile, including 1,138,818 numeric observations;
all per-workbook RDF validations report zero errors. The regression suite
for GIS, model semantics, source preservation and geographic assessments
passes 55 tests.

```bash
make lod-census-sources
# Export/reconcile the completed source staging without repeating ingestion:
python3 scripts/export_census_sources.py
# Or run both stages from source:
make lod-census-source-rdf
make lod-model-check
```

Outputs are under ignored `data_quality/lod_census_sources/`:

* `catalog.json`: all selected workbooks and source-preservation counts.
* Each workbook directory: SQLite source staging, manifests, source
  validation, compressed RDF and RDF validation.
* `rdf-catalog.json`: complete export and RDF reconciliation results.
* `variable_inventory.csv`: definitions, units, periods and 38 flagged
  column positions, including both occurrences of repeated headers.
* `source_identity_review.csv`: 63 flagged rows, covering duplicate codes,
  unresolved levels and the source-year formula.
* `text_value_review.csv`: original text values, frequencies and example
  source cells, distinguishing whitespace from other nonnumeric text.

## Source-to-map assessments

`scripts/build_source_spatial_bindings.py` assesses every source reporting row
against the corrected national representation inventory. The result is under
`data_quality/lod_source_bindings/`; it is separate from the source RDF and
does not rewrite source observations as historical-entity observations.

| Assessment | Source rows |
| --- | ---: |
| Explicit TCPUID and year/province/district/name agree | 22,436 |
| Unique contextual name candidate | 30,292 |
| Multiple contextual name candidates | 9 |
| Explicit identifier with a context disagreement | 8,352 |
| Explicit identifier absent from the map | 4 |
| No contextual name match | 4,664 |
| Survey designation with unresolved geometry | 11,885 |
| Country/province aggregate outside CSD/CD inventory | 90 |
| Missing or ambiguous parent district | 66 |
| Unresolved reporting level | 58 |

All 77,856 source rows and 52,746 candidate map endpoints pass the independent
row/endpoint checks. These checks reject missing endpoints, wrong vintages or
levels, dropped source rows, and population bindings to coverage records.
The 23 CD coverage placeholders are excluded as well as the 327 CSD coverage
records. Candidates are not historical identity assertions.

The matcher normalizes spacing, punctuation and dash characters while
retaining administrative tiers. It preserves raw source codes and province
values alongside effective matching values. For 2,962 rows it reads stored
workbook results for metadata formulas (2,961 identifier rows and one YEAR
row). Formulas and cached results remain separate evidence; no Excel formula
is executed or silently repaired. Reading those stored identifiers reduces
the unresolved missing-ID cases to four.

`identifier_context_review.csv` distinguishes name/tier, district and province
differences. The 100 distinct Manitoba province-code discrepancies are trailing
spaces, handled by normalization. Seventeen 1881 V1T1 rows actually say PE
while their identifiers and mapped district belong to NS; these remain
flagged, without automatic population links. District differences also include
the 1871 PEI table's electoral districts versus the GIS county grouping.
That difference may require parallel reporting hierarchies rather than a
correction to either source.

```bash
python3 scripts/build_source_spatial_bindings.py
# To rebuild its prerequisite source and identity inventories as well:
make lod-source-bindings
```

The general source export supersedes the single-table 1911 example as the
input to the national migration. They are alternative staging generations;
loading both would duplicate the 1911 V1T1 observations. Resolution and RDF
integration of the geographic binding assessments,
national date configuration, the project vocabulary and database/site
consumers still require integration before a submission release.
