// Canadian Census CIDOC-CRM Spatial Data Import Script
// Part 1: Node Import (E53, E4, E93, E94)
// Generated: October 1, 2025

// ============================================================
// STEP 1: Import E4_Period nodes (Census years)
// ============================================================
LOAD CSV WITH HEADERS FROM 'file:///e4_period.csv' AS row
CREATE (:E4_Period {
  period_id: row.`period_id:ID`,
  year: toInteger(row.`year:int`),
  label: row.label
});

// ============================================================
// STEP 2: Import E53_Place nodes (CSD places)
// ============================================================
LOAD CSV WITH HEADERS FROM 'file:///e53_place_csd.csv' AS row
CREATE (:E53_Place {
  place_id: row.`place_id:ID`,
  place_type: row.place_type,
  name: row.name,
  province: row.province
});

// ============================================================
// STEP 3: Import E53_Place nodes (CD places)
// ============================================================
LOAD CSV WITH HEADERS FROM 'file:///e53_place_cd.csv' AS row
CREATE (:E53_Place {
  place_id: row.`place_id:ID`,
  place_type: row.place_type,
  name: row.name,
  province: row.province
});

// ============================================================
// STEP 4: Import E93_Presence nodes (CSD presences) - All years
// ============================================================
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///e93_presence_' + year + '.csv' AS row
  CREATE (:E93_Presence {
    presence_id: row.`presence_id:ID`,
    csd_tcpuid: row.csd_tcpuid,
    census_year: toInteger(row.`census_year:int`),
    area_sqm: toFloat(row.`area_sqm:float`)
  })
} IN TRANSACTIONS OF 500 ROWS;

// ============================================================
// STEP 5: Import E93_Presence nodes (CD presences) - All years
// ============================================================
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///e93_presence_cd_' + year + '.csv' AS row
  CREATE (:E93_Presence {
    presence_id: row.`presence_id:ID`,
    cd_id: row.cd_id,
    census_year: toInteger(row.`census_year:int`),
    area_sqm: toFloat(row.`area_sqm:float`),
    num_csds: toInteger(row.`num_csds:int`)
  })
} IN TRANSACTIONS OF 500 ROWS;

// ============================================================
// STEP 6: Import E94_Space_Primitive nodes (CSD centroids) - All years
// ============================================================
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///e94_space_primitive_' + year + '.csv' AS row
  CREATE (:E94_Space_Primitive {
    space_id: row.`space_id:ID`,
    latitude: toFloat(row.`latitude:float`),
    longitude: toFloat(row.`longitude:float`),
    crs: row.crs,
    point: point({latitude: toFloat(row.`latitude:float`), longitude: toFloat(row.`longitude:float`)})
  })
} IN TRANSACTIONS OF 500 ROWS;

// ============================================================
// STEP 7: Import E94_Space_Primitive nodes (CD centroids) - All years
// ============================================================
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL {
  WITH year
  LOAD CSV WITH HEADERS FROM 'file:///e94_space_primitive_cd_' + year + '.csv' AS row
  CREATE (:E94_Space_Primitive {
    space_id: row.`space_id:ID`,
    latitude: toFloat(row.`latitude:float`),
    longitude: toFloat(row.`longitude:float`),
    crs: row.crs,
    point: point({latitude: toFloat(row.`latitude:float`), longitude: toFloat(row.`longitude:float`)})
  })
} IN TRANSACTIONS OF 500 ROWS;
