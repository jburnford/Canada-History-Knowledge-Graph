# GIS subdivision connection audit

Audit date: 2026-09-05. Scope: the eight base `CANADA_{year}_CSD` layers,
1851–1921, their dissolved census divisions, and all seven adjacent census
comparisons. Research-paper files were excluded.

## Result

The legacy overlap calculations largely reproduce, but the legacy CSD filters
lose substantial correspondences in complex redistributions. Those filtered
tables cannot serve as a complete subdivision crosswalk. The revised pipeline
retains every positive-area intersection, with both directional fractions,
intersection area, source polygon areas, CRS, and an explicit indication that
historical succession has not been verified.

The EPSG:3347 rebuild contains **53,078 CSD pairs and 3,848 CD pairs**. All 14
rebuilt tables agree with the audit on identifiers, areas, fractions, CRS, and
evidence status. Audit and production share the corrected geometry kernel;
agreement establishes pipeline consistency, not independent proof of the
kernel. Analytical fixtures separately test exact split/merge fractions,
many-to-many partitions, boundary touches, geometry repair, and index handling.

These are clean computational evidence tables with recorded source limitations.
They are not verified histories of administrative change, and this audit does
not certify the full LOD export for submission.

## Corrections and evidence

* **Dropped CSD correspondences:** the legacy high-confidence and ambiguous
  files together omit 2,487 material correspondences, including 350 involving
  Saskatchewan. Here “material” is a review flag: at least 1,000 m² and at least
  1% of either polygon. It is neither an identity rule nor a deletion threshold.
  All smaller positive intersections are retained too.
* **Repeated source identifier:** 1851 Quebec `QC053009`, Chantiers, has two
  polygon records with identical descriptive attributes. Combining the pieces
  produces one identified area and corrects two legacy overlap records.
  Conflicting metadata under a repeated identifier now stops processing.
* **Geometry preparation:** 55 invalid input geometries are repaired, with
  before/after areas and validity explanations logged. The duplicate-ID
  dissolve adds one preparation action. Polygon components from geometry
  collections are retained. Missing, empty, or nonpolygonal areas fail clearly.
* **Consistent consumers:** CSD linking, CD aggregation, and the spatial node
  builders use the same preparation rules. Geometry errors propagate rather
  than becoming apparent zero-overlap results. Empty result files retain their
  headers and replace stale results. Batch wrappers stop on failure.
* **Identity safeguard:** a nonadjacent name bridge now requires valid centroid
  evidence for both endpoints before applying the existing distance test.
  Passing that test still provides only a candidate identity relationship.

Of 23,688 legacy CSD/CD records, all endpoints resolve. There are no duplicate
legacy pair keys. Apart from the two Chantiers records, overlap fractions agree
within the legacy four-decimal rounding tolerance. The CD filter omits no
material correspondence under the stated review threshold.

| Census comparison | Material CSD correspondences omitted by legacy filters |
| --- | ---: |
| 1851–1861 | 114 |
| 1861–1871 | 156 |
| 1871–1881 | 230 |
| 1881–1891 | 269 |
| 1891–1901 | 296 |
| 1901–1911 | 691 |
| 1911–1921 | 731 |

## Westmeath and Saskatchewan

Westmeath has identical mapped extent (IoU 1) across all seven adjacent
comparisons, including the 1881 spelling “Wesmeath”. Its sequence is
`ON033008`, `ON096020`, `ON082003`, `ON114011`, `ON114011`, `ON110012`,
`ON116013`, `ON142032`, each qualified by its census year. This supports spatial
stability. Historical and community identity remain separate assertions.

The 1911 Saskatchewan area `SK211001`, “870 townships”, has 190 material
counterparts in 1921. A pairwise one-to-one matcher cannot express this.

For a specific omission, the 1921 area `SK187010`, “528. T. 52-55, R. 16-18,
W. 3”, intersects these 1911 areas (EPSG:3347 fractions):

| 1911 source | Share of the 1921 area | Legacy treatment |
| --- | ---: | --- |
| `SK208001`, 423 townships | 49.7874% | Dropped |
| `SK208999`, NO DATA | 49.9770% | Dropped |
| `SK208022`, Stony I R | 0.2356% | Retained |

The two dropped pairs cover approximately 99.76% of the later area. Their low
IoU and directional fractions below the legacy cutoffs hid substantial
connections. The `NO DATA` intersection describes the source map's coverage;
it must not become an assertion that an unknown administrative unit merged
into the later CSD.

## Source qualifications

There are **49 distinct CSD-year areas** with less than 99% summed overlap in
at least one adjacent source layer, represented by 82 directional comparison
rows. None is in Saskatchewan. These are queued in `coverage_review.csv`.
Examples with almost no correspondence include 1901 Sultana Mine, 1911 Prince
Rupert c, and 1911 Canadian Navy. Their source interpretation needs review;
the pipeline does not manufacture missing connections or relocate polygons.

