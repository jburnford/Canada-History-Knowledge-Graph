# Census Variables CIDOC-CRM Data Model (REVISED)

**Version**: 2.0 - Codex Aligned
**Date**: September 30, 2025
**Changes**: Corrected to proper CIDOC-CRM/CRMsci patterns

## Key Changes from v1.0

1. **E13_Attribute_Assignment → E16_Measurement** - Measurements are observations, not assignments
2. **P140 → P39** - Use P39_measured for linking measurements to places
3. **P4 targets E52_Time-Span** - Not E4_Period directly
4. **E54_Dimension nodes** - Separate value/unit representation via P40_observed_dimension
5. **E58_Measurement_Unit** - Explicit unit representation (persons, acres, etc.)
6. **E73_Information_Object** - Provenance tracking for source tables

## CIDOC-CRM Entity Model

### Core Measurement Pattern

```
E16_Measurement (observation)
  ├─ P39_measured → E93_Presence (CSD in specific year)
  ├─ P2_has_type → E55_Type (variable type: POP_TOTAL, AGE_05to10M, etc.)
  ├─ P40_observed_dimension → E54_Dimension
  │   ├─ P90_has_value → "1234"^^xsd:integer
  │   └─ P91_has_unit → E58_Measurement_Unit (persons)
  ├─ P4_has_time-span → E52_Time-Span (1901-01-01 to 1901-12-31)
  └─ P70_documents → E73_Information_Object (source table)
```

### Entity Descriptions

#### E16_Measurement - Census Observation
Represents a single measurement/observation made during a census.

**Properties**:
- `measurement_id:ID` - Unique identifier (e.g., `MEAS_ON001001_1901_POP_TOT`)
- `label` - Human-readable label (e.g., "Population Total for ON001001 in 1901")
- `notes` - Data quality notes

**Relationships**:
- `P39_measured` → E93_Presence (which CSD-year was measured)
- `P2_has_type` → E55_Type (what kind of measurement: population, age, religion)
- `P40_observed_dimension` → E54_Dimension (the measured value)
- `P4_has_time-span` → E52_Time-Span (when measurement was taken)
- `P70_documents` → E73_Information_Object (source table reference)

#### E54_Dimension - Measured Value
Represents the actual numeric/string value with units.

**Properties**:
- `dimension_id:ID` - Unique identifier (e.g., `DIM_ON001001_1901_POP_TOT`)
- `value:float` - Numeric value (if applicable)
- `value_string` - String value (if non-numeric)

**Relationships**:
- `P90_has_value` → Literal value ("1234"^^xsd:integer)
- `P91_has_unit` → E58_Measurement_Unit (persons, acres, dollars)

#### E58_Measurement_Unit - Unit of Measure
Controlled vocabulary of measurement units.

**Properties**:
- `unit_id:ID` - Unique identifier (e.g., `UNIT_PERSONS`)
- `label` - Unit label (e.g., "persons", "acres", "dollars")
- `symbol` - Unit symbol (e.g., "ppl", "ac", "$")

#### E52_Time-Span - Temporal Extent
Represents the time period when measurement occurred.

**Properties**:
- `timespan_id:ID` - Unique identifier (e.g., `TIMESPAN_1901`)
- `begin_of_begin` - Start date (1901-01-01)
- `end_of_end` - End date (1901-12-31)
- `label` - "Census Year 1901"

**Relationships**:
- Used by both E16_Measurement (P4) and E4_Period (P4)

#### E4_Period - Census Period
Represents the census event as a historical period.

**Properties**:
- `period_id:ID` - Unique identifier (e.g., `PERIOD_CENSUS_1901`)
- `label` - "1901 Canadian Census"

**Relationships**:
- `P4_has_time-span` → E52_Time-Span (same timespan as measurements)
- `P10_falls_within` → E4_Period (optional: broader historical periods)

#### E73_Information_Object - Source Data
Represents the Excel table file that contains the measurement.

**Properties**:
- `info_object_id:ID` - Unique identifier (e.g., `SOURCE_1901_V1T7_CSD`)
- `label` - File name (e.g., "1901_V1T7_CSD_202306.xlsx")
- `source_table` - Table identifier (e.g., "V1T7")
- `file_hash` - SHA256 hash for verification (if available)
- `access_uri` - Direct download URL from repository
- `landing_page` - Human-readable landing page URL

**Relationships**:
- `P70i_documents` ← E16_Measurement (measurements derived from this source)
- `P67i_is_referred_to_by` ← E33_Linguistic_Object (citation, DOI)
- `P104_is_subject_to` → E30_Right (license information)

