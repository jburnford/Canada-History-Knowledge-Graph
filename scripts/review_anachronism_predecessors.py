#!/usr/bin/env python3
"""Verify P1365 predecessors of post-1930 matched entities.

For each of the 66 candidates flagged by --review-anachronism that have a
predecessor with pre-1922 inception, this script:
  - Fetches all predecessors and the modern matched entity
  - Counts how many predecessors the modern entity has (single rename vs merger)
  - Picks the predecessor whose label best matches the CSD name
  - Confirms the predecessor has a valid settlement P31
  - Recommends: KEEP modern, SWITCH to predecessor X, or REVIEW manually

Output: csd_anachronism_decisions.csv
"""

import csv
import json
import sys
import time
import urllib.request
from pathlib import Path
from difflib import SequenceMatcher

REPO_DIR = Path(__file__).resolve().parent.parent
GROUNDING_DIR = REPO_DIR / "wikidata_grounding"
REPORT_CSV = GROUNDING_DIR / "csd_anachronism_review_1930.csv"
OUT_CSV = GROUNDING_DIR / "csd_anachronism_decisions.csv"

# Re-import the allowed P31 set from the main script
sys.path.insert(0, str(REPO_DIR / "scripts"))
from disambiguate_csds import GOOD_P31_QIDS, fetch_wikidata_entities  # noqa: E402


def name_similarity(a, b):
    """Normalized fuzzy similarity, 0..1."""
    a = a.lower().replace("-", " ").replace("'", "").replace("é", "e").replace("è", "e").replace("ô", "o").replace("ê", "e")
    b = b.lower().replace("-", " ").replace("'", "").replace("é", "e").replace("è", "e").replace("ô", "o").replace("ê", "e")
    return SequenceMatcher(None, a, b).ratio()


def entity_p31(entity):
    out = set()
    for claim in entity.get("claims", {}).get("P31", []):
        v = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(v, dict) and "id" in v:
            out.add(v["id"])
    return out


def entity_inception_years(entity):
    years = []
    for claim in entity.get("claims", {}).get("P571", []):
        v = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(v, dict) and "time" in v:
            t = v["time"]
            try:
                sign = 1 if t.startswith("+") else -1
                year_str = t[1:].split("-")[0]
                years.append(sign * int(year_str))
            except (ValueError, IndexError):
                pass
    return sorted(years)


