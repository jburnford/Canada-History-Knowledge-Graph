# Census Observations RDF Generation

**Status**: Ready for use with census data files
**Script**: `scripts/rdf_generate_census_observations.py`
**Complements**: `canada_cidoc_places_1851_1921.ttl` (spatial/temporal structure)

## Overview

This script generates CIDOC-CRM compliant RDF for census measurements (E16_Measurement, E54_Dimension) that link to the existing spatial/temporal E93_Presence nodes. Together, they create a complete knowledge graph combining:

- **Spatial structure**: Places, boundaries, coordinates
- **Temporal structure**: Presences across census years
- **Observations**: Population, demographics, agriculture, economics

## Requirements

### Census Data Files

The script requires historical census tables in either format:
- **ZIP archives**: `1891Tables.zip`, `1901Tables.zip`, `1911Tables.zip`
- **Extracted directories**: `1891Tables/`, `1901Tables/`, `1911Tables/`

These files should contain Statistics Canada TCP historical census Excel files:
- 1891: V1T3 (population), V4T2 (agriculture), V4T3 (livestock)
- 1901: V1T7 (population and demographics)
- 1911: V1T1, V1T2, V2T2, V2T7, V2T28 (comprehensive demographics)

### Python Dependencies

- **Standard library only** for basic usage
- **Optional**: `openpyxl` for faster Excel reading from directories

```bash
# Install optional dependency
pip install openpyxl
```

## Usage

### Generate Observations for Entire Canada

```bash
# 1901 Census observations (all of Canada)
python3 scripts/rdf_generate_census_observations.py \
  --year 1901 \
  --census-data 1901Tables.zip \
  --base https://canada.census.example.org/ \
  --out generated/canada/canada_observations_1901.ttl

# 1911 Census observations (all of Canada)
python3 scripts/rdf_generate_census_observations.py \
  --year 1911 \
  --census-data 1911Tables \
  --base https://canada.census.example.org/ \
  --out generated/canada/canada_observations_1911.ttl
```

### Generate Observations for Specific Province

```bash
# Ontario 1901
python3 scripts/rdf_generate_census_observations.py \
  --year 1901 \
  --census-data 1901Tables.zip \
  --province ON \
  --out generated/canada/ontario_observations_1901.ttl

# Quebec 1911
python3 scripts/rdf_generate_census_observations.py \
  --year 1911 \
  --census-data 1911Tables \
  --province QC \
  --out generated/canada/quebec_observations_1911.ttl
```

### Batch Generation for All Years

```bash
#!/bin/bash
# generate_all_observations.sh

for year in 1891 1901 1911; do
  echo "Generating observations for ${year}..."
  python3 scripts/rdf_generate_census_observations.py \
    --year ${year} \
    --census-data ${year}Tables.zip \
    --base https://canada.census.example.org/ \
    --out generated/canada/canada_observations_${year}.ttl
done

echo "All census observations generated!"
```

## Output Structure

### Measurement Units (E58_Measurement_Unit)

```turtle
ex:unit/person a crm:E58_Measurement_Unit ; rdfs:label "person" .
ex:unit/acre a crm:E58_Measurement_Unit ; rdfs:label "acre" .
ex:unit/bushel a crm:E58_Measurement_Unit ; rdfs:label "bushel" .
ex:unit/ton a crm:E58_Measurement_Unit ; rdfs:label "ton" .
ex:unit/head a crm:E58_Measurement_Unit ; rdfs:label "head" .
ex:unit/pound a crm:E58_Measurement_Unit ; rdfs:label "pound" .
ex:unit/count a crm:E58_Measurement_Unit ; rdfs:label "count" .
```

### Measurement Types (E55_Type)

```turtle
ex:measurementType/population_total_1901 a crm:E55_Type ;
  rdfs:label "Population Total (1901)" .

ex:measurementType/pop_m_1901 a crm:E55_Type ;
  rdfs:label "Population Male (1901)" .

ex:measurementType/pop_f_1901 a crm:E55_Type ;
  rdfs:label "Population Female (1901)" .

ex:measurementType/wheat_spring_bushels_1891 a crm:E55_Type ;
  rdfs:label "Wheat Spring (1891)" .
```

### Census Measurements (E16_Measurement → E54_Dimension)