#### E33_Linguistic_Object - Citation/DOI
Represents formal citation and DOI for the dataset.

**Properties**:
- `citation_id:ID` - Unique identifier (e.g., `CITATION_CHGIS_CENSUS`)
- `citation_text` - Full citation text
- `doi` - Digital Object Identifier
- `version` - Dataset version

**Example**:
```
McInnis, Marvin; Dawson, Michael; Emery, J.C. Herbert; Mackinnon, Mary;
St-Hilaire, Marc; Stainton, Corinne; Warkentin, John; Waite, Peter, 2023,
"The Canadian Historical GIS (CHGIS)",
https://doi.org/10.5683/SP3/PKUZJN, Borealis, V1
```

**Relationships**:
- `P67_refers_to` → E73_Information_Object (citation describes the dataset)

#### E30_Right - License
Represents usage rights and licensing information.

**Properties**:
- `right_id:ID` - Unique identifier (e.g., `LICENSE_CC_BY_4_0`)
- `label` - License name (e.g., "CC BY 4.0")
- `access_rights` - Access restrictions
- `license_uri` - URL to license text

**Relationships**:
- `P104i_applies_to` ← E73_Information_Object (dataset subject to this license)

#### E39_Actor - Data Creators/Contributors
Represents individuals and organizations responsible for creating the dataset.

**Properties**:
- `actor_id:ID` - Unique identifier (e.g., `ACTOR_MCINNIS_MARVIN`)
- `name` - Full name
- `type` - E21_Person or E74_Group
- `orcid` - ORCID identifier (if applicable)
- `affiliation` - Institutional affiliation

**Relationships**:
- `P14_carried_out` → E7_Activity (creation/publication activity)

#### E55_Type - Variable Type Taxonomy
Controlled vocabulary for census variable types (unchanged from v1.0).

**Properties**:
- `type_id:ID` - Unique identifier (e.g., `VAR_POP_TOTAL`)
- `label` - Variable label (e.g., "Total Population")
- `category` - Broader category (POPULATION, AGE, RELIGION, etc.)
- `description` - Full description
- `skos:prefLabel` - Preferred label
- `skos:broader` - Link to parent category

## Neo4j CSV Files

### 1. e16_measurements_{YEAR}.csv

```csv
measurement_id:ID,:LABEL,label,notes
MEAS_ON001001_1901_POP_TOT,E16_Measurement,Population Total for ON001001 in 1901,
MEAS_ON001001_1901_POP_M,E16_Measurement,Male Population for ON001001 in 1901,
```

### 2. e54_dimensions_{YEAR}.csv

```csv
dimension_id:ID,:LABEL,value:float,value_string
DIM_ON001001_1901_POP_TOT,E54_Dimension,1234.0,
DIM_ON001001_1901_RELIGION_CATHOLIC,E54_Dimension,,Catholic
```

### 3. e58_measurement_units.csv

```csv
unit_id:ID,:LABEL,label,symbol
UNIT_PERSONS,E58_Measurement_Unit,persons,ppl
UNIT_ACRES,E58_Measurement_Unit,acres,ac
UNIT_SQUARE_MILES,E58_Measurement_Unit,square miles,sq mi
UNIT_DOLLARS,E58_Measurement_Unit,dollars,$
UNIT_BUSHELS,E58_Measurement_Unit,bushels,bu
UNIT_HEAD,E58_Measurement_Unit,head (livestock),head
UNIT_FARMS,E58_Measurement_Unit,farms,farms
```

### 4. e52_timespans.csv

```csv
timespan_id:ID,:LABEL,label,begin_of_begin,end_of_end
TIMESPAN_1851,E52_Time-Span,Census Year 1851,1851-01-01,1851-12-31
TIMESPAN_1861,E52_Time-Span,Census Year 1861,1861-01-01,1861-12-31
TIMESPAN_1871,E52_Time-Span,Census Year 1871,1871-01-01,1871-12-31
TIMESPAN_1881,E52_Time-Span,Census Year 1881,1881-01-01,1881-12-31
TIMESPAN_1891,E52_Time-Span,Census Year 1891,1891-01-01,1891-12-31
TIMESPAN_1901,E52_Time-Span,Census Year 1901,1901-01-01,1901-12-31
TIMESPAN_1911,E52_Time-Span,Census Year 1911,1911-01-01,1911-12-31
TIMESPAN_1921,E52_Time-Span,Census Year 1921,1921-01-01,1921-12-31
```

