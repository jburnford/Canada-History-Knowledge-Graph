# Census Division Presences - Neo4j Import Guide

**Generated**: October 1, 2025
**Purpose**: Import CD temporal presence nodes and relationships
**Related**: README_CIDOC_CRM.md (CSD presences)

---

## Overview

This guide covers importing **Census Division (CD) presences** - temporal manifestations of administrative districts that aggregate Census Subdivisions. CD presences enable:

- **Administrative hierarchy queries**: "Show all CSDs within Ottawa CD in 1901"
- **CD temporal evolution**: Track CD boundary changes, splits, mergers (1851-1921)
- **Multi-scale analysis**: Compare CD-level vs CSD-level patterns

---

## Data Model

### Entities

#### E93_Presence (CD)
Temporal manifestation of a Census Division during a specific census year.

**Properties**:
- `presence_id:ID` - Unique identifier (e.g., `CD_ON_Ottawa_1901`)
- `cd_id` - Links to E53_Place (CD)
- `census_year:int` - Census year
- `area_sqm:float` - Total area in square meters
- `num_csds:int` - Number of CSDs within this CD

**Example**:
```
CD_ON_Ottawa_1901, CD_ON_Ottawa, 1901, 5028420158.34, 18
```

#### E94_Space_Primitive (CD)
Geographic centroid for CD presence.

**Properties**:
- `space_id:ID` - Unique identifier (e.g., `CD_ON_Ottawa_1901_SPACE`)
- `latitude:float` - Centroid latitude (WGS84)
- `longitude:float` - Centroid longitude (WGS84)
- `crs` - Coordinate reference system (EPSG:4326)

### Relationships

#### P166_was_a_presence_of
- **Domain**: E93_Presence (CD) → **Range**: E53_Place (CD)
- **Count**: 1,482 relationships (8 years × ~185 CDs/year)
- Links CD presence to abstract CD place

#### P164_is_temporally_specified_by
- **Domain**: E93_Presence (CD) → **Range**: E4_Period
- **Count**: 1,482 relationships
- Specifies which census year

#### P161_has_spatial_projection
- **Domain**: E93_Presence (CD) → **Range**: E94_Space_Primitive
- **Count**: 1,482 relationships
- Links to centroid geometry

#### P132_spatiotemporally_overlaps_with (CD)
- **Domain**: E93_Presence (CD) → **Range**: E93_Presence (CD)
- **Count**: 1,302 relationships
- **Properties**: `overlap_type`, `iou`, `from_fraction`, `to_fraction`, `year_from`, `year_to`
- Tracks CD evolution across adjacent census years

#### P10_falls_within
- **Domain**: E93_Presence (CSD) → **Range**: E93_Presence (CD)
- **Count**: 21,047 relationships
- **Property**: `during_period` (E4_Period ID)
- Links CSD presences to their parent CD presence in specific year

---

## File Structure

### Node Files (8 years each)
```
e93_presence_cd_1851.csv           91 CD presences
e93_presence_cd_1861.csv          121 CD presences
e93_presence_cd_1871.csv          213 CD presences
e93_presence_cd_1881.csv          197 CD presences
e93_presence_cd_1891.csv          209 CD presences
e93_presence_cd_1901.csv          214 CD presences
e93_presence_cd_1911.csv          222 CD presences
e93_presence_cd_1921.csv          223 CD presences

e94_space_primitive_cd_YYYY.csv   (same counts as above)
```

### Relationship Files
```
p166_was_presence_of_cd_YYYY.csv           1,482 relationships (8 files)
p164_temporally_specified_by_cd_YYYY.csv   1,482 relationships (8 files)
p161_spatial_projection_cd_YYYY.csv        1,482 relationships (8 files)
p132_spatiotemporally_overlaps_with_cd.csv 1,302 relationships (1 file)
p10_csd_within_cd_presence_YYYY.csv       21,047 relationships (8 files)
```

---

## Neo4j Import Commands

### Step 1: Import CD Presence Nodes

```cypher
// Import E93_Presence (CD) nodes for all years
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///e93_presence_cd_' + year + '.csv' AS row
  CREATE (:E93_Presence {
    presence_id: row.`presence_id:ID`,
    cd_id: row.cd_id,
    census_year: toInteger(row.`census_year:int`),
    area_sqm: toFloat(row.`area_sqm:float`),
    num_csds: toInteger(row.`num_csds:int`)
  })
} IN TRANSACTIONS OF 100 ROWS;
```

### Step 2: Import CD Space Primitives

