# Census Variables CIDOC-CRM Data Model

**Version**: 1.0
**Date**: September 30, 2025
**Purpose**: Extend Canadian Census Knowledge Graph with demographic, population, agricultural, and economic variables

## Overview

This model extends the existing CIDOC-CRM structure (E53_Place, E93_Presence, E4_Period) to incorporate census tabular data. It follows LINCS project patterns for linking observations to places and time periods.

## Core Principle

**Key Insight**: Census variables are **observations/measurements made during a specific census event**, not properties of the place itself. A CSD's population in 1911 is an observation made in 1911, distinct from its 1901 population.

## CIDOC-CRM Entities for Census Data

### E13_Attribute_Assignment - Census Observation Event
Represents the act of measuring/recording a census variable during a census.

**Properties**:
- `observation_id:ID` - Unique identifier (e.g., `AB001001_1911_POP_TOT`)
- `variable_name` - Standardized variable name (e.g., `POP_TOT`, `AGE_05to10M_N`)
- `variable_category` - Category (POPULATION, AGE, RELIGION, BIRTHPLACE, LANGUAGE, AGRICULTURE, etc.)
- `value_numeric:float` - Numeric value if applicable
- `value_string` - String value if applicable
- `unit` - Unit of measurement (persons, acres, bushels, dollars, etc.)
- `source_table` - Source file (e.g., `1911_V1T1`)
- `notes` - Data quality notes

**Relationships**:
- `P140_assigned_attribute_to` → E93_Presence (which CSD-year this observation describes)
- `P4_has_time_span` → E4_Period (which census year)
- `P2_has_type` → E55_Type (variable type: population, agricultural, demographic)

### E55_Type - Variable Type Taxonomy
Controlled vocabulary for variable types and categories.

**Hierarchy**:
```
E55_Type (Census Variable)
├── POPULATION
│   ├── POP_TOTAL
│   ├── POP_MALE
│   ├── POP_FEMALE
│   └── POP_DENSITY
├── AGE_COHORT
│   ├── AGE_0to5
│   ├── AGE_5to10
│   └── ...
├── RELIGION
│   ├── ANGLICAN
│   ├── CATHOLIC
│   ├── PRESBYTERIAN
│   └── ...
├── BIRTHPLACE
│   ├── CANADIAN_BORN
│   ├── BRITISH_BORN
│   └── FOREIGN_BORN
├── LANGUAGE
│   ├── ENGLISH
│   ├── FRENCH
│   └── OTHER
├── AGRICULTURE
│   ├── FARM_COUNT
│   ├── FARM_ACREAGE
│   ├── CROP_YIELD
│   └── LIVESTOCK_COUNT
└── ECONOMIC
    ├── OCCUPATION
    └── INDUSTRY
```

## Neo4j Data Model

### Node Labels

#### :E13_Attribute_Assignment (Census Observation)
```cypher
CREATE (:E13_Attribute_Assignment {
  observation_id: "AB001001_1911_POP_TOT",
  variable_name: "POP_TOT_1911",
  variable_category: "POPULATION",
  value_numeric: 196.0,
  unit: "persons",
  source_table: "1911_V1T1",
  notes: null
})
```

#### :E55_Type (Variable Type)
```cypher
CREATE (:E55_Type {
  type_id: "VAR_POP_TOTAL",
  label: "Total Population",
  category: "POPULATION",
  description: "Total population count (male + female)"
})
```

### Relationships

#### P140_assigned_attribute_to
Links observation to the CSD-year presence it describes.

```cypher
MATCH (obs:E13_Attribute_Assignment {observation_id: "AB001001_1911_POP_TOT"})
MATCH (presence:E93_Presence {presence_id: "AB001001_1911"})
CREATE (obs)-[:P140_assigned_attribute_to]->(presence)
```

#### P4_has_time_span
Links observation to the census period.

```cypher
MATCH (obs:E13_Attribute_Assignment {observation_id: "AB001001_1911_POP_TOT"})
MATCH (period:E4_Period {period_id: "CENSUS_1911"})
CREATE (obs)-[:P4_has_time_span]->(period)
```

#### P2_has_type
Links observation to its variable type.

```cypher
MATCH (obs:E13_Attribute_Assignment {observation_id: "AB001001_1911_POP_TOT"})
MATCH (type:E55_Type {type_id: "VAR_POP_TOTAL"})
CREATE (obs)-[:P2_has_type]->(type)
```

## Data Structure

### CSV Files to Generate

#### 1. `e13_observations_{YEAR}.csv`
One file per census year with all observations.

```csv
observation_id:ID,variable_name,variable_category,value_numeric:float,value_string,unit,source_table,notes
AB001001_1911_POP_TOT,POP_TOT,POPULATION,196.0,,persons,1911_V1T1,
AB001001_1911_POP_M,POP_M,POPULATION,112.0,,persons,1911_V1T1,
AB001001_1911_POP_F,POP_F,POPULATION,84.0,,persons,1911_V1T1,
AB001001_1911_AREA_ACRES,AREA_ACRES,GEOGRAPHY,230400.0,,acres,1911_V1T1,
```