def main():
    rows = []
    with open(REPORT_CSV) as f:
        r = csv.DictReader(f)
        for row in r:
            if row["predecessor_qids"]:
                pmin = row.get("predecessor_inception_min", "")
                if pmin and pmin.isdigit() and int(pmin) <= 1921:
                    rows.append(row)

    print(f"Verifying {len(rows)} candidates with pre-1922 predecessors...")

    # Collect all QIDs we need (modern + predecessors)
    all_qids = set()
    for row in rows:
        all_qids.add(row["matched_qid"])
        for q in row["predecessor_qids"].split(";"):
            if q:
                all_qids.add(q)

    print(f"Fetching {len(all_qids)} entities...")
    entities = fetch_wikidata_entities(sorted(all_qids))

    decisions = []
    for row in rows:
        csd_id = row["csd_id"]
        csd_name = row["csd_name"]
        modern_qid = row["matched_qid"]
        modern_label = row["matched_label"]
        modern_inception = row["min_inception"]
        pred_qids = [q for q in row["predecessor_qids"].split(";") if q]

        modern_ent = entities.get(modern_qid)
        n_predecessors = len(pred_qids)

        # Score each predecessor by name similarity to CSD name
        scored = []
        for pq in pred_qids:
            pent = entities.get(pq)
            if not pent:
                continue
            plabel = pent.get("labels", {}).get("en", {}).get("value", "")
            pdesc = pent.get("descriptions", {}).get("en", {}).get("value", "")
            pyears = entity_inception_years(pent)
            pp31 = entity_p31(pent)
            sim = name_similarity(csd_name, plabel)
            valid_type = bool(pp31 & GOOD_P31_QIDS)
            scored.append({
                "qid": pq,
                "label": plabel,
                "desc": pdesc,
                "min_year": min(pyears) if pyears else None,
                "p31": pp31,
                "valid_type": valid_type,
                "name_sim": sim,
            })

        scored.sort(key=lambda x: x["name_sim"], reverse=True)
        best = scored[0] if scored else None

        # Decide: keep modern, switch, or review
        if not best:
            decision = "REVIEW"
            reason = "No predecessor entity data"
            target_qid = ""
            target_label = ""
        elif n_predecessors == 1 and best["name_sim"] > 0.7:
            # Single rename — modern is fine territorially, but predecessor
            # is more historically accurate. Keep modern unless name matches
            # predecessor much better.
            modern_sim = name_similarity(csd_name, modern_label)
            if best["name_sim"] > modern_sim + 0.1 and best["valid_type"]:
                decision = "SWITCH"
                reason = f"Single replacement, predecessor name ({best['name_sim']:.2f}) much closer than modern ({modern_sim:.2f})"
                target_qid = best["qid"]
                target_label = best["label"]
            else:
                decision = "KEEP_MODERN"
                reason = f"Single replacement, modern label fits ({modern_sim:.2f}) ≥ predecessor ({best['name_sim']:.2f})"
                target_qid = modern_qid
                target_label = modern_label
        elif best["name_sim"] >= 0.8 and best["valid_type"]:
            # Multi-predecessor merger but a clear best match exists
            decision = "SWITCH"
            reason = f"Modern is N→1 merger ({n_predecessors} predecessors); best predecessor matches CSD name ({best['name_sim']:.2f})"
            target_qid = best["qid"]
            target_label = best["label"]
        elif best["name_sim"] >= 0.6 and best["valid_type"]:
            # Plausible match but not a slam-dunk — flag for review
            decision = "REVIEW"
            reason = f"Best predecessor name match is {best['name_sim']:.2f} (borderline); manual check"
            target_qid = best["qid"]
            target_label = best["label"]
        else:
            decision = "REVIEW"
            reason = f"No predecessor with strong name match (best sim={best['name_sim']:.2f}, valid_type={best['valid_type']})"
            target_qid = best["qid"]
            target_label = best["label"]

        decisions.append({
            "csd_id": csd_id,
            "csd_name": csd_name,
            "modern_qid": modern_qid,
            "modern_label": modern_label,
            "modern_inception": modern_inception,
            "n_predecessors": n_predecessors,
            "best_predecessor_qid": best["qid"] if best else "",
            "best_predecessor_label": best["label"] if best else "",
            "best_predecessor_inception": best["min_year"] if best else "",
            "best_name_similarity": f"{best['name_sim']:.2f}" if best else "",
            "best_valid_p31": best["valid_type"] if best else "",
            "decision": decision,
            "reason": reason,
            "target_qid": target_qid,
            "target_label": target_label,
        })

    # Write output
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(decisions[0].keys()))
        w.writeheader()
        w.writerows(decisions)

    # Summary
    from collections import Counter
    by_dec = Counter(d["decision"] for d in decisions)
    print(f"\nDecisions:")
    for k, v in by_dec.most_common():
        print(f"  {k}: {v}")
    print(f"\nReport: {OUT_CSV}")

    print("\nSWITCH cases (sample):")
    for d in [d for d in decisions if d["decision"] == "SWITCH"][:15]:
        print(f"  {d['csd_id']} \"{d['csd_name']}\" : {d['modern_qid']} \"{d['modern_label']}\" → "
              f"{d['target_qid']} \"{d['target_label']}\" (sim={d['best_name_similarity']})")

    print("\nKEEP_MODERN cases (sample):")
    for d in [d for d in decisions if d["decision"] == "KEEP_MODERN"][:10]:
        print(f"  {d['csd_id']} \"{d['csd_name']}\" : keep {d['modern_qid']} \"{d['modern_label']}\" "
              f"(predecessor was {d['best_predecessor_qid']} sim={d['best_name_similarity']})")

    print("\nREVIEW cases (sample):")
    for d in [d for d in decisions if d["decision"] == "REVIEW"][:10]:
        print(f"  {d['csd_id']} \"{d['csd_name']}\" : {d['reason']}")


if __name__ == "__main__":
    main()