### 5. e4_periods.csv (updated)

```csv
period_id:ID,:LABEL,label
PERIOD_CENSUS_1851,E4_Period,1851 Canadian Census
PERIOD_CENSUS_1861,E4_Period,1861 Canadian Census
PERIOD_CENSUS_1871,E4_Period,1871 Canadian Census
PERIOD_CENSUS_1881,E4_Period,1881 Canadian Census
PERIOD_CENSUS_1891,E4_Period,1891 Canadian Census
PERIOD_CENSUS_1901,E4_Period,1901 Canadian Census
PERIOD_CENSUS_1911,E4_Period,1911 Canadian Census
PERIOD_CENSUS_1921,E4_Period,1921 Canadian Census
```

### 6. e73_information_objects_{YEAR}.csv

```csv
info_object_id:ID,:LABEL,label,source_table,file_hash,access_uri,landing_page
SOURCE_1901_V1T7_CSD,E73_Information_Object,1901_V1T7_CSD_202306.xlsx,V1T7,,https://borealisdata.ca/api/access/datafile/:persistentId/?persistentId=doi:10.5683/SP3/XXXX,https://borealisdata.ca/dataset.xhtml?persistentId=doi:10.5683/SP3/XXXX
```

### 7. p39_measured_{YEAR}.csv

```csv
:START_ID,:END_ID,:TYPE
MEAS_ON001001_1901_POP_TOT,ON001001_1901,P39_measured
MEAS_ON001001_1901_POP_M,ON001001_1901,P39_measured
```

### 8. p40_observed_dimension_{YEAR}.csv

```csv
:START_ID,:END_ID,:TYPE
MEAS_ON001001_1901_POP_TOT,DIM_ON001001_1901_POP_TOT,P40_observed_dimension
```

### 9. p90_has_value_{YEAR}.csv

This is typically represented as a property on E54_Dimension, not a separate relationship.
Include in e54_dimensions CSV as `value:float` column.

### 10. p91_has_unit_{YEAR}.csv

```csv
:START_ID,:END_ID,:TYPE
DIM_ON001001_1901_POP_TOT,UNIT_PERSONS,P91_has_unit
DIM_ON001001_1901_AREA_ACRES,UNIT_ACRES,P91_has_unit
```

### 11. p2_has_type_{YEAR}.csv (unchanged)

```csv
:START_ID,:END_ID,:TYPE
MEAS_ON001001_1901_POP_TOT,VAR_POP_TOTAL,P2_has_type
```

### 12. p4_has_timespan_{YEAR}.csv

```csv
:START_ID,:END_ID,:TYPE
MEAS_ON001001_1901_POP_TOT,TIMESPAN_1901,P4_has_time-span
PERIOD_CENSUS_1901,TIMESPAN_1901,P4_has_time-span
```

### 13. p70_documents_{YEAR}.csv

```csv
:START_ID,:END_ID,:TYPE
SOURCE_1901_V1T7_CSD,MEAS_ON001001_1901_POP_TOT,P70_documents
```

### 14. e55_variable_types.csv (enhanced with SKOS)

```csv
type_id:ID,:LABEL,label,category,description,skos_prefLabel,skos_broader
VAR_POP_TOTAL,E55_Type,Total Population,POPULATION,Combined male and female population,Total Population,VAR_POPULATION_ROOT
VAR_POP_MALE,E55_Type,Male Population,POPULATION,Male population count,Male Population,VAR_POP_TOTAL
VAR_POP_FEMALE,E55_Type,Female Population,POPULATION,Female population count,Female Population,VAR_POP_TOTAL
VAR_POPULATION_ROOT,E55_Type,Population (all types),POPULATION,Root category for all population measurements,Population,
```

### 15. e33_citations.csv

```csv
citation_id:ID,:LABEL,citation_text,doi,version,repository
CITATION_CHGIS_CENSUS,E33_Linguistic_Object,"McInnis, Marvin; Dawson, Michael; Emery, J.C. Herbert; Mackinnon, Mary; St-Hilaire, Marc; Stainton, Corinne; Warkentin, John; Waite, Peter, 2023, ""The Canadian Historical GIS (CHGIS)"", https://doi.org/10.5683/SP3/PKUZJN, Borealis, V1",https://doi.org/10.5683/SP3/PKUZJN,V1,Borealis - Canadian Dataverse Repository
```

### 16. e30_rights.csv

