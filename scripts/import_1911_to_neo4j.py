#!/usr/bin/env python3
"""
Import corrected 1911 V2T2 data to Neo4j Canada Census database.
"""
from neo4j import GraphDatabase
from pathlib import Path
import pandas as pd
import sys

NEO4J_URI = "bolt://localhost:7690"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "canadacensus123"
DATA_DIR = Path("/home/jic823/GraphRAG_test/neo4j_cidoc_crm")

def import_1911_data():
    """Import corrected 1911 data to Neo4j."""

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        with driver.session() as session:
            # Import E93_Presence (CSD) nodes for 1911
            print("Importing E93_Presence (CSD) nodes for 1911...")
            df = pd.read_csv(DATA_DIR / 'e93_presence_1911.csv')
            for _, row in df.iterrows():
                session.run("""
                    CREATE (p:E93_Presence {
                        presence_id: $presence_id,
                        csd_tcpuid: $tcpuid,
                        census_year: $census_year,
                        area_sqm: $area_sqm
                    })
                """, presence_id=row['presence_id:ID'], tcpuid=row['csd_tcpuid'],
                     census_year=int(row['census_year:int']), area_sqm=float(row['area_sqm:float']))
            print(f"  ✓ Created {len(df)} E93_Presence (CSD) nodes")

            # Import E94_Space_Primitive nodes for 1911
            print("Importing E94_Space_Primitive nodes for 1911...")
            df = pd.read_csv(DATA_DIR / 'e94_space_primitive_1911.csv')
            for _, row in df.iterrows():
                session.run("""
                    CREATE (s:E94_Space_Primitive {
                        space_id: $space_id,
                        latitude: $latitude,
                        longitude: $longitude,
                        crs: $crs
                    })
                """, space_id=row['space_id:ID'], latitude=float(row['latitude:float']),
                     longitude=float(row['longitude:float']), crs=row['crs'])
            print(f"  ✓ Created {len(df)} E94_Space_Primitive nodes")

            # Import P166_was_a_presence_of relationships
            print("Importing P166_was_a_presence_of relationships...")
            df = pd.read_csv(DATA_DIR / 'p166_was_presence_of_1911.csv')
            for _, row in df.iterrows():
                session.run("""
                    MATCH (presence:E93_Presence {presence_id: $start_id})
                    MATCH (place:E53_Place {place_id: $end_id})
                    CREATE (presence)-[:P166_was_a_presence_of]->(place)
                """, start_id=row[':START_ID'], end_id=row[':END_ID'])
            print(f"  ✓ Created {len(df)} P166 relationships")

            # Import P164_is_temporally_specified_by relationships
            print("Importing P164_is_temporally_specified_by relationships...")
            df = pd.read_csv(DATA_DIR / 'p164_temporally_specified_by_1911.csv')
            for _, row in df.iterrows():
                session.run("""
                    MATCH (presence:E93_Presence {presence_id: $start_id})
                    MATCH (period:E4_Period {period_id: $end_id})
                    CREATE (presence)-[:P164_is_temporally_specified_by]->(period)
                """, start_id=row[':START_ID'], end_id=row[':END_ID'])
            print(f"  ✓ Created {len(df)} P164 relationships")

            # Import P161_has_spatial_projection relationships
            print("Importing P161_has_spatial_projection relationships...")
            df = pd.read_csv(DATA_DIR / 'p161_spatial_projection_1911.csv')
            for _, row in df.iterrows():
                session.run("""
                    MATCH (presence:E93_Presence {presence_id: $start_id})
                    MATCH (space:E94_Space_Primitive {space_id: $end_id})
                    CREATE (presence)-[:P161_has_spatial_projection]->(space)
                """, start_id=row[':START_ID'], end_id=row[':END_ID'])
            print(f"  ✓ Created {len(df)} P161 relationships")

            # Import P89_falls_within relationships
            print("Importing P89_falls_within relationships...")
            df = pd.read_csv(DATA_DIR / 'p89_falls_within_1911.csv')
            for _, row in df.iterrows():
                session.run("""
                    MATCH (csd:E93_Presence {presence_id: $start_id})
                    MATCH (cd:E53_Place {place_id: $end_id})
                    CREATE (csd)-[:P89_falls_within {
                        during_period: $during_period
                    }]->(cd)
                """, start_id=row[':START_ID'], end_id=row[':END_ID'],
                     during_period=row['during_period'])
            print(f"  ✓ Created {len(df)} P89 relationships")

            # Import P122_borders_with relationships
            print("Importing P122_borders_with relationships...")
            df = pd.read_csv(DATA_DIR / 'p122_borders_with_1911.csv')
            for _, row in df.iterrows():
                session.run("""
                    MATCH (p1:E93_Presence {presence_id: $start_id})
                    MATCH (p2:E93_Presence {presence_id: $end_id})
                    CREATE (p1)-[:P122_borders_with {
                        shared_border_length_m: $border_length,
                        during_period: $during_period
                    }]->(p2)
                """, start_id=row[':START_ID'], end_id=row[':END_ID'],
                     border_length=float(row['shared_border_length_m:float']),
                     during_period=row['during_period'])
            print(f"  ✓ Created {len(df)} P122 relationships")

            # Import CD presences
            print("Importing E93_Presence (CD) nodes for 1911...")
            df = pd.read_csv(DATA_DIR / 'e93_presence_cd_1911.csv')
            for _, row in df.iterrows():
                session.run("""
                    CREATE (p:E93_Presence {
                        presence_id: $presence_id,
                        cd_id: $cd_id,
                        census_year: $census_year,
                        area_sqm: $area_sqm,
                        num_csds: $num_csds
                    })
                """, presence_id=row['presence_id:ID'], cd_id=row['cd_id'],
                     census_year=int(row['census_year:int']), area_sqm=float(row['area_sqm:float']),
                     num_csds=int(row['num_csds:int']))
            print(f"  ✓ Created {len(df)} E93_Presence (CD) nodes")

            # Import CD space primitives
            print("Importing E94_Space_Primitive (CD) nodes for 1911...")
            df = pd.read_csv(DATA_DIR / 'e94_space_primitive_cd_1911.csv')
            for _, row in df.iterrows():
                session.run("""
                    CREATE (s:E94_Space_Primitive {
                        space_id: $space_id,
                        latitude: $latitude,
                        longitude: $longitude,
                        crs: $crs
                    })
                """, space_id=row['space_id:ID'], latitude=float(row['latitude:float']),
                     longitude=float(row['longitude:float']), crs=row['crs'])
            print(f"  ✓ Created {len(df)} E94_Space_Primitive (CD) nodes")

            # Import CD P166 relationships
            print("Importing P166_was_a_presence_of (CD) relationships...")
            df = pd.read_csv(DATA_DIR / 'p166_was_presence_of_cd_1911.csv')
            for _, row in df.iterrows():
                session.run("""
                    MATCH (presence:E93_Presence {presence_id: $start_id})
                    MATCH (place:E53_Place {place_id: $end_id})
                    CREATE (presence)-[:P166_was_a_presence_of]->(place)
                """, start_id=row[':START_ID'], end_id=row[':END_ID'])
            print(f"  ✓ Created {len(df)} P166 (CD) relationships")

            # Import CD P164 relationships
            print("Importing P164_is_temporally_specified_by (CD) relationships...")
            df = pd.read_csv(DATA_DIR / 'p164_temporally_specified_by_cd_1911.csv')
            for _, row in df.iterrows():
                session.run("""
                    MATCH (presence:E93_Presence {presence_id: $start_id})
                    MATCH (period:E4_Period {period_id: $end_id})
                    CREATE (presence)-[:P164_is_temporally_specified_by]->(period)
                """, start_id=row[':START_ID'], end_id=row[':END_ID'])
            print(f"  ✓ Created {len(df)} P164 (CD) relationships")

            # Import CD P161 relationships
            print("Importing P161_has_spatial_projection (CD) relationships...")
            df = pd.read_csv(DATA_DIR / 'p161_spatial_projection_cd_1911.csv')
            for _, row in df.iterrows():
                session.run("""
                    MATCH (presence:E93_Presence {presence_id: $start_id})
                    MATCH (space:E94_Space_Primitive {space_id: $end_id})
                    CREATE (presence)-[:P161_has_spatial_projection]->(space)
                """, start_id=row[':START_ID'], end_id=row[':END_ID'])
            print(f"  ✓ Created {len(df)} P161 (CD) relationships")

            # Import P10_falls_within (CSD → CD) relationships
            print("Importing P10_falls_within (CSD → CD presence) relationships...")
            df = pd.read_csv(DATA_DIR / 'p10_csd_within_cd_presence_1911.csv')
            for _, row in df.iterrows():
                session.run("""
                    MATCH (csd:E93_Presence {presence_id: $start_id})
                    MATCH (cd:E93_Presence {presence_id: $end_id})
                    CREATE (csd)-[:P10_falls_within {
                        during_period: $during_period
                    }]->(cd)
                """, start_id=row[':START_ID'], end_id=row[':END_ID'],
                     during_period=row['during_period'])
            print(f"  ✓ Created {len(df)} P10 (CSD→CD) relationships")

            print("\n✓ 1911 V2T2 data import complete!")

    finally:
        driver.close()

if __name__ == "__main__":
    import_1911_data()
