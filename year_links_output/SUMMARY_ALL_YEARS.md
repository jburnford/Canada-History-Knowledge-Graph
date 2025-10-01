# Canadian Census CSD Temporal Linking - Complete Results

**Generated**: September 30, 2025
**Processing Time**: ~2 minutes
**Method**: Pure spatial overlap analysis (IoU + containment fractions)

## Overview

Successfully linked Census Subdivisions (CSDs) across 7 consecutive census year pairs (1851-1921) using polygon geometry overlap analysis. No Excel files required - all data extracted from TCP FileGDB layers.

## Results Summary

| Year Pair | From CSDs | To CSDs | High-Conf Links | Ambiguous | Total Links |
|-----------|-----------|---------|-----------------|-----------|-------------|
| 1851→1861 | 936       | 1,202   | 973             | 221       | 1,194       |
| 1861→1871 | 1,202     | 1,818   | 1,549           | 333       | 1,882       |
| 1871→1881 | 1,818     | 2,173   | 1,920           | 287       | 2,207       |
| 1881→1891 | 2,173     | 2,509   | 2,144           | 422       | 2,566       |
| 1891→1901 | 2,509     | 3,221   | 2,749           | 490       | 3,239       |
| 1901→1911 | 3,221     | 3,825   | 3,336           | 917       | 4,253       |
| 1911→1921 | 3,825     | 5,363   | 4,389           | 1,007     | 5,396       |
| **TOTAL** | **-**     | **-**   | **17,060**      | **3,677** | **20,737**  |

## Growth Trajectory

Canada's census subdivisions grew **473%** over 70 years:
- **1851**: 936 CSDs (Ontario, Quebec, Maritime provinces)
- **1921**: 5,363 CSDs (Confederation complete, Western expansion)

Key expansion periods:
- **1861-1871**: +51% (Confederation, Manitoba joins 1870)
- **1901-1911**: +19% (Western settlement boom)
- **1911-1921**: +40% (Post-WWI growth, Prairie subdivisions)

## Relationship Type Breakdown

### High-Confidence Links (17,060 total)

| Relationship | Count  | % of Total | Description |
|--------------|--------|------------|-------------|
| **SAME_AS**  | 8,780  | 51.5%      | CSDs with high spatial overlap (IoU > 0.98) and name match |
| **CONTAINS** | 6,615  | 38.8%      | Earlier CSD absorbed/split into smaller units |
| **WITHIN**   | 1,665  | 9.8%       | Later CSD contained within earlier larger area |

### Ambiguous Links (3,677 total)

| Relationship | Count  | % of Total | Description |
|--------------|--------|------------|-------------|
| **OVERLAPS** | 1,917  | 52.1%      | Partial overlap (boundary changes, redrawing) |
| **SAME_AS**  | 1,760  | 47.9%      | Good spatial match but name mismatch (OCR errors) |

## Key Insights

### 1. Temporal Stability
- **51.5%** of CSDs maintained stable boundaries across consecutive census years
- Eastern provinces (ON, QC) show higher stability
- Western provinces show more boundary changes due to settlement patterns

### 2. Administrative Reorganization
- **38.8%** CONTAINS relationships indicate active subdivision/amalgamation
- Peak reorganization: 1901-1911 (1,329 CONTAINS links) - Western settlement
- 1911-1921 shows highest number (1,836) - post-WWI municipal incorporation

### 3. OCR Error Detection
- **1,760 ambiguous SAME_AS links** have perfect spatial match but name discrepancies
- Examples: "Gretna Village" vs "Gretna vl (T1 R1 MW1)" (IoU=1.0, name_sim=65)
- Enables systematic identification of transcription errors in historical records

### 4. Western Redrawing
- **1,917 OVERLAPS** reflect complex boundary changes
- Manitoba CSDs 1901-1911: Extensive township reorganization
- Saskatchewan/Alberta emergence: New provincial subdivisions created

## Data Quality Notes

### Column Naming Inconsistencies (Handled)
- **1851, 1861, 1871, 1881, 1901, 1921**: `Name_CD`, `Name_CSD` (Title Case)
- **1891, 1911**: `NAME_CD`, `NAME_CSD` (UPPERCASE)

### Geometry Validation
- **55 invalid geometries** automatically fixed across all years
- All polygons reprojected to EPSG:3347 (Statistics Canada Lambert) for accurate area calculations

## Output Files

### High-Confidence Links (17,060 records, 1.8 MB)
```
year_links_1851_1861.csv    973 links
year_links_1861_1871.csv    1,549 links
year_links_1871_1881.csv    1,920 links
year_links_1881_1891.csv    2,144 links
year_links_1891_1901.csv    2,749 links
year_links_1901_1911.csv    3,336 links
year_links_1911_1921.csv    4,389 links
```

### Ambiguous Links (3,677 records, 413 KB)
```
ambiguous_1851_1861.csv     221 links
ambiguous_1861_1871.csv     333 links
ambiguous_1871_1881.csv     287 links
ambiguous_1881_1891.csv     422 links
ambiguous_1891_1901.csv     490 links
ambiguous_1901_1911.csv     917 links
ambiguous_1911_1921.csv     1,007 links
```

## Next Steps for Knowledge Graph Integration

### 1. Neo4j Schema Design
```cypher
// Node types
(:CSD {tcpuid, name, cd_name, province, year, area})

// Relationship types
(:CSD)-[:SAME_AS {iou, name_similarity}]->(:CSD)
(:CSD)-[:WITHIN {frac_from, frac_to}]->(:CSD)
(:CSD)-[:CONTAINS {frac_from, frac_to}]->(:CSD)
(:CSD)-[:OVERLAPS {iou, frac_from, frac_to}]->(:CSD)
```

### 2. Temporal Queries
- Track CSD evolution across 70 years
- Identify stable vs. dynamic regions
- Analyze urbanization patterns (WITHIN relationships)
- Detect amalgamation trends (CONTAINS relationships)

### 3. Ambiguous Case Resolution
- Review 1,760 SAME_AS name mismatches for OCR corrections
- Analyze 1,917 OVERLAPS for complex boundary change patterns
- Create manual review workflow for high-value cases

## Technical Details

### Algorithm Parameters
- **IoU threshold (SAME_AS)**: 0.98
- **Coverage threshold (SAME_AS)**: 0.98
- **IoU threshold (OVERLAPS)**: 0.30
- **Name similarity threshold**: 80.0
- **WITHIN threshold**: 95% containment
- **CONTAINS threshold**: 95% coverage

### Performance
- **Total processing time**: ~120 seconds
- **Average per year pair**: ~17 seconds
- **Largest pair (1911→1921)**: ~30 seconds (3,825 → 5,363 CSDs)

### Data Sources
- **GDB**: TCP_CANADA_CSD_202306.gdb
- **Projection**: EPSG:3347 (Statistics Canada Lambert Conformal Conic)
- **Spatial index**: R-tree for efficient overlap detection
- **Name matching**: RapidFuzz (70% CSD name, 30% CD name weighting)