# Canadian Census CIDOC-CRM Knowledge Graph Data

**Generated**: September 30, 2025
**CIDOC-CRM Version**: 7.1.x compatible
**Coverage**: Canadian Census 1851-1921 (8 census years)

## Overview

This directory contains CSV files ready for Neo4j import using the CIDOC-CRM (Conceptual Reference Model) ontology for cultural heritage data. The model captures Canadian census subdivisions as places with temporal manifestations, spatial projections, and administrative relationships.

## CIDOC-CRM Model

### Entity Types (Nodes)

#### E53_Place - Physical/Administrative Places
- **CSD Places**: 13,135 unique Census Subdivisions across all years
- **CD Places**: 579 unique Census Divisions (parent administrative units)
- **Properties**: place_id, place_type (CSD/CD), name, province

#### E4_Period - Temporal Periods
- **8 Census Periods**: 1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921
- **Properties**: period_id, year, label

#### E93_Presence - Place Manifestations
- **21,047 temporal manifestations**: CSDs during specific census years
- **Properties**: presence_id, csd_tcpuid, census_year, area_sqm
- Represents "Westmeath CSD as it existed in 1901"

#### E94_Space_Primitive - Spatial Coordinates
- **21,047 centroid points**: One per CSD presence
- **Properties**: space_id, latitude, longitude, crs (EPSG:4326 - WGS84)
- Neo4j Community Edition compatible point geometry

### Relationship Types (Edges)

#### P166_was_a_presence_of
- **Source**: E93_Presence → **Target**: E53_Place (CSD)
- **Count**: 21,047 relationships
- Connects the presence to the enduring place it realises (CIDOC-CRM domain: E93, range: E77/E53)

#### P164_is_temporally_specified_by
- **Source**: E93_Presence → **Target**: E4_Period
- **Count**: 21,047 relationships
- Specifies when the presence occurred (which census year)

#### P161_has_spatial_projection
- **Source**: E93_Presence → **Target**: E94_Space_Primitive
- **Count**: 21,047 relationships
- Links presence to geographic coordinates (centroid)

#### P89_falls_within
- **Source**: E53_Place (CSD) → **Target**: E53_Place (CD)
- **Count**: 21,046 relationships
- Administrative hierarchy: CSD within Census Division

#### P122_borders_with
- **Source**: E53_Place (CSD) → **Target**: E53_Place (CSD)
- **Count**: 45,598 relationships
- **Properties**: during_period (E4_Period ID), shared_border_length_m
- Spatial adjacency between CSDs within same census year

#### P132_spatiotemporally_overlaps_with
- **Source**: E93_Presence → **Target**: E93_Presence
- **Count**: 17,060 relationships
- **Properties**: overlap_type (SAME_AS/CONTAINS/WITHIN), iou, from_fraction, to_fraction, year_from, year_to
- Captures spatiotemporal overlap of CSD presences across adjacent census years
- CD-level temporal continuity requires modelling E92/E93 nodes for CDs and is therefore not included in this CIDOC-compliant export

## File Structure

### Node Files

```
e53_place_csd.csv           13,135 CSD places
e53_place_cd.csv              579 CD places
e4_period.csv                   8 census periods
e93_presence_YYYY.csv      21,047 presences (by year)
e94_space_primitive_YYYY.csv 21,047 centroids (by year)
```

### Relationship Files

```
p166_was_presence_of_YYYY.csv        21,047 relationships
p164_temporally_specified_by_YYYY.csv 21,047 relationships
p161_spatial_projection_YYYY.csv      21,047 relationships
p89_falls_within_YYYY.csv             21,046 relationships
p122_borders_with_YYYY.csv            45,598 relationships
p132_spatiotemporally_overlaps_with_csd.csv 17,060 relationships
```

## CSV Format

All files use Neo4j LOAD CSV format with header annotations:

- `:ID` - Node identifier (unique within node type)
- `:LABEL` - Node label (CIDOC-CRM class)
- `:START_ID` - Relationship source node
- `:END_ID` - Relationship target node
- `:TYPE` - Relationship type (CIDOC-CRM property)
- `field:int` - Integer type annotation
- `field:float` - Float type annotation

## Neo4j Import Script

