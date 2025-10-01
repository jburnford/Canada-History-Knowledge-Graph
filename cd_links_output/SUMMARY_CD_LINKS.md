# Census Division Temporal Links - Summary

**Generated**: September 30, 2025
**Method**: Spatial overlap analysis (IoU + containment fractions)
**Years**: 1851-1921 (7 year pairs)

## Overview

Census Divisions (CDs) are administrative aggregations of Census Subdivisions (CSDs). CD boundaries changed significantly over time, especially in Western Canada as new provinces were formed and territories reorganized.

This analysis tracks CD evolution using spatial overlap to identify:
- **SAME_AS**: CDs that remain largely unchanged (IoU > 0.98)
- **CONTAINS**: CD splits (new CDs carved from existing ones)
- **WITHIN**: CD mergers (CDs absorbed into larger units)
- **OVERLAPS**: Complex boundary changes

## Year-by-Year Summary

### 1851 → 1861
- **CDs (1851)**: 95
- **CDs (1861)**: 103
- **Total overlaps**: 169
  - High-confidence: 86
    - SAME_AS: 64
    - CONTAINS: 9
    - WITHIN: 13
  - Ambiguous: 83 (OVERLAPS)

### 1861 → 1871
- **CDs (1861)**: 103
- **CDs (1871)**: 132
- **Total overlaps**: 254
  - High-confidence: 187
    - SAME_AS: 62
    - CONTAINS: 76
    - WITHIN: 49
  - Ambiguous: 67 (OVERLAPS)

### 1871 → 1881
- **CDs (1871)**: 132
- **CDs (1881)**: 159
- **Total overlaps**: 282
  - High-confidence: 198
    - SAME_AS: 71
    - CONTAINS: 61
    - WITHIN: 66
  - Ambiguous: 84 (OVERLAPS)

### 1881 → 1891
- **CDs (1881)**: 159
- **CDs (1891)**: 192
- **Total overlaps**: 320
  - High-confidence: 156
    - SAME_AS: 66
    - CONTAINS: 32
    - WITHIN: 58
  - Ambiguous: 164 (OVERLAPS)

### 1891 → 1901
- **CDs (1891)**: 192
- **CDs (1901)**: 213
- **Total overlaps**: 333
  - High-confidence: 220
    - SAME_AS: 91
    - CONTAINS: 55
    - WITHIN: 74
  - Ambiguous: 113 (OVERLAPS)

### 1901 → 1911
- **CDs (1901)**: 213
- **CDs (1911)**: 221
- **Total overlaps**: 417
  - High-confidence: 167
    - SAME_AS: 83
    - CONTAINS: 32
    - WITHIN: 52
  - Ambiguous: 250 (OVERLAPS) ⚠️ **Highest ambiguity**

### 1911 → 1921
- **CDs (1911)**: 221
- **CDs (1921)**: 222
- **Total overlaps**: 393
  - High-confidence: 230
    - SAME_AS: 80
    - CONTAINS: 67
    - WITHIN: 83
  - Ambiguous: 163 (OVERLAPS)

## Aggregate Statistics

- **Total year pairs**: 7
- **Total CD instances**: 1,317 (across all years)
- **Unique CDs**: 579
- **Total spatial overlaps**: 2,168
  - High-confidence: 1,244 (57%)
  - Ambiguous: 924 (43%)

### Relationship Distribution
- **SAME_AS**: 517 (stable CDs across years)
- **CONTAINS**: 332 (CD subdivisions)
- **WITHIN**: 395 (CD mergers/absorptions)
- **OVERLAPS**: 924 (complex reorganizations)

## Key Observations

### High Stability Periods
- **1891 → 1901**: Highest SAME_AS rate (41% of overlaps)
- **1851 → 1861**: Early stability in Eastern Canada (67% SAME_AS of high-confidence)

### High Change Periods
- **1901 → 1911**: Highest ambiguity (60% OVERLAPS)
  - Alberta/Saskatchewan provincial formation (1905)
  - Extensive CD reorganization in Western provinces
- **1861 → 1871**: Confederation expansion
  - Manitoba creation (1870)
  - Significant territorial reorganization

### Western vs Eastern Patterns
- **Eastern Canada** (ON, QC, Maritimes): More stable CD boundaries
- **Western Canada** (MB, SK, AB, BC): Frequent reorganizations
  - Prairie provinces: Division numbering systems
  - British Columbia: Named districts changing

## Files Generated

### High-Confidence Links
- `cd_links_1851_1861.csv` (86 links)
- `cd_links_1861_1871.csv` (187 links)
- `cd_links_1871_1881.csv` (198 links)
- `cd_links_1881_1891.csv` (156 links)
- `cd_links_1891_1901.csv` (220 links)
- `cd_links_1901_1911.csv` (167 links)
- `cd_links_1911_1921.csv` (230 links)

### Ambiguous Links (Need Review)
- `cd_ambiguous_1851_1861.csv` (83 links)
- `cd_ambiguous_1861_1871.csv` (67 links)
- `cd_ambiguous_1871_1881.csv` (84 links)
- `cd_ambiguous_1881_1891.csv` (164 links)
- `cd_ambiguous_1891_1901.csv` (113 links)
- `cd_ambiguous_1901_1911.csv` (250 links) ⚠️
- `cd_ambiguous_1911_1921.csv` (163 links)

## Next Steps

1. **Create P134_continued relationships**: Convert high-confidence links to Neo4j import format
2. **Review ambiguous links**: Especially 1901→1911 with provincial reorganization
3. **Document CD evolution**: Notable cases (e.g., Alberta/Saskatchewan formation)
4. **Validate with historical records**: Cross-reference CD name changes with administrative history

## Sample Complex Cases

### Alberta/Saskatchewan Formation (1905)
- Northwest Territories CDs reorganized into provincial CDs
- Division numbering systems introduced
- Significant OVERLAPS in 1901→1911 period

### British Columbia Reorganization
- Named districts (Kootenay, Cariboo, etc.) changing boundaries
- Urban CDs splitting from regional CDs (Vancouver, Victoria)

### Manitoba Expansion
- Original small province (1870) expanding westward
- Division numbering evolving with growth
