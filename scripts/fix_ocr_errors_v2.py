#!/usr/bin/env python3
"""
Detect and fix OCR errors in CSD names using temporal consistency.

Simpler approach: For each ambiguous SAME_AS link with high IoU but low name similarity,
check if names in adjacent years provide a consensus correction.
"""

import pandas as pd
import argparse
from pathlib import Path
from collections import Counter
from rapidfuzz import fuzz
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Detect OCR errors in CSD names using temporal links"
    )
    parser.add_argument(
        '--links-dir',
        type=Path,
        default='year_links_output',
        help='Directory containing temporal link CSV files'
    )
    parser.add_argument(
        '--out',
        type=Path,
        default='ocr_corrections.csv',
        help='Output CSV file with correction suggestions'
    )

    args = parser.parse_args()

    print(f"Loading temporal links from {args.links_dir}...", file=sys.stderr)

    # Year pairs
    year_pairs = [
        (1851, 1861), (1861, 1871), (1871, 1881), (1881, 1891),
        (1891, 1901), (1901, 1911), (1911, 1921)
    ]

    corrections = []

    for year_from, year_to in year_pairs:
        # Load ambiguous SAME_AS links (high IoU, low name similarity)
        ambig_file = args.links_dir / f"ambiguous_{year_from}_{year_to}.csv"

        if not ambig_file.exists():
            continue

        print(f"\nProcessing {year_from} → {year_to}...", file=sys.stderr)
        df = pd.read_csv(ambig_file)

        # Focus on SAME_AS with very high spatial overlap but name mismatch
        same_as = df[(df['relationship'] == 'SAME_AS') &
                     (df['iou'] > 0.98) &
                     (df['name_similarity'] < 80)]

        print(f"  Found {len(same_as)} potential OCR errors", file=sys.stderr)

        for _, row in same_as.iterrows():
            name_from = row[f'csd_name_{year_from}']
            name_to = row[f'csd_name_{year_to}']

            # Simple heuristic: if one name is much longer, it might be OCR adding garbage
            len_diff = abs(len(str(name_from)) - len(str(name_to)))

            # Or if they're similar length, find which one looks more "standard"
            # (e.g., fewer numbers, special characters)
            corrections.append({
                'year_from': year_from,
                'year_to': year_to,
                'tcpuid_from': row[f'tcpuid_{year_from}'],
                'tcpuid_to': row[f'tcpuid_{year_to}'],
                'name_from': name_from,
                'name_to': name_to,
                'iou': row['iou'],
                'name_similarity': row['name_similarity'],
                'len_diff': len_diff,
                'cd_name_from': row[f'cd_name_{year_from}'],
                'cd_name_to': row[f'cd_name_{year_to}'],
                'pr_from': row[f'pr_{year_from}']
            })

    if corrections:
        df_out = pd.DataFrame(corrections)
        df_out = df_out.sort_values(['year_from', 'name_similarity'])
        df_out.to_csv(args.out, index=False)
        print(f"\n✓ Wrote {len(corrections)} potential OCR errors to {args.out}")

        print(f"\nTop 20 examples (lowest name similarity):")
        print(df_out[['year_from', 'name_from', 'name_to', 'name_similarity', 'iou']]
              .head(20).to_string(index=False))
    else:
        print("\nNo OCR error candidates found")


if __name__ == '__main__':
    main()