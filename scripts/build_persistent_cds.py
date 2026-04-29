#!/usr/bin/env python3
"""
Build persistent Census Division (CD) registry from cd_links_output spatial
overlap analysis, mirroring scripts/build_persistent_places.py for CDs.

CDs are currently year-name-keyed in neo4j_cidoc_crm_v2/e53_place_cd.csv
(one row per (province, NAME_CD_<year>) pair → 579 raw CDs). The same
physical CD often appears under multiple labels across census years
("Renfrew, North—Nord" 1871-1901, "Renfrew N" 1911) plus genuine
split/merge lineage (Renfrew unified 1851-61 → split N+S 1871-1911 →
re-merged 1921). This script collapses the format-variants into
~persistent CD chains while preserving the lineage as edges.

Algorithm: Union-Find over cd_links with multi-rule accept:
  Rule 1: SAME_AS, IoU >= 0.95
  Rule 2: SAME_AS, IoU >= 0.85 + canonical-name match
  Rule 3: WITHIN/CONTAINS, frac >= 0.95 + canonical-name match
  Rule 4 (post-Union-Find): two preliminary chains A, A' fuse iff
          (a) A SPLIT_INTO set S, every chain in S MERGED_INTO A',
          (b) canonical_name(A) == canonical_name(A') + same province,
          (c) A.last_year < A'.first_year (no temporal overlap),
          (d) no chain in S persists past A'.first_year.

  1-to-1 uniqueness demotion: any Rule 2/3 candidate where source has
  multiple descendants OR target has multiple ancestors → demote to
  lineage edge instead of chain merge.

Outputs to persistent_cds_output/:
  - persistent_cd_registry.csv: one row per persistent CD chain
  - cd_id_year_to_chain.csv: (raw cd_id, year) -> chain place_id
  - cd_lineage.csv: SPLIT_FROM / MERGED_INTO edges between chains
                    (Neo4j-import format mirror of place_lineage.csv)
  - chain_audit.csv (with --audit): per-link decisions
"""

import argparse
import csv
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

YEARS = [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921]
YEAR_PAIRS = list(zip(YEARS[:-1], YEARS[1:]))

RULE1_IOU = 0.95       # SAME_AS strong-spatial only
RULE2_IOU = 0.85       # SAME_AS weaker-spatial, canonical-name must match
RULE3_FRAC = 0.95      # WITHIN/CONTAINS strong containment, name must match


# ---- Name canonicalization ------------------------------------------------

# Map directional abbreviations to full English words.
DIR_ABBREV = {
    "N": "North", "S": "South", "E": "East", "W": "West",
}
# Bilingual directional pairs to collapse to English.
BILINGUAL_DIR = {
    "north": "North", "nord": "North",
    "south": "South", "sud": "South",
    "east": "East", "est": "East",
    "west": "West", "ouest": "West",
    "centre": "Centre", "center": "Centre",
}
# Bilingual administrative tier suffixes to collapse.
TIER_SUFFIX_PAIRS = [
    (re.compile(r",?\s*City[—\-]\s*(?:Cit[ée]|Ville)\s*$", re.IGNORECASE), " City"),
    (re.compile(r",?\s*\(City[—\-]Ville\)\s*$", re.IGNORECASE), " City"),
    (re.compile(r",?\s*Cit[ée]\s*$", re.IGNORECASE), " City"),
    (re.compile(r",?\s*City\s*$", re.IGNORECASE), " City"),
    (re.compile(r",?\s*\(?County[—\-]Comt[ée]\)?\s*$", re.IGNORECASE), " County"),
    (re.compile(r",?\s*\(?County[—\- ]?Ville\)?\s*$", re.IGNORECASE), " County"),
    (re.compile(r",?\s*Comt[ée]\s*$", re.IGNORECASE), " County"),
    (re.compile(r",?\s*\(?County\)?\s*$", re.IGNORECASE), " County"),
]
DIR_FULL_RE = re.compile(
    r",?\s*(North|Nord|South|Sud|East|Est|West|Ouest|Centre|Center)"
    r"(?:[—\-/]\s*(North|Nord|South|Sud|East|Est|West|Ouest|Centre|Center))?"
    r"(\s+(?:City|County|District))?\s*$",
    re.IGNORECASE,
)
DIR_SINGLE_LETTER_RE = re.compile(r"\s+([NSEW])\.?\s*$")
# Bilingual single-letter pair (e.g., "Toronto W-O" = West-Ouest, "Huron W-O").
# First letter is English (N/S/E/W); second is French (Nord/Sud/Est/Ouest = N/S/E/O).
DIR_DOUBLE_LETTER_RE = re.compile(r"\s+([NSEW])-([NSEO])\.?\s*$", re.IGNORECASE)


