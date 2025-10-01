# E41_Appellation Name Variants - Neo4j Import Guide

**Created**: September 30, 2025
**Status**: Ready for Neo4j import

## Overview

E41_Appellation entities model canonical names and OCR-corrected variants for Census Subdivisions according to CIDOC-CRM P1_is_identified_by pattern.

## Data Sources

- **Canonical Names**: `canonical_names_final.csv` (OCR correction analysis)
- **Total CSD-year records**: 8949
- **OCR corrections applied**: 476
- **Intentional name changes preserved**: 8473

## Entities Generated

### E41_Appellation - Name Appellations (350 entities)
- **Canonical appellations**: 207 (corrected names for CSDs with OCR errors)
- **Variant appellations**: 143 (original OCR-error names from specific years)

### Relationship: P1_is_identified_by (350 relationships)
- **E53_Place → E41 (canonical)**: 207 links (persistent CSD to corrected name)
- **E93_Presence → E41 (variant)**: 143 links (CSD-year to OCR-error name actually used)

## Name Variant Categories

### 1. OCR Corrections (Canonical Names Applied)
**Examples**:
- "Melvern" (1891) → canonical: "Malvern" (spelling error)
- "Nictau" (1901) → canonical: "Nictaux" (spelling error)
- "Parker Cove" (1861) → canonical: "Parker's Cove" (apostrophe missing)

### 2. Intentional Name Changes (NOT Corrected)
**Examples**:
- "Berlin" (1911) → "Kitchener" (1921) - WWI rename
- Ward reorganizations in cities
- Municipal amalgamations

## CSV Format

### e41_appellations.csv

```csv
appellation_id:ID,:LABEL,name,type,tcpuid,year,notes
APP_ON001001_CANONICAL,E41_Appellation,Malvern,canonical,ON001001,,Canonical name for ON001001 (OCR corrected)
APP_ON001001_1891_VARIANT,E41_Appellation,Melvern,variant,ON001001,1891,OCR variant of "Malvern"
```

### p1_is_identified_by.csv

```csv
:START_ID,:END_ID,:TYPE,type
ON001001,APP_ON001001_CANONICAL,P1_is_identified_by,canonical_name
ON001001_1891,APP_ON001001_1891_VARIANT,P1_is_identified_by,variant_name
```

## Neo4j Import Instructions

### Step 1: Create Constraint

```cypher
// E41_Appellation constraint
CREATE CONSTRAINT e41_id IF NOT EXISTS
  FOR (n:E41_Appellation) REQUIRE n.`appellation_id:ID` IS UNIQUE;
```

### Step 2: Import E41 Appellations

```cypher
// E41_Appellation (Name variants)
LOAD CSV WITH HEADERS FROM 'file:///neo4j_appellations/e41_appellations.csv' AS row
CREATE (:E41_Appellation {
  appellation_id: row.`appellation_id:ID`,
  name: row.name,
  type: row.type,
  tcpuid: row.tcpuid,
  year: CASE WHEN row.year IS NOT NULL AND row.year <> '' THEN toInteger(row.year) ELSE NULL END,
  notes: row.notes
});
```

### Step 3: Import P1 Relationships

```cypher
// P1_is_identified_by: E53_Place -> E41 (canonical names)
LOAD CSV WITH HEADERS FROM 'file:///neo4j_appellations/p1_is_identified_by.csv' AS row
WHERE row.type = 'canonical_name'
MATCH (place:E53_Place {place_id: row.`:START_ID`})
MATCH (appellation:E41_Appellation {appellation_id: row.`:END_ID`})
CREATE (place)-[:P1_is_identified_by {type: row.type}]->(appellation);

// P1_is_identified_by: E93_Presence -> E41 (variant names)
LOAD CSV WITH HEADERS FROM 'file:///neo4j_appellations/p1_is_identified_by.csv' AS row
WHERE row.type = 'variant_name'
MATCH (presence:E93_Presence {presence_id: row.`:START_ID`})
MATCH (appellation:E41_Appellation {appellation_id: row.`:END_ID`})
CREATE (presence)-[:P1_is_identified_by {type: row.type}]->(appellation);
```

## Validation Queries

### Count appellations by type

```cypher
MATCH (a:E41_Appellation)
RETURN a.type AS type, count(*) AS count
ORDER BY count DESC;
// Expected: canonical ~207, variant ~143
```

