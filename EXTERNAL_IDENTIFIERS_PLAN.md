# External Identifier Matching Plan

**Date**: October 1, 2025 (Updated)
**Goal**: Link real-world Canadian communities to Wikidata and GeoNames PIDs, then connect to census geography

**Status**: ✅ Wikidata communities fetched (2,897 entities), ⏳ Linking to 1921 census in progress

---

## Strategy Revision (October 1, 2025)

**Original Plan**: Link PIDs directly to census CSDs/CDs
**Revised Plan**: Create community entities with PIDs, then link communities to census presences

**Rationale**:
- Census geography (CSDs/CDs) changes over time (boundaries, mergers, splits)
- Real communities have continuous identity across census years
- Example: "City of Ottawa" (Wikidata Q1930) was enumerated in multiple CSDs across different years
- This approach mirrors how historians think about places

See **COMMUNITY_LINKING_PROGRESS.md** for current implementation status.

---

## Overview

Add Linked Open Data identifiers to make the census knowledge graph interoperable with external data sources. This will enable federated queries, enrichment from external sources, and broader discoverability.

## Target Identifier Systems

### 1. Wikidata
- **Coverage**: ~100M entities with PIDs (Q-numbers)
- **API**: SPARQL endpoint (query.wikidata.org)
- **Relevant Properties**:
  - P31: instance of (Q3788231 = census subdivision)
  - P131: located in administrative territorial entity
  - P17: country (Q16 = Canada)
  - P625: coordinate location
  - P1566: GeoNames ID (cross-reference!)
  - P402: OpenStreetMap relation ID

### 2. GeoNames
- **Coverage**: 11M place names worldwide
- **API**: REST API (geonames.org/export)
- **Structure**:
  - ADM1: Provinces/territories (13 in Canada)
  - ADM2: Census divisions (~300)
  - ADM3: Census subdivisions (~5,000)
- **Free tier**: 20,000 requests/day

### 3. Canadian Geographical Names Data Base (CGNDB)
- **Coverage**: 500,000+ Canadian place names
- **API**: Natural Resources Canada GeoNames Service
- **Authority**: Official Canadian government source

---

## CIDOC-CRM Data Model

### New Entity: E42_Identifier

```
E42_Identifier
  - identifier_id (PK): "IDENT_WIKIDATA_Q123456"
  - identifier_value: "Q123456"
  - identifier_type: "WIKIDATA" | "GEONAMES" | "CGNDB"
  - uri: "https://www.wikidata.org/entity/Q123456"
  - label: "Wikidata ID for Ottawa"
  - retrieved_date: "2025-10-01"
  - confidence: 0.95 (float, 0-1)
```

### New Relationship: P1_is_identified_by (extended)

```
(E53_Place)-[:P1_is_identified_by]->(E42_Identifier)
  - match_method: "name_exact" | "name_fuzzy" | "coordinates" | "manual"
  - match_score: 0.95 (float, 0-1)
  - verified: true | false
  - verified_by: "user_id" or "script_name"
  - notes: "Matched via exact name + province"
```

---

## Matching Strategy

### Phase 1: Modern Places (2021 Census)
Start with places that exist in 2021 census - highest chance of Wikidata/GeoNames coverage.

**Approach**:
1. Extract unique place names from 1921 (most recent year with data)
2. Query Wikidata SPARQL for Canadian CSDs
3. Match on: name + province + coordinates (fuzzy)
4. Generate E42 nodes for high-confidence matches (>0.8)

### Phase 2: Historical Places (1851-1911)
Places that no longer exist or were renamed.

**Approach**:
1. Use E41_Appellation canonical names
2. Check Wikidata for historical administrative divisions
3. Use GeoNames "historical" feature type
4. Manual review for ambiguous cases

### Phase 3: Cross-Validation
Use GeoNames ↔ Wikidata cross-references to validate matches.

**Approach**:
1. Wikidata has P1566 property linking to GeoNames IDs
2. If we match to Wikidata, extract GeoNames ID
3. If we match to GeoNames, query Wikidata for that GeoNames ID
4. High confidence when both agree

---

## Matching Algorithm

### Score Calculation

```python
def calculate_match_score(census_place, external_place):
    score = 0.0
    weights = {
        'name_exact': 0.4,
        'name_fuzzy': 0.25,
        'province_match': 0.15,
        'coordinate_distance': 0.20
    }

    # Name matching
    if census_place.name.lower() == external_place.name.lower():
        score += weights['name_exact']
    else:
        similarity = fuzzy_match(census_place.name, external_place.name)
        score += weights['name_fuzzy'] * similarity

    # Province matching
    if census_place.province == external_place.province:
        score += weights['province_match']

    # Coordinate proximity (within 10km)
    distance_km = haversine(census_place.coords, external_place.coords)
    if distance_km < 10:
        coord_score = 1.0 - (distance_km / 10.0)
        score += weights['coordinate_distance'] * coord_score

    return score
```

