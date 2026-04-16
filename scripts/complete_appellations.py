#!/usr/bin/env python3
"""
C2: ensure every E53_Place has at least one E33_E41_Linguistic_Appellation.

Reads the existing OCR-corrected appellations (build_e41_appellations_v2.py
output) and fills the gap for the ~97% of places that have no appellation
node. Also fixes :LABEL from E41_Appellation → E33_E41_Linguistic_Appellation
(LINCS requirement).

Does NOT require the geo environment — reads only the v2 CSV files.
"""

import csv
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
V2 = REPO / "neo4j_cidoc_crm_v2"

LABEL = "E33_E41_Linguistic_Appellation"


def load_existing_appellations() -> list[dict]:
    """Load existing OCR appellations, fixing :LABEL."""
    rows = []
    path = V2 / "e41_appellations.csv"
    with path.open() as f:
        for r in csv.DictReader(f):
            r[":LABEL"] = LABEL
            rows.append(r)
    return rows


def load_existing_p1() -> tuple[list[dict], set[str]]:
    """Load existing P1 edges; return (rows, set of :START_IDs already linked)."""
    path = V2 / "p1_is_identified_by.csv"
    rows = []
    covered: set[str] = set()
    with path.open() as f:
        for r in csv.DictReader(f):
            rows.append(r)
            covered.add(r[":START_ID"])
    return rows, covered


def load_places(filename: str) -> list[tuple[str, str]]:
    """Return [(place_id, name), ...] from an E53 CSV."""
    path = V2 / filename
    out = []
    with path.open() as f:
        for r in csv.DictReader(f):
            pid = r.get("place_id:ID", "")
            name = r.get("name", "")
            out.append((pid, name))
    return out


def main():
    existing_apps = load_existing_appellations()
    existing_p1, covered = load_existing_p1()
    print(f"Existing appellations: {len(existing_apps)} ({len(covered)} place_ids already linked)")

    csd_places = load_places("e53_place_csd.csv")
    cd_places = load_places("e53_place_cd.csv")
    all_places = csd_places + cd_places
    print(f"Total places: {len(all_places)} ({len(csd_places)} CSD + {len(cd_places)} CD)")

    new_apps = []
    new_p1 = []
    for place_id, name in all_places:
        if place_id in covered:
            continue
        if not name:
            continue
        app_id = f"APP_{place_id}_NAME"
        new_apps.append({
            "appellation_id:ID": app_id,
            ":LABEL": LABEL,
            "name": name,
            "type": "name",
            "tcpuid": place_id.replace("PLACE_", "").replace("CD_", ""),
            "notes": "",
            "year": "",
        })
        new_p1.append({
            ":START_ID": place_id,
            ":END_ID": app_id,
            ":TYPE": "P1_is_identified_by",
        })

    print(f"New appellations generated: {len(new_apps)}")
    print(f"Already covered (OCR canonical): {len(covered)}")
    print(f"Total after merge: {len(existing_apps) + len(new_apps)}")

    all_apps = existing_apps + new_apps
    all_p1 = existing_p1 + new_p1

    fieldnames_app = ["appellation_id:ID", ":LABEL", "name", "type", "tcpuid", "notes", "year"]
    with (V2 / "e41_appellations.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames_app)
        w.writeheader()
        w.writerows(all_apps)

    fieldnames_p1 = [":START_ID", ":END_ID", ":TYPE"]
    with (V2 / "p1_is_identified_by.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames_p1)
        w.writeheader()
        w.writerows(all_p1)

    print(f"\nWrote {len(all_apps)} → e41_appellations.csv")
    print(f"Wrote {len(all_p1)} → p1_is_identified_by.csv")
    print(f"\n:LABEL updated to '{LABEL}' for all appellations")


if __name__ == "__main__":
    main()
