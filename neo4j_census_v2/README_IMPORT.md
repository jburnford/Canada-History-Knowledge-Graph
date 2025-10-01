# CIDOC-CRM v2.0 Census Observations - Neo4j Import Guide

## Overview

This directory contains CIDOC-CRM v2.0 compliant census observation data for 666,423 measurements across 6 census years (1851-1901). The data model properly implements:

- **E16_Measurement**: Census observations (not E13_Attribute_Assignment)
- **E54_Dimension**: Measured values with units
- **E58_Measurement_Unit**: Controlled unit vocabulary
- **E52_Time-Span**: Temporal extents (proper P4 target)
- **E73_Information_Object**: Source file provenance

## Prerequisites

**Required Node Files** (must be loaded first):
- E93_Presence nodes from `neo4j_cidoc_crm/e93_presence_*.csv` (21,047 nodes)
- E53_Place nodes from `neo4j_cidoc_crm/e53_place_*.csv` (13,135 nodes)

## File Inventory

### Node Files (14 files)
```
e16_measurements_all.csv           666,423 E16_Measurement nodes (51 MB)
e54_dimensions_all.csv             666,423 E54_Dimension nodes (32 MB)
e55_variable_types.csv             490 E55_Type nodes (variable taxonomy)
e58_measurement_units.csv          11 E58_Measurement_Unit nodes
e52_timespans.csv                  6 E52_Time-Span nodes
e4_periods.csv                     6 E4_Period nodes
e73_information_objects.csv        17 E73_Information_Object nodes
```

### Relationship Files (7 files)
```
p39_measured_all.csv               E16_Measurement → E93_Presence (37 MB)
p40_observed_dimension_all.csv     E16_Measurement → E54_Dimension (53 MB)
p91_has_unit_all.csv              E54_Dimension → E58_Measurement_Unit (35 MB)
p2_has_type_all.csv               E16_Measurement → E55_Type (37 MB)
p4_measurement_timespan_all.csv   E16_Measurement → E52_Time-Span (39 MB)
p4_period_timespan.csv            E4_Period → E52_Time-Span
p70_documents_all.csv             E73_Information_Object → E16_Measurement (39 MB)
```

## Import Procedure

### Step 1: Create Constraints (Before Import)

```cypher
// Uniqueness constraints for primary IDs
CREATE CONSTRAINT e16_id IF NOT EXISTS
  FOR (n:E16_Measurement) REQUIRE n.measurement_id IS UNIQUE;

CREATE CONSTRAINT e54_id IF NOT EXISTS
  FOR (n:E54_Dimension) REQUIRE n.dimension_id IS UNIQUE;

CREATE CONSTRAINT e55_id IF NOT EXISTS
  FOR (n:E55_Type) REQUIRE n.type_id IS UNIQUE;

CREATE CONSTRAINT e58_id IF NOT EXISTS
  FOR (n:E58_Measurement_Unit) REQUIRE n.unit_id IS UNIQUE;

CREATE CONSTRAINT e52_id IF NOT EXISTS
  FOR (n:E52_Time_Span) REQUIRE n.timespan_id IS UNIQUE;

CREATE CONSTRAINT e4_id IF NOT EXISTS
  FOR (n:E4_Period) REQUIRE n.period_id IS UNIQUE;

CREATE CONSTRAINT e73_id IF NOT EXISTS
  FOR (n:E73_Information_Object) REQUIRE n.info_object_id IS UNIQUE;

// E93 and E53 constraints (from CIDOC-CRM spatial data)
CREATE CONSTRAINT e93_id IF NOT EXISTS
  FOR (n:E93_Presence) REQUIRE n.presence_id IS UNIQUE;

CREATE CONSTRAINT e53_id IF NOT EXISTS
  FOR (n:E53_Place) REQUIRE n.place_id IS UNIQUE;
```

### Step 2: Create Performance Indexes (Optional)

