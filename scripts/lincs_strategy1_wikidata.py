"""Strategy 1: Wikidata P19/P20/P119 → CSD place_id match.

For each DCB-cohort person with a Wikidata QID:
  1. Query Wikidata SPARQL endpoint for P19 (birth), P20 (death), P119 (burial).
  2. Look up returned place QIDs in our grounded CSD registry.
  3. Emit (person, csd, event_type, year) link rows.

Inputs:
  data/lincs_dcb_persons.json
  neo4j_cidoc_crm_v2/e53_place_uri.csv
  persistent_places_output/persistent_place_registry.csv

Outputs:
  data/wd_person_places_cache.json   — per-person {P19,P20,P119} from Wikidata
  data/lincs_strategy1_links.csv     — final (person, csd) links
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COHORT = REPO / "data" / "lincs_dcb_persons.json"
PLACE_URI = REPO / "neo4j_cidoc_crm_v2" / "e53_place_uri.csv"
PERSISTENT = REPO / "persistent_places_output" / "persistent_place_registry.csv"
CACHE = REPO / "data" / "wd_person_places_cache.json"
OUT = REPO / "data" / "lincs_strategy1_links.csv"

WD_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = (
    "Canada-History-KG/0.1 (https://github.com/jburnford/Canada-History-Knowledge-Graph; "
    "cljim22@gmail.com) Python/urllib"
)


def cohort_qids(persons: list[dict]) -> dict[str, str]:
    """Return person_id → QID for cohort entries that have any wikidata anchor."""
    out = {}
    for p in persons:
        qid = p.get("wikidataQid")
        if not qid and p.get("personId", "").startswith("wd:"):
            qid = p["personId"][3:]
        if qid:
            out[p["personId"]] = qid
    return out


def load_csd_qid_lookup() -> dict[str, dict]:
    """Build {wikidata_qid: {place_id, label, ...}} for grounded CSD-level places only."""
    csd_ids = set()
    with open(PERSISTENT) as fh:
        r = csv.DictReader(fh)
        for row in r:
            csd_ids.add(row["persistent_place_id"])

    out = {}
    with open(PLACE_URI) as fh:
        r = csv.DictReader(fh)
        for row in r:
            place_id = row["place_id:ID"]
            qid = (row.get("wikidata_qid") or "").strip()
            status = (row.get("grounding_status") or "").strip()
            if not qid or status != "matched":
                continue
            if place_id not in csd_ids:
                continue
            out[qid] = {
                "place_id": place_id,
                "label": row.get("wikidata_label", ""),
                "uri": row.get("uri", ""),
            }
    return out


def sparql_query(query: str, retries: int = 3) -> dict:
    params = urllib.parse.urlencode({"query": query, "format": "json"})
    url = f"{WD_ENDPOINT}?{params}"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/sparql-results+json",
    })
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)
        except Exception as e:
            last_err = e
            wait = 5 * (attempt + 1)
            print(f"      SPARQL retry {attempt+1}/{retries} after {wait}s: {e}", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"SPARQL failed after {retries} attempts: {last_err}")


def fetch_person_places(qids: list[str], batch_size: int = 200) -> dict[str, dict]:
    """Returns {qid: {"P19": [qids], "P20": [qids], "P119": [qids]}}."""
    out: dict[str, dict] = {q: {"P19": [], "P20": [], "P119": []} for q in qids}
    for i in range(0, len(qids), batch_size):
        chunk = qids[i:i + batch_size]
        values = " ".join(f"wd:{q}" for q in chunk)
        query = f"""
        SELECT ?person ?p19 ?p20 ?p119 WHERE {{
          VALUES ?person {{ {values} }}
          OPTIONAL {{ ?person wdt:P19 ?p19 . }}
          OPTIONAL {{ ?person wdt:P20 ?p20 . }}
          OPTIONAL {{ ?person wdt:P119 ?p119 . }}
        }}
        """
        print(f"      batch {i//batch_size + 1}: {len(chunk)} persons", file=sys.stderr)
        data = sparql_query(query)
        for row in data["results"]["bindings"]:
            person_qid = row["person"]["value"].rsplit("/", 1)[-1]
            for prop in ("p19", "p20", "p119"):
                if prop in row:
                    place_qid = row[prop]["value"].rsplit("/", 1)[-1]
                    bucket = out[person_qid][prop.upper()]
                    if place_qid not in bucket:
                        bucket.append(place_qid)
        # Be polite — Wikidata asks for short pauses between heavy queries.
        time.sleep(2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--use-cache", action="store_true",
                    help="Reuse cached WD responses if present")
    ap.add_argument("--batch-size", type=int, default=200)
    ap.add_argument("--limit", type=int, default=0,
                    help="Limit cohort persons (for testing)")
    args = ap.parse_args()

    print(f"[1/4] Loading cohort: {COHORT}", file=sys.stderr)
    with open(COHORT) as fh:
        persons = json.load(fh)["persons"]
    by_id = {p["personId"]: p for p in persons}
    pid_to_qid = cohort_qids(persons)
    print(f"      cohort size: {len(persons)}, with WD QID: {len(pid_to_qid)}", file=sys.stderr)
    if args.limit:
        pid_to_qid = dict(list(pid_to_qid.items())[:args.limit])
        print(f"      LIMITED to {len(pid_to_qid)}", file=sys.stderr)

    print(f"[2/4] Loading CSD wikidata grounding", file=sys.stderr)
    csd_lookup = load_csd_qid_lookup()
    print(f"      grounded CSD QIDs: {len(csd_lookup)}", file=sys.stderr)

    print(f"[3/4] Fetching P19/P20/P119 from Wikidata", file=sys.stderr)
    if args.use_cache and CACHE.exists():
        with open(CACHE) as fh:
            cache = json.load(fh)
        print(f"      using cache with {len(cache)} entries", file=sys.stderr)
    else:
        cache = {}
    qids_needed = sorted({q for q in pid_to_qid.values() if q not in cache})
    print(f"      QIDs to fetch: {len(qids_needed)} (cached: {len(cache)})", file=sys.stderr)
    if qids_needed:
        fresh = fetch_person_places(qids_needed, batch_size=args.batch_size)
        cache.update(fresh)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE, "w") as fh:
            json.dump(cache, fh)
        print(f"      cached {len(cache)} entries → {CACHE}", file=sys.stderr)

    print(f"[4/4] Matching against CSD registry → {OUT}", file=sys.stderr)
    n_links = 0
    n_persons_with_link = 0
    n_persons_with_any_p19_p20_p119 = 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "person_id", "person_name", "person_qid", "dcb_url",
            "event_type", "event_year",
            "place_qid", "place_id", "place_label",
            "match_strategy", "confidence",
        ])
        for person_id, person_qid in sorted(pid_to_qid.items()):
            person = by_id[person_id]
            wd_props = cache.get(person_qid, {})
            has_any = any(wd_props.get(p) for p in ("P19", "P20", "P119"))
            if has_any:
                n_persons_with_any_p19_p20_p119 += 1
            person_linked = False
            for prop, event_type, year_field in [
                ("P19", "birth", "birthYear"),
                ("P20", "death", "deathYear"),
                ("P119", "burial", "deathYear"),  # burial year — fall back to death year
            ]:
                year = person.get(year_field)
                for place_qid in wd_props.get(prop, []):
                    csd = csd_lookup.get(place_qid)
                    if not csd:
                        continue
                    w.writerow([
                        person_id, person.get("name", ""), person_qid,
                        person.get("dcb_url", ""),
                        event_type, year if year is not None else "",
                        place_qid, csd["place_id"], csd["label"],
                        "wd", "high",
                    ])
                    n_links += 1
                    person_linked = True
            if person_linked:
                n_persons_with_link += 1

    print(f"      persons with any P19/P20/P119 from WD: {n_persons_with_any_p19_p20_p119}",
          file=sys.stderr)
    print(f"      persons with ≥1 CSD-level match:       {n_persons_with_link}", file=sys.stderr)
    print(f"      total link rows emitted:               {n_links}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
