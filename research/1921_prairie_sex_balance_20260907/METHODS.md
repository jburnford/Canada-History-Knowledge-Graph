# Methods and evidentiary limits

Companion to *Where the male surplus lived*, version 1, 7 September 2026.

The analytical population is the 1921 population recorded for Manitoba, Saskatchewan and Alberta in source `1921_V1T16_PUB_202306`. The source is read through SQLite in read-only mode. Its original workbook SHA-256 is `d74714fc2ac372de79462a33951ed975fb1ac307fe703a9ba3922055c3472fbf`; worksheet `CA_V1T16_1921`. The research directory is separate from the publication data. No old research papers, benchmark outputs or existing research analyses were read.

The nine analytical columns are:

| Worksheet column | Meaning |
|---|---|
| G | Total population, both sexes |
| H, I | Total males, females |
| J, K | Canadian-born males, females |
| L, M | British-born males, females |
| N, O | Foreign-born males, females |

All nine are counts of persons for reference year and reporting vintage 1921. “British-born” is the census's category, which is broader than an unqualified modern use of UK-born: the contemporary birthplace monograph includes British possessions and Newfoundland in its British-born breakdown. “Foreign-born” is the mutually exclusive non-British foreign category. The analysis does not relabel these as ethnicity or citizenship. The detailed original definitions remain in `source_cells.jsonl.gz`.

The main selection uses the reporting level `census_subdivision_reporting_unit`, provinces MB/SK/AB, and exact source label suffix `, C`. The three province totals are separately selected by level. Their worksheet rows are 3877, 4086 and 4912. The seventeen cities are:

| Province | City | Worksheet row | Printed Table 16 page |
|---|---|---:|---:|
| MB | Portage la Prairie | 3957 | 313 |
| MB | St. Boniface | 3958 | 313 |
| MB | Winnipeg | 3959 | 313 |
| MB | Brandon | 3972 | 314 |
| SK | Weyburn | 4155 | 317 |
| SK | Regina | 4349 | 320 |
| SK | Moosejaw (source spelling) | 4420 | 321 |
| SK | Swift Current | 4472 | 321 |
| SK | Saskatoon | 4599 | 323 |
| SK | Prince Albert | 4804 | 327 |
| SK | North Battleford | 4858 | 328 |
| AB | Medicine Hat | 4936 | 329 |
| AB | Lethbridge | 4963 | 329 |
| AB | Calgary | 5104 | 332 |
| AB | Red Deer | 5187 | 333 |
| AB | Wetaskiwin | 5188 | 334 |
| AB | Edmonton | 5293 | 335 |

Printed page locations were located using the downloaded volume's text layer and page images; only the six rows listed in `verify.py` were visually checked across all nine values. The PDF's one-based page number is the printed Arabic page plus 98 in this portion of the volume.

Province totals and their constituent rows are never summed together. Let C be the sum of city counts and P the sum of province counts. The main remainder R is P−C separately in every column. It is a mixture of non-city settlements and rural reporting units. Urban areas defined by municipalities differ from metropolitan areas. St. Boniface is separately designated as a city in the source; suburban St. James, for example, remains outside the city selection. Comparisons do not assume modern borders or use external GIS matches.

For birthplace group g in area a, let n_ag be the male-plus-female count, w_ag = n_ag / n_a its population weight, and p_ag = males_ag / n_ag its male proportion. The overall male proportion is p_a = Σ_g w_ag p_ag. The observed difference is D = p_R−p_C. The exact symmetric decomposition is:

```
W = sum_g [ (w_Rg + w_Cg)/2 * (p_Rg - p_Cg) ]
B = sum_g [ (p_Rg + p_Cg)/2 * (w_Rg - w_Cg) ]
D = W + B
```

W describes differences within the three birthplace groups; B describes their composition. Multiplying by 100 expresses contributions in percentage points. `analyze.py` uses rational arithmetic for these identities; values are converted to floating point only for export. Decimal strings are first parsed exactly, then converted to integers after checking that they are nonnegative whole counts. Ratios use 100×males/females. No person-count input is rounded.

