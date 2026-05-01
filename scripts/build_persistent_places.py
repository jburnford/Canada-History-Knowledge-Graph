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
import re
import pandas as pd
from pathlib import Path
from collections import defaultdict, Counter
import argparse
import sys

from _normalize import normalize_for_match, bridge_normalize

YEARS = [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921]
YEAR_PAIRS = list(zip(YEARS[:-1], YEARS[1:]))
YEAR_PAIR_SET = set(YEAR_PAIRS)


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
    pid_to_nodes = {}     # persistent_place_id -> list[(tcpuid, year)]
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
        pid_to_nodes[persistent_id] = list(nodes_sorted)

    return registry, tcpuid_year_map, pid_to_nodes


def load_year_links_pairs(links_dir: Path):
    """Load every year_links + ambiguous_links row keyed by year-pair so
    the bridge pass can look up cross-chain spatial overlap. Returns
    dict[(y1, y2)] -> set[(uid1, uid2)] of pairs that have any spatial
    relationship with positive iou OR any positive frac_from / frac_to
    (CONTAINS / WITHIN edges may have iou=0 but nonzero containment).

    A spatial-overlap pair between any TCPUID in chain A's year YA and any
    TCPUID in chain B's year YB confirms the two chains are spatially
    adjacent in that gap — the bridge needs this so it doesn't merge
    "Hamilton" township with a different "Hamilton" elsewhere in the province.

    Tuple (uid1, uid2) is ordered (y1-side, y2-side) so the lookup is direction-
    safe even when the same TCPUID is reused across years (TCPUIDs are
    year-scoped per project memory).
    """
    pairs_by_yp: dict[tuple[int, int], set[tuple[str, str]]] = {}
    for y1, y2 in YEAR_PAIRS:
        bucket: set[tuple[str, str]] = set()
        for stem in (f"year_links_{y1}_{y2}.csv", f"ambiguous_{y1}_{y2}.csv"):
            fpath = links_dir / stem
            if not fpath.exists():
                continue
            with open(fpath) as f:
                for row in csv.DictReader(f):
                    def _f(k: str) -> float:
                        try:
                            return float(row.get(k, "0") or "0")
                        except ValueError:
                            return 0.0
                    if _f("iou") <= 0.0 and _f("frac_from") <= 0.0 and _f("frac_to") <= 0.0:
                        continue
                    uid1 = row[f"tcpuid_{y1}"].strip()
                    uid2 = row[f"tcpuid_{y2}"].strip()
                    if uid1 and uid2:
                        bucket.add((uid1, uid2))
        pairs_by_yp[(y1, y2)] = bucket
    return pairs_by_yp


def _years_set(years_active: str) -> set[int]:
    if not years_active:
        return set()
    return {int(y) for y in years_active.split(";") if y}


def _spans_disjoint(spans: list[set[int]]) -> bool:
    seen: set[int] = set()
    for s in spans:
        if s & seen:
            return False
        seen |= s
    return True


def _gap_supported(chain_a_nodes: list[tuple[str, int]],
                   chain_b_nodes: list[tuple[str, int]],
                   pairs_by_yp: dict[tuple[int, int], set[frozenset[str]]]
                   ) -> tuple[bool, str]:
    """Confirm chain A's last year and chain B's first year are spatially
    adjacent. Returns (confirmed, confidence) where confidence ∈ {high, medium}.
    high = direct year_links overlap evidence; medium = year gap spans intervening
    censuses where neither chain has a presence (no spatial evidence available)."""
    last_a_year = max(y for _, y in chain_a_nodes)
    first_b_year = min(y for _, y in chain_b_nodes)
    if last_a_year >= first_b_year:
        return False, "overlap"

    # Adjacent census pair → require year_links spatial confirmation.
    if (last_a_year, first_b_year) in YEAR_PAIR_SET:
        bucket = pairs_by_yp.get((last_a_year, first_b_year), set())
        a_uids = {uid for uid, y in chain_a_nodes if y == last_a_year}
        b_uids = {uid for uid, y in chain_b_nodes if y == first_b_year}
        for ua in a_uids:
            for ub in b_uids:
                if (ua, ub) in bucket:
                    return True, "high"
        return False, "no_spatial_link"

    # Non-adjacent: chain A ends at e.g. 1881, chain B starts at e.g. 1911,
    # gap covers censuses where neither chain has a presence. We can't directly
    # verify spatial adjacency. Return medium-confidence so the curator can audit.
    return True, "medium"