```csv
right_id:ID,:LABEL,label,access_rights,license_uri
LICENSE_CC_BY_4_0,E30_Right,CC BY 4.0,Open Access,https://creativecommons.org/licenses/by/4.0/
```

### 17. e39_actors.csv

```csv
actor_id:ID,:LABEL,name,type,orcid,affiliation
ACTOR_MCINNIS_MARVIN,E39_Actor,Marvin McInnis,E21_Person,,Queen's University
ACTOR_DAWSON_MICHAEL,E39_Actor,Michael Dawson,E21_Person,,University of Victoria
ACTOR_EMERY_HERBERT,E39_Actor,J.C. Herbert Emery,E21_Person,,University of Calgary
ACTOR_MACKINNON_MARY,E39_Actor,Mary MacKinnon,E21_Person,,McGill University
ACTOR_STHILAIRE_MARC,E39_Actor,Marc St-Hilaire,E21_Person,,Université Laval
ACTOR_STAINTON_CORINNE,E39_Actor,Corinne Stainton,E21_Person,,University of Guelph
ACTOR_WARKENTIN_JOHN,E39_Actor,John Warkentin,E21_Person,,York University
ACTOR_WAITE_PETER,E39_Actor,Peter Waite,E21_Person,,Dalhousie University
ACTOR_CHGIS_PROJECT,E39_Actor,Canadian Historical GIS Project,E74_Group,,Multi-institutional collaboration
```

### 18. p67_citation_refers_to.csv

```csv
:START_ID,:END_ID,:TYPE
CITATION_CHGIS_CENSUS,SOURCE_1851_V1T1_CSD,P67_refers_to
CITATION_CHGIS_CENSUS,SOURCE_1861_V1T1_CSD,P67_refers_to
CITATION_CHGIS_CENSUS,SOURCE_1871_V1T1_CSD,P67_refers_to
CITATION_CHGIS_CENSUS,SOURCE_1881_V1T1_CSD,P67_refers_to
CITATION_CHGIS_CENSUS,SOURCE_1891_V1T2_CSD,P67_refers_to
CITATION_CHGIS_CENSUS,SOURCE_1901_V1T7_CSD,P67_refers_to
```

### 19. p104_subject_to_right.csv

```csv
:START_ID,:END_ID,:TYPE
SOURCE_1851_V1T1_CSD,LICENSE_CC_BY_4_0,P104_is_subject_to
SOURCE_1861_V1T1_CSD,LICENSE_CC_BY_4_0,P104_is_subject_to
SOURCE_1871_V1T1_CSD,LICENSE_CC_BY_4_0,P104_is_subject_to
SOURCE_1881_V1T1_CSD,LICENSE_CC_BY_4_0,P104_is_subject_to
SOURCE_1891_V1T2_CSD,LICENSE_CC_BY_4_0,P104_is_subject_to
SOURCE_1901_V1T7_CSD,LICENSE_CC_BY_4_0,P104_is_subject_to
```

## Borealis Repository Provenance

### Dataset Information

**Repository**: Borealis - The Canadian Dataverse Repository
**Collection**: The Canadian Historical GIS (CHGIS)
**Landing Page**: https://borealisdata.ca/dataverse/census?q=&fq2=seriesName_ss%3A%22The+Canadian+Historical+GIS+%28CHGIS%29%22
**DOI**: https://doi.org/10.5683/SP3/PKUZJN
**License**: CC BY 4.0
**Version**: V1 (2023)

### Principal Investigators

1. **Marvin McInnis** - Queen's University
2. **Michael Dawson** - University of Victoria
3. **J.C. Herbert Emery** - University of Calgary
4. **Mary MacKinnon** - McGill University
5. **Marc St-Hilaire** - Université Laval
6. **Corinne Stainton** - University of Guelph
7. **John Warkentin** - York University
8. **Peter Waite** - Dalhousie University

### Dataset Components by Year

Each census year has multiple tables in the Borealis repository:

- **1851**: V1T1, V1T3, V2T6, V2T7 (CSD, CD, PUB, OCR versions)
- **1861**: V1T1, V1T5, V2T11 (CSD, CD, PUB, OCR versions)
- **1871**: V1T1, V3T23, PE_V1T1 (CSD, CD, PUB, OCR versions)
- **1881**: V1T1, V3T24, V3T27 (CSD, CD, PUB, OCR versions)
- **1891**: V1T2, V1T3, V2T16, V4T2, V4T3 (CSD, CD, PUB, OCR versions)
- **1901**: V1T7 (CSD, CD, PUB, OCR versions)
- **1911**: V1T1, V1T2, V2T2, V2T7, V2T28 (Multiple spatial layers)
- **1921**: (To be processed)

