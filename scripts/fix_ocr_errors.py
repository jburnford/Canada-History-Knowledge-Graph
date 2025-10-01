#!/usr/bin/env python3
"""
Detect and fix OCR errors in CSD names using temporal consistency.

Algorithm:
1. Build temporal chains: CSD_1851 -> CSD_1861 -> ... -> CSD_1921
2. For each chain, find the consensus name (most common across years)
3. Identify outliers: years where name differs but spatial match is strong (IoU > 0.98)
4. Propose corrections based on consensus name and fuzzy matching
"""

import pandas as pd
import argparse
from pathlib import Path
from collections import Counter, defaultdict
from rapidfuzz import fuzz
from typing import Dict, List, Tuple, Set
import sys


def load_temporal_links(links_dir: Path) -> pd.DataFrame:
    """Load all year-to-year temporal links."""
    all_links = []

    year_pairs = [
        (1851, 1861), (1861, 1871), (1871, 1881), (1881, 1891),
        (1891, 1901), (1901, 1911), (1911, 1921)
    ]

    for year_from, year_to in year_pairs:
        # Load high-confidence links
        high_conf_file = links_dir / f"year_links_{year_from}_{year_to}.csv"
        if high_conf_file.exists():
            df = pd.read_csv(high_conf_file)
            df['source'] = 'high_confidence'
            all_links.append(df)

        # Load ambiguous links (only SAME_AS with high IoU)
        ambig_file = links_dir / f"ambiguous_{year_from}_{year_to}.csv"
        if ambig_file.exists():
            df = pd.read_csv(ambig_file)
            # Only use SAME_AS links with very high spatial overlap
            df = df[(df['relationship'] == 'SAME_AS') & (df['iou'] > 0.98)]
            df['source'] = 'ambiguous'
            all_links.append(df)

    return pd.concat(all_links, ignore_index=True)


def build_temporal_chains(links_df: pd.DataFrame) -> Dict[str, List[Tuple[int, str, str]]]:
    """
    Build temporal chains of CSDs across years.

    Returns:
        Dict mapping chain_id -> [(year, tcpuid, name), ...]
    """
    print("Building temporal chains...", file=sys.stderr)

    # Build graph: tcpuid -> {year -> [(next_year, next_tcpuid, name)]}
    forward_links = defaultdict(lambda: defaultdict(list))

    for _, row in links_df[links_df['relationship'] == 'SAME_AS'].iterrows():
        year_from = int(str(row['tcpuid_1851'])[-4:] if '1851' in str(row) else
                       str([c for c in row.index if 'tcpuid_' in c][0]).split('_')[1])
        year_to = int(str([c for c in row.index if 'tcpuid_' in c and str(year_from) not in c][0]).split('_')[1])

        # Get column names dynamically
        tcpuid_from_col = [c for c in row.index if f'tcpuid_{year_from}' == c][0]
        tcpuid_to_col = [c for c in row.index if f'tcpuid_{year_to}' == c][0]
        name_to_col = [c for c in row.index if f'csd_name_{year_to}' == c][0]

        tcpuid_from = row[tcpuid_from_col]
        tcpuid_to = row[tcpuid_to_col]
        name_to = row[name_to_col]

        forward_links[tcpuid_from][year_from].append((year_to, tcpuid_to, name_to))

    # Traverse chains
    chains = {}
    visited = set()
    chain_id = 0

    # Find starting points (CSDs in earliest years not linked from previous years)
    for tcpuid, year_links in forward_links.items():
        min_year = min(year_links.keys())

        if tcpuid in visited:
            continue

        # Start a new chain
        chain = []
        current_tcpuid = tcpuid
        current_year = min_year

        # Get initial name from links
        initial_name = None
        for _, links in forward_links.items():
            for y, entries in links.items():
                for next_year, next_tcpuid, name in entries:
                    if next_tcpuid == tcpuid and next_year == min_year:
                        initial_name = name
                        break

        chain.append((current_year, current_tcpuid, initial_name or "UNKNOWN"))
        visited.add(current_tcpuid)

        # Follow the chain forward
        while current_year in forward_links[current_tcpuid]:
            next_links = forward_links[current_tcpuid][current_year]
            if not next_links:
                break

            # Take first link (should only be one for SAME_AS)
            current_year, current_tcpuid, current_name = next_links[0]
            chain.append((current_year, current_tcpuid, current_name))
            visited.add(current_tcpuid)

        if len(chain) > 1:  # Only keep chains spanning multiple years
            chains[f"chain_{chain_id:04d}"] = chain
            chain_id += 1

    print(f"  Found {len(chains)} temporal chains", file=sys.stderr)
    return chains


