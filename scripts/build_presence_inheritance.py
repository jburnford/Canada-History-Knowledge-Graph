"""Phase A of per-presence Wikidata grounding: pure-Python inheritance pass.

For every chain that's currently ungrounded (uri_source=minted_hgis AND
grounding_status=ungrounded in e53_place_uri.csv), try to inherit a Wikidata
QID OR a deliberate mint_uri decision from an already-resolved chain via four
signals (strongest first):

  S1 STRICT_YEAR_LINK   year_links_*.csv SAME_AS partner whose chain is resolved
  S2 STRICT_MULTIHOP    multi-hop SAME_AS chain through year_links_*.csv only
  S3 AMBIGUOUS_NAMED    ambiguous_*.csv SAME_AS partner with tier_root+province
                        agreement (the Saskatoon "Saskatoon c" / "Saskatoon, C"
                        case where the spatial link was demoted to ambiguous)
  S4 TIER_ROOT_PROVINCE tier_root+province match to a uniquely-grounded chain
                        (the Brantford City vs Township disambiguation)

Per-chain consolidation: collect candidates across all the chain's presences.
If they unanimously point to one QID (or one mint_uri decision) the chain
inherits. Disagreements go to a review CSV and are NOT auto-applied —
mint_uri decisions in particular are curated and never get silently overridden
by a per-presence MCP candidate.

Outputs (in wikidata_grounding/):
  presence_inheritance_matches.jsonl  — proposed new chain groundings
  presence_inheritance_audit.csv      — per-chain decision + evidence
  presence_inheritance_review.csv     — conflicting candidates needing humans
  presence_inheritance_unresolved.csv — no signal; input for Phase C MCP queue

The matches file mirrors csd_verified_matches.jsonl's schema so downstream
scripts can consume both. status is "matched" (with QID) or "mint_uri".
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _normalize import tier_root  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
URI_SIDECAR = REPO / "neo4j_cidoc_crm_v2" / "e53_place_uri.csv"
CSD_NODES = REPO / "neo4j_cidoc_crm_v2" / "e53_place_csd.csv"
TCPUID_MAP = REPO / "persistent_places_output" / "tcpuid_year_to_place.csv"
VERIFIED_1921 = REPO / "wikidata_grounding" / "csd_verified_matches.jsonl"
YEAR_LINKS_DIR = REPO / "year_links_output"

OUT_DIR = REPO / "wikidata_grounding"
OUT_MATCHES = OUT_DIR / "presence_inheritance_matches.jsonl"
OUT_AUDIT = OUT_DIR / "presence_inheritance_audit.csv"
OUT_REVIEW = OUT_DIR / "presence_inheritance_review.csv"
OUT_UNRESOLVED = OUT_DIR / "presence_inheritance_unresolved.csv"

YEARS = (1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921)
YEAR_PAIRS = list(zip(YEARS[:-1], YEARS[1:]))


def load_chain_resolutions() -> dict[str, dict]:
    """chain_id -> {state, qid, label, mint_reason, uri}.

    state ∈ {GROUNDED, DELIBERATE_MINT, UNGROUNDED, SKIP}.
    """
    resolutions: dict[str, dict] = {}
    with URI_SIDECAR.open() as f:
        for row in csv.DictReader(f):
            chain = row["place_id:ID"]
            src = row["uri_source"]
            status = row["grounding_status"]
            qid = row["wikidata_qid"]
            label = row["wikidata_label"]
            uri = row["uri"]
            mint_reason = row["mint_reason"]
            if src in ("wikidata", "wikidata_via_sibling", "wikidata_via_override"):
                state = "GROUNDED"
            elif status == "mint_uri":
                state = "DELIBERATE_MINT"
            elif status == "skip":
                state = "SKIP"
            else:
                state = "UNGROUNDED"
            resolutions[chain] = {
                "state": state,
                "qid": qid,
                "label": label,
                "uri": uri,
                "mint_reason": mint_reason,
            }
    return resolutions


def load_chain_metadata() -> dict[str, dict]:
    """chain_id -> {name, province, place_type, years_active}."""
    meta: dict[str, dict] = {}
    with CSD_NODES.open() as f:
        for row in csv.DictReader(f):
            meta[row["place_id:ID"]] = {
                "name": row["name"],
                "province": row["province"],
                "place_type": row["place_type"],
                "years_active": row["years_active"],
            }
    return meta


def load_presence_to_chain() -> tuple[dict[tuple[str, int], str], dict[str, list[tuple[str, int]]]]:
    """Return ((tcpuid, year) -> chain, chain -> [(tcpuid, year), ...])."""
    p2c: dict[tuple[str, int], str] = {}
    c2p: dict[str, list[tuple[str, int]]] = defaultdict(list)
    with TCPUID_MAP.open() as f:
        for row in csv.DictReader(f):
            key = (row["tcpuid"], int(row["year"]))
            chain = row["persistent_place_id"]
            p2c[key] = chain
            c2p[chain].append(key)
    return p2c, c2p


def load_year_link_graph() -> tuple[dict, dict]:
    """Return (strict_links, ambiguous_links) where each maps
    (tcpuid, year) -> list of (other_tcpuid, other_year, relationship, name_sim).

    Edges are bidirectional. Only SAME_AS / WITHIN / CONTAINS / OVERLAPS rows
    in the from-year/to-year file format are kept.
    """
    def _load(path: Path, store: dict) -> int:
        if not path.exists():
            return 0
        n = 0
        with path.open() as f:
            for row in csv.DictReader(f):
                # Identify the two year columns from header keys
                keys = list(row.keys())
                tcp_a_key = next(k for k in keys if k.startswith("tcpuid_"))
                tcp_b_key = [k for k in keys if k.startswith("tcpuid_")][1]
                year_a = int(tcp_a_key.split("_")[1])
                year_b = int(tcp_b_key.split("_")[1])
                tcp_a = row[tcp_a_key]
                tcp_b = row[tcp_b_key]
                rel = row.get("relationship", "")
                ns = row.get("name_similarity", "") or ""
                if not tcp_a or not tcp_b or not rel:
                    continue
                key_a = (tcp_a, year_a)
                key_b = (tcp_b, year_b)
                store[key_a].append((tcp_b, year_b, rel, ns))
                store[key_b].append((tcp_a, year_a, rel, ns))
                n += 1
        return n

    strict: dict = defaultdict(list)
    ambig: dict = defaultdict(list)
    s_total = 0
    a_total = 0
    for ya, yb in YEAR_PAIRS:
        s_total += _load(YEAR_LINKS_DIR / f"year_links_{ya}_{yb}.csv", strict)
        a_total += _load(YEAR_LINKS_DIR / f"ambiguous_{ya}_{yb}.csv", ambig)
    print(f"Loaded {s_total:,} strict year-links, {a_total:,} ambiguous", file=sys.stderr)
    return strict, ambig


def load_1921_mint_reasons() -> dict[str, str]:
    """tcpuid -> mint_reason for 1921 csd_verified_matches.jsonl rows where
    status=mint_uri. Used to seed mint_reason on inherited mint_uri chains."""
    out: dict[str, str] = {}
    with VERIFIED_1921.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("status") == "mint_uri" and d.get("mint_reason"):
                out[d["csd_id"]] = d["mint_reason"]
    return out


def find_inheritance_candidates(
    chain_id: str,
    presences: list[tuple[str, int]],
    p2c: dict,
    resolutions: dict,
    metadata: dict,
    strict_links: dict,
    ambig_links: dict,
) -> list[dict]:
    """For one ungrounded chain, walk its presences through year-links and
    collect every candidate target chain (resolved chain reachable via spatial
    evidence). Returns list of dicts with keys: target_chain, signal,
    presence_path, partner_name_similarity.
    """
    candidates: list[dict] = []
    seen_targets: set[tuple[str, str]] = set()  # (target_chain, signal)
    src_meta = metadata.get(chain_id, {})
    src_root, src_tier = tier_root(src_meta.get("name", ""))
    src_prov = src_meta.get("province", "")

    # S1 + S2: BFS through STRICT SAME_AS only
    strict_visited: set[tuple[str, int]] = set(presences)
    queue: deque = deque((p, p, 0) for p in presences)  # (current, origin_presence, hops)
    while queue:
        cur, origin, hops = queue.popleft()
        for tcp_b, year_b, rel, ns in strict_links.get(cur, []):
            if rel != "SAME_AS":
                continue
            partner = (tcp_b, year_b)
            if partner in strict_visited:
                continue
            strict_visited.add(partner)
            target = p2c.get(partner)
            if not target:
                continue
            if target == chain_id:
                queue.append((partner, origin, hops + 1))
                continue
            tres = resolutions.get(target, {})
            if tres.get("state") in ("GROUNDED", "DELIBERATE_MINT"):
                signal = "S1_STRICT_YEAR_LINK" if hops == 0 else "S2_STRICT_MULTIHOP"
                key = (target, signal)
                if key not in seen_targets:
                    seen_targets.add(key)
                    candidates.append({
                        "target_chain": target,
                        "signal": signal,
                        "presence_path": f"{origin[0]}_{origin[1]} -> {tcp_b}_{year_b}",
                        "name_similarity": ns,
                        "hops": hops + 1,
                    })
            # Continue BFS regardless — multi-hop might reach a deeper grounded chain
            queue.append((partner, origin, hops + 1))

    # S3: AMBIGUOUS SAME_AS partners restricted to tier_root+province agreement
    for p in presences:
        for tcp_b, year_b, rel, ns in ambig_links.get(p, []):
            if rel != "SAME_AS":
                continue
            partner = (tcp_b, year_b)
            target = p2c.get(partner)
            if not target or target == chain_id:
                continue
            tres = resolutions.get(target, {})
            if tres.get("state") not in ("GROUNDED", "DELIBERATE_MINT"):
                continue
            tgt_meta = metadata.get(target, {})
            tgt_root, tgt_tier = tier_root(tgt_meta.get("name", ""))
            tgt_prov = tgt_meta.get("province", "")
            # Allow cross-province match (NT 1901 -> SK 1921 case) as long as
            # tier_root agrees; province difference recorded in evidence.
            if not src_root or not tgt_root or src_root != tgt_root:
                continue
            if src_tier != tgt_tier and "BARE" not in (src_tier, tgt_tier):
                # tiers must agree OR one of them is BARE (e.g., the 1901
                # presence has no admin tier in its name yet)
                continue
            key = (target, "S3_AMBIGUOUS_NAMED")
            if key not in seen_targets:
                seen_targets.add(key)
                cross_prov = "" if src_prov == tgt_prov else f" cross-province {src_prov}->{tgt_prov}"
                candidates.append({
                    "target_chain": target,
                    "signal": "S3_AMBIGUOUS_NAMED",
                    "presence_path": f"{p[0]}_{p[1]} -> {tcp_b}_{year_b}{cross_prov}",
                    "name_similarity": ns,
                    "hops": 1,
                })

    return candidates


def find_tier_root_candidates(
    chain_id: str,
    metadata: dict,
    resolutions: dict,
    grounded_by_tier: dict,
) -> list[dict]:
    """S4: tier_root+province match to a uniquely-grounded chain."""
    src_meta = metadata.get(chain_id, {})
    src_root, src_tier = tier_root(src_meta.get("name", ""))
    src_prov = src_meta.get("province", "")
    if not src_root or not src_prov:
        return []
    bucket = grounded_by_tier.get((src_root, src_tier, src_prov), [])
    if len(bucket) != 1:
        return []
    target = bucket[0]
    if target == chain_id:
        return []
    return [{
        "target_chain": target,
        "signal": "S4_TIER_ROOT_PROVINCE",
        "presence_path": f"({src_root}, {src_tier}, {src_prov}) bucket",
        "name_similarity": "",
        "hops": 0,
    }]


def consolidate_candidates(candidates: list[dict], resolutions: dict) -> dict:
    """Decide chain-level inheritance from per-presence candidates.

    Returns {decision, qid, label, mint_reason, target_chains, signals,
    confidence, evidence}.

    decision ∈ {INHERIT_QID, INHERIT_MINT, REVIEW_CONFLICT, NO_EVIDENCE}.
    """
    if not candidates:
        return {"decision": "NO_EVIDENCE"}

    # Group by inherited resolution (qid OR "MINT:<reason-hash>")
    qids: Counter = Counter()
    mints: Counter = Counter()
    qid_label: dict[str, str] = {}
    qid_targets: dict[str, list[str]] = defaultdict(list)
    mint_reasons: dict[str, str] = {}
    mint_targets: dict[str, list[str]] = defaultdict(list)
    qid_signals: dict[str, set] = defaultdict(set)
    mint_signals: dict[str, set] = defaultdict(set)

    for c in candidates:
        tres = resolutions.get(c["target_chain"], {})
        if tres.get("state") == "GROUNDED" and tres.get("qid"):
            q = tres["qid"]
            qids[q] += 1
            qid_label[q] = tres.get("label", "")
            qid_targets[q].append(c["target_chain"])
            qid_signals[q].add(c["signal"])
        elif tres.get("state") == "DELIBERATE_MINT":
            mr = tres.get("mint_reason", "") or "no-reason"
            mints[mr] += 1
            mint_reasons[mr] = mr
            mint_targets[mr].append(c["target_chain"])
            mint_signals[mr].add(c["signal"])

    distinct_qids = list(qids.keys())
    distinct_mints = list(mints.keys())

    # Conflict if both QID and mint candidates, OR multiple distinct QIDs,
    # OR multiple distinct mint_reasons. Multiple chains with the same QID
    # is fine (they're already-grounded siblings of the same QID).
    if distinct_qids and distinct_mints:
        return _conflict(qids, mints, qid_targets, mint_targets, qid_signals, mint_signals)
    if len(distinct_qids) > 1:
        return _conflict(qids, mints, qid_targets, mint_targets, qid_signals, mint_signals)
    if len(distinct_mints) > 1:
        return _conflict(qids, mints, qid_targets, mint_targets, qid_signals, mint_signals)

    if distinct_qids:
        q = distinct_qids[0]
        targets = sorted(set(qid_targets[q]))
        signals = sorted(qid_signals[q])
        confidence = _confidence_from_signals(signals)
        return {
            "decision": "INHERIT_QID",
            "qid": q,
            "label": qid_label[q],
            "mint_reason": "",
            "target_chains": targets,
            "signals": signals,
            "confidence": confidence,
            "evidence": _evidence_summary(candidates, q, target_filter=set(targets)),
        }
    if distinct_mints:
        mr = distinct_mints[0]
        targets = sorted(set(mint_targets[mr]))
        signals = sorted(mint_signals[mr])
        confidence = _confidence_from_signals(signals)
        return {
            "decision": "INHERIT_MINT",
            "qid": "",
            "label": "",
            "mint_reason": mr,
            "target_chains": targets,
            "signals": signals,
            "confidence": confidence,
            "evidence": _evidence_summary(candidates, mr, target_filter=set(targets)),
        }
    return {"decision": "NO_EVIDENCE"}


def _confidence_from_signals(signals: list[str]) -> str:
    if any(s in ("S1_STRICT_YEAR_LINK", "S2_STRICT_MULTIHOP") for s in signals):
        return "high"
    if "S3_AMBIGUOUS_NAMED" in signals:
        return "medium"
    return "low"


def _evidence_summary(candidates: list[dict], key, target_filter: set) -> str:
    """One-line summary of evidence supporting the chosen decision."""
    parts = []
    for c in candidates:
        if c["target_chain"] not in target_filter:
            continue
        parts.append(f"{c['signal']} via {c['presence_path']} -> {c['target_chain']}")
        if len(parts) >= 3:
            break
    return " | ".join(parts)


def _conflict(qids, mints, qid_targets, mint_targets, qid_signals, mint_signals) -> dict:
    return {
        "decision": "REVIEW_CONFLICT",
        "qid": "",
        "label": "",
        "mint_reason": "",
        "target_chains": [],
        "signals": [],
        "confidence": "",
        "evidence": (
            f"qids={dict(qids)} | "
            f"mints={ {k: v for k, v in mints.items()} } | "
            f"qid_targets={dict(qid_targets)} | "
            f"mint_targets={dict(mint_targets)}"
        ),
    }


def main() -> None:
    print("Loading inputs...", file=sys.stderr)
    resolutions = load_chain_resolutions()
    metadata = load_chain_metadata()
    p2c, c2p = load_presence_to_chain()
    strict_links, ambig_links = load_year_link_graph()
    mint_reasons_1921 = load_1921_mint_reasons()
    print(f"  Chains: {len(resolutions):,} resolved + metadata; {len(c2p):,} with presences",
          file=sys.stderr)

    # Build (tier_root, tier, province) → list of grounded chains for S4
    grounded_by_tier: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    deliberate_mint_by_tier: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for chain, res in resolutions.items():
        if res["state"] not in ("GROUNDED", "DELIBERATE_MINT"):
            continue
        meta = metadata.get(chain, {})
        root, tier = tier_root(meta.get("name", ""))
        prov = meta.get("province", "")
        if not root or not prov:
            continue
        if res["state"] == "GROUNDED":
            grounded_by_tier[(root, tier, prov)].append(chain)
        else:
            deliberate_mint_by_tier[(root, tier, prov)].append(chain)
    # For S4, ONLY use tier-buckets that resolve unambiguously (one entry).
    # Multi-entry buckets across QIDs/mints are ambiguous by definition.

    # Restrict to CSD chains; CD_* chains belong to a separate inheritance track.
    ungrounded_chains = [
        c for c, r in resolutions.items()
        if r["state"] == "UNGROUNDED" and c.startswith("PLACE_")
    ]
    print(f"  Ungrounded CSD chains to process: {len(ungrounded_chains):,}", file=sys.stderr)

    # 649 chains exist in CIDOC export but aren't in tcpuid_year_to_place.csv
    # (e.g., PLACE_SK216003_1911 — a v10.4 ward-level CSD the registry build
    # missed). Synthesize a single presence from the chain ID's _YEAR suffix
    # so they're still inheritance candidates. The data inconsistency is a
    # separate upstream bug worth tracking.
    import re as _re
    chain_year_re = _re.compile(r"^PLACE_([A-Z]{2}\d+)(?:_(\d{4}))?$")
    synthesized = 0
    for chain in ungrounded_chains:
        if c2p.get(chain):
            continue
        m = chain_year_re.match(chain)
        if not m:
            continue
        tcpuid, year_str = m.group(1), m.group(2)
        meta = metadata.get(chain, {})
        years_active = meta.get("years_active", "")
        # Prefer the chain id's year suffix; fall back to years_active first entry.
        years = []
        if year_str:
            years = [int(year_str)]
        elif years_active:
            years = [int(y) for y in years_active.split(";") if y.strip().isdigit()]
        for y in years:
            c2p[chain].append((tcpuid, y))
            p2c[(tcpuid, y)] = chain
        if years:
            synthesized += 1
    if synthesized:
        print(f"  Synthesized presences for {synthesized:,} chains missing from tcpuid map",
              file=sys.stderr)

    matches: list[dict] = []
    audit_rows: list[dict] = []
    review_rows: list[dict] = []
    unresolved_rows: list[dict] = []
    decision_counter: Counter = Counter()
    signal_counter: Counter = Counter()

    for chain in sorted(ungrounded_chains):
        presences = c2p.get(chain, [])
        meta = metadata.get(chain, {})
        if not presences:
            unresolved_rows.append({
                "chain_id": chain,
                "name": meta.get("name", ""),
                "province": meta.get("province", ""),
                "n_presences": 0,
                "reason": "no_presences_in_map",
            })
            continue

        candidates = find_inheritance_candidates(
            chain, presences, p2c, resolutions, metadata, strict_links, ambig_links,
        )
        if not candidates:
            # Try S4 as backup
            candidates = find_tier_root_candidates(
                chain, metadata, resolutions, grounded_by_tier,
            )
            # Also try mint_uri tier bucket
            if not candidates:
                src_root, src_tier = tier_root(meta.get("name", ""))
                src_prov = meta.get("province", "")
                bucket = deliberate_mint_by_tier.get((src_root, src_tier, src_prov), [])
                if len(bucket) == 1 and bucket[0] != chain:
                    candidates = [{
                        "target_chain": bucket[0],
                        "signal": "S4_TIER_ROOT_PROVINCE",
                        "presence_path": f"({src_root}, {src_tier}, {src_prov}) mint bucket",
                        "name_similarity": "",
                        "hops": 0,
                    }]

        decision = consolidate_candidates(candidates, resolutions)
        decision_counter[decision["decision"]] += 1
        for s in decision.get("signals", []):
            signal_counter[s] += 1

        audit_row = {
            "chain_id": chain,
            "name": meta.get("name", ""),
            "province": meta.get("province", ""),
            "n_presences": len(presences),
            "decision": decision["decision"],
            "inherited_qid": decision.get("qid", ""),
            "inherited_label": decision.get("label", ""),
            "inherited_mint_reason": decision.get("mint_reason", ""),
            "target_chains": ";".join(decision.get("target_chains", [])),
            "signals": ";".join(decision.get("signals", [])),
            "confidence": decision.get("confidence", ""),
            "evidence": decision.get("evidence", ""),
        }
        audit_rows.append(audit_row)

        if decision["decision"] == "INHERIT_QID":
            # Emit one match record per presence (mirrors csd_verified_matches.jsonl)
            for tcp, yr in presences:
                matches.append({
                    "presence_id": f"{tcp}_{yr}",
                    "tcpuid": tcp,
                    "year": yr,
                    "csd_name": meta.get("name", ""),
                    "province": meta.get("province", ""),
                    "current_chain": chain,
                    "wikidata_qid": decision["qid"],
                    "wikidata_label": decision["label"],
                    "status": "matched",
                    "match_type": f"inherit_{decision['confidence']}",
                    "inheritance_signals": ";".join(decision["signals"]),
                    "source_chains": ";".join(decision["target_chains"]),
                    "evidence": decision["evidence"],
                    "needs_verify": decision["confidence"] != "high",
                })
        elif decision["decision"] == "INHERIT_MINT":
            for tcp, yr in presences:
                matches.append({
                    "presence_id": f"{tcp}_{yr}",
                    "tcpuid": tcp,
                    "year": yr,
                    "csd_name": meta.get("name", ""),
                    "province": meta.get("province", ""),
                    "current_chain": chain,
                    "wikidata_qid": None,
                    "wikidata_label": None,
                    "status": "mint_uri",
                    "match_type": f"inherit_mint_{decision['confidence']}",
                    "inheritance_signals": ";".join(decision["signals"]),
                    "source_chains": ";".join(decision["target_chains"]),
                    "evidence": decision["evidence"],
                    "mint_reason": decision["mint_reason"],
                    "needs_verify": False,
                })
        elif decision["decision"] == "REVIEW_CONFLICT":
            review_rows.append(audit_row)
        else:  # NO_EVIDENCE
            unresolved_rows.append({
                "chain_id": chain,
                "name": meta.get("name", ""),
                "province": meta.get("province", ""),
                "n_presences": len(presences),
                "reason": "no_inheritance_signal",
            })

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with OUT_MATCHES.open("w") as f:
        for m in matches:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    audit_fields = [
        "chain_id", "name", "province", "n_presences",
        "decision", "inherited_qid", "inherited_label", "inherited_mint_reason",
        "target_chains", "signals", "confidence", "evidence",
    ]
    with OUT_AUDIT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=audit_fields)
        w.writeheader()
        w.writerows(audit_rows)

    with OUT_REVIEW.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=audit_fields)
        w.writeheader()
        w.writerows(review_rows)

    with OUT_UNRESOLVED.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["chain_id", "name", "province", "n_presences", "reason"])
        w.writeheader()
        w.writerows(unresolved_rows)

    print("\n=== Phase A inheritance summary ===", file=sys.stderr)
    print(f"Ungrounded chains processed: {len(ungrounded_chains):,}", file=sys.stderr)
    print(f"Decisions:", file=sys.stderr)
    for k, v in decision_counter.most_common():
        print(f"  {k:<22} {v:>6,}", file=sys.stderr)
    print(f"Signals used:", file=sys.stderr)
    for k, v in signal_counter.most_common():
        print(f"  {k:<22} {v:>6,}", file=sys.stderr)
    print(f"\nPresence-level matches written: {len(matches):,}", file=sys.stderr)
    print(f"  → {OUT_MATCHES.relative_to(REPO)}", file=sys.stderr)
    print(f"  → {OUT_AUDIT.relative_to(REPO)} ({len(audit_rows):,} rows)", file=sys.stderr)
    print(f"  → {OUT_REVIEW.relative_to(REPO)} ({len(review_rows):,} rows)", file=sys.stderr)
    print(f"  → {OUT_UNRESOLVED.relative_to(REPO)} ({len(unresolved_rows):,} rows)", file=sys.stderr)


if __name__ == "__main__":
    main()
