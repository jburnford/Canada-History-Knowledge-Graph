# Codex Review - Improvement Plan

**Date**: September 30, 2025
**Status**: In Progress

## Analysis of Codex's Review

Codex identifies **critical consistency issues** that must be fixed before Neo4j import, plus valuable enhancements.

---

## 🔴 **MUST FIX NOW (Blocking Issues)**

### **1. E4_Period ID Inconsistency** ⚠️ **CRITICAL**
- **Problem**:
  - Spatial uses: `CENSUS_1901` (with `year:int`)
  - V2 uses: `PERIOD_CENSUS_1901` (without `year:int`)
- **Impact**: P4 relationships will fail to link properly
- **Fix**: Standardize to `CENSUS_YYYY` with `year:int` in both datasets
- **Files to Update**:
  - `scripts/build_census_observations_v2.py`
  - `neo4j_census_v2/e4_periods.csv`
  - `neo4j_census_v2/p4_period_timespan.csv`

### **2. Missing CSD Names on E53_Place**
- **Problem**: E53 CSD nodes have no `name` property (only `place_id`)
- **Impact**: Queries can't find places by name
- **Resources Available**: `canonical_names_final.csv` with corrected names
- **Fix**: Add names from canonical_names or GDB to E53_Place_CSD.csv
- **Files to Update**:
  - `scripts/build_neo4j_cidoc_crm.py` (use `extract_e53_places` function)
  - `neo4j_cidoc_crm/e53_place_csd.csv`

### **3. P89 Time-Scoping Issue**
- **Problem**: Current P89 links E53_CSD → E53_CD without temporal context
- **Impact**: Incorrect hierarchical relationships across years (CD membership changes)
- **Fix Options**:
  - **Option A**: Add `during_period` property to P89 relationships (simpler)
  - **Option B**: Create CD E93_Presence nodes and link presence→presence (cleaner)
- **Files to Update**:
  - `scripts/build_neo4j_cidoc_crm.py` (`extract_p89_falls_within` function)
  - `neo4j_cidoc_crm/p89_falls_within_*.csv`

---

## 🟡 **SHOULD ADD (High Value)**

### **4. CD (Census Division) Temporal Links**
- **Value**: Track CD evolution, boundary changes (especially Western provinces)
- **Method**: Apply same spatial overlap analysis used for CSDs
- **Data Available**: CD polygons in GDB for all years
- **Implementation**:
  - Create CD-specific temporal linking script or extend existing
  - Generate CIDOC-compliant E92/E93 representations for CDs before exporting
  - Output P132_spatiotemporally_overlaps_with relationships once modelling supports it
- **Effort**: Medium - reuse CSD linking methodology with additional modelling work

### **5. P132_spatiotemporally_overlaps_with Temporal Links (CSDs)**
- **Value**: Track CSD evolution, boundary changes, amalgamations
- **Data Available**: `year_links_output/` with 20,737 SAME_AS links + IoU scores
- **Effort**: Medium - read year_links CSVs, create P132 relationships
- **Implementation**:
  - Create `p132_spatiotemporally_overlaps_with_*.csv` files
  - Include overlap metrics (IoU, area fraction) as properties

### **6. E41_Appellation for Names**
- **Value**: Clean name disambiguation, OCR correction tracking
- **Data Available**: `canonical_names_final.csv` (107 corrections, 3,179 intentional changes)
- **Effort**: Medium - create E41 nodes + P1 relationships
- **Implementation**:
  - Model canonical vs variant names properly
  - Link E53_Place → E41_Appellation via P1_is_identified_by

---

## 🟢 **NICE TO HAVE (Lower Priority)**