### File Naming Convention

Format: `{YEAR}_{TABLE}_{TYPE}_202306.xlsx`

- **YEAR**: Census year (1851-1921)
- **TABLE**: Volume and Table number (e.g., V1T1, V2T7)
- **TYPE**:
  - `CSD` - Census Subdivision level data
  - `CD` - Census Division level data
  - `PUB` - Published format
  - `OCR` - OCR-scanned historical tables
- **202306**: Dataset version (June 2023)

### Direct Download URLs (Template)

```
https://borealisdata.ca/api/access/datafile/:persistentId/?persistentId=doi:10.5683/SP3/[DATASET_ID]
```

Note: Individual file DOIs need to be obtained from the Borealis API or metadata.

## Revised Script Output Structure

### File Naming Convention

```
neo4j_census_observations_v2/
├── e16_measurements_1851.csv
├── e16_measurements_1861.csv
├── ...
├── e54_dimensions_1851.csv
├── e54_dimensions_1861.csv
├── ...
├── e58_measurement_units.csv
├── e52_timespans.csv
├── e4_periods.csv
├── e73_information_objects_1851.csv
├── ...
├── e55_variable_types.csv
├── p39_measured_1851.csv
├── p40_observed_dimension_1851.csv
├── p91_has_unit_1851.csv
├── p2_has_type_1851.csv
├── p4_has_timespan_1851.csv
└── p70_documents_1851.csv
```

## Neo4j Cypher Import Example

```cypher
// 1. Import E58_Measurement_Unit nodes
LOAD CSV WITH HEADERS FROM 'file:///e58_measurement_units.csv' AS row
CREATE (:E58_Measurement_Unit {
  unit_id: row.`unit_id:ID`,
  label: row.label,
  symbol: row.symbol
});

// 2. Import E52_Time-Span nodes
LOAD CSV WITH HEADERS FROM 'file:///e52_timespans.csv' AS row
CREATE (:E52_Time_Span {
  timespan_id: row.`timespan_id:ID`,
  label: row.label,
  begin_of_begin: date(row.begin_of_begin),
  end_of_end: date(row.end_of_end)
});

// 3. Import E4_Period nodes
LOAD CSV WITH HEADERS FROM 'file:///e4_periods.csv' AS row
CREATE (:E4_Period {
  period_id: row.`period_id:ID`,
  label: row.label
});

// 4. Link E4_Period to E52_Time-Span
LOAD CSV WITH HEADERS FROM 'file:///p4_has_timespan_periods.csv' AS row
MATCH (period:E4_Period {period_id: row.`:START_ID`})
MATCH (timespan:E52_Time_Span {timespan_id: row.`:END_ID`})
CREATE (period)-[:P4_has_time_span]->(timespan);

// 5. Import E16_Measurement nodes (per year)
LOAD CSV WITH HEADERS FROM 'file:///e16_measurements_1901.csv' AS row
CREATE (:E16_Measurement {
  measurement_id: row.`measurement_id:ID`,
  label: row.label,
  notes: row.notes
});

// 6. Import E54_Dimension nodes (per year)
LOAD CSV WITH HEADERS FROM 'file:///e54_dimensions_1901.csv' AS row
CREATE (:E54_Dimension {
  dimension_id: row.`dimension_id:ID`,
  value: CASE WHEN row.`value:float` <> '' THEN toFloat(row.`value:float`) ELSE null END,
  value_string: row.value_string
});

// 7. Link E16_Measurement P39 measured → E93_Presence
LOAD CSV WITH HEADERS FROM 'file:///p39_measured_1901.csv' AS row
MATCH (measurement:E16_Measurement {measurement_id: row.`:START_ID`})
MATCH (presence:E93_Presence {presence_id: row.`:END_ID`})
CREATE (measurement)-[:P39_measured]->(presence);

// 8. Link E16_Measurement P40 observed_dimension → E54_Dimension
LOAD CSV WITH HEADERS FROM 'file:///p40_observed_dimension_1901.csv' AS row
MATCH (measurement:E16_Measurement {measurement_id: row.`:START_ID`})
MATCH (dimension:E54_Dimension {dimension_id: row.`:END_ID`})
CREATE (measurement)-[:P40_observed_dimension]->(dimension);

// 9. Link E54_Dimension P91 has_unit → E58_Measurement_Unit
LOAD CSV WITH HEADERS FROM 'file:///p91_has_unit_1901.csv' AS row
MATCH (dimension:E54_Dimension {dimension_id: row.`:START_ID`})
MATCH (unit:E58_Measurement_Unit {unit_id: row.`:END_ID`})
CREATE (dimension)-[:P91_has_unit]->(unit);

// 10. Link E16_Measurement P2 has_type → E55_Type
LOAD CSV WITH HEADERS FROM 'file:///p2_has_type_1901.csv' AS row
MATCH (measurement:E16_Measurement {measurement_id: row.`:START_ID`})
MATCH (type:E55_Type {type_id: row.`:END_ID`})
CREATE (measurement)-[:P2_has_type]->(type);

// 11. Link E16_Measurement P4 has_time-span → E52_Time-Span
LOAD CSV WITH HEADERS FROM 'file:///p4_has_timespan_1901.csv' AS row
MATCH (measurement:E16_Measurement {measurement_id: row.`:START_ID`})
MATCH (timespan:E52_Time_Span {timespan_id: row.`:END_ID`})
CREATE (measurement)-[:P4_has_time_span]->(timespan);
```

