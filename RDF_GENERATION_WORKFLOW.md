# RDF Generation Workflow for Canadian Census Data

**Date**: November 5, 2025
**Status**: Complete - Ready for use with census data files

## Overview

This repository now contains a complete pipeline for generating CIDOC-CRM compliant RDF from Canadian census spatial and observational data. The workflow consists of two main scripts that work together to create a comprehensive historical knowledge graph.

## Pipeline Architecture

```
TCP Geospatial Data (GDB)
         +
Census Tables (ZIP/XLSX)
         |
         v
   [Data Processing]
         |
         +-------------------+
         |                   |
         v                   v
  Spatial/Temporal      Observations
   Structure RDF          RDF
         |                   |
    (25 MB TTL)         (3-30 MB TTL)
         |                   |
         +-------------------+
                 |
                 v
         Combined RDF Graph
    (Spatial + Temporal + Census)
                 |
                 v
           Triple Store
      (Fuseki/GraphDB/Blazegraph)
                 |
                 v
         SPARQL Queries
    (Demographics, Agriculture,
     Spatial Analysis)
```

## Step 1: Generate Spatial/Temporal Structure

### Script: `rdf_from_cidoc_csv.py`

**Input**: CIDOC-CRM CSV files from `neo4j_cidoc_crm/` directory

**Output**: `generated/canada/canada_cidoc_places_1851_1921.ttl`

**Contents**:
- E53_Place: 5,585 places (5,363 CSDs + 222 CDs)
- E4_Period: 8 census years (1851-1921)
- E93_Presence: 20,811 temporal manifestations
- E94_Space_Primitive: 20,811 centroids (WGS84)
- P166/P164/P161/P89/P122/P132: 150,000+ relationships

**Command**:
```bash
python3 scripts/rdf_from_cidoc_csv.py \
  --csv-dir neo4j_cidoc_crm \
  --canonical canonical_names_final.csv \
  --base https://canada.census.example.org/ \
  --out generated/canada/canada_cidoc_places_1851_1921.ttl
```

**Features**:
- Includes 476 canonical name corrections for OCR errors
- Preserves 3,179 intentional name changes
- Full temporal chain linking (17,060 P132 relationships)
- Border adjacency with measured lengths
- Administrative hierarchy (CSD within CD)

### Documentation
See: `generated/canada/README_RDF.md`

## Step 2: Generate Census Observations

### Script: `rdf_generate_census_observations.py`

**Input**: Historical census tables (ZIP or extracted)
- 1891Tables.zip (or 1891Tables/)
- 1901Tables.zip (or 1901Tables/)
- 1911Tables.zip (or 1911Tables/)

**Output**: Year-specific observation files
- `canada_observations_1891.ttl` (~8 measures × 2,500 CSDs)
- `canada_observations_1901.ttl` (~5 measures × 3,200 CSDs)
- `canada_observations_1911.ttl` (~40 measures × 3,800 CSDs)

**Contents**:
- E16_Measurement: Census observations
- E54_Dimension: Values with units
- E58_Measurement_Unit: person, acre, bushel, ton, head, pound, count
- E55_Type: Measurement type definitions
- Links to E93_Presence nodes via P39_measured

**Commands**:
```bash
# Generate for all of Canada
python3 scripts/rdf_generate_census_observations.py \
  --year 1901 \
  --census-data 1901Tables.zip \
  --base https://canada.census.example.org/ \
  --out generated/canada/canada_observations_1901.ttl

# Generate for specific province
python3 scripts/rdf_generate_census_observations.py \
  --year 1911 \
  --census-data 1911Tables \
  --province ON \
  --out generated/canada/ontario_observations_1911.ttl
```

**Features**:
- Auto-detects measurement columns
- Infers units from column names/labels
- Filters by province (optional)
- Handles ZIP archives or extracted directories
- Supports openpyxl for faster reading (optional)

### Documentation
See: `generated/canada/README_CENSUS_OBSERVATIONS.md`

## Step 3: Load into Triple Store

### Apache Jena Fuseki

