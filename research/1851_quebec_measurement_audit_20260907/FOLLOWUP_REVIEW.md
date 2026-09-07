# Review of the follow-up dossier — verdict: ACCEPT

Reviewer: Claude (Fable 5), 7 September 2026. Second-round review of
`followup/` and `followup_dossier.zip`. Independent checks: reran `verify.py`
(all six outputs reproduced byte-for-byte, 150 digital cells verified against
workbook + SQLite + retrieval JSONL under the recorded hashes); read the
evidence page images myself for the load-bearing claims; inspected the
retained Bond article HTML and Table 4.

## Claims verified

1. **Whole-row swap, 112 cells.** Reproduces exactly; sole exception is
   `BA` (calves/heifers) as claimed. The manual print transcription carries
   structural corroboration beyond my page reads: for the 111 agreeing cells,
   the print reading coincides with the *machine-verified opposite workbook
   cell* — a misreading would not coincide. My own reads of printed pp. 131,
   134 and 135 (~2/3 of the columns) match the transcription; pp. 130/132/133
   rest on the coincidence argument, which is strong.
2. **Both 30,000 discrepancies are in print.** I independently summed the
   locality columns from the page images: Richelieu oats 224,297 vs printed
   total 194,297; Rouville wheat 186,962 vs 156,962. In both counties the
   *acres* column sums exactly (18,802 and 28,162), isolating the fault to a
   single bushel figure per county. Annotate-don't-fix is the right call.
   Optional annotation enrichment: the minimal-edit reconciliations are
   Richelieu locality 46,149→16,149 and Rouville locality 34,227→4,227, and
   yield plausibility cuts opposite ways (Rouville 4,227 bu on 4,877 ac ≈ 0.9
   bu/ac is implausible, pointing at the total; Richelieu 16,149 on 3,338 ac
   ≈ 4.8 bu/ac is possible, pointing at the locality). Recording the
   candidates without adjudicating would help future users.
3. **Calves 5,503 vs 5,508.** Confirmed from the enlarged image: printed total
   5,503; the 14 locality returns sum to 5,508, matching the CSD workbook and
   `BA70`. Recording both without adjudication is correct.
4. **Hay units.** Confirmed: printed p. 134 column is headed "Hay—Bundles and
   Tons," with ton sub-totals ("9144 tons.", "19956 tons") printed beneath the
   large bundle totals. The `HAY_XX_T` warning is warranted. **Follow-up
   flagged below: this is unlikely to be a two-county problem.**
5. **Correction of my first review's triage — Astra is right, I was wrong.**
   All 16 swap screening rows are `partial_observed_subtotal`; the 24 complete
   nonzero comparisons are entirely non-swap counties. My review implied the
   swap pair sat among the 24. Erratum now recorded in REVIEW_RESPONSE.md.
6. **Bond, Geloso and Swanson — now checked against the retained article.**
   Table 4 (official HTML): Gross Output Per Arpent 1784 = −0.079 / −0.074
   (no significance markers), 1831 = 0.634*** / 0.644*** — as stated.
   Equation (2) as written is Y_it = α + βT_it + X_itγ + µ_t + η_i + ε_it with
   T = settlement duration and "newly introduced time fixed effects, µt, and
   area fixed effects, ηi" — so the written specification genuinely contains
   the collinear triple, and the algebraic critique applies to the text as
   published, with the correct hedge retained about what the software
   estimated (the tabled estimable form uses date dummies without a duration
   term).
7. **Overlay design.** 112 records; originals intact with nested
   `research_correction`; unit warnings on the hay cells; adjudication field
   distinguishes the calves case; production data untouched;
   `UPSTREAM_NOTE.md` accurate and unsent. All as represented.

## Remaining gaps (none blocking)

- **Hay units are probably a table-wide problem, not a two-county one.** Both
  county blocks on p. 134 carry ton sub-lines, and Lower Canada hay was
  commonly returned in bundles (bottes). Every QC county's `HAY_XX_T` value in
  this table deserves the same unit audit (and the printed ton sub-totals are
  recoverable per county). This belongs in the upstream note as a general
  caution, not just under the two swapped counties.
- The upstream note is ready to send pending the user's go-ahead; the site/RDF
  correction layer remains to be implemented, as the response itself states.
- The replacement research pilot is sensibly specified (pair pre-selection
  before outcome inspection, daughters and indirect transfers, explicit
  absence-of-evidence rules, a stop condition) and honestly contingent on
  BALSAC/notarial access that has not been secured. No objection; the novelty
  bar relative to Bouchard 1983/1996 must be argued at proposal time, not
  assumed.

## Verdict

Accept. The source-correction track is now publication-grade as a data
note/erratum: one whole-row county swap (TCP CD layer, 1851 V2T6 only), two
printed arithmetic inconsistencies, one printed total/constituent conflict,
and a unit-labelling hazard — each with the right epistemic treatment
(correct, annotate, annotate, warn). The withdrawal of the aggregate mechanism
paper resolves the redesign verdict's strongest objection.