def find_consensus_name(names: List[str]) -> Tuple[str, int]:
    """
    Find the most common name in a list (consensus name).

    Returns:
        (consensus_name, count)
    """
    if not names:
        return None, 0

    # Normalize: strip whitespace, lowercase for comparison
    normalized = [n.strip().lower() for n in names if n and n != "UNKNOWN"]

    if not normalized:
        return None, 0

    counter = Counter(normalized)
    consensus_normalized, count = counter.most_common(1)[0]

    # Find original casing
    for name in names:
        if name.strip().lower() == consensus_normalized:
            return name, count

    return consensus_normalized, count


def detect_ocr_errors(chains: Dict[str, List[Tuple[int, str, str]]]) -> List[Dict]:
    """
    Detect likely OCR errors in temporal chains.

    Returns:
        List of error records with correction suggestions
    """
    print("\nDetecting OCR errors...", file=sys.stderr)

    errors = []

    for chain_id, chain in chains.items():
        if len(chain) < 3:  # Need at least 3 years for consensus
            continue

        names = [name for _, _, name in chain]
        consensus_name, consensus_count = find_consensus_name(names)

        if not consensus_name or consensus_count < 2:
            continue

        # Check each year in the chain
        for year, tcpuid, name in chain:
            if not name or name == "UNKNOWN":
                continue

            # Check if this name differs from consensus
            if name.strip().lower() != consensus_name.lower():
                # Calculate similarity to consensus
                similarity = fuzz.ratio(name.lower(), consensus_name.lower())

                # Likely OCR error if:
                # - Similar but not identical (60-95% similarity)
                # - Consensus appears in 2+ other years
                if 60 <= similarity < 95 and consensus_count >= 2:
                    errors.append({
                        'chain_id': chain_id,
                        'year': year,
                        'tcpuid': tcpuid,
                        'current_name': name,
                        'suggested_name': consensus_name,
                        'similarity': similarity,
                        'consensus_count': consensus_count,
                        'chain_length': len(chain),
                        'all_names': ' | '.join([f"{y}:{n}" for y, _, n in chain])
                    })

    print(f"  Found {len(errors)} potential OCR errors", file=sys.stderr)
    return errors


def main():
    parser = argparse.ArgumentParser(
        description="Detect and fix OCR errors in CSD names using temporal consistency"
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
    parser.add_argument(
        '--min-similarity',
        type=float,
        default=60.0,
        help='Minimum similarity threshold for OCR error detection (default: 60.0)'
    )
    parser.add_argument(
        '--min-consensus',
        type=int,
        default=2,
        help='Minimum consensus count (default: 2)'
    )

    args = parser.parse_args()

    # Load temporal links
    print(f"Loading temporal links from {args.links_dir}...", file=sys.stderr)
    links_df = load_temporal_links(args.links_dir)
    print(f"  Loaded {len(links_df)} links", file=sys.stderr)

    # Build temporal chains
    chains = build_temporal_chains(links_df)

    # Detect OCR errors
    errors = detect_ocr_errors(chains)

    # Filter by thresholds
    filtered_errors = [
        e for e in errors
        if e['similarity'] >= args.min_similarity
        and e['consensus_count'] >= args.min_consensus
    ]

    # Save results
    if filtered_errors:
        df = pd.DataFrame(filtered_errors)
        df = df.sort_values(['chain_id', 'year'])
        df.to_csv(args.out, index=False)
        print(f"\n✓ Wrote {len(filtered_errors)} OCR corrections to {args.out}")

        # Summary statistics
        print(f"\nSummary:")
        print(f"  Total chains analyzed: {len(chains)}")
        print(f"  OCR errors found: {len(filtered_errors)}")
        print(f"  Affected years: {df['year'].nunique()}")
        print(f"  Average similarity: {df['similarity'].mean():.1f}%")

        # Show examples
        print(f"\nTop 10 corrections (by similarity):")
        print(df[['year', 'tcpuid', 'current_name', 'suggested_name', 'similarity']]
              .head(10).to_string(index=False))
    else:
        print("\nNo OCR errors found with current thresholds")


if __name__ == '__main__':
    main()