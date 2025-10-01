# GraphRAG Project Documentation

## Project Overview
Multi-database GraphRAG system combining:
- **UK Parliamentary data** (Hansard) in Neo4j
- **Canadian Census geospatial data** (TCP polygons + historical census)
- **Geospatial analysis** for historical census subdivision linking

## Environment Setup

### Geospatial Environment (COMPLETED ✅)
- **Location**: `/home/jic823/miniforge3/envs/geo`
- **Activation**: `conda activate geo`
- **Packages**: geopandas, shapely, pyproj, fiona, rtree, gdal, pandas, rapidfuzz
- **Test Command**: `python -c "import geopandas, shapely, pyproj, fiona, rtree, pandas, rapidfuzz; print('All working!')"`

### Neo4j Instances (COMPLETED ✅)

#### UK GraphRAG Instance
- **Container**: `neo4j-uk-graphrag`
- **Browser**: http://localhost:7475
- **Bolt**: bolt://localhost:7688
- **Credentials**: neo4j/ukgraph123
- **Status**: ✅ Running with Hansard Parliamentary data
- **Data**: 6,450 MPs, 1,121 constituencies, 34 parties, 17 offices
- **Start Command**: `docker start neo4j-uk-graphrag`

#### Saskatchewan Instance  
- **Container**: `neo4j-saskatchewan`
- **Browser**: http://localhost:7476
- **Bolt**: bolt://localhost:7689
- **Credentials**: neo4j/saskgraph123
- **Status**: ❌ Empty (no data loaded)

## Data Locations

### Canadian Census Geospatial Data (TCP)
```
TCP_CANADA_CSD_202306/
├── TCP_CANADA_CSD_202306/
    ├── TCP_CANADA_CSD_202306.gdb/          # FileGDB with polygon data
    ├── TCP_CANADA_HGIS_CSD_202306.pdf      # Documentation
    └── LPC_CANADA_HGIS_CSD_202306.pdf      # Legend/documentation
```

### Historical Census Tables (ZIP files - NOT EXTRACTED YET)
```
1851Tables.zip    # Contains 1851 census subdivision data
1861Tables.zip    # Contains 1861 census subdivision data  
1871Tables.zip    # Contains 1871 census subdivision data
1881Tables.zip    # Contains 1881 census subdivision data
1891Tables.zip    # Contains 1891 census subdivision data
1901Tables.zip    # Contains 1901 census subdivision data
1911Tables.zip    # Contains 1911 census subdivision data
1921Tables.zip    # Contains 1921 census subdivision data
```

### 1911 Data (EXTRACTED)
```
1911Tables/1911/
├── 1911_V1T1_PUB_202306.xlsx           # Population by census subdivision
├── 1911_V1T2_PUB_202306.xlsx           # Additional demographic data
├── 1911_V2T2_PUB_202306.xlsx           # Religious denominations
├── 1911_V2T7_PUB_202306.xlsx           # Birthplace data
├── 1911_V2T28_PUB_202306.xlsx          # Language data
└── TCP_CANADA_CD-CSD_Mastvar.xlsx      # Master variables crosswalk
```

### Generated Outputs
```
generated/
├── ca_1911/
│   ├── observations.csv                # Processed 1911 observations
│   └── places.csv                      # Processed 1911 places
├── canada/
│   ├── canada_all_1891_crm.ttl        # RDF triples 1891
│   ├── canada_all_1901_crm.ttl        # RDF triples 1901  
│   └── canada_all_1911_crm.ttl        # RDF triples 1911
└── sk_1911/
    ├── observations.csv                # Saskatchewan 1911 observations
    └── places.csv                     # Saskatchewan 1911 places
```

## Scripts Available

### CSD Temporal Linking (PRODUCTION - September 30, 2025)

#### Main Script: `link_csd_years_spatial_v2.py`
**Purpose**: Link Census Subdivisions across years using pure spatial overlap analysis (no Excel files needed)

**Key Features**:
- Uses only GDB polygon layers - all data from geometry + attributes
- Handles column naming inconsistencies (1891, 1911 use uppercase NAME_CD/NAME_CSD)
- Spatial index for efficient overlap detection
- IoU + containment fraction analysis for relationship classification

