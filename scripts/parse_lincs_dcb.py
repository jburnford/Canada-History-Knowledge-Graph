"""Parse LINCS hist-cdns.ttl for the DCB-backed person cohort.

Outputs:
  data/lincs_dcb_persons.json  — full per-person record (DCB cohort only)
  data/lincs_dcb_links.csv     — (person_id, dcb_url, dcb_label_en, dcb_label_fr)

Strategy:
  1. rdflib loads the 195 MB TTL once (~4-6 GB RAM, ~2-3 min).
  2. SPARQL extracts (a) DCB → person mapping, (b) person → occupations.
  3. Existing JSON (lincs_historical_canadians.json) supplies events + ids.
  4. Inner-join by personId, drop pre-cohort lifespans, write output.

Date rule (from NOTABLE_CANADIANS_PLAN.md §61):
  keep_person(p) := death_year >= 1850
                    OR (death_year is None AND birth_year >= 1800)
                    OR any_event_year >= 1850
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

import rdflib

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from _config import CONFIG  # noqa: E402

TTL_DEFAULT = CONFIG.lincs_ttl
JSON_DEFAULT = CONFIG.lincs_json
OUT_JSON = REPO / "data" / "lincs_dcb_persons.json"
OUT_CSV = REPO / "data" / "lincs_dcb_links.csv"

LINCS_PREFIX = "http://id.lincsproject.ca/"
WD_PREFIX = "http://www.wikidata.org/entity/"
VIAF_PREFIX = "http://viaf.org/viaf/"
DCB_PREFIX = "http://www.biographi.ca/"
OCCUPATION_PREFIX = "http://id.lincsproject.ca/occupation/"


def normalize_person_uri(uri: str) -> Optional[str]:
    """Map a full TTL URI to the JSON personId convention (lincs:X / wd:Q / viaf:N)."""
    if uri.startswith(LINCS_PREFIX):
        tail = uri[len(LINCS_PREFIX):]
        # Filter sub-namespaced URIs we don't expect (e.g., occupation/X) — persons are bare ids.
        if "/" in tail:
            return None
        return f"lincs:{tail}"
    if uri.startswith(WD_PREFIX):
        return f"wd:{uri[len(WD_PREFIX):]}"
    if uri.startswith(VIAF_PREFIX):
        return f"viaf:{uri[len(VIAF_PREFIX):]}"
    return None


def event_year(event: Optional[dict]) -> Optional[int]:
    if not event:
        return None
    for key in ("dateBegin", "dateEnd", "date"):
        v = event.get(key)
        if not v:
            continue
        # ISO timestamp: pick the leading 4 digits if they look like a year.
        head = str(v)[:4]
        if head.isdigit():
            year = int(head)
            if 1000 <= year <= 2100:
                return year
    return None


def keep_person(birth_year: Optional[int], death_year: Optional[int],
                any_event_year: Optional[int]) -> bool:
    if death_year is not None and death_year >= 1850:
        return True
    if death_year is None and birth_year is not None and birth_year >= 1800:
        return True
    if any_event_year is not None and any_event_year >= 1850:
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ttl", type=Path, default=TTL_DEFAULT)
    ap.add_argument("--json", type=Path, default=JSON_DEFAULT)
    ap.add_argument("--out-json", type=Path, default=OUT_JSON)
    ap.add_argument("--out-csv", type=Path, default=OUT_CSV)
    args = ap.parse_args()

    args.out_json.parent.mkdir(parents=True, exist_ok=True)

    print(f"[1/5] Loading TTL: {args.ttl}", file=sys.stderr)
    t0 = time.time()
    g = rdflib.Graph()
    g.parse(str(args.ttl), format="turtle")
    print(f"      loaded {len(g):,} triples in {time.time()-t0:.0f}s", file=sys.stderr)

    print("[2/5] Querying DCB → person", file=sys.stderr)
    q_dcb = """
    PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?dcb ?person ?label WHERE {
      ?dcb a crm:E33_Linguistic_Object ;
           crm:P129_is_about ?person .
      OPTIONAL { ?dcb rdfs:label ?label }
      FILTER(STRSTARTS(STR(?dcb), "http://www.biographi.ca/"))
    }
    """
    person_to_dcb: dict[str, dict] = {}
    dcb_to_person: dict[str, str] = {}
    rows = 0
    for dcb, person, label in g.query(q_dcb):
        rows += 1
        dcb_url = str(dcb)
        person_id = normalize_person_uri(str(person))
        if not person_id:
            continue
        rec = person_to_dcb.setdefault(person_id, {
            "dcb_url": dcb_url,
            "dcb_url_en": None,
            "dcb_url_fr": None,
            "dcb_label_en": None,
            "dcb_label_fr": None,
        })
        if "/en/bio/" in dcb_url:
            rec["dcb_url_en"] = dcb_url
            # Prefer the English URL as canonical when both exist.
            rec["dcb_url"] = dcb_url
        elif "/fr/bio/" in dcb_url:
            rec["dcb_url_fr"] = dcb_url
            if not rec["dcb_url_en"]:
                rec["dcb_url"] = dcb_url
        if label is not None:
            lang = getattr(label, "language", None)
            if lang == "en" and not rec["dcb_label_en"]:
                rec["dcb_label_en"] = str(label)
            elif lang == "fr" and not rec["dcb_label_fr"]:
                rec["dcb_label_fr"] = str(label)
        dcb_to_person[dcb_url] = person_id
    print(f"      DCB→person rows: {rows:,}", file=sys.stderr)
    print(f"      distinct persons with DCB bio: {len(person_to_dcb):,}", file=sys.stderr)
    print(f"      distinct DCB URLs: {len(dcb_to_person):,}", file=sys.stderr)

    print("[3/5] Querying person → occupations", file=sys.stderr)
    q_occ = """
    PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?person ?occ ?label WHERE {
      ?activity a crm:E7_Activity ;
                crm:P14_carried_out_by ?person ;
                crm:P2_has_type ?occ .
      OPTIONAL { ?occ rdfs:label ?label FILTER(LANG(?label) = "en") }
      FILTER(STRSTARTS(STR(?occ), "http://id.lincsproject.ca/occupation/"))
    }
    """
    person_occupations: dict[str, dict[str, str]] = defaultdict(dict)
    occ_rows = 0
    for person, occ, label in g.query(q_occ):
        occ_rows += 1
        person_id = normalize_person_uri(str(person))
        if not person_id:
            continue
        occ_id = str(occ)[len(OCCUPATION_PREFIX):] if str(occ).startswith(OCCUPATION_PREFIX) else str(occ)
        # Prefer the rdfs:label, else the URI tail.
        person_occupations[person_id][occ_id] = str(label) if label is not None else occ_id
    print(f"      occupation activity rows: {occ_rows:,}", file=sys.stderr)
    print(f"      persons with ≥1 occupation: {len(person_occupations):,}", file=sys.stderr)

    print("[4/5] Loading existing JSON for events + ids", file=sys.stderr)
    with open(args.json) as fh:
        json_data = json.load(fh)
    by_id = {p["personId"]: p for p in json_data["persons"]}
    print(f"      JSON persons indexed: {len(by_id):,}", file=sys.stderr)

    print("[5/5] Merging + filtering DCB cohort by date rule", file=sys.stderr)
    output = []
    n_dcb_with_json = 0
    n_dcb_without_json = 0
    n_kept = 0
    n_dropped_date = 0
    for person_id, dcb_info in sorted(person_to_dcb.items()):
        json_rec = by_id.get(person_id)
        if json_rec is None:
            n_dcb_without_json += 1
            # Stub record so we don't lose the DCB linkage entirely.
            merged = {
                "personId": person_id,
                "idType": person_id.split(":", 1)[0].upper(),
                "name": dcb_info.get("dcb_label_en") or dcb_info.get("dcb_label_fr"),
                "alternateNames": [],
                "wikidataQid": person_id[3:] if person_id.startswith("wd:") else None,
                "viafId": person_id[5:] if person_id.startswith("viaf:") else None,
                "birthEvent": None,
                "deathEvent": None,
                "occupations": [],
                "relationships": [],
                "_no_event_data": True,
            }
        else:
            n_dcb_with_json += 1
            merged = dict(json_rec)
        merged["dcb_url"] = dcb_info["dcb_url"]
        merged["dcb_url_en"] = dcb_info["dcb_url_en"]
        merged["dcb_url_fr"] = dcb_info["dcb_url_fr"]
        merged["dcb_label_en"] = dcb_info["dcb_label_en"]
        merged["dcb_label_fr"] = dcb_info["dcb_label_fr"]
        merged["occupations"] = sorted(person_occupations.get(person_id, {}).values())
        merged["occupationIds"] = sorted(person_occupations.get(person_id, {}).keys())

        birth_year = event_year(merged.get("birthEvent"))
        death_year = event_year(merged.get("deathEvent"))
        any_event_year = max(filter(None, [birth_year, death_year]), default=None)
        if not keep_person(birth_year, death_year, any_event_year):
            n_dropped_date += 1
            continue
        merged["birthYear"] = birth_year
        merged["deathYear"] = death_year
        output.append(merged)
        n_kept += 1

    print(f"      DCB persons with JSON event data: {n_dcb_with_json:,}", file=sys.stderr)
    print(f"      DCB persons missing from JSON:    {n_dcb_without_json:,}", file=sys.stderr)
    print(f"      dropped by date rule:             {n_dropped_date:,}", file=sys.stderr)
    print(f"      kept in cohort:                   {n_kept:,}", file=sys.stderr)

    print(f"      Writing {args.out_json}", file=sys.stderr)
    with open(args.out_json, "w") as fh:
        json.dump({
            "metadata": {
                "source": "LINCS hist-cdns.ttl + lincs_historical_canadians.json",
                "totalDcbPersons": len(person_to_dcb),
                "cohortPersons": n_kept,
                "droppedByDateRule": n_dropped_date,
                "missingJsonEvents": n_dcb_without_json,
            },
            "persons": output,
        }, fh, indent=2, default=str)

    print(f"      Writing {args.out_csv}", file=sys.stderr)
    with open(args.out_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["person_id", "dcb_url", "dcb_url_en", "dcb_url_fr",
                    "dcb_label_en", "dcb_label_fr", "in_cohort"])
        kept_ids = {p["personId"] for p in output}
        for person_id, dcb_info in sorted(person_to_dcb.items()):
            w.writerow([
                person_id,
                dcb_info["dcb_url"],
                dcb_info["dcb_url_en"] or "",
                dcb_info["dcb_url_fr"] or "",
                dcb_info["dcb_label_en"] or "",
                dcb_info["dcb_label_fr"] or "",
                "1" if person_id in kept_ids else "0",
            ])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