```cypher
// Value lookups
CREATE INDEX e54_value IF NOT EXISTS
  FOR (n:E54_Dimension) ON (n.value);

// Year-based queries
CREATE INDEX e52_begin IF NOT EXISTS
  FOR (n:E52_Time_Span) ON (n.begin_of_begin);

// Variable category browsing
CREATE INDEX e55_category IF NOT EXISTS
  FOR (n:E55_Type) ON (n.category);
```

### Step 3: Import Node Files (Order Matters!)

**Prerequisites** (load from `neo4j_cidoc_crm/` first if not already loaded):
```cypher
// E53 Places
LOAD CSV WITH HEADERS FROM 'file:///neo4j_cidoc_crm/e53_place_csd.csv' AS row
CREATE (n:E53_Place {
  place_id: row.`place_id:ID`,
  name: row.name,
  province: row.province
});

// E93 Presence nodes (all years)
LOAD CSV WITH HEADERS FROM 'file:///neo4j_cidoc_crm/e93_presence_1851.csv' AS row
CREATE (n:E93_Presence {
  presence_id: row.`presence_id:ID`,
  csd_tcpuid: row.csd_tcpuid,
  census_year: toInteger(row.`census_year:int`),
  area_sqm: toFloat(row.`area_sqm:float`)
});
// Repeat for 1861, 1871, 1881, 1891, 1901
```

**V2 Census Nodes**:
```cypher
// E55 Variable Types
LOAD CSV WITH HEADERS FROM 'file:///neo4j_census_v2/e55_variable_types.csv' AS row
CREATE (n:E55_Type {
  type_id: row.`type_id:ID`,
  label: row.label,
  category: row.category,
  unit: row.unit,
  variable_name: row.variable_name
});

// E58 Measurement Units
LOAD CSV WITH HEADERS FROM 'file:///neo4j_census_v2/e58_measurement_units.csv' AS row
CREATE (n:E58_Measurement_Unit {
  unit_id: row.`unit_id:ID`,
  label: row.label,
  symbol: row.symbol
});

// E52 Time-Spans
LOAD CSV WITH HEADERS FROM 'file:///neo4j_census_v2/e52_timespans.csv' AS row
CREATE (n:E52_Time_Span {
  timespan_id: row.`timespan_id:ID`,
  label: row.label,
  begin_of_begin: row.begin_of_begin,
  end_of_end: row.end_of_end
});

// E4 Periods
LOAD CSV WITH HEADERS FROM 'file:///neo4j_census_v2/e4_periods.csv' AS row
CREATE (n:E4_Period {
  period_id: row.`period_id:ID`,
  label: row.label,
  year: toInteger(row.`year:int`)
});

// E73 Information Objects
LOAD CSV WITH HEADERS FROM 'file:///neo4j_census_v2/e73_information_objects.csv' AS row
CREATE (n:E73_Information_Object {
  info_object_id: row.`info_object_id:ID`,
  label: row.label,
  year: toInteger(row.`year:int`),
  landing_page: row.landing_page,
  access_uri: row.access_uri
});

// E16 Measurements (LARGE - use PERIODIC COMMIT)
:auto USING PERIODIC COMMIT 10000
LOAD CSV WITH HEADERS FROM 'file:///neo4j_census_v2/e16_measurements_all.csv' AS row
CREATE (n:E16_Measurement {
  measurement_id: row.`measurement_id:ID`,
  label: row.label,
  notes: row.notes
});

// E54 Dimensions (LARGE - use PERIODIC COMMIT)
:auto USING PERIODIC COMMIT 10000
LOAD CSV WITH HEADERS FROM 'file:///neo4j_census_v2/e54_dimensions_all.csv' AS row
CREATE (n:E54_Dimension {
  dimension_id: row.`dimension_id:ID`,
  value: CASE WHEN row.`value:float` = '' THEN null ELSE toFloat(row.`value:float`) END,
  value_string: row.value_string
});
```

### Step 4: Import Relationships (Order Matters!)

