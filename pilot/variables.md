# Pilot Variable Lock-in (ON, 1851–1921)

Five variables selected to stress-test three knowledge-graph models across distinct data types and sparsity patterns. Picked after scanning `neo4j_census_v2/e55_variable_types.csv` and per-year `p2_has_type_*.csv` on 2026-04-24.

## The fractional-data reality

The source CSDs are almost entirely integer counts. A scan of all ON dimension values across 8 census years turned up only **5 variables** with genuinely non-integer values:

| Variable | Year | Fractional rows (ON) | Type |
|---|---|---|---|
| `POP_AVF_PR` | 1891 | 710 | ratio |
| `FAMILIES_AV_SIZE` | 1891 | 710 | ratio |
| `POP_PER_SQ_MI` | 1911 | 1,004 | ratio |
| `AREA_SQ_MI` | 1911 | 1,042 | area |
| stray AGR | 1891 | 3 | mostly noise |

Everything else — population, acres, bushels, livestock, religion/origin counts — is rounded integer. The float test is therefore narrow and we keep one token float (`POP_PER_SQ_MI`) rather than fabricate diversity the data doesn't have.

## Five selected variables

| Schema column | Type | Source variable(s) by year | Coverage | Role |
|---|---|---|---|---|
| `pop_total` | INT64 | `VAR_POP_XX_N` (1851, 1871); `VAR_POP_TOT` (1861, 1881–1921) | all 8 years | integer count, always-present, name drift |
| `pop_total_m` | INT64 | `VAR_POP_MX_N` (1851–1881); `VAR_POP_M` (1891–1921) | all 8 years | sex split, name drift |
| `pop_total_f` | INT64 | `VAR_POP_FX_N` (1851–1881); `VAR_POP_F` (1891–1921) | all 8 years | sex split, name drift |
| `pop_per_sq_mi` | DOUBLE | `VAR_POP_PER_SQ_MI` | **1911 only** | genuine fractional values; null-vs-zero probe target |
| `cd_name` | STRING | `VAR_CD_NAME` (value_string column in e54) | 1851, 1861, 1881 (partial) | categorical string, early-years sparse |

### Name-drift details (integer counts)

```
pop_total:
  1851  VAR_POP_XX_N    (897 ON rows)
  1861  VAR_POP_TOT     (1161)  or VAR_POP_XX_N (1162)
  1871  VAR_POP_XX_N    (1773)  — VAR_POP_TOT only has 71 rows, incomplete
  1881  VAR_POP_TOT     (2135)
  1891  VAR_POP_TOT     (2473)
  1901  VAR_POP_TOT     (3181)
  1911  VAR_POP_TOT     (3761)  — POP_XX_N absent
  1921  VAR_POP_TOT     (5312)

pop_total_m:
  1851–1881  VAR_POP_MX_N
  1891       VAR_POP_MX_N and VAR_POP_M both present
  1901       VAR_POP_MX_N and VAR_POP_M both present
  1911–1921  VAR_POP_M only

pop_total_f:  mirrors pop_total_m (FX_N → F)
```

Rule for the exporters: prefer `VAR_POP_TOT` / `VAR_POP_M` / `VAR_POP_F` where present; fall back to the `*_XX_N` / `*_MX_N` / `*_FX_N` family when the TOT form is absent or incomplete (1851, 1871).

## Sparsity patterns exercised

| Pattern | Variable | Tests |
|---|---|---|
| Always present (with drift) | `pop_total` + sex split | how each model represents a variable whose source column changes name |
| Early-years only | `cd_name` | how each model represents a categorical string variable in some years, absent in others |
| Single-year only | `pop_per_sq_mi` | how each model distinguishes "not asked" from zero (the null-vs-zero probe) |

## Null-vs-zero probe

Use `pop_per_sq_mi` for the Track-2 probe: *"What was the population density of Westmeath in 1851?"*

Expected answer: **"That variable wasn't recorded in the 1851 census — only 1911."** Record per-approach whether the model distinguishes this from a zero return or an empty result set.

- Approach A (full CIDOC-CRM): no E16_Measurement for 1851 density → SPARQL returns no rows. Correct but requires interpreting emptiness.
- Approach B (Lite): no `base:pop_per_sq_mi` triple on 1851 presence → same as A. Cannot distinguish "not asked" from "asked and zero" without an extra annotation.
- Approach C (Kuzu): `Presence.pop_per_sq_mi = NULL` for 1851 rows. Distinguishable from `= 0.0`.

This distinction is documented as a known expressivity gap of A/B vs C.

## Out-of-scope variables considered and rejected

- `VAR_FML_XX_A` (acres of farmland, 1851/1861/1891): values are whole-number acres stored as floats — not a genuine fractional test.
- `VAR_CAN_BORN_M` (Canadian-born males, 1921 only): good sparse-integer candidate but `pop_per_sq_mi` already covers single-year sparsity and adds the float axis.
- Religion / origin detail variables: dozens per year with inconsistent coding; out of scope for a 5-variable pilot.