```cypher
// Create constraints
CREATE CONSTRAINT e53_place_id IF NOT EXISTS FOR (p:E53_Place) REQUIRE p.`place_id:ID` IS UNIQUE;
CREATE CONSTRAINT e4_period_id IF NOT EXISTS FOR (p:E4_Period) REQUIRE p.`period_id:ID` IS UNIQUE;
CREATE CONSTRAINT e93_presence_id IF NOT EXISTS FOR (p:E93_Presence) REQUIRE p.`presence_id:ID` IS UNIQUE;
CREATE CONSTRAINT e94_space_id IF NOT EXISTS FOR (s:E94_Space_Primitive) REQUIRE s.`space_id:ID` IS UNIQUE;

// Import E53_Place nodes (CSDs)
LOAD CSV WITH HEADERS FROM 'file:///e53_place_csd.csv' AS row
CREATE (:E53_Place {
  place_id: row.`place_id:ID`,
  place_type: row.place_type
});

// Import E53_Place nodes (CDs)
LOAD CSV WITH HEADERS FROM 'file:///e53_place_cd.csv' AS row
CREATE (:E53_Place {
  place_id: row.`place_id:ID`,
  place_type: row.place_type,
  name: row.name,
  province: row.province
});

// Import E4_Period nodes
LOAD CSV WITH HEADERS FROM 'file:///e4_period.csv' AS row
CREATE (:E4_Period {
  period_id: row.`period_id:ID`,
  year: toInteger(row.`year:int`),
  label: row.label
});

// Import E93_Presence nodes (repeat for each year)
LOAD CSV WITH HEADERS FROM 'file:///e93_presence_1851.csv' AS row
CREATE (:E93_Presence {
  presence_id: row.`presence_id:ID`,
  csd_tcpuid: row.csd_tcpuid,
  census_year: toInteger(row.`census_year:int`),
  area_sqm: toFloat(row.`area_sqm:float`)
});

// Import E94_Space_Primitive nodes (repeat for each year)
LOAD CSV WITH HEADERS FROM 'file:///e94_space_primitive_1851.csv' AS row
CREATE (:E94_Space_Primitive {
  space_id: row.`space_id:ID`,
  latitude: toFloat(row.`latitude:float`),
  longitude: toFloat(row.`longitude:float`),
  crs: row.crs,
  point: point({latitude: toFloat(row.`latitude:float`), longitude: toFloat(row.`longitude:float`)})
});

// Import P166_was_a_presence_of relationships (repeat for each year)
LOAD CSV WITH HEADERS FROM 'file:///p166_was_presence_of_1851.csv' AS row
MATCH (presence:E93_Presence {presence_id: row.`:START_ID`})
MATCH (place:E53_Place {place_id: row.`:END_ID`})
CREATE (presence)-[:P166_was_a_presence_of]->(place);

// Import P164_is_temporally_specified_by relationships (repeat for each year)
LOAD CSV WITH HEADERS FROM 'file:///p164_temporally_specified_by_1851.csv' AS row
MATCH (presence:E93_Presence {presence_id: row.`:START_ID`})
MATCH (period:E4_Period {period_id: row.`:END_ID`})
CREATE (presence)-[:P164_is_temporally_specified_by]->(period);

// Import P161_has_spatial_projection relationships (repeat for each year)
LOAD CSV WITH HEADERS FROM 'file:///p161_spatial_projection_1851.csv' AS row
MATCH (presence:E93_Presence {presence_id: row.`:START_ID`})
MATCH (space:E94_Space_Primitive {space_id: row.`:END_ID`})
CREATE (presence)-[:P161_has_spatial_projection]->(space);

// Import P89_falls_within relationships (repeat for each year)
LOAD CSV WITH HEADERS FROM 'file:///p89_falls_within_1851.csv' AS row
MATCH (csd:E53_Place {place_id: row.`:START_ID`})
MATCH (cd:E53_Place {place_id: row.`:END_ID`})
CREATE (csd)-[:P89_falls_within]->(cd);

// Import P122_borders_with relationships (repeat for each year)
LOAD CSV WITH HEADERS FROM 'file:///p122_borders_with_1851.csv' AS row
MATCH (place1:E53_Place {place_id: row.`:START_ID`})
MATCH (place2:E53_Place {place_id: row.`:END_ID`})
CREATE (place1)-[:P122_borders_with {
  during_period: row.during_period,
  shared_border_length_m: toFloat(row.`shared_border_length_m:float`)
}]->(place2);
```

## Sample Queries

### Find all presences of a specific CSD across time
```cypher
MATCH (place:E53_Place {place_id: 'ON039029'})<-[:P166_was_a_presence_of]-(presence:E93_Presence)
MATCH (presence)-[:P164_is_temporally_specified_by]->(period:E4_Period)
MATCH (presence)-[:P161_has_spatial_projection]->(space:E94_Space_Primitive)
RETURN period.year, presence.area_sqm, space.latitude, space.longitude
ORDER BY period.year
```

### Find CSDs that border a specific CSD in 1901
```cypher
MATCH (place:E53_Place {place_id: 'ON039029'})-[b:P122_borders_with]->(neighbor:E53_Place)
WHERE b.during_period = 'CENSUS_1901'
RETURN neighbor.place_id, b.shared_border_length_m
ORDER BY b.shared_border_length_m DESC
```

### Find CSDs within 50km of a point (using Neo4j spatial)
```cypher
MATCH (presence:E93_Presence)-[:P164_is_temporally_specified_by]->(period:E4_Period {year: 1901})
MATCH (presence)-[:P161_has_spatial_projection]->(space:E94_Space_Primitive)
WITH presence, space,
     point.distance(space.point, point({latitude: 45.4215, longitude: -75.6972})) AS distance
WHERE distance < 50000  // 50km in meters
RETURN presence.csd_tcpuid, distance
ORDER BY distance
```

