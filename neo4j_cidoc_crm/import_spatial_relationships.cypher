// Canadian Census CIDOC-CRM Spatial Relationships Import Script
// Part 2: Relationship Import (P166, P164, P161, P89, P122, P132, P10)
// Generated: October 1, 2025

// ============================================================
// STEP 1: Import P166_was_a_presence_of (CSD presence → CSD place)
// ============================================================
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///p166_was_presence_of_' + year + '.csv' AS row
  MATCH (presence:E93_Presence {presence_id: row.`:START_ID`})
  MATCH (place:E53_Place {place_id: row.`:END_ID`})
  CREATE (presence)-[:P166_was_a_presence_of]->(place)
} IN TRANSACTIONS OF 500 ROWS;

// ============================================================
// STEP 2: Import P166_was_a_presence_of (CD presence → CD place)
// ============================================================
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///p166_was_presence_of_cd_' + year + '.csv' AS row
  MATCH (presence:E93_Presence {presence_id: row.`:START_ID`})
  MATCH (place:E53_Place {place_id: row.`:END_ID`})
  CREATE (presence)-[:P166_was_a_presence_of]->(place)
} IN TRANSACTIONS OF 500 ROWS;

// ============================================================
// STEP 3: Import P164_is_temporally_specified_by (CSD presence → period)
// ============================================================
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///p164_temporally_specified_by_' + year + '.csv' AS row
  MATCH (presence:E93_Presence {presence_id: row.`:START_ID`})
  MATCH (period:E4_Period {period_id: row.`:END_ID`})
  CREATE (presence)-[:P164_is_temporally_specified_by]->(period)
} IN TRANSACTIONS OF 500 ROWS;

// ============================================================
// STEP 4: Import P164_is_temporally_specified_by (CD presence → period)
// ============================================================
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///p164_temporally_specified_by_cd_' + year + '.csv' AS row
  MATCH (presence:E93_Presence {presence_id: row.`:START_ID`})
  MATCH (period:E4_Period {period_id: row.`:END_ID`})
  CREATE (presence)-[:P164_is_temporally_specified_by]->(period)
} IN TRANSACTIONS OF 500 ROWS;

// ============================================================
// STEP 5: Import P161_has_spatial_projection (CSD presence → space primitive)
// ============================================================
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///p161_spatial_projection_' + year + '.csv' AS row
  MATCH (presence:E93_Presence {presence_id: row.`:START_ID`})
  MATCH (space:E94_Space_Primitive {space_id: row.`:END_ID`})
  CREATE (presence)-[:P161_has_spatial_projection]->(space)
} IN TRANSACTIONS OF 500 ROWS;

// ============================================================
// STEP 6: Import P161_has_spatial_projection (CD presence → space primitive)
// ============================================================
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///p161_spatial_projection_cd_' + year + '.csv' AS row
  MATCH (presence:E93_Presence {presence_id: row.`:START_ID`})
  MATCH (space:E94_Space_Primitive {space_id: row.`:END_ID`})
  CREATE (presence)-[:P161_has_spatial_projection]->(space)
} IN TRANSACTIONS OF 500 ROWS;

// ============================================================
// STEP 7: Import P89_falls_within (CSD place → CD place)
// ============================================================
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///p89_falls_within_' + year + '.csv' AS row
  MATCH (csd:E53_Place {place_id: row.`:START_ID`})
  MATCH (cd:E53_Place {place_id: row.`:END_ID`})
  MERGE (csd)-[:P89_falls_within {during_period: row.during_period}]->(cd)
} IN TRANSACTIONS OF 500 ROWS;

// ============================================================
// STEP 8: Import P10_falls_within (CSD presence → CD presence)
// ============================================================
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///p10_csd_within_cd_presence_' + year + '.csv' AS row
  MATCH (csd_presence:E93_Presence {presence_id: row.`:START_ID`})
  MATCH (cd_presence:E93_Presence {presence_id: row.`:END_ID`})
  CREATE (csd_presence)-[:P10_falls_within {during_period: row.during_period}]->(cd_presence)
} IN TRANSACTIONS OF 1000 ROWS;

// ============================================================
// STEP 9: Import P122_borders_with (CSD place → CSD place)
// ============================================================
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///p122_borders_with_' + year + '.csv' AS row
  MATCH (place1:E53_Place {place_id: row.`:START_ID`})
  MATCH (place2:E53_Place {place_id: row.`:END_ID`})
  CREATE (place1)-[:P122_borders_with {
    during_period: row.during_period,
    shared_border_length_m: toFloat(row.`shared_border_length_m:float`)
  }]->(place2)
} IN TRANSACTIONS OF 1000 ROWS;

// ============================================================
// STEP 10: Import P132_spatiotemporally_overlaps_with (CSD temporal evolution)
// ============================================================
LOAD CSV WITH HEADERS FROM 'file:///p132_spatiotemporally_overlaps_with_csd.csv' AS row
CALL {
  WITH row
  MATCH (p1:E93_Presence {presence_id: row.`:START_ID`})
  MATCH (p2:E93_Presence {presence_id: row.`:END_ID`})
  CREATE (p1)-[:P132_spatiotemporally_overlaps_with {
    overlap_type: row.overlap_type,
    iou: toFloat(row.`iou:float`),
    from_fraction: toFloat(row.`from_fraction:float`),
    to_fraction: toFloat(row.`to_fraction:float`),
    year_from: toInteger(row.`year_from:int`),
    year_to: toInteger(row.`year_to:int`)
  }]->(p2)
} IN TRANSACTIONS OF 1000 ROWS;

// ============================================================
// STEP 11: Import P132_spatiotemporally_overlaps_with (CD temporal evolution)
// ============================================================
LOAD CSV WITH HEADERS FROM 'file:///p132_spatiotemporally_overlaps_with_cd.csv' AS row
CALL {
  WITH row
  MATCH (p1:E93_Presence {presence_id: row.`:START_ID`})
  MATCH (p2:E93_Presence {presence_id: row.`:END_ID`})
  CREATE (p1)-[:P132_spatiotemporally_overlaps_with {
    overlap_type: row.overlap_type,
    iou: toFloat(row.`iou:float`),
    from_fraction: toFloat(row.`from_fraction:float`),
    to_fraction: toFloat(row.`to_fraction:float`),
    year_from: toInteger(row.`year_from:int`),
    year_to: toInteger(row.`year_to:int`)
  }]->(p2)
} IN TRANSACTIONS OF 1000 ROWS;
