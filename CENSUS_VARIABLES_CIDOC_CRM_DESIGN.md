# Census Variables CIDOC-CRM Ontological Model

**Date**: September 30, 2025
**Purpose**: Design LOD-compatible knowledge graph for Canadian census variables (1851-1921)
**Scope**: 490 census variables across 8 categories, ~21,000 CSD presences

---

## Executive Summary

This document defines a CIDOC-CRM compliant ontological model for representing historical census data as Linked Open Data. The model handles:

- **Statistical Observations**: Population, agriculture, manufacturing, vital statistics
- **Dimension Properties**: Gender, age groups, ethnicity, religion, industry types
- **Measurement Units**: Counts, acres, bushels, dollars, etc.
- **Temporal Specificity**: Observations tied to specific census years
- **Spatial Context**: Observations linked to Census Subdivisions (CSDs)

### Key Design Principles

1. **Separation of Concerns**: Statistical observations are separate from place definitions
2. **Temporal Precision**: Each observation is explicitly dated to a census year
3. **Provenance**: All data traceable to specific census tables and variables
4. **Composability**: Variables can be aggregated, filtered, and cross-referenced
5. **LOD Compatibility**: Uses W3C standards (RDF, SKOS, CIDOC-CRM, QB)

---

## Ontological Framework

### Core CIDOC-CRM Classes

#### E13_Attribute_Assignment (Census Observation)
**Definition**: The act of assigning a measured value to a place at a specific time

**Properties**:
- `observation_id:ID` - Unique identifier (e.g., `OBS_ON001001_1911_POP_TOT`)
- `observed_value:float` - The numeric measurement
- `variable_code` - Standard variable name (e.g., `POP_TOT_1911`)
- `variable_label` - Human-readable description
- `category` - Thematic category (POP, AGR, MFG, etc.)
- `unit_of_measurement` - Count, acres, bushels, dollars, etc.
- `precision` - Measurement precision/reliability

**CIDOC-CRM Relationships**:
- `P140_assigned_attribute_to` → **E93_Presence** (which CSD-year presence)
- `P141_assigned` → **E60_Number** (the measured value)
- `P177_assigned_property_type` → **E55_Type** (which census variable)
- `P4_has_time_span` → **E52_Time-Span** (census year)
- `P70i_is_documented_in` → **E31_Document** (source census table)

**Example**: "The 1911 census recorded a total population of 226 persons in T24 R25 MW4"

```turtle
:OBS_AB001002_1911_POP_TOT a crm:E13_Attribute_Assignment ;
    rdfs:label "Population observation: T24 R25 MW4, 1911" ;
    crm:P140_assigned_attribute_to :PRESENCE_AB001002_1911 ;
    crm:P141_assigned :NUMBER_226 ;
    crm:P177_assigned_property_type :VAR_POP_TOT ;
    crm:P4_has_time_span :CENSUS_YEAR_1911 ;
    :observed_value 226 ;
    :unit_of_measurement "count" ;
    :category "POP" .

:NUMBER_226 a crm:E60_Number ;
    rdf:value 226 ;
    rdfs:label "226 persons" .

:VAR_POP_TOT a crm:E55_Type , skos:Concept ;
    skos:prefLabel "Total Population"@en ;
    skos:notation "POP_TOT" ;
    skos:inScheme :CENSUS_VARIABLE_SCHEME ;
    :category "POP" ;
    :unit "count" .
```

#### E55_Type (Census Variable Definitions)
**Definition**: Controlled vocabulary of standardized census variables

**Properties**:
- `variable_id:ID` - Variable code (e.g., `VAR_POP_TOT`)
- `skos:prefLabel` - Human-readable label
- `skos:notation` - Short code (POP_TOT, AGR_WHT, MFG_SAW)
- `skos:definition` - Full description
- `skos:broader` - Category hierarchy (e.g., POP_M → POP)
- `category` - Top-level grouping (AGE, POP, AGR, MFG, etc.)
- `unit_of_measurement` - Default unit
- `available_years` - Which censuses collected this variable