#### 2. `e55_variable_types.csv`
Controlled vocabulary of all variable types (once, not per year).

```csv
type_id:ID,label,category,description,unit
VAR_POP_TOTAL,Total Population,POPULATION,Combined male and female population,persons
VAR_POP_MALE,Male Population,POPULATION,Male population count,persons
VAR_POP_FEMALE,Female Population,POPULATION,Female population count,persons
VAR_AREA_ACRES,Area in Acres,GEOGRAPHY,Land area in acres,acres
VAR_AGE_05to10M,Males Aged 5-10,AGE_COHORT,Number of males aged 5 to 10 years,persons
```

#### 3. `p140_observation_to_presence_{YEAR}.csv`
Links observations to CSD-year presences.

```csv
:START_ID,:END_ID,:TYPE
AB001001_1911_POP_TOT,AB001001_1911,P140_assigned_attribute_to
AB001001_1911_POP_M,AB001001_1911,P140_assigned_attribute_to
AB001001_1911_POP_F,AB001001_1911,P140_assigned_attribute_to
```

#### 4. `p4_observation_to_period_{YEAR}.csv`
Links observations to census periods.

```csv
:START_ID,:END_ID,:TYPE
AB001001_1911_POP_TOT,CENSUS_1911,P4_has_time_span
AB001001_1911_POP_M,CENSUS_1911,P4_has_time_span
AB001001_1911_POP_F,CENSUS_1911,P4_has_time_span
```

#### 5. `p2_observation_to_type_{YEAR}.csv`
Links observations to variable types.

```csv
:START_ID,:END_ID,:TYPE
AB001001_1911_POP_TOT,VAR_POP_TOTAL,P2_has_type
AB001001_1911_POP_M,VAR_POP_MALE,P2_has_type
AB001001_1911_POP_F,VAR_POP_FEMALE,P2_has_type
```

## Data Processing Pipeline

### Step 1: Extract Variable Definitions
Parse `TCP_CANADA_CD-CSD_Mastvar.xlsx` to understand which variables exist for which years.

```python
# Read master variables
mastvar = pd.read_excel('TCP_CANADA_CD-CSD_Mastvar.xlsx')

# Create E55_Type nodes for all variables
variable_types = []
for _, row in mastvar.iterrows():
    variable_types.append({
        'type_id': f"VAR_{row['Name']}",
        'label': row['Description'],
        'category': row['Category'],
        'unit': infer_unit(row['Name'])  # persons, acres, etc.
    })
```

### Step 2: Process Census Tables by Year
For each year (1851-1921), read all available tables and create observations.

```python
# For 1911
v1t1 = pd.read_excel('1911Tables/1911/1911_V1T1_PUB_202306.xlsx', skiprows=3)
v2t2 = pd.read_excel('1911Tables/1911/1911_V2T2_PUB_202306.xlsx', skiprows=3)
# ... etc

observations = []
for _, row in v1t1.iterrows():
    csd_id = row['V1T1_1911']  # e.g., AB001001

    # Create observation for each non-null variable
    if pd.notna(row['POP_TOT_1911']):
        observations.append({
            'observation_id': f"{csd_id}_1911_POP_TOT",
            'variable_name': 'POP_TOT',
            'variable_category': 'POPULATION',
            'value_numeric': row['POP_TOT_1911'],
            'unit': 'persons',
            'source_table': '1911_V1T1'
        })
```

### Step 3: Link to Existing CIDOC-CRM Structure
Use the V1T1_1911 ID (e.g., AB001001) to link to E93_Presence nodes.

**Critical**: The V1T1_1911 ID must be matched to TCPUID_CSD_1911 from the GDB layer.

```python
# Load GDB layer to get TCPUID mapping
gdf = gpd.read_file(gdb_path, layer='CSD_1911')

# Create mapping: V1T1_1911 → TCPUID_CSD_1911
# Note: These might be identical or need reconciliation
id_mapping = dict(zip(gdf['V1T1_1911'], gdf['TCPUID_CSD_1911']))

# Use TCPUID to link to E93_Presence
for obs in observations:
    v1t1_id = obs['observation_id'].split('_')[0]  # AB001001
    tcpuid = id_mapping.get(v1t1_id)
    if tcpuid:
        obs['presence_id'] = f"{tcpuid}_1911"  # Link to existing E93_Presence
```

## Sample Queries

### Query 1: Get all demographic data for a CSD in 1911
```cypher
MATCH (place:E53_Place {place_id: 'AB001001'})<-[:P7_took_place_at]-(presence:E93_Presence)
MATCH (presence)<-[:P140_assigned_attribute_to]-(obs:E13_Attribute_Assignment)
MATCH (presence)-[:P164_is_temporally_specified_by]->(period:E4_Period {year: 1911})
RETURN obs.variable_name, obs.value_numeric, obs.unit, obs.variable_category
ORDER BY obs.variable_category, obs.variable_name
```

