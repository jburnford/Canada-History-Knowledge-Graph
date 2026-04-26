#!/usr/bin/env python3
"""Join verified Wikidata matches onto E53_Place nodes as a URI sidecar.

Produces neo4j_cidoc_crm_v2/e53_place_uri.csv — one row per E53_Place with the
URI the RDF exporter should use as the subject.

URI assignment (post-v9.2):
  - status=matched  -> http://www.wikidata.org/entity/{QID}
  - status=mint_uri -> https://jimclifford.ca/hgiscanada/places/<prov>/<slug>-<id>/
  - status=skip     -> https://jimclifford.ca/hgiscanada/places/<prov>/<slug>-<id>/
  - ungrounded      -> https://jimclifford.ca/hgiscanada/places/<prov>/<slug>-<id>/

The minted URI is the actual GitHub Pages page URL. Pages dereference to a
CIDOC-CRM-rich HTML representation. Migration to w3id.org or LINCS later layers
on without invalidating the place_id portion (a redirect rule is enough).

The Neo4j :ID column stays as PLACE_{tcpuid}; this sidecar only supplies the
URI property so the RDF exporter can emit the right subject. No existing CSVs
are rewritten.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
JSONL = REPO / "wikidata_grounding" / "csd_verified_matches.jsonl"
CD_JSONL = REPO / "wikidata_grounding" / "cd_verified_matches.jsonl"
CD_CHAIN_MAP = REPO / "persistent_cds_output" / "cd_id_year_to_chain.csv"
CD_CHAIN_REGISTRY = REPO / "persistent_cds_output" / "persistent_cd_registry.csv"
E53_CSD = REPO / "neo4j_cidoc_crm_v2" / "e53_place_csd.csv"
E53_CD = REPO / "neo4j_cidoc_crm_v2" / "e53_place_cd.csv"
OUT = REPO / "neo4j_cidoc_crm_v2" / "e53_place_uri.csv"
UNPLACED = REPO / "neo4j_cidoc_crm_v2" / "e53_place_uri_unplaced.csv"
CD_CONFLICTS = REPO / "wikidata_grounding" / "cd_qid_conflicts.csv"

WIKIDATA_PREFIX = "http://www.wikidata.org/entity/"
HGIS_PAGE_BASE = "https://jimclifford.ca/hgiscanada/places"
HGIS_CD_BASE = "https://jimclifford.ca/hgiscanada/cds"
GROUNDING_YEAR = "1921"  # JSONL grounding was done against the 1921 CSD snapshot
SUFFIX_RE = re.compile(r"_(\d{4})$")
SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(s: str) -> str:
    """Match scripts/generate_rag_pages.py:slugify exactly so minted URIs
    align with the actual rendered page URLs."""
    return SLUG_RE.sub("-", s.lower()).strip("-")


def minted_page_url(name: str, place_id: str, province: str) -> str:
    """Construct the per-Place page URL the static site renders for this chain.
    Mirrors generate_rag_pages.url_for_place()."""
    stem = slugify(place_id.replace("PLACE_", ""))
    return f"{HGIS_PAGE_BASE}/{province.lower()}/{slugify(name)}-{stem}/"


def minted_cd_url(name: str, province: str, chain_place_id: str = "") -> str:
    """Construct the CD index page URL.

    Default uses just `name` + `province`. When `chain_place_id` carries a
    collision-disambiguator suffix (e.g., `CD_ON_York_1921` for the post-merge
    1921 York chain), append that year suffix to the URL slug so two chains
    sharing canonical_name+province get distinct URLs. Mirrors the chain-id
    pattern from build_persistent_cds.py:chain_id_for + collision suffix."""
    slug = slugify(name)
    if chain_place_id:
        # Detect suffix: chain_place_id is `CD_<prov>_<canonical>` optionally
        # followed by `_<year>` or `_<year_first>_<year_last>`. Anything beyond
        # the canonical-name portion is a collision disambiguator.
        expected_prefix = f"CD_{province}_{name.replace(' ', '_')}"
        if chain_place_id.startswith(expected_prefix + "_"):
            tail = chain_place_id[len(expected_prefix) + 1:]
            if tail:
                slug = f"{slug}-{slugify(tail)}"
    return f"{HGIS_CD_BASE}/{province.lower()}/{slug}/"


def load_grounding(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            out[r["csd_id"]] = r
    return out


def load_cd_grounding(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            out[r["cd_id"]] = r
    return out


def load_cd_chain_members(mapping_path: Path) -> dict[str, list[str]]:
    """Returns chain_place_id -> sorted list of distinct raw_cd_ids that
    map to that chain (across all years). Used to gather grounding records
    for a chain and resolve QID conflicts."""
    members: dict[str, set[str]] = {}
    if not mapping_path.exists():
        return {}
    with mapping_path.open() as f:
        for r in csv.DictReader(f):
            members.setdefault(r["chain_place_id"], set()).add(r["raw_cd_id"])
    return {k: sorted(v) for k, v in members.items()}


def load_cd_chain_canonical(registry_path: Path) -> dict[str, dict]:
    """Returns chain_place_id -> {canonical_name, num_years, anchor_year}."""
    out: dict[str, dict] = {}
    if not registry_path.exists():
        return out
    with registry_path.open() as f:
        for r in csv.DictReader(f):
            out[r["place_id"]] = {
                "canonical_name": r["canonical_name"],
                "num_years": int(r["num_years"]),
                "anchor_year": int(r["anchor_year"]),
            }
    return out


def resolve_chain_qid(member_records: list[dict], canonical_name: str
                       ) -> tuple[dict | None, list[dict]]:
    """Apply deterministic priority to pick a representative record for a
    chain when its members have mixed grounding records.

    Returns (chosen_record_or_None, conflict_audit_rows).

    Rule:
      1. Filter to status == 'matched' members.
      2. If 0 → return (None, []) (chain falls through to mint URI).
      3. If 1 → return that record.
      4. If multiple distinct QIDs → priority:
         (a) member whose 'csd_name' / 'cd_name' equals canonical_name exactly
         (b) lex order on cd_id (deterministic tie-break)
         Log all conflicting QIDs so user can review.
      5. If multiple records agree on same QID → pick first; no conflict.
    """
    matched = [r for r in member_records if r.get("status") == "matched"
               and r.get("wikidata_qid")]
    if not matched:
        return None, []
    distinct_qids = {r["wikidata_qid"] for r in matched}
    if len(distinct_qids) == 1:
        return matched[0], []
    # Conflict: prefer canonical-name match, then lex.
    def _name_match(rec: dict) -> bool:
        nm = rec.get("cd_name") or rec.get("csd_name") or ""
        return nm.strip().lower() == (canonical_name or "").strip().lower()
    canonical_picks = [r for r in matched if _name_match(r)]
    pool = canonical_picks if canonical_picks else matched
    chosen = sorted(pool, key=lambda r: r.get("cd_id", ""))[0]
    audit = [
        {"cd_id": r.get("cd_id", ""),
         "wikidata_qid": r.get("wikidata_qid", ""),
         "wikidata_label": r.get("wikidata_label", ""),
         "is_chosen": r is chosen}
        for r in matched
    ]
    return chosen, audit


def uri_for(tcpuid: str, record: dict | None,
            *, place_id: str, name: str, province: str) -> tuple[str, str, str]:
    """Return (uri, uri_source, wikidata_qid_or_empty).
    Wikidata when matched; minted GitHub Pages URL otherwise."""
    if record and record.get("status") == "matched":
        qid = record["wikidata_qid"]
        return f"{WIKIDATA_PREFIX}{qid}", "wikidata", qid
    return minted_page_url(name, place_id, province), "minted_hgis", ""


def base_tcpuid(tcpuid: str) -> str:
    """Strip a trailing _YYYY disambiguation suffix."""
    return SUFFIX_RE.sub("", tcpuid)


def main() -> None:
    grounding = load_grounding(JSONL)
    print(f"Loaded {len(grounding):,} verified records from {JSONL.name}")

    # Grounding keys refer to the 1921 snapshot. The CSV uses place_id
    # PLACE_{tcpuid} sometimes with a _YYYY disambiguation suffix. For each
    # grounding key, pick the CSV row whose base tcpuid matches AND whose
    # years_active includes 1921.
    status_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()
    province_source: dict[str, Counter[str]] = {}
    grounding_used: set[str] = set()

    rows_out = []
    with E53_CSD.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            place_id = row["place_id:ID"]
            assert place_id.startswith("PLACE_"), place_id
            tcpuid = place_id[len("PLACE_"):]
            base = base_tcpuid(tcpuid)
            province = row["province"]
            years = row["years_active"].split(";") if row["years_active"] else []

            # Only consume grounding when this CSV row is the 1921-active one.
            record = None
            if GROUNDING_YEAR in years and base in grounding:
                record = grounding[base]
                grounding_used.add(base)

            uri, source, qid = uri_for(
                base, record,
                place_id=place_id, name=row["name"], province=province,
            )
            status = record["status"] if record else "ungrounded"
            mint_reason = (record or {}).get("mint_reason", "") if record else ""
            wd_label = (record or {}).get("wikidata_label", "") if record else ""

            rows_out.append(
                {
                    "place_id:ID": place_id,
                    "uri": uri,
                    "uri_source": source,
                    "wikidata_qid": qid,
                    "wikidata_label": wd_label,
                    "grounding_status": status,
                    "mint_reason": mint_reason,
                }
            )
            status_counter[status] += 1
            source_counter[source] += 1
            province_source.setdefault(province, Counter())[source] += 1

    cd_grounding = load_cd_grounding(CD_JSONL)
    cd_chain_members = load_cd_chain_members(CD_CHAIN_MAP)
    cd_chain_canonical = load_cd_chain_canonical(CD_CHAIN_REGISTRY)
    print(f"Loaded {len(cd_grounding):,} verified records from {CD_JSONL.name}")
    print(f"Loaded {len(cd_chain_members):,} chain → members from {CD_CHAIN_MAP.name}")
    cd_status_counter: Counter[str] = Counter()
    cd_source_counter: Counter[str] = Counter()
    cd_province_source: dict[str, Counter[str]] = {}
    cd_grounding_used: set[str] = set()
    cd_conflict_rows = []

    with E53_CD.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            chain_id = row["place_id:ID"]
            assert chain_id.startswith("CD_"), chain_id
            province = row["province"]
            name = row["name"]

            # Gather grounding records for all raw cd_ids that map to this chain.
            # Fall back to the chain id itself if the chain registry isn't
            # available (singletons / pre-Phase-1 mode).
            raw_members = cd_chain_members.get(chain_id, [chain_id])
            member_records = []
            for rid in raw_members:
                rec = cd_grounding.get(rid)
                if rec:
                    member_records.append(rec)
                    cd_grounding_used.add(rid)

            canonical_name = (cd_chain_canonical.get(chain_id) or {}).get(
                "canonical_name", name
            )
            chosen, conflict_audit = resolve_chain_qid(member_records, canonical_name)

            if conflict_audit:
                for ar in conflict_audit:
                    cd_conflict_rows.append({
                        "chain_place_id": chain_id,
                        "canonical_name": canonical_name,
                        "province": province,
                        **ar,
                    })

            if chosen is not None:
                qid = chosen["wikidata_qid"]
                uri = f"{WIKIDATA_PREFIX}{qid}"
                source = "wikidata"
                status = "matched"
                wd_label = chosen.get("wikidata_label", "")
                mint_reason = ""
            else:
                # No matched member: pick a representative mint_reason if any
                # member said mint_uri; else status=ungrounded.
                mint_member = next(
                    (r for r in member_records if r.get("status") == "mint_uri"),
                    None,
                )
                uri = minted_cd_url(name, province, chain_id)
                source = "minted_hgis_cd"
                qid = ""
                status = "mint_uri" if mint_member else (
                    member_records[0].get("status") if member_records else "ungrounded"
                )
                mint_reason = (mint_member or {}).get("mint_reason", "") if mint_member else ""
                wd_label = ""

            rows_out.append(
                {
                    "place_id:ID": chain_id,
                    "uri": uri,
                    "uri_source": source,
                    "wikidata_qid": qid,
                    "wikidata_label": wd_label,
                    "grounding_status": status,
                    "mint_reason": mint_reason,
                }
            )
            cd_status_counter[status] += 1
            cd_source_counter[source] += 1
            cd_province_source.setdefault(province, Counter())[source] += 1

    # Write chain-level QID conflict audit file (whenever any conflict occurred).
    if cd_conflict_rows:
        CD_CONFLICTS.parent.mkdir(parents=True, exist_ok=True)
        with CD_CONFLICTS.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "chain_place_id", "canonical_name", "province",
                "cd_id", "wikidata_qid", "wikidata_label", "is_chosen",
            ])
            writer.writeheader()
            writer.writerows(cd_conflict_rows)
        n_chains = len({r["chain_place_id"] for r in cd_conflict_rows})
        print(f"\nWARNING: {n_chains} CD chains had member-QID conflicts; "
              f"deterministic pick written to {CD_CONFLICTS.relative_to(REPO)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "place_id:ID",
                "uri",
                "uri_source",
                "wikidata_qid",
                "wikidata_label",
                "grounding_status",
                "mint_reason",
            ],
        )
        writer.writeheader()
        writer.writerows(rows_out)

    total = len(rows_out)
    print(f"\nWrote {total:,} rows -> {OUT.relative_to(REPO)}")

    unused = set(grounding) - grounding_used
    if unused:
        print(
            f"\nWARNING: {len(unused)} grounding records could not be placed "
            f"(no 1921-active CSV row for base tcpuid). Written to "
            f"{UNPLACED.relative_to(REPO)}"
        )
        with UNPLACED.open("w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["csd_id", "status", "csd_name", "wikidata_qid", "wikidata_label"],
            )
            writer.writeheader()
            for cid in sorted(unused):
                rec = grounding[cid]
                writer.writerow(
                    {
                        "csd_id": cid,
                        "status": rec["status"],
                        "csd_name": rec.get("csd_name", ""),
                        "wikidata_qid": rec.get("wikidata_qid", ""),
                        "wikidata_label": rec.get("wikidata_label", ""),
                    }
                )

    cd_unused = set(cd_grounding) - cd_grounding_used
    if cd_unused:
        print(
            f"\nWARNING: {len(cd_unused)} CD grounding records had no matching "
            f"row in {E53_CD.name} (cd_id mismatch): {sorted(cd_unused)[:5]}..."
        )

    print("\nCSD grounding status:")
    for status, n in sorted(status_counter.items(), key=lambda x: -x[1]):
        print(f"  {status:12s} {n:6,}  ({n / sum(status_counter.values()):5.1%})")
    print("\nCSD URI source:")
    for source, n in sorted(source_counter.items(), key=lambda x: -x[1]):
        print(f"  {source:12s} {n:6,}  ({n / sum(source_counter.values()):5.1%})")
    print("\nCSD per-province URI source (wikidata / minted_hgis):")
    for prov in sorted(province_source):
        c = province_source[prov]
        wd = c.get("wikidata", 0)
        mt = c.get("minted_hgis", 0)
        tot = wd + mt
        pct = wd / tot if tot else 0.0
        print(f"  {prov:3s}  wikidata={wd:5,}  minted={mt:5,}  total={tot:5,}  ({pct:5.1%} grounded)")

    cd_total = sum(cd_status_counter.values())
    if cd_total:
        print("\nCD grounding status:")
        for status, n in sorted(cd_status_counter.items(), key=lambda x: -x[1]):
            print(f"  {status:12s} {n:6,}  ({n / cd_total:5.1%})")
        print("\nCD URI source:")
        for source, n in sorted(cd_source_counter.items(), key=lambda x: -x[1]):
            print(f"  {source:18s} {n:6,}  ({n / cd_total:5.1%})")
        print("\nCD per-province URI source (wikidata / minted_hgis_cd):")
        for prov in sorted(cd_province_source):
            c = cd_province_source[prov]
            wd = c.get("wikidata", 0)
            mt = c.get("minted_hgis_cd", 0)
            tot = wd + mt
            pct = wd / tot if tot else 0.0
            print(f"  {prov:3s}  wikidata={wd:4,}  minted={mt:4,}  total={tot:4,}  ({pct:5.1%} grounded)")


if __name__ == "__main__":
    main()
