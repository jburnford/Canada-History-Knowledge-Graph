#!/usr/bin/env python3
"""
Generate E41_Appellation entities with persistent place identities.

Fork of build_e41_appellations.py that:
1. Links canonical E41_Appellation nodes to persistent_place_id (not raw tcpuid)
2. Keeps variant appellations linked from E93_Presence nodes (unchanged)
3. Adds E42_Identifier nodes for TCP UIDs on each E93_Presence (provenance)
"""

import pandas as pd
from pathlib import Path
import argparse
import sys


def load_persistent_mapping(places_dir: Path) -> dict:
    """Load tcpuid -> persistent_place_id mapping."""
    mapping_file = places_dir / "tcpuid_year_to_place.csv"
    df = pd.read_csv(mapping_file)

    # For canonical appellations, we need tcpuid -> persistent_place_id
    # A tcpuid may map to different persistent places in different years,
    # but for canonical names we need the primary mapping.
    # Use the registry to get the canonical mapping.
    registry_file = places_dir / "persistent_place_registry.csv"
    registry_df = pd.read_csv(registry_file)

    # Build tcpuid -> persistent_place_id from anchor_tcpuid
    tcpuid_to_place = {}
    for _, row in registry_df.iterrows():
        tcpuid_to_place[row['anchor_tcpuid']] = row['persistent_place_id']

    # Also build (tcpuid, year) -> persistent_place_id for presence lookups
    year_mapping = {}
    for _, row in df.iterrows():
        year_mapping[(row['tcpuid'], int(row['year']))] = row['persistent_place_id']

    # For each raw tcpuid, find which persistent place it belongs to
    # (could be in multiple years but should map to same place via SAME_AS)
    raw_to_place = {}
    for (uid, yr), pid in year_mapping.items():
        if uid not in raw_to_place:
            raw_to_place[uid] = pid

    print(f"  Loaded {len(raw_to_place)} tcpuid -> persistent_place_id mappings", file=sys.stderr)
    return raw_to_place, year_mapping


def create_e41_appellations(canonical_df: pd.DataFrame) -> pd.DataFrame:
    """Create E41_Appellation nodes (same as v1)."""
    appellations = []

    ocr_corrections = canonical_df[canonical_df['should_apply'] == True].copy()
    print(f"\n  Processing {len(ocr_corrections)} OCR correction records...", file=sys.stderr)

    for tcpuid, group in ocr_corrections.groupby('tcpuid'):
        canonical_name = group.iloc[0]['canonical_name']

        appellations.append({
            'appellation_id:ID': f'APP_{tcpuid}_CANONICAL',
            ':LABEL': 'E41_Appellation',
            'name': canonical_name,
            'type': 'canonical',
            'tcpuid': tcpuid,
            'notes': f'Canonical name for {tcpuid} (OCR corrected)'
        })

        for _, row in group.iterrows():
            original = row['original_name']
            year = row['year']

            if original != canonical_name:
                appellations.append({
                    'appellation_id:ID': f'APP_{tcpuid}_{int(year)}_VARIANT',
                    ':LABEL': 'E41_Appellation',
                    'name': original,
                    'type': 'variant',
                    'tcpuid': tcpuid,
                    'year': int(year),
                    'notes': f'OCR variant of "{canonical_name}"'
                })

    name_changes = canonical_df[canonical_df['reason'] == 'name_change'].copy()
    print(f"  Found {len(name_changes)} intentional name changes (not creating E41s)", file=sys.stderr)

    return pd.DataFrame(appellations)


def create_p1_is_identified_by(canonical_df: pd.DataFrame,
                                raw_to_place: dict) -> pd.DataFrame:
    """
    P1_is_identified_by relationships using persistent place IDs.

    Changes from v1:
    - Canonical links: :START_ID = persistent_place_id (not raw tcpuid)
    - Variant links: :START_ID = presence_id (unchanged, still {tcpuid}_{year})
    """
    relationships = []

    ocr_corrections = canonical_df[canonical_df['should_apply'] == True].copy()

    # Canonical: persistent_place -> E41_Appellation
    for tcpuid in ocr_corrections['tcpuid'].unique():
        place_id = raw_to_place.get(tcpuid, f'PLACE_{tcpuid}')
        relationships.append({
            ':START_ID': place_id,
            ':END_ID': f'APP_{tcpuid}_CANONICAL',
            ':TYPE': 'P1_is_identified_by',
            'type': 'canonical_name'
        })

    # Variant: E93_Presence -> E41_Appellation (unchanged)
    for _, row in ocr_corrections.iterrows():
        if row['original_name'] != row['canonical_name']:
            presence_id = f"{row['tcpuid']}_{int(row['year'])}"
            relationships.append({
                ':START_ID': presence_id,
                ':END_ID': f"APP_{row['tcpuid']}_{int(row['year'])}_VARIANT",
                ':TYPE': 'P1_is_identified_by',
                'type': 'variant_name'
            })

    return pd.DataFrame(relationships)