The alternative validation in `verify.py` calculates W twice, once with city weights and once with remainder weights, then averages the results. It reads the main counts directly from the original workbook. The resulting pooled W is 4.992741443791594 percentage points, agreeing with the main exact-arithmetic calculation within floating-point tolerance. The decomposition is an application of [Evelyn M. Kitagawa's standard two-component method](https://doi.org/10.1080/01621459.1955.10501299), not a causal model.

Sensitivity comparisons are all reported in `sensitivity.csv`. The main partition uses all seventeen cities. The population-threshold partition uses nine designated cities of at least 10,000; other cities join the remainder in this variant. Each leave-one-city-out comparison removes that city's counts from the universe as well as the selected group, keeping the main non-city remainder fixed. The special Winnipeg row duplicates its leave-one-out case to make it easy to find. The observed gap ranges from 4.563 to 4.884 points across the seventeen leave-one-out cases.

The broader urban selection uses exact suffixes `, C`, `, T-V`, or `, VL`. It includes 656 subdivisions with a combined population of 703,478. Summing the complete total-population column reproduces the three published urban totals in source `1921_V3T3_PUB_202306` exactly. That comparison uses province totals, not a local cross-table name or code join. The second source's path and checksums appear in `independent_validation.json`.

There are 105 incomplete rows among the 1,519 Prairie subdivisions, including 28 in the broader urban selection. Main city and province rows are complete. Original nulls remain null in the extract. For a separately labelled sensitivity only, zeros are derived when a recorded nonnegative total is exhausted by its recorded components: G=H+I, H=J+L+N, I=K+M+O. If the known components already equal the parent total, every missing nonnegative component must be zero under these accounting assumptions. In a few tiny reporting units I itself is blank; G=H first forces I=0, then its birthplace components to zero. All 105 incomplete local rows can be completed under these constraints and all completed identities hold. This is an explicitly conditional analytical derivation, not a statement that a source blank lexically means zero. `blank_cell_audit.csv` records each affected row and its missing columns.

The complete-record urban comparison uses only the 628 urban rows with all nine numeric values; its remainder includes the excluded urban rows. Consequently it is labelled a selected-urban versus remainder sensitivity, not an exact urban–rural partition. The 68 urban units of at least 1,000 people are all complete. The main finding does not rely on derived zeros.

For local comparisons, the provincial and `CD_NO` metadata in this single source identify city membership within census divisions. Fourteen divisions contain the seventeen cities. Each division's main city sum is subtracted from that division's own total. All fourteen overall differences are positive. Canadian- and British-born differences are positive in all fourteen; foreign-born differences are negative in two cases, Prince Albert's and North Battleford's divisions. Results are descriptive local comparisons and neither independent samples nor natural experiments.

Uncertainty is evaluated through source checks, explicit accounting and alternative definitions. Sampling confidence intervals and p-values are omitted because these are published enumeration totals and a deterministic decomposition, not a random sample design. This does not imply error-free enumeration. The workbook, SQLite and JSONL share a source lineage, so their agreement establishes preservation rather than independent historical truth. Printed-source checking covered 54 selected values, not every row. No correction was made to publication inputs.

The main interpretive limits are all-age aggregation; no province-of-birth breakdown within Canadian birth; no detailed foreign countries or arrival periods; no occupation, marital-status or movement histories; colonial categorization and possible enumeration errors; and an exploratory selection of the question. Within-category components can contain age and finer birthplace composition effects as well as migration and mortality processes. Reclassification more detailed than these three groups could produce a different decomposition. “Composition contributes little” is therefore restricted to the displayed three-category calculation.

The evidence file contains 14,157 source cells covering 1,519 local rows, 51 division totals and three province totals. Each cell retains the source's original value/status, citation URL, RDF identifier, workbook SHA-256, reporting subject and definitions. `main_citations.csv` exposes all 180 cells used in the main pooled and provincial results. `provenance.json` records exact input hashes. The research code does not require a SPARQL endpoint and makes no claims about retrieval benchmarks or ontology conformance.