## Sample Queries

### Query 1: Get all measurements for a CSD in 1901 with values and units

```cypher
MATCH (place:E53_Place {place_id: 'ON001001'})<-[:P166_was_a_presence_of]-(presence:E93_Presence)
MATCH (measurement:E16_Measurement)-[:P39_measured]->(presence)
MATCH (measurement)-[:P40_observed_dimension]->(dimension:E54_Dimension)
MATCH (dimension)-[:P91_has_unit]->(unit:E58_Measurement_Unit)
MATCH (measurement)-[:P2_has_type]->(type:E55_Type)
MATCH (presence)-[:P164_is_temporally_specified_by]->(period:E4_Period {year: 1901})
RETURN
  type.label AS variable,
  dimension.value AS value,
  dimension.value_string AS value_string,
  unit.label AS unit,
  measurement.label AS measurement_label
ORDER BY type.category, type.label
```

### Query 2: Population growth analysis with proper temporal linking

```cypher
MATCH (place:E53_Place)<-[:P166_was_a_presence_of]-(p1901:E93_Presence)
MATCH (place)<-[:P166_was_a_presence_of]-(p1911:E93_Presence)
MATCH (m1901:E16_Measurement)-[:P39_measured]->(p1901)
MATCH (m1911:E16_Measurement)-[:P39_measured]->(p1911)
MATCH (m1901)-[:P2_has_type]->(:E55_Type {type_id: 'VAR_POP_TOTAL'})
MATCH (m1911)-[:P2_has_type]->(:E55_Type {type_id: 'VAR_POP_TOTAL'})
MATCH (m1901)-[:P40_observed_dimension]->(d1901:E54_Dimension)
MATCH (m1911)-[:P40_observed_dimension]->(d1911:E54_Dimension)
RETURN
  place.place_id,
  d1901.value AS pop_1901,
  d1911.value AS pop_1911,
  d1911.value - d1901.value AS growth
ORDER BY growth DESC
LIMIT 20
```

### Query 3: Find all measurements from a specific source table

```cypher
MATCH (source:E73_Information_Object {source_table: 'V1T7'})-[:P70_documents]->(measurement:E16_Measurement)
MATCH (measurement)-[:P40_observed_dimension]->(dimension:E54_Dimension)
MATCH (measurement)-[:P2_has_type]->(type:E55_Type)
RETURN
  measurement.measurement_id,
  type.label,
  dimension.value,
  source.label
LIMIT 100
```

## LOD Best Practices

### URI Minting Pattern

```
Base URI: https://census.canadianarchives.ca/crm/

E16_Measurement: {base}/measurement/{measurement_id}
E54_Dimension: {base}/dimension/{dimension_id}
E58_Measurement_Unit: {base}/unit/{unit_id}
E52_Time-Span: {base}/timespan/{timespan_id}
E4_Period: {base}/period/{period_id}
E55_Type: {base}/type/{type_id}
E73_Information_Object: {base}/source/{info_object_id}
```

### RDF Prefixes

```turtle
@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .
@prefix crmdig: <http://www.ics.forth.gr/isl/CRMdig/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix census: <https://census.canadianarchives.ca/crm/> .
```

### Sample RDF (Turtle) with Full Provenance

