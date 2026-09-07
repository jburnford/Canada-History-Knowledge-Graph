# Follow-up correction supplement

Read `RESPONSE.pdf` or `RESPONSE.md` first. This is an additive response to the redesign review, not a replacement historical paper or a deployed data release.

- `verify.py`: workbook/SQLite/JSONL reconciliation and manually transcribed print comparisons. Requires the current source workspace plus Python/openpyxl.
- `manual_print_transcription.json`: explicit visual-reading inputs, also embedded in the script.
- `all_county_cells.csv`: all 112 St. Maurice/Saguenay statistical cells.
- `corrected_interpretations.jsonl`: original source records with separate nested row reassignments and printed values; read `research_correction`, including any unit warning. Original `rdf_decimal` is intentionally unchanged.
- `printed_localities.csv`: 22 constituent values behind the two 30,000 checks, plus 14 calf/heifer returns.
- `arithmetic_discrepancies.csv`: unresolved inconsistencies already present in print.
- `verification.json`: counts, source hashes and verification limits.
- `UPSTREAM_NOTE.md`: prepared report, not sent.
- `manifest.json`: package file hashes. `reproducibility.json`: rerun comparison.
- `evidence/`: page images for visual review, including the calf/heifer enlargement.

The archive is portable for inspection. Full rerunning requires the original workbooks and current SQLite/JSONL files identified in the script and verification output; it is not advertised as a self-contained national data distribution. The original dossier and reviewer response have not been overwritten.
