# Canada 1911 Census Knowledge Graph Plan

## Objectives
- Build a Canada-wide knowledge graph for 1911 Census geography and measures.
- Use stable 1911 geographic IDs to link across tables and external datasets.
- Support mixed geographies (cities, wards, townships, irregular units) via variants/sets.
- Preserve provenance, units, and data quality flags for reproducibility.

## Data Sources
- 1911Tables.zip → 1911/1911_V1T1_PUB_202306.xlsx (Volume 1 Table 1: population & area by geography).
- Additional 1911 tables (age, religion, origin, etc.) to be added iteratively.
- External population and agriculture datasets (mixed geographies, various granularities).

## Identifiers and Linking
- Place.id: from V1T1 column `V1T1_1911` (e.g., `SK207001`) — canonical 1911 geo code and primary join key.
- Observation.id: `${dataset_or_table}:${row_or_unit_id}:${year}:${indicator}` (unique per fact).
- Indicator.code: short code per measure (e.g., `population_total`, `wheat_production_bu`).
- Source.id: dataset/source identifier (e.g., `statscan_1911_v1t1_202306`).

## Graph Schema Overview
- Place
  - id (unique), name, name_en, name_fr, province_code, cd_no, csd_no, level, valid_from, valid_to, alt_names, notes, geom (optional), bbox (optional)
- CensusTable
  - id (unique), title, year, volume, table_no, sheet, columns, citation, license, url, dataset_version, retrieved_at, description_en/description_fr
- Indicator
  - code (unique), name, unit, definition, category, notes
- Observation
  - id (unique), year, value, unit, method, quality_flags, footnote_refs, source_file, sheet, row_idx, source_hash, ingested_at, place_id, table_id
- Source (optional but recommended)
  - id (unique), publisher, url, version, license, citation, checksum
- PlaceVariant (for non-canonical units)
  - authority, unit_id, name, level, valid_from, valid_to, geom (optional)
- PlaceSet (optional aggregate)
  - id, name, notes

### Relationships
- (Place)-[:IN_COUNTRY]->(Place {id:'CA000000'})
- (Place)-[:IN_PROVINCE]->(Place {province_code: <PR>}) when level ∈ {division, subdivision, township}
- (Place)-[:HAS_SUBDIVISION]->(Place)
- (Observation)-[:OF_PLACE]->(Place)
- (Observation)-[:MEASURES]->(Indicator)
- (Observation)-[:FROM_TABLE]->(CensusTable)
- (Observation)-[:FROM_SOURCE]->(Source)
- (PlaceVariant)-[:ALIASES]->(Place)
- (PlaceVariant)-[:PART_OF|WITHIN|OVERLAPS]->(Place|PlaceVariant)
- (PlaceSet)-[:MEMBER {weight}]->(Place|PlaceVariant)
- (Observation)-[:OF_PLACESET]->(PlaceSet) when reported for a set/union

## Observation Strategy (Population & Agriculture)
- Store all facts as Observation nodes with a pointer to Indicator.
- Keep raw measures (e.g., acres, bushels, head) and derived metrics (e.g., bu/acre) as separate Observations; set `method='derived'` for calculated indicators.
- Attach provenance (file/sheet/row, checksum, dataset_version, retrieved_at) for traceability.
- Use `quality_flags` and `footnote_refs` for corrections and caveats noted in source tables.

## Handling Mixed Geographies
- Exact match: Attach Observations to the canonical Place by `Place.id`.
- Non-standard units (cities, wards, irregular regions):
  - Create PlaceVariant with (authority, unit_id) as identity; link to Place via ALIASES/PART_OF/OVERLAPS.
  - If geometry available, store overlap weights in PlaceSet MEMBERS and optionally apportion observations with `method='areal_interpolation'`.
  - If no geometry, link by best name/hierarchy match and set `method='name_match'` with uncertainty noted.

## Pipeline
1. Extract and parse V1T1 (done)
   - Script: `scripts/parse_1911_v1t1_sk.py` (Canada-wide)
   - Output: `generated/ca_1911/places.csv`, `generated/ca_1911/observations.csv`
2. Define Indicators for V1T1
   - population_total, population_male, population_female, area_acres, area_sq_mi, pop_per_sq_mi, pop_1901
3. Load to Neo4j
   - Create constraints/indexes
   - Load Place, CensusTable, Indicator, Observation, and relationships
4. Extend to more 1911 tables
   - Parser modules per table → normalized Observation CSVs
   - Reuse Place.id and Indicator model
5. Integrate external population/agriculture datasets
   - Mapping spec → Place or PlaceVariant/PlaceSet
   - Load Observations with provenance and method
6. QA & validation
   - Sanity checks, totals by province, spot-checks vs source

## Neo4j Load Plan (Cypher Outline)
- Constraints/Indexes
  - CREATE CONSTRAINT place_id IF NOT EXISTS FOR (p:Place) REQUIRE p.id IS UNIQUE
  - CREATE CONSTRAINT table_id IF NOT EXISTS FOR (t:CensusTable) REQUIRE t.id IS UNIQUE
  - CREATE CONSTRAINT indicator_code IF NOT EXISTS FOR (i:Indicator) REQUIRE i.code IS UNIQUE
  - CREATE CONSTRAINT observation_id IF NOT EXISTS FOR (o:Observation) REQUIRE o.id IS UNIQUE
- Seed table metadata
  - MERGE (t:CensusTable {id:'V1T1_1911'}) SET t += {title:'1911 Volume 1 Table 1', year:1911, volume:1, table_no:1, dataset_version:'202306'}
- Load Places (LOAD CSV)
  - MERGE (p:Place {id:$id}) SET p += {name:$name, province_code:$province_code, cd_no:$cd_no, csd_no:$csd_no, level:$level, year_start:toInteger($year_start)}
- Load Indicators
  - MERGE (i:Indicator {code:$code}) SET i += {name:$name, unit:$unit, category:$category}
- Load Observations
  - MERGE (o:Observation {id:$id}) SET o += {year:toInteger($year), value:toFloat($value), unit:$unit, method:$method, source_file:$source_file, sheet:$sheet, row_idx:toInteger($row_idx)}
  - MATCH (p:Place {id:$place_id}), (t:CensusTable {id:$table_id}), (i:Indicator {code:$indicator_code})
  - MERGE (o)-[:OF_PLACE]->(p)
  - MERGE (o)-[:FROM_TABLE]->(t)
  - MERGE (o)-[:MEASURES]->(i)

## Validation & QA
- Row counts by province and level (compare against source totals where available).
- Spot-check selected Places (e.g., SK province, Regina division) for exact value matches.
- Check uniqueness of Place.id and Observation.id.
- Verify indicator units and numeric coercion are consistent.

## Deliverables
- Model doc: `docs/saskatchewan_kg_model.md` (Canada-wide description)
- Plan doc: `docs/canada_kg_plan.md` (this file)
- Parser: `scripts/parse_1911_v1t1_sk.py` (Canada-wide, optional province filter)
- Staged CSVs: `generated/ca_1911/places.csv`, `generated/ca_1911/observations.csv`

## Next Steps
- Generate Cypher scripts to load Places, Indicators, and V1T1 Observations.
- Add parser modules for additional 1911 tables (age, origin, religion).
- Prepare mapping for external population/ag datasets to Place/PlaceVariant/PlaceSet.
- Add provenance (Source) nodes and wire to Observations.
- Optional: enrich Places with bilingual names and geometry (centroids/bbox) where available.

---
Last updated: autogenerated by assistant.
