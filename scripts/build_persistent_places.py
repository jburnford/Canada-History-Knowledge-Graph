#!/usr/bin/env python3
"""
Build persistent place registry from year_links SAME_AS chains.

Reads spatial overlap analysis (year_links) and uses Union-Find to identify
persistent places across census years. Each connected component of SAME_AS
links with IOU=1.0 becomes one persistent place.

Outputs:
- persistent_place_registry.csv: one row per persistent place
- tcpuid_year_to_place.csv: mapping (tcpuid, year) -> persistent_place_id
- place_lineage.csv: split/merge relationships between persistent places
"""

import csv
import pandas as pd
from pathlib import Path
from collections import defaultdict, Counter
import argparse
import sys

YEARS = [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921]
YEAR_PAIRS = list(zip(YEARS[:-1], YEARS[1:]))


# -- Union-Find --
class UnionFind:
    def __init__(self):
        self.parent = {}
        self.rank = {}

    def make_set(self, x):
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # path compression
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        # union by rank
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1

    def components(self):
        groups = defaultdict(list)
        for node in self.parent:
            groups[self.find(node)].append(node)
        return dict(groups)


def load_all_year_links(links_dir: Path):
    """Load all year_links CSV files, returning SAME_AS and lineage links separately."""
    same_as_links = []
    lineage_links = []
    node_meta = {}  # (tcpuid, year) -> {name, cd, province}

    for y1, y2 in YEAR_PAIRS:
        fpath = links_dir / f"year_links_{y1}_{y2}.csv"
        if not fpath.exists():
            print(f"  Warning: {fpath} not found, skipping", file=sys.stderr)
            continue

        with open(fpath) as f:
            for row in csv.DictReader(f):
                rel = row["relationship"]
                uid1 = row[f"tcpuid_{y1}"].strip()
                uid2 = row[f"tcpuid_{y2}"].strip()
                name1 = row[f"csd_name_{y1}"].strip()
                name2 = row[f"csd_name_{y2}"].strip()
                cd1 = row[f"cd_name_{y1}"].strip()
                cd2 = row[f"cd_name_{y2}"].strip()
                pr1 = row[f"pr_{y1}"].strip()
                pr2 = row[f"pr_{y2}"].strip()

                node_meta[(uid1, y1)] = {"name": name1, "cd": cd1, "province": pr1}
                node_meta[(uid2, y2)] = {"name": name2, "cd": cd2, "province": pr2}

                try:
                    iou = float(row["iou"])
                except (ValueError, KeyError):
                    iou = 0.0

                if rel == "SAME_AS" and iou >= 1.0:
                    same_as_links.append(((uid1, y1), (uid2, y2)))
                elif rel in ("CONTAINS", "WITHIN"):
                    lineage_links.append({
                        "uid_from": uid1, "year_from": y1,
                        "uid_to": uid2, "year_to": y2,
                        "relationship": rel,
                        "iou": iou,
                    })

    print(f"  Loaded {len(same_as_links)} SAME_AS (IOU=1.0) links", file=sys.stderr)
    print(f"  Loaded {len(lineage_links)} CONTAINS/WITHIN links", file=sys.stderr)
    return same_as_links, lineage_links, node_meta


def build_persistent_places(same_as_links, node_meta):
    """Build persistent place registry using Union-Find on SAME_AS chains."""
    uf = UnionFind()

    # Initialize all nodes from metadata (covers singletons too)
    for node in node_meta:
        uf.make_set(node)

    # Union SAME_AS pairs
    for a, b in same_as_links:
        uf.make_set(a)
        uf.make_set(b)
        uf.union(a, b)

    components = uf.components()
    print(f"  Built {len(components)} persistent places from Union-Find", file=sys.stderr)

    # Build registry
    registry = []
    tcpuid_year_map = {}  # (tcpuid, year) -> persistent_place_id
    used_ids = set()

    for root, nodes in components.items():
        nodes_sorted = sorted(nodes, key=lambda x: x[1])  # sort by year
        years_present = sorted(set(n[1] for n in nodes_sorted))

        # Pick anchor: latest year's UID
        latest_node = nodes_sorted[-1]
        anchor_tcpuid = latest_node[0]
        anchor_year = latest_node[1]

        # Generate unique ID: try tcpuid alone, add year suffix if collision
        persistent_id = f"PLACE_{anchor_tcpuid}"
        if persistent_id in used_ids:
            persistent_id = f"PLACE_{anchor_tcpuid}_{years_present[0]}"
            # In the extremely rare case of still colliding, add full range
            while persistent_id in used_ids:
                persistent_id = f"PLACE_{anchor_tcpuid}_{years_present[0]}_{years_present[-1]}"
        used_ids.add(persistent_id)

        # Canonical name: most frequent name in chain, latest year breaks ties
        name_counter = Counter()
        name_latest_year = {}
        for uid, yr in nodes_sorted:
            meta = node_meta.get((uid, yr), {})
            name = meta.get("name", "")
            if name:
                name_counter[name] += 1
                if name not in name_latest_year or yr > name_latest_year[name]:
                    name_latest_year[name] = yr

        if name_counter:
            max_count = max(name_counter.values())
            top_names = [n for n, c in name_counter.items() if c == max_count]
            # Break tie by latest year
            canonical_name = max(top_names, key=lambda n: name_latest_year.get(n, 0))
        else:
            canonical_name = ""

        # Province (should be consistent within chain)
        provinces = set()
        for uid, yr in nodes_sorted:
            meta = node_meta.get((uid, yr), {})
            if meta.get("province"):
                provinces.add(meta["province"])
        province = sorted(provinces)[0] if provinces else ""

        years_active = ";".join(str(y) for y in years_present)

        registry.append({
            "persistent_place_id": persistent_id,
            "canonical_name": canonical_name,
            "province": province,
            "anchor_tcpuid": anchor_tcpuid,
            "anchor_year": anchor_year,
            "years_active": years_active,
            "num_years": len(years_present),
        })

        # Map every (tcpuid, year) in this component
        for uid, yr in nodes_sorted:
            tcpuid_year_map[(uid, yr)] = persistent_id

    return registry, tcpuid_year_map


