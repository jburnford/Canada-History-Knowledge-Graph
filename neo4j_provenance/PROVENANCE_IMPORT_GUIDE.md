# CIDOC-CRM Provenance Entities - Neo4j Import Guide

**Created**: September 30, 2025
**Status**: Ready for Neo4j import

## Overview

Provenance entities track the origin, authorship, licensing, and creation of the Canadian Census dataset according to FAIR data principles and CIDOC-CRM standards.

## Entities Generated

### E33_Linguistic_Object - Citations and DOIs (9 entities)
- 1 spatial dataset citation (TCP polygons)
- 8 census year citations (1851-1921 aggregate data)
- Each includes: full citation text, DOI, version, publication date

### E30_Right - License Information (1 entity)
- CC BY 4.0 International license
- Permits use, sharing, and adaptation with attribution

### E39_Actor - Creators and Contributors (7 entities)
- 5 Principal Investigators:
  - Geoff Cunfer (University of Saskatchewan)
  - Rhianne Billard (University of Saskatchewan)
  - Sauvelm McClean (University of Saskatchewan)
  - Laurent Richard (Université Laval)
  - Marc St-Hilaire (Université Laval)
- 1 Project Organization: The Canadian Peoples / Les populations canadiennes
- 1 Repository: Borealis - Canadian Dataverse

### E65_Creation - Dataset Creation Activity (1 entity)
- Represents the development and publication process (2018-2023)

### E73_Information_Object - Source Files (9 entities)
- 1 spatial GDB file (TCP_CANADA_CSD_202306.gdb)
- 8 census year aggregate data collections (1851-1921)
- Each includes: access URI, landing page URL

## Relationships

### P67_refers_to (9 relationships)
**Pattern**: E33_Linguistic_Object → E73_Information_Object
**Meaning**: Citation describes/refers to the source file

### P104_is_subject_to (9 relationships)
**Pattern**: E73_Information_Object → E30_Right
**Meaning**: Source file is subject to CC BY 4.0 license

### P14_carried_out (6 relationships)
**Pattern**: E39_Actor → E65_Creation
**Meaning**: Actor participated in dataset creation

## Neo4j Import Instructions

### Step 1: Create Constraints

```cypher
// E33_Linguistic_Object constraint
CREATE CONSTRAINT e33_id IF NOT EXISTS
  FOR (n:E33_Linguistic_Object) REQUIRE n.`citation_id:ID` IS UNIQUE;

// E30_Right constraint
CREATE CONSTRAINT e30_id IF NOT EXISTS
  FOR (n:E30_Right) REQUIRE n.`right_id:ID` IS UNIQUE;

// E39_Actor constraint
CREATE CONSTRAINT e39_id IF NOT EXISTS
  FOR (n:E39_Actor) REQUIRE n.`actor_id:ID` IS UNIQUE;

// E65_Creation constraint
CREATE CONSTRAINT e65_id IF NOT EXISTS
  FOR (n:E65_Creation) REQUIRE n.`creation_id:ID` IS UNIQUE;

// E73_Information_Object constraint (if not already created)
CREATE CONSTRAINT e73_id IF NOT EXISTS
  FOR (n:E73_Information_Object) REQUIRE n.`info_object_id:ID` IS UNIQUE;
```

### Step 2: Import Entity Nodes

