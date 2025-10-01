# P134_continued Temporal Relationships - Import Guide

**Created**: September 30, 2025
**Status**: Ready for Neo4j import

## Overview

P134_continued relationships track temporal continuity between places across census years. These relationships enable:
- Tracking CSD/CD evolution from 1851 to 1921
- Identifying boundary changes and administrative reorganizations
- Querying historical continuity paths
- Understanding place transformations over time

## Files Generated

### 1. CSD Temporal Links
**File**: `p134_continued_csd.csv`
- **Relationships**: 17,060
- **Pattern**: E93_Presence → E93_Presence
- **Links**: CSD presences across adjacent census years

### 2. CD Temporal Links
**File**: `p134_continued_cd.csv`
- **Relationships**: 1,302
- **Pattern**: E53_Place (CD) → E53_Place (CD)
- **Links**: Census Divisions across adjacent census years

**Total P134_continued relationships**: 18,362

## Relationship Types

### SAME_AS (9,423 total)
- **Meaning**: Place remains largely unchanged between census years
- **Criteria**: IoU (intersection over union) > 0.98
- **Example**: Westmeath CSD in 1901 → Westmeath CSD in 1911 (same boundaries)
- **CSD**: 8,780 relationships
- **CD**: 643 relationships

### CONTAINS (6,985 total)
- **Meaning**: Earlier place was subdivided into smaller units
- **Criteria**: to_fraction > 0.95 (later place mostly contained in earlier)
- **Example**: Large township in 1881 → Multiple villages in 1891
- **CSD**: 6,615 relationships
- **CD**: 370 relationships

### WITHIN (1,954 total)
- **Meaning**: Earlier place was absorbed into larger unit
- **Criteria**: from_fraction > 0.95 (earlier place mostly within later)
- **Example**: Small district in 1871 → Merged into county in 1881
- **CSD**: 1,665 relationships
- **CD**: 289 relationships

## CSV Format

### Column Schema

```csv
:START_ID,:END_ID,relationship_type,iou:float,from_fraction:float,to_fraction:float,year_from:int,year_to:int,:TYPE
```

### Column Descriptions

- **:START_ID**: Source presence/place ID
  - CSD: `{TCPUID}_{year}` (e.g., `ON039029_1901`) - E93_Presence ID
  - CD: `CD_{province}_{name}` (e.g., `CD_ON_Renfrew`) - E53_Place ID

- **:END_ID**: Target presence/place ID (format same as START_ID)

- **relationship_type**: SAME_AS | CONTAINS | WITHIN

- **iou:float**: Intersection over union (0.0 to 1.0)
  - Measures overall spatial overlap
  - 1.0 = perfect overlap, 0.0 = no overlap

- **from_fraction:float**: Fraction of source contained in target (0.0 to 1.0)
  - How much of the earlier place is in the later place

- **to_fraction:float**: Fraction of target contained in source (0.0 to 1.0)
  - How much of the later place was in the earlier place

- **year_from:int**: Source census year (1851-1911)

- **year_to:int**: Target census year (1861-1921)

- **:TYPE**: Always `P134_continued`

### Example Rows

**SAME_AS** (stable boundary):
```csv
ON002001_1851,ON065002_1861,SAME_AS,1.0,1.0,1.0,1851,1861,P134_continued
```
Brantford CSD remained unchanged from 1851 to 1861

**CONTAINS** (subdivision):
```csv
CD_NT_The_Territories_1851,CD_ON_Nipissing_1861,CONTAINS,0.0065,0.0065,1.0,1851,1861,P134_continued
```
Northwest Territories was subdivided, Nipissing became a new CD

**WITHIN** (merger):
```csv
BC004001_1891,BC004001_1901,WITHIN,0.7794,0.9931,0.7837,1891,1901,P134_continued
```
Victoria ward was largely absorbed into larger jurisdiction

## Neo4j Import Instructions

### Step 1: Create Constraints (if not already created)

```cypher
// E93_Presence constraint
CREATE CONSTRAINT e93_id IF NOT EXISTS
  FOR (n:E93_Presence) REQUIRE n.presence_id IS UNIQUE;

// E53_Place constraint
CREATE CONSTRAINT e53_id IF NOT EXISTS
  FOR (n:E53_Place) REQUIRE n.place_id IS UNIQUE;
```

### Step 2: Import CSD P134_continued

