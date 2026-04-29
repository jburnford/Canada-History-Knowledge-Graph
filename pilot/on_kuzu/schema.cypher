// Three-Model KG Pilot -- Approach C (KuzuDB)
// Strict typing: every column explicitly typed, CSV column order must match
// See pilot/variables.md for the five pilot measurement columns

CREATE NODE TABLE Place (
  place_id STRING,
  name STRING,
  province STRING,
  place_type STRING,
  wikidata_qid STRING,
  geonames_id STRING,
  enwiki_url STRING,
  frwiki_url STRING,
  PRIMARY KEY (place_id)
);

CREATE NODE TABLE Presence (
  presence_id STRING,
  tcpuid STRING,
  year INT64,
  area_sqm DOUBLE,
  centroid_lat DOUBLE,
  centroid_lon DOUBLE,
  pop_total INT64,
  pop_total_m INT64,
  pop_total_f INT64,
  pop_per_sq_mi DOUBLE,
  cd_name STRING,
  PRIMARY KEY (presence_id)
);

CREATE NODE TABLE Name (
  name_id STRING,
  label STRING,
  language STRING,
  kind STRING,
  PRIMARY KEY (name_id)
);

CREATE NODE TABLE CensusVariable (
  var_code STRING,
  label STRING,
  category STRING,
  unit STRING,
  source_tables STRING,
  year_count INT64,
  comparable_across_years BOOLEAN,
  presence_count INT64,
  quality STRING,
  PRIMARY KEY (var_code)
);

CREATE NODE TABLE Measurement (
  measurement_id STRING,
  value_float DOUBLE,
  value_string STRING,
  PRIMARY KEY (measurement_id)
);

CREATE REL TABLE HAS_NAME_PLACE (FROM Place TO Name);
CREATE REL TABLE HAS_NAME_PRESENCE (FROM Presence TO Name);
CREATE REL TABLE OBSERVED_IN (FROM Presence TO Place);
CREATE REL TABLE PART_OF_COUNTY (FROM Presence TO Presence);
CREATE REL TABLE BORDERS (FROM Presence TO Presence, length_m DOUBLE);
CREATE REL TABLE CONTINUES_AS (FROM Presence TO Presence, iou DOUBLE);
CREATE REL TABLE OVERLAPS_TEMPORALLY (FROM Presence TO Presence, overlap_type STRING, iou DOUBLE, year_from INT64, year_to INT64);
CREATE REL TABLE SPLIT_FROM (FROM Place TO Place, change_year INT64);
CREATE REL TABLE MERGED_INTO (FROM Place TO Place, change_year INT64);
CREATE REL TABLE MEASURED_AT (FROM Presence TO Measurement);
CREATE REL TABLE OF_VARIABLE (FROM Measurement TO CensusVariable);