**Relationship Types**:
- **SAME_AS**: High overlap (IoU > 0.98), same CSD over time
- **WITHIN**: CSD contained in another (city split from larger area)
- **CONTAINS**: CSD contains others (amalgamation)
- **OVERLAPS**: Partial overlap (boundary changes, Western province redrawing)

**Single Year Pair**:
```bash
conda activate geo
python scripts/link_csd_years_spatial_v2.py \
  --gdb TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306.gdb \
  --year-from 1901 --year-to 1911 \
  --out year_links_output
```

**All Years (1851→1921)**:
```bash
conda activate geo
./scripts/link_all_years.sh
```

**Outputs**:
- `year_links_YYYY_YYYY.csv` - High-confidence links (SAME_AS with name match, WITHIN, CONTAINS)
- `ambiguous_YYYY_YYYY.csv` - Needs review (OCR errors, complex overlaps)
- `summary_YYYY_YYYY.txt` - Statistics by relationship type

**Test Results (1901→1911)**:
- 3,221 CSDs (1901) → 3,825 CSDs (1911)
- 3,336 high-confidence links: 1,514 SAME_AS, 1,329 CONTAINS, 493 WITHIN
- 917 ambiguous: 470 SAME_AS (OCR errors), 447 OVERLAPS

**Column Name Variations**:
- 1851, 1861, 1871, 1881, 1901, 1921: `Name_CD`, `Name_CSD` (Title Case)
- 1891, 1911: `NAME_CD`, `NAME_CSD` (UPPERCASE)

### Scripts Directory
```
scripts/
├── link_csd_years_spatial_v2.py        # ✅ PRODUCTION spatial linking
├── link_all_years.sh                   # Batch process all year pairs
├── build_neo4j_cidoc_crm.py           # ✅ CIDOC-CRM Neo4j data generator
├── assign_canonical_names_simple.py   # ✅ OCR error correction
├── fix_ocr_errors_v2.py               # OCR error detection
├── build_year_links_spatial.py         # OLD (Codex version, needs Excel)
├── csd_name_crosswalk.py               # Name standardization utilities
├── parse_1911_v1t1_sk.py              # Saskatchewan 1911 parser
├── rdf_generate_pei.py                 # PEI RDF generation
├── rdf_generate_pei_all_crm.py        # PEI CRM RDF generation
├── rdf_generate_pei_irish_crm.py      # PEI Irish-specific RDF
└── xlsx_inspect_in_zip.py             # ZIP file inspection utility
```

### CIDOC-CRM Neo4j Data Generation

**Script**: `build_neo4j_cidoc_crm.py`

**Purpose**: Generate CIDOC-CRM compliant Neo4j CSV files with spatial data

**CIDOC-CRM Entities**:
- **E53_Place**: CSD and CD places (13,135 + 579 nodes)
- **E4_Period**: Census years (8 periods)
- **E93_Presence**: Temporal manifestations (21,047 nodes)
- **E94_Space_Primitive**: Centroids with lat/lon (21,047 nodes)

**CIDOC-CRM Relationships**:
- **P7_took_place_at**: Presence → Place (21,047)
- **P164_is_temporally_specified_by**: Presence → Period (21,047)
- **P161_has_spatial_projection**: Presence → Space (21,047)
- **P89_falls_within**: CSD → CD hierarchy (21,046)
- **P122_borders_with**: Border adjacency + length (45,598)

**Usage**:
```bash
conda activate geo
python scripts/build_neo4j_cidoc_crm.py \
  --gdb TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306.gdb \
  --years 1851,1861,1871,1881,1891,1901,1911,1921 \
  --out neo4j_cidoc_crm
```

**Output**: 67 CSV files (9.7 MB) ready for Neo4j LOAD CSV

**Documentation**: `neo4j_cidoc_crm/README_CIDOC_CRM.md`

### OCR Error Detection and Canonical Names

**Script**: `assign_canonical_names_simple.py`

**Purpose**: Detect OCR errors and assign canonical names using temporal consistency

**Algorithm**:
1. Build temporal chains of CSDs with perfect spatial match (IoU ≥ 0.999)
2. Find consensus name (most common across years)
3. Calculate similarity of all names to consensus
4. Apply canonical name only if names are similar (avg ≥ 70%, min ≥ 60%)
5. Preserve intentional name changes (Berlin→Kitchener, ward reorganizations)