**Example Hierarchy**:
```
POP (Population)
├── POP_TOT (Total Population)
├── POP_M (Male Population)
├── POP_F (Female Population)
├── POP_DENSITY (Persons per square mile)
└── BIRTH_LY (Births in past year)
```

```turtle
:VAR_POP a crm:E55_Type , skos:Concept ;
    skos:prefLabel "Population Variables"@en ;
    skos:topConceptOf :CENSUS_VARIABLE_SCHEME .

:VAR_POP_TOT a crm:E55_Type , skos:Concept ;
    skos:prefLabel "Total Population"@en ;
    skos:notation "POP_TOT" ;
    skos:broader :VAR_POP ;
    :category "POP" ;
    :unit "count" ;
    :available_years "1851,1861,1871,1881,1891,1901,1911,1921" .

:VAR_POP_M a crm:E55_Type , skos:Concept ;
    skos:prefLabel "Male Population"@en ;
    skos:notation "POP_M" ;
    skos:broader :VAR_POP ;
    :category "POP" ;
    :unit "count" .
```

#### E31_Document (Census Tables)
**Definition**: Published census volumes and tables containing the data

**Properties**:
- `document_id:ID` - Table identifier (e.g., `DOC_1911_V1T1`)
- `title` - Official table name
- `census_year` - Which census
- `volume` - Census volume number
- `table_number` - Table within volume
- `url` - Link to digitized source

**Example**:
```turtle
:DOC_1911_V1T1 a crm:E31_Document ;
    rdfs:label "1911 Census Volume 1 Table 1" ;
    dc:title "Population by census subdivision" ;
    dc:date "1911" ;
    :volume "V1" ;
    :table_number "T1" ;
    :census_year 1911 .
```

---

## Alternative Model: W3C Data Cube (QB)

For purely statistical analysis, the **RDF Data Cube Vocabulary** may be more appropriate than CIDOC-CRM's E13_Attribute_Assignment. Data Cube is designed specifically for multi-dimensional statistical data.

### QB Model Structure

```turtle
# Dataset definition
:CENSUS_DATASET_1911 a qb:DataSet ;
    rdfs:label "Canadian Census 1911" ;
    qb:structure :CENSUS_DSD ;
    dc:issued "1911"^^xsd:gYear .

# Data Structure Definition (dimensions + measures)
:CENSUS_DSD a qb:DataStructureDefinition ;
    qb:component [ qb:dimension :dim_place ] ;
    qb:component [ qb:dimension :dim_year ] ;
    qb:component [ qb:dimension :dim_variable ] ;
    qb:component [ qb:measure :measure_value ] .

# Observation
:OBS_AB001002_1911_POP_TOT a qb:Observation ;
    qb:dataSet :CENSUS_DATASET_1911 ;
    :dim_place :PRESENCE_AB001002_1911 ;
    :dim_year :CENSUS_YEAR_1911 ;
    :dim_variable :VAR_POP_TOT ;
    :measure_value 226 ;
    sdmx-attribute:unitMeasure :UNIT_COUNT .
```

### Hybrid Approach (Recommended)

Use **CIDOC-CRM for provenance and context**, **QB for statistical queries**:

```turtle
:OBS_AB001002_1911_POP_TOT a crm:E13_Attribute_Assignment , qb:Observation ;
    # CIDOC-CRM properties (provenance)
    crm:P140_assigned_attribute_to :PRESENCE_AB001002_1911 ;
    crm:P70i_is_documented_in :DOC_1911_V1T1 ;
    crm:P4_has_time_span :CENSUS_YEAR_1911 ;

    # Data Cube properties (analysis)
    qb:dataSet :CENSUS_DATASET_1911 ;
    :dim_variable :VAR_POP_TOT ;
    :measure_value 226 ;
    sdmx-attribute:unitMeasure :UNIT_COUNT .
```