def name_bridge_pass(registry, tcpuid_year_map, pid_to_nodes,
                      pairs_by_yp, *, restrict_province: str | None = None):
    """Second pass: merge chains that share (normalize_for_match(name), province)
    when their year-spans are strictly disjoint and the inter-chain gap is
    supported by year_links spatial evidence (high confidence) or covers
    intervening censuses with no member presence (medium confidence).

    Returns:
      merged_registry, merged_tcpuid_year_map,
      redirect_rows (list[dict]): one per subsumed chain id,
      bridge_lineage_rows (list[dict]): BRIDGE_NAME_MATCH edges,
      review_rows (list[dict]): families that were auto-merged but whose
        evidence is medium-confidence — useful for curator audit.
      skipped_rows (list[dict]): families that were NOT merged (overlap or
        ambiguity) — emitted for visibility.
    """
    # Group by (bridge_normalize(name), province). bridge_normalize strips
    # admin-tier suffixes (Town/City/Village/...) so the four Peterborough
    # variants ("Town of" / "Town—Ville" / "C") collapse to one key.
    # Directionals (N/S/E/W) and wards stay intact so we never merge across
    # those genuine distinctions.
    families: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in registry:
        norm = bridge_normalize(r["canonical_name"])
        prov = r["province"]
        if not norm or not prov:
            continue
        if restrict_province and prov != restrict_province:
            continue
        families[(norm, prov)].append(r)

    redirects: list[dict] = []
    bridge_lineage: list[dict] = []
    review_rows: list[dict] = []
    skipped_rows: list[dict] = []
    merged_into: dict[str, str] = {}   # subsumed_pid -> winner_pid
    winner_absorbed: dict[str, list[str]] = defaultdict(list)
    confidence_per_merge: dict[tuple[str, str], str] = {}

    for (norm, prov), members in families.items():
        if len(members) < 2:
            continue

        # Compute years_set per member; require strict disjointness across all.
        with_spans = [(m, _years_set(m["years_active"])) for m in members]
        all_spans = [s for _, s in with_spans]
        if not _spans_disjoint(all_spans):
            skipped_rows.append({
                "norm_name": norm,
                "province": prov,
                "n_members": len(members),
                "reason": "overlapping_year_spans",
                "members": ";".join(m["persistent_place_id"] for m in members),
            })
            continue

        # Sort by first year ascending.
        with_spans.sort(key=lambda ms: min(ms[1]))
        ordered = [m for m, _ in with_spans]

        # Walk consecutive pairs, gather evidence; abort on first failure.
        pair_evidence: list[str] = []
        ok = True
        for a, b in zip(ordered[:-1], ordered[1:]):
            a_nodes = pid_to_nodes.get(a["persistent_place_id"], [])
            b_nodes = pid_to_nodes.get(b["persistent_place_id"], [])
            confirmed, conf = _gap_supported(a_nodes, b_nodes, pairs_by_yp)
            if not confirmed:
                ok = False
                skipped_rows.append({
                    "norm_name": norm,
                    "province": prov,
                    "n_members": len(members),
                    "reason": f"gap_{a['persistent_place_id']}_to_{b['persistent_place_id']}_unsupported_{conf}",
                    "members": ";".join(m["persistent_place_id"] for m in members),
                })
                break
            pair_evidence.append(conf)
        if not ok:
            continue

        # Winner = chain with the latest anchor_year (canonical 1921 grounding wins).
        winner = max(ordered, key=lambda r: int(r["anchor_year"]))
        family_confidence = "medium" if "medium" in pair_evidence else "high"

        for m in ordered:
            if m["persistent_place_id"] == winner["persistent_place_id"]:
                continue
            merged_into[m["persistent_place_id"]] = winner["persistent_place_id"]
            winner_absorbed[winner["persistent_place_id"]].append(m["persistent_place_id"])
            redirects.append({
                "old_place_id": m["persistent_place_id"],
                "new_place_id": winner["persistent_place_id"],
                "province": prov,
                "old_canonical_name": m["canonical_name"],
                "new_canonical_name": winner["canonical_name"],
                "old_years_active": m["years_active"],
                "new_years_active": winner["years_active"],
                "confidence": family_confidence,
                "reason": "bridge_name_match",
                # Carry the (tcpuid, year) members of the SUBSUMED chain so the
                # renderer can emit per-presence URL redirects when the canonical
                # name slug changes (the per-presence URL embeds the chain's
                # canonical_name, so a bridge merge breaks the old presence URLs).
                "_subsumed_nodes": pid_to_nodes.get(m["persistent_place_id"], []),
            })
            bridge_lineage.append({
                "lineage_type": "BRIDGE_NAME_MATCH",
                ":START_ID": m["persistent_place_id"],
                ":END_ID": winner["persistent_place_id"],
                "change_year:int": min(_years_set(winner["years_active"]) or {0}),
                ":TYPE": "BRIDGE_NAME_MATCH",
            })
            confidence_per_merge[(m["persistent_place_id"], winner["persistent_place_id"])] = family_confidence

        if family_confidence == "medium":
            review_rows.append({
                "norm_name": norm,
                "province": prov,
                "n_members": len(members),
                "winner": winner["persistent_place_id"],
                "members": ";".join(m["persistent_place_id"] for m in ordered),
                "reason": "medium_confidence_gap",
            })

    if not merged_into:
        return registry, tcpuid_year_map, redirects, bridge_lineage, review_rows, skipped_rows

    # Apply merges: rebuild registry and remap tcpuid_year_map.
    # Step 1: remap tcpuid_year_map values.
    new_map = {k: merged_into.get(v, v) for k, v in tcpuid_year_map.items()}

    # Step 2: rebuild registry rows for winners (absorb subsumed members'
    # years_active), drop subsumed rows.
    pid_to_row = {r["persistent_place_id"]: r for r in registry}
    new_registry: list[dict] = []
    for r in registry:
        pid = r["persistent_place_id"]
        if pid in merged_into:
            continue
        absorbed = winner_absorbed.get(pid, [])
        if not absorbed:
            new_registry.append(r)
            continue
        # Merge years_active sets.
        years_set = _years_set(r["years_active"])
        for sub in absorbed:
            years_set |= _years_set(pid_to_row[sub]["years_active"])
        years_sorted = sorted(years_set)
        merged_row = dict(r)
        merged_row["years_active"] = ";".join(str(y) for y in years_sorted)
        merged_row["num_years"] = len(years_sorted)
        # anchor stays as the winner's anchor (latest-year by construction).
        new_registry.append(merged_row)

    return new_registry, new_map, redirects, bridge_lineage, review_rows, skipped_rows


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
    parser.add_argument(
        "--bridge-name-match",
        dest="bridge_name_match",
        action="store_true",
        default=True,
        help="Run name-based bridge pass after the strict IoU=1.0 union-find "
             "(default on; v10.5+).",
    )
    parser.add_argument(
        "--no-bridge-name-match",
        dest="bridge_name_match",
        action="store_false",
        help="Disable the name-bridge pass — emit pre-v10.5 strict-IoU registry.",
    )
    parser.add_argument(
        "--province",
        default=None,
        help="Restrict bridge-name-match merges to a single province (e.g. ON). "
             "Useful for subset audits; chains in other provinces stay strict.",
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
    registry, tcpuid_year_map, pid_to_nodes = build_persistent_places(same_as_links, node_meta)

    # Step 2b: Name-bridge pass — collapse same-modern-entity chains that the
    # strict IoU=1.0 union-find left split (e.g. four separate Peterborough
    # chains across 1851-1921). Year-disjointness + spatial-evidence gated.
    redirects: list[dict] = []
    bridge_lineage: list[dict] = []
    review_rows: list[dict] = []
    skipped_rows: list[dict] = []
    if args.bridge_name_match:
        print(f"\nRunning name-bridge pass"
              + (f" (province={args.province})" if args.province else "")
              + "...", file=sys.stderr)
        pairs_by_yp = load_year_links_pairs(links_dir)
        before = len(registry)
        registry, tcpuid_year_map, redirects, bridge_lineage, review_rows, skipped_rows = \
            name_bridge_pass(
                registry, tcpuid_year_map, pid_to_nodes, pairs_by_yp,
                restrict_province=args.province,
            )
        print(f"  Bridge merges: {len(redirects)} chains subsumed "
              f"({before} → {len(registry)} chains)", file=sys.stderr)
        print(f"  Bridge lineage edges: {len(bridge_lineage)}", file=sys.stderr)
        print(f"  Medium-confidence families flagged for review: {len(review_rows)}",
              file=sys.stderr)
        print(f"  Same-name families NOT merged: {len(skipped_rows)}", file=sys.stderr)

    # Step 3: Build lineage from CONTAINS/WITHIN
    print(f"\nBuilding lineage relationships...", file=sys.stderr)
    lineage = build_lineage(lineage_links, tcpuid_year_map)
    lineage.extend(bridge_lineage)

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

    # Bridge pass artifacts
    redirect_cols = [
        "old_place_id", "new_place_id", "province",
        "old_canonical_name", "new_canonical_name",
        "old_years_active", "new_years_active",
        "confidence", "reason",
    ]
    # Strip the _subsumed_nodes column for the CSV — it's only used below to
    # derive the per-presence redirect file.
    csv_redirects = [{k: v for k, v in r.items() if k in redirect_cols}
                     for r in redirects]
    pd.DataFrame(csv_redirects, columns=redirect_cols).to_csv(
        out_dir / "place_chain_redirects.csv", index=False)
    print(f"  place_chain_redirects.csv: {len(redirects)} subsumed chain ids",
          file=sys.stderr)

    # Per-presence URL redirects: the renderer slugs presence URLs from the
    # CHAIN's canonical_name. When a bridge merge changes that canonical_name
    # ("Peterborough, Town of" → "Peterborough, C"), the presence URLs for
    # every (tcpuid, year) in the subsumed chain change, breaking inbound
    # links. Emit one row per presence whose URL slug actually changes so
    # the renderer can write a redirect stub at the old URL.
    presence_redirect_rows = []
    for r in redirects:
        old_name = r["old_canonical_name"]
        new_name = r["new_canonical_name"]
        if not old_name or old_name == new_name:
            continue
        for (uid, yr) in r["_subsumed_nodes"]:
            presence_redirect_rows.append({
                "tcpuid": uid,
                "year": yr,
                "province": r["province"],
                "old_canonical_name": old_name,
                "new_canonical_name": new_name,
                "old_place_id": r["old_place_id"],
                "new_place_id": r["new_place_id"],
            })
    presence_cols = ["tcpuid", "year", "province",
                      "old_canonical_name", "new_canonical_name",
                      "old_place_id", "new_place_id"]
    pd.DataFrame(presence_redirect_rows, columns=presence_cols).to_csv(
        out_dir / "place_presence_redirects.csv", index=False)
    print(f"  place_presence_redirects.csv: {len(presence_redirect_rows)} "
          f"presence-URL redirects",
          file=sys.stderr)

    review_cols = ["norm_name", "province", "n_members", "winner", "members", "reason"]
    pd.DataFrame(review_rows, columns=review_cols).to_csv(
        out_dir / "place_chain_bridge_review.csv", index=False)
    skipped_cols = ["norm_name", "province", "n_members", "reason", "members"]
    pd.DataFrame(skipped_rows, columns=skipped_cols).to_csv(
        out_dir / "place_chain_bridge_skipped.csv", index=False)
    if review_rows or skipped_rows:
        print(f"  place_chain_bridge_review.csv: {len(review_rows)} medium-confidence merges",
              file=sys.stderr)
        print(f"  place_chain_bridge_skipped.csv: {len(skipped_rows)} same-name families NOT merged",
              file=sys.stderr)

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
