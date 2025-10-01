#!/usr/bin/env python3
"""
Generate E41_Appellation entities for CSD name variants and OCR corrections.

Models canonical names vs variants according to CIDOC-CRM P1_is_identified_by.

Author: Claude Code
Date: September 30, 2025
"""

import pandas as pd
from pathlib import Path
import argparse
import sys


def load_canonical_names(canonical_file: Path) -> pd.DataFrame:
    """Load canonical names analysis."""
    df = pd.read_csv(canonical_file)
    print(f"  Loaded {len(df)} CSD-year records from {canonical_file.name}", file=sys.stderr)
    return df


def create_e41_appellations(canonical_df: pd.DataFrame) -> pd.DataFrame:
    """
    Create E41_Appellation nodes for:
    1. Canonical names (corrected OCR variants)
    2. Original variant names that were OCR errors
    """
    appellations = []

    # Get unique CSDs with canonical names applied (OCR corrections)
    ocr_corrections = canonical_df[canonical_df['should_apply'] == True].copy()

    print(f"\n  Processing {len(ocr_corrections)} OCR correction records...", file=sys.stderr)

    # Group by TCPUID to get all name variants
    for tcpuid, group in ocr_corrections.groupby('tcpuid'):
        canonical_name = group.iloc[0]['canonical_name']

        # Create canonical appellation
        appellations.append({
            'appellation_id:ID': f'APP_{tcpuid}_CANONICAL',
            ':LABEL': 'E41_Appellation',
            'name': canonical_name,
            'type': 'canonical',
            'tcpuid': tcpuid,
            'notes': f'Canonical name for {tcpuid} (OCR corrected)'
        })

        # Create variant appellations for each original name
        for _, row in group.iterrows():
            original = row['original_name']
            year = row['year']

            if original != canonical_name:
                appellations.append({
                    'appellation_id:ID': f'APP_{tcpuid}_{year}_VARIANT',
                    ':LABEL': 'E41_Appellation',
                    'name': original,
                    'type': 'variant',
                    'tcpuid': tcpuid,
                    'year': year,
                    'notes': f'OCR variant of "{canonical_name}"'
                })

    # Also track intentional name changes (for context)
    name_changes = canonical_df[canonical_df['reason'] == 'name_change'].copy()
    print(f"  Found {len(name_changes)} intentional name changes (not creating E41s)", file=sys.stderr)

    return pd.DataFrame(appellations)


def create_p1_is_identified_by(canonical_df: pd.DataFrame) -> pd.DataFrame:
    """
    P1_is_identified_by: E53_Place -> E41_Appellation

    Links:
    1. E53_Place -> canonical E41_Appellation (primary name)
    2. E93_Presence -> variant E41_Appellation (name used in that year)
    """
    relationships = []

    # Get OCR corrections
    ocr_corrections = canonical_df[canonical_df['should_apply'] == True].copy()

    # For each TCPUID, link E53_Place to canonical appellation
    for tcpuid in ocr_corrections['tcpuid'].unique():
        relationships.append({
            ':START_ID': tcpuid,  # E53_Place ID
            ':END_ID': f'APP_{tcpuid}_CANONICAL',
            ':TYPE': 'P1_is_identified_by',
            'type': 'canonical_name'
        })

    # For each E93_Presence, link to variant appellation (if different from canonical)
    for _, row in ocr_corrections.iterrows():
        if row['original_name'] != row['canonical_name']:
            presence_id = f"{row['tcpuid']}_{row['year']}"
            relationships.append({
                ':START_ID': presence_id,  # E93_Presence ID
                ':END_ID': f"APP_{row['tcpuid']}_{row['year']}_VARIANT",
                ':TYPE': 'P1_is_identified_by',
                'type': 'variant_name'
            })

    return pd.DataFrame(relationships)


