#!/usr/bin/env python3
"""
Fetch English + French Wikipedia article URLs for every Wikidata QID currently
grounded in the Kuzu DB. Output: wikidata_grounding/wikipedia_sitelinks.csv
with columns: qid, enwiki_url, frwiki_url.

Uses the Wikidata Query Service SPARQL endpoint. Batched in chunks of 300
QIDs to stay well under WDQS query limits.

Usage:
    python3 scripts/fetch_wikipedia_sitelinks.py
    python3 scripts/fetch_wikipedia_sitelinks.py --limit 50    # for testing
"""

import argparse
import csv
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB_PATH = REPO / "pilot" / "on_kuzu" / "on.kuzu"
OUT_PATH = REPO / "wikidata_grounding" / "wikipedia_sitelinks.csv"

WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = (
    "HGISCanadaKnowledgeGraph/1.0 "
    "(https://jimclifford.ca/hgiscanada/; jim.clifford@usask.ca) Python/urllib"
)

BATCH_SIZE = 300


SPARQL_TEMPLATE = """\
SELECT ?qid ?enArticle ?frArticle WHERE {{
  VALUES ?qid {{ {qid_values} }}
  OPTIONAL {{
    ?enArticle schema:about ?qid ;
               schema:isPartOf <https://en.wikipedia.org/> ;
               schema:inLanguage "en" .
  }}
  OPTIONAL {{
    ?frArticle schema:about ?qid ;
               schema:isPartOf <https://fr.wikipedia.org/> ;
               schema:inLanguage "fr" .
  }}
}}
"""


def fetch_batch(qids: list[str]) -> dict:
    """Return {qid: (enwiki_url, frwiki_url)}."""
    qid_values = " ".join(f"wd:{q}" for q in qids)
    sparql = SPARQL_TEMPLATE.format(qid_values=qid_values)
    data = urllib.parse.urlencode({"query": sparql, "format": "json"}).encode()
    req = urllib.request.Request(
        WDQS_ENDPOINT,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/sparql-results+json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode()
    import json
    parsed = json.loads(body)
    out = {}
    for binding in parsed.get("results", {}).get("bindings", []):
        qid_uri = binding.get("qid", {}).get("value", "")
        # qid uri looks like http://www.wikidata.org/entity/Q1234
        qid = qid_uri.rsplit("/", 1)[-1]
        en = binding.get("enArticle", {}).get("value", "") or ""
        fr = binding.get("frArticle", {}).get("value", "") or ""
        # If both are absent we still want a row so the QID isn't refetched.
        prev = out.get(qid, ("", ""))
        out[qid] = (en or prev[0], fr or prev[1])
    # Make sure every requested QID appears in the dict, even if empty.
    for q in qids:
        out.setdefault(q, ("", ""))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="Limit number of QIDs (for smoke testing)")
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()

    out_path = Path(args.out)

    import ladybug as kuzu  # Ladybug = maintained Kuzu fork; drop-in API
    db = kuzu.Database(str(DB_PATH))
    conn = kuzu.Connection(db)

    print(f"[1/3] Reading distinct grounded QIDs from {DB_PATH}...")
    res = conn.execute(
        "MATCH (p:Place) WHERE p.wikidata_qid IS NOT NULL "
        "RETURN DISTINCT p.wikidata_qid ORDER BY p.wikidata_qid;"
    )
    qids = []
    while res.has_next():
        qids.append(res.get_next()[0])
    print(f"   {len(qids)} distinct QIDs")

    if args.limit:
        qids = qids[: args.limit]
        print(f"   (limited to {len(qids)} for testing)")

    print(f"[2/3] Querying WDQS in batches of {BATCH_SIZE}...")
    all_results = {}
    for i in range(0, len(qids), BATCH_SIZE):
        batch = qids[i : i + BATCH_SIZE]
        print(f"   batch {i // BATCH_SIZE + 1}/{(len(qids) + BATCH_SIZE - 1) // BATCH_SIZE} "
              f"({len(batch)} QIDs)...", end="", flush=True)
        try:
            results = fetch_batch(batch)
            all_results.update(results)
            with_en = sum(1 for v in results.values() if v[0])
            with_fr = sum(1 for v in results.values() if v[1])
            print(f" got {len(results)} rows, {with_en} EN + {with_fr} FR")
        except Exception as e:
            print(f" ERROR: {e}", file=sys.stderr)
            # Mark them all as empty so they're not retried indefinitely.
            for q in batch:
                all_results.setdefault(q, ("", ""))
        # Polite delay to stay friendly with WDQS.
        time.sleep(1.0)

    print(f"[3/3] Writing {out_path}...")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["qid", "enwiki_url", "frwiki_url"])
        for qid in sorted(all_results):
            en, fr = all_results[qid]
            w.writerow([qid, en, fr])
    en_count = sum(1 for v in all_results.values() if v[0])
    fr_count = sum(1 for v in all_results.values() if v[1])
    print(f"   {len(all_results)} rows; {en_count} have EN article, {fr_count} have FR article")


if __name__ == "__main__":
    main()