### Query 2: Compare population growth 1901-1911
```cypher
MATCH (place:E53_Place)<-[:P7_took_place_at]-(p1901:E93_Presence)
MATCH (place)<-[:P7_took_place_at]-(p1911:E93_Presence)
MATCH (p1901)-[:P164_is_temporally_specified_by]->(:E4_Period {year: 1901})
MATCH (p1911)-[:P164_is_temporally_specified_by]->(:E4_Period {year: 1911})
MATCH (p1901)<-[:P140_assigned_attribute_to]-(obs1901:E13_Attribute_Assignment {variable_name: 'POP_TOT'})
MATCH (p1911)<-[:P140_assigned_attribute_to]-(obs1911:E13_Attribute_Assignment {variable_name: 'POP_TOT'})
RETURN place.place_id,
       obs1901.value_numeric AS pop_1901,
       obs1911.value_numeric AS pop_1911,
       obs1911.value_numeric - obs1901.value_numeric AS growth
ORDER BY growth DESC
LIMIT 20
```

### Query 3: Find CSDs with specific religious demographics
```cypher
MATCH (obs:E13_Attribute_Assignment)
WHERE obs.variable_category = 'RELIGION'
  AND obs.variable_name = 'CATHOLIC'
  AND obs.value_numeric > 5000
MATCH (obs)-[:P140_assigned_attribute_to]->(presence:E93_Presence)
MATCH (presence)-[:P7_took_place_at]->(place:E53_Place)
MATCH (presence)-[:P164_is_temporally_specified_by]->(period:E4_Period)
RETURN place.place_id, period.year, obs.value_numeric
ORDER BY obs.value_numeric DESC
```

### Query 4: Agricultural productivity analysis
```cypher
MATCH (obs:E13_Attribute_Assignment)
WHERE obs.variable_category = 'AGRICULTURE'
  AND obs.variable_name CONTAINS 'WHEAT'
MATCH (obs)-[:P140_assigned_attribute_to]->(presence:E93_Presence)
MATCH (presence)-[:P7_took_place_at]->(place:E53_Place)
MATCH (presence)-[:P164_is_temporally_specified_by]->(period:E4_Period {year: 1911})
MATCH (place)-[:P89_falls_within]->(cd:E53_Place {place_type: 'CD', province: 'SK'})
RETURN cd.name, sum(obs.value_numeric) AS total_wheat
ORDER BY total_wheat DESC
```

## Data Quality Considerations

### 1. Missing Data
- Not all variables available in all years
- Use master variables file to validate
- Store NULL/missing differently than 0

### 2. Unit Consistency
- Some variables change units across years
- Always store unit with observation
- Normalize when comparing across years

### 3. Geographic Changes
- CSDs split/merge between censuses
- Use spatial temporal links to aggregate
- Be careful with longitudinal comparisons

### 4. Variable Name Standardization
- Column names vary: `POP_TOT_1911` vs `POP_TOT_1901`
- Strip year suffix for variable_name
- Store original column in source_table metadata

## Implementation Script Structure

```
scripts/
└── build_census_observations.py
    ├── load_master_variables()      # Read variable definitions
    ├── create_variable_types()      # Generate E55_Type nodes
    ├── process_year_tables()        # For each year:
    │   ├── read_all_tables()        #   - V1T1, V2T2, V2T7, etc.
    │   ├── create_observations()    #   - Create E13 nodes
    │   └── link_to_presence()       #   - Match to TCPUID
    └── export_neo4j_csvs()          # Write LOAD CSV files
```

## Output Statistics (Estimated)

### For 1911 Census
- **E13_Attribute_Assignment nodes**: ~200,000 observations
  - 3,825 CSDs × 50 variables average
- **E55_Type nodes**: ~500 unique variable types
- **P140 relationships**: ~200,000 (one per observation)
- **P4 relationships**: ~200,000 (one per observation)
- **P2 relationships**: ~200,000 (one per observation)

### All Years (1851-1921)
- **E13_Attribute_Assignment nodes**: ~1-2 million observations
- **Total relationships**: ~3-6 million

## Integration with Existing Graph

This model **extends** the current graph:
- ✅ E53_Place nodes (already exist)
- ✅ E93_Presence nodes (already exist)
- ✅ E4_Period nodes (already exist)
- ➕ NEW: E13_Attribute_Assignment nodes
- ➕ NEW: E55_Type nodes
- ➕ NEW: P140, P4, P2 relationships

## Next Steps

1. **Build variable type taxonomy** from master variables file
2. **Write processing script** for 1911 as proof of concept
3. **Validate ID mapping** between V1T1_1911 and TCPUID_CSD_1911
4. **Generate Neo4j CSVs** for 1911 observations
5. **Test import** into Neo4j
6. **Scale to all years** (1851-1921)
7. **Add spatial aggregation** queries (CD-level rollups)

---

**References**:
- LINCS Project: https://lincsproject.ca/
- CIDOC-CRM: http://www.cidoc-crm.org/
- TCP Canada HGIS: https://www.statcan.gc.ca/en/lode/databases/hgis