### Confidence Thresholds

- **0.95-1.0**: Automatic accept (exact name + province + close coords)
- **0.80-0.94**: High confidence (review recommended)
- **0.60-0.79**: Medium confidence (manual review required)
- **<0.60**: Reject (no match)

---

## Implementation Plan

### Step 1: Build Wikidata Matcher
```python
scripts/match_wikidata_ids.py
  - Query Wikidata SPARQL for Canadian CSDs
  - Match against E53_Place nodes
  - Generate e42_identifiers_wikidata.csv
  - Generate p1_is_identified_by_wikidata.csv
```

### Step 2: Build GeoNames Matcher
```python
scripts/match_geonames_ids.py
  - Query GeoNames API for ADM3 (CSDs) in Canada
  - Match against E53_Place nodes
  - Generate e42_identifiers_geonames.csv
  - Generate p1_is_identified_by_geonames.csv
```

### Step 3: Cross-Validate
```python
scripts/validate_identifiers.py
  - Compare Wikidata P1566 (GeoNames ID) with our GeoNames matches
  - Flag discrepancies for review
  - Generate validation_report.csv
```

### Step 4: Import to Neo4j
```cypher
// Import E42_Identifier nodes
LOAD CSV WITH HEADERS FROM 'file:///e42_identifiers_all.csv' AS row
CREATE (:E42_Identifier {
  identifier_id: row.`identifier_id:ID`,
  identifier_value: row.identifier_value,
  identifier_type: row.identifier_type,
  uri: row.uri,
  label: row.label,
  retrieved_date: row.retrieved_date,
  confidence: toFloat(row.`confidence:float`)
});

// Import P1_is_identified_by relationships
LOAD CSV WITH HEADERS FROM 'file:///p1_external_identifiers.csv' AS row
MATCH (place:E53_Place {place_id: row.`:START_ID`})
MATCH (ident:E42_Identifier {identifier_id: row.`:END_ID`})
CREATE (place)-[:P1_is_identified_by {
  match_method: row.match_method,
  match_score: toFloat(row.`match_score:float`),
  verified: toBoolean(row.verified)
}]->(ident);
```

---

## Expected Results

### Coverage Estimates

| Place Type | Total | Wikidata Match | GeoNames Match | Cross-Validated |
|------------|-------|----------------|----------------|-----------------|
| **Modern CSDs (1921)** | ~3,800 | ~2,500 (65%) | ~3,000 (80%) | ~2,200 (58%) |
| **Modern CDs (1921)** | ~200 | ~180 (90%) | ~190 (95%) | ~175 (88%) |
| **Historical CSDs** | ~9,300 | ~3,000 (32%) | ~4,000 (43%) | ~2,500 (27%) |
| **Total** | ~13,700 | ~5,680 (41%) | ~7,190 (52%) | ~4,875 (36%) |

### Value Proposition

Once implemented, we can:
1. **Enrich data**: Pull additional metadata from Wikidata (population estimates, Wikipedia links, etc.)
2. **Federated queries**: Join census data with external datasets via SPARQL
3. **Visualization**: Display places on interactive maps using GeoNames coordinates
4. **Discovery**: Make our data discoverable via Wikidata/GeoNames searches
5. **Validation**: Use external sources to validate our historical place names

---

## Example Query (After Implementation)

```cypher
// Find census places with Wikidata IDs and retrieve Wikipedia links
MATCH (place:E53_Place {place_type: 'CSD'})-[:P1_is_identified_by]->(wid:E42_Identifier {identifier_type: 'WIKIDATA'})
MATCH (place)<-[:P166_was_a_presence_of]-(presence:E93_Presence {census_year: 1901})
MATCH (m:E16_Measurement)-[:P39_measured]->(presence)
MATCH (m)-[:P2_has_type]->(vtype:E55_Type {variable_name: 'POP_XX_N'})
MATCH (m)-[:P40_observed_dimension]->(dim:E54_Dimension)
WHERE place.province = 'ON'
RETURN place.name, dim.value AS population,
       wid.uri AS wikidata_url,
       'https://en.wikipedia.org/wiki/' + split(wid.uri, '/')[4] AS wikipedia_url
ORDER BY population DESC
LIMIT 10;
```

---

## Next Steps

1. ✅ Research Wikidata/GeoNames APIs
2. ⏳ Design CIDOC-CRM model for identifiers (this document)
3. ⏳ Build Wikidata matcher script
4. ⏳ Build GeoNames matcher script
5. ⏳ Generate identifier CSV files
6. ⏳ Import to Neo4j
7. ⏳ Validate and document results
