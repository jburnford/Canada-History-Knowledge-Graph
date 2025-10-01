#!/usr/bin/env python3
"""
Assign canonical names using a simpler direct approach.

For each TCPUID that appears across multiple years with IoU = 1.0:
1. Collect all names used
2. Find consensus name (most common)
3. Check if names are similar (OCR variants) vs different (intentional changes)
4. Apply canonical name only if names are similar
"""

import pandas as pd
import argparse
from pathlib import Path
from collections import Counter
from rapidfuzz import fuzz
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Assign canonical names based on temporal consensus"
    )
    parser.add_argument('--links-dir', type=Path, default='year_links_output')
    parser.add_argument('--out', type=Path, default='canonical_names_final.csv')
    parser.add_argument('--min-similarity', type=float, default=70.0)

    args = parser.parse_args()

    print("Loading all temporal links...", file=sys.stderr)

    # Collect all CSD appearances across years
    # Key: tcpuid, Value: list of (year, name, cd_name, pr)
    csd_timeline = {}

    year_pairs = [
        (1851, 1861), (1861, 1871), (1871, 1881), (1881, 1891),
        (1891, 1901), (1901, 1911), (1911, 1921)
    ]

    for year_from, year_to in year_pairs:
        # Process high-confidence SAME_AS links
        for file_type in ['year_links', 'ambiguous']:
            filepath = args.links_dir / f"{file_type}_{year_from}_{year_to}.csv"
            if not filepath.exists():
                continue

            df = pd.read_csv(filepath)
            df = df[(df['relationship'] == 'SAME_AS') & (df['iou'] >= 0.999)]

            for _, row in df.iterrows():
                tcpuid_from = row[f'tcpuid_{year_from}']
                tcpuid_to = row[f'tcpuid_{year_to}']
                name_from = row[f'csd_name_{year_from}']
                name_to = row[f'csd_name_{year_to}']
                cd_from = row[f'cd_name_{year_from}']
                cd_to = row[f'cd_name_{year_to}']
                pr_from = row[f'pr_{year_from}']

                # Add FROM appearance
                if tcpuid_from not in csd_timeline:
                    csd_timeline[tcpuid_from] = []
                if (year_from, name_from) not in [(y, n) for y, n, _, _ in csd_timeline[tcpuid_from]]:
                    csd_timeline[tcpuid_from].append((year_from, name_from, cd_from, pr_from))

                # Add TO appearance
                if tcpuid_to not in csd_timeline:
                    csd_timeline[tcpuid_to] = []
                if (year_to, name_to) not in [(y, n) for y, n, _, _ in csd_timeline[tcpuid_to]]:
                    csd_timeline[tcpuid_to].append((year_to, name_to, cd_to, pr_from))

    print(f"  Found {len(csd_timeline)} unique TCPUIDs with temporal data", file=sys.stderr)

    # Analyze each TCPUID
    print("\nAnalyzing for canonical names...", file=sys.stderr)

    results = []
    applied = 0
    skipped_single = 0
    skipped_change = 0

    for tcpuid, timeline in csd_timeline.items():
        if len(timeline) < 2:
            skipped_single += 1
            continue

        # Sort by year
        timeline.sort()

        names = [name for _, name, _, _ in timeline if name and pd.notna(name)]
        if not names:
            continue

        # Find consensus name
        name_counter = Counter(names)
        canonical_name, consensus_count = name_counter.most_common(1)[0]

        # Calculate similarity of all names to consensus
        similarities = []
        for name in set(names):
            if name != canonical_name:
                sim = fuzz.ratio(name.lower(), canonical_name.lower())
                similarities.append(sim)

        if not similarities:
            # All names identical
            avg_sim = 100.0
            min_sim = 100.0
            should_apply = True
            reason = "unanimous"
        else:
            avg_sim = sum(similarities) / len(similarities)
            min_sim = min(similarities)

            # Apply canonical name if names are similar (OCR variants)
            if avg_sim >= args.min_similarity and min_sim >= 60:
                should_apply = True
                reason = f"ocr_variants"
                applied += 1
            else:
                should_apply = False
                reason = f"name_change"
                skipped_change += 1

        # Create result record for each year
        for year, name, cd_name, pr in timeline:
            results.append({
                'tcpuid': tcpuid,
                'year': year,
                'original_name': name,
                'canonical_name': canonical_name if should_apply else name,
                'should_apply': should_apply,
                'consensus_count': consensus_count,
                'total_years': len(timeline),
                'avg_similarity': round(avg_sim, 1),
                'min_similarity': round(min_sim, 1) if min_sim != 100 else 100,
                'reason': reason,
                'all_names': ' | '.join(sorted(set(names))),
                'cd_name': cd_name,
                'province': pr
            })

    # Save results
    if results:
        df = pd.DataFrame(results)
        df = df.sort_values(['tcpuid', 'year'])
        df.to_csv(args.out, index=False)
        print(f"\n✓ Wrote {len(results)} records to {args.out}")

        print(f"\nSummary:")
        print(f"  TCPUIDs analyzed: {len(csd_timeline)}")
        print(f"  Canonical names applied: {applied}")
        print(f"  Skipped (name changes): {skipped_change}")
        print(f"  Skipped (single year): {skipped_single}")

        # Show examples
        print(f"\nExamples with canonical names applied:")
        applied_df = df[df['should_apply'] & (df['original_name'] != df['canonical_name'])]
        if not applied_df.empty:
            sample = applied_df.groupby('tcpuid').first().reset_index().head(10)
            print(sample[['tcpuid', 'original_name', 'canonical_name', 'avg_similarity', 'all_names']].to_string(index=False))

        print(f"\nExamples of name changes (not corrected):")
        changed_df = df[~df['should_apply'] & (df['reason'] == 'name_change')]
        if not changed_df.empty:
            sample = changed_df.groupby('tcpuid').first().reset_index().head(5)
            print(sample[['tcpuid', 'year', 'original_name', 'min_similarity', 'all_names']].to_string(index=False))

    else:
        print("\nNo results generated")


if __name__ == '__main__':
    main()