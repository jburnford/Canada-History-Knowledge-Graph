# Post-Merge CIDOC-CRM Improvements Plan

**Created**: October 1, 2025
**Context**: After merging Codex's CIDOC-CRM compliance fixes (P7→P166, P134→P132)
**Goal**: Further enhance model to be maximally CIDOC-CRM compliant and feature-complete

---

## Overview

The Codex merge successfully fixed critical property domain/range violations. This plan addresses:
1. **Purist CIDOC-CRM modeling**: Add explicit E92_Spacetime_Volume nodes
2. **CD temporal continuity**: Restore Census Division evolution tracking
3. **Advanced spatial modeling**: Polygon-based E92 nodes instead of just centroids
4. **Query optimization**: Improve performance with strategic indexing

---

## Priority 1: Add E92_Spacetime_Volume Nodes (Optional - Purist Approach)

### Current State
- E93_Presence → P166 → E53_Place (works via inheritance, E53 is subclass of E92)
- **Issue**: Unconventional - P166 range is technically E92, not E53

### Proposed Enhancement
```
E53_Place (abstract, timeless)
  "Ontario" as a conceptual place
  ↓ P161_has_spatial_projection (NEW)
E92_Spacetime_Volume (bounded in space and time)
  "Ontario's spatial extent 1851-1921"
  ↑ P166_was_a_presence_of
E93_Presence (phenomenal manifestation)
  "Ontario in 1901"
```

### Implementation