def create_e42_identifiers(places_dir: Path) -> tuple:
    """
    Create E42_Identifier nodes for TCP UIDs on each E93_Presence.
    This provides provenance: which raw TCP UID was used in each census year.
    """
    mapping_file = places_dir / "tcpuid_year_to_place.csv"
    df = pd.read_csv(mapping_file)

    identifiers = []
    relationships = []

    for _, row in df.iterrows():
        tcpuid = row['tcpuid']
        year = int(row['year'])
        presence_id = f"{tcpuid}_{year}"
        identifier_id = f"TCPUID_{tcpuid}_{year}"

        identifiers.append({
            'identifier_id:ID': identifier_id,
            ':LABEL': 'E42_Identifier',
            'value': tcpuid,
            'identifier_type': 'TCP_UID',
            'year:int': year,
        })

        relationships.append({
            ':START_ID': presence_id,
            ':END_ID': identifier_id,
            ':TYPE': 'P1_is_identified_by',
            'type': 'tcp_uid'
        })

    print(f"  Created {len(identifiers)} E42_Identifier nodes (TCP UID provenance)", file=sys.stderr)
    return pd.DataFrame(identifiers), pd.DataFrame(relationships)


def main():
    parser = argparse.ArgumentParser(
        description='Generate E41_Appellation entities with persistent place identities'
    )
    parser.add_argument('--canonical-names', required=True, help='canonical_names_final.csv file')
    parser.add_argument('--persistent-places', default='persistent_places_output',
                        help='Directory with persistent place registry')
    parser.add_argument('--out', required=True, help='Output directory')
    args = parser.parse_args()

    canonical_file = Path(args.canonical_names)
    places_dir = Path(args.persistent_places)
    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True, parents=True)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Generating E41_Appellation Name Variants (v2 - persistent places)", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # Load persistent place mapping
    print(f"\nLoading persistent place mapping...", file=sys.stderr)
    raw_to_place, year_mapping = load_persistent_mapping(places_dir)

    # Load canonical names
    print(f"\nLoading canonical names...", file=sys.stderr)
    canonical_df = pd.read_csv(canonical_file)
    print(f"  Loaded {len(canonical_df)} records", file=sys.stderr)

    # E41 Appellations (same nodes as v1)
    print(f"\nCreating E41_Appellation entities...", file=sys.stderr)
    appellations = create_e41_appellations(canonical_df)
    appellations.to_csv(out_dir / 'e41_appellations.csv', index=False)
    print(f"  Wrote {len(appellations)} appellations", file=sys.stderr)

    # P1 relationships (updated with persistent place IDs)
    print(f"\nCreating P1_is_identified_by relationships...", file=sys.stderr)
    p1_rels = create_p1_is_identified_by(canonical_df, raw_to_place)
    p1_rels.to_csv(out_dir / 'p1_is_identified_by.csv', index=False)
    print(f"  Wrote {len(p1_rels)} P1 relationships", file=sys.stderr)

    # E42 Identifiers (new: TCP UID provenance)
    print(f"\nCreating E42_Identifier nodes (TCP UID provenance)...", file=sys.stderr)
    e42_nodes, e42_rels = create_e42_identifiers(places_dir)
    e42_nodes.to_csv(out_dir / 'e42_identifiers.csv', index=False)
    e42_rels.to_csv(out_dir / 'p1_identifier_provenance.csv', index=False)
    print(f"  Wrote {len(e42_nodes)} E42_Identifier nodes", file=sys.stderr)
    print(f"  Wrote {len(e42_rels)} provenance relationships", file=sys.stderr)

    # Summary
    canonical_count = len(appellations[appellations['type'] == 'canonical']) if len(appellations) > 0 else 0
    variant_count = len(appellations[appellations['type'] == 'variant']) if len(appellations) > 0 else 0
    canonical_links = len(p1_rels[p1_rels['type'] == 'canonical_name']) if len(p1_rels) > 0 else 0
    variant_links = len(p1_rels[p1_rels['type'] == 'variant_name']) if len(p1_rels) > 0 else 0

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"E41_Appellation: {len(appellations)} ({canonical_count} canonical, {variant_count} variants)", file=sys.stderr)
    print(f"P1 relationships: {len(p1_rels)} ({canonical_links} canonical, {variant_links} variant)", file=sys.stderr)
    print(f"E42_Identifier: {len(e42_nodes)} (TCP UID provenance)", file=sys.stderr)
    print(f"Output: {out_dir}/", file=sys.stderr)


if __name__ == '__main__':
    main()