There are 33 positive same-year CSD overlap pairs, all below the material
threshold. Endpoint fraction sums never exceed 1.0001. The coverage statistic
is a **sum of pairwise fractions**, not the area of a geometric union; source
overlap can slightly inflate it. Small boundary discrepancies and numerical
slivers remain available in the topology and correspondence tables.

Cross-province comparisons are retained. They may reflect historical changes
in provincial organization, as well as boundary discrepancies. The flag alone
does not establish an error. `involves_no_data` identifies endpoints explicitly
named `NO DATA`; it does not measure all uncertainty within an aggregated CD.

## Area projection

EPSG:3347 reproduces the legacy area basis but is conformal, not equal-area.
The audit was also rerun in ESRI:102001, Canada Albers Equal Area Conic.
Every material pair survives in both projections, with no change to material
flags. Maximum directional fraction differences are approximately 0.66
percentage points for CSDs and 0.73 for CDs. Two CSD pairs cross the descriptive
95% containment threshold; no CD pair changes that category.

Use the equal-area tables for new area-based evidence. Keep the legacy-basis
run for comparison, and always carry the CRS with the metrics. Neither
threshold classification is a historical split/merge determination.

The equal-area production rebuild contains **53,102 CSD pairs and 3,850 CD
pairs**, and also passes all 14 audit comparisons without discrepancies.
Counts of small positive intersections differ between projections; the
24,036 material CSD pairs and 1,948 material CD pairs are unchanged. All
23 regression tests pass.

## Reproduce and inspect

Run from the repository root with the GIS Python dependencies installed and
`config.local.toml` or `config.toml` pointing to the source data:

```bash
python3 -m pytest -q tests/test_gis_connections.py
python3 scripts/audit_gis_connections.py
OUT_DIR=data_quality/gis_rebuild/csd bash scripts/link_all_years.sh
OUT_DIR=data_quality/gis_rebuild/cd bash scripts/link_cd_all_years.sh
python3 scripts/audit_gis_connections.py --crs ESRI:102001 --out data_quality/gis_audit_equal_area
python3 scripts/validate_gis_rebuild.py --equal-area data_quality/gis_audit_equal_area
GIS_CRS=ESRI:102001 OUT_DIR=data_quality/gis_rebuild_equal_area/csd bash scripts/link_all_years.sh
GIS_CRS=ESRI:102001 OUT_DIR=data_quality/gis_rebuild_equal_area/cd bash scripts/link_cd_all_years.sh
python3 scripts/validate_gis_rebuild.py --audit data_quality/gis_audit_equal_area --staged data_quality/gis_rebuild_equal_area
```

`python` used by the shell wrappers must select the same GIS environment.
The Makefile also provides `gis-audit`, `gis-stage-links`, and `gis-validate`.

Generated artifacts live under the ignored `data_quality/` directory:

* `gis_audit/report.json`: source GDB file hashes, library versions, CRS,
  inventories, and comparison counts.
* `gis_audit/geometry_preparation.csv`: individual repairs and dissolution.
* `gis_audit/*_correspondences.csv`: complete evidence, including review flags.
* `gis_audit/*_omitted.csv` and `*_metric_differences.csv`: legacy differences.
* `gis_audit/coverage_review.csv`: source areas requiring interpretation.
* `gis_audit/projection_sensitivity.csv` and `projection_threshold_review.csv`:
  comparison with the equal-area run.
* `gis_rebuild/validation.csv`: the 14 audit/rebuild checks.
* `gis_audit_equal_area/` and `gis_rebuild_equal_area/`: corresponding
  equal-area outputs.

Existing identity registries, published RDF, and the site have not been
regenerated as part of this GIS checkpoint. The next modelling step is to
replace cross-census `P132` assertions with qualified spatial correspondence
evidence, then represent documented changes separately with multiple
predecessors and successors. Persistent communities must remain distinct from
both the census-year areas and the inferred identity chains.

## Coverage status after CD aggregation

The source-table migration exposed 23 named CD polygons made entirely from
NO DATA CSD children. Examples include Newfoundland in several vintages and
the 1901 Montréal placeholder. The CD name alone cannot distinguish these
coverage records from census reporting areas. `dissolve_cds` now derives
`is_coverage_record` from all constituent CSDs, and both the audit and CD linker
propagate it into `involves_no_data`. A mixed CD with some real CSDs is not
automatically classified as an entirely missing coverage area.

The equal-area audit and all seven CD link pairs were regenerated. All 14
CSD/CD audit-to-rebuild checks pass, now including coverage flags alongside
metrics. All positive intersections remain available. The identity staging
excludes these 23 CD records from historical identity inference; coverage
geometry does not imply zero population or establish why census data is
absent. Earlier Lambert comparison outputs predate this metadata correction.
