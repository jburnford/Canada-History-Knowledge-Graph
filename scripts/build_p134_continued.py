#!/usr/bin/env python3
"""
Generate P134_continued relationships from temporal link data.

Converts CSD and CD temporal links into CIDOC-CRM P134_continued relationships
for Neo4j import. P134_continued models temporal continuity between places.

Author: Claude Code
Date: September 30, 2025
"""

import pandas as pd
from pathlib import Path
import argparse
import sys


def load_csd_links(links_dir: Path) -> pd.DataFrame:
    """Load CSD temporal links from year_links_output/."""
    all_links = []

    year_pairs = [
        (1851, 1861), (1861, 1871), (1871, 1881),
        (1881, 1891), (1891, 1901), (1901, 1911),
        (1911, 1921)
    ]

    for year_from, year_to in year_pairs:
        link_file = links_dir / f'year_links_{year_from}_{year_to}.csv'
        if link_file.exists():
            print(f"  Loading {link_file.name}...", file=sys.stderr)
            df = pd.read_csv(link_file)

            # Filter for high-confidence links suitable for P134
            # SAME_AS: clear continuity
            # CONTAINS/WITHIN: administrative restructuring
            suitable = df[df['relationship'].isin(['SAME_AS', 'CONTAINS', 'WITHIN'])].copy()

            # Create P134 relationships (column names are year-specific)
            tcpuid_from_col = f'tcpuid_{year_from}'
            tcpuid_to_col = f'tcpuid_{year_to}'

            for _, row in suitable.iterrows():
                all_links.append({
                    ':START_ID': row[tcpuid_from_col] + f'_{year_from}',  # E93_Presence ID from year
                    ':END_ID': row[tcpuid_to_col] + f'_{year_to}',        # E93_Presence ID to year
                    'relationship_type': row['relationship'],
                    'iou:float': row.get('iou', 0.0),
                    'from_fraction:float': row.get('frac_from', 0.0),
                    'to_fraction:float': row.get('frac_to', 0.0),
                    'year_from:int': year_from,
                    'year_to:int': year_to,
                    ':TYPE': 'P134_continued'
                })

    return pd.DataFrame(all_links)


def load_cd_links(links_dir: Path) -> pd.DataFrame:
    """Load CD temporal links from cd_links_output/."""
    all_links = []

    year_pairs = [
        (1851, 1861), (1861, 1871), (1871, 1881),
        (1881, 1891), (1891, 1901), (1901, 1911),
        (1911, 1921)
    ]

    for year_from, year_to in year_pairs:
        link_file = links_dir / f'cd_links_{year_from}_{year_to}.csv'
        if link_file.exists():
            print(f"  Loading {link_file.name}...", file=sys.stderr)
            df = pd.read_csv(link_file)

            # CD links already filtered to high-confidence
            # Create P134 relationships between CD E53_Place nodes
            # Note: CDs don't have E93_Presence, so we link E53 directly
            for _, row in df.iterrows():
                all_links.append({
                    ':START_ID': row['cd_from'],  # CD E53_Place ID
                    ':END_ID': row['cd_to'],      # CD E53_Place ID
                    'relationship_type': row['relationship'],
                    'iou:float': row.get('iou', 0.0),
                    'from_fraction:float': row.get('from_fraction', 0.0),
                    'to_fraction:float': row.get('to_fraction', 0.0),
                    'year_from:int': year_from,
                    'year_to:int': year_to,
                    ':TYPE': 'P134_continued'
                })

    return pd.DataFrame(all_links)


def main():
    parser = argparse.ArgumentParser(description='Generate P134_continued relationships')
    parser.add_argument('--csd-links', default='year_links_output', help='CSD links directory')
    parser.add_argument('--cd-links', default='cd_links_output', help='CD links directory')
    parser.add_argument('--out', required=True, help='Output directory')
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True, parents=True)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Generating P134_continued relationships", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # Load CSD links
    print(f"\nLoading CSD temporal links from {args.csd_links}/...", file=sys.stderr)
    csd_links = load_csd_links(Path(args.csd_links))

    if len(csd_links) > 0:
        csd_file = out_dir / 'p134_continued_csd.csv'
        csd_links.to_csv(csd_file, index=False)
        print(f"\n✓ CSD P134 relationships: {len(csd_links)} → {csd_file}", file=sys.stderr)

        # Summary by relationship type
        print(f"\n  CSD P134 by type:", file=sys.stderr)
        for rel_type in ['SAME_AS', 'CONTAINS', 'WITHIN']:
            count = len(csd_links[csd_links['relationship_type'] == rel_type])
            if count > 0:
                print(f"    {rel_type}: {count}", file=sys.stderr)

    # Load CD links
    print(f"\nLoading CD temporal links from {args.cd_links}/...", file=sys.stderr)
    cd_links = load_cd_links(Path(args.cd_links))

    if len(cd_links) > 0:
        cd_file = out_dir / 'p134_continued_cd.csv'
        cd_links.to_csv(cd_file, index=False)
        print(f"\n✓ CD P134 relationships: {len(cd_links)} → {cd_file}", file=sys.stderr)

        # Summary by relationship type
        print(f"\n  CD P134 by type:", file=sys.stderr)
        for rel_type in ['SAME_AS', 'CONTAINS', 'WITHIN']:
            count = len(cd_links[cd_links['relationship_type'] == rel_type])
            if count > 0:
                print(f"    {rel_type}: {count}", file=sys.stderr)

    # Overall summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"Total P134_continued relationships: {len(csd_links) + len(cd_links)}", file=sys.stderr)
    print(f"  CSD (E93 Presence → E93 Presence): {len(csd_links)}", file=sys.stderr)
    print(f"  CD (E53 Place → E53 Place): {len(cd_links)}", file=sys.stderr)
    print(f"\nOutput files in: {out_dir}/", file=sys.stderr)
    print(f"", file=sys.stderr)


if __name__ == '__main__':
    main()
