#!/bin/bash
# Test queries for Canadian Census Neo4j database

echo "=========================================="
echo "TEST 1: Find Ottawa across all census years"
echo "=========================================="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 "
MATCH (place:E53_Place {name: 'Ottawa', place_type: 'CSD'})<-[:P166_was_a_presence_of]-(presence:E93_Presence)
MATCH (presence)-[:P164_is_temporally_specified_by]->(period:E4_Period)
MATCH (presence)-[:P161_has_spatial_projection]->(space:E94_Space_Primitive)
RETURN period.year AS year, presence.area_sqm AS area_sqm, space.latitude AS lat, space.longitude AS lon
ORDER BY year;
"

echo ""
echo "=========================================="
echo "TEST 2: Count CSDs within Ottawa CD in 1901"
echo "=========================================="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 "
MATCH (cd_place:E53_Place {name: 'Ottawa', place_type: 'CD'})<-[:P166_was_a_presence_of]-(cd_presence:E93_Presence)
MATCH (cd_presence)-[:P164_is_temporally_specified_by]->(period:E4_Period {year: 1901})
MATCH (csd_presence:E93_Presence)-[:P10_falls_within]->(cd_presence)
MATCH (csd_presence)-[:P166_was_a_presence_of]->(csd_place:E53_Place)
RETURN count(csd_place) AS num_csds, cd_presence.num_csds AS expected_num;
"

echo ""
echo "=========================================="
echo "TEST 3: Track CSD temporal evolution (SAME_AS links)"
echo "=========================================="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 "
MATCH (p1:E93_Presence)-[r:P132_spatiotemporally_overlaps_with {overlap_type: 'SAME_AS'}]->(p2:E93_Presence)
WHERE r.iou > 0.99
RETURN r.year_from AS from_year, r.year_to AS to_year, count(*) AS stable_csds
ORDER BY from_year
LIMIT 10;
"

echo ""
echo "=========================================="
echo "TEST 4: Find CSDs that border Ottawa in 1901"
echo "=========================================="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 "
MATCH (ottawa:E53_Place {name: 'Ottawa', place_type: 'CSD'})-[r:P122_borders_with {during_period: 'CENSUS_1901'}]->(neighbor:E53_Place)
RETURN neighbor.name AS neighbor_name, r.shared_border_length_m AS border_length_m
ORDER BY border_length_m DESC
LIMIT 10;
"

echo ""
echo "=========================================="
echo "TEST 5: CD growth analysis (1851 vs 1921)"
echo "=========================================="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 "
MATCH (cd:E53_Place {place_type: 'CD', province: 'ON'})<-[:P166_was_a_presence_of]-(p1851:E93_Presence {census_year: 1851})
MATCH (cd)<-[:P166_was_a_presence_of]-(p1921:E93_Presence {census_year: 1921})
RETURN cd.name AS cd_name,
       p1851.num_csds AS csds_1851,
       p1921.num_csds AS csds_1921,
       p1921.num_csds - p1851.num_csds AS csd_growth
ORDER BY csd_growth DESC
LIMIT 10;
"

echo ""
echo "=========================================="
echo "TEST 6: Performance test - Complex multi-hop query"
echo "=========================================="
time docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 "
MATCH (p1901:E93_Presence {census_year: 1901})-[:P10_falls_within]->(cd_presence:E93_Presence)
MATCH (cd_presence)-[:P166_was_a_presence_of]->(cd:E53_Place)
WHERE cd.province = 'ON'
RETURN cd.name AS cd_name, count(p1901) AS num_csds
ORDER BY num_csds DESC
LIMIT 10;
"

echo ""
echo "=========================================="
echo "DATABASE STATISTICS"
echo "=========================================="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 "
CALL db.stats.retrieve('GRAPH COUNTS');
"
