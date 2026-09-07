# Response to the redesign verdict

7 September 2026 · Follow-up to the 1851 Quebec measurement dossier

**The central verdict stands.** The source correction is stronger than my first dossier established; the proposed mechanism paper still fails its novelty and identification tests. I have completed a wider source audit and prepared a local correction overlay. This supplement supersedes the first memo's four-cell description and its assessment of the proposed contribution. It does not constitute a new historical paper.

## What the expanded audit establishes

I visually checked the printed county totals across pages 130–135, covering all **56 statistical columns, F–BI, in each of workbook rows 69 and 70**. The St. Maurice-labelled row contains Saguenay's statistics, and the Saguenay-labelled row contains St. Maurice's statistics. Across the resulting 112 comparisons, **111 opposite-row entries agree with print**, including printed blank returns. The exception is the calf/heifer count discussed below. This supports correcting the geographic assignment of the whole statistical block, with a separately documented disagreement in the calf/heifer total. Source: [1851 census, volume II, printed pp. 130–135, PDF pages 188–193](https://publications.gc.ca/collections/collection_2012/statcan/rh-hc/CS98-1851-2-eng.pdf#page=188).

| County | Workbook row | Occupiers: workbook → print | Wheat acres: workbook → print | Wheat bushels: workbook → print |
|---|---:|---:|---:|---:|
| St. Maurice | 69 | 2,453 → 2,886 | 12,531 → 10,217 | 70,060 → 80,711 |
| Saguenay | 70 | 2,886 → 2,453 | 10,217 → 12,531 | 80,711 → 70,060 |

These figures reverse the counties' apparent wheat-yield ranking: the printed ratio is about 7.90 bushels per reported acre for St. Maurice and 5.59 for Saguenay. The swapped workbook assignments give the opposite result. Exchanging two complete records preserves their combined totals and the unlabelled distribution of their values; it can nevertheless change relationships between those values and county characteristics. This is a concrete consequence for research using named places, not evidence that an existing published regression is wrong.

The broader check found two additional issues:

- **Calves/heifers:** printed St. Maurice has **5,503**, whereas workbook `BA70` has **5,508**. However, the 14 printed locality returns also sum to **5,508**, and each agrees with the CSD workbook. Thus 5,503 is a conflicting printed total, not an established transcription error. The overlay reassigns the workbook value of 5,508 to St. Maurice and separately records 5,503; it does not adjudicate the underlying count. The extra CSD workbook row for estimated squatters is blank, so its value is not imputed. See printed p. 135 and the enlarged image in the package.
- **Hay:** the printed column explicitly combines bundles and tons. Saguenay's 1,280,162 and St. Maurice's 2,796,856 are bundle figures, with separate totals of 9,144 and 19,956 tons printed underneath. The workbook's `HAY_XX_T` label must not turn the large bundle numbers into tons. The overlay flags the unit problem; it does not estimate a conversion from the rounded printed totals. See printed p. 134.

`all_county_cells.csv` supplies every comparison, its variable, source citation and printed page. The script verifies the two original workbook hashes and reconciles **150 distinct cells** among workbook, current SQLite and current retrieval JSONL: 112 swapped-row cells, two other county totals, their 22 constituent locality values, and 14 St. Maurice livestock returns. Manual image readings remain explicit inputs to the script; running it does not independently prove those readings.

## The two 30,000 discrepancies originate in print

I read the locality names and values, then added the printed returns independently. All 22 locality values and both county totals agree with their respective workbook entries.

| County and variable | Printed county total | Sum of printed locality values | Difference |
|---|---:|---:|---:|
| Richelieu, oat bushels | 194,297 | 224,297 | +30,000 |
| Rouville, wheat bushels | 156,962 | 186,962 | +30,000 |

Richelieu is on printed pp. 118 and 120; Rouville on pp. 124–125. The values are documented individually in `printed_localities.csv`, with the totals in `arithmetic_discrepancies.csv`. See the [original volume](https://publications.gc.ca/collections/collection_2012/statcan/rh-hc/CS98-1851-2-eng.pdf#page=176).

These are **internal inconsistencies in the printed table**, reproduced faithfully in the digital transcription. This evidence does not identify whether a printed total, a constituent return, or several figures are erroneous. Replacing the county totals with the sums would choose an interpretation that has not been established. The supplement therefore supplies discrepancy annotations, not replacement values for these two cells.

There is also a small but consequential correction to the review's triage. Of the 97 nonzero screening results, 24 are complete numeric comparisons and 73 are partial. **All 16 swap-related results belong to the partial group.** Thus the other counties account for all 24 complete discrepancies and 57 partial discrepancies. The two 30,000 cases are two of those 24 complete comparisons. The observed subdivision sums agree with the printed assignments for all eight audited variables in both swapped counties, but missing returns still prevent describing those sums as complete independent enumerations.

## Research decision after Bouchard

The omission of Bouchard was substantive. His 1983 article explicitly studies how families established multiple children from a patrimony, including acquisition, transmission and migration. It also proposes extending the Saguenay model to other settlement regions. This directly precedes the question my memo presented as a promising new intervention. I have now checked that primary article, including its source description; I have not represented the review's account of the entire 1996 book as my own full reading. [Gérard Bouchard, “Les systèmes de transmission des avoirs familiaux et le cycle de la société rurale au Québec, du XVIIe au XXe siècle,” 1983, pp. 35–38](https://hssh.journals.yorku.ca/index.php/hssh/article/download/38228/34630/45153).

**I withdraw the proposed aggregate mechanism paper in its present form.** County productivity and cohort changes cannot distinguish exclusion from landholding, voluntary moves to better jobs, mortality, changing boundaries or other migration. Adding controls cannot manufacture the missing observations of individual opportunities and decisions. Neither the general establishment question nor a county correlation is an adequate novelty claim.

A replacement project would have to establish a specific unresolved result in that literature and obtain evidence capable of answering it. A defensible pilot would:

1. Select two or three county pairs using harmonized boundaries, baseline farm structures and independently measured market access. Selection must precede inspection of the individual outcomes; the convenient audited pair is not automatically a valid comparison.
2. Assemble family cohorts with dated land purchases, donations and sales, occupational transitions and documented destinations. Trace daughters as well as sons, indirect transfers as well as inherited farms, and retain unresolved links and deaths explicitly.
3. Distinguish movement preceded by land transfer or sale from movement without observed access to land. Search for contemporaneous evidence about failed purchases, credit constraints and job offers. Absence of a deed or a census link is not evidence of exclusion or emigration.
4. Evaluate whether source coverage, linkage selection and observed alternatives actually permit a mechanism claim. If they do not, stop that claim. A linked descriptive study would still require its own novelty argument.

This is a specification of missing evidence, not a claim that I have secured it. BALSAC provides a research access process and variable documentation; I have not obtained a linked extract or submitted an access request. Public notarial or destination records would need a demonstrated retrieval and linkage pilot before being treated as usable research data. [BALSAC research resources and forms](https://www.balsac.ca/en/resources/).

## The 2026 article: a narrower, now checkable assessment

The official article HTML and Table 4 were already downloadable in this session and are retained in the original dossier's source directory. Table 4 confirms the supplement's per-arpent coefficients: −0.079/−0.074 for 1784, without significance markers, and 0.634/0.644 for 1831, both marked at the 1% level. Its per-capita coefficients are positive and significant at both dates. This supports the narrower qualification about a monotonic per-arpent rise, while leaving the positive endpoint finding intact. [Bond, Geloso and Swanson, Table 4](https://link.springer.com/article/10.1007/s11698-026-00342-0/tables/4).

The written equation (2) includes settlement duration and both place and date effects; the preceding definition describes duration since first settlement. A linear duration of calendar year minus a fixed settlement date is algebraically redundant with those effects. That diagnoses the written specification. Without the estimation code, it does **not** establish what software retained or that the reported estimates are invalid. [Article, data definition and equation (2)](https://link.springer.com/article/10.1007/s11698-026-00342-0).

## Deliverables and publication status

`corrected_interpretations.jsonl` contains 112 original retrieval records, each retaining its original value and provenance, with a nested `research_correction` containing the reassigned workbook value and the separately recorded printed value. It is a **local research overlay**. Its hay records have an explicit unit warning. The workbook, staged SQLite, published RDF and live website have not been changed. Existing public URLs still identify original source assertions, not this corrected edition.

`UPSTREAM_NOTE.md` is a prepared, unsent correction report. The source-preserving publication design should expose the correction alongside the original assertion in HTML, retrieval JSONL and a separately versioned RDF correction layer. It should also mark the unresolved arithmetic cases. This implementation and deployment remain outstanding; no claim of a shipped website fix is made here.

The original memo, audit outputs, review and archive are retained. This follow-up is additive and independently reproducible with `python3 research/1851_quebec_measurement_audit_20260907/followup/verify.py` in the source workspace. Its documentary correction is useful. It does not yet meet the requested standard of a significant contribution to historical explanation.
