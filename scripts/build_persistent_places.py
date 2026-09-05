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
import math
import re
import pandas as pd
from pathlib import Path
from collections import defaultdict, Counter
import argparse
import sys

from _normalize import normalize_for_match, bridge_normalize, suffix_tier

YEARS = [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921]
YEAR_PAIRS = list(zip(YEARS[:-1], YEARS[1:]))
YEAR_PAIR_SET = set(YEAR_PAIRS)

# The linker (link_csd_years_spatial_v2.classify_relationship) classifies
# SAME_AS at IoU >= 0.98 AND min(frac) >= 0.98. Union at the linker's own
# threshold — the old `iou >= 1.0` gate silently discarded 587 near-perfect
# continuation links (London/London IoU 0.993 etc.), fragmenting chains.
SAME_AS_MIN_IOU = 0.98

# Max centroid distance (km) between a chain's last presence and a same-name
# chain's first presence for a MEDIUM-confidence (non-adjacent-gap) bridge
# merge. Mirrors the 50 km sibling gate in join_wikidata_to_places.py.
BRIDGE_CENTROID_GATE_KM = 50.0

# Admin-tier groups that must not be bridged together: a Township/Parish is
# the rural unit that COEXISTS with its same-name town/village, not an
# earlier or later form of it ("Trois Rivières, Paroisse" vs the city).
_RURAL_TIERS = {"TOWNSHIP", "PARISH", "RESERVE"}
_URBAN_TIERS = {"URBAN", "VILLAGE", "HAMLET"}


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
    """Load year_links AND ambiguous CSV files.

    Returns (same_as_links, lineage_links, node_meta, rescued_rows).

    - year_links_*.csv: SAME_AS at IoU >= SAME_AS_MIN_IOU chains; CONTAINS/
      WITHIN become lineage candidates. (Unchanged except the threshold —
      the old `iou >= 1.0` discarded 587 linker-classified SAME_AS links.)
    - ambiguous_*.csv: SAME_AS rows here are spatially identical polygons
      (IoU >= 0.98, both fracs >= 0.98) whose fuzzy name similarity fell
      below the linker's 80 gate — nearly all OCR variants (Kincaraio/
      Kincardine) or renamings. Spatial identity at that strictness defines
      chain membership in this model, so accept them, and emit every rescue
      to same_as_rescued.csv for curator audit. OVERLAPS rows in the
      ambiguous file stay ignored (no node_meta either, so previously-
      fallback singleton ids downstream don't churn).
    """
    same_as_links = []
    lineage_links = []
    node_meta = {}  # (tcpuid, year) -> {name, cd, province}
    rescued_rows = []

    for y1, y2 in YEAR_PAIRS:
        for source, fname in (("year_links", f"year_links_{y1}_{y2}.csv"),
                               ("ambiguous", f"ambiguous_{y1}_{y2}.csv")):
            fpath = links_dir / fname
            if not fpath.exists():
                if source == "year_links":
                    print(f"  Warning: {fpath} not found, skipping", file=sys.stderr)
                continue

            with open(fpath) as f:
                for row in csv.DictReader(f):
                    rel = row["relationship"]

                    try:
                        iou = float(row["iou"])
                    except (ValueError, KeyError):
                        iou = 0.0

                    if source == "ambiguous" and not (
                            rel == "SAME_AS" and iou >= SAME_AS_MIN_IOU):
                        continue

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

                    if rel == "SAME_AS" and iou >= SAME_AS_MIN_IOU:
                        same_as_links.append(((uid1, y1), (uid2, y2)))
                        if source == "ambiguous":
                            rescued_rows.append({
                                "tcpuid_from": uid1, "year_from": y1,
                                "name_from": name1,
                                "tcpuid_to": uid2, "year_to": y2,
                                "name_to": name2,
                                "province": pr1,
                                "iou": iou,
                                "name_similarity": row.get("name_similarity", ""),
                            })
                    elif rel in ("CONTAINS", "WITHIN"):
                        lineage_links.append({
                            "uid_from": uid1, "year_from": y1,
                            "uid_to": uid2, "year_to": y2,
                            "relationship": rel,
                            "iou": iou,
                        })

    print(f"  Loaded {len(same_as_links)} SAME_AS (IoU>={SAME_AS_MIN_IOU}) links "
          f"({len(rescued_rows)} rescued from ambiguous files)", file=sys.stderr)
    print(f"  Loaded {len(lineage_links)} CONTAINS/WITHIN links", file=sys.stderr)
    return same_as_links, lineage_links, node_meta, rescued_rows


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
            if persistent_id in used_ids:
                # Extremely rare: add full range, then a counter. (The old
                # code looped assigning the same range string forever if
                # THAT collided too — latent infinite loop.)
                persistent_id = f"PLACE_{anchor_tcpuid}_{years_present[0]}_{years_present[-1]}"
                n = 2
                while persistent_id in used_ids:
                    persistent_id = (f"PLACE_{anchor_tcpuid}_{years_present[0]}"
                                     f"_{years_present[-1]}_{n}")
                    n += 1
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


