# Prairie census research, 1921

Start with **DRAFT.pdf** or [DRAFT.md](DRAFT.md). The paper is an exploratory quantitative contribution whose significance and novelty remain open to review. [REVIEW_REQUEST.md](REVIEW_REQUEST.md) provides a critical brief for Fable 5.1. `review_package.zip` contains the draft, methods, data extracts, code, figures and validation reports.

From the pipeline repository root:

```bash
python3 research/1921_prairie_sex_balance_20260907/analyze.py
python3 research/1921_prairie_sex_balance_20260907/verify.py
python3 research/1921_prairie_sex_balance_20260907/make_figures.py
python3 research/1921_prairie_sex_balance_20260907/package_draft.py
```

The main analysis uses the standard library and the current local SQLite/JSONL source files. Independent verification also uses `openpyxl` and the original workbook at its recorded path. Figures use matplotlib. Packaging uses Markdown and WeasyPrint. These dependencies were available in the research environment; no installations were made.

For a standalone check after extracting the ZIP, run `python3 recheck_extract.py`. It needs only the standard library and the included evidence extract, and independently recalculates the main pooled result without access to the repository.

The full original census PDF and 1929 monograph were downloaded into `external_sources/` and are excluded from the review ZIP to keep it small. Selected census page images used in the audit are included. Download the original volume, if needed, with:

```bash
curl --fail --location --referer https://publications.gc.ca/ https://publications.gc.ca/collections/collection_2017/statcan/CS98-1921-1-1924.pdf -o research/1921_prairie_sex_balance_20260907/external_sources/census_1921_volume1.pdf
```

The referer permits direct retrieval past the site's archive information page; the downloaded file's PDF signature and hash were checked. The website's public retrieval file can be downloaded from [the source catalogue](https://jimclifford.ca/hgiscanada/sources/1921_V1T16_PUB_202306/). Local SQLite and original workbooks are not advertised as public downloads. `source_cells.jsonl.gz` in the review ZIP contains every cell needed for the main and sensitivity calculations; use its supplied citation URLs.

The principal outputs are `main_totals.csv`, `ratios.csv`, `decomposition.csv`, `cities.csv`, `sensitivity.csv` and `within_divisions.csv`. Audits are in `validation.json`, `independent_validation.json`, `reconciliation.csv` and `blank_cell_audit.csv`. Exact source identity is in `provenance.json`; the main 180 cell references are in `main_citations.csv`. [METHODS.md](METHODS.md) specifies every population partition and limitation. [SOURCES.md](SOURCES.md) records the literature consulted and the development of the question.

No source or website files were modified, no publication was deployed, and no past research papers or pre-existing analyses in the repository were consulted. This directory was created for this investigation on 7 September 2026.
