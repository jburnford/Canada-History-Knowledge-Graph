# Quebec agricultural crisis: second investigation

Start with [RESEARCH_MEMO.md](RESEARCH_MEMO.md), then [REVIEW_REQUEST.md](REVIEW_REQUEST.md).

This is a research dossier, not a finished historical paper or a claim of a breakthrough.

`audit.py` reproduces the county reconciliation, preserved source extract, four workbook checks against manually inspected printed entries, and the synthetic panel algebra check. The script reads current source data only and does not change it. It does not automatically read or transcribe the printed image; that verification is explicitly manual.

`source_cells.jsonl.gz` preserves all selected source records and their supplied citations. `provenance.json` records workbook paths and hashes. `county_reconciliation.csv` labels sums with nonnumeric constituents as partial observed subtotals. `verified_print_discrepancies.csv` contains the four verified wheat discrepancies. `validation.json` reports checks and their limits.

Downloaded external sources are stored separately. A file initially downloaded as `external_sources/mcinnis_1981.pdf` was actually a browser-verification HTML response; it is not used as a PDF or included in the review package. McInnis was read through the web tool's accessible PDF text. The full 2019 Geloso article and the 2026 replication data have not been obtained.
