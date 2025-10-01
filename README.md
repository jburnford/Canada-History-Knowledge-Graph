# Canadian Census Knowledge Graph

**CIDOC-CRM Compliant Linked Open Data for Historical Canadian Census (1851-1921)**

## Project Overview

This project transforms historical Canadian census data into a CIDOC-CRM compliant knowledge graph, integrating:
- **Geographic data**: Census Subdivision (CSD) and Census Division (CD) boundaries with temporal tracking
- **Census variables**: Population, demographics, agriculture, economic data (628,734+ observations)
- **Provenance**: Complete attribution to CHGIS project and Borealis repository
- **Temporal linking**: Spatial overlap analysis tracking CSD evolution across 70 years

## Data Source

**The Canadian Historical GIS (CHGIS)**
- **Repository**: [Borealis - Canadian Dataverse](https://borealisdata.ca/dataverse/census)
- **DOI**: https://doi.org/10.5683/SP3/PKUZJN
- **License**: CC BY 4.0
- **Version**: V1 (June 2023)

**Principal Investigators**: Marvin McInnis, Michael Dawson, J.C. Herbert Emery, Mary MacKinnon, Marc St-Hilaire, Corinne Stainton, John Warkentin, Peter Waite

## Current Status (September 30, 2025)

### ✅ Completed

- **Geospatial Environment**: Conda environment with geopandas, shapely, pyproj, fiona, rtree
- **Temporal Linking**: 20,737 spatial links across census years (1851-1921)
  - 17,060 high-confidence links (SAME_AS, CONTAINS, WITHIN)
  - 3,677 ambiguous links (OCR errors, complex overlaps)
- **CIDOC-CRM Spatial Model**: 67 CSV files (9.7 MB)
  - 13,135 E53_Place nodes (CSDs)
  - 21,047 E93_Presence nodes (CSD-year instances)
  - 45,598 P122_borders_with relationships
  - E94_Space_Primitive with centroids (lat/lon)
- **OCR Correction**: 107 canonical names assigned, 3,179 intentional name changes preserved
- **Census Observations (1851-1891)**: 628,734 observations processed
  - E13_Attribute_Assignment nodes (v1.0 - to be upgraded to E16_Measurement)
  - Population, age, religion, agriculture, manufacturing variables

### 🔄 In Progress

- **CIDOC-CRM v2.0 Model**: Revised per Codex feedback
  - E16_Measurement (proper measurement class)
  - E54_Dimension + E58_Measurement_Unit (value/unit separation)
  - E52_Time-Span (proper temporal linking)
  - E73_Information_Object + E33_Linguistic_Object (full provenance)
  - E30_Right + E39_Actor (licensing and attribution)

### ⏳ Todo

- Update `build_census_observations.py` to v2.0 structure
- Process 1911/1921 data (multi-layer GDB issue)
- Generate RDF/TTL exports for LOD publication
- Neo4j import and validation
- Public SPARQL endpoint deployment

## File Structure

```
GraphRAG_test/
├── CLAUDE.md                           # Project instructions and status
├── CENSUS_VARIABLES_CIDOC_CRM_MODEL.md # Original model (v1.0)
├── CENSUS_CIDOC_CRM_REVISED.md         # Revised model (v2.0) - CURRENT
├── README.md                           # This file
├── scripts/
│   ├── build_neo4j_cidoc_crm.py       # Spatial CIDOC-CRM generator
│   ├── link_csd_years_spatial_v2.py   # Temporal linking (spatial)
│   ├── link_all_years.sh              # Batch temporal linking
│   ├── assign_canonical_names_simple.py # OCR error correction
│   └── build_census_observations.py    # Census variable processor
├── neo4j_cidoc_crm/                   # Spatial graph CSVs (67 files)
│   ├── README_CIDOC_CRM.md            # Import guide
│   ├── e53_place_*.csv                # Place nodes
│   ├── e93_presence_*.csv             # Temporal presences
│   ├── e94_space_primitive_*.csv      # Spatial coordinates
│   └── p*_*.csv                       # Relationships
├── year_links_output/                 # Temporal links (20,737 links)
│   ├── year_links_YYYY_YYYY.csv       # High-confidence links
│   ├── ambiguous_YYYY_YYYY.csv        # Needs review
│   └── SUMMARY_ALL_YEARS.md           # Analysis report
└── canonical_names_final.csv          # OCR corrections (107 CSDs)
```

## Data Model

### CIDOC-CRM Classes Used

**Spatial Model**:
- `E53_Place` - Persistent place entities (CSDs, CDs)
- `E93_Presence` - Temporal manifestations ("Westmeath in 1901")
- `E94_Space_Primitive` - Geographic coordinates (centroids)
- `E4_Period` - Census years

**Measurement Model (v2.0)**:
- `E16_Measurement` - Census observations
- `E54_Dimension` - Measured values
- `E58_Measurement_Unit` - Units (persons, acres, dollars)
- `E52_Time-Span` - Temporal extents
- `E55_Type` - Variable taxonomy (population, age, religion, agriculture)

**Provenance Model**:
- `E73_Information_Object` - Source Excel files
- `E33_Linguistic_Object` - Citations and DOI
- `E30_Right` - License (CC BY 4.0)
- `E39_Actor` - Creators (8 PIs + CHGIS team)
- `E65_Creation` - Dataset creation activity

### Key Relationships

- `P39_measured` - Measurement → Presence
- `P40_observed_dimension` - Measurement → Dimension
- `P91_has_unit` - Dimension → Unit
- `P4_has_time-span` - Measurement/Period → Time-Span
- `P70_documents` - Information Object → Measurement
- `P67_refers_to` - Citation → Information Object
- `P104_is_subject_to` - Information Object → Right

## Installation

### Requirements

```bash
# Python 3.12+
conda create -n geo python=3.12
conda activate geo

# Geospatial packages
conda install -c conda-forge geopandas shapely pyproj fiona rtree gdal

# Data processing
pip install pandas rapidfuzz openpyxl

# Graph database
# Neo4j 4.4+ or Docker container
```

### Neo4j Setup

```bash
# UK Parliamentary data instance
docker run -d \
  --name neo4j-uk-graphrag \
  -p 7475:7474 -p 7688:7687 \
  -e NEO4J_AUTH=neo4j/ukgraph123 \
  neo4j:4.4

# Canadian Census instance
docker run -d \
  --name neo4j-canada-census \
  -p 7476:7474 -p 7689:7687 \
  -e NEO4J_AUTH=neo4j/canadacensus123 \
  neo4j:4.4
```

## Usage

### Generate Temporal Links

```bash
conda activate geo

# Single year pair
python scripts/link_csd_years_spatial_v2.py \
  --gdb TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306.gdb \
  --year-from 1901 --year-to 1911 \
  --out year_links_output

# All years (1851→1921)
./scripts/link_all_years.sh
```

### Generate Spatial CIDOC-CRM Data

```bash
python scripts/build_neo4j_cidoc_crm.py \
  --gdb TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306.gdb \
  --years 1851,1861,1871,1881,1891,1901,1911,1921 \
  --out neo4j_cidoc_crm
```

### Process Census Variables

```bash
# 1851-1891 (working)
python scripts/build_census_observations.py \
  --years 1891,1881,1871,1861,1851 \
  --out neo4j_census_observations

# 1901 (working)
python scripts/build_census_observations.py \
  --years 1901 \
  --out neo4j_census_observations

# 1911, 1921 (multi-layer GDB - needs investigation)
```

### Correct OCR Errors

```bash
python scripts/assign_canonical_names_simple.py \
  --links-dir year_links_output \
  --min-similarity 70 \
  --out canonical_names_final.csv
```

## Sample Queries

### Cypher: Find CSD Evolution

```cypher
// Track a CSD across all census years
MATCH (place:E53_Place {place_id: 'ON039029'})<-[:P7_took_place_at]-(presence:E93_Presence)
MATCH (presence)-[:P164_is_temporally_specified_by]->(period:E4_Period)
MATCH (presence)-[:P161_has_spatial_projection]->(space:E94_Space_Primitive)
RETURN period.year, presence.area_sqm, space.latitude, space.longitude
ORDER BY period.year
```

### Cypher: Population Growth with Provenance

```cypher
MATCH (measurement:E16_Measurement)-[:P39_measured]->(presence:E93_Presence)
MATCH (measurement)-[:P2_has_type]->(:E55_Type {type_id: 'VAR_POP_TOTAL'})
MATCH (measurement)-[:P40_observed_dimension]->(dim:E54_Dimension)
MATCH (measurement)-[:P70i_is_documented_in]->(source:E73_Information_Object)
MATCH (source)<-[:P67_refers_to]-(citation:E33_Linguistic_Object)
RETURN presence.presence_id, dim.value, source.label, citation.doi
```

## Data Statistics

### Spatial Coverage

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

### Census Observations

| Year | Observations | CSDs | Variables | Categories |
|------|--------------|------|-----------|------------|
| 1851 | 150,266      | 903  | 298       | 8          |
| 1861 | 164,246      | 1,162| 242       | 8          |
| 1871 | 36,860       | 1,774| 138       | 10         |
| 1881 | 75,793       | 2,136| 59        | 6          |
| 1891 | 201,569      | 2,474| 90        | 5          |
| 1901 | 37,689       | 3,184| 14        | 3          |
| **Total** | **666,423** | - | - | - |

## Contributing

This project is part of academic research. For questions or collaboration:
- Repository: (Add GitHub URL)
- Issues: (Add GitHub Issues URL)
- Contact: (Add contact information)

## License

This project code is licensed under MIT License.

**Source data** from CHGIS is licensed under CC BY 4.0:
- Citation: McInnis, Marvin; Dawson, Michael; Emery, J.C. Herbert; Mackinnon, Mary; St-Hilaire, Marc; Stainton, Corinne; Warkentin, John; Waite, Peter, 2023, "The Canadian Historical GIS (CHGIS)", https://doi.org/10.5683/SP3/PKUZJN, Borealis, V1

## Acknowledgments

- **CHGIS Project Team**: 8 Principal Investigators from Canadian universities
- **Borealis Repository**: Long-term data preservation
- **CIDOC-CRM Community**: Ontology guidance and standards
- **Codex**: CIDOC-CRM model review and improvements

## References

- CIDOC-CRM: http://www.cidoc-crm.org/
- LINCS Project: https://lincsproject.ca/
- Statistics Canada TCP: https://www.statcan.gc.ca/en/lode/databases/hgis
- Neo4j Graph Database: https://neo4j.com/