def canonical_cd_name(raw: str) -> str:
    """Normalize a CD's NAME_CD value into a canonical form for chain matching.

    Examples:
      'Renfrew'                        -> 'Renfrew'
      'Renfrew, North—Nord'            -> 'Renfrew North'
      'Renfrew N'                      -> 'Renfrew North'
      'Renfrew, South—Sud'             -> 'Renfrew South'
      'Renfrew S'                      -> 'Renfrew South'
      'Toronto, City—Cité'             -> 'Toronto City'
      'Toronto, City'                  -> 'Toronto City'
      'Toronto, East—Est, City—Cité'   -> 'Toronto East City'
      'Quebec, County—Comté'           -> 'Quebec County'
    """
    if not raw:
        return ""
    s = raw.strip()

    # Iteratively peel suffixes (City—Cité; County—Comté; directional).
    # Loop because some names have multiple suffixes ("Toronto, East—Est, City—Cité").
    # Strict change-detection: only re-loop if the normalized output differs from
    # the input. Without this, "Renfrew N" → "Renfrew North" gets re-matched by
    # DIR_FULL_RE on "North" and loops forever.
    for _ in range(8):  # bounded; even pathological inputs converge in <8 passes
        original = s
        for pat, repl in TIER_SUFFIX_PAIRS:
            new = pat.sub(repl, s)
            if new != s:
                cand = re.sub(r"\s+", " ", new.strip().rstrip(",")).strip()
                if cand != s:
                    s = cand
                    break
        m = DIR_FULL_RE.search(s)
        if m:
            base = s[: m.start()].rstrip().rstrip(",").rstrip()
            standardized = BILINGUAL_DIR.get(m.group(1).lower(), m.group(1).title())
            tier_tail = (m.group(3) or "").strip()
            tier_part = f" {tier_tail}" if tier_tail else ""
            cand = re.sub(r"\s+", " ", f"{base} {standardized}{tier_part}").strip()
            if cand != s:
                s = cand
                continue
        m_dbl = DIR_DOUBLE_LETTER_RE.search(s)
        if m_dbl:
            base = s[: m_dbl.start()].rstrip().rstrip(",").rstrip()
            # First letter is the English directional (W-O = West).
            cand = re.sub(r"\s+", " ",
                          f"{base} {DIR_ABBREV[m_dbl.group(1).upper()]}").strip()
            if cand != s:
                s = cand
                continue
        m2 = DIR_SINGLE_LETTER_RE.search(s)
        if m2:
            base = s[: m2.start()].rstrip().rstrip(",").rstrip()
            cand = re.sub(r"\s+", " ", f"{base} {DIR_ABBREV[m2.group(1)]}").strip()
            if cand != s:
                s = cand
                continue
        if s == original:
            break

    return re.sub(r"\s+", " ", s).strip()


def normalize_for_match(name: str) -> str:
    """Loose name-equality key used by Rules 1-3 chain matching and the
    Rule 4-NAME / split-detect / Rule 4-BRIDGE name comparisons.

    Folds diacritics (Châteauguay → chateauguay), unifies straight and
    curly apostrophes and backticks, treats hyphen as space (Jacques-Cartier
    matches Jacques Cartier), collapses whitespace, lowercases. Used only
    for matching — does NOT replace canonical_cd_name as displayed."""
    if not name:
        return ""
    # Unify quote variants BEFORE diacritic folding: curly apostrophe is not
    # ASCII, so the encode("ascii", "ignore") step below would strip it
    # entirely — silently breaking equality between "L'Islet" (curly) and
    # "L'Islet" (straight).
    s = name.replace("’", "'").replace("‘", "'").replace("`", "'")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def parse_cd_id(cd_id: str):
    """Return (province, raw_name) from cd_id format CD_<PROV>_<name_underscored>.
    The raw name may contain commas, em-dashes, and other punctuation; we
    just unescape underscores -> spaces."""
    parts = cd_id.split("_", 2)
    if len(parts) < 3 or parts[0] != "CD":
        return None, None
    prov = parts[1]
    name = parts[2].replace("_", " ")
    return prov, name


def chain_id_for(prov: str, canonical_name: str) -> str:
    """Mint a chain place_id from canonical name."""
    return f"CD_{prov}_{canonical_name.replace(' ', '_')}"