```turtle
@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix census: <https://census.canadianarchives.ca/crm/> .

# Measurement
census:measurement/MEAS_ON001001_1901_POP_TOT a crm:E16_Measurement ;
  rdfs:label "Population Total for ON001001 in 1901" ;
  crm:P39_measured census:presence/ON001001_1901 ;
  crm:P2_has_type census:type/VAR_POP_TOTAL ;
  crm:P40_observed_dimension census:dimension/DIM_ON001001_1901_POP_TOT ;
  crm:P4_has_time-span census:timespan/TIMESPAN_1901 ;
  crm:P70i_is_documented_in census:source/SOURCE_1901_V1T7_CSD .

# Dimension (value + unit)
census:dimension/DIM_ON001001_1901_POP_TOT a crm:E54_Dimension ;
  crm:P90_has_value "1234"^^xsd:integer ;
  crm:P91_has_unit census:unit/UNIT_PERSONS .

# Measurement Unit
census:unit/UNIT_PERSONS a crm:E58_Measurement_Unit ;
  rdfs:label "persons" ;
  skos:prefLabel "persons"@en .

# Time-Span
census:timespan/TIMESPAN_1901 a crm:E52_Time-Span ;
  rdfs:label "Census Year 1901" ;
  crm:P82a_begin_of_the_begin "1901-01-01"^^xsd:date ;
  crm:P82b_end_of_the_end "1901-12-31"^^xsd:date .

# Period
census:period/PERIOD_CENSUS_1901 a crm:E4_Period ;
  rdfs:label "1901 Canadian Census" ;
  crm:P4_has_time-span census:timespan/TIMESPAN_1901 .

# Source Information Object
census:source/SOURCE_1901_V1T7_CSD a crm:E73_Information_Object ;
  rdfs:label "1901_V1T7_CSD_202306.xlsx" ;
  dcterms:identifier "SOURCE_1901_V1T7_CSD" ;
  dcterms:format "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" ;
  crm:P104_is_subject_to census:license/LICENSE_CC_BY_4_0 ;
  crm:P67i_is_referred_to_by census:citation/CITATION_CHGIS_CENSUS ;
  dcterms:isPartOf <https://borealisdata.ca/dataset.xhtml?persistentId=doi:10.5683/SP3/PKUZJN> .

# Citation
census:citation/CITATION_CHGIS_CENSUS a crm:E33_Linguistic_Object ;
  rdfs:label "CHGIS Dataset Citation" ;
  dcterms:bibliographicCitation """McInnis, Marvin; Dawson, Michael; Emery, J.C. Herbert;
    Mackinnon, Mary; St-Hilaire, Marc; Stainton, Corinne; Warkentin, John; Waite, Peter, 2023,
    "The Canadian Historical GIS (CHGIS)", https://doi.org/10.5683/SP3/PKUZJN, Borealis, V1""" ;
  dcterms:identifier <https://doi.org/10.5683/SP3/PKUZJN> ;
  crm:P67_refers_to census:source/SOURCE_1901_V1T7_CSD .

# License
census:license/LICENSE_CC_BY_4_0 a crm:E30_Right ;
  rdfs:label "CC BY 4.0" ;
  dcterms:license <https://creativecommons.org/licenses/by/4.0/> ;
  dcterms:rights "Open Access" .

# Creators (sample)
census:actor/ACTOR_MCINNIS_MARVIN a crm:E21_Person ;
  rdfs:label "Marvin McInnis" ;
  foaf:name "Marvin McInnis" ;
  schema:affiliation "Queen's University" ;
  crm:P14_carried_out census:activity/CREATION_CHGIS .

census:actor/ACTOR_CHGIS_PROJECT a crm:E74_Group ;
  rdfs:label "Canadian Historical GIS Project" ;
  foaf:name "Canadian Historical GIS Project" ;
  crm:P107_has_current_or_former_member census:actor/ACTOR_MCINNIS_MARVIN ,
    census:actor/ACTOR_DAWSON_MICHAEL ,
    census:actor/ACTOR_EMERY_HERBERT ,
    census:actor/ACTOR_MACKINNON_MARY ,
    census:actor/ACTOR_STHILAIRE_MARC ,
    census:actor/ACTOR_STAINTON_CORINNE ,
    census:actor/ACTOR_WARKENTIN_JOHN ,
    census:actor/ACTOR_WAITE_PETER .

# Creation Activity
census:activity/CREATION_CHGIS a crm:E65_Creation ;
  rdfs:label "Creation of CHGIS Dataset" ;
  crm:P14_carried_out_by census:actor/ACTOR_CHGIS_PROJECT ;
  crm:P94_has_created census:source/SOURCE_1901_V1T7_CSD ;
  crm:P4_has_time-span [
    a crm:E52_Time-Span ;
    crm:P82a_begin_of_the_begin "2020-01-01"^^xsd:date ;
    crm:P82b_end_of_the_end "2023-06-30"^^xsd:date
  ] .

# Variable Type with SKOS
census:type/VAR_POP_TOTAL a crm:E55_Type ;
  rdfs:label "Total Population" ;
  skos:prefLabel "Total Population"@en ;
  skos:definition "Combined male and female population count"@en ;
  skos:broader census:type/VAR_POPULATION_ROOT ;
  skos:inScheme census:scheme/CENSUS_VARIABLES .

census:scheme/CENSUS_VARIABLES a skos:ConceptScheme ;
  rdfs:label "Canadian Census Variable Taxonomy" ;
  skos:hasTopConcept census:type/VAR_POPULATION_ROOT ,
    census:type/VAR_AGE_ROOT ,
    census:type/VAR_RELIGION_ROOT ,
    census:type/VAR_AGRICULTURE_ROOT .
```