```turtle
# Population measurement for Toronto CSD in 1901
ex:measurement/ON038001_1901_population_total a crm:E16_Measurement ;
  crm:P39_measured ex:presence/ON038001_1901 ;
  crm:P2_has_type ex:measurementType/population_total_1901 ;
  crm:P40_observed_dimension ex:dimension/ON038001_1901_population_total_dim ;
  crm:P4_has_time-span ex:period/CENSUS_1901 .

ex:dimension/ON038001_1901_population_total_dim a crm:E54_Dimension ;
  crm:P91_has_unit ex:unit/person ;
  crm:P90_has_value "208040"^^xsd:integer .
```

## Integration with Spatial/Temporal RDF

### Combined Query: Place + Temporal + Observations

```sparql
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX ex: <https://canada.census.example.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

# Find population growth for Toronto across census years
SELECT ?year ?population
WHERE {
  # Get all presences of Toronto
  ex:place/ON038001 ^crm:P166_was_a_presence_of ?presence .

  # Get census year
  ?presence crm:P164_is_temporally_specified_by ?period .
  ?period ex:year ?year .

  # Get population measurement
  ?measurement crm:P39_measured ?presence ;
              crm:P2_has_type ?type ;
              crm:P40_observed_dimension ?dim .

  ?type rdfs:label ?typeLabel .
  FILTER(CONTAINS(?typeLabel, "Population Total"))

  ?dim crm:P90_has_value ?population .
}
ORDER BY ?year
```

### Query: Agricultural Production by Region

```sparql
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX ex: <https://canada.census.example.org/>
PREFIX geo: <http://www.w3.org/2003/01/geo/wgs84_pos#>

# Find wheat production in Saskatchewan 1911
SELECT ?placeName ?wheatBushels ?lat ?lon
WHERE {
  # Get all 1911 presences
  ?presence crm:P164_is_temporally_specified_by ex:period/CENSUS_1911 ;
           crm:P166_was_a_presence_of ?place .

  # Get place info
  ?place rdfs:label ?placeName ;
        ex:province "SK" .

  # Get coordinates
  ?presence crm:P161_has_spatial_projection ?space .
  ?space geo:lat ?lat ; geo:long ?lon .

  # Get wheat measurement
  ?measurement crm:P39_measured ?presence ;
              crm:P2_has_type ?type ;
              crm:P40_observed_dimension ?dim .

  ?type rdfs:label ?typeLabel .
  FILTER(CONTAINS(?typeLabel, "Wheat"))

  ?dim crm:P90_has_value ?wheatBushels .
}
ORDER BY DESC(?wheatBushels)
LIMIT 20
```

### Query: Demographics with Spatial Context

```sparql
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX ex: <https://canada.census.example.org/>

# Find male/female population ratio in 1901
SELECT ?placeName ?male ?female
       (?male + ?female AS ?total)
       (ROUND(?male * 100.0 / (?male + ?female)) AS ?malePercent)
WHERE {
  ?presence crm:P164_is_temporally_specified_by ex:period/CENSUS_1901 ;
           crm:P166_was_a_presence_of ?place .

  ?place rdfs:label ?placeName .

  # Male population
  ?measM crm:P39_measured ?presence ;
        crm:P2_has_type ex:measurementType/pop_m_1901 ;
        crm:P40_observed_dimension ?dimM .
  ?dimM crm:P90_has_value ?male .

  # Female population
  ?measF crm:P39_measured ?presence ;
        crm:P2_has_type ex:measurementType/pop_f_1901 ;
        crm:P40_observed_dimension ?dimF .
  ?dimF crm:P90_has_value ?female .

  FILTER(?male + ?female > 1000)  # Only places with 1000+ people
}
ORDER BY DESC(?total)
LIMIT 50
```

## Auto-Detection Features

### Measurement Column Detection

The script automatically:
1. Scans all columns in census tables
2. Identifies numeric columns with data
3. Skips metadata columns (ROW_ID, PR, CD_NO, CSD_NO, etc.)
4. Generates measurement types from variable names

### Unit Inference

Units are inferred from column names and labels:

| Pattern | Unit | Examples |
|---------|------|----------|
| `POP*`, `POPULATION` | person | POP_TOT_1901, POPULATION |
| `*_ACRE`, `ACRE` | acre | WHT_AC, HAY_AREA_ACRES |
| `*_BU`, `BUSHEL` | bushel | OAT_BU, WHEAT_BUSHELS |
| `*_LB`, `POUND` | pound | BUTTER_LB, CHEESE_POUNDS |
| `*TON*` | ton | HAY_TONS |
| `CATTLE`, `SHEEP`, `SWINE`, `COW` | head | MILK_COWS, OTHER_CATTLE |
| `HOUSE*`, `FAMIL*` | count | HOUSES_1901, FAMILIES |
| Default | count | Other numeric measures |

