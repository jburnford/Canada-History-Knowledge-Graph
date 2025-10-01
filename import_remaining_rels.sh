#!/bin/bash
# Import remaining spatial relationships efficiently

echo "=== Importing P89_falls_within (CSD → CD places) ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL { WITH year
  LOAD CSV WITH HEADERS FROM 'file:///p89_falls_within_' + year + '.csv' AS row
  MATCH (csd:E53_Place {place_id: row.\`:START_ID\`})
  MATCH (cd:E53_Place {place_id: row.\`:END_ID\`})
  MERGE (csd)-[:P89_falls_within {during_period: row.during_period}]->(cd)
} IN TRANSACTIONS OF 500 ROWS;
"

echo "=== Importing P10_falls_within (CSD presence → CD presence) ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL { WITH year
  LOAD CSV WITH HEADERS FROM 'file:///p10_csd_within_cd_presence_' + year + '.csv' AS row
  MATCH (csd_presence:E93_Presence {presence_id: row.\`:START_ID\`})
  MATCH (cd_presence:E93_Presence {presence_id: row.\`:END_ID\`})
  CREATE (csd_presence)-[:P10_falls_within {during_period: row.during_period}]->(cd_presence)
} IN TRANSACTIONS OF 1000 ROWS;
"

echo "=== Importing P122_borders_with (CSD borders) ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
UNWIND [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921] AS year
CALL { WITH year
  LOAD CSV WITH HEADERS FROM 'file:///p122_borders_with_' + year + '.csv' AS row
  MATCH (place1:E53_Place {place_id: row.\`:START_ID\`})
  MATCH (place2:E53_Place {place_id: row.\`:END_ID\`})
  CREATE (place1)-[:P122_borders_with {
    during_period: row.during_period,
    shared_border_length_m: toFloat(row.\`shared_border_length_m:float\`)
  }]->(place2)
} IN TRANSACTIONS OF 1000 ROWS;
"

echo "=== Importing P132 CSD temporal overlaps ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///p132_spatiotemporally_overlaps_with_csd.csv' AS row
CALL { WITH row
  MATCH (p1:E93_Presence {presence_id: row.\`:START_ID\`})
  MATCH (p2:E93_Presence {presence_id: row.\`:END_ID\`})
  CREATE (p1)-[:P132_spatiotemporally_overlaps_with {
    overlap_type: row.overlap_type,
    iou: toFloat(row.\`iou:float\`),
    from_fraction: toFloat(row.\`from_fraction:float\`),
    to_fraction: toFloat(row.\`to_fraction:float\`),
    year_from: toInteger(row.\`year_from:int\`),
    year_to: toInteger(row.\`year_to:int\`)
  }]->(p2)
} IN TRANSACTIONS OF 1000 ROWS;
"

echo "=== Importing P132 CD temporal overlaps ==="
docker exec neo4j-canada-census cypher-shell -u neo4j -p canadacensus123 --format plain "
LOAD CSV WITH HEADERS FROM 'file:///p132_spatiotemporally_overlaps_with_cd.csv' AS row
CALL { WITH row
  MATCH (p1:E93_Presence {presence_id: row.\`:START_ID\`})
  MATCH (p2:E93_Presence {presence_id: row.\`:END_ID\`})
  CREATE (p1)-[:P132_spatiotemporally_overlaps_with {
    overlap_type: row.overlap_type,
    iou: toFloat(row.\`iou:float\`),
    from_fraction: toFloat(row.\`from_fraction:float\`),
    to_fraction: toFloat(row.\`to_fraction:float\`),
    year_from: toInteger(row.\`year_from:int\`),
    year_to: toInteger(row.\`year_to:int\`)
  }]->(p2)
} IN TRANSACTIONS OF 1000 ROWS;
"

echo "=== All relationships imported! ==="
