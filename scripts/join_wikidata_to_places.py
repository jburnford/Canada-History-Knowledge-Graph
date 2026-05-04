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
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
JSONL = REPO / "wikidata_grounding" / "csd_verified_matches.jsonl"
PRESENCE_JSONL = REPO / "wikidata_grounding" / "presence_verified_matches.jsonl"
CD_JSONL = REPO / "wikidata_grounding" / "cd_verified_matches.jsonl"
CD_CHAIN_MAP = REPO / "persistent_cds_output" / "cd_id_year_to_chain.csv"
CD_CHAIN_REGISTRY = REPO / "persistent_cds_output" / "persistent_cd_registry.csv"
TCPUID_TO_PLACE = REPO / "persistent_places_output" / "tcpuid_year_to_place.csv"
CIDOC_DIR = REPO / "neo4j_cidoc_crm_v2"
E53_CSD = REPO / "neo4j_cidoc_crm_v2" / "e53_place_csd.csv"
E53_CD = REPO / "neo4j_cidoc_crm_v2" / "e53_place_cd.csv"
OUT = REPO / "neo4j_cidoc_crm_v2" / "e53_place_uri.csv"
UNPLACED = REPO / "neo4j_cidoc_crm_v2" / "e53_place_uri_unplaced.csv"
CD_CONFLICTS = REPO / "wikidata_grounding" / "cd_qid_conflicts.csv"
CSD_XREFS = REPO / "wikidata_grounding" / "csd_chain_qid_xrefs.csv"
SIBLING_REVIEW_QUEUE = REPO / "wikidata_grounding" / "sibling_review_queue.jsonl"
YEARS = (1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921)
MAX_SIBLING_KM = 50.0

# Path injection so `from _normalize import …` works whether invoked as
# `python3 scripts/join_wikidata_to_places.py` or imported as a module.
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from _normalize import normalize_for_match, bridge_normalize  # noqa: E402

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


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _load_presence_centroids() -> dict[tuple[str, int], tuple[float, float]]:
    """(tcpuid, year) → (lat, lon) from per-year e94 centroid files."""
    out: dict[tuple[str, int], tuple[float, float]] = {}
    for year in YEARS:
        path = CIDOC_DIR / f"e94_space_primitive_{year}.csv"
        if not path.exists():
            continue
        with path.open() as f:
            for row in csv.DictReader(f):
                space_id = row.get("space_id:ID", "")
                if not space_id.endswith("_centroid"):
                    continue
                stem = space_id[: -len("_centroid")]
                parts = stem.rsplit("_", 1)
                if len(parts) != 2 or not parts[1].isdigit():
                    continue
                tcpuid, yr = parts[0], int(parts[1])
                try:
                    out[(tcpuid, yr)] = (
                        float(row["latitude:float"]),
                        float(row["longitude:float"]),
                    )
                except (ValueError, TypeError, KeyError):
                    pass
    return out


CHAIN_SUFFIX_RE = re.compile(r"(?:_(\d{4}))+$")


def _tcpuid_from_place_id(place_id: str) -> str:
    """PLACE_ON065002 → ON065002; PLACE_AB001999_1911 → AB001999.
    The trailing _YYYY (optionally repeated) is a disambiguation suffix and
    must be stripped to recover the TCPUID for centroid lookup."""
    if place_id.startswith("PLACE_"):
        stem = place_id[len("PLACE_"):]
    else:
        stem = place_id
    return CHAIN_SUFFIX_RE.sub("", stem)


