// Canadian Census CIDOC-CRM Index Creation
// Part 3: Performance Optimization
// Generated: October 1, 2025

// ============================================================
// Node ID Indexes (Critical for LOAD CSV and relationship matching)
// ============================================================

CREATE INDEX place_id_index FOR (n:E53_Place) ON (n.place_id);
CREATE INDEX presence_id_index FOR (n:E93_Presence) ON (n.presence_id);
CREATE INDEX period_id_index FOR (n:E4_Period) ON (n.period_id);
CREATE INDEX space_id_index FOR (n:E94_Space_Primitive) ON (n.space_id);

// ============================================================
// Property Indexes (Common query patterns)
// ============================================================

// Query by year
CREATE INDEX period_year_index FOR (n:E4_Period) ON (n.year);
CREATE INDEX presence_year_index FOR (n:E93_Presence) ON (n.census_year);

// Query by place type
CREATE INDEX place_type_index FOR (n:E53_Place) ON (n.place_type);

// Query by province
CREATE INDEX place_province_index FOR (n:E53_Place) ON (n.province);

// Query by place name
CREATE INDEX place_name_index FOR (n:E53_Place) ON (n.name);

// ============================================================
// Composite Indexes (Multi-property queries)
// ============================================================

// Find presence by CSD and year
CREATE INDEX presence_csd_year_index FOR (n:E93_Presence) ON (n.csd_tcpuid, n.census_year);

// Find presence by CD and year
CREATE INDEX presence_cd_year_index FOR (n:E93_Presence) ON (n.cd_id, n.census_year);

// Find place by type and province
CREATE INDEX place_type_province_index FOR (n:E53_Place) ON (n.place_type, n.province);