# -- Union-Find -------------------------------------------------------------
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
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
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


# -- Link classification ---------------------------------------------------

def _classify(rel: str, iou: float, frac_from: float, frac_to: float,
              canon1: str, canon2: str) -> int:
    """Return accept-rule number (1, 2, 3) or 0 to reject."""
    n1, n2 = normalize_for_match(canon1), normalize_for_match(canon2)
    name_match = bool(n1) and n1 == n2

    if rel == "SAME_AS":
        if iou >= RULE1_IOU:
            return 1
        if iou >= RULE2_IOU and name_match:
            return 2
        return 0

    if rel in ("WITHIN", "CONTAINS", "OVERLAPS"):
        # max-of-fractions catches both "A is within B" (frac_from=1.0) and
        # "B is within A" (frac_to=1.0). At least one polygon nearly contained.
        frac = max(frac_from, frac_to)
        if frac >= RULE3_FRAC and name_match:
            return 3
        return 0

    return 0


def load_all_cd_links(links_dir: Path):
    """Load cd_links AND cd_ambiguous CSVs, applying Rules 1-3.

    Returns:
      accepted_links: list of dicts (uid_from, year_from, name_from,
                       uid_to, year_to, name_to, rel, iou, frac_from,
                       frac_to, source, accept_rule)
      lineage_links:  list of dicts for CONTAINS/WITHIN that were NOT
                       chained (split/merge candidates)
      node_meta:      (cd_id, year) -> {name, province, canonical_name}
    """
    accepted_links = []
    lineage_links = []
    node_meta = {}
    rule_counts = Counter()
    source_counts = Counter()

    for y1, y2 in YEAR_PAIRS:
        for source_label, fname in (
            ("high_confidence", f"cd_links_{y1}_{y2}.csv"),
            ("ambiguous", f"cd_ambiguous_{y1}_{y2}.csv"),
        ):
            fpath = links_dir / fname
            if not fpath.exists():
                print(f"  Warning: {fpath} not found, skipping", file=sys.stderr)
                continue

            with open(fpath) as f:
                for row in csv.DictReader(f):
                    rel = row["relationship"]
                    cd_from = row["cd_from"].strip()
                    cd_to = row["cd_to"].strip()

                    prov1, name1 = parse_cd_id(cd_from)
                    prov2, name2 = parse_cd_id(cd_to)
                    if not prov1 or not prov2:
                        continue
                    canon1 = canonical_cd_name(name1)
                    canon2 = canonical_cd_name(name2)

                    node_meta[(cd_from, y1)] = {
                        "name": name1, "province": prov1, "canonical_name": canon1,
                    }
                    node_meta[(cd_to, y2)] = {
                        "name": name2, "province": prov2, "canonical_name": canon2,
                    }

                    def _f(key):
                        try:
                            return float(row.get(key, "") or 0.0)
                        except ValueError:
                            return 0.0

                    iou = _f("iou")
                    frac_from = _f("from_fraction")
                    frac_to = _f("to_fraction")

                    rule = _classify(rel, iou, frac_from, frac_to, canon1, canon2)

                    if rule > 0:
                        accepted_links.append({
                            "uid_from": cd_from, "year_from": y1, "name_from": name1,
                            "uid_to": cd_to, "year_to": y2, "name_to": name2,
                            "canon_from": canon1, "canon_to": canon2,
                            "rel": rel, "iou": iou,
                            "frac_from": frac_from, "frac_to": frac_to,
                            "source": source_label, "accept_rule": rule,
                        })
                        rule_counts[rule] += 1
                        source_counts[source_label] += 1
                    elif rel in ("CONTAINS", "WITHIN", "OVERLAPS"):
                        # Even sub-threshold overlaps are evidence of split/merge
                        # lineage when the canonical names suggest it. The
                        # 1861→1871 Renfrew → Renfrew_North split has IoU 0.41
                        # because the unified CD covers both future halves;
                        # neither half passes Rule 3 individually (frac<0.95)
                        # but together they form a proper SPLIT_FROM lineage.
                        # Filter to canonical-name matches OR strict containment
                        # (max(frac_from, frac_to) >= 0.5) to avoid noise.
                        n1 = normalize_for_match(canon1)
                        n2 = normalize_for_match(canon2)
                        canon_match = bool(n1) and n1 == n2
                        max_frac = max(frac_from, frac_to)
                        if canon_match or max_frac >= 0.5:
                            # CONTAINS: from-polygon contains to-polygon → high
                            # frac_to (most of `to` is inside `from`).
                            # WITHIN: from-polygon is inside to-polygon → high
                            # frac_from. Mapping is intentionally NOT inverted.
                            store_rel = rel if rel != "OVERLAPS" else (
                                "CONTAINS" if frac_to >= frac_from else "WITHIN"
                            )
                            lineage_links.append({
                                "uid_from": cd_from, "year_from": y1,
                                "uid_to": cd_to, "year_to": y2,
                                "relationship": store_rel, "iou": iou,
                            })

    print(f"  Accepted chain links by rule:", file=sys.stderr)
    print(f"    Rule 1 (SAME_AS, IoU>={RULE1_IOU}):           {rule_counts[1]}", file=sys.stderr)
    print(f"    Rule 2 (SAME_AS, IoU>={RULE2_IOU} + name):     {rule_counts[2]}", file=sys.stderr)
    print(f"    Rule 3 (CONTAINS/WITHIN, frac>={RULE3_FRAC} + name): {rule_counts[3]}", file=sys.stderr)
    print(f"  By source: high_confidence={source_counts['high_confidence']}, "
          f"ambiguous={source_counts['ambiguous']}", file=sys.stderr)
    print(f"  Lineage candidates (rejected CONTAINS/WITHIN): {len(lineage_links)}",
          file=sys.stderr)
    return accepted_links, lineage_links, node_meta


