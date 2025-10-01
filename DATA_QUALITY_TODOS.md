# Data Quality To-Do List

**Date Created**: September 30, 2025
**Source**: Codex data quality audit of census observations
**Status**: Ready for review

---

## Overview

These issues were identified during Codex's review of the census observation data (1851-1901). Most appear to be OCR errors or data entry issues from the original CHGIS dataset creation, not errors introduced by our CIDOC-CRM transformation. However, we should address them before final publication to ensure LOD quality.

---

## 🔴 High Priority - Data Integrity Issues

### 1. Missing Numeric Values with Placeholder Strings (1851)
**Issue**: Observation rows where `value_numeric:float` is blank but `value_string` contains placeholders like `.`

**Impact**: Published LOD will have E54_Dimension nodes without actual values

**Action Items**:
- [ ] Query 1851 observations where `value_numeric IS NULL AND value_string = '.'`
- [ ] Determine if `.` indicates:
  - Missing census data (legitimate null)
  - OCR noise (should be removed)
  - Special meaning in historical context
- [ ] Decision: Either populate `value_numeric` or add metadata flag for "no data recorded"
- [ ] Document decision in provenance

**Priority**: High - affects data completeness

---

### 2. OCR Errors in Agricultural Data (1851)
**Issue**: Alpha-numeric strings in `value_string` that should be numeric totals:
- `9S6` (likely `956`)
- `2S56` (likely `2256` or `256`)
- `163'` (likely `163`)

**Impact**: Agricultural statistics are unparsed and unusable for numeric queries

**Action Items**:
- [ ] Query 1851 observations where `value_string ~ '[0-9]+[A-Z]+[0-9]+' OR value_string ~ '[0-9]+''`
- [ ] Build OCR correction mapping (S→5, l→1, etc.)
- [ ] Parse corrected values into `value_numeric:float`
- [ ] Flag as `corrected_ocr:true` in E54_Dimension properties
- [ ] Add provenance note: "OCR correction applied"

**Priority**: High - affects agricultural data accuracy

---

### 3. Lowercase 'l' for '1' in Population Data (1881)
**Issue**: Population record stores `"l,003"` (lowercase L) instead of `"1,003"`

**Impact**: Population count missing from numeric field

**Action Items**:
- [ ] Find 1881 observation(s) with `value_string = 'l,003'`
- [ ] Verify intended value is `1,003` (check against other sources if possible)
- [ ] Correct to `value_numeric = 1003.0`
- [ ] Add OCR correction flag

**Priority**: High - population is critical demographic data

---

## 🟡 Medium Priority - Model Consistency Issues

### 4. Textual County Names in Numeric Dataset (1871)
**Issue**: County names appear in `value_string` (e.g., `"Prince County"`) with `variable_category = UNKNOWN`

**Impact**: Breaks assumption that observations are quantitative measurements

**Action Items**:
- [ ] Identify all 1871 observations where `value_string` contains county names
- [ ] Decision options:
  - **Option A**: Remove these observations (county already in E53_Place hierarchy)
  - **Option B**: Model as E41_Appellation linked via different relationship
  - **Option C**: Create new variable category (e.g., `ADMINISTRATIVE_NAME`)
- [ ] Implement chosen approach
- [ ] Document in `CENSUS_CIDOC_CRM_REVISED.md`

**Priority**: Medium - affects model consistency

---

### 5. Sterling Currency Strings (1871)
**Issue**: Monetary values stored as formatted strings (e.g., `"£14 s0 d0"`) with `variable_category = UNKNOWN`

**Impact**: Financial data not parseable for economic analysis

**Action Items**:
- [ ] Query 1871 observations matching pattern `£[0-9]+ s[0-9]+ d[0-9]+`
- [ ] Parse pounds/shillings/pence into decimal pounds (e.g., `£14 0s 0d` → `14.0`)
- [ ] Store in `value_numeric:float` with `E58_Measurement_Unit = "GBP_pounds_sterling"`
- [ ] Keep original string in `value_string` for reference
- [ ] Update `variable_category` to `ECONOMIC` or `FINANCIAL`

**Priority**: Medium - enables economic queries

---

