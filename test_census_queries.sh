#!/bin/bash
# Test queries for census observations in Neo4j database

echo "=========================================="
echo "TEST 1: Find population measurements for Ottawa CSD in 1901"
echo "=========================================="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 "
MATCH (place:E53_Place {name: 'Ottawa', place_type: 'CSD'})<-[:P166_was_a_presence_of]-(presence:E93_Presence {census_year: 1901})
MATCH (m:E16_Measurement)-[:P39_measured]->(presence)
MATCH (m)-[:P2_has_type]->(vtype:E55_Type)
MATCH (m)-[:P40_observed_dimension]->(dim:E54_Dimension)
WHERE vtype.category = 'POP' AND vtype.variable_name CONTAINS '_XX_N'
RETURN vtype.label AS variable, dim.value AS population
ORDER BY variable
LIMIT 5;
"

echo ""
echo "=========================================="
echo "TEST 2: Total population by province in 1891"
echo "=========================================="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 "
MATCH (place:E53_Place {place_type: 'CSD'})<-[:P166_was_a_presence_of]-(presence:E93_Presence {census_year: 1891})
MATCH (m:E16_Measurement)-[:P39_measured]->(presence)
MATCH (m)-[:P2_has_type]->(vtype:E55_Type {variable_name: 'POP_XX_N'})
MATCH (m)-[:P40_observed_dimension]->(dim:E54_Dimension)
WHERE place.province IS NOT NULL
RETURN place.province AS province,
       sum(dim.value) AS total_population,
       count(DISTINCT place) AS num_csds
ORDER BY total_population DESC;
"

echo ""
echo "=========================================="
echo "TEST 3: Variable types by category"
echo "=========================================="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 "
MATCH (vtype:E55_Type)
RETURN vtype.category AS category, count(vtype) AS num_variables
ORDER BY num_variables DESC;
"

echo ""
echo "=========================================="
echo "TEST 4: Census measurements by source file"
echo "=========================================="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 "
MATCH (source:E73_Information_Object)-[:P70_documents]->(m:E16_Measurement)
RETURN source.label AS source_file, count(m) AS num_measurements
ORDER BY source_file
LIMIT 10;
"

echo ""
echo "=========================================="
echo "TEST 5: Performance - Complex query joining spatial and census data"
echo "=========================================="
time docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 "
MATCH (cd:E53_Place {place_type: 'CD', name: 'York', province: 'ON'})<-[:P166_was_a_presence_of]-(cd_presence:E93_Presence {census_year: 1871})
MATCH (csd_presence:E93_Presence)-[:P10_falls_within]->(cd_presence)
MATCH (csd_presence)-[:P166_was_a_presence_of]->(csd:E53_Place)
MATCH (m:E16_Measurement)-[:P39_measured]->(csd_presence)
MATCH (m)-[:P2_has_type]->(vtype:E55_Type {variable_name: 'POP_XX_N'})
MATCH (m)-[:P40_observed_dimension]->(dim:E54_Dimension)
RETURN csd.name AS csd_name, dim.value AS population
ORDER BY population DESC
LIMIT 10;
"

echo ""
echo "=========================================="
echo "DATABASE STATISTICS"
echo "=========================================="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 "
CALL db.stats.retrieve('GRAPH COUNTS') YIELD data
RETURN data.nodes AS total_nodes, data.relationships AS total_rels;
"