def augment_node_meta_from_e53(node_meta: dict, cidoc_dir: Path):
    """Add (cd_id, year) entries for CDs in e53_place_cd.csv that don't appear
    in any cd_links pair. These become singleton chains. Also need
    e93_presence_cd_<year>.csv to know which years each CD exists in."""
    e53_path = cidoc_dir / "e53_place_cd.csv"
    if not e53_path.exists():
        print(f"  Warning: {e53_path} not found, skipping augmentation",
              file=sys.stderr)
        return
    cd_master = {}  # cd_id -> {name, province}
    with open(e53_path) as f:
        for r in csv.DictReader(f):
            cd_master[r["place_id:ID"]] = {
                "name": r["name"], "province": r["province"],
            }

    added = 0
    for yr in YEARS:
        fpath = cidoc_dir / f"e93_presence_cd_{yr}.csv"
        if not fpath.exists():
            continue
        with open(fpath) as f:
            for r in csv.DictReader(f):
                cd_id = r["cd_id"].strip()
                key = (cd_id, yr)
                if key in node_meta:
                    continue
                meta = cd_master.get(cd_id)
                if not meta:
                    continue
                node_meta[key] = {
                    "name": meta["name"],
                    "province": meta["province"],
                    "canonical_name": canonical_cd_name(meta["name"]),
                }
                added += 1
    print(f"  Augmented node_meta with {added} CD-year presences not in cd_links",
          file=sys.stderr)


def find_name_only_rescue_links(node_meta, accepted_links):
    """Adjacent-year name-only rescue: chains two CDs in consecutive census
    years when they share canonical_name + province AND that combination is
    unique in both years. Catches cases where boundary shifts (~15-20%)
    push the spatial overlap below Rule 3's frac>=0.95 threshold but the
    administrative entity is clearly the same.

    Mirrors build_persistent_places.find_name_only_rescue_links."""
    by_key = defaultdict(list)
    for (cd_id, yr), meta in node_meta.items():
        canon = meta.get("canonical_name", "")
        prov = meta.get("province", "")
        if not canon or not prov:
            continue
        by_key[(normalize_for_match(canon), prov, yr)].append((cd_id, yr))

    existing_pairs = set()
    for link in accepted_links:
        a = (link["uid_from"], link["year_from"])
        b = (link["uid_to"], link["year_to"])
        existing_pairs.add((a, b))
        existing_pairs.add((b, a))

    new_links = []
    for y1, y2 in YEAR_PAIRS:
        for (canon, prov, yr), nodes in list(by_key.items()):
            if yr != y1 or len(nodes) != 1:
                continue
            partners = by_key.get((canon, prov, y2), [])
            if len(partners) != 1:
                continue
            a = nodes[0]
            b = partners[0]
            if (a, b) in existing_pairs:
                continue
            new_links.append({
                "uid_from": a[0], "year_from": y1,
                "name_from": node_meta[a].get("name", ""),
                "uid_to": b[0], "year_to": y2,
                "name_to": node_meta[b].get("name", ""),
                "canon_from": canon, "canon_to": canon,
                "rel": "NAME_ONLY", "iou": 0.0,
                "frac_from": 0.0, "frac_to": 0.0,
                "source": "name_only_rescue", "accept_rule": 4,
            })

    print(f"  Rule 4-NAME (adjacent-year canonical-unique rescue): {len(new_links)}",
          file=sys.stderr)
    return new_links