def build_lineage(lineage_links, tcpuid_year_map):
    """Build lineage relationships between persistent places from CONTAINS/WITHIN."""
    lineage = []
    seen = set()

    for link in lineage_links:
        uid_from = link["uid_from"]
        year_from = link["year_from"]
        uid_to = link["uid_to"]
        year_to = link["year_to"]
        rel = link["relationship"]

        place_from = tcpuid_year_map.get((uid_from, year_from))
        place_to = tcpuid_year_map.get((uid_to, year_to))

        if not place_from or not place_to or place_from == place_to:
            continue

        # CONTAINS: from-CSD contained to-CSD (to was carved out of from)
        # WITHIN: from-CSD was within to-CSD (from was absorbed into to)
        if rel == "CONTAINS":
            lineage_type = "SPLIT_FROM"
            parent_place = place_from
            child_place = place_to
            change_year = year_to
        else:  # WITHIN
            lineage_type = "MERGED_INTO"
            parent_place = place_from
            child_place = place_to
            change_year = year_to

        key = (lineage_type, parent_place, child_place, change_year)
        if key in seen:
            continue
        seen.add(key)

        lineage.append({
            "lineage_type": lineage_type,
            ":START_ID": parent_place,
            ":END_ID": child_place,
            "change_year:int": change_year,
            ":TYPE": lineage_type,
        })

    print(f"  Built {len(lineage)} lineage relationships", file=sys.stderr)
    return lineage


def collect_all_csd_presences(links_dir: Path, node_meta: dict):
    """
    Ensure we have metadata for ALL (tcpuid, year) combos,
    including those not in any year_links file (singletons from first/last year).

    The GDB itself is the authoritative source but we don't load it here.
    The node_meta from year_links covers most cases since every CSD that
    overlaps with anything in an adjacent year appears in year_links.

    Singletons that appear in NO year_links file are CSDs that existed in
    only one year and had no spatial overlap with any CSD in adjacent years.
    These are rare but we handle them in build_neo4j_cidoc_crm_v2.py by
    creating PLACE_{tcpuid} for any unmapped (tcpuid, year).
    """
    pass  # handled downstream


def main():
    parser = argparse.ArgumentParser(
        description="Build persistent place registry from year_links SAME_AS chains"
    )
    parser.add_argument(
        "--links-dir",
        default="year_links_output",
        help="Directory containing year_links_*.csv files",
    )
    parser.add_argument(
        "--out",
        default="persistent_places_output",
        help="Output directory",
    )
    args = parser.parse_args()

    links_dir = Path(args.links_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Building Persistent Place Registry", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # Step 1: Load all links
    print(f"\nLoading year_links...", file=sys.stderr)
    same_as_links, lineage_links, node_meta = load_all_year_links(links_dir)

    # Step 2: Build persistent places via Union-Find
    print(f"\nBuilding persistent places...", file=sys.stderr)
    registry, tcpuid_year_map = build_persistent_places(same_as_links, node_meta)

    # Step 3: Build lineage from CONTAINS/WITHIN
    print(f"\nBuilding lineage relationships...", file=sys.stderr)
    lineage = build_lineage(lineage_links, tcpuid_year_map)

    # Step 4: Write outputs
    print(f"\nWriting outputs to {out_dir}/...", file=sys.stderr)

    # Registry
    registry_df = pd.DataFrame(registry)
    registry_df.to_csv(out_dir / "persistent_place_registry.csv", index=False)
    print(f"  persistent_place_registry.csv: {len(registry_df)} persistent places", file=sys.stderr)

    # Mapping
    mapping_rows = [
        {"tcpuid": uid, "year": yr, "persistent_place_id": pid}
        for (uid, yr), pid in tcpuid_year_map.items()
    ]
    mapping_df = pd.DataFrame(mapping_rows)
    mapping_df.to_csv(out_dir / "tcpuid_year_to_place.csv", index=False)
    print(f"  tcpuid_year_to_place.csv: {len(mapping_df)} mappings", file=sys.stderr)

    # Lineage
    lineage_df = pd.DataFrame(lineage)
    lineage_df.to_csv(out_dir / "place_lineage.csv", index=False)
    print(f"  place_lineage.csv: {len(lineage_df)} lineage relationships", file=sys.stderr)

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    year_dist = Counter(r["num_years"] for r in registry)
    print(f"Persistent places: {len(registry)}", file=sys.stderr)
    print(f"Total (tcpuid, year) mappings: {len(mapping_rows)}", file=sys.stderr)
    print(f"Lineage relationships: {len(lineage)}", file=sys.stderr)
    print(f"\nYear span distribution:", file=sys.stderr)
    for span in sorted(year_dist):
        print(f"  {span} years: {year_dist[span]} places", file=sys.stderr)

    multi_year = sum(1 for r in registry if r["num_years"] > 1)
    singletons = sum(1 for r in registry if r["num_years"] == 1)
    print(f"\nMulti-year chains: {multi_year}", file=sys.stderr)
    print(f"Single-year singletons: {singletons}", file=sys.stderr)
    print(f"\nOutput: {out_dir}/", file=sys.stderr)


if __name__ == "__main__":
    main()
