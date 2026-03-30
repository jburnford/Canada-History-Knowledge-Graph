# Wikidata Grounding for Canadian Census Geography

Ground 1921 Census Divisions (CDs) and Census Subdivisions (CSDs) from the
TCP Historical GIS dataset to Wikidata QIDs.

## Phase 1: Census Divisions (CDs)

**Script:** `scripts/ground_places_to_wikidata.py` (Phase 1)
**Helper:** `wikidata_grounding/apply_cd_matches.py`

### Method
1. Bulk SPARQL query via QLever for all Canadian county/district entities
2. MCP Wikidata search for unmatched CDs (QC historic counties, PEI, territories)
3. Manual validation of edge cases (Montmorency No.1+2, Lac-Saint-Jean Est+Ouest)

### Results: `cd_wikidata_matches.csv`

| Category | Count | Notes |
|---|---|---|
| Wikidata QID | 154 | Real administrative entities |
| Minted URI | 17 | 13 BC (electoral-district CDs), 2 QC (composite), 1 ON (Muskoka), 1 QC (Montreal+Jesus Islands) |
| **Total** | **171** | Zero unmatched |

**Minted URI cases:**
- **BC (13):** 1921 census divisions based on electoral districts, no county equivalents
- **QC (2):** Montmorency (spans No.1 + No.2), Lac St. Jean (spans Est + Ouest)
- **QC (1):** Montreal & Jesus Islands (composite CD)
- **ON (1):** Muskoka (no Wikidata entity for historic district)

## Phase 2: Census Subdivisions (CSDs)

**Script:** `scripts/ground_csds_phase2.py`

### Method — three paths based on province/CD type

**Path A (non-QC CDs with Wikidata QIDs):**
Batch QLever SPARQL queries using P131 (located in administrative entity) to find
all Wikidata places within each CD. Match to CSDs by normalized name + coordinate
validation (< 50 km).

**Path B (Quebec CSDs):**
Quebec P131 chains point to modern RCMs, not historic counties. Single QLever query
fetches all QC municipalities, townships, parishes by P31 type, then matches by
name + coordinates. Includes qualifier-stripping fallback ("St. Albert de Warwick"
matches "Saint-Albert-de-Warwick").

**Path C (Prairie + BC CSDs):**
CDs are numbered divisions (minted URIs), but individual CSDs (towns, villages,
rural municipalities) often have Wikidata entities. Province-level QLever queries
fetch all places, with special handling for SK rural municipality naming
("5. Estevan" matches "Rural Municipality of Estevan No. 5").

### Results

| Path | Scope | Matched | Rate |
|---|---|---|---|
| A (non-QC via P131) | 2,259 | 1,036 | 46% |
| B (QC province query) | 1,434 | 972 | 68% |
| C (Prairie/BC province) | 1,554 | 1,055 | 68% |
| **Total** | **5,247** | **3,063** | **58%** |

**Output files:**
- `csd_wikidata_matches.csv` — 3,063 matched CSDs with QIDs, labels, types, distances
- `csd_wikidata_unmatched.csv` — 2,114 unmatched CSDs with reasons

### Unmatched categories
- Alberta LIDs (Local Improvement Districts) — numbered administrative units
- Quebec parishes with historical name variants not in modern Wikidata
- Ontario/NS townships not represented in Wikidata
- Compass-direction parish splits (Chester E., Chester N.)
- Unorganized territories and "NO DATA" entries

## Name Normalization

Key transformations applied to both TCP and Wikidata names:
- Accent removal (é→e, ç→c, etc.)
- Saint/Sainte variants unified (St., Ste., Saint-, Sainte- → "st ")
- Hyphen removal (critical for QC: "Saint-Albert-de-Warwick" → "st albert de warwick")
- CSD type suffix stripping (, VL / , T-V / , C / , par.)
- Qualifier fallback: strip "de/du/des/d'" clauses for fuzzy matching
- SK RM number stripping: "5. Estevan" → "estevan"

## Coordinate Validation

All matches validated by haversine distance between 1921 TCP centroid and Wikidata
P625 coordinates. Maximum threshold: 50 km. This prevents false positives from
same-name places in different locations.

## Dependencies

- **QLever** (https://qlever.dev/api/wikidata) — SPARQL endpoint for bulk queries
- **Wikidata MCP server** — for interactive entity search and validation
- **TCP CIDOC-CRM data** — centroids, place hierarchies from `neo4j_cidoc_crm/`
