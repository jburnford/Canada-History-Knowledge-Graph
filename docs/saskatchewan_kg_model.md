# Canada 1911 Census Knowledge Graph Model

This model maps 1911 Census tabular data into a Neo4j graph to enable flexible querying across geography and measures over time. It starts with Volume 1 Table 1 (population and area by geography) and can be extended to additional tables. Scope is all of Canada (country, provinces, census divisions/subdivisions, townships).

## Node Types

- Place: A geographic unit at any level (Country, Province, Census Division, Census Subdivision, Township/Range) across Canada.
  - id: stable code (e.g., `V1T1_1911` like `SK001000`)
  - name: display name (e.g., `Saskatchewan`, `Regina`, `T23 R25 MW4`)
  - province_code: two-letter province (e.g., `SK`)
  - cd_no: census division number as string (e.g., `1`, `0`)
  - csd_no: census subdivision number as string (e.g., `3`, `0`)
  - level: one of `country|province|division|subdivision|township` (derived)
  - year_start: first year this unit appears (e.g., 1911)
  - notes: optional notes carried from source where geographic context is encoded in name

- CensusTable: A published table definition shared across Canada.
  - id: e.g., `V1T1_1911`
  - title: e.g., `1911 Volume 1 Table 1`
  - year: `1911`
  - volume: `1`
  - table_no: `1`
  - description: from the workbook, if available

- Observation: A row of measured values from a table for a Place in a given year.
  - id: `${table_id}:${row_id}`
  - year: `1911`
  - pop_m_1911, pop_f_1911, pop_total_1911
  - pop_per_sq_mi_1911
  - pop_1901 (comparison baseline)
  - area_acres_1911, area_sq_mi_1911 (if present)
  - notes: any source footnotes/remarks

## Relationships

- (Place)-[:IN_COUNTRY]->(Place {id:'CA000000'})
- (Place)-[:IN_PROVINCE]->(Place {province_code: <PR>}) when `level` is `division|subdivision|township`
- (Place)-[:HAS_SUBDIVISION]->(Place) to capture Division/Subdivision hierarchy
- (Observation)-[:OF_PLACE]->(Place)
- (Observation)-[:FROM_TABLE]->(CensusTable)

## Mapping from 1911 V1T1 columns (Canada-wide)

Source sheet: `CA_V1T1_1911`

- ROW_ID → Observation.id suffix
- V1T1_1911 → Place.id (stable code; unique across all 1911 tables; use for cross-table linking)
- PR → Place.province_code
- CD_NO → Place.cd_no
- CSD_NO → Place.csd_no
- PR_CD_CSD → Place.name
- AREA_ACRES_1911 → Observation.area_acres_1911 (and optionally Place.area_acres_1911)
- AREA_SQ_MI_1911 → Observation.area_sq_mi_1911
- POP_M_1911 / POP_F_1911 / POP_TOT_1911 → Observation.*
- POP_PER_SQ_MI_1911 → Observation.pop_per_sq_mi_1911
- POP_1901 → Observation.pop_1901
- NOTES → Observation.notes

Level derivation rules:

- If PR == 'CA' → level = `country`
- Else if CD_NO == '0' and CSD_NO == '0' → `province`
- Else if CSD_NO == '0' → `division`
- Else if PR_CD_CSD matches `T\\d+ R\\d+` (Township/Range) → `township`
- Else → `subdivision`

## Example Queries

- Top 10 most populous Saskatchewan subdivisions in 1911:
  MATCH (t:CensusTable {id:'V1T1_1911'})<-[:FROM_TABLE]-(o:Observation {year:1911})-[:OF_PLACE]->(p:Place {province_code:'SK'})
  WHERE p.level IN ['subdivision','township']
  RETURN p.name, o.pop_total_1911
  ORDER BY o.pop_total_1911 DESC
  LIMIT 10;

- Saskatchewan province vs 1901–1911 growth:
  MATCH (o:Observation {year:1911})-[:OF_PLACE]->(p:Place {province_code:'SK', level:'province'})
  RETURN p.name, o.pop_1901, o.pop_total_1911, o.pop_total_1911 - o.pop_1901 AS growth;

This foundation supports adding additional 1911 tables (e.g., age, origin, religion) using the same Observation pattern with additional dimensions as needed. The `Place.id` (e.g., `SK207001`) is the join key for 1911 tables and any external datasets keyed the same way.