```cypher
// CSD temporal continuity (E93_Presence → E93_Presence)
:auto USING PERIODIC COMMIT 5000
LOAD CSV WITH HEADERS FROM 'file:///neo4j_cidoc_crm/p134_continued_csd.csv' AS row
MATCH (from:E93_Presence {presence_id: row.`:START_ID`})
MATCH (to:E93_Presence {presence_id: row.`:END_ID`})
CREATE (from)-[:P134_continued {
  relationship_type: row.relationship_type,
  iou: toFloat(row.`iou:float`),
  from_fraction: toFloat(row.`from_fraction:float`),
  to_fraction: toFloat(row.`to_fraction:float`),
  year_from: toInteger(row.`year_from:int`),
  year_to: toInteger(row.`year_to:int`)
}]->(to);
```

### Step 3: Import CD P134_continued

```cypher
// CD temporal continuity (E53_Place → E53_Place)
:auto USING PERIODIC COMMIT 500
LOAD CSV WITH HEADERS FROM 'file:///neo4j_cidoc_crm/p134_continued_cd.csv' AS row
MATCH (from:E53_Place {place_id: row.`:START_ID`})
MATCH (to:E53_Place {place_id: row.`:END_ID`})
CREATE (from)-[:P134_continued {
  relationship_type: row.relationship_type,
  iou: toFloat(row.`iou:float`),
  from_fraction: toFloat(row.`from_fraction:float`),
  to_fraction: toFloat(row.`to_fraction:float`),
  year_from: toInteger(row.`year_from:int`),
  year_to: toInteger(row.`year_to:int`)
}]->(to);
```

## Validation Queries

### Count P134 relationships

```cypher
MATCH ()-[r:P134_continued]->()
RETURN count(r) AS total_p134_relationships;
// Expected: 18,362
```

### Count by relationship type

```cypher
MATCH ()-[r:P134_continued]->()
RETURN r.relationship_type AS type, count(*) AS count
ORDER BY count DESC;
// Expected: SAME_AS ~9,423, CONTAINS ~6,985, WITHIN ~1,954
```

### Verify CSD continuity

```cypher
MATCH (p1:E93_Presence)-[r:P134_continued]->(p2:E93_Presence)
RETURN count(*) AS csd_p134_count;
// Expected: 17,060
```

### Verify CD continuity

```cypher
MATCH (p1:E53_Place)-[r:P134_continued]->(p2:E53_Place)
WHERE p1.place_type = 'CD' AND p2.place_type = 'CD'
RETURN count(*) AS cd_p134_count;
// Expected: 1,302
```

## Sample Research Queries

### 1. Trace CSD evolution across all years

```cypher
// Find all CSDs that have continuous records from 1851 to 1921
MATCH path = (start:E93_Presence {census_year: 1851})-[:P134_continued*7]->(end:E93_Presence {census_year: 1921})
WHERE ALL(r IN relationships(path) WHERE r.relationship_type = 'SAME_AS')
RETURN start.csd_tcpuid AS tcpuid,
       start.presence_id AS start_presence,
       end.presence_id AS end_presence,
       length(path) AS continuity_links;
```

### 2. Find CSDs that underwent subdivision

```cypher
// Find CSDs that were subdivided (CONTAINS relationship)
MATCH (earlier:E93_Presence)-[r:P134_continued {relationship_type: 'CONTAINS'}]->(later:E93_Presence)
MATCH (earlier)-[:P7_took_place_at]->(place:E53_Place)
RETURN place.name AS csd_name,
       r.year_from AS subdivision_from_year,
       r.year_to AS subdivision_to_year,
       r.to_fraction AS fraction_retained
ORDER BY r.year_from;
```

### 3. Track CD boundary changes

```cypher
// Find CDs with significant boundary changes (IoU < 0.9)
MATCH (cd1:E53_Place)-[r:P134_continued]->(cd2:E53_Place)
WHERE cd1.place_type = 'CD' AND r.iou < 0.9
RETURN cd1.name AS earlier_cd,
       cd2.name AS later_cd,
       r.year_from AS from_year,
       r.year_to AS to_year,
       r.iou AS overlap_ratio,
       r.relationship_type AS change_type
ORDER BY r.iou;
```

### 4. Find places that merged