---

## Neo4j Graph Schema

### Node Types

```
(:E13_Attribute_Assignment)  - Census observations (millions of nodes)
(:E93_Presence)              - CSD-year presences (21,047 nodes)
(:E55_Type)                  - Variable definitions (490 nodes)
(:E31_Document)              - Census tables (~40 nodes)
(:E60_Number)                - Numeric values (optional, for rich semantics)
(:E52_Time_Span)             - Census years (8 nodes)
```

### Relationship Types

```
(:E13)-[:P140_assigned_attribute_to]->(:E93_Presence)
(:E13)-[:P141_assigned]->(:E60_Number)
(:E13)-[:P177_assigned_property_type]->(:E55_Type)
(:E13)-[:P4_has_time_span]->(:E52_Time_Span)
(:E13)-[:P70i_is_documented_in]->(:E31_Document)
(:E55_Type)-[:SKOS_BROADER]->(:E55_Type)  # Variable hierarchy
```

### Simplified Neo4j Schema (Performance Optimization)

For Neo4j performance, we can flatten the model:

```
(:CensusObservation)  # E13_Attribute_Assignment
  Properties:
    - obs_id (ID)
    - presence_id (denormalized link to E93_Presence)
    - csd_tcpuid (denormalized for quick lookup)
    - census_year (denormalized)
    - variable_code (denormalized)
    - variable_label (denormalized)
    - category (indexed for filtering)
    - value (the actual measurement)
    - unit (count, acres, etc.)
    - source_table (DOC_1911_V1T1)

(:CensusObservation)-[:OBSERVED_IN]->(:E93_Presence)
(:CensusObservation)-[:OF_TYPE]->(:CensusVariable)
(:CensusObservation)-[:FROM_TABLE]->(:CensusTable)
```

### Indexing Strategy

```cypher
// Core lookup indexes
CREATE INDEX obs_presence_year IF NOT EXISTS
FOR (o:CensusObservation) ON (o.presence_id, o.census_year);

CREATE INDEX obs_variable_year IF NOT EXISTS
FOR (o:CensusObservation) ON (o.variable_code, o.census_year);

CREATE INDEX obs_category IF NOT EXISTS
FOR (o:CensusObservation) ON (o.category);

CREATE INDEX obs_csd_year IF NOT EXISTS
FOR (o:CensusObservation) ON (o.csd_tcpuid, o.census_year);

// Full-text search on variable labels
CREATE FULLTEXT INDEX var_search IF NOT EXISTS
FOR (v:CensusVariable) ON EACH [v.label, v.description];
```

---

## Data Volume Estimates

### Node Counts

| Node Type | 1911 Only | All 8 Years | Notes |
|-----------|-----------|-------------|-------|
| CensusObservation | ~380,000 | ~1,900,000 | 3,825 CSDs × ~100 variables/CSD |
| E93_Presence | 3,825 | 21,047 | Existing |
| CensusVariable | 490 | 490 | Controlled vocabulary |
| CensusTable | ~5 | ~40 | 5 tables/year × 8 years |

### Relationship Counts

| Relationship | 1911 Only | All 8 Years |
|--------------|-----------|-------------|
| OBSERVED_IN | 380,000 | 1,900,000 |
| OF_TYPE | 380,000 | 1,900,000 |
| FROM_TABLE | 380,000 | 1,900,000 |

### Storage Requirements

- **Neo4j Database**: ~500MB (1911 only), ~2.5GB (all years)
- **CSV Export Files**: ~150MB (1911 only), ~750MB (all years)
- **RDF Triples**: ~5M triples (1911), ~25M triples (all years)

---

## Variable Categories and Examples

### Population (POP) - 41 variables
- Total, male, female population
- Population density
- Births, deaths in past year
- Urban/rural breakdown

