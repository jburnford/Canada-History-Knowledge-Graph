# Community Linking Progress

**Date**: October 1, 2025
**Status**: In Progress - Wikidata communities fetched, 1921 LOD conversion ready

---

## Objective

Link real-world Canadian communities (cities, towns, villages) with persistent identities to census administrative geography. This distinguishes between:

1. **Real Communities**: Settlements with continuous existence, founding dates, Wikidata/GeoNames PIDs
2. **Census Geography**: Administrative units (CSDs/CDs) that change boundaries over time

---

## Progress Summary

### ✅ Completed

1. **Wikidata Community Extraction** (October 1, 2025)
   - Fetched 2,897 Canadian communities via SPARQL query
   - Entity types: 1,626 hamlets, 522 villages, 507 towns, 121 cities
   - Coverage: 514 with founding dates, 2,876 with coordinates
   - Cross-references: 933 with GeoNames IDs (32.2%)

2. **Data Files Generated**
   - `neo4j_communities/e53_communities.csv` - 2,897 community nodes
   - `neo4j_communities/e42_identifiers.csv` - Wikidata + GeoNames PIDs
   - `neo4j_communities/p1_community_identifiers.csv` - Identifier relationships
   - `communities_no_geonames.csv` - 1,964 communities without GeoNames (for review)

3. **Script Development**
   - `scripts/fetch_canadian_communities_wikidata.py` - Working Wikidata fetcher
   - `scripts/convert_1921_to_lod.py` - Ready for 1921 LOD conversion and matching

### 🔄 In Progress

1. **1921 Census LOD Conversion**
   - Script ready to convert 5,363 CSDs to LOD format with URIs
   - Automated matching to Wikidata communities (name + coordinates + province)
   - Expected match rate: ~40-60% for 1921 CSDs

2. **GeoNames Gap Analysis**
   - 1,964 communities (67.8%) lack GeoNames IDs
   - Heavily skewed to hamlets (1,577) and small villages (301)
   - May need manual GeoNames API queries for missing entities

### ⏳ Pending

1. **Import Community Data to Neo4j**
   - E53_Place nodes for communities (distinct from census CSDs)
   - E42_Identifier nodes for Wikidata/GeoNames PIDs
   - P1_is_identified_by relationships

2. **Link Communities to Census Presences**
   - Create `was_enumerated_as` relationships
   - Link communities to E93_Presence nodes (1851-1921)
   - Handle name changes, amalgamations, boundary shifts

3. **Validate and Enhance**
   - Manual review of low-confidence matches
   - Query GeoNames API for missing IDs
   - Add additional Wikidata properties (incorporation dates, population)

---

## Data Model

### New Entity: Community (E53_Place with place_type='COMMUNITY')

```
E53_Place (Community)
  - place_id: COMMUNITY_{wikidata_id}
  - name: "City of Ottawa"
  - place_type: "COMMUNITY"
  - community_type: "city" | "town" | "village" | "hamlet"
  - wikidata_id: "Q1930"
  - wikidata_uri: "http://www.wikidata.org/entity/Q1930"
  - geonames_id: "6094817"
  - inception_date: "1826-01-01" (founding)
  - province: "Ontario"
  - latitude, longitude: Centroid coordinates
```

### Relationship: was_enumerated_as

```
(Community:E53_Place)-[:was_enumerated_as {
  match_confidence: 0.95,
  match_method: "automated_fuzzy_match",
  census_year: 1921
}]->(CSD_Presence:E93_Presence)
```

### Example Graph Structure

```
[City of Ottawa] (Q1930, GeoNames 6094817)
  ├─ P1_is_identified_by → E42_Identifier (Wikidata Q1930)
  ├─ P1_is_identified_by → E42_Identifier (GeoNames 6094817)
  ├─ was_enumerated_as → E93_Presence (Ottawa CSD, 1851)
  ├─ was_enumerated_as → E93_Presence (Ottawa CSD, 1861)
  ├─ was_enumerated_as → E93_Presence (Ottawa CSD, 1871)
  └─ was_enumerated_as → E93_Presence (Ottawa CSD, 1901)
```

---

## Wikidata SPARQL Query Used

```sparql
SELECT DISTINCT ?place ?placeLabel ?typeLabel ?inception ?coords ?geonames ?provinceLabel
WHERE {
  VALUES ?type {
    wd:Q15284     # municipality (general)
    wd:Q515       # city
    wd:Q3957      # town
    wd:Q532       # village
    wd:Q1549591   # big city
    wd:Q5084      # hamlet
    wd:Q3327873   # municipality of Canada
    wd:Q3504868   # city of Canada
  }

  ?place wdt:P31 ?type ;        # instance of municipality/city/town/etc
         wdt:P17 wd:Q16 .        # country = Canada

  OPTIONAL { ?place wdt:P571 ?inception . }       # founding/inception date
  OPTIONAL { ?place wdt:P625 ?coords . }          # coordinates
  OPTIONAL { ?place wdt:P1566 ?geonames . }       # GeoNames ID
  OPTIONAL { ?place wdt:P131 ?province . }        # located in province

  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,fr" . }
}
LIMIT 5000
```