**Usage**:
```bash
conda activate geo
python scripts/assign_canonical_names_simple.py \
  --links-dir year_links_output \
  --min-similarity 70 \
  --out canonical_names_final.csv
```

**Results**:
- **8,949 CSD-year records** analyzed
- **107 CSDs** with canonical names applied (OCR variants)
- **3,179 intentional name changes** preserved
- **5,127 single-year CSDs** (no temporal comparison)

**OCR Error Types Fixed**:
- Spelling variants: "Melvern" → "Malvern", "Nictau" → "Nictaux"
- Apostrophe variants: "Parker Cove" → "Parker's Cove"
- Similar names: "Clarendon" → "Carleton"
- Accent variants: "St. Léonard" → "St. Leonard's"

**Output File**: `canonical_names_final.csv`
- Columns: `tcpuid`, `year`, `original_name`, `canonical_name`, `should_apply`, `consensus_count`, `avg_similarity`, `reason`
- Can be joined with CIDOC-CRM data to add canonical names to E93_Presence nodes

## Current Status - CIDOC-CRM DATA + OCR CORRECTIONS READY FOR NEO4J

### Infrastructure Status
- ✅ Geospatial environment ready
- ✅ Neo4j UK GraphRAG populated and working
- ✅ Temporal linking complete (20,737 links across 1851-1921)
- ✅ CIDOC-CRM data generated (67 CSV files, 9.7 MB)
- ✅ OCR error detection and canonical names assigned (1,757 errors detected, 107 corrected)
- ⏳ Next: Load CIDOC-CRM data into Neo4j with canonical names

### Completed Milestones (September 30, 2025)
- ✅ **Temporal linking**: 17,060 high-confidence + 3,677 ambiguous links
- ✅ **CIDOC-CRM model**: 13,135 CSD places, 21,047 presences, 45,598 borders
- ✅ **Spatial data**: Centroids (lat/lon) + border adjacency with lengths
- ✅ **OCR corrections**: 107 canonical names assigned, 3,179 intentional name changes preserved
- ✅ **Pure spatial analysis** - No Excel files needed from GDB layers
- ✅ **Data quality** - Column naming inconsistencies handled, OCR errors detected

## Technical Notes

### TCP FileGDB Structure
- Contains polygon geometries for Canadian census subdivisions
- Multiple years of TCPUID columns (TCPUID_CSD_1851, TCPUID_CSD_1861, etc.)
- Requires layer detection or explicit layer specification

### Spatial Analysis Method
- Uses intersection-over-union (IoU) for polygon comparison
- Classifies relationships based on area overlap thresholds
- Handles geometric validation and CRS reprojection
- Includes name normalization for French/English place names

### Docker Commands
```bash
# Start UK GraphRAG Neo4j
docker start neo4j-uk-graphrag

# Check status
docker ps | grep neo4j

# Access browser
# http://localhost:7475 (neo4j/ukgraph123)
```

## File Permissions Note
The `generated/` directory had permission issues (owned by Docker user ID 7474). Fixed with:
```bash
sudo chown -R jic823:jic823 ~/GraphRAG_test/generated/
```

---

**Last Updated**: September 30, 2025
**Status**: CIDOC-CRM data ready for Neo4j import with OCR corrections applied

## Data Files Generated

### Temporal Linking (`year_links_output/`)
- `year_links_YYYY_YYYY.csv` - 17,060 high-confidence temporal links
- `ambiguous_YYYY_YYYY.csv` - 3,677 ambiguous temporal links
- `SUMMARY_ALL_YEARS.md` - Complete analysis report

### CIDOC-CRM Neo4j Data (`neo4j_cidoc_crm/`)
- **67 CSV files (9.7 MB)** ready for LOAD CSV import
- Node types: E53_Place, E4_Period, E93_Presence, E94_Space_Primitive
- Relationship types: P7, P164, P161, P89, P122
- `README_CIDOC_CRM.md` - Import guide with sample queries

### Data Quality (`/`)
- `ocr_corrections.csv` - 1,757 potential OCR errors detected
- `canonical_names_final.csv` - 107 canonical names assigned, 3,179 name changes preserved