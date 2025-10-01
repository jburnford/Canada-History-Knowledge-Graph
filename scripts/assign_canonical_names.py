#!/usr/bin/env python3
"""
Assign canonical names to CSDs based on temporal consistency.

Strategy:
1. Build chains of CSDs across years (SAME_AS relationships with IoU = 1.0)
2. For each chain, find the consensus name (most common across years)
3. Only assign canonical name if names are similar (avoid Berlin→Kitchener type changes)
4. Output mapping: tcpuid_year -> canonical_name

This preserves intentional name changes while fixing OCR errors.
"""

import pandas as pd
import argparse
from pathlib import Path
from collections import Counter, defaultdict
from rapidfuzz import fuzz
import sys


def load_high_confidence_links(links_dir: Path) -> pd.DataFrame:
    """Load only SAME_AS links with perfect spatial match (IoU = 1.0)."""
    all_links = []

    year_pairs = [
        (1851, 1861), (1861, 1871), (1871, 1881), (1881, 1891),
        (1891, 1901), (1901, 1911), (1911, 1921)
    ]

    for year_from, year_to in year_pairs:
        # High confidence links
        high_conf_file = links_dir / f"year_links_{year_from}_{year_to}.csv"
        if high_conf_file.exists():
            df = pd.read_csv(high_conf_file)
            df = df[(df['relationship'] == 'SAME_AS') & (df['iou'] >= 0.999)]
            all_links.append(df)

        # Ambiguous SAME_AS with perfect spatial match
        ambig_file = links_dir / f"ambiguous_{year_from}_{year_to}.csv"
        if ambig_file.exists():
            df = pd.read_csv(ambig_file)
            df = df[(df['relationship'] == 'SAME_AS') & (df['iou'] >= 0.999)]
            all_links.append(df)

    return pd.concat(all_links, ignore_index=True)


def build_chains(links_df: pd.DataFrame) -> dict:
    """
    Build temporal chains of CSDs.

    Returns:
        Dict mapping chain_id -> [(year, tcpuid, csd_name, cd_name, pr), ...]
    """
    print("Building temporal chains from perfect spatial matches...", file=sys.stderr)

    # Build adjacency: (tcpuid, year) -> (next_tcpuid, next_year, name, cd, pr)
    graph = defaultdict(list)

    for _, row in links_df.iterrows():
        # Extract year_from and year_to from column names
        year_cols = [c for c in row.index if c.startswith('tcpuid_')]
        years = sorted([int(c.split('_')[1]) for c in year_cols])
        year_from, year_to = years[0], years[1]

        tcpuid_from = row[f'tcpuid_{year_from}']
        tcpuid_to = row[f'tcpuid_{year_to}']
        name_to = row[f'csd_name_{year_to}']
        cd_to = row[f'cd_name_{year_to}']
        pr_to = row[f'pr_{year_to}']

        graph[(tcpuid_from, year_from)].append((tcpuid_to, year_to, name_to, cd_to, pr_to))

    # Find chain starting points (earliest year for each CSD)
    all_nodes = set(graph.keys())
    for children in graph.values():
        for tcpuid, year, _, _, _ in children:
            all_nodes.add((tcpuid, year))

    starts = []
    for tcpuid, year in all_nodes:
        # Check if this node has no incoming edges
        is_start = True
        for _, prev_year, prev_children in [(k[0], k[1], v) for k, v in graph.items()]:
            for next_tcpuid, next_year, _, _, _ in prev_children:
                if next_tcpuid == tcpuid and next_year == year:
                    is_start = False
                    break
            if not is_start:
                break

        if is_start:
            starts.append((tcpuid, year))

    # Build chains from starting points
    chains = {}
    chain_id = 0
    visited = set()

    for start_tcpuid, start_year in starts:
        if (start_tcpuid, start_year) in visited:
            continue

        chain = []
        current = (start_tcpuid, start_year)

        # Get initial name from first link
        initial_name = None
        initial_cd = None
        initial_pr = None

        # Look for this node as a target
        for (from_tcpuid, from_year), children in graph.items():
            for to_tcpuid, to_year, name, cd, pr in children:
                if to_tcpuid == start_tcpuid and to_year == start_year:
                    initial_name = name
                    initial_cd = cd
                    initial_pr = pr
                    break
            if initial_name:
                break

        # If no incoming edge found, try to get name from outgoing
        if not initial_name and current in graph:
            children = graph[current]
            if children:
                # Use the first child's info for the start node
                initial_name = f"[Start of chain]"
                initial_cd = children[0][3]
                initial_pr = children[0][4]

        chain.append((start_year, start_tcpuid, initial_name or "UNKNOWN", initial_cd or "", initial_pr or ""))
        visited.add(current)

        # Follow chain forward
        while current in graph:
            children = graph[current]
            if not children:
                break

            # Take first child (should only be one for SAME_AS)
            next_tcpuid, next_year, next_name, next_cd, next_pr = children[0]
            next_node = (next_tcpuid, next_year)

            if next_node in visited:  # Avoid cycles
                break

            chain.append((next_year, next_tcpuid, next_name, next_cd, next_pr))
            visited.add(next_node)
            current = next_node

        if len(chain) > 1:  # Only keep multi-year chains
            chains[f"chain_{chain_id:05d}"] = chain
            chain_id += 1

    print(f"  Found {len(chains)} temporal chains", file=sys.stderr)
    return chains


