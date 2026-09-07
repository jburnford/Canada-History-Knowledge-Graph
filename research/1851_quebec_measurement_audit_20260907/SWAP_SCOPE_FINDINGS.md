# Scope and origin of the St. Maurice / Saguenay swap

Follow-up to REVIEW_RESPONSE.md, 7 September 2026. Method: every county row in
each TCP `*_CD_202306.xlsx` workbook (1851 V1T1, V1T3, V2T6, V2T7; 1861 V1T1,
V1T5, V2T11 — 742 county rows total) was compared as a numeric multiset against
the county-total rows of the corresponding `*_PUB_202306.xlsx` transcription
(or, for 1861 V1T1/V1T5, which publish no county totals, against sums of the
PUB CSD rows). Scan script: session scratchpad `swap_scan.py`.

## Where the error lives

The TCP distribution carries four layers per table: OCR (raw print-order
transcription), PUB (coded transcription with PR/CD_NO/CSD_NO), CD and CSD
(derived analysis tables). For 1851 V2T6:

- **OCR layer — correct.** Follows print order; "Total of Saguenay" (2,453
  occupiers) and "Total of St. Maurice" (2,886) match the printed volume.
- **PUB layer — correct.** St. Maurice (CD_NO 73, CSD_NO 0) HELD = 250,090;
  Saguenay (74) = 278,678 — matching the printed page.
- **CSD layer — correct.** Subdivision sums match the printed assignment.
- **CD layer — swapped.** Row 69 "St. Maurice" carries the full printed
  Saguenay line; row 70 the reverse. 100% mutual multiset match with the
  *other* county's PUB total.

So the swap was introduced in TCP's own PUB→CD derivation step and ships in
the original distributed Excel (`1851_V2T6_CD_202306.xlsx`, sha256
`ac90a90f…`); this repo's pipeline preserved it faithfully. Probable
mechanism: the printed volume (and OCR sheet) lists Saguenay as county No. 24
*before* St. Maurice (No. 25), while TCP's CD table orders St. Maurice (073)
before Saguenay (074); totals appear to have been carried by print position
into the reordered rows.

## How widespread

- **Value/label swaps: exactly one.** QC073/QC074 in 1851 V2T6 only. Not
  present in V2T7 (the companion agricultural table), nor in any other 1851 or
  1861 table.
- **A separate, harmless class — PUB↔CD numbering transpositions** where the
  *names and values stay together* in the CD file (no data error): 1851 V1T1
  Montreal City/Quebec City (CD 084/085 vs PUB 85/84); 1851 V2T6+V2T7
  Norfolk/Northumberland (ON024/025), Peel/Perth (ON028/029),
  Welland/Wellington (ON039/040); 1851 V2T7 Kingston/Hamilton (ON044/045).
  All are adjacent alphabetical pairs; only PUB's CD_NO deviates. Relevant
  only if anything ever joins on PUB CD_NO instead of TCPUID.
- **1861: clean.** V1T5 and V2T11 fully consistent; V1T1 has three residual
  low-signal rows (Rimouski, Lennox & Addington, Nipissing) whose best match
  is still their own county — blank-cell noise, not swaps.
- The Rouville WHT_XX_B / Richelieu OAT_XX_B exact-30,000 differences are a
  different class (CD and PUB agree with each other; the CSD file disagrees).
  *[Resolved later same day: both are internal inconsistencies in the printed
  volume — the printed locality returns sum to exactly 30,000 more than the
  printed county total in each case, while the acres columns sum exactly. All
  digital layers transcribe print faithfully. Annotation, not correction. See
  `followup/` and FOLLOWUP_REVIEW.md.]*

## Action items

1. Correct QC073/QC074 in the 1851 V2T6 CD-derived data (all variables, incl.
   `FRM_XX_N` 2,453↔2,886), or overlay PUB totals in the pipeline.
2. Report upstream to TCP.
3. Never join TCP CD data to PUB via CD_NO; use TCPUID/name.