def load_chain_centroids() -> dict[str, tuple[float, float]]:
    """Compute representative chain centroid as the latest-year presence
    centroid. Joins e94 per-presence centroids onto chain place_ids using
    the years_active field on e53_place_csd plus tcpuid_year_to_place
    fallbacks. Place_ids with year-suffix disambiguators (e.g.
    PLACE_AB001999_1911) are resolved by stripping the suffix to recover
    the TCPUID."""
    presence_coords = _load_presence_centroids()
    chain_to_presences: dict[str, list[tuple[int, float, float]]] = defaultdict(list)

    # Pass 1: tcpuid_year_to_place mapping (handles base PLACE_<tcpuid> chains
    # whose presences span multiple TCPUIDs across years).
    if TCPUID_TO_PLACE.exists():
        with TCPUID_TO_PLACE.open() as f:
            for row in csv.DictReader(f):
                try:
                    year = int(row["year"])
                except (ValueError, KeyError):
                    continue
                tcpuid = row.get("tcpuid", "")
                place_id = row.get("persistent_place_id", "")
                coord = presence_coords.get((tcpuid, year))
                if not coord or not place_id:
                    continue
                chain_to_presences[place_id].append((year, coord[0], coord[1]))

    # Pass 2: for chains in e53_place_csd that the registry mapping missed
    # (year-suffix-disambiguated chains), derive (tcpuid, year) from the
    # place_id + years_active and look up coords directly.
    if E53_CSD.exists():
        with E53_CSD.open() as f:
            for row in csv.DictReader(f):
                place_id = row["place_id:ID"]
                if place_id in chain_to_presences:
                    continue
                tcpuid = _tcpuid_from_place_id(place_id)
                years_str = row.get("years_active", "")
                for ystr in years_str.split(";"):
                    ystr = ystr.strip()
                    if not ystr.isdigit():
                        continue
                    year = int(ystr)
                    coord = presence_coords.get((tcpuid, year))
                    if coord:
                        chain_to_presences[place_id].append((year, coord[0], coord[1]))

    out: dict[str, tuple[float, float]] = {}
    for place_id, presences in chain_to_presences.items():
        presences.sort(key=lambda x: x[0])
        out[place_id] = (presences[-1][1], presences[-1][2])
    return out


def load_presence_grounding(path: Path) -> dict[str, dict]:
    """Phase C output: per-presence records keyed by `current_chain` (E53 place_id).
    Multiple presences may map to one chain; collapse to the best status per chain.
    Priority: matched > mint_uri > skip. Returns chain_place_id -> representative record."""
    if not path.exists():
        return {}
    priority = {"matched": 3, "mint_uri": 2, "skip": 1}
    out: dict[str, dict] = {}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            chain = r.get("current_chain")
            if not chain:
                continue
            cur = out.get(chain)
            if cur is None or priority.get(r["status"], 0) > priority.get(cur["status"], 0):
                out[chain] = r
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