def detect_splits_and_demote(accepted_links, links_dir: Path):
    """1-to-1 uniqueness rule: a Rule-2/3 candidate is kept only if both its
    source and target are unique in their canonical-name-match relationships.
    Multi-candidate cases are 1-to-N splits or N-to-1 merges - demoted.

    Rule 1 (SAME_AS IoU>=0.95) keeps unconditionally."""
    descendants = defaultdict(set)
    ancestors = defaultdict(set)

    for y1, y2 in YEAR_PAIRS:
        for fname in (f"cd_links_{y1}_{y2}.csv", f"cd_ambiguous_{y1}_{y2}.csv"):
            fpath = links_dir / fname
            if not fpath.exists():
                continue
            with open(fpath) as f:
                for r in csv.DictReader(f):
                    rel = r["relationship"]
                    if rel not in ("WITHIN", "CONTAINS", "OVERLAPS"):
                        continue
                    cd_from = r["cd_from"].strip()
                    cd_to = r["cd_to"].strip()
                    _, name1 = parse_cd_id(cd_from)
                    _, name2 = parse_cd_id(cd_to)
                    canon1 = canonical_cd_name(name1)
                    canon2 = canonical_cd_name(name2)
                    n1 = normalize_for_match(canon1)
                    n2 = normalize_for_match(canon2)
                    if not n1 or n1 != n2:
                        continue
                    descendants[(cd_from, y1)].add((cd_to, y2))
                    ancestors[(cd_to, y2)].add((cd_from, y1))

    multi_desc = {k for k, vs in descendants.items() if len(vs) > 1}
    multi_anc = {k for k, vs in ancestors.items() if len(vs) > 1}

    kept = []
    demoted = []
    for link in accepted_links:
        if link["accept_rule"] == 1:
            kept.append(link)
            continue
        a = (link["uid_from"], link["year_from"])
        b = (link["uid_to"], link["year_to"])
        if a in multi_desc or b in multi_anc:
            demoted.append(link)
        else:
            kept.append(link)

    print(f"  Split/merge detection: {len(multi_desc)} multi-descendant sources, "
          f"{len(multi_anc)} multi-ancestor targets", file=sys.stderr)
    print(f"  Demoted {len(demoted)} Rule-2/3 links to lineage", file=sys.stderr)
    return kept, demoted


def build_chains(accepted_links, node_meta):
    """Run Union-Find on accepted links to produce preliminary chains.
    Returns (registry, member_to_chain) where registry has one row per
    chain and member_to_chain maps (cd_id, year) -> chain place_id."""
    uf = UnionFind()
    for node in node_meta:
        uf.make_set(node)
    for link in accepted_links:
        a = (link["uid_from"], link["year_from"])
        b = (link["uid_to"], link["year_to"])
        uf.make_set(a)
        uf.make_set(b)
        uf.union(a, b)

    components = uf.components()
    print(f"  Built {len(components)} preliminary chains via Union-Find",
          file=sys.stderr)

    used_chain_ids = set()
    registry = []
    member_to_chain = {}

    for root, nodes in components.items():
        nodes_sorted = sorted(nodes, key=lambda x: x[1])
        years_present = sorted(set(n[1] for n in nodes_sorted))

        # Province: should be unique within a chain. Take first (sorted).
        provs = sorted({node_meta[n].get("province") for n in nodes_sorted
                        if node_meta[n].get("province")})
        province = provs[0] if provs else ""

        # Canonical name: most frequent canonical_name in chain;
        # latest year breaks ties.
        canon_counter = Counter()
        canon_latest_year = {}
        for cd_id, yr in nodes_sorted:
            cn = node_meta[(cd_id, yr)].get("canonical_name", "")
            if cn:
                canon_counter[cn] += 1
                if cn not in canon_latest_year or yr > canon_latest_year[cn]:
                    canon_latest_year[cn] = yr
        if canon_counter:
            max_count = max(canon_counter.values())
            top = [n for n, c in canon_counter.items() if c == max_count]
            canonical_name = max(top, key=lambda n: canon_latest_year.get(n, 0))
        else:
            canonical_name = ""

        # Anchor = latest-year member.
        anchor_cd_id, anchor_year = nodes_sorted[-1]

        # Mint chain id with collision-safe disambiguator.
        chain_id = chain_id_for(province, canonical_name)
        if chain_id in used_chain_ids:
            chain_id = f"{chain_id}_{years_present[0]}"
            while chain_id in used_chain_ids:
                chain_id = f"{chain_id}_{years_present[-1]}"
        used_chain_ids.add(chain_id)

        registry.append({
            "place_id": chain_id,
            "canonical_name": canonical_name,
            "province": province,
            "anchor_cd_id": anchor_cd_id,
            "anchor_year": anchor_year,
            "years_active": ";".join(str(y) for y in years_present),
            "num_years": len(years_present),
        })
        for cd_id, yr in nodes_sorted:
            member_to_chain[(cd_id, yr)] = chain_id

    return registry, member_to_chain