### Count P1 relationships

```cypher
MATCH ()-[r:P1_is_identified_by]->()
RETURN count(r) AS total_p1;
// Expected: 350
```

### Find CSDs with canonical names

```cypher
MATCH (place:E53_Place)-[:P1_is_identified_by]->(canonical:E41_Appellation {type: 'canonical'})
RETURN place.place_id, place.name AS original, canonical.name AS canonical
LIMIT 20;
```

### Find OCR variants for a specific CSD

```cypher
MATCH (place:E53_Place {place_id: 'NS012030'})-[:P1_is_identified_by]->(canonical:E41_Appellation {type: 'canonical'})
MATCH (presence:E93_Presence)-[:P7_took_place_at]->(place)
OPTIONAL MATCH (presence)-[:P1_is_identified_by]->(variant:E41_Appellation {type: 'variant'})
MATCH (presence)-[:P164_is_temporally_specified_by]->(period:E4_Period)
RETURN period.year AS year,
       canonical.name AS canonical_name,
       variant.name AS variant_name_used
ORDER BY period.year;
```

## Sample Research Queries

### 1. Find all OCR corrections

```cypher
MATCH (place:E53_Place)-[:P1_is_identified_by]->(canonical:E41_Appellation {type: 'canonical'})
MATCH (presence:E93_Presence)-[:P7_took_place_at]->(place)
      -[:P1_is_identified_by]->(variant:E41_Appellation {type: 'variant'})
WHERE canonical.name <> variant.name
RETURN place.place_id AS tcpuid,
       canonical.name AS corrected_name,
       variant.name AS ocr_error,
       variant.year AS year_of_error
ORDER BY place.place_id, variant.year;
```

### 2. CSDs with most name variants

```cypher
MATCH (place:E53_Place)-[:P1_is_identified_by]->(canonical:E41_Appellation {type: 'canonical'})
MATCH (presence:E93_Presence)-[:P7_took_place_at]->(place)
      -[:P1_is_identified_by]->(variant:E41_Appellation {type: 'variant'})
RETURN place.place_id AS tcpuid,
       canonical.name AS canonical_name,
       count(DISTINCT variant.name) AS num_variants,
       collect(DISTINCT variant.name) AS variant_names
ORDER BY num_variants DESC
LIMIT 10;
```

### 3. Track name corrections through time

```cypher
MATCH (place:E53_Place {place_id: 'NS012030'})-[:P1_is_identified_by]->(canonical:E41_Appellation)
MATCH (presence:E93_Presence)-[:P7_took_place_at]->(place)
MATCH (presence)-[:P164_is_temporally_specified_by]->(period:E4_Period)
OPTIONAL MATCH (presence)-[:P1_is_identified_by]->(variant:E41_Appellation {type: 'variant'})
RETURN period.year AS year,
       COALESCE(variant.name, canonical.name) AS name_used,
       variant IS NOT NULL AS was_ocr_error
ORDER BY period.year;
```

## Integration with Canonical Names Analysis

This E41 model preserves the analysis from `canonical_names_final.csv`:
- **should_apply=True**: OCR corrections → E41 canonical appellations created
- **reason=name_change**: Intentional renames → NOT modeled as OCR errors
- **avg_similarity, min_similarity**: Used to determine if names are similar enough to be variants

## Data Quality Notes

- **Canonical names**: Only created for CSDs with avg_similarity ≥ 70% and min_similarity ≥ 60%
- **Variant preservation**: Original OCR-error names retained for historical accuracy
- **Intentional changes**: Berlin→Kitchener, ward reorganizations NOT treated as OCR errors

## Files Generated

```
neo4j_appellations/
├── e41_appellations.csv           # 350 appellation nodes
├── p1_is_identified_by.csv        # 350 relationships
└── E41_APPELLATION_GUIDE.md       # This file
```

## Next Steps

1. Import E41 appellations using Cypher above
2. Validate counts match expected totals
3. Query OCR corrections for data quality reporting
4. Use canonical names in publications and citations

## References

- **CIDOC-CRM P1**: http://www.cidoc-crm.org/Property/p1-is-identified-by/version-7.1.1
- **Source Analysis**: `canonical_names_final.csv`
- **Generation Script**: `scripts/build_e41_appellations.py`
