#!/usr/bin/env python3
"""
Import provenance data (actors, creation events, information objects) to Neo4j.
"""
from neo4j import GraphDatabase
from pathlib import Path
import pandas as pd

NEO4J_URI = "bolt://localhost:7690"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "canadacensus123"
DATA_DIR = Path("/home/jic823/GraphRAG_test/neo4j_provenance")

def import_provenance():
    """Import provenance metadata to Neo4j."""

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        with driver.session() as session:
            # Import E39_Actor nodes
            print("Importing E39_Actor nodes...")
            df = pd.read_csv(DATA_DIR / 'e39_actors.csv')
            for _, row in df.iterrows():
                session.run("""
                    MERGE (a:E39_Actor {actor_id: $actor_id})
                    SET a.name = $name,
                        a.type = $type,
                        a.affiliation = $affiliation,
                        a.role = $role,
                        a.website = $website
                """, actor_id=row['actor_id:ID'], name=row['name'],
                     type=row['type'], affiliation=row['affiliation'],
                     role=row['role'], website=row['website'] if pd.notna(row['website']) else None)
            print(f"  ✓ Processed {len(df)} E39_Actor nodes")

            # Import E65_Creation nodes
            print("Importing E65_Creation nodes...")
            df = pd.read_csv(DATA_DIR / 'e65_creation.csv')
            for _, row in df.iterrows():
                session.run("""
                    MERGE (c:E65_Creation {creation_id: $creation_id})
                    SET c.label = $label,
                        c.description = $description,
                        c.timespan_start = $timespan_start,
                        c.timespan_end = $timespan_end
                """, creation_id=row['creation_id:ID'], label=row['label'],
                     description=row['description'], timespan_start=row['timespan_start'],
                     timespan_end=row['timespan_end'])
            print(f"  ✓ Processed {len(df)} E65_Creation nodes")

            # Import E73_Information_Object nodes (provenance sources)
            print("Importing E73_Information_Object (provenance) nodes...")
            df = pd.read_csv(DATA_DIR / 'e73_information_objects_provenance.csv')
            for _, row in df.iterrows():
                session.run("""
                    MERGE (i:E73_Information_Object {info_object_id: $info_object_id})
                    SET i.label = $label,
                        i.source_table = $source_table,
                        i.access_uri = $access_uri,
                        i.landing_page = $landing_page
                """, info_object_id=row['info_object_id:ID'], label=row['label'],
                     source_table=row['source_table'],
                     access_uri=row['access_uri'] if pd.notna(row['access_uri']) else None,
                     landing_page=row['landing_page'] if pd.notna(row['landing_page']) else None)
            print(f"  ✓ Processed {len(df)} E73_Information_Object (provenance) nodes")

            # Import E30_Right nodes (licenses)
            print("Importing E30_Right nodes...")
            df = pd.read_csv(DATA_DIR / 'e30_rights.csv')
            for _, row in df.iterrows():
                session.run("""
                    MERGE (r:E30_Right {right_id: $right_id})
                    SET r.label = $label,
                        r.license_uri = $license_uri
                """, right_id=row['right_id:ID'], label=row['label'],
                     license_uri=row['license_uri'])
            print(f"  ✓ Processed {len(df)} E30_Right nodes")

            # Import P14_carried_out relationships
            print("Importing P14_carried_out relationships...")
            df = pd.read_csv(DATA_DIR / 'p14_carried_out.csv')
            for _, row in df.iterrows():
                session.run("""
                    MATCH (a:E39_Actor {actor_id: $start_id})
                    MATCH (c:E65_Creation {creation_id: $end_id})
                    MERGE (a)-[:P14_carried_out]->(c)
                """, start_id=row[':START_ID'], end_id=row[':END_ID'])
            print(f"  ✓ Created {len(df)} P14_carried_out relationships")

            # Import P67_refers_to relationships
            print("Importing P67_refers_to relationships...")
            df = pd.read_csv(DATA_DIR / 'p67_refers_to.csv')
            for _, row in df.iterrows():
                session.run("""
                    MATCH (i:E73_Information_Object {info_object_id: $start_id})
                    MATCH (target) WHERE elementId(target) = $end_id OR
                                        target.period_id = $end_id OR
                                        target.place_id = $end_id
                    MERGE (i)-[:P67_refers_to]->(target)
                """, start_id=row[':START_ID'], end_id=row[':END_ID'])
            print(f"  ✓ Processed {len(df)} P67_refers_to relationships")

            # Import P104_is_subject_to relationships
            print("Importing P104_is_subject_to relationships...")
            df = pd.read_csv(DATA_DIR / 'p104_is_subject_to.csv')
            for _, row in df.iterrows():
                session.run("""
                    MATCH (i:E73_Information_Object {info_object_id: $start_id})
                    MATCH (r:E30_Right {right_id: $end_id})
                    MERGE (i)-[:P104_is_subject_to]->(r)
                """, start_id=row[':START_ID'], end_id=row[':END_ID'])
            print(f"  ✓ Created {len(df)} P104_is_subject_to relationships")

            print("\n✓ Provenance data import complete!")

    finally:
        driver.close()

if __name__ == "__main__":
    import_provenance()