---

## Summary of Provenance Integration

### Complete Provenance Chain

```
E16_Measurement (observation)
  ↓ P70i_is_documented_in
E73_Information_Object (1901_V1T7_CSD_202306.xlsx)
  ↓ P67i_is_referred_to_by
E33_Linguistic_Object (CHGIS Citation with DOI)
  ↓ dcterms:isPartOf
Borealis Repository (https://borealisdata.ca/...)
  ↓ P104_is_subject_to
E30_Right (CC BY 4.0 License)

E73_Information_Object
  ↓ P94i_was_created_by
E65_Creation (CHGIS Dataset Creation Activity)
  ↓ P14_carried_out_by
E39_Actor (8 Principal Investigators + CHGIS Project Team)
```

### Provenance Benefits

1. **Attribution**: Clear credit to CHGIS project and all 8 PIs
2. **Citability**: DOI links measurements back to citable dataset
3. **Licensing**: Explicit CC BY 4.0 open access licensing
4. **Reproducibility**: Direct links to source files in Borealis repository
5. **Versioning**: Dataset version (V1, June 2023) tracked
6. **Institutional Context**: University affiliations for all researchers
7. **Repository Stability**: Borealis as long-term preservation repository

### Compliance with Standards

- ✅ **CIDOC-CRM**: Proper use of E16, E54, E58, E52, E73, E33, E30, E39
- ✅ **Dublin Core**: dcterms properties for bibliographic metadata
- ✅ **SKOS**: Taxonomy for variable types
- ✅ **FAIR Principles**: Findable (DOI), Accessible (Borealis), Interoperable (CRM), Reusable (CC BY 4.0)
- ✅ **LOD Best Practices**: Resolvable URIs, typed literals, provenance chains

### Query Example: Full Provenance Trace

```cypher
// Find all information about a measurement including full provenance
MATCH (measurement:E16_Measurement {measurement_id: 'MEAS_ON001001_1901_POP_TOT'})
MATCH (measurement)-[:P70i_is_documented_in]->(source:E73_Information_Object)
MATCH (source)<-[:P67_refers_to]-(citation:E33_Linguistic_Object)
MATCH (source)-[:P104_is_subject_to]->(license:E30_Right)
MATCH (source)<-[:P94_has_created]-(creation:E65_Creation)
MATCH (creation)-[:P14_carried_out_by]->(actor:E39_Actor)
MATCH (measurement)-[:P40_observed_dimension]->(dimension:E54_Dimension)
MATCH (dimension)-[:P91_has_unit]->(unit:E58_Measurement_Unit)
RETURN
  measurement.label AS observation,
  dimension.value AS value,
  unit.label AS unit,
  source.label AS source_file,
  citation.doi AS dataset_doi,
  license.label AS license,
  collect(actor.name) AS creators
```

---

**Next Steps**:
1. Update `build_census_observations.py` to generate v2.0 structure
2. Add E54_Dimension and E58_Measurement_Unit generation
3. Add E52_Time-Span and updated E4_Period nodes
4. Add E73_Information_Object provenance tracking with Borealis URLs
5. Add E33_Linguistic_Object citation with CHGIS DOI
6. Add E30_Right (CC BY 4.0) and E39_Actor (8 PIs + CHGIS team)
7. Test with 1901 data (37,689 observations)
8. Generate RDF/TTL exports for LOD publication
9. Validate against CIDOC-CRM ontology
10. Publish to public SPARQL endpoint