## Data Coverage by Year

### 1891 Census
**Tables**: V1T3 (population), V4T2 (agriculture), V4T3 (livestock)

**Measurements**:
- Population total, male, female
- Families count
- Wheat (spring, fall), oats, hay, potatoes (area + production)
- Livestock: milk cows, cattle, sheep, swine
- Dairy: butter, cheese production

**CSDs**: ~2,500

### 1901 Census
**Tables**: V1T7 (population and demographics)

**Measurements**:
- Population total, male, female
- Houses, families count

**CSDs**: ~3,200

### 1911 Census
**Tables**: V1T1, V1T2, V2T2, V2T7, V2T28 (comprehensive)

**Measurements**:
- Population by age, sex, marital status
- Birthplace data
- Religious denominations
- Language spoken
- Housing characteristics
- Economic indicators

**CSDs**: ~3,800

## Expected Output Statistics

### 1901 Canada-wide
- **Measurements**: ~16,000 (5 measures × 3,200 CSDs)
- **Dimensions**: ~16,000
- **File size**: ~3-4 MB
- **CSDs with data**: ~3,200

### 1911 Canada-wide
- **Measurements**: ~150,000 (40+ measures × 3,800 CSDs)
- **Dimensions**: ~150,000
- **File size**: ~25-30 MB
- **CSDs with data**: ~3,800

### Province-specific (Ontario 1911)
- **Measurements**: ~40,000
- **Dimensions**: ~40,000
- **File size**: ~7-8 MB
- **CSDs with data**: ~1,000

## Combining Multiple RDF Files

### Load into Triple Store

```bash
# Load spatial/temporal structure first
curl -X POST \
  -H "Content-Type: text/turtle" \
  --data-binary @canada_cidoc_places_1851_1921.ttl \
  http://localhost:3030/canada/data

# Then load observations for each year
for file in canada_observations_*.ttl; do
  echo "Loading $file..."
  curl -X POST \
    -H "Content-Type: text/turtle" \
    --data-binary @$file \
    http://localhost:3030/canada/data
done
```

### Merge RDF Files

```bash
# Concatenate multiple TTL files (remove duplicate prefixes manually)
cat canada_cidoc_places_1851_1921.ttl > combined.ttl
tail -n +10 canada_observations_1891.ttl >> combined.ttl
tail -n +10 canada_observations_1901.ttl >> combined.ttl
tail -n +10 canada_observations_1911.ttl >> combined.ttl
```

## Troubleshooting

### Issue: "Sheet not found"
**Cause**: Census table sheet name mismatch
**Solution**: Check sheet names in Excel file, update `build_dataset_configs()` in script

### Issue: "No numeric columns found"
**Cause**: Data columns not detected or all empty
**Solution**: Verify Excel file has data, check column names against skip list

### Issue: "TCPUID not extracted"
**Cause**: Row ID format doesn't match expected pattern
**Solution**: Verify ID column format in census table (should be 8-char TCPUID)

### Issue: "No measurements generated"
**Cause**: Province filter doesn't match or CSD_NO = 0 (aggregates)
**Solution**: Check province code, verify CSD_NO column has valid values

## Future Enhancements

1. **Additional Census Years**: Extend to 1851, 1861, 1871, 1881
2. **Custom Measure Selection**: Allow filtering specific measurements
3. **Aggregation Support**: Generate CD-level and province-level aggregates
4. **Variable Documentation**: Include variable definitions and sources
5. **Quality Indicators**: Add data quality flags (estimated, incomplete, etc.)

## References

- **CIDOC-CRM E16_Measurement**: http://www.cidoc-crm.org/Entity/E16-Measurement/version-7.1.1
- **CIDOC-CRM E54_Dimension**: http://www.cidoc-crm.org/Entity/E54-Dimension/version-7.1.1
- **Statistics Canada TCP**: https://www.statcan.gc.ca/en/lode/databases/hgis

---

**Script**: `scripts/rdf_generate_census_observations.py`
**Version**: 1.0
**Date**: November 5, 2025
