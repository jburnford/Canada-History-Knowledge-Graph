#!/usr/bin/env python3
"""
Export ON 1851-1921 census pilot as CIDOC-CRM Lite RDF/Turtle (Approach B).

Keeps the E53 / E93 / E33_E41 backbone but collapses measurement reification:
  - E16/E54/E58 chains → typed datatype properties on E93_Presence
    (base:pop_total xsd:integer, base:pop_per_sq_mi xsd:decimal, base:cd_name xsd:string)
  - E52_Time-Span nodes → base:observed_on xsd:date literal on E93_Presence
  - E42_Identifier for TCP UIDs → dcterms:identifier string literal on E53_Place

Preserves external PIDs as URIs (owl:sameAs to Wikidata); never collapses
a Q-ID to a plain string.

Output: rdf_export/pilot_on_B.ttl

Usage:
    python3 scripts/export_rdf_lite.py
"""

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

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
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix base: <{BASE}> .

"""

YEARS = [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921]

# Same variable mapping as Approach C (see pilot/variables.md).
PILOT_VAR_MAP = {
    "pop_total": {
        1851: "VAR_POP_XX_N", 1861: "VAR_POP_TOT", 1871: "VAR_POP_XX_N",
        1881: "VAR_POP_TOT", 1891: "VAR_POP_TOT", 1901: "VAR_POP_TOT",
        1911: "VAR_POP_TOT", 1921: "VAR_POP_TOT",
    },
    "pop_total_m": {
        1851: "VAR_POP_MX_N", 1861: "VAR_POP_MX_N", 1871: "VAR_POP_MX_N", 1881: "VAR_POP_MX_N",
        1891: "VAR_POP_M", 1901: "VAR_POP_M", 1911: "VAR_POP_M", 1921: "VAR_POP_M",
    },
    "pop_total_f": {
        1851: "VAR_POP_FX_N", 1861: "VAR_POP_FX_N", 1871: "VAR_POP_FX_N", 1881: "VAR_POP_FX_N",
        1891: "VAR_POP_F", 1901: "VAR_POP_F", 1911: "VAR_POP_F", 1921: "VAR_POP_F",
    },
    "pop_per_sq_mi": {1911: "VAR_POP_PER_SQ_MI"},
    "cd_name":       {1851: "VAR_CD_NAME", 1861: "VAR_CD_NAME", 1881: "VAR_CD_NAME"},
}

PILOT_COL_DATATYPE = {
    "pop_total":     "xsd:integer",
    "pop_total_m":   "xsd:integer",
    "pop_total_f":   "xsd:integer",
    "pop_per_sq_mi": "xsd:decimal",
    "cd_name":       "xsd:string",
}


def escape_turtle(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")


_SAFE_LOCAL_RE = re.compile(r"[^A-Za-z0-9_.\-]")


def safe_local(neo4j_id: str) -> str:
    # UTF-8 percent-encoding (RFC 3987): é → %C3%A9, — → %E2%80%94.
    return _SAFE_LOCAL_RE.sub(
        lambda m: "".join(f"%{byte:02X}" for byte in m.group().encode("utf-8")),
        neo4j_id)


def b(neo4j_id: str) -> str:
    return f"base:{safe_local(neo4j_id)}"


def read_csv(path):
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def read_csv_iter(path):
    if not path.exists():
        return
    with path.open() as f:
        yield from csv.DictReader(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--province", default="ON")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    prov = args.province
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Approach B (CRM Lite) pilot: province={prov}")

    # ----- URI map (Wikidata sameAs targets) -----
    uri_by_place = {}
    for r in read_csv(CRM / "e53_place_uri.csv"):
        uri_by_place[r["place_id:ID"]] = {
            "uri": r.get("uri", ""),
            "wikidata_qid": r.get("wikidata_qid", ""),
        }

    # ----- Places -----
    csd_places = [r for r in read_csv(CRM / "e53_place_csd.csv") if r["province"] == prov]
    cd_places = [r for r in read_csv(CRM / "e53_place_cd.csv") if r.get("province", "") == prov]
    place_ids = {r["place_id:ID"] for r in csd_places + cd_places}
    print(f"  Places: {len(csd_places)} CSD + {len(cd_places)} CD")

    # ----- Appellations -----
    app_ids = set()
    p1_edges = []  # (place_or_presence_id, appellation_id)
    for r in read_csv_iter(CRM / "p1_is_identified_by.csv"):
        s = r[":START_ID"]
        e = r[":END_ID"]
        if not e.startswith("APP_"):
            continue
        if s in place_ids:
            p1_edges.append((s, e))
            app_ids.add(e)
    apps = [r for r in read_csv(CRM / "e41_appellations.csv") if r["appellation_id:ID"] in app_ids]
    print(f"  Appellations: {len(apps)}  P1 edges: {len(p1_edges)}")

    # ----- Presences + P166 + P164 + centroids -----
    presences = []          # list of {year, presence_id, tcpuid, area_sqm, place_id, lat, lon}
    presence_ids = set()
    for year in YEARS:
        # presence_id -> place_id (for P166)
        p166 = {}
        for r in read_csv_iter(CRM / f"p166_was_presence_of_{year}.csv"):
            p166[r[":START_ID"]] = r[":END_ID"]
        # presence_id -> space_id (for P161)
        p161 = {}
        for r in read_csv_iter(CRM / f"p161_spatial_projection_{year}.csv"):
            p161[r[":START_ID"]] = r[":END_ID"]
        space_coords = {}
        for r in read_csv_iter(CRM / f"e94_space_primitive_{year}.csv"):
            space_coords[r["space_id:ID"]] = (
                r.get("latitude:float", "") or r.get("latitude", ""),
                r.get("longitude:float", "") or r.get("longitude", ""),
            )
        for r in read_csv_iter(CRM / f"e93_presence_{year}.csv"):
            pid = r["presence_id:ID"]
            if pid[:len(prov)] != prov:
                continue
            place_id = p166.get(pid, "")
            space_id = p161.get(pid, "")
            lat, lon = space_coords.get(space_id, ("", ""))
            presences.append({
                "year": year,
                "presence_id": pid,
                "tcpuid": r.get("csd_tcpuid", ""),
                "place_id": place_id,
                "lat": lat,
                "lon": lon,
            })
            presence_ids.add(pid)
    print(f"  Presences: {len(presences)}")

    # ----- Collapse pilot measurements into per-presence dict -----
    # {(year, presence_id): {col_name: value}}
    measures = defaultdict(dict)
    for year in YEARS:
        wanted_vars = {
            var_map[year] for var_map in PILOT_VAR_MAP.values() if year in var_map
        }
        var_to_col = {}
        for col, year_map in PILOT_VAR_MAP.items():
            if year in year_map:
                var_to_col[year_map[year]] = col
        # meas_id -> col_name
        meas_to_col = {}
        for r in read_csv_iter(OBS / f"p2_has_type_{year}.csv"):
            if r[":END_ID"] in wanted_vars:
                mid = r[":START_ID"]
                if mid[5:5+len(prov)] == prov:
                    meas_to_col[mid] = var_to_col[r[":END_ID"]]
        # meas_id -> presence_id
        meas_to_pres = {}
        for r in read_csv_iter(OBS / f"p39_measured_{year}.csv"):
            mid = r[":START_ID"]
            if mid in meas_to_col:
                meas_to_pres[mid] = r[":END_ID"]
        # meas_id -> dim_id
        meas_to_dim = {}
        for r in read_csv_iter(OBS / f"p40_observed_dimension_{year}.csv"):
            mid = r[":START_ID"]
            if mid in meas_to_col:
                meas_to_dim[mid] = r[":END_ID"]
        # dim_id -> values
        dim_vals = {}
        wanted_dims = set(meas_to_dim.values())
        for r in read_csv_iter(OBS / f"e54_dimensions_{year}.csv"):
            did = r["dimension_id:ID"]
            if did in wanted_dims:
                dim_vals[did] = (r.get("value:float", ""), r.get("value_string", ""))
        for mid, col in meas_to_col.items():
            pid = meas_to_pres.get(mid)
            if not pid:
                continue
            did = meas_to_dim.get(mid)
            if not did:
                continue
            fval, sval = dim_vals.get(did, ("", ""))
            dt = PILOT_COL_DATATYPE[col]
            if dt == "xsd:string":
                if sval:
                    measures[(year, pid)][col] = sval
            elif dt == "xsd:integer":
                if fval:
                    try:
                        measures[(year, pid)][col] = int(float(fval))
                    except ValueError:
                        pass
            elif dt == "xsd:decimal":
                if fval:
                    try:
                        measures[(year, pid)][col] = float(fval)
                    except ValueError:
                        pass

    total_measures = sum(len(v) for v in measures.values())
    print(f"  Collapsed measurement values: {total_measures}")

    # ----- P10 CD hierarchy -----
    p10_edges = []  # (csd_presence, cd_presence)
    cd_presence_ids = set()
    for year in YEARS:
        for r in read_csv_iter(CRM / f"p10_csd_within_cd_presence_{year}.csv"):
            if r[":START_ID"] in presence_ids:
                p10_edges.append((r[":START_ID"], r[":END_ID"]))
                cd_presence_ids.add(r[":END_ID"])

    # Load CD presences that appear in p10.
    cd_presence_rows = []
    for year in YEARS:
        for r in read_csv_iter(CRM / f"e93_presence_cd_{year}.csv"):
            if r["presence_id:ID"] in cd_presence_ids:
                cd_presence_rows.append((year, r["presence_id:ID"], r.get("cd_id", "")))

    # ----- P122 borders (no reification in Lite) -----
    borders = []
    for year in YEARS:
        for r in read_csv_iter(CRM / f"p122_borders_with_{year}.csv"):
            a, e = r[":START_ID"], r[":END_ID"]
            if a in presence_ids and e in presence_ids:
                borders.append((a, e))
    print(f"  P122 borders: {len(borders)}")

    # ----- P132 SAME_AS as base:continues_as -----
    continues_as = []
    for r in read_csv_iter(CRM / "p132_spatiotemporally_overlaps_with_csd.csv"):
        if r.get("overlap_type", "") != "SAME_AS":
            continue
        a, e = r[":START_ID"], r[":END_ID"]
        if a in presence_ids and e in presence_ids:
            continues_as.append((a, e))

    # ----- place_lineage (CSD SPLIT_FROM / MERGED_INTO) -----
    lineage = []  # (kind, from_pid, to_pid, year)
    for r in read_csv_iter(CRM / "place_lineage.csv"):
        lt = r.get("lineage_type", "")
        s = r[":START_ID"]; e = r[":END_ID"]
        year = r.get("change_year:int", "") or r.get("change_year", "")
        if s not in place_ids and e not in place_ids:
            continue
        if lt in ("SPLIT_FROM", "MERGED_INTO"):
            lineage.append((lt, s, e, year))

    # ----- cd_lineage (CD chain SPLIT_FROM / MERGED_INTO; Phase 1 output) -----
    cd_lineage_path = CRM / "cd_lineage.csv"
    if cd_lineage_path.exists():
        for r in read_csv_iter(cd_lineage_path):
            lt = r.get("lineage_type", "")
            s = r[":START_ID"]; e = r[":END_ID"]
            year = r.get("change_year:int", "") or r.get("change_year", "")
            if s not in place_ids and e not in place_ids:
                continue
            if lt in ("SPLIT_FROM", "MERGED_INTO"):
                lineage.append((lt, s, e, year))

    # ----- E4_Period nodes (keep) -----
    e4_rows = read_csv(CRM / "e4_period.csv")
    e52_rows = {r["timespan_id:ID"]: r for r in read_csv(CRM / "e52_timespans.csv")}
    p4_rows = read_csv(CRM / "p4_period_timespan.csv")
    period_ts = {r[":START_ID"]: r[":END_ID"] for r in p4_rows}  # period -> timespan

    # ----- Write Turtle -----
    out_path = out_dir / "pilot_on_B.ttl"
    triple_count = 0

    def lang(val, la="en"):
        return f'"{escape_turtle(str(val))}"@{la}'

    def lit(val, dt="xsd:string"):
        return f'"{escape_turtle(str(val))}"^^{dt}'

    with out_path.open("w") as f:
        f.write(PREFIXES)

        def triple(s, p, o):
            nonlocal triple_count
            f.write(f"{s} {p} {o} .\n")
            triple_count += 1

        # E4_Period (keep, but skip E52 nodes — use inline date literals instead)
        f.write("\n# E4_Period\n")
        for r in e4_rows:
            pid = r["period_id:ID"]
            s = b(pid)
            triple(s, "a", "crm:E4_Period")
            triple(s, "rdfs:label", lang(r["label"]))
            # Inline date bounds from the joined E52_Time-Span (drop E52 as a node).
            ts_id = period_ts.get(pid)
            if ts_id and ts_id in e52_rows:
                ts = e52_rows[ts_id]
                if ts.get("begin_of_begin"):
                    triple(s, "crm:P82a_begin_of_the_begin", lit(ts["begin_of_begin"], "xsd:date"))
                if ts.get("end_of_end"):
                    triple(s, "crm:P82b_end_of_the_end", lit(ts["end_of_end"], "xsd:date"))

        # E53_Place
        f.write(f"\n# E53_Place ({prov})\n")
        for r in csd_places + cd_places:
            pid = r["place_id:ID"]
            meta = uri_by_place.get(pid, {})
            # Use the assigned URI as subject (Wikidata if grounded, temp otherwise).
            subject_uri = meta.get("uri", "") or f"{BASE}{safe_local(pid)}"
            s = f"<{subject_uri}>"
            triple(s, "a", "crm:E53_Place")
            triple(s, "rdfs:label", lang(r["name"]))
            # PRESERVED PID: if URI is Wikidata, emit explicit owl:sameAs back to
            # Wikidata (redundant when URI already is Wikidata, but makes grounding
            # queryable without parsing subject IRIs).
            qid = meta.get("wikidata_qid", "")
            if qid:
                triple(s, "owl:sameAs", f"wikidata:{qid}")
            # Internal TCP place_id as dcterms:identifier (not E42).
            triple(s, "dcterms:identifier", lit(pid))

        # E33_E41 appellations
        f.write(f"\n# E33_E41_Linguistic_Appellation\n")
        for r in apps:
            aid = r["appellation_id:ID"]
            triple(b(aid), "a", "crm:E33_E41_Linguistic_Appellation")
            triple(b(aid), "crm:P190_has_symbolic_content", lit(r.get("name", "")))
            triple(b(aid), "rdfs:label", lang(r.get("name", "")))

        # P1 Place -> Appellation
        f.write(f"\n# P1_is_identified_by (Place -> Appellation)\n")
        seen = set()
        for s_id, a_id in p1_edges:
            if (s_id, a_id) in seen:
                continue
            seen.add((s_id, a_id))
            meta = uri_by_place.get(s_id, {})
            subject_uri = meta.get("uri", "") or f"{BASE}{safe_local(s_id)}"
            triple(f"<{subject_uri}>", "crm:P1_is_identified_by", b(a_id))

        # E93_Presence with flattened measurements
        f.write(f"\n# E93_Presence (Lite: inline measurements, inline dates)\n")
        period_id_by_year = {}
        for r in e4_rows:
            m = re.search(r"(\d{4})", r["period_id:ID"])
            if m:
                period_id_by_year[int(m.group(1))] = r["period_id:ID"]

        for pres in presences:
            s = b(pres["presence_id"])
            triple(s, "a", "crm:E93_Presence")
            year = pres["year"]
            triple(s, "rdfs:label", lang(f"{pres['tcpuid']} ({year})"))
            # P166 -> E53
            place_meta = uri_by_place.get(pres["place_id"], {})
            place_uri = place_meta.get("uri", "") or f"{BASE}{safe_local(pres['place_id'])}"
            triple(s, "crm:P166_was_a_presence_of", f"<{place_uri}>")
            # P10 -> E4_Period (spacetime containment; P164's range is E52,
            # and Lite has no time-span nodes)
            period_id = period_id_by_year.get(year)
            if period_id:
                triple(s, "crm:P10_falls_within", b(period_id))
            # observed_on: inline xsd:date (replaces P4 -> E52_Time-Span)
            triple(s, "base:observed_on", lit(f"{year}-06-01", "xsd:date"))
            # Inline measurement values (the core Lite collapse).
            vals = measures.get((year, pres["presence_id"]), {})
            for col, val in vals.items():
                dt = PILOT_COL_DATATYPE[col]
                triple(s, f"base:{col}", lit(val, dt))

        # E94_Space_Primitive + P168 WKT + P161 link
        f.write(f"\n# E94_Space_Primitive (centroid WKT)\n")
        for pres in presences:
            lat, lon = pres["lat"], pres["lon"]
            if not lat or not lon:
                continue
            space_id = f"SPACE_{pres['presence_id']}"
            s_space = b(space_id)
            triple(s_space, "a", "crm:E94_Space_Primitive")
            triple(s_space, "crm:P168_place_is_defined_by",
                   f'"POINT({lon} {lat})"^^geo:wktLiteral')
            triple(b(pres["presence_id"]), "crm:P161_has_spatial_projection", s_space)

        # P10 CSD presence -> CD presence
        f.write(f"\n# P10_falls_within (CSD presence -> CD presence)\n")
        for a, e in p10_edges:
            triple(b(a), "crm:P10_falls_within", b(e))

        # CD presences (minimal labels)
        f.write(f"\n# E93_Presence (CDs, minimal)\n")
        for year, pid, cd_id in cd_presence_rows:
            s = b(pid)
            triple(s, "a", "crm:E93_Presence")
            triple(s, "rdfs:label", lang(f"{cd_id} ({year})"))
            period_id = period_id_by_year.get(year)
            if period_id:
                triple(s, "crm:P10_falls_within", b(period_id))

        # P122 borders (Lite: no reification — simple edge)
        f.write(f"\n# P122_borders_with (Lite: no E16 reification)\n")
        for a, e in borders:
            triple(b(a), "crm:P122_borders_with", b(e))

        # base:continues_as (Lite flavour of P132 SAME_AS chain)
        f.write(f"\n# base:continues_as (temporal continuity, SAME_AS chains)\n")
        for a, e in continues_as:
            triple(b(a), "base:continues_as", b(e))

        # base:split_from / base:merged_into
        f.write(f"\n# Lineage (Place -> Place)\n")
        for kind, s_id, e_id, year in lineage:
            s_meta = uri_by_place.get(s_id, {})
            e_meta = uri_by_place.get(e_id, {})
            s_uri = s_meta.get("uri", "") or f"{BASE}{safe_local(s_id)}"
            e_uri = e_meta.get("uri", "") or f"{BASE}{safe_local(e_id)}"
            pred = "base:split_from" if kind == "SPLIT_FROM" else "base:merged_into"
            triple(f"<{s_uri}>", pred, f"<{e_uri}>")
            # optional change_year as annotation on the subject (simple Lite form)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\n  Wrote {triple_count:,} triples → {out_path.name} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