def build_lineage(lineage_links, member_to_chain):
    """Convert demoted CONTAINS/WITHIN links into SPLIT_FROM / MERGED_INTO
    edges between chain place_ids. CONTAINS = parent split into child →
    SPLIT_FROM (parent → child). WITHIN = source merged into target →
    MERGED_INTO (source → target)."""
    seen = set()
    edges = []

    for link in lineage_links:
        chain_from = member_to_chain.get((link["uid_from"], link["year_from"]))
        chain_to = member_to_chain.get((link["uid_to"], link["year_to"]))
        if not chain_from or not chain_to or chain_from == chain_to:
            continue
        rel = link["relationship"]
        if rel == "CONTAINS":
            ltype = "SPLIT_FROM"
        elif rel == "WITHIN":
            ltype = "MERGED_INTO"
        else:
            continue
        change_year = link["year_to"]
        key = (ltype, chain_from, chain_to, change_year)
        if key in seen:
            continue
        seen.add(key)
        edges.append({
            "lineage_type": ltype,
            ":START_ID": chain_from,
            ":END_ID": chain_to,
            "change_year:int": change_year,
            ":TYPE": ltype,
        })
    print(f"  Built {len(edges)} lineage edges", file=sys.stderr)
    return edges


def apply_rule4_gap_bridge(registry, lineage_edges, member_to_chain):
    """Rule 4: gap-spanning lineage bridge.

    Two preliminary chains A and A' fuse iff:
      (a) A has SPLIT_FROM edges to a non-empty set S of children
      (b) every chain in S has MERGED_INTO edges back to A'
      (c) canonical_name(A) == canonical_name(A') AND same province
      (d) A's last_year < A'.first_year (no temporal overlap)
      (e) no chain in S persists past A'.first_year

    Mutates registry + member_to_chain. Returns audit list of fusions."""
    by_chain = {r["place_id"]: r for r in registry}

    # Build SPLIT_FROM and MERGED_INTO indexes once.
    splits_out = defaultdict(set)
    merges_out = defaultdict(set)
    for e in lineage_edges:
        if e["lineage_type"] == "SPLIT_FROM":
            splits_out[e[":START_ID"]].add(e[":END_ID"])
        elif e["lineage_type"] == "MERGED_INTO":
            merges_out[e[":START_ID"]].add(e[":END_ID"])

    # Collect all candidate (A, A') fusions.
    candidate_fusions = []
    for a_id, a_row in by_chain.items():
        all_children = splits_out.get(a_id, set())
        if not all_children:
            continue
        # Restrict children to those whose canonical_name starts with A's
        # canonical_name (e.g., for parent "Renfrew", consider children
        # "Renfrew North" / "Renfrew South" but NOT "Renfew" sliver). This
        # excludes spurious lineage neighbours (OCR slivers, name-coincidence
        # CDs) that would otherwise break the merge-target intersection.
        a_canon = a_row.get("canonical_name", "")
        a_norm = normalize_for_match(a_canon)
        children = set()
        for c in all_children:
            c_row = by_chain.get(c)
            if not c_row:
                continue
            c_canon = c_row.get("canonical_name", "")
            c_norm = normalize_for_match(c_canon)
            if not a_norm or not c_norm:
                continue
            if c_norm == a_norm or c_norm.startswith(a_norm + " "):
                children.add(c)
        if not children:
            continue
        # Each child's set of merge-into targets.
        child_targets_list = []
        for c in children:
            tgts = merges_out.get(c, set())
            if not tgts:
                child_targets_list = []
                break
            child_targets_list.append(tgts)
        if not child_targets_list:
            continue
        intersection = set.intersection(*child_targets_list)
        intersection.discard(a_id)
        for ap_id in intersection:
            ap_row = by_chain.get(ap_id)
            if not ap_row:
                continue
            if (normalize_for_match(a_row["canonical_name"])
                    != normalize_for_match(ap_row["canonical_name"])
                    or a_row["province"] != ap_row["province"]):
                continue
            a_years = [int(y) for y in a_row["years_active"].split(";") if y]
            ap_years = [int(y) for y in ap_row["years_active"].split(";") if y]
            if not a_years or not ap_years:
                continue
            if max(a_years) >= min(ap_years):
                continue
            ap_first = min(ap_years)
            child_overshoots = False
            for c in children:
                c_row = by_chain.get(c)
                if not c_row:
                    continue
                c_years = [int(y) for y in c_row["years_active"].split(";") if y]
                if c_years and max(c_years) > ap_first:
                    child_overshoots = True
                    break
            if child_overshoots:
                continue
            candidate_fusions.append((a_id, ap_id))

    if not candidate_fusions:
        print(f"  Rule 4: 0 gap-bridge fusions", file=sys.stderr)
        return []

    # Apply fusions in order. Skip ones whose endpoints have been re-mapped
    # by an earlier fusion in the same batch.
    redirect = {}  # chain_id -> current alias chain_id

    def resolve(cid):
        seen = set()
        while cid in redirect and cid not in seen:
            seen.add(cid)
            cid = redirect[cid]
        return cid

    fused_audit = []
    for a_id, ap_id in candidate_fusions:
        a_resolved = resolve(a_id)
        ap_resolved = resolve(ap_id)
        if a_resolved == ap_resolved:
            continue
        a_row = by_chain.get(a_resolved)
        ap_row = by_chain.get(ap_resolved)
        if not a_row or not ap_row:
            continue
        # Merge A' into A; A is older (keep its anchor).
        a_years = sorted(
            set(int(y) for y in a_row["years_active"].split(";") if y)
            | set(int(y) for y in ap_row["years_active"].split(";") if y)
        )
        a_row["years_active"] = ";".join(str(y) for y in a_years)
        a_row["num_years"] = len(a_years)
        for k, v in list(member_to_chain.items()):
            if v == ap_resolved:
                member_to_chain[k] = a_resolved
        del by_chain[ap_resolved]
        redirect[ap_resolved] = a_resolved
        for e in lineage_edges:
            if e[":START_ID"] == ap_resolved:
                e[":START_ID"] = a_resolved
            if e[":END_ID"] == ap_resolved:
                e[":END_ID"] = a_resolved
        fused_audit.append({
            "fused_into": a_resolved, "removed_chain": ap_resolved,
            "canonical_name": a_row["canonical_name"],
            "province": a_row["province"],
            "years_active": a_row["years_active"],
        })

    # Rebuild registry list from by_chain dict (preserve sort by chain id).
    registry.clear()
    registry.extend(sorted(by_chain.values(), key=lambda r: r["place_id"]))

    # Drop self-loop / dup edges that may have arisen from the rewriting.
    seen_keys = set()
    deduped = []
    for e in lineage_edges:
        if e[":START_ID"] == e[":END_ID"]:
            continue
        key = (e["lineage_type"], e[":START_ID"], e[":END_ID"], e["change_year:int"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(e)
    lineage_edges[:] = deduped

    print(f"  Rule 4: {len(fused_audit)} gap-bridge fusions applied", file=sys.stderr)
    return fused_audit


def main():
    parser = argparse.ArgumentParser(
        description="Build persistent CD registry from cd_links spatial overlap"
    )
    parser.add_argument("--links-dir", default="cd_links_output")
    parser.add_argument("--cidoc-dir", default="neo4j_cidoc_crm_v2",
                        help="Source for e53_place_cd.csv + e93_presence_cd_*.csv "
                             "to find singleton CDs not covered by cd_links pairs")
    parser.add_argument("--out", default="persistent_cds_output")
    parser.add_argument("--audit", action="store_true",
                        help="Emit chain_audit.csv with every accepted link + rule")
    args = parser.parse_args()

    links_dir = Path(args.links_dir)
    cidoc_dir = Path(args.cidoc_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Building Persistent CD Registry (multi-signal)", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    print(f"\nLoading and classifying cd_links...", file=sys.stderr)
    accepted_links, lineage_links, node_meta = load_all_cd_links(links_dir)

    print(f"\nAugmenting with CDs not in cd_links (singletons)...", file=sys.stderr)
    augment_node_meta_from_e53(node_meta, cidoc_dir)

    print(f"\nApplying name-only rescue (adjacent-year canonical-unique)...",
          file=sys.stderr)
    rescue_links = find_name_only_rescue_links(node_meta, accepted_links)
    accepted_links.extend(rescue_links)

    print(f"\nDetecting splits/merges (1-to-1 uniqueness rule)...", file=sys.stderr)
    accepted_links, demoted_links = detect_splits_and_demote(accepted_links, links_dir)
    for d in demoted_links:
        rel = d["rel"]
        if rel == "OVERLAPS":
            rel = "CONTAINS" if d["frac_to"] >= d["frac_from"] else "WITHIN"
        lineage_links.append({
            "uid_from": d["uid_from"], "year_from": d["year_from"],
            "uid_to": d["uid_to"], "year_to": d["year_to"],
            "relationship": rel, "iou": d["iou"],
        })

    print(f"\nBuilding preliminary chains (Union-Find)...", file=sys.stderr)
    registry, member_to_chain = build_chains(accepted_links, node_meta)

    print(f"\nBuilding lineage edges...", file=sys.stderr)
    lineage_edges = build_lineage(lineage_links, member_to_chain)

    print(f"\nApplying Rule 4 (gap-spanning lineage bridge)...", file=sys.stderr)
    rule4_audit = apply_rule4_gap_bridge(registry, lineage_edges, member_to_chain)

    print(f"\nWriting outputs to {out_dir}/...", file=sys.stderr)

    registry_df = pd.DataFrame(registry)
    registry_df.to_csv(out_dir / "persistent_cd_registry.csv", index=False)
    print(f"  persistent_cd_registry.csv: {len(registry_df)} chains",
          file=sys.stderr)

    mapping_rows = [
        {"raw_cd_id": cd_id, "year": yr, "chain_place_id": chain_id}
        for (cd_id, yr), chain_id in sorted(member_to_chain.items())
    ]
    pd.DataFrame(mapping_rows).to_csv(
        out_dir / "cd_id_year_to_chain.csv", index=False
    )
    print(f"  cd_id_year_to_chain.csv: {len(mapping_rows)} mappings",
          file=sys.stderr)

    pd.DataFrame(lineage_edges, columns=[
        "lineage_type", ":START_ID", ":END_ID", "change_year:int", ":TYPE",
    ]).to_csv(out_dir / "cd_lineage.csv", index=False)
    print(f"  cd_lineage.csv: {len(lineage_edges)} lineage edges",
          file=sys.stderr)

    if rule4_audit:
        pd.DataFrame(rule4_audit).to_csv(
            out_dir / "rule4_fusions.csv", index=False
        )
        print(f"  rule4_fusions.csv: {len(rule4_audit)} gap-bridge fusions",
              file=sys.stderr)

    if args.audit:
        for link in accepted_links:
            chain_id = (member_to_chain.get((link["uid_from"], link["year_from"]))
                        or member_to_chain.get((link["uid_to"], link["year_to"])))
            link["chain_place_id"] = chain_id or ""
        pd.DataFrame(accepted_links, columns=[
            "uid_from", "year_from", "name_from", "canon_from",
            "uid_to", "year_to", "name_to", "canon_to",
            "rel", "iou", "frac_from", "frac_to",
            "source", "accept_rule", "chain_place_id",
        ]).to_csv(out_dir / "chain_audit.csv", index=False)
        print(f"  chain_audit.csv: {len(accepted_links)} accepted links",
              file=sys.stderr)

    print(f"\n{'='*60}\nSUMMARY\n{'='*60}", file=sys.stderr)
    year_dist = Counter(r["num_years"] for r in registry)
    multi = sum(1 for r in registry if r["num_years"] > 1)
    single = sum(1 for r in registry if r["num_years"] == 1)
    print(f"Persistent CD chains: {len(registry)}", file=sys.stderr)
    print(f"  Multi-year chains:  {multi}", file=sys.stderr)
    print(f"  Single-year:        {single}", file=sys.stderr)
    print(f"\nYear-span distribution:", file=sys.stderr)
    for span in sorted(year_dist):
        print(f"  {span} years: {year_dist[span]}", file=sys.stderr)
    print(f"\nLineage edges: {len(lineage_edges)}", file=sys.stderr)
    print(f"\nOutput: {out_dir}/", file=sys.stderr)


if __name__ == "__main__":
    main()