def load_csd_xref_overrides(path: Path) -> dict[str, dict]:
    """Curator override file. Schema:
        place_id, qid, label, decision, reason
    decision ∈ {force, suppress}. `force` attaches the QID to a chain that
    Track A + sibling-lookup couldn't ground; `suppress` removes a sibling
    match the curator considers wrong (no qid attached, chain stays minted).
    Empty / missing file is fine."""
    overrides: dict[str, dict] = {}
    if not path.exists():
        return overrides
    with path.open() as f:
        for r in csv.DictReader(f):
            pid = (r.get("place_id") or "").strip()
            decision = (r.get("decision") or "").strip().lower()
            if not pid or decision not in {"force", "suppress"}:
                continue
            overrides[pid] = {
                "qid": (r.get("qid") or "").strip(),
                "label": (r.get("label") or "").strip(),
                "decision": decision,
                "reason": (r.get("reason") or "").strip(),
            }
    return overrides


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

    overrides = load_csd_xref_overrides(CSD_XREFS)
    if overrides:
        print(f"Loaded {len(overrides):,} CSD chain QID overrides from "
              f"{CSD_XREFS.relative_to(REPO)}")

    # PHASE 1: direct grounding via 1921 csd_verified_matches.jsonl.
    # Build per-row scratch state so we can run the sibling pass against it.
    rows_out: list[dict] = []
    csd_rows: list[dict] = []  # parallel scratch: {place_id, base, name, province, years}
    with E53_CSD.open() as f:
        for row in csv.DictReader(f):
            place_id = row["place_id:ID"]
            assert place_id.startswith("PLACE_"), place_id
            tcpuid = place_id[len("PLACE_"):]
            base = base_tcpuid(tcpuid)
            province = row["province"]
            name = row["name"]
            years = row["years_active"].split(";") if row["years_active"] else []

            record = None
            if GROUNDING_YEAR in years and base in grounding:
                record = grounding[base]
                grounding_used.add(base)

            uri, source, qid = uri_for(
                base, record,
                place_id=place_id, name=name, province=province,
            )
            status = record["status"] if record else "ungrounded"
            mint_reason = (record or {}).get("mint_reason", "") if record else ""
            wd_label = (record or {}).get("wikidata_label", "") if record else ""

            out_row = {
                "place_id:ID": place_id,
                "uri": uri,
                "uri_source": source,
                "wikidata_qid": qid,
                "wikidata_label": wd_label,
                "grounding_status": status,
                "mint_reason": mint_reason,
            }
            rows_out.append(out_row)
            csd_rows.append({
                "place_id": place_id,
                "base": base,
                "name": name,
                "province": province,
                "years": years,
            })

    # PHASE 1.5: per-presence grounding from Phase C output. For any chain
    # still ungrounded after Phase 1, apply the chain-level Phase C decision:
    #   matched   → wd:Q… URI, uri_source = "wikidata_via_presence"
    #   mint_uri  → minted GitHub Pages URL, uri_source = "minted_hgis",
    #               grounding_status = "mint_uri" (with mint_reason from record)
    #   skip      → minted URL, uri_source = "minted_hgis",
    #               grounding_status = "skip" (no Wikidata sameAs at RDF emit)
    presence_grounding = load_presence_grounding(PRESENCE_JSONL)
    print(f"\nLoaded {len(presence_grounding):,} chain-level Phase C decisions "
          f"from {PRESENCE_JSONL.name}")
    presence_applied = Counter()
    for out_row, src in zip(rows_out, csd_rows):
        if out_row["uri_source"] != "minted_hgis":
            continue  # already grounded by Phase 1 (1921 grounding)
        rec = presence_grounding.get(out_row["place_id:ID"])
        if not rec:
            continue
        st = rec["status"]
        if st == "matched":
            qid = rec["wikidata_qid"]
            out_row["uri"] = f"{WIKIDATA_PREFIX}{qid}"
            out_row["uri_source"] = "wikidata_via_presence"
            out_row["wikidata_qid"] = qid
            out_row["wikidata_label"] = rec.get("wikidata_label", "")
            out_row["grounding_status"] = "matched"
            out_row["mint_reason"] = ""
        elif st == "mint_uri":
            # URI stays as the minted page URL from Phase 1; just upgrade the
            # status and attach the curator-provided mint_reason.
            out_row["grounding_status"] = "mint_uri"
            out_row["mint_reason"] = rec.get("mint_reason", "")
        elif st == "skip":
            out_row["grounding_status"] = "skip"
            out_row["mint_reason"] = rec.get("mint_reason", "")
        presence_applied[st] += 1
    print(f"Phase C applied: matched={presence_applied['matched']:,} "
          f"mint_uri={presence_applied['mint_uri']:,} "
          f"skip={presence_applied['skip']:,}")

    # PHASE 2: sibling-name inheritance. Index every directly-grounded chain
    # by (bridge_normalize(name), province) → (qid, label, donor_place_id,
    # donor_centroid). Then any chain whose Phase-1/1.5 result is `ungrounded`
    # looks itself up in the index. On hit, the chain inherits the QID with
    # uri_source = `wikidata_via_sibling` ONLY IF the candidate's chain
    # centroid is within MAX_SIBLING_KM of the donor's chain centroid. This
    # blocks the common-name false-positive pattern (multiple QC parishes
    # named "St. François" in different regions all inheriting one parish's
    # QID). Skipped if multiple distinct QIDs collide for the same key.
    chain_centroids = load_chain_centroids()
    print(f"\nLoaded {len(chain_centroids):,} chain centroids for sibling-distance gate")
    sibling_index: dict[tuple[str, str], dict] = {}
    sibling_conflicts: dict[tuple[str, str], set[str]] = defaultdict(set)
    for out_row, src in zip(rows_out, csd_rows):
        if not out_row["uri_source"].startswith("wikidata"):
            continue
        key = (bridge_normalize(src["name"]), src["province"])
        if not key[0] or not key[1]:
            continue
        sibling_conflicts[key].add(out_row["wikidata_qid"])
        if key not in sibling_index:
            sibling_index[key] = {
                "qid": out_row["wikidata_qid"],
                "label": out_row["wikidata_label"],
                "donor": out_row["place_id:ID"],
                "donor_centroid": chain_centroids.get(out_row["place_id:ID"]),
            }
    # Drop ambiguous keys (multiple QIDs)
    for key, qids in sibling_conflicts.items():
        if len(qids) > 1:
            sibling_index.pop(key, None)

    # PHASE 3: apply sibling lookup + override file.
    sibling_inherits = 0
    sibling_rejected_far = 0
    sibling_rejected_no_centroid = 0
    review_queue: list[dict] = []
    override_force = 0
    override_suppress = 0
    for out_row, src in zip(rows_out, csd_rows):
        place_id = out_row["place_id:ID"]
        ov = overrides.get(place_id)

        # Suppress override: clear any auto-attached QID and keep minted URI.
        if ov and ov["decision"] == "suppress":
            if out_row["uri_source"].startswith("wikidata"):
                # Override fights an auto-match; restore minted URI.
                out_row["uri"] = minted_page_url(src["name"], place_id, src["province"])
                out_row["uri_source"] = "minted_hgis"
                out_row["wikidata_qid"] = ""
                out_row["wikidata_label"] = ""
                out_row["grounding_status"] = "ungrounded"
                out_row["mint_reason"] = f"override_suppress: {ov['reason']}"
            override_suppress += 1
            continue

        # Force override: attach a QID regardless of Phase 1 / Phase 2.
        if ov and ov["decision"] == "force" and ov["qid"]:
            out_row["uri"] = f"{WIKIDATA_PREFIX}{ov['qid']}"
            out_row["uri_source"] = "wikidata_via_override"
            out_row["wikidata_qid"] = ov["qid"]
            out_row["wikidata_label"] = ov["label"]
            out_row["grounding_status"] = "matched"
            out_row["mint_reason"] = ""
            override_force += 1
            continue

        # Sibling inheritance: only for chains still genuinely ungrounded.
        # Skip chains whose grounding_status is already mint_uri or skip —
        # those represent explicit Phase C decisions ("no separate WD entity"
        # / "aggregate enumeration") that the sibling pass must not overrule.
        if out_row["uri_source"] != "minted_hgis":
            continue
        if out_row["grounding_status"] != "ungrounded":
            continue
        key = (bridge_normalize(src["name"]), src["province"])
        donor = sibling_index.get(key)
        if not donor or donor["donor"] == place_id:
            continue
        # Centroid gate: distinct QC parishes named e.g. "Ste. Anne" sit
        # in different parts of the province. Refuse to inherit a donor's
        # QID if the candidate chain's centroid is more than MAX_SIBLING_KM
        # from the donor's chain centroid.
        cand_cent = chain_centroids.get(place_id)
        donor_cent = donor.get("donor_centroid")
        if cand_cent and donor_cent:
            d_km = haversine_km(cand_cent[0], cand_cent[1],
                                donor_cent[0], donor_cent[1])
            if d_km > MAX_SIBLING_KM:
                sibling_rejected_far += 1
                review_queue.append({
                    "place_id": place_id,
                    "name": src["name"],
                    "province": src["province"],
                    "candidate_lat": cand_cent[0],
                    "candidate_lon": cand_cent[1],
                    "rejected_qid": donor["qid"],
                    "rejected_label": donor["label"],
                    "donor_chain": donor["donor"],
                    "donor_lat": donor_cent[0],
                    "donor_lon": donor_cent[1],
                    "distance_km": round(d_km, 1),
                    "reason": "sibling_far",
                })
                continue
        else:
            # Lacking centroid for either side — refuse to inherit blindly.
            sibling_rejected_no_centroid += 1
            review_queue.append({
                "place_id": place_id,
                "name": src["name"],
                "province": src["province"],
                "candidate_lat": (cand_cent or (None, None))[0],
                "candidate_lon": (cand_cent or (None, None))[1],
                "rejected_qid": donor["qid"],
                "rejected_label": donor["label"],
                "donor_chain": donor["donor"],
                "donor_lat": (donor_cent or (None, None))[0],
                "donor_lon": (donor_cent or (None, None))[1],
                "distance_km": None,
                "reason": "no_centroid",
            })
            continue
        out_row["uri"] = f"{WIKIDATA_PREFIX}{donor['qid']}"
        out_row["uri_source"] = "wikidata_via_sibling"
        out_row["wikidata_qid"] = donor["qid"]
        out_row["wikidata_label"] = donor["label"]
        out_row["grounding_status"] = "matched"
        out_row["mint_reason"] = f"sibling: {donor['donor']}"
        sibling_inherits += 1

    # Recompute counters from final state.
    for out_row in rows_out:
        status_counter[out_row["grounding_status"]] += 1
        source_counter[out_row["uri_source"]] += 1
        # province lookup via parallel csd_rows
    for out_row, src in zip(rows_out, csd_rows):
        province_source.setdefault(src["province"], Counter())[out_row["uri_source"]] += 1

    print(f"\nSibling-name inheritance: {sibling_inherits:,} chains")
    print(f"Sibling rejected (far >{MAX_SIBLING_KM:.0f} km): {sibling_rejected_far:,}")
    print(f"Sibling rejected (no centroid): {sibling_rejected_no_centroid:,}")
    print(f"Override force / suppress: {override_force:,} / {override_suppress:,}")
    if review_queue:
        SIBLING_REVIEW_QUEUE.parent.mkdir(parents=True, exist_ok=True)
        with SIBLING_REVIEW_QUEUE.open("w") as f:
            for entry in review_queue:
                f.write(json.dumps(entry) + "\n")
        print(f"Wrote {len(review_queue):,} rejected sibling candidates -> "
              f"{SIBLING_REVIEW_QUEUE.relative_to(REPO)}")

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