```cypher
// Import E94_Space_Primitive (CD) nodes for all years
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///e94_space_primitive_cd_' + year + '.csv' AS row
  CREATE (:E94_Space_Primitive {
    space_id: row.`space_id:ID`,
    latitude: toFloat(row.`latitude:float`),
    longitude: toFloat(row.`longitude:float`),
    crs: row.crs,
    point: point({latitude: toFloat(row.`latitude:float`), longitude: toFloat(row.`longitude:float`)})
  })
} IN TRANSACTIONS OF 100 ROWS;
```

### Step 3: Import CD Relationships

```cypher
// Import P166_was_a_presence_of (CD presence → CD place)
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///p166_was_presence_of_cd_' + year + '.csv' AS row
  MATCH (presence:E93_Presence {presence_id: row.`:START_ID`})
  MATCH (place:E53_Place {place_id: row.`:END_ID`})
  CREATE (presence)-[:P166_was_a_presence_of]->(place)
} IN TRANSACTIONS OF 100 ROWS;

// Import P164_is_temporally_specified_by
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///p164_temporally_specified_by_cd_' + year + '.csv' AS row
  MATCH (presence:E93_Presence {presence_id: row.`:START_ID`})
  MATCH (period:E4_Period {period_id: row.`:END_ID`})
  CREATE (presence)-[:P164_is_temporally_specified_by]->(period)
} IN TRANSACTIONS OF 100 ROWS;

// Import P161_has_spatial_projection
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///p161_spatial_projection_cd_' + year + '.csv' AS row
  MATCH (presence:E93_Presence {presence_id: row.`:START_ID`})
  MATCH (space:E94_Space_Primitive {space_id: row.`:END_ID`})
  CREATE (presence)-[:P161_has_spatial_projection]->(space)
} IN TRANSACTIONS OF 100 ROWS;
```

### Step 4: Import CD Temporal Overlap Links

```cypher
// Import P132_spatiotemporally_overlaps_with (CD evolution)
LOAD CSV WITH HEADERS FROM 'file:///p132_spatiotemporally_overlaps_with_cd.csv' AS row
MATCH (p1:E93_Presence {presence_id: row.`:START_ID`})
MATCH (p2:E93_Presence {presence_id: row.`:END_ID`})
CREATE (p1)-[:P132_spatiotemporally_overlaps_with {
  overlap_type: row.overlap_type,
  iou: toFloat(row.`iou:float`),
  from_fraction: toFloat(row.`from_fraction:float`),
  to_fraction: toFloat(row.`to_fraction:float`),
  year_from: toInteger(row.`year_from:int`),
  year_to: toInteger(row.`year_to:int`)
}]->(p2);
```

### Step 5: Import CSD→CD Administrative Hierarchy

```cypher
// Import P10_falls_within (CSD presence → CD presence)
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///p10_csd_within_cd_presence_' + year + '.csv' AS row
  MATCH (csd_presence:E93_Presence {presence_id: row.`:START_ID`})
  MATCH (cd_presence:E93_Presence {presence_id: row.`:END_ID`})
  CREATE (csd_presence)-[:P10_falls_within {
    during_period: row.during_period
  }]->(cd_presence)
} IN TRANSACTIONS OF 1000 ROWS;
```

---

## Sample Queries

### Query 1: Find all CSDs within a CD in 1901

```cypher
MATCH (cd_place:E53_Place {name: 'Ottawa', place_type: 'CD'})<-[:P166_was_a_presence_of]-(cd_presence:E93_Presence)
MATCH (cd_presence)-[:P164_is_temporally_specified_by]->(period:E4_Period {year: 1901})
MATCH (csd_presence:E93_Presence)-[:P10_falls_within]->(cd_presence)
MATCH (csd_presence)-[:P166_was_a_presence_of]->(csd_place:E53_Place)
RETURN csd_place.name, csd_presence.area_sqm
ORDER BY csd_place.name;
```

### Query 2: Track CD evolution across years

```cypher
// Find CD temporal continuity for Saskatchewan formation (1905)
MATCH path = (p1905:E93_Presence)-[:P132_spatiotemporally_overlaps_with*1..3]->(p1921:E93_Presence)
WHERE p1905.cd_id CONTAINS 'SK_' AND p1905.census_year = 1905
  AND p1921.census_year = 1921
RETURN path
LIMIT 10;
```

### Query 3: Compare CD sizes over time