```cypher
// E33_Linguistic_Object (Citations/DOIs)
LOAD CSV WITH HEADERS FROM 'file:///neo4j_provenance/e33_linguistic_objects.csv' AS row
CREATE (:E33_Linguistic_Object {
  citation_id: row.`citation_id:ID`,
  citation_text: row.citation_text,
  doi: row.doi,
  version: row.version,
  publication_date: row.publication_date
});

// E30_Right (License)
LOAD CSV WITH HEADERS FROM 'file:///neo4j_provenance/e30_rights.csv' AS row
CREATE (:E30_Right {
  right_id: row.`right_id:ID`,
  label: row.label,
  access_rights: row.access_rights,
  license_uri: row.license_uri,
  description: row.description
});

// E39_Actor (Creators)
LOAD CSV WITH HEADERS FROM 'file:///neo4j_provenance/e39_actors.csv' AS row
CREATE (:E39_Actor {
  actor_id: row.`actor_id:ID`,
  name: row.name,
  type: row.type,
  affiliation: row.affiliation,
  orcid: row.orcid,
  role: row.role,
  website: CASE WHEN row.website IS NOT NULL THEN row.website ELSE NULL END
});

// E65_Creation (Creation Activity)
LOAD CSV WITH HEADERS FROM 'file:///neo4j_provenance/e65_creation.csv' AS row
CREATE (:E65_Creation {
  creation_id: row.`creation_id:ID`,
  label: row.label,
  description: row.description,
  timespan_start: row.timespan_start,
  timespan_end: row.timespan_end
});

// E73_Information_Object (Source Files)
LOAD CSV WITH HEADERS FROM 'file:///neo4j_provenance/e73_information_objects_provenance.csv' AS row
CREATE (:E73_Information_Object {
  info_object_id: row.`info_object_id:ID`,
  label: row.label,
  source_table: row.source_table,
  file_hash: row.file_hash,
  access_uri: row.access_uri,
  landing_page: row.landing_page
});
```

### Step 3: Import Relationships

```cypher
// P67_refers_to: Citation → Information Object
LOAD CSV WITH HEADERS FROM 'file:///neo4j_provenance/p67_refers_to.csv' AS row
MATCH (citation:E33_Linguistic_Object {citation_id: row.`:START_ID`})
MATCH (source:E73_Information_Object {info_object_id: row.`:END_ID`})
CREATE (citation)-[:P67_refers_to {note: row.note}]->(source);

// P104_is_subject_to: Information Object → Right
LOAD CSV WITH HEADERS FROM 'file:///neo4j_provenance/p104_is_subject_to.csv' AS row
MATCH (source:E73_Information_Object {info_object_id: row.`:START_ID`})
MATCH (license:E30_Right {right_id: row.`:END_ID`})
CREATE (source)-[:P104_is_subject_to]->(license);

// P14_carried_out: Actor → Creation
LOAD CSV WITH HEADERS FROM 'file:///neo4j_provenance/p14_carried_out.csv' AS row
MATCH (actor:E39_Actor {actor_id: row.`:START_ID`})
MATCH (creation:E65_Creation {creation_id: row.`:END_ID`})
CREATE (actor)-[:P14_carried_out]->(creation);
```

## Validation Queries

### Count all provenance entities

```cypher
MATCH (e33:E33_Linguistic_Object) RETURN count(e33) AS citations;
// Expected: 9

MATCH (e30:E30_Right) RETURN count(e30) AS licenses;
// Expected: 1

MATCH (e39:E39_Actor) RETURN count(e39) AS actors;
// Expected: 7

MATCH (e65:E65_Creation) RETURN count(e65) AS creation_events;
// Expected: 1

MATCH (e73:E73_Information_Object) RETURN count(e73) AS sources;
// Expected: 9
```

### Count all provenance relationships

```cypher
MATCH ()-[r:P67_refers_to]->() RETURN count(r) AS p67_count;
// Expected: 9

MATCH ()-[r:P104_is_subject_to]->() RETURN count(r) AS p104_count;
// Expected: 9

MATCH ()-[r:P14_carried_out]->() RETURN count(r) AS p14_count;
// Expected: 6
```

### Verify citation → source → license chain

```cypher
MATCH (citation:E33_Linguistic_Object)-[:P67_refers_to]->(source:E73_Information_Object)-[:P104_is_subject_to]->(license:E30_Right)
RETURN citation.citation_id, source.label, license.label
ORDER BY citation.citation_id;
// Should return 9 rows showing complete provenance chain
```

### Verify actor → creation linkage

```cypher
MATCH (actor:E39_Actor)-[:P14_carried_out]->(creation:E65_Creation)
RETURN actor.name, actor.role, creation.label
ORDER BY actor.name;
// Should return 6 actors linked to creation activity
```

## Sample Research Queries

### 1. Get full citation for dataset

```cypher
MATCH (citation:E33_Linguistic_Object {citation_id: 'CITATION_TCP_SPATIAL'})
RETURN citation.citation_text AS citation,
       citation.doi AS doi,
       citation.version AS version;
```