### **7. Provenance Extensions (E33, E30, E39)**
- **E33_Linguistic_Object**: DOI citation (https://doi.org/10.5683/SP3/PKUZJN)
- **E30_Right**: CC BY 4.0 license
- **E39_Actor**: 8 PIs + CHGIS team
- **Value**: Complete FAIR data principles
- **Effort**: Low - already designed in `CENSUS_CIDOC_CRM_REVISED.md`

### **8. 1911/1921 Multi-Layer GDB**
- **Problem**: Multiple layers for different census tables
- **Value**: 40% more data coverage
- **Effort**: Medium - investigate GDB structure and add layer-name mapping

---

## ❌ **SKIP FOR NOW**

### **9. Git LFS**
- **Reason**: Files under 100MB are fine for GitHub (largest is 53MB)
- **Reconsider**: If files exceed 100MB in future

### **10. RDF/n10s Export**
- **Reason**: Focus on Neo4j graph first
- **Future**: Add after core model is stable

### **11. ETL Orchestration (make/CLI)**
- **Reason**: Premature - scripts work independently
- **Future**: Add if workflow becomes complex

---

## **3-Step Implementation Approach**

### **Step 1: Fix Blocking Issues (Do First)** ✅ **COMPLETE**
1. ✅ Align E4_Period IDs to `CENSUS_YYYY` format
2. ✅ Add names to E53_Place CSD nodes
3. ✅ Fix P89 time-scoping (add `during_period` property)

**Goal**: Ensure v2 dataset is internally consistent and ready for clean Neo4j import
**Status**: ✅ All critical blocking issues resolved

### **Step 2: Enhance Core Model (High ROI)** ✅ **COMPLETE**
4. ✅ Create CD temporal links using spatial overlap (2,168 links generated)
5. ✅ Add P132_spatiotemporally_overlaps_with from year_links (17,060 CSD relationships)
6. ✅ Add E41_Appellation for name variants (350 appellations: 207 canonical + 143 variants)

**Goal**: Rich temporal tracking and proper name modeling
**Status**: ALL enhancements complete (CD link analysis, P132 overlaps, E41_Appellation)

### **Step 3: Complete Provenance (Polish)** ✅ **COMPLETE**
7. ✅ Add E33/E30/E39 provenance entities (27 entities: 9 citations, 1 license, 7 actors, 1 creation, 9 sources)
8. ⏳ Tackle 1911/1921 multi-layer GDB (deferred - requires investigation)

**Goal**: FAIR-compliant dataset with maximum coverage
**Status**: Provenance complete. Multi-layer GDB deferred to future work.

---

## **Codex's Additional Recommendations**

### **Data Quality & Validation**
- Every E93_Presence has P166→E53, P164→E4, P161→E94
- Every E16_Measurement has P39→E93, P40→E54, P91 on E54, P4→E52, P2→E55
- Year counts match expected totals in README_IMPORT.md

### **Pipeline Improvements**
- Unify period ID logic in helper function
- Use `extract_e53_places` in spatial generator
- Time-scope P89 in `extract_p89_falls_within`
- Add explicit layer handling for 1911/1921

### **Neo4j Import Strategy**
- Use `:auto USING PERIODIC COMMIT 10000` for >100k row files
- Bump heap/pagecache (4-8GB heap, disable query logging temporarily)
- Load order: spatial (E53/E93/E94/E4) → census v2 (E55/E58/E52/E16/E54)

### **Repository Hygiene**
- Mark v1 scripts as deprecated
- Consider versioning strategy for large CSVs
- Add lightweight data check script (row counts, orphan detection)

---

## **Current Status** (September 30, 2025)

### ✅ **Completed**
- **V2.0 dataset**: 666,423 measurements (1851-1901) with proper CIDOC-CRM structure
- **Step 1 - Blocking Issues**: ALL RESOLVED
  - E4_Period IDs aligned (`CENSUS_YYYY` format)
  - CSD names added to E53_Place nodes (13,135 CSDs)
  - P89 time-scoped with `during_period` property (21,046 relationships)
- **Step 2 - Enhancements**: ALL COMPLETE
  - CD temporal links: 2,168 links generated (1851-1921)
  - P132_spatiotemporally_overlaps_with relationships: 17,060 CSD overlaps exported
  - Relationship types: SAME_AS (9,423), CONTAINS (6,985), WITHIN (1,954)
  - E41_Appellation name variants: 350 appellations (207 canonical + 143 variants)
- **Step 3 - Provenance**: ALL COMPLETE
  - E33_Linguistic_Object: 9 citations with DOIs
  - E30_Right: 1 license (CC BY 4.0)
  - E39_Actor: 7 creators and contributors
  - E65_Creation: 1 creation activity
  - E73_Information_Object: 9 source files
  - Provenance relationships: 24 (P67, P104, P14)
- **Import guides**: 5 comprehensive guides
  - README_CIDOC_CRM.md (spatial data + temporal overlaps)
  - README_IMPORT.md (census observations)
  - PROVENANCE_IMPORT_GUIDE.md (provenance entities)
  - E41_APPELLATION_GUIDE.md (name variants)
- **Data attribution**: Corrected to Geoff Cunfer et al. / The Canadian Peoples project
- **Codex feedback (Round 2 - Sept 30)**: Fixed 3 minor issues
  - Neo4j label hygiene: Changed `E52_Time-Span` → `E52_Time_Span` (hyphens not allowed)
  - README typo: Fixed `e40_observed_dimension_all.csv` → `p40_observed_dimension_all.csv`
  - Province bug: Fixed `assign_canonical_names_simple.py` to capture `pr_to` correctly (line 59, 71)

### ⏳ **Next Priority**
- **Neo4j Import**: Load complete CIDOC-CRM dataset into Neo4j (spatial + census + temporal + provenance + appellations)
- **Future Enhancement**: Tackle 1911/1921 multi-layer GDB (requires investigation)

---

## **Files to Monitor**

### **Critical Files (Step 1)**
- `scripts/build_census_observations_v2.py`
- `scripts/build_neo4j_cidoc_crm.py`
- `neo4j_census_v2/e4_periods.csv`
- `neo4j_census_v2/p4_period_timespan.csv`
- `neo4j_cidoc_crm/e53_place_csd.csv`
- `neo4j_cidoc_crm/p89_falls_within_*.csv`

### **Enhancement Files (Step 2)**
- `neo4j_cidoc_crm/p132_spatiotemporally_overlaps_with_csd.csv` - 17,060 CSD temporal overlap links
- `neo4j_cidoc_crm/README_CIDOC_CRM.md` - Complete import guide
- `canonical_names_final.csv` (for E41 - optional)

### **Provenance Files (Step 3)**
- `CENSUS_CIDOC_CRM_REVISED.md` (E33/E30/E39 design)