def create_readme(out_dir: Path, stats: dict):
    """Create import guide for E41 Appellation data."""
    readme_content = f"""# E41_Appellation Name Variants - Neo4j Import Guide

**Created**: September 30, 2025
**Status**: Ready for Neo4j import

## Overview

E41_Appellation entities model canonical names and OCR-corrected variants for Census Subdivisions according to CIDOC-CRM P1_is_identified_by pattern.

## Data Sources

- **Canonical Names**: `canonical_names_final.csv` (OCR correction analysis)
- **Total CSD-year records**: {stats['total_records']}
- **OCR corrections applied**: {stats['ocr_corrections']}
- **Intentional name changes preserved**: {stats['name_changes']}

## Entities Generated

### E41_Appellation - Name Appellations ({stats['total_appellations']} entities)
- **Canonical appellations**: {stats['canonical_appellations']} (corrected names for CSDs with OCR errors)
- **Variant appellations**: {stats['variant_appellations']} (original OCR-error names from specific years)

### Relationship: P1_is_identified_by ({stats['total_relationships']} relationships)
- **E53_Place → E41 (canonical)**: {stats['canonical_links']} links (persistent CSD to corrected name)
- **E93_Presence → E41 (variant)**: {stats['variant_links']} links (CSD-year to OCR-error name actually used)

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
CREATE (:E41_Appellation {{
  appellation_id: row.`appellation_id:ID`,
  name: row.name,
  type: row.type,
  tcpuid: row.tcpuid,
  year: CASE WHEN row.year IS NOT NULL AND row.year <> '' THEN toInteger(row.year) ELSE NULL END,
  notes: row.notes
}});
```

### Step 3: Import P1 Relationships

```cypher
// P1_is_identified_by: E53_Place -> E41 (canonical names)
LOAD CSV WITH HEADERS FROM 'file:///neo4j_appellations/p1_is_identified_by.csv' AS row
WHERE row.type = 'canonical_name'
MATCH (place:E53_Place {{place_id: row.`:START_ID`}})
MATCH (appellation:E41_Appellation {{appellation_id: row.`:END_ID`}})
CREATE (place)-[:P1_is_identified_by {{type: row.type}}]->(appellation);

// P1_is_identified_by: E93_Presence -> E41 (variant names)
LOAD CSV WITH HEADERS FROM 'file:///neo4j_appellations/p1_is_identified_by.csv' AS row
WHERE row.type = 'variant_name'
MATCH (presence:E93_Presence {{presence_id: row.`:START_ID`}})
MATCH (appellation:E41_Appellation {{appellation_id: row.`:END_ID`}})
CREATE (presence)-[:P1_is_identified_by {{type: row.type}}]->(appellation);
```

## Validation Queries

### Count appellations by type

```cypher
MATCH (a:E41_Appellation)
RETURN a.type AS type, count(*) AS count
ORDER BY count DESC;
// Expected: canonical ~{stats['canonical_appellations']}, variant ~{stats['variant_appellations']}
```

### Count P1 relationships

```cypher
MATCH ()-[r:P1_is_identified_by]->()
RETURN count(r) AS total_p1;
// Expected: {stats['total_relationships']}
```

### Find CSDs with canonical names

```cypher
MATCH (place:E53_Place)-[:P1_is_identified_by]->(canonical:E41_Appellation {{type: 'canonical'}})
RETURN place.place_id, place.name AS original, canonical.name AS canonical
LIMIT 20;
```

### Find OCR variants for a specific CSD

```cypher
MATCH (place:E53_Place {{place_id: 'NS012030'}})-[:P1_is_identified_by]->(canonical:E41_Appellation {{type: 'canonical'}})
MATCH (presence:E93_Presence)-[:P7_took_place_at]->(place)
OPTIONAL MATCH (presence)-[:P1_is_identified_by]->(variant:E41_Appellation {{type: 'variant'}})
MATCH (presence)-[:P164_is_temporally_specified_by]->(period:E4_Period)
RETURN period.year AS year,
       canonical.name AS canonical_name,
       variant.name AS variant_name_used
ORDER BY period.year;
```

## Sample Research Queries

### 1. Find all OCR corrections

```cypher
MATCH (place:E53_Place)-[:P1_is_identified_by]->(canonical:E41_Appellation {{type: 'canonical'}})
MATCH (presence:E93_Presence)-[:P7_took_place_at]->(place)
      -[:P1_is_identified_by]->(variant:E41_Appellation {{type: 'variant'}})
WHERE canonical.name <> variant.name
RETURN place.place_id AS tcpuid,
       canonical.name AS corrected_name,
       variant.name AS ocr_error,
       variant.year AS year_of_error
ORDER BY place.place_id, variant.year;
```

### 2. CSDs with most name variants

```cypher
MATCH (place:E53_Place)-[:P1_is_identified_by]->(canonical:E41_Appellation {{type: 'canonical'}})
MATCH (presence:E93_Presence)-[:P7_took_place_at]->(place)
      -[:P1_is_identified_by]->(variant:E41_Appellation {{type: 'variant'}})
RETURN place.place_id AS tcpuid,
       canonical.name AS canonical_name,
       count(DISTINCT variant.name) AS num_variants,
       collect(DISTINCT variant.name) AS variant_names
ORDER BY num_variants DESC
LIMIT 10;
```

### 3. Track name corrections through time

```cypher
MATCH (place:E53_Place {{place_id: 'NS012030'}})-[:P1_is_identified_by]->(canonical:E41_Appellation)
MATCH (presence:E93_Presence)-[:P7_took_place_at]->(place)
MATCH (presence)-[:P164_is_temporally_specified_by]->(period:E4_Period)
OPTIONAL MATCH (presence)-[:P1_is_identified_by]->(variant:E41_Appellation {{type: 'variant'}})
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
├── e41_appellations.csv           # {stats['total_appellations']} appellation nodes
├── p1_is_identified_by.csv        # {stats['total_relationships']} relationships
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
"""

    readme_path = out_dir / 'E41_APPELLATION_GUIDE.md'
    readme_path.write_text(readme_content)
    print(f"\n  ✓ Import guide created: {readme_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Generate E41_Appellation entities for name variants')
    parser.add_argument('--canonical-names', required=True, help='canonical_names_final.csv file')
    parser.add_argument('--out', required=True, help='Output directory')
    args = parser.parse_args()

    canonical_file = Path(args.canonical_names)
    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True, parents=True)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Generating E41_Appellation Name Variants", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # Load canonical names analysis
    print(f"\nLoading canonical names analysis...", file=sys.stderr)
    canonical_df = load_canonical_names(canonical_file)

    # Generate E41 appellations
    print(f"\nCreating E41_Appellation entities...", file=sys.stderr)
    appellations = create_e41_appellations(canonical_df)

    e41_file = out_dir / 'e41_appellations.csv'
    appellations.to_csv(e41_file, index=False)
    print(f"  ✓ E41_Appellation: {len(appellations)} appellations → {e41_file}", file=sys.stderr)

    # Generate P1 relationships
    print(f"\nCreating P1_is_identified_by relationships...", file=sys.stderr)
    p1_relationships = create_p1_is_identified_by(canonical_df)

    p1_file = out_dir / 'p1_is_identified_by.csv'
    p1_relationships.to_csv(p1_file, index=False)
    print(f"  ✓ P1_is_identified_by: {len(p1_relationships)} relationships → {p1_file}", file=sys.stderr)

    # Calculate statistics
    stats = {
        'total_records': len(canonical_df),
        'ocr_corrections': len(canonical_df[canonical_df['should_apply'] == True]),
        'name_changes': len(canonical_df[canonical_df['reason'] == 'name_change']),
        'total_appellations': len(appellations),
        'canonical_appellations': len(appellations[appellations['type'] == 'canonical']),
        'variant_appellations': len(appellations[appellations['type'] == 'variant']),
        'total_relationships': len(p1_relationships),
        'canonical_links': len(p1_relationships[p1_relationships['type'] == 'canonical_name']),
        'variant_links': len(p1_relationships[p1_relationships['type'] == 'variant_name'])
    }

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"Total appellations: {stats['total_appellations']}", file=sys.stderr)
    print(f"  Canonical: {stats['canonical_appellations']} (corrected names)", file=sys.stderr)
    print(f"  Variants: {stats['variant_appellations']} (OCR errors)", file=sys.stderr)
    print(f"\nTotal P1 relationships: {stats['total_relationships']}", file=sys.stderr)
    print(f"  E53_Place → canonical: {stats['canonical_links']}", file=sys.stderr)
    print(f"  E93_Presence → variant: {stats['variant_links']}", file=sys.stderr)
    print(f"\nOutput directory: {out_dir}/", file=sys.stderr)

    # Create import guide
    create_readme(out_dir, stats)
    print(f"", file=sys.stderr)


if __name__ == '__main__':
    main()