### Track CSD evolution (split/merge patterns)
```cypher
// Find CSDs that split between 1901 and 1911
MATCH (p1901:E93_Presence)-[:P164_is_temporally_specified_by]->(:E4_Period {year: 1901})
MATCH (p1911:E93_Presence)-[:P164_is_temporally_specified_by]->(:E4_Period {year: 1911})
WHERE p1901.area_sqm > p1911.area_sqm * 2
RETURN p1901.csd_tcpuid, p1901.area_sqm, p1911.area_sqm
ORDER BY (p1901.area_sqm - p1911.area_sqm) DESC
LIMIT 20
```

### Administrative hierarchy query
```cypher
// Find all CSDs within a specific Census Division
MATCH (cd:E53_Place {place_type: 'CD', name: 'Ottawa'})<-[:P89_falls_within]-(csd:E53_Place)
MATCH (csd)<-[:P166_was_a_presence_of]-(presence:E93_Presence)
MATCH (presence)-[:P164_is_temporally_specified_by]->(period:E4_Period {year: 1901})
RETURN csd.place_id, presence.area_sqm
```

## Data Statistics

### Growth Over Time

| Year | CSDs | CDs | Presences | Borders | Total Area (km²) |
|------|------|-----|-----------|---------|------------------|
| 1851 | 936  | ~60 | 936       | 2,150   | ~800,000         |
| 1861 | 1,202| ~75 | 1,202     | 2,778   | ~1,000,000       |
| 1871 | 1,818| ~100| 1,818     | 4,031   | ~2,500,000       |
| 1881 | 2,173| ~120| 2,173     | 4,779   | ~3,000,000       |
| 1891 | 2,509| ~140| 2,509     | 5,521   | ~4,000,000       |
| 1901 | 3,221| ~180| 3,221     | 7,281   | ~7,000,000       |
| 1911 | 3,825| ~200| 3,825     | 7,762   | ~8,500,000       |
| 1921 | 5,363| ~250| 5,363     | 11,296  | ~9,000,000       |

### Spatial Coverage

- **Provinces Covered**: ON, QC, NS, NB, PE, MB, SK, AB, BC, NL, YT, NT
- **Eastern Provinces**: Complete coverage from 1851
- **Western Provinces**: Manitoba (1871+), Saskatchewan/Alberta (1891+), BC (1871+)
- **Centroid Precision**: 6 decimal places (~0.11 meters)
- **Area Precision**: Square meters (2 decimal places)

## Technical Notes

### Coordinate Reference Systems
- **Internal Processing**: EPSG:3347 (Statistics Canada Lambert Conformal Conic)
- **Output Coordinates**: EPSG:4326 (WGS84 lat/lon for Neo4j compatibility)

### Border Detection Algorithm
- Uses `geometry.touches()` for adjacency detection
- Computes shared border length via boundary intersection
- Minimum threshold: 1 meter (filters numeric precision artifacts)
- Directed relationships avoided (only A→B, not B→A to prevent duplicates)

### Data Quality
- **55 invalid geometries** fixed via shapely `make_valid()`
- **Area calculations**: Precise to 0.01 m²
- **Centroid accuracy**: Within 0.1 meters
- **Border lengths**: Measured in projected CRS (EPSG:3347) for accuracy

## Integration with Temporal Links

This CIDOC-CRM data should be combined with temporal linkage data from `/year_links_output/`:

```cypher
// Add P132_spatiotemporally_overlaps_with relationships (SAME_AS links)
LOAD CSV WITH HEADERS FROM 'file:///year_links_1851_1861.csv' AS row
WHERE row.relationship = 'SAME_AS'
MATCH (p1:E93_Presence {presence_id: row.`tcpuid_1851` + '_1851'})
MATCH (p2:E93_Presence {presence_id: row.`tcpuid_1861` + '_1861'})
CREATE (p1)-[:P132_spatiotemporally_overlaps_with {
  iou: toFloat(row.iou)
}]->(p2);
```

Additional relationship metadata such as `relationship_type`, `from_fraction`, and `to_fraction` is retained in the exported CSV.

## Future Extensions

1. **Population Data**: Add E67_Birth entities for population counts
2. **Institutional Data**: Link E53_Places to churches, schools, hospitals
3. **Transportation Networks**: Add railway E53_Places and connections
4. **Historical Events**: E5_Event nodes for incorporation, annexation
5. **Multi-scale Geography**: Add province/territory E53_Places

## References

- **CIDOC-CRM**: http://www.cidoc-crm.org/
- **Neo4j Spatial**: https://neo4j.com/docs/cypher-manual/current/functions/spatial/
- **Statistics Canada TCP**: https://www.statcan.gc.ca/en/lode/databases/hgis

---

**Generated by**: `build_neo4j_cidoc_crm.py`
**Source Data**: TCP_CANADA_CSD_202306.gdb
**Processing Time**: ~2 minutes
**Total Files**: 61 CSV files (9.6 MB)