```cypher
// Find CSDs that were absorbed into larger units (WITHIN)
MATCH (smaller:E93_Presence)-[r:P134_continued {relationship_type: 'WITHIN'}]->(larger:E93_Presence)
MATCH (smaller)-[:P7_took_place_at]->(place_small:E53_Place)
MATCH (larger)-[:P7_took_place_at]->(place_large:E53_Place)
RETURN place_small.name AS absorbed_csd,
       place_large.name AS absorbing_csd,
       r.year_from AS merger_from,
       r.year_to AS merger_to,
       r.from_fraction AS fraction_absorbed
ORDER BY r.year_to;
```

### 5. Alberta/Saskatchewan provincial formation (1905)

```cypher
// Track CD reorganization during Alberta/Saskatchewan formation
MATCH (cd1:E53_Place)-[r:P134_continued]->(cd2:E53_Place)
WHERE r.year_from = 1901 AND r.year_to = 1911
  AND (cd1.province IN ['NT', 'AB', 'SK'] OR cd2.province IN ['AB', 'SK'])
RETURN cd1.name AS earlier_cd,
       cd1.province AS earlier_province,
       cd2.name AS later_cd,
       cd2.province AS later_province,
       r.relationship_type AS change_type,
       r.iou AS overlap
ORDER BY cd1.province, cd1.name;
```

## Data Quality Notes

### High-Confidence Links Only
- Only SAME_AS, CONTAINS, and WITHIN relationships are included
- OVERLAPS relationships (complex cases) are excluded from P134
- See `year_links_output/ambiguous_*.csv` for excluded complex cases
- See `cd_links_output/cd_ambiguous_*.csv` for CD complex cases

### Spatial Overlap Thresholds
- **SAME_AS**: IoU > 0.98 (98% overlap)
- **CONTAINS**: to_fraction > 0.95 (later place 95% within earlier)
- **WITHIN**: from_fraction > 0.95 (earlier place 95% within later)

### Known Complex Cases
- **1901 → 1911**: Highest ambiguity due to Alberta/Saskatchewan formation
  - Many CDs reorganized with OVERLAPS relationships
  - Provincial boundaries redrawn
  - Division numbering systems introduced
- **Western provinces**: More P134 gaps due to rapid reorganization
- **Eastern provinces**: More complete P134 chains (stable boundaries)

## Integration with Census Observations

P134_continued relationships can be combined with census observations (E16_Measurement) to track demographic changes:

```cypher
// Track population change for a continuously existing CSD
MATCH path = (p1851:E93_Presence {census_year: 1851})-[:P134_continued*]->(p1921:E93_Presence {census_year: 1921})
WHERE ALL(r IN relationships(path) WHERE r.relationship_type = 'SAME_AS')
MATCH (m1851:E16_Measurement)-[:P39_measured]->(p1851)
MATCH (m1851)-[:P2_has_type]->(:E55_Type {type_id: 'VAR_POP_TOTAL'})
MATCH (m1851)-[:P40_observed_dimension]->(d1851:E54_Dimension)
MATCH (m1921:E16_Measurement)-[:P39_measured]->(p1921)
MATCH (m1921)-[:P2_has_type]->(:E55_Type {type_id: 'VAR_POP_TOTAL'})
MATCH (m1921)-[:P40_observed_dimension]->(d1921:E54_Dimension)
MATCH (p1851)-[:P7_took_place_at]->(place:E53_Place)
RETURN place.name AS csd_name,
       d1851.value AS pop_1851,
       d1921.value AS pop_1921,
       (d1921.value - d1851.value) AS population_change,
       ((d1921.value - d1851.value) / d1851.value * 100) AS percent_change
ORDER BY percent_change DESC;
```

## Performance Considerations

- **Index on E93_Presence.presence_id**: Critical for P134 traversal
- **Index on E53_Place.place_id**: Critical for CD P134 traversal
- **Path queries**: Use `[:P134_continued*1..7]` to limit path length (max 7 census intervals)
- **Periodic commit**: Use for large imports (PERIODIC COMMIT 5000)

## Next Steps

1. Import P134_continued relationships (use Cypher above)
2. Validate counts match expected totals
3. Run sample queries to verify temporal paths
4. Explore census observation integration
5. Document notable cases (Alberta/Saskatchewan formation, etc.)

## References

- CIDOC-CRM P134: http://www.cidoc-crm.org/Property/p134-continued/version-7.1.1
- Source data: `year_links_output/year_links_*.csv` (CSDs)
- Source data: `cd_links_output/cd_links_*.csv` (CDs)
- Generation script: `scripts/build_p134_continued.py`
