#!/bin/bash
# Import provenance and appellations data

echo "=== Creating indexes for provenance and appellation nodes ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
CREATE INDEX actor_id_index IF NOT EXISTS FOR (n:E39_Actor) ON (n.actor_id);
CREATE INDEX right_id_index IF NOT EXISTS FOR (n:E30_Right) ON (n.right_id);
CREATE INDEX creation_id_index IF NOT EXISTS FOR (n:E65_Creation) ON (n.creation_id);
CREATE INDEX linguistic_object_id_index IF NOT EXISTS FOR (n:E33_Linguistic_Object) ON (n.citation_id);
CREATE INDEX appellation_id_index IF NOT EXISTS FOR (n:E41_Appellation) ON (n.appellation_id);
"

echo ""
echo "=== Importing E39_Actor (creators) - 7 records ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///e39_actors.csv' AS row
CALL {
  WITH row
  CREATE (:E39_Actor {
    actor_id: row.\`actor_id:ID\`,
    name: row.name,
    type: row.type,
    affiliation: row.affiliation,
    orcid: row.orcid,
    role: row.role,
    website: row.website
  })
} IN TRANSACTIONS OF 100 ROWS;
"

echo ""
echo "=== Importing E30_Right (licenses) - 1 record ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///e30_rights.csv' AS row
CALL {
  WITH row
  CREATE (:E30_Right {
    right_id: row.\`right_id:ID\`,
    label: row.label,
    access_rights: row.access_rights,
    license_uri: row.license_uri,
    description: row.description
  })
} IN TRANSACTIONS OF 100 ROWS;
"

echo ""
echo "=== Importing E65_Creation (creation activities) - 1 record ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///e65_creation.csv' AS row
CALL {
  WITH row
  CREATE (:E65_Creation {
    creation_id: row.\`creation_id:ID\`,
    label: row.label,
    description: row.description
  })
} IN TRANSACTIONS OF 100 ROWS;
"

echo ""
echo "=== Importing E33_Linguistic_Object (citations) - 9 records ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///e33_linguistic_objects.csv' AS row
CALL {
  WITH row
  CREATE (:E33_Linguistic_Object {
    citation_id: row.\`citation_id:ID\`,
    citation_text: row.citation_text,
    citation_style: row.citation_style
  })
} IN TRANSACTIONS OF 100 ROWS;
"

echo ""
echo "=== Importing E41_Appellation (place name variants) - 350 records ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///e41_appellations.csv' AS row
CALL {
  WITH row
  CREATE (:E41_Appellation {
    appellation_id: row.\`appellation_id:ID\`,
    name: row.name,
    type: row.type,
    tcpuid: row.tcpuid,
    notes: row.notes,
    year: CASE WHEN row.year IS NOT NULL AND row.year <> '' THEN toFloat(row.year) ELSE null END
  })
} IN TRANSACTIONS OF 500 ROWS;
"

echo ""
echo "=== Importing P14_carried_out_by (Creation -> Actor) - 6 relationships ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///p14_carried_out.csv' AS row
CALL {
  WITH row
  MATCH (c:E65_Creation {creation_id: row.\`:START_ID\`})
  MATCH (a:E39_Actor {actor_id: row.\`:END_ID\`})
  CREATE (c)-[:P14_carried_out_by {role: row.role}]->(a)
} IN TRANSACTIONS OF 100 ROWS;
"

echo ""
echo "=== Importing P104_is_subject_to (Information Object -> Right) - 9 relationships ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///p104_is_subject_to.csv' AS row
CALL {
  WITH row
  MATCH (i:E73_Information_Object {info_object_id: row.\`:START_ID\`})
  MATCH (r:E30_Right {right_id: row.\`:END_ID\`})
  CREATE (i)-[:P104_is_subject_to]->(r)
} IN TRANSACTIONS OF 100 ROWS;
"

echo ""
echo "=== Importing P67_refers_to (Citation -> Information Object) - 9 relationships ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///p67_refers_to.csv' AS row
CALL {
  WITH row
  MATCH (c:E33_Linguistic_Object {citation_id: row.\`:START_ID\`})
  MATCH (i:E73_Information_Object {info_object_id: row.\`:END_ID\`})
  CREATE (c)-[:P67_refers_to]->(i)
} IN TRANSACTIONS OF 100 ROWS;
"

echo ""
echo "=== Importing P1_is_identified_by (Place -> Appellation) - 350 relationships ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///p1_is_identified_by.csv' AS row
CALL {
  WITH row
  MATCH (p:E53_Place {place_id: row.\`:START_ID\`})
  MATCH (a:E41_Appellation {appellation_id: row.\`:END_ID\`})
  CREATE (p)-[:P1_is_identified_by {
    appellation_type: row.appellation_type
  }]->(a)
} IN TRANSACTIONS OF 500 ROWS;
"

echo ""
echo "=== Provenance and appellations import complete! ==="