### Age (AGE) - 91 variables
- Age cohorts by gender
- Very granular for early censuses (1-year increments)
- Coarser for later censuses (5-year increments)

### Agriculture (AGR) - 114 variables
- Total farm area (acres)
- Crop production (wheat, barley, oats, etc.) in bushels
- Livestock counts (cattle, horses, sheep, pigs)
- Farm buildings and equipment

### Manufacturing (MFG) - 99 variables
- Industrial establishments by type
- Production output (bricks, lumber, flour)
- Employment in industries
- Capital invested

### Fisheries (FSH) - 35 variables
- Fishing vessels and crews
- Fish caught by species
- Processing facilities

### Ethnicity (ETH) - 35 variables
- Ethnic origin counts
- Indigenous populations
- Immigration statistics

### Religion (REL) - 10 variables
- Religious denomination counts
- Church attendance

### Buildings (BLD) - 25 variables
- Housing stock by size
- Public buildings (churches, schools)
- Building materials

### Deaths (DTH) - 40 variables
- Deaths by age and gender
- Causes of death (limited data)

---

## Sample Queries

### Query 1: Population Growth of a CSD Over Time

```cypher
// Neo4j
MATCH (obs:CensusObservation {variable_code: 'POP_TOT'})-[:OBSERVED_IN]->(pres:E93_Presence)
WHERE pres.csd_tcpuid = 'ON001001'
RETURN obs.census_year AS year, obs.value AS population
ORDER BY year
```

```sparql
# SPARQL
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX : <http://example.org/census/>

SELECT ?year ?population
WHERE {
  ?obs a crm:E13_Attribute_Assignment ;
       crm:P140_assigned_attribute_to ?presence ;
       crm:P177_assigned_property_type :VAR_POP_TOT ;
       :observed_value ?population ;
       crm:P4_has_time_span ?timespan .
  ?presence :csd_tcpuid "ON001001" .
  ?timespan :year ?year .
}
ORDER BY ?year
```

### Query 2: Agricultural Production in Saskatchewan, 1911

```cypher
// Neo4j - All wheat production in Saskatchewan
MATCH (obs:CensusObservation {variable_code: 'AGR_WHT', census_year: 1911})
MATCH (obs)-[:OBSERVED_IN]->(pres:E93_Presence)-[:P7_took_place_at]->(place:E53_Place)
WHERE place.province = 'SK'
RETURN place.place_id, obs.value AS wheat_bushels
ORDER BY wheat_bushels DESC
```

### Query 3: Religious Diversity Index

```cypher
// Count number of different religious denominations per CSD in 1911
MATCH (obs:CensusObservation {census_year: 1911})-[:OBSERVED_IN]->(pres:E93_Presence)
MATCH (obs)-[:OF_TYPE]->(var:CensusVariable {category: 'REL'})
WHERE obs.value > 0
WITH pres.csd_tcpuid AS csd, count(DISTINCT var.variable_code) AS religious_diversity
RETURN csd, religious_diversity
ORDER BY religious_diversity DESC
LIMIT 20
```

### Query 4: Correlated Variables (Population vs Agriculture)

```cypher
// Compare population and agricultural productivity
MATCH (pop_obs:CensusObservation {variable_code: 'POP_TOT', census_year: 1911})
      -[:OBSERVED_IN]->(pres:E93_Presence)
MATCH (agr_obs:CensusObservation {variable_code: 'AGR_WHT', census_year: 1911})
      -[:OBSERVED_IN]->(pres)
WHERE pop_obs.value > 100  // Filter out tiny settlements
RETURN pres.csd_tcpuid,
       pop_obs.value AS population,
       agr_obs.value AS wheat_bushels,
       agr_obs.value / pop_obs.value AS wheat_per_capita
ORDER BY wheat_per_capita DESC
LIMIT 20
```

---

## Implementation Plan