def load_presence_centroids(centroids_dir: Path) -> dict[tuple[str, int], tuple[float, float]]:
    """Load per-presence centroids from e94_space_primitive_{year}.csv.

    Keyed (tcpuid, year) -> (lat, lon). These files are geometry-derived and
    keyed by year-scoped tcpuids — they can never leak chain ids back into
    the builder (unlike e93_presence_cd_*, see build_persistent_cds guard).
    Returns {} with a warning when the files are absent. Non-adjacent name
    bridges are then rejected: missing evidence cannot authorize a merge."""
    centroids: dict[tuple[str, int], tuple[float, float]] = {}
    for yr in YEARS:
        fpath = centroids_dir / f"e94_space_primitive_{yr}.csv"
        if not fpath.exists():
            continue
        with open(fpath) as f:
            for row in csv.DictReader(f):
                sid = row.get("space_id:ID", "")
                if not sid.endswith("_centroid"):
                    continue
                stem = sid[: -len("_centroid")]
                uid, _, yr_s = stem.rpartition("_")
                try:
                    lat = float(row["latitude:float"])
                    lon = float(row["longitude:float"])
                    centroids[(uid, int(yr_s))] = (lat, lon)
                except (KeyError, ValueError):
                    continue
    if not centroids:
        print("  WARNING: no presence centroids found under "
              f"{centroids_dir}/e94_space_primitive_*.csv — the medium-"
              "confidence non-adjacent bridges will be skipped.", file=sys.stderr)
    return centroids


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


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
                   pairs_by_yp: dict[tuple[int, int], set[frozenset[str]]],
                   centroids: dict[tuple[str, int], tuple[float, float]] | None = None,
                   ) -> tuple[bool, str]:
    """Confirm chain A's last year and chain B's first year are spatially
    adjacent. Returns (confirmed, confidence) where confidence ∈ {high, medium}.
    high = direct year_links overlap evidence; medium = year gap spans intervening
    censuses where neither chain has a presence (no direct overlap evidence —
    gated instead by centroid distance when centroids are available)."""
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
    # gap covers censuses where neither chain has a presence. No overlap
    # evidence exists, so gate on centroid distance: a same-name chain
    # >50 km away is a namesake elsewhere in the province, not a
    # continuation ("a different Hamilton").
    centroids = centroids or {}
    a_pts = [centroids[(uid, y)] for uid, y in chain_a_nodes
             if y == last_a_year and (uid, y) in centroids]
    b_pts = [centroids[(uid, y)] for uid, y in chain_b_nodes
             if y == first_b_year and (uid, y) in centroids]
    if not a_pts or not b_pts or not all(math.isfinite(v) for p in a_pts + b_pts for v in p):
        return False, "missing_centroid_evidence"
    min_km = min(_haversine_km(pa, pb) for pa in a_pts for pb in b_pts)
    if min_km > BRIDGE_CENTROID_GATE_KM:
        return False, f"centroid_gate_{min_km:.0f}km"
    return True, "medium"


