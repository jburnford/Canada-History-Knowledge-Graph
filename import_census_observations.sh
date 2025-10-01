#!/bin/bash
# Import census observations (E16, E54 nodes) and relationships
# Large dataset: 666,423 measurements, 666,423 dimensions

echo "=== Creating indexes for census observation nodes ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
CREATE INDEX measurement_id_index IF NOT EXISTS FOR (n:E16_Measurement) ON (n.measurement_id);
CREATE INDEX dimension_id_index IF NOT EXISTS FOR (n:E54_Dimension) ON (n.dimension_id);
CREATE INDEX variable_type_id_index IF NOT EXISTS FOR (n:E55_Type) ON (n.type_id);
CREATE INDEX unit_id_index IF NOT EXISTS FOR (n:E58_Measurement_Unit) ON (n.unit_id);
CREATE INDEX timespan_id_index IF NOT EXISTS FOR (n:E52_Time_Span) ON (n.timespan_id);
CREATE INDEX info_object_id_index IF NOT EXISTS FOR (n:E73_Information_Object) ON (n.info_id);
"

echo ""
echo "=== Importing E55_Type (variable types) - 491 records ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///e55_variable_types.csv' AS row
CALL {
  WITH row
  CREATE (:E55_Type {
    type_id: row.\`type_id:ID\`,
    label: row.label,
    category: row.category,
    unit: row.unit,
    variable_name: row.variable_name
  })
} IN TRANSACTIONS OF 500 ROWS;
"

echo ""
echo "=== Importing E58_Measurement_Unit (units) - 6 records ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///e58_measurement_units.csv' AS row
CALL {
  WITH row
  CREATE (:E58_Measurement_Unit {
    unit_id: row.\`unit_id:ID\`,
    label: row.label
  })
} IN TRANSACTIONS OF 100 ROWS;
"

echo ""
echo "=== Importing E52_Time_Span (timespans) - 8 records ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///e52_timespans.csv' AS row
CALL {
  WITH row
  CREATE (:E52_Time_Span {
    timespan_id: row.\`timespan_id:ID\`,
    year: toInteger(row.\`year:int\`),
    start_date: row.start_date,
    end_date: row.end_date,
    label: row.label
  })
} IN TRANSACTIONS OF 100 ROWS;
"

echo ""
echo "=== Importing E73_Information_Object (source files) - 9 records ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///e73_information_objects.csv' AS row
CALL {
  WITH row
  CREATE (:E73_Information_Object {
    info_id: row.\`info_id:ID\`,
    filename: row.filename,
    year: toInteger(row.\`year:int\`),
    label: row.label
  })
} IN TRANSACTIONS OF 100 ROWS;
"

echo ""
echo "=== Importing E16_Measurement nodes - 666,423 records (this will take several minutes) ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///e16_measurements_all.csv' AS row
CALL {
  WITH row
  CREATE (:E16_Measurement {
    measurement_id: row.\`measurement_id:ID\`,
    label: row.label,
    notes: row.notes
  })
} IN TRANSACTIONS OF 5000 ROWS;
"

echo ""
echo "=== Importing E54_Dimension nodes - 666,423 records (this will take several minutes) ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///e54_dimensions_all.csv' AS row
CALL {
  WITH row
  CREATE (:E54_Dimension {
    dimension_id: row.\`dimension_id:ID\`,
    value: CASE WHEN row.\`value:float\` IS NOT NULL THEN toFloat(row.\`value:float\`) ELSE null END,
    value_string: row.value_string
  })
} IN TRANSACTIONS OF 5000 ROWS;
"

echo ""
echo "=== Importing P39_measured (Measurement -> Dimension) - 666,423 relationships ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///p39_measured_all.csv' AS row
CALL {
  WITH row
  MATCH (m:E16_Measurement {measurement_id: row.\`:START_ID\`})
  MATCH (d:E54_Dimension {dimension_id: row.\`:END_ID\`})
  CREATE (m)-[:P39_measured]->(d)
} IN TRANSACTIONS OF 5000 ROWS;
"

echo ""
echo "=== Importing P40_observed_dimension (Measurement -> Dimension) - 666,423 relationships ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///p40_observed_dimension_all.csv' AS row
CALL {
  WITH row
  MATCH (m:E16_Measurement {measurement_id: row.\`:START_ID\`})
  MATCH (d:E54_Dimension {dimension_id: row.\`:END_ID\`})
  CREATE (m)-[:P40_observed_dimension]->(d)
} IN TRANSACTIONS OF 5000 ROWS;
"

echo ""
echo "=== Importing P2_has_type (Measurement -> Variable Type) - 666,423 relationships ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///p2_has_type_all.csv' AS row
CALL {
  WITH row
  MATCH (m:E16_Measurement {measurement_id: row.\`:START_ID\`})
  MATCH (t:E55_Type {type_id: row.\`:END_ID\`})
  CREATE (m)-[:P2_has_type]->(t)
} IN TRANSACTIONS OF 5000 ROWS;
"

echo ""
echo "=== Importing P91_has_unit (Dimension -> Unit) - 666,423 relationships ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///p91_has_unit_all.csv' AS row
CALL {
  WITH row
  MATCH (d:E54_Dimension {dimension_id: row.\`:START_ID\`})
  MATCH (u:E58_Measurement_Unit {unit_id: row.\`:END_ID\`})
  CREATE (d)-[:P91_has_unit]->(u)
} IN TRANSACTIONS OF 5000 ROWS;
"

echo ""
echo "=== Importing P4_has_time_span (Measurement -> Time Span) - 666,423 relationships ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///p4_measurement_timespan_all.csv' AS row
CALL {
  WITH row
  MATCH (m:E16_Measurement {measurement_id: row.\`:START_ID\`})
  MATCH (t:E52_Time_Span {timespan_id: row.\`:END_ID\`})
  CREATE (m)-[:P4_has_time_span]->(t)
} IN TRANSACTIONS OF 5000 ROWS;
"

echo ""
echo "=== Importing P4_has_time_span (Period -> Time Span) - 8 relationships ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///p4_period_timespan.csv' AS row
CALL {
  WITH row
  MATCH (p:E4_Period {period_id: row.\`:START_ID\`})
  MATCH (t:E52_Time_Span {timespan_id: row.\`:END_ID\`})
  CREATE (p)-[:P4_has_time_span]->(t)
} IN TRANSACTIONS OF 100 ROWS;
"

echo ""
echo "=== Importing P70_documents (Information Object -> Measurement) - 666,423 relationships ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///p70_documents_all.csv' AS row
CALL {
  WITH row
  MATCH (i:E73_Information_Object {info_id: row.\`:START_ID\`})
  MATCH (m:E16_Measurement {measurement_id: row.\`:END_ID\`})
  CREATE (i)-[:P70_documents]->(m)
} IN TRANSACTIONS OF 5000 ROWS;
"

echo ""
echo "=== Census observations import complete! ==="