#### New Entities
- **E92_Spacetime_Volume**: One per E53_Place (collapsed across all years)
  - Properties: `volume_id`, `place_id_ref`, `temporal_extent_start`, `temporal_extent_end`
  - Example: `VOLUME_ON039029` (Ottawa's spacetime volume 1851-1921)

#### New Relationships
- **P166_was_a_presence_of**: E93_Presence → E92_Spacetime_Volume (redirected)
- **P161_has_spatial_projection**: E92_Spacetime_Volume → E53_Place (NEW)
- **P10_falls_within** (spatial): E92_Spacetime_Volume → E92_Spacetime_Volume (CSD→CD hierarchy)

#### Script: `scripts/build_e92_volumes.py`
```python
"""
Generate E92_Spacetime_Volume nodes linking E93_Presence to E53_Place.

Reads existing E53_Place and E93_Presence CSVs, creates E92 intermediate nodes.
"""

Input:
  - neo4j_cidoc_crm/e53_place_csd.csv
  - neo4j_cidoc_crm/e93_presence_*.csv (8 years)

Output:
  - neo4j_cidoc_crm/e92_spacetime_volume_csd.csv (13,135 volumes)
  - neo4j_cidoc_crm/e92_spacetime_volume_cd.csv (579 volumes)
  - neo4j_cidoc_crm/p166_was_presence_of_e92_*.csv (21,047 relationships, redirected to E92)
  - neo4j_cidoc_crm/p161_e92_to_e53.csv (13,135 relationships, E92→E53)

Algorithm:
  1. For each E53_Place, create one E92_Spacetime_Volume
  2. Determine temporal extent: min/max year from linked E93_Presences
  3. Redirect P166 from E93→E53 to E93→E92
  4. Add P161 from E92→E53 (spatial projection)
```

#### Benefits
- **Formal correctness**: P166 now targets E92 (exact range match)
- **Semantic clarity**: Separates "timeless place concept" (E53) from "bounded spacetime volume" (E92)
- **Extensibility**: Can model place name changes (multiple E92s per E53)

#### Effort
- **Time**: 4-6 hours (script + testing + documentation)
- **Risk**: Low - additive change, doesn't break existing queries
- **Priority**: Optional - only needed for maximum CIDOC-CRM purity

---

## Priority 2: Census Division Temporal Continuity (HIGH VALUE)

### Current State
- **Lost**: 1,302 CD temporal links removed in Codex merge
- **Reason**: CD nodes are E53_Place only (no E93_Presence)
- **Data available**: `cd_links_output/` contains all CD spatial overlap analysis

### Proposed Solution: Generate CD Presences

#### New Entities
- **E93_Presence (CD-year)**: 579 CDs × 8 years = ~4,600 presences
  - Properties: `presence_id`, `cd_id`, `year`, `area_sqm`, `num_csds`
  - Example: `ON_Ottawa_1901` (Ottawa CD's 1901 manifestation)

#### New Relationships
- **P166_was_a_presence_of**: E93_Presence → E53_Place (CD version)
- **P164_is_temporally_specified_by**: E93_Presence → E4_Period
- **P161_has_spatial_projection**: E93_Presence → E94_Space_Primitive (CD centroid)
- **P132_spatiotemporally_overlaps_with**: CD Presence → CD Presence (2,168 links)
- **P10_falls_within** (spatial): CSD Presence → CD Presence (21,046 links)

#### Script: `scripts/build_cd_presences.py`
```python
"""
Generate E93_Presence nodes for Census Divisions with temporal overlap tracking.

Reads CD polygons from GDB, creates presences parallel to CSD presences.
"""

Input:
  - TCP_CANADA_CSD_202306.gdb (CD layer for each year)
  - cd_links_output/cd_links_*.csv (2,168 temporal links)

Output:
  - neo4j_cidoc_crm/e93_presence_cd_*.csv (8 files, ~4,600 presences)
  - neo4j_cidoc_crm/e94_space_primitive_cd_*.csv (CD centroids)
  - neo4j_cidoc_crm/p166_was_presence_of_cd_*.csv
  - neo4j_cidoc_crm/p164_temporally_specified_by_cd_*.csv
  - neo4j_cidoc_crm/p161_spatial_projection_cd_*.csv
  - neo4j_cidoc_crm/p132_spatiotemporally_overlaps_with_cd.csv (2,168 links)
  - neo4j_cidoc_crm/p10_csd_presence_within_cd_presence_*.csv (21,046 links)

Algorithm:
  1. Load CD polygons for each year from GDB
  2. Calculate CD area, centroid, CSD count
  3. Create E93_Presence (CD-year) nodes
  4. Link to E53_Place (CD), E4_Period, E94_Space_Primitive
  5. Read cd_links CSV files, generate P132 relationships
  6. Match CSD presences to CD presences via P89 (existing E53→E53 hierarchy)
```

#### Benefits
- **Restored functionality**: CD temporal evolution tracking (lost in merge)
- **Administrative hierarchy**: Full CSD→CD presence linkage over time
- **Western expansion analysis**: Track Saskatchewan/Alberta CD creation (1905)
- **Query capability**: "Show all CSDs within Winnipeg CD in 1901"

#### Effort
- **Time**: 6-8 hours (script + GDB processing + documentation)
- **Risk**: Medium - requires GDB CD layer extraction (similar to CSD script)
- **Priority**: HIGH - restores lost functionality, high research value

---

## Priority 3: Advanced Spatial Modeling (Future Work)

### Current State
- E94_Space_Primitive stores only centroid points
- E93_Presence has `area_sqm` property (flat attribute)
- No polygon geometry in Neo4j

### Proposed Enhancement: WKT Polygon Storage

#### Option A: Store WKT in E94_Space_Primitive
```csv
space_id,latitude,longitude,wkt_polygon,crs
ON039029_1901,45.4215,-75.6972,"POLYGON((-75.7 45.3, -75.5 45.3, ...))",EPSG:4326
```

**Neo4j Query**:
```cypher
MATCH (presence:E93_Presence)-[:P161_has_spatial_projection]->(space:E94_Space_Primitive)
WHERE space.wkt_polygon IS NOT NULL
RETURN presence.presence_id, space.wkt_polygon
```

**Benefits**:
- Enables spatial intersection queries (with Neo4j Spatial plugin)
- Preserves exact boundary shapes
- Supports advanced GIS analysis

**Drawbacks**:
- Large file sizes (~50-100 MB for WKT strings)
- Requires Neo4j Spatial plugin (not available in Community Edition)
- Query performance penalty

#### Option B: External PostGIS Database
```
Neo4j (graph structure) ←→ PostGIS (spatial operations)
```

**Architecture**:
- Neo4j: E93_Presence nodes with `presence_id`, `area_sqm`, `tcpuid`
- PostGIS: `census_polygons` table with `presence_id`, `geometry`
- Join via `presence_id` key

**Benefits**:
- Optimized spatial queries (PostGIS specialized for GIS)
- No Neo4j Community Edition limitations
- Industry-standard GIS workflow

**Drawbacks**:
- Dual database maintenance
- More complex deployment

#### Recommendation
- **Phase 1**: Keep current centroid-only approach (SIMPLE, FAST)
- **Phase 2** (if needed): Add WKT polygons for specific use cases
- **Phase 3** (if needed): Integrate PostGIS for advanced spatial analytics

#### Effort
- **Phase 1**: 0 hours (already complete)
- **Phase 2**: 8-10 hours (WKT export + Neo4j Spatial setup)
- **Phase 3**: 16-20 hours (PostGIS integration + API layer)
- **Priority**: LOW - current centroid model sufficient for most queries

---

## Priority 4: Query Optimization & Indexing

### Neo4j Performance Enhancements

#### Indexes to Create
```cypher
// Node ID indexes (critical for LOAD CSV)
CREATE INDEX FOR (n:E53_Place) ON (n.place_id);
CREATE INDEX FOR (n:E93_Presence) ON (n.presence_id);
CREATE INDEX FOR (n:E4_Period) ON (n.period_id);
CREATE INDEX FOR (n:E16_Measurement) ON (n.measurement_id);

// Property indexes (common query patterns)
CREATE INDEX FOR (n:E4_Period) ON (n.year);
CREATE INDEX FOR (n:E53_Place) ON (n.place_type);
CREATE INDEX FOR (n:E55_Type) ON (n.category);

// Composite indexes (multi-property queries)
CREATE INDEX FOR (n:E93_Presence) ON (n.tcpuid, n.year);
```

#### Query Templates (Optimized)
```cypher
// Fast: Population time series for specific CSD
MATCH (place:E53_Place {place_id: 'ON039029'})<-[:P166_was_a_presence_of]-(presence:E93_Presence)
MATCH (presence)-[:P164_is_temporally_specified_by]->(period:E4_Period)
MATCH (m:E16_Measurement)-[:P39_measured]->(presence)
MATCH (m)-[:P2_has_type]->(:E55_Type {type_id: 'VAR_POP_TOTAL'})
MATCH (m)-[:P40_observed_dimension]->(dim:E54_Dimension)
RETURN period.year, dim.value
ORDER BY period.year;

// Fast: All CSDs with population > 10,000 in 1901
MATCH (period:E4_Period {year: 1901})<-[:P164_is_temporally_specified_by]-(presence:E93_Presence)
MATCH (m:E16_Measurement)-[:P39_measured]->(presence)
MATCH (m)-[:P2_has_type]->(:E55_Type {type_id: 'VAR_POP_TOTAL'})
MATCH (m)-[:P40_observed_dimension]->(dim:E54_Dimension)
WHERE dim.value > 10000
MATCH (presence)-[:P166_was_a_presence_of]->(place:E53_Place)
RETURN place.name, dim.value
ORDER BY dim.value DESC;
```

#### Effort
- **Time**: 1-2 hours (index creation + documentation)
- **Risk**: Zero - indexes improve performance only
- **Priority**: HIGH - should be done immediately after data load

---

## Summary: Implementation Roadmap

### Phase 1: Immediate (1-2 weeks)
1. ✅ **Merge Codex branch** (COMPLETE)
2. **Create Neo4j indexes** (Priority 4 - 2 hours)
3. **Generate CD presences** (Priority 2 - 8 hours)
4. **Document query patterns** (update README with optimized examples)

### Phase 2: Optional Enhancements (1-2 months)
5. **Add E92_Spacetime_Volume nodes** (Priority 1 - 6 hours, purist CIDOC-CRM)
6. **WKT polygon storage** (Priority 3 - 10 hours, if spatial queries needed)

### Phase 3: Advanced (3-6 months)
7. **PostGIS integration** (Priority 3 - 20 hours, for GIS specialists)
8. **RDF/SPARQL endpoint** (LOD publication)
9. **GraphQL API** (web application development)

---

## Decision Points

### Should we add E92 nodes? (Priority 1)
- **YES if**: Publishing to LOD community, want maximum CIDOC-CRM compliance
- **NO if**: Primarily internal use, current P166 to E53 is "good enough"
- **Recommendation**: DEFER until LOD publication phase

### Should we restore CD presences? (Priority 2)
- **YES if**: Need administrative hierarchy queries, Western expansion research
- **NO if**: Only interested in CSD-level analysis
- **Recommendation**: YES - high research value, restores lost functionality

### Should we add polygon geometries? (Priority 3)
- **YES if**: Need boundary intersection queries, spatial joins, GIS analysis
- **NO if**: Centroid + area sufficient (most historical census research)
- **Recommendation**: DEFER - current centroid model sufficient for 90% of queries

---

## Next Steps

1. Review this plan with project stakeholders
2. Prioritize based on immediate research needs
3. Create GitHub issues for tracking
4. Begin with Priority 2 (CD presences) - highest value/effort ratio
5. Set up Neo4j indexes (Priority 4) before loading data

---

**Questions? Issues?**
- See `CODEX_IMPROVEMENTS_PLAN.md` for context on completed work
- See `DATA_QUALITY_TODOS.md` for data cleaning tasks
- See `README.md` for project overview and current status