def find_canonical_name(chain: list, min_similarity: float = 70.0) -> tuple:
    """
    Find canonical name for a chain.

    Returns:
        (canonical_name, should_apply, reason, name_diversity)

    should_apply is True only if:
    - Names are similar (avg similarity > min_similarity)
    - There's a clear consensus name
    """
    names = [name for _, _, name, _, _ in chain if name and name != "UNKNOWN" and name != "[Start of chain]"]

    if len(names) < 2:
        return None, False, "insufficient_data", 0

    # Find most common name
    name_counter = Counter(names)
    canonical_name, consensus_count = name_counter.most_common(1)[0]

    # Calculate diversity: how similar are all names to consensus?
    similarities = []
    for name in names:
        if name != canonical_name:
            sim = fuzz.ratio(name.lower(), canonical_name.lower())
            similarities.append(sim)

    if not similarities:
        # All names are identical
        return canonical_name, True, "unanimous", 100.0

    avg_similarity = sum(similarities) / len(similarities)
    min_sim = min(similarities) if similarities else 100

    # Decision logic
    if avg_similarity >= min_similarity and min_sim >= 60:
        # Names are similar enough - likely OCR variants
        reason = f"ocr_variants_avg_{avg_similarity:.1f}"
        return canonical_name, True, reason, avg_similarity
    else:
        # Names are too different - likely intentional change (Berlin→Kitchener)
        reason = f"name_change_min_{min_sim:.1f}"
        return canonical_name, False, reason, avg_similarity


def main():
    parser = argparse.ArgumentParser(
        description="Assign canonical names to CSDs based on temporal consensus"
    )
    parser.add_argument(
        '--links-dir',
        type=Path,
        default='year_links_output',
        help='Directory containing temporal link CSV files'
    )
    parser.add_argument(
        '--out-mapping',
        type=Path,
        default='canonical_names_mapping.csv',
        help='Output CSV: tcpuid,year,original_name,canonical_name,chain_id'
    )
    parser.add_argument(
        '--out-chains',
        type=Path,
        default='canonical_names_chains.csv',
        help='Output CSV: chain_id,should_apply,reason,diversity,all_names'
    )
    parser.add_argument(
        '--min-similarity',
        type=float,
        default=70.0,
        help='Minimum average similarity to apply canonical name (default: 70.0)'
    )

    args = parser.parse_args()

    # Load links
    print(f"Loading temporal links from {args.links_dir}...", file=sys.stderr)
    links_df = load_high_confidence_links(args.links_dir)
    print(f"  Loaded {len(links_df)} perfect spatial matches (IoU >= 0.999)", file=sys.stderr)

    # Build chains
    chains = build_chains(links_df)

    # Analyze each chain
    print("\nAnalyzing chains for canonical names...", file=sys.stderr)

    mapping_records = []
    chain_records = []

    applied_count = 0
    skipped_count = 0

    for chain_id, chain in chains.items():
        canonical_name, should_apply, reason, diversity = find_canonical_name(chain, args.min_similarity)

        # Record chain info
        all_names = " | ".join([f"{y}:{n}" for y, _, n, _, _ in chain])
        chain_records.append({
            'chain_id': chain_id,
            'chain_length': len(chain),
            'canonical_name': canonical_name or "N/A",
            'should_apply': should_apply,
            'reason': reason,
            'name_diversity': round(diversity, 2) if diversity else 0,
            'all_names': all_names
        })

        # Create mapping records
        for year, tcpuid, original_name, cd_name, pr in chain:
            mapping_records.append({
                'chain_id': chain_id,
                'year': year,
                'tcpuid': tcpuid,
                'original_name': original_name,
                'canonical_name': canonical_name if should_apply else original_name,
                'should_apply': should_apply,
                'cd_name': cd_name,
                'province': pr
            })

        if should_apply:
            applied_count += 1
        else:
            skipped_count += 1

    # Save results
    if mapping_records:
        df_mapping = pd.DataFrame(mapping_records)
        df_mapping = df_mapping.sort_values(['chain_id', 'year'])
        df_mapping.to_csv(args.out_mapping, index=False)
        print(f"\n✓ Wrote {len(mapping_records)} mappings to {args.out_mapping}")

    if chain_records:
        df_chains = pd.DataFrame(chain_records)
        df_chains = df_chains.sort_values('chain_length', ascending=False)
        df_chains.to_csv(args.out_chains, index=False)
        print(f"✓ Wrote {len(chain_records)} chain summaries to {args.out_chains}")

    # Summary
    print(f"\nSummary:")
    print(f"  Total chains: {len(chains)}")
    print(f"  Canonical names applied: {applied_count}")
    print(f"  Skipped (name changes): {skipped_count}")
    print(f"  Total CSD-year records: {len(mapping_records)}")

    # Show examples
    print(f"\nExample chains with canonical names applied:")
    applied = df_chains[df_chains['should_apply']].head(10)
    if not applied.empty:
        print(applied[['chain_id', 'canonical_name', 'name_diversity', 'all_names']].to_string(index=False))

    print(f"\nExample chains skipped (intentional name changes):")
    skipped = df_chains[~df_chains['should_apply']].head(5)
    if not skipped.empty:
        print(skipped[['chain_id', 'canonical_name', 'name_diversity', 'reason', 'all_names']].to_string(index=False))


if __name__ == '__main__':
    main()