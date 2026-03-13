#!/usr/bin/env python3
"""Analyze SAME_AS chains to identify persistent places."""
import csv, json, os
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
LINKS_DIR = os.path.join(BASE, "year_links_output")
YEARS = [1851,1861,1871,1881,1891,1901,1911,1921]
YEAR_PAIRS = list(zip(YEARS[:-1], YEARS[1:]))

# Union-Find
parent = {}
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x
def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb: parent[ra] = rb

node_meta = {}  # (uid, year) -> {name, cd, prov}

# Load all SAME_AS links with IOU=1.0
link_count = 0
for y1, y2 in YEAR_PAIRS:
    fpath = os.path.join(LINKS_DIR, f"year_links_{y1}_{y2}.csv")
    with open(fpath) as f:
        for row in csv.DictReader(f):
            if row["relationship"] != "SAME_AS": continue
            try:
                if float(row["iou"]) < 1.0: continue
            except: continue

            uid1 = row[f"tcpuid_{y1}"].strip()
            uid2 = row[f"tcpuid_{y2}"].strip()
            k1, k2 = (uid1, y1), (uid2, y2)
            parent.setdefault(k1, k1)
            parent.setdefault(k2, k2)
            node_meta[k1] = {"name": row[f"csd_name_{y1}"].strip(), "cd": row[f"cd_name_{y1}"].strip()}
            node_meta[k2] = {"name": row[f"csd_name_{y2}"].strip(), "cd": row[f"cd_name_{y2}"].strip()}
            union(k1, k2)
            link_count += 1

print(f"SAME_AS links (IOU=1.0): {link_count}")

# Build chains
components = defaultdict(list)
for node in parent:
    components[find(node)].append(node)

chains = []
for root, nodes in components.items():
    nodes_sorted = sorted(nodes, key=lambda x: x[1])
    uids = [n[0] for n in nodes_sorted]
    years = sorted(set(n[1] for n in nodes_sorted))
    names = sorted(set(node_meta[n]["name"] for n in nodes_sorted))
    cds = sorted(set(node_meta[n]["cd"] for n in nodes_sorted))
    chains.append({"uids": uids, "names": names, "years": years, "cds": cds, "n_uids": len(uids), "n_years": len(years)})

chains.sort(key=lambda c: (-c["n_years"], c["years"][0]))

# Stats
total_uids = sum(c["n_uids"] for c in chains)
year_dist = defaultdict(int)
for c in chains:
    year_dist[c["n_years"]] += 1

print(f"\n{'='*60}")
print(f"PERSISTENT PLACES ANALYSIS")
print(f"{'='*60}")
print(f"Persistent places identified: {len(chains)}")
print(f"TCP UIDs consumed in chains:  {total_uids}")
print(f"\nYear span distribution:")
for span in sorted(year_dist):
    print(f"  {span} years: {year_dist[span]} places")

# Places spanning all 8 years
full_span = [c for c in chains if c["n_years"] == 8]
print(f"\nPlaces present in ALL 8 census years: {len(full_span)}")
if full_span:
    print(f"  Example: {full_span[0]['names']} ({full_span[0]['uids']})")

# Name variation within chains
multi_name = [c for c in chains if len(c["names"]) > 1]
print(f"\nChains with name variations: {len(multi_name)} ({100*len(multi_name)/len(chains):.1f}%)")

# UID fragmentation
unique_uids_in_chains = set()
for c in chains:
    unique_uids_in_chains.update(c["uids"])
print(f"\nUnique UIDs in chains: {len(unique_uids_in_chains)}")
print(f"If modeled correctly: {len(chains)} E53_Place entities")
print(f"Current model creates: ~{len(unique_uids_in_chains)} E53_Place entities")
print(f"Fragmentation factor: {len(unique_uids_in_chains)/len(chains):.1f}x")

out = {"summary": {"persistent_places": len(chains), "total_uids": total_uids,
       "year_span_distribution": dict(year_dist), "fragmentation_factor": round(len(unique_uids_in_chains)/len(chains), 2)},
       "chains": chains[:500]}  # top 500 for file size
with open(os.path.join(BASE, "analysis_persistent_places.json"), "w") as f:
    json.dump(out, f, indent=2)
print(f"\nSaved analysis_persistent_places.json")
