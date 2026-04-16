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
@prefix geo: <{GEO_NS}> .
@prefix wikidata: <{WD_NS}> .
@prefix base: <{BASE}> .

"""

YEARS = [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921]


def escape_turtle(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")


def uri(neo4j_id: str, uri_map: dict | None = None) -> str:
    if uri_map and neo4j_id in uri_map:
        u = uri_map[neo4j_id]
        if u.startswith("http://www.wikidata.org/"):
            return f"<{u}>"
        return f"<{u}>"
    return f"base:{neo4j_id}"


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
        prov_p4_ts = []
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
                (prov_p4_ts, "p4_has_time_span_{}.csv"),
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

        # CD presences (for P10 targets)
        cd_presence_ids = {r[":END_ID"] for r in prov_p10}
        cd_presences = []
        for year in YEARS:
            for r in read_csv(CRM / f"e93_presence_cd_{year}.csv"):
                if r.get("presence_id:ID", "") in cd_presence_ids:
                    cd_presences.append(r)

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
                s = f"base:{r['period_id:ID']}"
                triple(s, "a", "crm:E4_Period")
                triple(s, "rdfs:label", lang(r["label"]))

            f.write("\n# E52_Time-Span nodes\n")
            for r in e52_timespans:
                s = f"base:{r['timespan_id:ID']}"
                triple(s, "a", "crm:E52_Time-Span")
                triple(s, "rdfs:label", lang(r["label"]))
                triple(s, "crm:P82a_begin_of_the_begin", lit(r["begin_of_begin"], "xsd:date"))
                triple(s, "crm:P82b_end_of_the_end", lit(r["end_of_end"], "xsd:date"))

            f.write("\n# P4: E4_Period → E52_Time-Span\n")
            for r in p4_period_ts:
                triple(f"base:{r[':START_ID']}", "crm:P4_has_time-span", f"base:{r[':END_ID']}")

            f.write("\n# E58_Measurement_Unit nodes\n")
            emitted_units = set()
            for r in e58_units_spatial + e58_units_census:
                uid = r["unit_id:ID"]
                if uid in emitted_units:
                    continue
                emitted_units.add(uid)
                s = f"base:{uid}"
                triple(s, "a", "crm:E58_Measurement_Unit")
                triple(s, "rdfs:label", lang(r["label"]))
                if r.get("wikidata_qid"):
                    triple(s, "owl:sameAs", f"wikidata:{r['wikidata_qid']}")

            f.write("\n# E55_Type nodes (variable types)\n")
            for r in e55_types:
                s = f"base:{r['type_id:ID']}"
                triple(s, "a", "crm:E55_Type")
                triple(s, "rdfs:label", lang(r.get("label", r["type_id:ID"])))

            f.write("\n# E73_Information_Object (provenance)\n")
            for r in e73_objects:
                s = f"base:{r['info_object_id:ID']}"
                triple(s, "a", "crm:E73_Information_Object")
                triple(s, "rdfs:label", lang(r["label"]))
                if r.get("access_uri"):
                    triple(s, "crm:P1_is_identified_by", lit(r["access_uri"]))

            # --- Province-specific nodes ---
            f.write(f"\n# E53_Place nodes ({prov})\n")
            for r in csd_places + cd_places:
                pid = r["place_id:ID"]
                s = uri(pid, uri_map)
                triple(s, "a", "crm:E53_Place")
                triple(s, "rdfs:label", lang(r["name"]))
                # owl:sameAs for Wikidata-grounded places
                u = uri_map.get(pid, "")
                if u.startswith(WD_NS):
                    pass  # URI itself IS Wikidata; no sameAs needed

            f.write(f"\n# E33_E41_Linguistic_Appellation ({prov})\n")
            for r in prov_apps:
                s = f"base:{r['appellation_id:ID']}"
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
                s = uri(r[":START_ID"], uri_map) if r[":START_ID"] in place_ids else f"base:{r[':START_ID']}"
                triple(s, "crm:P1_is_identified_by", f"base:{r[':END_ID']}")

            f.write(f"\n# E93_Presence ({prov} CSDs)\n")
            for r in prov_presences:
                s = f"base:{r['presence_id:ID']}"
                triple(s, "a", "crm:E93_Presence")
                name = r.get("name", r["presence_id:ID"])
                year_m = re.search(r"_(\d{4})$", r["presence_id:ID"])
                yr = year_m.group(1) if year_m else ""
                triple(s, "rdfs:label", lang(f"{name} ({yr})"))

            f.write(f"\n# E93_Presence ({prov} CDs)\n")
            for r in cd_presences:
                s = f"base:{r['presence_id:ID']}"
                triple(s, "a", "crm:E93_Presence")
                triple(s, "rdfs:label", lang(r.get("label", r["presence_id:ID"])))

            f.write(f"\n# P166: E93_Presence → E53_Place\n")
            for r in prov_p166:
                triple(f"base:{r[':START_ID']}", "crm:P166i_was_a_presence_of",
                       uri(r[":END_ID"], uri_map))

            f.write(f"\n# P164: E93_Presence → E4_Period\n")
            for r in prov_p164:
                triple(f"base:{r[':START_ID']}", "crm:P164_is_temporally_specified_by",
                       f"base:{r[':END_ID']}")

            f.write(f"\n# P4: E93_Presence → E52_Time-Span\n")
            for r in prov_p4_ts:
                triple(f"base:{r[':START_ID']}", "crm:P4_has_time-span", f"base:{r[':END_ID']}")

            f.write(f"\n# E94_Space_Primitive + P161 + P168 WKT\n")
            for r in all_space:
                sid = r["space_id:ID"]
                s = f"base:{sid}"
                lat = r.get("latitude", r.get("lat", ""))
                lon = r.get("longitude", r.get("lon", ""))
                if lat and lon:
                    triple(s, "a", "crm:E94_Space_Primitive")
                    wkt = f"POINT({lon} {lat})"
                    triple(s, "crm:P168_place_is_defined_by",
                           f'"{wkt}"^^geo:wktLiteral')

            f.write(f"\n# P161: E93_Presence → E94_Space_Primitive\n")
            for r in prov_p161:
                triple(f"base:{r[':START_ID']}", "crm:P161_has_spatial_projection",
                       f"base:{r[':END_ID']}")

            f.write(f"\n# P10: CSD presence → CD presence\n")
            for r in prov_p10:
                triple(f"base:{r[':START_ID']}", "crm:P10_falls_within", f"base:{r[':END_ID']}")

            f.write(f"\n# P122: E93 borders + E16/E54/E58 reification\n")
            for r in prov_p122:
                triple(f"base:{r[':START_ID']}", "crm:P122_borders_with", f"base:{r[':END_ID']}")
            for r in prov_e16_border:
                s = f"base:{r['measurement_id:ID']}"
                triple(s, "a", "crm:E16_Measurement")
                triple(s, "rdfs:label", lang(f"Border length measurement ({r.get('year:int', '')})"))
            for r in prov_e54_border:
                s = f"base:{r['dimension_id:ID']}"
                triple(s, "a", "crm:E54_Dimension")
                triple(s, "crm:P90_has_value", lit(r["value:float"], "xsd:decimal"))
            for r in prov_p39_border:
                triple(f"base:{r[':START_ID']}", "crm:P39_measured", f"base:{r[':END_ID']}")
            for r in prov_p40_border:
                triple(f"base:{r[':START_ID']}", "crm:P40_observed_dimension", f"base:{r[':END_ID']}")
            for r in prov_p91_border:
                triple(f"base:{r[':START_ID']}", "crm:P91_has_unit", f"base:{r[':END_ID']}")

            # --- Census observations ---
            f.write(f"\n# E16_Measurement (census observations)\n")
            for r in prov_e16_obs:
                s = f"base:{r['measurement_id:ID']}"
                triple(s, "a", "crm:E16_Measurement")
                triple(s, "rdfs:label", lang(r["label"]))

            f.write(f"\n# E54_Dimension (census values)\n")
            for r in prov_e54_obs:
                s = f"base:{r['dimension_id:ID']}"
                triple(s, "a", "crm:E54_Dimension")
                v = r.get("value:float", "")
                vs = r.get("value_string", "")
                if v:
                    triple(s, "crm:P90_has_value", lit(v, "xsd:decimal"))
                elif vs:
                    triple(s, "crm:P90_has_value", lit(vs))

            f.write(f"\n# Census observation relationships\n")
            for r in prov_p39_obs:
                triple(f"base:{r[':START_ID']}", "crm:P39_measured", f"base:{r[':END_ID']}")
            for r in prov_p40_obs:
                triple(f"base:{r[':START_ID']}", "crm:P40_observed_dimension", f"base:{r[':END_ID']}")
            for r in prov_p91_obs:
                triple(f"base:{r[':START_ID']}", "crm:P91_has_unit", f"base:{r[':END_ID']}")
            for r in prov_p2_obs:
                triple(f"base:{r[':START_ID']}", "crm:P2_has_type", f"base:{r[':END_ID']}")
            for r in prov_p4_meas_ts:
                triple(f"base:{r[':START_ID']}", "crm:P4_has_time-span", f"base:{r[':END_ID']}")
            for r in prov_p70_obs:
                triple(f"base:{r[':START_ID']}", "crm:P70_documents", f"base:{r[':END_ID']}")

        size_mb = ttl_path.stat().st_size / (1024 * 1024)
        print(f"\n  Wrote {triple_count:,} triples → {ttl_path.name} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
