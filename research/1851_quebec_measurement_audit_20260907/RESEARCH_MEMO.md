# Growth for whom? A harder test of Quebec's agricultural crisis

Research dossier, 7 September 2026. **Exploratory work; no claim of a historical breakthrough.**

The first study established a demographic pattern but did not change a consequential historical explanation. This second investigation has identified a more consequential dispute, rejected two tempting shortcuts, and independently verified a problem in the census inputs. It has **not** yet established a new explanation of nineteenth-century Quebec.

## The historical question

Could agricultural output improve while access to an independent farming livelihood deteriorated for the next generation? If so, rising productivity and agrarian distress would not be contradictory descriptions of the same society. The substantive question is which mechanism explains departure from farming: deteriorating production, restricted access to land and farm establishment, or attractive opportunities elsewhere.

This is an existing historical problem, not a newly invented thesis. Dessureault's work uses the 1831 census to investigate day labourers, and links occupational histories and wealth records in Saint-Hyacinthe. It also makes clear that cultivator and labourer were not necessarily permanent, mutually exclusive identities. A new contribution would have to explain something those studies leave unresolved; simply finding rural inequality would fail the novelty test. [Dessureault, Montreal district study](https://doi.org/10.7202/1079246ar); [Saint-Hyacinthe study](https://doi.org/10.7202/1088208ar).

The immediate intervention is in the inference from productivity to the absence of distress. Bond, Geloso and Swanson's 2026 article rejects the painful-modernization interpretation using several forms of productivity evidence. Its historical panel covers 1739, 1784 and 1831. Its 1851 cross-section uses settlement duration and corrected crop yields. These are substantive results that a competing explanation must confront, not dismiss. [Article](https://doi.org/10.1007/s11698-026-00342-0).

The potential contribution would be a discriminating account of **who could establish a farm, and where the next generation went**, conditional on production opportunities. A larger descriptive map, a significant regression coefficient, or a more ambitious introduction would not by itself meet that standard.

## What the source audit actually establishes

The current agricultural county workbook assigns the following wheat observations:

| County | Workbook reported area | Workbook reported output | Area under this county in the English printed census | Output under this county in the English printed census |
|---|---:|---:|---:|---:|
| Saint-Maurice | 12,531 | 70,060 | 10,217 | 80,711 |
| Saguenay | 10,217 | 80,711 | 12,531 | 70,060 |