```cypher
MATCH (cd:E53_Place {place_type: 'CD'})<-[:P166_was_a_presence_of]-(presence:E93_Presence)
WHERE cd.province = 'ON'
WITH cd.name AS cd_name,
     collect({year: presence.census_year, area: presence.area_sqm, num_csds: presence.num_csds}) AS timeline
WHERE size(timeline) = 8  // CDs present in all 8 census years
RETURN cd_name, timeline
ORDER BY cd_name;
```

### Query 4: CD boundary changes

```cypher
// Find CDs with significant boundary changes (IoU < 0.95)
MATCH (p1:E93_Presence)-[r:P132_spatiotemporally_overlaps_with]->(p2:E93_Presence)
WHERE r.overlap_type = 'SAME_AS' AND r.iou < 0.95
MATCH (p1)-[:P166_was_a_presence_of]->(cd:E53_Place)
RETURN cd.name, cd.province, p1.census_year, p2.census_year, r.iou
ORDER BY r.iou ASC
LIMIT 20;
```

### Query 5: Western expansion analysis

```cypher
// Track Alberta/Saskatchewan CD formation (1905)
MATCH (p1901:E93_Presence)-[r:P132_spatiotemporally_overlaps_with]->(p1911:E93_Presence)
WHERE p1901.cd_id CONTAINS 'NT_' AND (p1911.cd_id CONTAINS 'AB_' OR p1911.cd_id CONTAINS 'SK_')
MATCH (p1901)-[:P166_was_a_presence_of]->(cd1901:E53_Place)
MATCH (p1911)-[:P166_was_a_presence_of]->(cd1911:E53_Place)
RETURN cd1901.name AS from_cd, cd1911.name AS to_cd,
       r.overlap_type, r.iou, r.from_fraction, r.to_fraction;
```

---

## Data Statistics

### CD Presences by Year
| Year | CD Presences | Avg Area (km²) | Avg CSDs per CD |
|------|--------------|----------------|-----------------|
| 1851 | 91           | ~8,800         | 10              |
| 1861 | 121          | ~8,300         | 10              |
| 1871 | 213          | ~11,750        | 9               |
| 1881 | 197          | ~15,200        | 11              |
| 1891 | 209          | ~19,200        | 12              |
| 1901 | 214          | ~32,700        | 15              |
| 1911 | 222          | ~38,500        | 17              |
| 1921 | 223          | ~40,400        | 24              |

### CD Temporal Evolution (P132 links)
- **SAME_AS**: 643 (stable CDs across years)
- **CONTAINS**: 370 (CD subdivisions)
- **WITHIN**: 289 (CD mergers/absorptions)
- **Total**: 1,302 high-confidence relationships

### Administrative Hierarchy (P10 links)
- **Total**: 21,047 CSD→CD links
- **Coverage**: Every CSD presence links to exactly one CD presence
- **Enables**: Multi-scale temporal queries

---

## Integration with CSD Presences

CD presences complement CSD presences in the same database:

```cypher
// Multi-scale population aggregation
MATCH (cd_presence:E93_Presence {cd_id: 'CD_ON_Ottawa', census_year: 1901})
MATCH (csd_presence:E93_Presence)-[:P10_falls_within]->(cd_presence)
MATCH (m:E16_Measurement)-[:P39_measured]->(csd_presence)
MATCH (m)-[:P2_has_type]->(:E55_Type {type_id: 'VAR_POP_TOTAL'})
MATCH (m)-[:P40_observed_dimension]->(dim:E54_Dimension)
RETURN cd_presence.cd_id, sum(dim.value) AS total_population;
```

---

## Generation Script

**Script**: `scripts/build_cd_presences.py`

**Usage**:
```bash
conda activate geo
python scripts/build_cd_presences.py \
  --gdb TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306.gdb \
  --years 1851,1861,1871,1881,1891,1901,1911,1921 \
  --cd-links cd_links_output \
  --out neo4j_cidoc_crm
```

**Processing Time**: ~10-15 minutes
**Total Output**: 49 CSV files (1.4 MB)

---

## Notes

- **CD geometries**: Aggregated from CSDs via spatial dissolve
- **Centroids**: Calculated from dissolved polygons (may differ from published centroids)
- **Invalid geometries**: Fixed using `buffer(0)` or `make_valid()` for 1911/1921
- **P10 relationships**: Enable hierarchical queries without joining on static E53 places

---

**See also**:
- `README_CIDOC_CRM.md` - CSD presence import
- `cd_links_output/SUMMARY_CD_LINKS.md` - CD temporal analysis
- `POST_MERGE_IMPROVEMENTS.md` - Implementation plan