```cypher
// P2: E16 Measurement → E55 Type
:auto USING PERIODIC COMMIT 10000
LOAD CSV WITH HEADERS FROM 'file:///neo4j_census_v2/p2_has_type_all.csv' AS row
MATCH (m:E16_Measurement {measurement_id: row.`:START_ID`})
MATCH (t:E55_Type {type_id: row.`:END_ID`})
CREATE (m)-[:P2_has_type]->(t);

// P40: E16 Measurement → E54 Dimension
:auto USING PERIODIC COMMIT 10000
LOAD CSV WITH HEADERS FROM 'file:///neo4j_census_v2/p40_observed_dimension_all.csv' AS row
MATCH (m:E16_Measurement {measurement_id: row.`:START_ID`})
MATCH (d:E54_Dimension {dimension_id: row.`:END_ID`})
CREATE (m)-[:P40_observed_dimension]->(d);

// P91: E54 Dimension → E58 Unit
:auto USING PERIODIC COMMIT 10000
LOAD CSV WITH HEADERS FROM 'file:///neo4j_census_v2/p91_has_unit_all.csv' AS row
MATCH (d:E54_Dimension {dimension_id: row.`:START_ID`})
MATCH (u:E58_Measurement_Unit {unit_id: row.`:END_ID`})
CREATE (d)-[:P91_has_unit]->(u);

// P4: E16 Measurement → E52 Time-Span
:auto USING PERIODIC COMMIT 10000
LOAD CSV WITH HEADERS FROM 'file:///neo4j_census_v2/p4_measurement_timespan_all.csv' AS row
MATCH (m:E16_Measurement {measurement_id: row.`:START_ID`})
MATCH (t:E52_Time_Span {timespan_id: row.`:END_ID`})
CREATE (m)-[:P4_has_time_span]->(t);

// P4: E4 Period → E52 Time-Span
LOAD CSV WITH HEADERS FROM 'file:///neo4j_census_v2/p4_period_timespan.csv' AS row
MATCH (p:E4_Period {period_id: row.`:START_ID`})
MATCH (t:E52_Time_Span {timespan_id: row.`:END_ID`})
CREATE (p)-[:P4_has_time_span]->(t);

// P39: E16 Measurement → E93 Presence
:auto USING PERIODIC COMMIT 10000
LOAD CSV WITH HEADERS FROM 'file:///neo4j_census_v2/p39_measured_all.csv' AS row
MATCH (m:E16_Measurement {measurement_id: row.`:START_ID`})
MATCH (p:E93_Presence {presence_id: row.`:END_ID`})
CREATE (m)-[:P39_measured]->(p);

// P70: E73 Information Object → E16 Measurement
:auto USING PERIODIC COMMIT 10000
LOAD CSV WITH HEADERS FROM 'file:///neo4j_census_v2/p70_documents_all.csv' AS row
MATCH (i:E73_Information_Object {info_object_id: row.`:START_ID`})
MATCH (m:E16_Measurement {measurement_id: row.`:END_ID`})
CREATE (i)-[:P70_documents]->(m);
```

## Validation Queries

### Data Completeness Checks

```cypher
// Count measurements per year
MATCH (t:E52_Time_Span)<-[:P4_has_time_span]-(m:E16_Measurement)
RETURN t.timespan_id, count(m) AS measurement_count
ORDER BY t.timespan_id;

// Expected counts:
// 1851: 150,266
// 1861: 164,246
// 1871: 36,860
// 1881: 75,793
// 1891: 201,569
// 1901: 37,689
// TOTAL: 666,423

// Verify dimension-unit linkage
MATCH (m:E16_Measurement)-[:P40_observed_dimension]->(d:E54_Dimension)-[:P91_has_unit]->(u:E58_Measurement_Unit)
RETURN m.measurement_id, d.value, u.label
LIMIT 5;

// Check variable types resolve
MATCH (m:E16_Measurement)-[:P2_has_type]->(t:E55_Type)
RETURN t.category, count(m) AS measurement_count
ORDER BY measurement_count DESC
LIMIT 10;

// Verify P39 targets are E93_Presence
MATCH (m:E16_Measurement)-[:P39_measured]->(x)
RETURN labels(x) AS target_class, count(*) AS relationship_count;
// Should return: ["E93_Presence"], 666423

// Check provenance chain
MATCH (i:E73_Information_Object)-[:P70_documents]->(m:E16_Measurement)
RETURN i.label, count(m) AS documented_measurements
ORDER BY i.label;
```