```bash
# Start Fuseki server
fuseki-server --update --mem /canada

# Load spatial/temporal structure
curl -X POST \
  -H "Content-Type: text/turtle" \
  --data-binary @generated/canada/canada_cidoc_places_1851_1921.ttl \
  http://localhost:3030/canada/data

# Load observations for each year
for year in 1891 1901 1911; do
  curl -X POST \
    -H "Content-Type: text/turtle" \
    --data-binary @generated/canada/canada_observations_${year}.ttl \
    http://localhost:3030/canada/data
done
```

### GraphDB

1. Create repository "canada-census"
2. Import > RDF > Upload RDF files
3. Select all generated TTL files
4. Enable inference (optional for CIDOC-CRM reasoning)

### Blazegraph

```bash
# Load all files
for file in generated/canada/*.ttl; do
  curl -X POST \
    -H "Content-Type: text/turtle" \
    --data-binary @$file \
    http://localhost:9999/blazegraph/namespace/kb/sparql
done
```

## Step 4: Query the Knowledge Graph

### Example Queries

#### 1. Population Growth Over Time

```sparql
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX ex: <https://canada.census.example.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?placeName ?year ?population
WHERE {
  # Get place
  ?place rdfs:label ?placeName ;
         ex:province "ON" .

  # Get all presences
  ?place ^crm:P166_was_a_presence_of ?presence .

  # Get year
  ?presence crm:P164_is_temporally_specified_by ?period .
  ?period ex:year ?year .

  # Get population
  ?measurement crm:P39_measured ?presence ;
              crm:P2_has_type ?type ;
              crm:P40_observed_dimension ?dim .

  ?type rdfs:label ?typeLabel .
  FILTER(CONTAINS(?typeLabel, "Population Total"))

  ?dim crm:P90_has_value ?population .

  FILTER(?population > 10000)  # Cities only
}
ORDER BY ?placeName ?year
```

#### 2. Agricultural Production with Spatial Context

```sparql
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX ex: <https://canada.census.example.org/>
PREFIX geo: <http://www.w3.org/2003/01/geo/wgs84_pos#>

SELECT ?placeName ?wheatBushels ?lat ?lon
WHERE {
  # 1891 presences in Manitoba
  ?presence crm:P164_is_temporally_specified_by ex:period/CENSUS_1891 ;
           crm:P166_was_a_presence_of ?place .

  ?place rdfs:label ?placeName ;
        ex:province "MB" .

  # Get coordinates
  ?presence crm:P161_has_spatial_projection ?space .
  ?space geo:lat ?lat ; geo:long ?lon .

  # Get wheat production
  ?measurement crm:P39_measured ?presence ;
              crm:P2_has_type ?type ;
              crm:P40_observed_dimension ?dim .

  ?type rdfs:label ?typeLabel .
  FILTER(CONTAINS(?typeLabel, "Wheat"))

  ?dim crm:P90_has_value ?wheatBushels .
}
ORDER BY DESC(?wheatBushels)
LIMIT 50
```

#### 3. Temporal Continuity + Demographics

```sparql
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX ex: <https://canada.census.example.org/>

# Find places that merged between 1891-1901 with population data
SELECT ?place1Name ?place2Name ?pop1891 ?pop1901
WHERE {
  # Find CONTAINS relationship (place1 was split from place2)
  ?pres1891 crm:P132_spatiotemporally_overlaps_with ?pres1901 .
  ?pres1891 ex:overlapType "CONTAINS" .

  # Get place names
  ?pres1891 crm:P166_was_a_presence_of ?place1 .
  ?place1 rdfs:label ?place1Name .

  ?pres1901 crm:P166_was_a_presence_of ?place2 .
  ?place2 rdfs:label ?place2Name .

  # Get 1891 population
  ?meas1891 crm:P39_measured ?pres1891 ;
           crm:P2_has_type ex:measurementType/population_total_1891 ;
           crm:P40_observed_dimension ?dim1891 .
  ?dim1891 crm:P90_has_value ?pop1891 .

  # Get 1901 population
  ?meas1901 crm:P39_measured ?pres1901 ;
           crm:P2_has_type ex:measurementType/population_total_1901 ;
           crm:P40_observed_dimension ?dim1901 .
  ?dim1901 crm:P90_has_value ?pop1901 .
}
ORDER BY DESC(?pop1891)
```

