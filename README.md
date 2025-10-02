# Canadian Census Knowledge Graph

**CIDOC-CRM Compliant Linked Open Data for Historical Canadian Census (1851-1921)**

## Project Overview

This project transforms historical Canadian census data into a CIDOC-CRM compliant knowledge graph, integrating:
- **Geographic data**: Census Subdivision (CSD) and Census Division (CD) boundaries with temporal tracking
- **Census variables**: Population, demographics, agriculture, economic data (628,734+ observations)
- **Provenance**: Complete attribution to CHGIS project and Borealis repository
- **Temporal linking**: Spatial overlap analysis tracking CSD evolution across 70 years

## Data Sources

### Geospatial Boundaries
**The Canadian Historical GIS (Temporal Census Polygons)**
- **Repository**: [Borealis - Canadian Dataverse](https://borealisdata.ca/dataverse/census)
- **DOI**: https://doi.org/10.5683/SP3/PKUZJN (V1, June 2023)
- **License**: CC BY 4.0
- **Authors**: Geoff Cunfer, Rhianne Billard, Sauvelm McClean, Laurent Richard, Marc St-Hilaire
- **Project**: [The Canadian Peoples / Les populations canadiennes](https://thecanadianpeoples.com/team/)
- **Content**: Census Subdivision (CSD) and Census Division (CD) polygon boundaries for 1851-1921

### Census Aggregate Data (by year)
**The Canadian Historical GIS [Aggregate data] - Individual Years**
- **Repository**: [Borealis - Canadian Dataverse](https://borealisdata.ca/dataverse/census)
- **License**: CC BY 4.0
- **Principal Authors**: Geoff Cunfer, Rhianne Billard, Sauvelm McClean, Laurent Richard, Marc St-Hilaire
- **Project**: The Canadian Peoples / Les populations canadiennes

**Individual Year Datasets**:
- **1851**: https://doi.org/10.5683/SP3/NRPFY5 (V3, Oct 2023)
- **1861**: https://doi.org/10.5683/SP3/1I1C59 (V2, Oct 2023)
- **1871**: https://doi.org/10.5683/SP3/IYAR1W (V2, Oct 2023)
- **1881**: https://doi.org/10.5683/SP3/SFG7UI (V2, Oct 2023)
- **1891**: https://doi.org/10.5683/SP3/QA4AKE (V2, Oct 2023)
- **1901**: https://doi.org/10.5683/SP3/6XFJNU (V2, Oct 2023)
- **1911**: https://doi.org/10.5683/SP3/7ZG4XV (V2, Oct 2023)
- **1921**: https://doi.org/10.5683/SP3/JPGS9B (V2, Oct 2023)

## Current Status (October 1, 2025)

### ✅ Completed

- **Neo4j Knowledge Graph**: 1.39M nodes, 4.5M relationships fully imported and tested
  - Spatial entities: 13,714 places, 22,529 presences
  - Census observations: 666,423 measurements (1851-1901)
  - Provenance: 7 creators, 17 source files, 350 place name variants
  - Performance: Complex multi-hop queries in 2-3 seconds
- **Geospatial Environment**: Conda environment with geopandas, shapely, pyproj, fiona, rtree
- **Temporal Linking (CSDs)**: 20,737 spatial links across census years (1851-1921)
  - 17,060 high-confidence links (SAME_AS, CONTAINS, WITHIN)
  - 3,677 ambiguous links (OCR errors, complex overlaps)
- **Temporal Linking (CDs)**: 2,168 Census Division links (1851-1921)
- **P132_spatiotemporally_overlaps_with Relationships**: 18,362 temporal overlap relationships
- **Wikidata Community Extraction**: 2,897 Canadian communities fetched with PIDs
  - 514 with founding dates, 2,876 with coordinates
  - 933 with GeoNames cross-references (32.2%)
  - 17,060 CSD relationships (E93_Presence → E93_Presence)
  - 1,302 CD relationships (E93_Presence → E93_Presence) **NEW**
  - Relationship types: SAME_AS (10,066), CONTAINS (7,355), WITHIN (2,243)
- **CIDOC-CRM Spatial Model**: 110 CSV files (11.0 MB)
  - 13,135 E53_Place nodes (CSDs with names)
  - 579 E53_Place nodes (CDs)
  - 21,047 E93_Presence nodes (CSD-year instances)
  - 1,482 E93_Presence nodes (CD-year instances) **NEW**
  - 45,598 P122_borders_with relationships
  - 21,046 P89_falls_within relationships (time-scoped, E53→E53)
  - 21,047 P10_falls_within relationships (time-scoped, E93→E93) **NEW**
  - E94_Space_Primitive with centroids (lat/lon)
- **CIDOC-CRM v2.0 Census Model**: 666,423 measurements (1851-1901)
  - E16_Measurement nodes (proper measurement class)
  - E54_Dimension + E58_Measurement_Unit (value/unit separation)
  - E52_Time-Span (proper temporal linking)
  - E55_Type variable taxonomy
  - Population, age, religion, agriculture, manufacturing variables
- **OCR Correction**: 107 canonical names assigned, 3,179 intentional name changes preserved
- **Provenance Entities (FAIR-compliant)**:
  - E33_Linguistic_Object: 9 citations with DOIs
  - E30_Right: CC BY 4.0 license
  - E39_Actor: 7 creators and contributors
  - E65_Creation: Dataset creation activity (2018-2023)
  - E73_Information_Object: 9 source files
  - Provenance relationships: 24 (P67, P104, P14)
- **Name Variant Tracking**:
  - E41_Appellation: 350 appellations (207 canonical + 143 OCR variants)
  - P1_is_identified_by: 350 relationships
- **Import Documentation**: 6 comprehensive guides
  - README_CIDOC_CRM.md (spatial data - CSD presences)
  - CD_PRESENCES_IMPORT_GUIDE.md (spatial data - CD presences) **NEW**
  - README_IMPORT.md (census observations)
  - PROVENANCE_IMPORT_GUIDE.md (provenance entities)
  - E41_APPELLATION_GUIDE.md (name variants)

### 🔄 In Progress

- **Community Linking to Wikidata/GeoNames** (Oct 1, 2025)
  - ✅ Fetched 2,897 Canadian communities from Wikidata with PIDs
  - ⏳ Converting 1921 CSDs to LOD format with persistent URIs
  - ⏳ Creating `was_enumerated_as` relationships (communities → census presences)
  - See: **COMMUNITY_LINKING_PROGRESS.md**

### ⏳ Next Steps

- **Complete Community Linking**: Import community entities and link to all census years (1851-1921)
- **Linked Open Data**: Full LOD conversion with persistent URIs for all entities
- **Process 1911/1921 census observations**: Add remaining measurement data
- **RDF/TTL exports**: For LOD publication
- **Public SPARQL endpoint**: Deployment

## File Structure

```
GraphRAG_test/
├── CLAUDE.md                           # Project instructions and status
├── CENSUS_VARIABLES_CIDOC_CRM_MODEL.md # Original model (v1.0)
├── CENSUS_CIDOC_CRM_REVISED.md         # Revised model (v2.0) - CURRENT
├── README.md                           # This file
├── scripts/
│   ├── build_neo4j_cidoc_crm.py       # Spatial CIDOC-CRM generator (CSD)
│   ├── build_cd_presences.py          # CD presence generator **NEW**
│   ├── link_csd_years_spatial_v2.py   # Temporal linking (spatial)
│   ├── build_p132_overlaps.py         # Export P132 spatiotemporal overlap CSVs
│   ├── link_all_years.sh              # Batch temporal linking
│   ├── assign_canonical_names_simple.py # OCR error correction
│   └── build_census_observations.py    # Census variable processor
├── neo4j_cidoc_crm/                   # Spatial graph CSVs (110 files, 11.0 MB)
│   ├── README_CIDOC_CRM.md            # CSD presences import guide
│   ├── CD_PRESENCES_IMPORT_GUIDE.md   # CD presences import guide **NEW**
│   ├── e53_place_*.csv                # Place nodes (CSDs + CDs)
│   ├── e93_presence_*.csv             # CSD temporal presences
│   ├── e93_presence_cd_*.csv          # CD temporal presences **NEW**
│   ├── e94_space_primitive_*.csv      # CSD spatial coordinates
│   ├── e94_space_primitive_cd_*.csv   # CD spatial coordinates **NEW**
│   ├── p132_spatiotemporally_overlaps_with_csd.csv # CSD temporal overlaps (17,060)
│   ├── p132_spatiotemporally_overlaps_with_cd.csv  # CD temporal overlaps (1,302) **NEW**
│   ├── p10_csd_within_cd_presence_*.csv # CSD→CD hierarchy (21,047) **NEW**
│   └── p*_*.csv                       # Other relationships
├── neo4j_census_v2/                   # Census observations (666,423)
│   ├── README_IMPORT.md               # Census import guide
│   ├── e16_measurement_*.csv          # Measurement nodes
│   ├── e54_dimension_*.csv            # Dimension values
│   ├── e55_types.csv                  # Variable taxonomy
│   └── p*_*.csv                       # Relationships
├── year_links_output/                 # CSD temporal analysis (20,737 links)
│   ├── year_links_YYYY_YYYY.csv       # High-confidence links
│   ├── ambiguous_YYYY_YYYY.csv        # Needs review
│   └── SUMMARY_ALL_YEARS.md           # Analysis report
├── cd_links_output/                   # CD temporal analysis (2,168 links)
│   ├── cd_links_YYYY_YYYY.csv         # High-confidence links
│   ├── cd_ambiguous_YYYY_YYYY.csv     # Needs review
│   └── SUMMARY_CD_LINKS.md            # Analysis report
├── neo4j_provenance/                  # Provenance entities (27 nodes)
│   ├── PROVENANCE_IMPORT_GUIDE.md     # Import guide
│   ├── e33_linguistic_objects.csv     # Citations/DOIs (9)
│   ├── e30_rights.csv                 # License (1)
│   ├── e39_actors.csv                 # Creators (7)
│   ├── e65_creation.csv               # Creation activity (1)
│   ├── e73_information_objects_provenance.csv # Sources (9)
│   └── p*_*.csv                       # Relationships (24)
├── neo4j_appellations/                # Name variants (350 appellations)
│   ├── E41_APPELLATION_GUIDE.md       # Import guide
│   ├── e41_appellations.csv           # Appellations (207 canonical + 143 variants)
│   └── p1_is_identified_by.csv        # Relationships (350)
└── canonical_names_final.csv          # OCR corrections analysis (8,949 records)
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
- `E73_Information_Object` - Source files (GDB + Excel tables)
- `E33_Linguistic_Object` - Citations with DOIs
- `E30_Right` - License (CC BY 4.0)
- `E39_Actor` - Dataset creators and contributors
- `E65_Creation` - Dataset creation activity (2018-2023)

**Name Variant Model**:
- `E41_Appellation` - Canonical names and OCR variants
- `P1_is_identified_by` - Links places/presences to appellations

### Key Relationships

**Spatial Relationships**:
- `P166_was_a_presence_of` - Presence → Place
- `P164_is_temporally_specified_by` - Presence → Period
- `P161_has_spatial_projection` - Presence → Space Primitive
- `P89_falls_within` - Place (CSD) → Place (CD) [time-scoped, static hierarchy]
- `P10_falls_within` - Presence (CSD) → Presence (CD) [time-scoped, temporal hierarchy]
- `P122_borders_with` - Place → Place [with border length]
- `P132_spatiotemporally_overlaps_with` - Presence → Presence (temporal overlap)

**Measurement Relationships**:
- `P39_measured` - Measurement → Presence
- `P40_observed_dimension` - Measurement → Dimension
- `P91_has_unit` - Dimension → Unit
- `P4_has_time-span` - Measurement/Period → Time-Span
- `P2_has_type` - Measurement → Type

**Provenance Relationships**:
- `P67_refers_to` - Citation → Information Object
- `P104_is_subject_to` - Information Object → Right
- `P14_carried_out` - Actor → Creation
- `P70_documents` - Information Object → Measurement

**Name Variant Relationships**:
- `P1_is_identified_by` - Place/Presence → Appellation

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

## Deployment

- Neo4j VM (Arbutus/OpenStack): see `docs/NEO4J_VM_DEPLOYMENT_ARBUTUS.md` for a Docker-based setup with volumes, networking, and troubleshooting (including handling an instance stuck in Error state).

## Sample Queries

### Cypher: Find CSD Evolution

```cypher
// Track a CSD across all census years
MATCH (place:E53_Place {place_id: 'ON039029'})<-[:P166_was_a_presence_of]-(presence:E93_Presence)
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

**Source data** from The Canadian Historical GIS is licensed under CC BY 4.0:

**Geospatial Boundaries**:
- Cunfer, Geoff; Billard, Rhianne; McClean, Sauvelm; Richard, Laurent; St-Hilaire, Marc, 2023, "The Canadian Historical GIS (Temporal Census Polygons)", https://doi.org/10.5683/SP3/PKUZJN, Borealis, V1

**Census Aggregate Data** (by year):
- Cunfer, Geoff; Billard, Rhianne; McClean, Sauvelm, 2023, "The Canadian Historical GIS, 1851 [Aggregate data]", https://doi.org/10.5683/SP3/NRPFY5, Borealis, V3
- Cunfer, Geoff; Billard, Rhianne; McClean, Sauvelm, 2023, "The Canadian Historical GIS, 1861 [Aggregate data]", https://doi.org/10.5683/SP3/1I1C59, Borealis, V2
- Cunfer, Geoff; Billard, Rhianne; McClean, Sauvelm, 2023, "The Canadian Historical GIS, 1871 [Aggregate data]", https://doi.org/10.5683/SP3/IYAR1W, Borealis, V2
- Cunfer, Geoff; Billard, Rhianne; McClean, Sauvelm, 2023, "The Canadian Historical GIS, 1881 [Aggregate data]", https://doi.org/10.5683/SP3/SFG7UI, Borealis, V2
- The Canadian Peoples / Les populations canadiennes Project; Cunfer, Geoff; Billard, Rhianne; McClean, Sauvelm, 2023, "The Canadian Historical GIS, 1891 [Aggregate data]", https://doi.org/10.5683/SP3/QA4AKE, Borealis, V2
- Cunfer, Geoff; Billard, Rhianne; McClean, Sauvelm, 2023, "The Canadian Historical GIS, 1901 [Aggregate data]", https://doi.org/10.5683/SP3/6XFJNU, Borealis, V2
- Cunfer, Geoff; Richard, Laurent; St-Hilaire, Marc, 2023, "The Canadian Historical GIS, 1911 [Aggregate data]", https://doi.org/10.5683/SP3/7ZG4XV, Borealis, V2
- Cunfer, Geoff; Richard, Laurent; St-Hilaire, Marc, 2023, "The Canadian Historical GIS, 1921 [Aggregate data]", https://doi.org/10.5683/SP3/JPGS9B, Borealis, V2

## Acknowledgments

- **The Canadian Peoples / Les populations canadiennes Project**: Geoff Cunfer, Rhianne Billard, Sauvelm McClean, Laurent Richard, Marc St-Hilaire and team at https://thecanadianpeoples.com/team/
- **Borealis Repository**: Long-term data preservation
- **CIDOC-CRM Community**: Ontology guidance and standards
- **Codex**: CIDOC-CRM model review and improvements

## References

- CIDOC-CRM: http://www.cidoc-crm.org/
- LINCS Project: https://lincsproject.ca/
- Statistics Canada TCP: https://www.statcan.gc.ca/en/lode/databases/hgis
- Neo4j Graph Database: https://neo4j.com/
