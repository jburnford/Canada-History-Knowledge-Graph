#!/usr/bin/env python3
"""
Export CIDOC-CRM census data as RDF/Turtle, filtered by province.

Reads the v2 Neo4j CSV files from neo4j_cidoc_crm_v2/ and neo4j_census_v2/,
applies a province filter, and writes one .ttl file per province.

Usage:
    python3 scripts/export_rdf.py --provinces ON,SK
"""

import argparse
import csv
import re
import sys
from pathlib import Path
from collections import defaultdict

REPO = Path(__file__).resolve().parents[1]
CRM = REPO / "neo4j_cidoc_crm_v2"
OBS = REPO / "neo4j_census_v2"
OUT = REPO / "rdf_export"

BASE = "http://temp.lincsproject.ca/census/"
CRM_NS = "http://www.cidoc-crm.org/cidoc-crm/"
WD_NS = "http://www.wikidata.org/entity/"
GEO_NS = "http://www.opengis.net/ont/geosparql#"

PREFIXES = f"""\
@prefix crm: <{CRM_NS}> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix geo: <{GEO_NS}> .
@prefix wikidata: <{WD_NS}> .
@prefix base: <{BASE}> .

"""

YEARS = [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921]

# Province containment for P89_falls_within. QIDs verified against Wikidata
# via the MCP vector search (2026-08-10); do not edit from memory.
PROVINCES = {
    "AB": ("Alberta", "Q1951"),
    "BC": ("British Columbia", "Q1973"),
    "MB": ("Manitoba", "Q1948"),
    "NB": ("New Brunswick", "Q1965"),
    "NL": ("Newfoundland and Labrador", "Q2003"),
    "NS": ("Nova Scotia", "Q1952"),
    "NT": ("Northwest Territories", "Q2007"),
    "ON": ("Ontario", "Q1904"),
    "PE": ("Prince Edward Island", "Q1978"),
    "QC": ("Quebec", "Q176"),
    "SK": ("Saskatchewan", "Q1989"),
    "YT": ("Yukon", "Q2009"),
}
CANADA_QID = "Q16"

# Human labels for the SKOS concept scheme of census variable categories.
CATEGORY_LABELS = {
    "AGE": "Age structure",
    "AGR": "Agriculture",
    "BLD": "Buildings and dwellings",
    "DTH": "Deaths",
    "ETH": "Ethnic origin",
    "FSH": "Fisheries",
    "MFG": "Manufacturing",
    "POP": "Population",
    "REL": "Religion",
}

# BORDER_MEAS_<tcpuidA>_<tcpuidB>_<year>; tcpuids are 2 letters + 6
# alphanumerics (Ungava district ids like QC20N999 mix letters in).
TCPUID_PAT = r"[A-Z]{2}[0-9A-Z]{6}"
BORDER_MEAS_RE = re.compile(
    rf"^BORDER_MEAS_({TCPUID_PAT})_({TCPUID_PAT})_(\d{{4}})$")