def name_bridge_pass(registry, tcpuid_year_map, pid_to_nodes,
                      pairs_by_yp, *, restrict_province: str | None = None,
                      centroids: dict | None = None):
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
        # "NO DATA" is the GDB's placeholder for unenumerated territory —
        # two NO DATA chains share a name, never an identity. Never bridge.
        if norm == "no data":
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

        # Tier gate: bridge_normalize strips ALL admin-tier suffixes, so a
        # rural unit ("X, Township" / "X, Paroisse") and its same-name urban
        # unit key identically — but they are coexisting entities, not one
        # place renamed. When both rural and urban tiers appear in a family,
        # exclude the RURAL members (they keep their own chains) and let the
        # urban-ladder members (BARE/Village/Town/City — legitimate
        # incorporation sequences) bridge among themselves.
        tier_by_pid = {m["persistent_place_id"]: suffix_tier(m["canonical_name"])
                       for m in members}
        tset = set(tier_by_pid.values())
        if (tset & _RURAL_TIERS) and (tset & _URBAN_TIERS):
            rural = [m for m in members
                     if tier_by_pid[m["persistent_place_id"]] in _RURAL_TIERS]
            skipped_rows.append({
                "norm_name": norm,
                "province": prov,
                "n_members": len(rural),
                "reason": "tier_conflict_rural_member_excluded",
                "members": ";".join(m["persistent_place_id"] for m in rural),
            })
            members = [m for m in members
                       if tier_by_pid[m["persistent_place_id"]] not in _RURAL_TIERS]
            if len(members) < 2:
                continue

        # Greedy sequence assembly (replaces the old all-or-nothing family
        # disjointness rule, which blocked e.g. London Township 1851-61 from
        # bridging to London Township 1871-1921 just because the same-name
        # CITY chains overlap the family's span). Members are sorted by
        # first year and attached to the best OPEN sequence whose last
        # member's span ends before this member starts AND whose gap is
        # evidence-supported. Preference order: same admin tier, then
        # high > medium evidence, then smallest year gap. Members that fit
        # no sequence open a new one; each resulting sequence with >= 2
        # members merges independently.
        with_spans = [(m, _years_set(m["years_active"])) for m in members]
        with_spans.sort(key=lambda ms: (min(ms[1]), max(ms[1])))

        sequences: list[dict] = []
        for m, span in with_spans:
            best = None
            for seq in sequences:
                last_m, last_span = seq["members"][-1], seq["years"]
                if last_span & span or max(last_span) >= min(span):
                    continue
                a_nodes = pid_to_nodes.get(last_m["persistent_place_id"], [])
                b_nodes = pid_to_nodes.get(m["persistent_place_id"], [])
                confirmed, conf = _gap_supported(a_nodes, b_nodes, pairs_by_yp,
                                                  centroids)
                if not confirmed:
                    continue
                tier_mismatch = (suffix_tier(last_m["canonical_name"])
                                 != suffix_tier(m["canonical_name"]))
                # A medium (centroid-only) gap may not cross admin tiers:
                # weak evidence + a tier change is the township→city false-
                # merge signature (London Township 1851-61 vs London, C).
                # High-confidence (direct spatial overlap) crossings remain
                # allowed — real incorporations have overlapping polygons.
                if conf != "high" and tier_mismatch:
                    continue
                gap = min(span) - max(last_span)
                score = (tier_mismatch, 0 if conf == "high" else 1, gap)
                if best is None or score < best[0]:
                    best = (score, seq, conf)
            if best is None:
                sequences.append({"members": [m], "years": set(span),
                                  "evidence": []})
            else:
                _, seq, conf = best
                seq["members"].append(m)
                seq["years"] |= span
                seq["evidence"].append(conf)

        merge_seqs = [s for s in sequences if len(s["members"]) >= 2]
        if not merge_seqs:
            skipped_rows.append({
                "norm_name": norm,
                "province": prov,
                "n_members": len(members),
                "reason": "no_supported_pairs",
                "members": ";".join(m["persistent_place_id"] for m in members),
            })
            continue
        if len(sequences) > 1:
            # Partial merge — family split into parallel identities. Audit.
            skipped_rows.append({
                "norm_name": norm,
                "province": prov,
                "n_members": len(members),
                "reason": f"partitioned_into_{len(sequences)}_sequences",
                "members": " | ".join(
                    ";".join(m["persistent_place_id"] for m in s["members"])
                    for s in sequences),
            })

        for seq in merge_seqs:
            ordered = seq["members"]
            # Winner = chain with the latest anchor_year (canonical 1921
            # grounding wins).
            winner = max(ordered, key=lambda r: int(r["anchor_year"]))
            family_confidence = "medium" if "medium" in seq["evidence"] else "high"

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
                    # Carry the (tcpuid, year) members of the SUBSUMED chain so
                    # the renderer can emit per-presence URL redirects when the
                    # canonical name slug changes (the per-presence URL embeds
                    # the chain's canonical_name, so a bridge merge breaks the
                    # old presence URLs).
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
                    "n_members": len(ordered),
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
    parser.add_argument(
        "--centroids-dir",
        default="neo4j_cidoc_crm_v2",
        help="Directory with e94_space_primitive_{year}.csv presence "
             "centroids used by the medium-confidence bridge centroid gate. "
             "Non-adjacent bridges are skipped when centroid evidence is absent.",
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
    same_as_links, lineage_links, node_meta, rescued_rows = \
        load_all_year_links(links_dir)

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
        centroids = load_presence_centroids(Path(args.centroids_dir))
        before = len(registry)
        registry, tcpuid_year_map, redirects, bridge_lineage, review_rows, skipped_rows = \
            name_bridge_pass(
                registry, tcpuid_year_map, pid_to_nodes, pairs_by_yp,
                restrict_province=args.province,
                centroids=centroids,
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
    # BRIDGE_NAME_MATCH edges are NOT appended to place_lineage.csv: their
    # :START_ID is the subsumed chain id, which is deleted from the registry
    # in the same pass — every such edge dangles. The old→new mapping already
    # lives in place_chain_redirects.csv; the edges go to their own file
    # below purely for audit.

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

    # SAME_AS links rescued from the ambiguous_* files (spatially identical
    # polygons whose fuzzy name similarity fell below the linker's gate) —
    # full audit trail for curators.
    rescued_cols = ["tcpuid_from", "year_from", "name_from",
                     "tcpuid_to", "year_to", "name_to",
                     "province", "iou", "name_similarity"]
    pd.DataFrame(rescued_rows, columns=rescued_cols).to_csv(
        out_dir / "same_as_rescued.csv", index=False)
    print(f"  same_as_rescued.csv: {len(rescued_rows)} SAME_AS links rescued "
          f"from ambiguous files", file=sys.stderr)

    # BRIDGE_NAME_MATCH audit edges (subsumed → winner). Kept out of
    # place_lineage.csv because the subsumed ids no longer exist as nodes.
    bridge_cols = ["lineage_type", ":START_ID", ":END_ID", "change_year:int", ":TYPE"]
    pd.DataFrame(bridge_lineage, columns=bridge_cols).to_csv(
        out_dir / "place_bridge_lineage.csv", index=False)
    print(f"  place_bridge_lineage.csv: {len(bridge_lineage)} bridge audit edges",
          file=sys.stderr)
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
