# Prepared correction report — not sent

Subject: 1851 V2T6 CD workbook: St. Maurice/Saguenay row transposition, plus separate source discrepancies

The workbook `1851_V2T6_CD_202306.xlsx`, worksheet `Sheet1`, SHA-256 `ac90a90f1e0b552a1575f3e88d58c193f79566f0f9ec29cce9f0ba8cd042c8ca`, assigns the statistical block F:BI to the wrong county in rows 69 and 70.

- Row 69 is labelled St. Maurice, code QC073, but its statistics belong to printed Saguenay.
- Row 70 is labelled Saguenay, code QC074, but its statistics belong to printed St. Maurice.
- Across 112 cells, 111 opposite-row entries agree with the printed county totals. The remaining discrepancy is `BA70`, calves/heifers: workbook 5,508 versus printed St. Maurice 5,503. The 14 printed locality returns also sum to 5,508 and match the CSD workbook. Preserve this as an unresolved printed-total discrepancy; do not automatically replace 5,508 with 5,503.

The primary reference is the [1851 census, volume II](https://publications.gc.ca/collections/collection_2012/statcan/rh-hc/CS98-1851-2-eng.pdf), printed pages 130–135, corresponding to PDF pages 188–193 (one-based). The attached comparison CSV records every column and printed page. The current CSD workbook's observed subtotals independently support the printed county assignment for eight audited variables, although those comparisons contain missing entries and are not complete enumerations.

Two separate cautions:

1. The hay variable `HAY_XX_T` contains 1,280,162 and 2,796,856 for these rows. Printed p. 134 gives these as bundles, with 9,144 and 19,956 tons separately underneath. Please review the unit representation, including other rows, rather than interpreting the large figures as tons.
2. Richelieu oat output and Rouville wheat output differ from their constituent sums by exactly 30,000. The workbooks faithfully reproduce the printed county totals **and** the checked locality values. These cases require source-arithmetic annotations; our evidence does not identify which printed figure should be replaced.

Recommended correction: reassign the F:BI statistical blocks to the printed counties, annotate the separate calf/heifer total disagreement, preserve the original edition and record an erratum. Keep blank returns distinct from zero. Attach the hay unit qualification and unresolved arithmetic annotations to derived exports. Source-fidelity corrections do not establish the underlying accuracy of the enumeration.

Evidence: `all_county_cells.csv`, `printed_localities.csv`, `arithmetic_discrepancies.csv`, `verification.json`, primary-page images, and reproducible `verify.py`.