def escape_turtle(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")


# Characters safe in a Turtle prefixed-name local part (conservative subset).
_SAFE_LOCAL_RE = re.compile(r"[^A-Za-z0-9_.\-]")


def safe_local(neo4j_id: str) -> str:
    """Percent-encode characters that aren't valid in a Turtle prefixed local name.

    Encodes the UTF-8 octets of each disallowed character (RFC 3987), so
    multi-byte characters like é (%C3%A9) and — (%E2%80%94) round-trip as
    IRIs instead of collapsing to Latin-1 or spilling past the percent token."""
    return _SAFE_LOCAL_RE.sub(
        lambda m: "".join(f"%{byte:02X}" for byte in m.group().encode("utf-8")),
        neo4j_id)


def b(neo4j_id: str) -> str:
    """Emit a base:-prefixed URI with safe local name encoding."""
    return f"base:{safe_local(neo4j_id)}"


def uri(neo4j_id: str, uri_map: dict | None = None) -> str:
    if uri_map and neo4j_id in uri_map:
        u = uri_map[neo4j_id]
        return f"<{u}>"
    return b(neo4j_id)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def read_csv_filtered(path: Path, field: str, allowed: set) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open() as f:
        for r in csv.DictReader(f):
            if r.get(field, "") in allowed:
                out.append(r)
    return out


def main():
    parser = argparse.ArgumentParser(description="Export CIDOC-CRM census RDF/Turtle")
    parser.add_argument("--provinces", required=True, help="Comma-separated province codes")
    parser.add_argument("--out", default=str(OUT), help="Output directory")
    args = parser.parse_args()

    provinces = [p.strip() for p in args.provinces.split(",")]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Load URI mapping ---
    uri_map = {}
    for r in read_csv(CRM / "e53_place_uri.csv"):
        uri_map[r["place_id:ID"]] = r["uri"]

    # --- Global place-name map (all provinces; used for human labels) ---
    place_name = {}
    for r in read_csv(CRM / "e53_place_csd.csv") + read_csv(CRM / "e53_place_cd.csv"):
        place_name[r["place_id:ID"]] = r["name"]

    # --- Load shared entities (emitted once per file) ---
    e4_periods = read_csv(CRM / "e4_period.csv")
    e52_timespans = read_csv(CRM / "e52_timespans.csv")
    e58_units_spatial = read_csv(CRM / "e58_measurement_unit.csv")
    e58_units_census = read_csv(OBS / "e58_measurement_units.csv")
    e55_types = read_csv(OBS / "e55_variable_types.csv")
    e73_objects = read_csv(OBS / "e73_information_objects.csv")
    p4_period_ts = read_csv(CRM / "p4_period_timespan.csv")

    for prov in provinces:
        print(f"\n{'='*60}")
        print(f"Exporting {prov}")
        print(f"{'='*60}")

        # --- Filter places ---
        csd_places = [r for r in read_csv(CRM / "e53_place_csd.csv") if r["province"] == prov]
        cd_places = [r for r in read_csv(CRM / "e53_place_cd.csv") if r["province"] == prov]
        place_ids = {r["place_id:ID"] for r in csd_places + cd_places}
        print(f"  Places: {len(csd_places)} CSD + {len(cd_places)} CD = {len(place_ids)}")

        # --- Filter appellations ---
        all_p1 = read_csv(CRM / "p1_is_identified_by.csv")
        prov_p1 = [r for r in all_p1 if r[":START_ID"] in place_ids]
        app_ids = {r[":END_ID"] for r in prov_p1}
        # Also include presence-level P1 (OCR variants link from presence IDs)
        prov_prefix = prov
        prov_p1_presence = [r for r in all_p1 if r[":START_ID"].startswith(prov_prefix) and r[":END_ID"].startswith("APP_")]
        app_ids.update(r[":END_ID"] for r in prov_p1_presence)
        prov_p1.extend(prov_p1_presence)

        all_apps = read_csv(CRM / "e41_appellations.csv")
        prov_apps = [r for r in all_apps if r["appellation_id:ID"] in app_ids]
        print(f"  Appellations: {len(prov_apps)}")

        # --- Filter presences + spatial + temporal per year ---
        prov_presences = []
        prov_space = []
        prov_p166 = []
        prov_p164 = []
        prov_p10_period = []
        prov_p161 = []
        prov_p122 = []
        prov_p10 = []
        prov_e16_border = []
        prov_e54_border = []
        prov_p39_border = []
        prov_p40_border = []
        prov_p91_border = []

        for year in YEARS:
            yr_presences = read_csv_filtered(CRM / f"e93_presence_{year}.csv", "presence_id:ID", set())
            # Filter by province prefix on the presence_id
            yr_presences = [r for r in read_csv(CRM / f"e93_presence_{year}.csv")
                           if r["presence_id:ID"][:2] == prov or r["presence_id:ID"][:len(prov)] == prov]
            presence_ids_yr = {r["presence_id:ID"] for r in yr_presences}
            prov_presences.extend(yr_presences)

            for src, fname_pat in [
                (prov_p166, "p166_was_presence_of_{}.csv"),
                (prov_p164, "p164_temporally_specified_by_{}.csv"),
                (prov_p10_period, "p10_presence_within_period_{}.csv"),
                (prov_p161, "p161_spatial_projection_{}.csv"),
            ]:
                for r in read_csv(CRM / fname_pat.format(year)):
                    if r[":START_ID"] in presence_ids_yr:
                        src.append(r)

            # P10 (CSD presence → CD presence)
            for r in read_csv(CRM / f"p10_csd_within_cd_presence_{year}.csv"):
                if r[":START_ID"] in presence_ids_yr:
                    prov_p10.append(r)

            # P122 borders + reification
            for r in read_csv(CRM / f"p122_borders_with_{year}.csv"):
                if r[":START_ID"] in presence_ids_yr or r[":END_ID"] in presence_ids_yr:
                    prov_p122.append(r)
            border_meas_ids = set()
            for r in read_csv(CRM / f"e16_border_measurement_{year}.csv"):
                mid = r["measurement_id:ID"]
                # Include if either CSD in the border is in our province
                parts = mid.replace("BORDER_MEAS_", "").rsplit(f"_{year}", 1)[0]
                if parts.startswith(prov):
                    prov_e16_border.append(r)
                    border_meas_ids.add(mid)
            for r in read_csv(CRM / f"e54_border_dimension_{year}.csv"):
                did = r["dimension_id:ID"]
                mid = did.replace("BORDER_DIM_", "BORDER_MEAS_")
                if mid in border_meas_ids:
                    prov_e54_border.append(r)
            for r in read_csv(CRM / f"p39_measured_border_{year}.csv"):
                if r[":START_ID"] in border_meas_ids:
                    prov_p39_border.append(r)
            for r in read_csv(CRM / f"p40_observed_dimension_border_{year}.csv"):
                if r[":START_ID"] in border_meas_ids:
                    prov_p40_border.append(r)
            for r in read_csv(CRM / f"p91_has_unit_border_{year}.csv"):
                if r[":START_ID"].replace("BORDER_DIM_", "BORDER_MEAS_") in border_meas_ids:
                    prov_p91_border.append(r)

        print(f"  Presences: {len(prov_presences)}")
        print(f"  P122 borders: {len(prov_p122)}")

        # E94 space primitives: collect their IDs via the P161 :END_ID column
        space_ids = {r[":END_ID"] for r in prov_p161}
        all_space = []
        for year in YEARS:
            for r in read_csv(CRM / f"e94_space_primitive_{year}.csv"):
                if r["space_id:ID"] in space_ids:
                    all_space.append(r)

        # CD presences: this province's CDs plus any CD referenced as a P10
        # target by a CSD presence in this file.
        cd_presence_ids = {r[":END_ID"] for r in prov_p10}
        cd_presences = []
        cd_prefix = f"CD_{prov}_"
        for year in YEARS:
            for r in read_csv(CRM / f"e93_presence_cd_{year}.csv"):
                if (r.get("presence_id:ID", "") in cd_presence_ids
                        or r.get("cd_id", "").startswith(cd_prefix)):
                    cd_presences.append(r)
        cd_presence_ids.update(r["presence_id:ID"] for r in cd_presences)

        # CD-level relationship rows (previously never exported: the CD
        # presences were orphaned E93 nodes with no P166/P164/geometry).
        cd_p166, cd_p164, cd_p10_period, cd_p161 = [], [], [], []
        for year in YEARS:
            for src, fname_pat in [
                (cd_p166, "p166_was_presence_of_cd_{}.csv"),
                (cd_p164, "p164_temporally_specified_by_cd_{}.csv"),
                (cd_p10_period, "p10_cd_presence_within_period_{}.csv"),
                (cd_p161, "p161_spatial_projection_cd_{}.csv"),
            ]:
                for r in read_csv(CRM / fname_pat.format(year)):
                    if r[":START_ID"] in cd_presence_ids:
                        src.append(r)
        cd_space_ids = {r[":END_ID"] for r in cd_p161}
        cd_space = []
        for year in YEARS:
            for r in read_csv(CRM / f"e94_space_primitive_cd_{year}.csv"):
                if r["space_id:ID"] in cd_space_ids:
                    cd_space.append(r)

        # P132 spatiotemporal overlaps (chain continuity between year pairs)
        all_presence_ids = {r["presence_id:ID"] for r in prov_presences} | cd_presence_ids
        prov_p132 = []
        for fname in ["p132_spatiotemporally_overlaps_with_csd.csv",
                      "p132_spatiotemporally_overlaps_with_cd.csv"]:
            for r in read_csv(CRM / fname):
                if r[":START_ID"] in all_presence_ids and r[":END_ID"] in all_presence_ids:
                    prov_p132.append(r)

        # presence_id → place_id (for labels), presence_id → space_id (for
        # relocating P122 onto the year-specific spatial-projection places).
        presence_place = {r[":START_ID"]: r[":END_ID"] for r in prov_p166 + cd_p166}
        pres2space = {r[":START_ID"]: r[":END_ID"] for r in prov_p161 + cd_p161}

        def presence_name(pid: str) -> str:
            """Human name for a presence, falling back to its raw id."""
            name = place_name.get(presence_place.get(pid, ""), "")
            if not name:
                # Cross-province neighbour or unmapped: strip trailing year.
                name = re.sub(r"_\d{4}$", "", pid)
            if name == "NO DATA":
                name = "No-data area"
            return name

        # --- Census observations ---
        prov_e16_obs = []
        prov_e54_obs = []
        prov_p39_obs = []
        prov_p40_obs = []
        prov_p91_obs = []
        prov_p2_obs = []
        prov_p4_meas_ts = []
        prov_p70_obs = []

        for year in YEARS:
            meas_ids = set()
            dim_ids = set()
            for r in read_csv(OBS / f"e16_measurements_{year}.csv"):
                mid = r["measurement_id:ID"]
                if mid[5:5+len(prov)] == prov:
                    prov_e16_obs.append(r)
                    meas_ids.add(mid)
            for r in read_csv(OBS / f"e54_dimensions_{year}.csv"):
                did = r["dimension_id:ID"]
                if did[4:4+len(prov)] == prov:
                    prov_e54_obs.append(r)
                    dim_ids.add(did)
            for r in read_csv(OBS / f"p39_measured_{year}.csv"):
                if r[":START_ID"] in meas_ids:
                    prov_p39_obs.append(r)
            for r in read_csv(OBS / f"p40_observed_dimension_{year}.csv"):
                if r[":START_ID"] in meas_ids:
                    prov_p40_obs.append(r)
            for r in read_csv(OBS / f"p91_has_unit_{year}.csv"):
                if r[":START_ID"] in dim_ids:
                    prov_p91_obs.append(r)
            for r in read_csv(OBS / f"p2_has_type_{year}.csv"):
                if r[":START_ID"] in meas_ids:
                    prov_p2_obs.append(r)
            for r in read_csv(OBS / f"p4_measurement_timespan_{year}.csv"):
                if r[":START_ID"] in meas_ids:
                    prov_p4_meas_ts.append(r)
            for r in read_csv(OBS / f"p70_documents_{year}.csv"):
                if r[":END_ID"] in meas_ids:
                    prov_p70_obs.append(r)

        print(f"  Observations: {len(prov_e16_obs):,} measurements")

        # --- Write Turtle ---
        ttl_path = out_dir / f"{prov.lower()}_census_1851_1921.ttl"
        triple_count = 0

        with ttl_path.open("w") as f:
            f.write(PREFIXES)

            def triple(s, p, o):
                nonlocal triple_count
                f.write(f"{s} {p} {o} .\n")
                triple_count += 1

            def lit(val, dt="xsd:string"):
                return f'"{escape_turtle(str(val))}"^^{dt}'

            def lang(val, lang="en"):
                return f'"{escape_turtle(str(val))}"@{lang}'

            # --- Shared nodes ---
            f.write("\n# E4_Period nodes\n")
            for r in e4_periods:
                s = b(r['period_id:ID'])
                triple(s, "a", "crm:E4_Period")
                triple(s, "rdfs:label", lang(r["label"]))

            f.write("\n# E52_Time-Span nodes\n")
            for r in e52_timespans:
                s = b(r['timespan_id:ID'])
                triple(s, "a", "crm:E52_Time-Span")
                triple(s, "rdfs:label", lang(r["label"]))
                triple(s, "crm:P82a_begin_of_the_begin", lit(r["begin_of_begin"], "xsd:date"))
                triple(s, "crm:P82b_end_of_the_end", lit(r["end_of_end"], "xsd:date"))

            f.write("\n# P4: E4_Period → E52_Time-Span\n")
            for r in p4_period_ts:
                triple(b(r[':START_ID']), "crm:P4_has_time-span", b(r[':END_ID']))

            f.write("\n# E58_Measurement_Unit nodes\n")
            emitted_units = set()
            for r in e58_units_spatial + e58_units_census:
                uid = r["unit_id:ID"]
                if uid in emitted_units:
                    continue
                emitted_units.add(uid)
                s = b(uid)
                triple(s, "a", "crm:E58_Measurement_Unit")
                triple(s, "rdfs:label", lang(r["label"]))
                if r.get("wikidata_qid"):
                    triple(s, "owl:sameAs", f"wikidata:{r['wikidata_qid']}")

            f.write("\n# SKOS concept scheme for census variable types\n")
            scheme = "base:VOCAB_CENSUS_VARIABLES"
            triple(scheme, "a", "skos:ConceptScheme")
            triple(scheme, "rdfs:label",
                   lang("HGIS Canada census variables 1851–1921"))
            seen_cats = set()
            for r in e55_types:
                cat = r.get("category", "")
                if not cat or cat in seen_cats:
                    continue
                seen_cats.add(cat)
                cs = b(f"VARCAT_{cat}")
                cat_label = CATEGORY_LABELS.get(cat, cat)
                triple(cs, "a", "crm:E55_Type")
                triple(cs, "a", "skos:Concept")
                triple(cs, "rdfs:label", lang(cat_label))
                triple(cs, "skos:prefLabel", lang(cat_label))
                triple(cs, "skos:topConceptOf", scheme)
                triple(cs, "skos:inScheme", scheme)

            f.write("\n# E55_Type nodes (variable types)\n")
            for r in e55_types:
                s = b(r['type_id:ID'])
                label = r.get("label", r["type_id:ID"])
                triple(s, "a", "crm:E55_Type")
                triple(s, "a", "skos:Concept")
                triple(s, "rdfs:label", lang(label))
                triple(s, "skos:prefLabel", lang(label))
                triple(s, "skos:inScheme", scheme)
                cat = r.get("category", "")
                if cat:
                    triple(s, "skos:broader", b(f"VARCAT_{cat}"))
                    triple(s, "crm:P127_has_broader_term", b(f"VARCAT_{cat}"))

            f.write("\n# Utility E55 types\n")
            triple("base:TYPE_SHARED_BORDER_LENGTH", "a", "crm:E55_Type")
            triple("base:TYPE_SHARED_BORDER_LENGTH", "rdfs:label",
                   lang("shared border length"))
            triple("base:TYPE_NO_DATA_UNIT", "a", "crm:E55_Type")
            triple("base:TYPE_NO_DATA_UNIT", "rdfs:label",
                   lang("unenumerated / no-data census unit"))

            f.write("\n# E73_Information_Object (provenance)\n")
            for r in e73_objects:
                s = b(r['info_object_id:ID'])
                # Dual-typed: P70_documents (used below) has domain
                # E31_Document; E31 ⊂ E73, so a bare E73 typing put the
                # subject outside P70's domain.
                triple(s, "a", "crm:E31_Document")
                triple(s, "a", "crm:E73_Information_Object")
                triple(s, "rdfs:label", lang(r["label"]))
                if r.get("access_uri"):
                    # P1's range is E41_Appellation — a bare literal violated
                    # it. Route through an E42_Identifier node.
                    ident = f"{r['info_object_id:ID']}_ACCESS_URI"
                    triple(s, "crm:P1_is_identified_by", b(ident))
                    triple(b(ident), "a", "crm:E42_Identifier")
                    triple(b(ident), "rdfs:label",
                           lang(f"Access URI for {r['label']}"))
                    triple(b(ident), "crm:P190_has_symbolic_content",
                           lit(r["access_uri"]))

            # --- Province-specific nodes ---
            f.write(f"\n# E53_Place: province + country (P89 hierarchy)\n")
            prov_label, prov_qid = PROVINCES.get(prov, (prov, ""))
            prov_node = b(f"PROV_{prov}")
            triple(prov_node, "a", "crm:E53_Place")
            triple(prov_node, "rdfs:label", lang(prov_label))
            if prov_qid:
                triple(prov_node, "owl:sameAs", f"wikidata:{prov_qid}")
            triple("base:PLACE_CANADA", "a", "crm:E53_Place")
            triple("base:PLACE_CANADA", "rdfs:label", lang("Canada"))
            triple("base:PLACE_CANADA", "owl:sameAs", f"wikidata:{CANADA_QID}")
            triple(prov_node, "crm:P89_falls_within", "base:PLACE_CANADA")

            f.write(f"\n# E53_Place nodes ({prov})\n")
            for r in csd_places + cd_places:
                pid = r["place_id:ID"]
                s = uri(pid, uri_map)
                triple(s, "a", "crm:E53_Place")
                if r["name"] == "NO DATA":
                    # Placeholder polygons for unenumerated areas: keep the
                    # node (borders reference it) but label and type it
                    # honestly instead of publishing "NO DATA" as a name.
                    triple(s, "rdfs:label", lang(f"No-data area ({pid})"))
                    triple(s, "crm:P2_has_type", "base:TYPE_NO_DATA_UNIT")
                else:
                    triple(s, "rdfs:label", lang(r["name"]))
                triple(s, "crm:P89_falls_within", prov_node)
                # Grounded places use the Wikidata URI as their node URI, so
                # no owl:sameAs is needed for them.

            f.write(f"\n# E33_E41_Linguistic_Appellation ({prov})\n")
            for r in prov_apps:
                s = b(r['appellation_id:ID'])
                triple(s, "a", "crm:E33_E41_Linguistic_Appellation")
                triple(s, "rdfs:label", lang(f"Name: {r['name']}"))
                triple(s, "crm:P190_has_symbolic_content", lit(r["name"]))

            f.write(f"\n# P1_is_identified_by ({prov})\n")
            seen_p1 = set()
            for r in prov_p1:
                key = (r[":START_ID"], r[":END_ID"])
                if key in seen_p1:
                    continue
                seen_p1.add(key)
                s = uri(r[":START_ID"], uri_map) if r[":START_ID"] in place_ids else b(r[':START_ID'])
                triple(s, "crm:P1_is_identified_by", b(r[':END_ID']))

            f.write(f"\n# E93_Presence ({prov} CSDs)\n")
            for r in prov_presences:
                pid = r["presence_id:ID"]
                s = b(pid)
                triple(s, "a", "crm:E93_Presence")
                yr = r.get("census_year:int", "") or pid[-4:]
                triple(s, "rdfs:label",
                       lang(f"{presence_name(pid)} ({yr} presence)"))

            f.write(f"\n# E93_Presence ({prov} CDs)\n")
            for r in cd_presences:
                pid = r["presence_id:ID"]
                s = b(pid)
                triple(s, "a", "crm:E93_Presence")
                yr = r.get("census_year:int", "") or pid[-4:]
                triple(s, "rdfs:label",
                       lang(f"{presence_name(pid)} (CD, {yr} presence)"))

            f.write(f"\n# P166: E93_Presence → E53_Place\n")
            for r in prov_p166 + cd_p166:
                triple(b(r[':START_ID']), "crm:P166_was_a_presence_of",
                       uri(r[":END_ID"], uri_map))

            f.write(f"\n# P164: E93_Presence → E52_Time-Span\n")
            for r in prov_p164 + cd_p164:
                triple(b(r[':START_ID']), "crm:P164_is_temporally_specified_by",
                       b(r[':END_ID']))

            f.write(f"\n# P10: E93_Presence → E4_Period (spacetime containment)\n")
            for r in prov_p10_period + cd_p10_period:
                triple(b(r[':START_ID']), "crm:P10_falls_within", b(r[':END_ID']))

            f.write(f"\n# P132: spatiotemporal overlap between successive presences\n")
            for r in prov_p132:
                triple(b(r[':START_ID']),
                       "crm:P132_spatiotemporally_overlaps_with",
                       b(r[':END_ID']))

            # Spatial projections. CIDOC-CRM v7.x: P161's range is E53_Place
            # and P168's domain is E53_Place, so the projection node is an
            # E53 (year-specific spatial extent) carrying the WKT literal —
            # not an E94 individual (the earlier export used E94 off-domain).
            f.write(f"\n# E53 spatial-projection places + P168 WKT\n")
            space2pres = {r[":END_ID"]: r[":START_ID"]
                          for r in prov_p161 + cd_p161}
            for r in all_space + cd_space:
                sid = r["space_id:ID"]
                s = b(sid)
                lat = r.get("latitude:float", r.get("latitude", r.get("lat", "")))
                lon = r.get("longitude:float", r.get("longitude", r.get("lon", "")))
                if lat and lon:
                    triple(s, "a", "crm:E53_Place")
                    pres = space2pres.get(sid, "")
                    if pres:
                        triple(s, "rdfs:label",
                               lang(f"Spatial extent of {presence_name(pres)}"
                                    f" ({pres[-4:]}), centroid"))
                    else:
                        triple(s, "rdfs:label", lang(f"Spatial extent {sid}"))
                    wkt = f"POINT({lon} {lat})"
                    triple(s, "crm:P168_place_is_defined_by",
                           f'"{wkt}"^^geo:wktLiteral')

            f.write(f"\n# P161: E93_Presence → E53 spatial projection\n")
            for r in prov_p161 + cd_p161:
                triple(b(r[':START_ID']), "crm:P161_has_spatial_projection",
                       b(r[':END_ID']))

            f.write(f"\n# P10: CSD presence → CD presence\n")
            for r in prov_p10:
                triple(b(r[':START_ID']), "crm:P10_falls_within", b(r[':END_ID']))

            # P122's domain/range is E53_Place, so border edges link the
            # year-specific spatial-projection places, not the E93 presences.
            # Cross-province neighbours whose P161 rows aren't loaded here
            # get their conventional "<presence>_centroid" extent id; the
            # node is declared in the neighbouring province's file.
            f.write(f"\n# P122: year-specific extents border + E16/E54/E58 reification\n")
            def extent_of(pres_id: str) -> str | None:
                sid = pres2space.get(pres_id)
                if sid:
                    return sid
                if re.match(rf"^{TCPUID_PAT}_\d{{4}}$", pres_id):
                    return f"{pres_id}_centroid"
                return None
            p122_fallback = 0
            for r in prov_p122:
                se, oe = extent_of(r[":START_ID"]), extent_of(r[":END_ID"])
                if se and oe:
                    triple(b(se), "crm:P122_borders_with", b(oe))
                else:
                    p122_fallback += 1
            if p122_fallback:
                print(f"  WARNING: {p122_fallback} P122 rows had no extent id; dropped")
            for r in prov_e16_border:
                mid = r['measurement_id:ID']
                s = b(mid)
                triple(s, "a", "crm:E16_Measurement")
                m = BORDER_MEAS_RE.match(mid)
                yr = r.get('year:int', '')
                if m:
                    pa, pb = f"{m.group(1)}_{yr}", f"{m.group(2)}_{yr}"
                    triple(s, "rdfs:label",
                           lang(f"Shared border of {presence_name(pa)} and "
                                f"{presence_name(pb)} ({yr})"))
                else:
                    triple(s, "rdfs:label",
                           lang(f"Border length measurement ({yr})"))
                triple(s, "crm:P2_has_type", "base:TYPE_SHARED_BORDER_LENGTH")
                triple(s, "crm:P4_has_time-span", b(f"TIMESPAN_{yr}"))
            for r in prov_e54_border:
                s = b(r['dimension_id:ID'])
                triple(s, "a", "crm:E54_Dimension")
                triple(s, "rdfs:label", lang(f"{r['value:float']} m"))
                triple(s, "crm:P90_has_value", lit(r["value:float"], "xsd:decimal"))
            # The CSV asserts P39 to the first participant only; a border is
            # a relation between two extents, so synthesise the second P39.
            seen_p39_border = set()
            for r in prov_p39_border:
                seen_p39_border.add((r[":START_ID"], r[":END_ID"]))
                triple(b(r[':START_ID']), "crm:P39_measured", b(r[':END_ID']))
            for r in prov_e16_border:
                mid = r['measurement_id:ID']
                m = BORDER_MEAS_RE.match(mid)
                if not m:
                    continue
                yr = m.group(3)
                for part in (f"{m.group(1)}_{yr}", f"{m.group(2)}_{yr}"):
                    if (mid, part) not in seen_p39_border:
                        seen_p39_border.add((mid, part))
                        triple(b(mid), "crm:P39_measured", b(part))
            for r in prov_p40_border:
                triple(b(r[':START_ID']), "crm:P40_observed_dimension", b(r[':END_ID']))
            for r in prov_p91_border:
                triple(b(r[':START_ID']), "crm:P91_has_unit", b(r[':END_ID']))

            # --- Census observations ---
            f.write(f"\n# E16_Measurement (census observations)\n")
            for r in prov_e16_obs:
                s = b(r['measurement_id:ID'])
                triple(s, "a", "crm:E16_Measurement")
                triple(s, "rdfs:label", lang(r["label"]))

            f.write(f"\n# E54_Dimension (census values)\n")
            for r in prov_e54_obs:
                s = b(r['dimension_id:ID'])
                triple(s, "a", "crm:E54_Dimension")
                v = r.get("value:float", "")
                vs = r.get("value_string", "")
                lbl = v or vs
                if lbl:
                    try:
                        fv = float(lbl)
                        lbl = str(int(fv)) if fv.is_integer() else lbl
                    except ValueError:
                        pass
                    triple(s, "rdfs:label", lang(lbl))
                if v:
                    # Census counts are integers; the CSV stores them with a
                    # float lexical form ("386.0"). Emit integral values as
                    # xsd:integer, true decimals (acreages etc.) as decimal.
                    try:
                        fv = float(v)
                    except ValueError:
                        fv = None
                    if fv is not None and fv.is_integer():
                        triple(s, "crm:P90_has_value",
                               lit(str(int(fv)), "xsd:integer"))
                    else:
                        triple(s, "crm:P90_has_value", lit(v, "xsd:decimal"))
                elif vs:
                    triple(s, "crm:P90_has_value", lit(vs))

            f.write(f"\n# Census observation relationships\n")
            for r in prov_p39_obs:
                triple(b(r[':START_ID']), "crm:P39_measured", b(r[':END_ID']))
            for r in prov_p40_obs:
                triple(b(r[':START_ID']), "crm:P40_observed_dimension", b(r[':END_ID']))
            for r in prov_p91_obs:
                triple(b(r[':START_ID']), "crm:P91_has_unit", b(r[':END_ID']))
            for r in prov_p2_obs:
                triple(b(r[':START_ID']), "crm:P2_has_type", b(r[':END_ID']))
            for r in prov_p4_meas_ts:
                triple(b(r[':START_ID']), "crm:P4_has_time-span", b(r[':END_ID']))
            for r in prov_p70_obs:
                triple(b(r[':START_ID']), "crm:P70_documents", b(r[':END_ID']))

        size_mb = ttl_path.stat().st_size / (1024 * 1024)
        print(f"\n  Wrote {triple_count:,} triples → {ttl_path.name} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