### Sample Research Queries

```cypher
// Population measurements for a specific CSD across years
MATCH (m:E16_Measurement)-[:P39_measured]->(presence:E93_Presence {csd_tcpuid: 'ON039029'})
MATCH (m)-[:P2_has_type]->(t:E55_Type)
WHERE t.category = 'POP'
MATCH (m)-[:P40_observed_dimension]->(d:E54_Dimension)
MATCH (m)-[:P4_has_time_span]->(ts:E52_Time_Span)
RETURN presence.census_year, t.label, d.value
ORDER BY presence.census_year;

// Agricultural measurements by unit type
MATCH (m:E16_Measurement)-[:P2_has_type]->(t:E55_Type {category: 'AGR'})
MATCH (m)-[:P40_observed_dimension]->(d:E54_Dimension)-[:P91_has_unit]->(u:E58_Measurement_Unit)
RETURN u.label, count(*) AS measurement_count, avg(d.value) AS avg_value
ORDER BY measurement_count DESC;

// Find all measurements from specific source file
MATCH (i:E73_Information_Object {label: '1891_V6T19_PUB_202306.xlsx'})-[:P70_documents]->(m:E16_Measurement)
MATCH (m)-[:P2_has_type]->(t:E55_Type)
RETURN t.category, count(*) AS measurement_count
ORDER BY measurement_count DESC;
```

## Data Model Summary

### CIDOC-CRM Pattern (v2.0)
```
E16_Measurement (observation)
  ├─ P39_measured → E93_Presence (CSD-year instance)
  ├─ P40_observed_dimension → E54_Dimension
  │   ├─ value:float (numeric value)
  │   └─ P91_has_unit → E58_Measurement_Unit
  ├─ P2_has_type → E55_Type (variable taxonomy)
  ├─ P4_has_time_span → E52_Time-Span (temporal extent)
  └─ P70i_is_documented_in ← E73_Information_Object (source file)

E4_Period (census year concept)
  └─ P4_has_time_span → E52_Time-Span (shared with measurements)
```

### Variable Categories (E55_Type)
- **POP**: Population counts (total, by gender, age)
- **AGE**: Age distributions
- **REL**: Religious denominations
- **AGR**: Agricultural production (crops, livestock)
- **MAN**: Manufacturing output
- **HOUSE**: Household counts
- **ETHNIC**: Ethnic origins
- **LANG**: Language spoken

### Measurement Units (E58)
- persons, acres, square_miles, dollars, bushels, cwt, lbs, number, yards, gallons, cords

## Troubleshooting

### Missing E93 Presence Nodes
If P39 relationships fail, ensure E93 nodes are loaded from `neo4j_cidoc_crm/`:
```bash
ls -lh neo4j_cidoc_crm/e93_presence_*.csv
```

### Missing E55 Type Nodes
E55 variable types are now included in this directory:
```bash
wc -l neo4j_census_v2/e55_variable_types.csv
# Should show: 491 (490 types + header)
```

### Large File Import Performance
- Use `:auto USING PERIODIC COMMIT 10000` for files >100k rows
- Increase Neo4j heap memory: `dbms.memory.heap.max_size=4G`
- Consider splitting by year if needed

## File Size Summary
- **Total**: 318 MB across 14 CSV files
- **Largest files**:
  - p40_observed_dimension_all.csv (53 MB)
  - e16_measurements_all.csv (51 MB)
  - p4_measurement_timespan_all.csv (39 MB)
  - p70_documents_all.csv (39 MB)

## Next Steps
1. Load 1911/1921 data (multi-layer GDB investigation needed)
2. Add E33_Linguistic_Object for DOI citation
3. Add E30_Right for CC BY 4.0 license
4. Add E39_Actor nodes for CHGIS Principal Investigators
5. Generate RDF/TTL exports for LOD publication