---

## Sample Communities Retrieved

| Name | Wikidata ID | Type | Founded | GeoNames | Province |
|------|-------------|------|---------|----------|----------|
| Edmonton | Q2096 | city | 1795-01-01 | 5946768 | Alberta |
| Niagara Falls | Q274120 | city | 1903-06-12 | 6087892 | Regional Municipality of Niagara |
| Estevan | Q1018271 | city | 1892-01-01 | 5949568 | Saskatchewan |
| Westport | Q34184 | village | - | 6179363 | United Counties of Leeds and Grenville |
| Camrose | Q775610 | city | - | 5914653 | Alberta |

---

## Missing GeoNames Coverage

**Communities without GeoNames IDs: 1,964 (67.8%)**

Breakdown by type:
- Hamlets: 1,577 (80.3%)
- Villages: 301 (15.3%)
- Towns: 39 (2.0%)
- Municipalities: 25 (1.3%)
- Metropolitan areas: 13 (0.7%)
- Cities: 5 (0.3%)
- Local municipalities of Quebec: 4 (0.2%)

**Observation**: Smaller settlements (hamlets, villages) have poor GeoNames coverage. These may be:
- Historical places no longer inhabited
- Very small settlements below GeoNames threshold
- Indigenous communities with different naming conventions
- French Canadian settlements with name variants

**Next Steps**:
1. Review `communities_no_geonames.csv` for major missing cities/towns
2. Query GeoNames API directly for missing entities
3. Consider alternative identifiers (OpenStreetMap relation IDs via Wikidata P402)

---

## Matching Strategy (1921 Census → Communities)

### Scoring Algorithm

```python
total_score = (name_similarity * 0.5) +
              (coordinate_proximity * 0.3) +
              (province_match * 0.2)
```

### Thresholds
- **High confidence (≥0.9)**: Exact name match + close coordinates
- **Medium confidence (0.7-0.9)**: Similar name + same province
- **Low confidence (0.6-0.7)**: Manual review required
- **Reject (<0.6)**: No match

### Expected Results for 1921
- **Total CSDs**: 5,363
- **Expected matches**: ~2,000-3,000 (40-60%)
- **High confidence**: ~1,000-1,500 (automated)
- **Medium confidence**: ~500-1,000 (review)
- **Unmatched**: ~2,000-3,000 (rural/small places)

---

## Next Actions

1. **Run 1921 LOD Conversion**
   - Execute `scripts/convert_1921_to_lod.py`
   - Review match statistics
   - Manually validate high-value matches (cities, major towns)

2. **Import to Neo4j**
   - Copy CSV files to Neo4j import directory
   - Create import script for community nodes
   - Create import script for `was_enumerated_as` relationships

3. **Extend to Other Census Years**
   - Use P132_spatiotemporally_overlaps_with to propagate matches
   - If CSD X (1921) matches Community Y, and CSD Z (1911) is SAME_AS CSD X, then CSD Z also matches Community Y
   - Build temporal graph of community-census linkages

4. **Enrich Community Data**
   - Query Wikidata for additional properties (P576 dissolved date, P1082 population, P1448 official names)
   - Add OpenStreetMap relation IDs (P402) for geographic visualization
   - Link to Wikipedia articles via Wikidata

---

## Files Created

### Scripts
- `scripts/fetch_canadian_communities_wikidata.py` (357 lines)
- `scripts/convert_1921_to_lod.py` (336 lines)

### Data Files
- `neo4j_communities/e53_communities.csv` (2,897 communities)
- `neo4j_communities/e42_identifiers.csv` (3,830 identifiers: 2,897 Wikidata + 933 GeoNames)
- `neo4j_communities/p1_community_identifiers.csv` (3,830 relationships)
- `communities_no_geonames.csv` (1,964 communities for review)

### Documentation
- `EXTERNAL_IDENTIFIERS_PLAN.md` (original PID linking strategy)
- `COMMUNITY_LINKING_PROGRESS.md` (this file)

---

## Technical Notes

### Why Not MCP Wikidata Server?

The MCP Wikidata server (`mcp-wikidata`) is configured in Claude Code but tools are not available in CLI sessions. Instead, we:
1. Use direct SPARQL queries to Wikidata endpoint
2. Use `httpx` library for HTTP requests
3. Implement same functionality as MCP tools (search, SPARQL, metadata)

This approach is more portable and works in both CLI and notebook environments.

### Coordinate Handling

Wikidata returns coordinates as WKT `Point(lon lat)` strings:
- Example: `"Point(-75.6919 45.4215)"` = Ottawa (lon, lat)
- Note: WKT uses lon/lat order, not lat/lon
- Converted to separate float fields for Neo4j

### Name Normalization

Place names are normalized for matching:
- Remove commas and parentheticals: `"Ottawa (city)"` → `"Ottawa"`
- Standardize saint abbreviations: `"Saint John"` → `"St. John"`
- Case-insensitive comparison
- Use RapidFuzz for fuzzy string matching

---

**Status**: ✅ Wikidata data ready, ⏳ Awaiting 1921 LOD conversion and Neo4j import