The figures are transposed between the county labels. The original headings label area as acres and output as bushels; historical unit comparability remains a separate question. The original page is page 131, PDF page 189, of the English second volume. This finding compares reported entries; it does not establish that the printed totals themselves correctly add every local return. [Original volume](https://publications.gc.ca/collections/collection_2012/statcan/rh-hc/CS98-1851-2-eng.pdf#page=189); [page image](external_sources/census_pdfpage_189.png).

The four disputed cells survive unchanged from the workbook into SQLite and the published JSONL. Thus this particular discrepancy predates those exports. Workbook hashing and cell checks reproduce that conclusion. The corresponding source anchors are [Saint-Maurice area](https://jimclifford.ca/hgiscanada/sources/1851_V2T6_CD_202306/rows/69/#cell-S), [Saint-Maurice output](https://jimclifford.ca/hgiscanada/sources/1851_V2T6_CD_202306/rows/69/#cell-T), [Saguenay area](https://jimclifford.ca/hgiscanada/sources/1851_V2T6_CD_202306/rows/70/#cell-S), and [Saguenay output](https://jimclifford.ca/hgiscanada/sources/1851_V2T6_CD_202306/rows/70/#cell-T).

This reverses a regional comparison: the workbook assigns the lower raw wheat yield to Saint-Maurice, while the printed county totals assign it to Saguenay. It is a consequential input correction, **not a discovery about actual changes in farming**. No evidence has been established that the external authors used this workbook, or that their results contain this transposition. It would be improper to attribute it to them.

The pilot also compares eight agricultural variables across 36 county records and their associated subdivision records. These are 288 reconciliation checks and 4,200 preserved source cells. Of the checks, 97 have a nonzero difference between the county entry and the sum of observed numeric subdivision entries. This is a screening count, not 97 confirmed errors: blank returns, coverage differences, printed arithmetic, and transcription can each matter. The output retains nonnumeric counts and explicitly labels incomplete subtotals. Neither missing observations nor missing communities are treated as zero.

## What the literature audit establishes—and does not

Two attractive criticisms fail in their simple form.

First, the difference between land units and crop-volume units is already recognized. McInnis treats original surveys and the 1871 clerks' conversions as evidence about land measurement and acknowledges uncertainty about crop volumes. Thibeault independently examines grants, manuscripts and local usage. His Saguenay evidence supports acres for land and minots for grain, despite misleading labels. These are predecessors, not discoveries of this investigation. [McInnis, 1981, pp. 224–226](https://hssh.journals.yorku.ca/index.php/hssh/article/download/37964/34425/44361); [Thibeault, 1989, pp. 225–229](https://doi.org/10.7202/304788ar).

An accessible early Geloso manuscript also explicitly discusses retaining land areas while correcting crop volumes. Therefore “the revisionists ignored this distinction” is not a defensible criticism. The final 2019 article's full text and the later replication data have not been obtained; the early manuscript must not be silently substituted for them. [Early manuscript](https://www.academia.edu/24792022/Measuring_Away_the_Importance_of_Institutions_The_Case_of_Seigneurial_Tenure_and_Agricultural_Output_in_Canada_East_1851); [2019 publication](https://doi.org/10.1111/ssqu.12557).

Second, the 2026 article's prose and numerical results need to be distinguished. Its main Table 4 and supplementary Table A3 agree: under the preferred land correction, the 1784 coefficients for output per arpent are −0.079 and −0.074, while the 1831 coefficients are positive. The negative intermediate estimates are not statistically distinguishable from zero. The prose's description of the per-arpent sequence as a stronger rising pattern therefore needs qualification. This is **not a disagreement between the main and supplementary tables**, and it does not erase the positive endpoint or per-capita results. [Table 4](https://link.springer.com/article/10.1007/s11698-026-00342-0/tables/4); [supplement, p. 7](https://media.springernature.com/original/springer-static/esm/art%3A10.1007%2Fs11698-026-00342-0/MediaObjects/11698_2026_342_MOESM1_ESM.pdf#page=7).

There is also a basic identification issue in the written panel equation. If settlement duration is calendar year minus first-settlement year, it is exactly a combination of date and place fixed effects. A separate linear duration coefficient cannot then be identified. The included script verifies this algebra on explicitly synthetic observations. This is a standard mathematical fact, not a new historical estimate. A date-effects regression that drops the redundant duration term remains estimable. Without the authors' code, this is a question about the written specification, not a claim that their software estimated an invalid coefficient.

More fundamentally, date effects measure net change. Their sign alone cannot separate technological improvement, changing crop choice, soil deterioration, and selection of land or producers. A positive net result can coexist with a negative component. Nor does an increase among observed producers establish an improvement for households unable to become producers. These are reasons to test the competing mechanisms directly.

## A research design that could earn a stronger claim

The available 1851 and 1861 inventories contain age, sex and marital categories, farm-size categories, land use, and crop observations. They provide a plausible starting point, not an already harmonized panel. The exact age definitions and census dates require checking: a roughly nine-year interval cannot automatically be treated as ten years of cohort ageing.

The next empirical design must compare three explanations on the same validated geography:

| Explanation | Evidence that would help distinguish it |
|---|---|
| Production failure | Persistent deterioration across comparable crop or output measures precedes loss of young adults, after accounting for harvest shocks and crop substitution. |
| Restricted farm establishment | Young-adult departures or delayed household formation are associated with restricted land access even where production opportunities remain good. Farm acquisition or inheritance evidence corroborates the aggregate pattern. |
| Attractive outside opportunities | Departure is better accounted for by destination opportunities and access to transport than by either local production failure or restricted farm access. |

These mechanisms can coexist. The aim must be to establish their relative explanatory force, not assign each place a single label.

Three requirements are decisive. First, geography must be reconstructed from validated source bindings, boundary evidence and, where necessary, unions of changing units. Matching names is insufficient. Second, land and volume corrections must be separate, documented alternatives; results depending on an unsupported choice cannot establish the historical conclusion. Third, aggregate cohort deficits must not be presented as observed emigrants: mortality, in-migration, enumeration and age reporting also change cohort counts.

A farm-count-to-family-count ratio is not a landlessness rate. It may help screen cases, but establishing restricted access requires independent evidence about acquisition, occupation or inheritance. Household and notarial evidence would be particularly useful in matched cases with similar agricultural opportunities but contrasting demographic outcomes.

The stopping rule is substantive: if the project only reproduces known regional differences, or cannot distinguish these mechanisms, it should not become another purported breakthrough paper. A defensible negative result is preferable to inflating an empirical extension.

## Status and reproducibility

Completed: literature screening; primary-page verification of four county-cell discrepancies; workbook/SQLite/JSONL agreement checks; a preserved census extract; county reconciliation; and the panel-identification demonstration. No historical regression from the 2026 study has been replicated. No new causal estimate of emigration, productivity or farm access has been produced.

Run `python3 research/1851_quebec_measurement_audit_20260907/audit.py` from the repository root. See `validation.json`, `verified_print_discrepancies.csv`, `county_reconciliation.csv`, and `source_cells.jsonl.gz`. Source datasets have not been modified. Repository papers and earlier research directories were not used.

This dossier is a sharper, reviewable research intervention. It is not yet the significant contribution the user requested.
