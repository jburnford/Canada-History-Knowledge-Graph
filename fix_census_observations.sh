#!/bin/bash
# Fix census observation imports - correct P39 and P70 relationships

echo "=== Deleting existing E73_Information_Object nodes (incorrect IDs) ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
MATCH (i:E73_Information_Object)
DETACH DELETE i;
"

echo ""
echo "=== Re-importing E73_Information_Object with correct ID field ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///e73_information_objects.csv' AS row
CALL {
  WITH row
  CREATE (:E73_Information_Object {
    info_object_id: row.\`info_object_id:ID\`,
    label: row.label,
    source_table: row.source_table,
    file_hash: row.file_hash,
    access_uri: row.access_uri,
    landing_page: row.landing_page
  })
} IN TRANSACTIONS OF 100 ROWS;
"

echo ""
echo "=== Creating index for E73 info_object_id ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
CREATE INDEX info_object_id_index IF NOT EXISTS FOR (n:E73_Information_Object) ON (n.info_object_id);
"

echo ""
echo "=== Importing P39_measured (Measurement -> Presence) - 666,423 relationships ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///p39_measured_all.csv' AS row
CALL {
  WITH row
  MATCH (m:E16_Measurement {measurement_id: row.\`:START_ID\`})
  MATCH (p:E93_Presence {presence_id: row.\`:END_ID\`})
  CREATE (m)-[:P39_measured]->(p)
} IN TRANSACTIONS OF 5000 ROWS;
"

echo ""
echo "=== Importing P70_documents (Information Object -> Measurement) - 666,423 relationships ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///p70_documents_all.csv' AS row
CALL {
  WITH row
  MATCH (i:E73_Information_Object {info_object_id: row.\`:START_ID\`})
  MATCH (m:E16_Measurement {measurement_id: row.\`:END_ID\`})
  CREATE (i)-[:P70_documents]->(m)
} IN TRANSACTIONS OF 5000 ROWS;
"

echo ""
echo "=== Census observation fixes complete! ==="