### 2. Find all creators with their affiliations

```cypher
MATCH (actor:E39_Actor)-[:P14_carried_out]->(creation:E65_Creation)
WHERE actor.type = 'E21_Person'
RETURN actor.name AS creator,
       actor.affiliation AS institution,
       actor.role AS role
ORDER BY actor.name;
```

### 3. Get license information for all datasets

```cypher
MATCH (source:E73_Information_Object)-[:P104_is_subject_to]->(license:E30_Right)
RETURN source.label AS dataset,
       license.label AS license_name,
       license.license_uri AS license_url;
```

### 4. Complete provenance for a specific year

```cypher
MATCH (citation:E33_Linguistic_Object {citation_id: 'CITATION_CENSUS_1901'})
      -[:P67_refers_to]->(source:E73_Information_Object)
      -[:P104_is_subject_to]->(license:E30_Right)
MATCH (actor:E39_Actor)-[:P14_carried_out]->(creation:E65_Creation)
RETURN citation.citation_text AS citation,
       citation.doi AS doi,
       source.landing_page AS dataset_url,
       license.label AS license,
       collect(actor.name) AS creators;
```

### 5. Generate attribution statement

```cypher
MATCH (citation:E33_Linguistic_Object {citation_id: 'CITATION_TCP_SPATIAL'})
      -[:P67_refers_to]->(source:E73_Information_Object)
      -[:P104_is_subject_to]->(license:E30_Right)
RETURN citation.citation_text + ' Licensed under ' + license.label + ' (' + license.license_uri + ')' AS attribution;
```

## Integration with Census Observations

Connect E73_Information_Object provenance nodes to E16_Measurement census observations:

```cypher
// Example: Link 1901 measurements to their source and citation
MATCH (measurement:E16_Measurement)-[:P39_measured]->(presence:E93_Presence)
MATCH (presence)-[:P164_is_temporally_specified_by]->(period:E4_Period {year: 1901})
MATCH (source:E73_Information_Object {info_object_id: 'SOURCE_CENSUS_1901_AGGREGATE'})
CREATE (measurement)-[:P70_documents]->(source);

// Then query full provenance for a measurement
MATCH (measurement:E16_Measurement)
      -[:P70_documents]->(source:E73_Information_Object)
      <-[:P67_refers_to]-(citation:E33_Linguistic_Object)
MATCH (source)-[:P104_is_subject_to]->(license:E30_Right)
WHERE measurement.measurement_id = 'MEAS_ON001001_1901_POP_TOT'
RETURN measurement.label AS observation,
       citation.citation_text AS citation,
       license.label AS license;
```

## FAIR Data Principles

This provenance model ensures the dataset meets FAIR principles:

- **Findable**: DOIs and citations for all data sources
- **Accessible**: Direct access URIs and landing pages
- **Interoperable**: CIDOC-CRM standard ontology
- **Reusable**: Explicit CC BY 4.0 license, creator attribution, creation timeline

## Files Generated

```
neo4j_provenance/
├── e33_linguistic_objects.csv         # 9 citations with DOIs
├── e30_rights.csv                     # 1 license (CC BY 4.0)
├── e39_actors.csv                     # 7 creators and contributors
├── e65_creation.csv                   # 1 creation activity
├── e73_information_objects_provenance.csv # 9 source files
├── p67_refers_to.csv                  # 9 citation → source links
├── p104_is_subject_to.csv             # 9 source → license links
├── p14_carried_out.csv                # 6 actor → creation links
└── PROVENANCE_IMPORT_GUIDE.md         # This file
```

## Next Steps

1. Import provenance entities using Cypher statements above
2. Validate counts match expected totals
3. Link measurements to sources via P70_documents (if needed)
4. Generate attribution statements for publications
5. Use for FAIR data compliance reporting

## References

- **CIDOC-CRM**: http://www.cidoc-crm.org/
- **FAIR Principles**: https://www.go-fair.org/fair-principles/
- **Borealis**: https://borealisdata.ca/dataverse/census
- **The Canadian Peoples Project**: https://thecanadianpeoples.com/team/