### 6. Ethnicity Observation Fragments (1861)
**Issue**: Ethnicity observations with cryptic fragments like `"I 1"` in `value_string`

**Impact**: Unclear if these are counts, codes, or transcription errors

**Action Items**:
- [ ] Review all 1861 ethnicity observations (grep for `variable_category = DEMOGRAPHIC` and ethnicity-related vars)
- [ ] Cross-reference with original 1861 census tables (check `1861Tables/` directory)
- [ ] Determine meaning:
  - If counts: parse to `value_numeric`
  - If codes: create E55_Type taxonomy
  - If errors: flag for removal or correction
- [ ] Document ethnicity variable structure in README

**Priority**: Medium - affects demographic completeness

---

## 🟢 Low Priority - Type Definition Gaps

### 7. Missing E55_Type Definitions
**Issue**: Variables exist in observations but have no corresponding `VAR_...` node in `e55_types.csv`:
- `POP_MX_N.1` (male population variant?)
- `POP_FX_N.1` (female population variant?)
- `POP_XX_N.1` (total population variant?)
- `HRS_ov03_V` (horses over 3 years?)
- `NAME_COUNTY` (county name - see issue #4)
- `NUMBER_CD` (census division number - see issue #8)

**Impact**: P2_has_type relationships point to non-existent nodes (broken graph)

**Action Items**:
- [ ] Extract full list of variables from observations that lack E55_Type definitions
- [ ] Research variable meanings from original census documentation
- [ ] Add rows to `e55_types.csv` with:
  - `type_id` (e.g., `VAR_POP_MX_N.1`)
  - `label` (human-readable name)
  - `category` (POPULATION, AGRICULTURE, etc.)
  - `description` (optional)
- [ ] Regenerate census observations to include new types

**Priority**: Low - doesn't affect existing valid data, but creates graph integrity issue

---

### 8. NUMBER_CD Metadata vs. Observation
**Issue**: `NUMBER_CD` field in 1881 may be metadata (Census Division identifier) rather than a measured observation

**Impact**: If it's metadata, it shouldn't be modeled as E16_Measurement

**Action Items**:
- [ ] Review how `NUMBER_CD` is used in 1881 data
- [ ] Check if it's redundant with existing CD hierarchy (E53_Place CDs)
- [ ] Decision:
  - If metadata: Remove from observations, ensure CD linkage via P89_falls_within
  - If observation: Add proper E55_Type definition with category `ADMINISTRATIVE`
- [ ] Update `build_census_observations.py` if needed

**Priority**: Low - likely redundant with existing place hierarchy

---

## Implementation Strategy

### Phase 1: Quick Wins (1-2 hours)
1. Fix obvious OCR errors (lowercase 'l' → '1', 'S' → '5')
2. Add missing E55_Type definitions for common variables
3. Document decisions in `DATA_QUALITY_NOTES.md`

### Phase 2: Data Analysis (2-4 hours)
1. Query each dataset year for problematic patterns
2. Build correction mappings (OCR, currency parsing)
3. Cross-reference with original census tables when needed

### Phase 3: Regeneration (1 hour)
1. Update `build_census_observations.py` with corrections
2. Regenerate affected year CSVs (1851, 1861, 1871, 1881)
3. Re-run data validation queries

### Phase 4: Documentation (1 hour)
1. Update `README_IMPORT.md` with known data quality issues
2. Add data quality section to main `README.md`
3. Create `KNOWN_DATA_ISSUES.md` for transparency

---

## Notes

- **Source Attribution**: Most issues originate from CHGIS dataset OCR/digitization, not our transformation
- **Transparency**: Document all corrections in provenance (E73_Information_Object notes)
- **Validation**: After fixes, run queries to verify:
  - All observations have either `value_numeric` OR `value_string` with valid content
  - All P2_has_type relationships target existing E55_Type nodes
  - No orphaned nodes (E54 without E16, etc.)

---

## Progress Tracking

- [ ] Phase 1: Quick Wins
- [ ] Phase 2: Data Analysis
- [ ] Phase 3: Regeneration
- [ ] Phase 4: Documentation

**Estimated Total Effort**: 5-8 hours

---

**Last Updated**: September 30, 2025