#### 4. Gender Ratio Analysis

```sparql
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX ex: <https://canada.census.example.org/>

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

  FILTER(?male + ?female > 1000)
}
ORDER BY DESC(?total)
```

## Data Quality

### Canonical Names Applied
- **476 OCR corrections** applied via `canonical_names_final.csv`
- Spelling variants, apostrophe variants, similar names
- **3,179 intentional name changes** preserved (Berlin→Kitchener, ward reorganizations)

### Temporal Continuity
- **17,060 spatiotemporal overlaps** across adjacent census years
- Relationship types: SAME_AS, CONTAINS, WITHIN, OVERLAPS
- IoU metrics and containment fractions included

### Measurement Coverage

| Year | CSDs | Measurement Types | Total Observations |
|------|------|------------------|--------------------|
| 1891 | 2,509 | 8 (pop) + 7 (agri) + 6 (livestock) | ~50,000 |
| 1901 | 3,221 | 5 (demographics) | ~16,000 |
| 1911 | 3,825 | 40+ (comprehensive) | ~150,000 |

## Testing

### Run Unit Tests

```bash
python3 scripts/test_observations_rdf.py
```

**Tests verify**:
- TCPUID extraction from row IDs
- Unit inference from column names
- RDF structure generation
- Dataset configurations

All tests passing ✓

## File Structure

```
Canada-History-Knowledge-Graph/
├── scripts/
│   ├── rdf_from_cidoc_csv.py              # Step 1: Spatial/temporal RDF
│   ├── rdf_generate_census_observations.py # Step 2: Observations RDF
│   └── test_observations_rdf.py           # Unit tests
├── generated/
│   └── canada/
│       ├── canada_cidoc_places_1851_1921.ttl     # 25 MB spatial/temporal
│       ├── canada_observations_1891.ttl           # ~2 MB observations
│       ├── canada_observations_1901.ttl           # ~3 MB observations
│       ├── canada_observations_1911.ttl           # ~25 MB observations
│       ├── README_RDF.md                          # Spatial/temporal docs
│       └── README_CENSUS_OBSERVATIONS.md          # Observations docs
├── neo4j_cidoc_crm/                       # 67 CSV files (input for step 1)
├── canonical_names_final.csv              # OCR corrections
└── year_links_output/                     # Temporal links
```

## Future Enhancements

1. **Additional Census Years**: Extend observations to 1851, 1861, 1871, 1881
2. **Enhanced Measurements**: Add E67_Birth for vital statistics
3. **Institutional Data**: Link E53_Places to churches, schools, hospitals
4. **Transportation Networks**: Railway E53_Places and connections
5. **Historical Events**: E5_Event nodes for incorporation, annexation
6. **Aggregation Support**: Generate CD and province-level summaries
7. **Quality Indicators**: Add data quality flags and confidence scores

## References

- **CIDOC-CRM**: http://www.cidoc-crm.org/
- **WGS84 Geo**: http://www.w3.org/2003/01/geo/wgs84_pos#
- **Statistics Canada TCP**: https://www.statcan.gc.ca/en/lode/databases/hgis
- **SPARQL 1.1**: https://www.w3.org/TR/sparql11-query/
- **Apache Jena Fuseki**: https://jena.apache.org/documentation/fuseki2/
- **GraphDB**: https://graphdb.ontotext.com/
- **Blazegraph**: https://blazegraph.com/

## Support

For issues or questions:
1. Check documentation in `generated/canada/`
2. Review unit tests in `scripts/test_observations_rdf.py`
3. Verify census data file format and location
4. Ensure CIDOC-CRM CSV files are generated first

---

**Pipeline Status**: ✅ Complete and tested
**Last Updated**: November 5, 2025
**Scripts Version**: 1.0