### Phase 1: Variable Ontology (Week 1)
- [ ] Parse master variable files for all 8 census years
- [ ] Create unified variable taxonomy (SKOS hierarchy)
- [ ] Generate E55_Type nodes CSV for Neo4j
- [ ] Generate variable definitions RDF/Turtle

### Phase 2: Data Extraction (Week 2)
- [ ] Extract all Excel tables from ZIP files
- [ ] Parse table structures (varied formats across years)
- [ ] Map columns to standardized variable codes
- [ ] Handle missing data and data quality issues

### Phase 3: Observation Generation (Week 3)
- [ ] Create E13_Attribute_Assignment nodes for each CSD-variable-year
- [ ] Link observations to E93_Presence nodes
- [ ] Generate Neo4j CSV files (chunked by year)
- [ ] Create RDF export for LOD compatibility

### Phase 4: Quality Assurance (Week 4)
- [ ] Statistical validation (ranges, distributions)
- [ ] Cross-reference with published census summaries
- [ ] Test queries for common research questions
- [ ] Performance benchmarking on Neo4j

### Phase 5: Documentation & Publication (Week 5)
- [ ] API documentation for graph queries
- [ ] Sample notebooks (Jupyter) for analysis
- [ ] LOD publication via SPARQL endpoint
- [ ] Integration with GeoNames, DBpedia, Wikidata

---

## Technical Considerations

### Year-Specific Challenges

**1851-1871**: More granular age cohorts, fewer economic variables
**1881-1891**: Introduction of manufacturing and ethnic variables
**1901-1921**: Comprehensive coverage, but inconsistent column naming

### Data Quality Issues

1. **Missing Values**: Some CSDs don't have all variables (sparse data)
2. **OCR Errors**: Digitization errors in numeric values (need validation)
3. **Unit Inconsistencies**: Acres vs sq. miles, bushels vs pounds
4. **Name Mismatches**: CSD names in tables may differ from GIS data

### Performance Optimization

1. **Batch Imports**: Use Neo4j LOAD CSV with batching (10K rows at a time)
2. **Denormalization**: Store frequently-queried properties on observation nodes
3. **Pre-computed Aggregates**: Create summary nodes for province/country totals
4. **Caching**: Materialize common query patterns as views

---

## Standards Compliance

### W3C Standards
- **RDF 1.1**: Resource Description Framework
- **SKOS**: Simple Knowledge Organization System (for variables)
- **Data Cube**: Multi-dimensional statistical data
- **DCAT**: Dataset metadata and provenance

### Cultural Heritage Standards
- **CIDOC-CRM 7.1**: Conceptual Reference Model
- **EDM**: Europeana Data Model (cultural heritage aggregation)

### Geospatial Standards
- **GeoSPARQL**: Spatial queries on RDF
- **WGS84 Geo**: lat/lon coordinates
- **EPSG:4326**: Coordinate reference system

### Statistical Standards
- **SDMX**: Statistical Data and Metadata eXchange
- **DDI**: Data Documentation Initiative

---

## Future Extensions

1. **Time Series Analysis**: Integrate R/Python statistical libraries
2. **Machine Learning**: Predict missing values, detect anomalies
3. **Visualization**: Interactive maps, timeline charts
4. **Text Mining**: Link to digitized census manuscripts (OLMoCR output)
5. **Cross-Dataset Linking**: Connect to parish registers, immigration records
6. **Semantic Enrichment**: Link ethnicities to modern countries, industries to NAICS codes

---

## References

- CIDOC-CRM: http://www.cidoc-crm.org/
- W3C Data Cube: https://www.w3.org/TR/vocab-data-cube/
- SKOS Primer: https://www.w3.org/TR/skos-primer/
- Statistics Canada HGIS: https://www.statcan.gc.ca/en/lode/databases/hgis
- Neo4j Graph Data Science: https://neo4j.com/docs/graph-data-science/

---

**Status**: Design Complete - Ready for Implementation
**Next Step**: Create `build_census_observations.py` script
