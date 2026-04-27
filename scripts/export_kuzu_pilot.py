#!/usr/bin/env python3
"""
Export ON 1851-1921 census pilot as a KuzuDB property graph (Approach C).

Reads v2 Neo4j CSVs from neo4j_cidoc_crm_v2/ and neo4j_census_v2/, filters to
Ontario, flattens the five pilot measurement variables onto E93_Presence as
typed columns, and builds a Kuzu database with:

  Nodes:  Place, Presence, Name, CensusVariable
  Edges:  HAS_NAME, OBSERVED_IN, PART_OF_COUNTY, BORDERS,
          CONTINUES_AS, SPLIT_FROM, MERGED_INTO

Variable name-drift mapping per pilot/variables.md.

Output:
  pilot/on_kuzu/schema.cypher        DDL (git-reviewable)
  pilot/on_kuzu/nodes/*.csv          Loader CSVs (git-diff-friendly)
  pilot/on_kuzu/edges/*.csv          Loader CSVs
  pilot/on_kuzu/on.kuzu/             Built database (.gitignored)

Usage:
    python3 scripts/export_kuzu_pilot.py --province ON
"""

import argparse
import csv
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CRM = REPO / "neo4j_cidoc_crm_v2"
OBS = REPO / "neo4j_census_v2"
GROUNDING = REPO / "wikidata_grounding"
OUT_ROOT = REPO / "pilot" / "on_kuzu"

YEARS = [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921]

# Variable name drift: pilot_column -> {year: source_var_name}
# See pilot/variables.md for the rationale.
VAR_MAP = {
    # Ingestion now reads only CSD-format files for 1851-1901 (whose column
    # headers use the regularized Mastvar names like POP_XX_N/POP_MX_N/POP_FX_N)
    # and PUB-format files for 1911/1921 (which use POP_TOT/POP_M/POP_F).
    "pop_total": {
        1851: "VAR_POP_XX_N", 1861: "VAR_POP_XX_N", 1871: "VAR_POP_XX_N",
        1881: "VAR_POP_XX_N", 1891: "VAR_POP_XX_N", 1901: "VAR_POP_XX_N",
        1911: "VAR_POP_TOT",  1921: "VAR_POP_TOT",
    },
    "pop_total_m": {
        1851: "VAR_POP_MX_N", 1861: "VAR_POP_MX_N", 1871: "VAR_POP_MX_N",
        1881: "VAR_POP_MX_N", 1891: "VAR_POP_MX_N", 1901: "VAR_POP_MX_N",
        1911: "VAR_POP_M",    1921: "VAR_POP_M",
    },
    "pop_total_f": {
        1851: "VAR_POP_FX_N", 1861: "VAR_POP_FX_N", 1871: "VAR_POP_FX_N",
        1881: "VAR_POP_FX_N", 1891: "VAR_POP_FX_N", 1901: "VAR_POP_FX_N",
        1911: "VAR_POP_F",    1921: "VAR_POP_F",
    },
    "pop_per_sq_mi": {
        1911: "VAR_POP_PER_SQ_MI",
    },
    "cd_name": {
        1851: "VAR_CD_NAME",
        1861: "VAR_CD_NAME",
        1881: "VAR_CD_NAME",
    },
}

# Column types in the Presence table (drives CSV schema + DDL)
PRESENCE_COLS = [
    ("presence_id", "STRING"),
    ("tcpuid", "STRING"),
    ("year", "INT64"),
    ("area_sqm", "DOUBLE"),
    ("centroid_lat", "DOUBLE"),
    ("centroid_lon", "DOUBLE"),
    ("pop_total", "INT64"),
    ("pop_total_m", "INT64"),
    ("pop_total_f", "INT64"),
    ("pop_per_sq_mi", "DOUBLE"),
    ("cd_name", "STRING"),
]


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


def csv_write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


DEFAULT_PROVINCES = ["ON", "QC", "NS", "NB", "PE", "BC", "AB", "SK", "MB", "YT", "NT", "NL"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--province", help="Single province (legacy; prefer --provinces)")
    ap.add_argument("--provinces", default=",".join(DEFAULT_PROVINCES),
                    help="Comma-separated province codes; default = all of Canada")
    ap.add_argument("--out", default=str(OUT_ROOT))
    args = ap.parse_args()

    if args.province:
        provinces = [args.province]
    else:
        provinces = [p.strip() for p in args.provinces.split(",") if p.strip()]
    prov_set = set(provinces)
    # Backwards-compat single-province var used in print() lines.
    prov = provinces[0] if len(provinces) == 1 else "+".join(provinces)
    out_root = Path(args.out)
    if out_root.exists():
        shutil.rmtree(out_root)
    (out_root / "nodes").mkdir(parents=True)
    (out_root / "edges").mkdir(parents=True)

    print(f"Pilot export: province={prov} out={out_root}")

    # ----- Places: CSDs + CDs -----
    print("\n[1/7] Loading places...")
    uri_by_place = {}
    for r in read_csv(CRM / "e53_place_uri.csv"):
        uri_by_place[r["place_id:ID"]] = {
            "uri": r.get("uri", ""),
            "wikidata_qid": r.get("wikidata_qid", ""),
        }

    # Wikipedia EN+FR sitelinks per QID (from scripts/fetch_wikipedia_sitelinks.py).
    sitelinks_by_qid = {}
    sitelinks_path = REPO / "wikidata_grounding" / "wikipedia_sitelinks.csv"
    if sitelinks_path.exists():
        for r in read_csv(sitelinks_path):
            sitelinks_by_qid[r["qid"]] = (r.get("enwiki_url", ""),
                                          r.get("frwiki_url", ""))
        print(f"  Loaded {len(sitelinks_by_qid)} Wikipedia sitelinks")
    else:
        print(f"  (no sitelinks file at {sitelinks_path}; skipping Wikipedia URLs)")

    places = []
    place_ids = set()
    for r in read_csv(CRM / "e53_place_csd.csv"):
        rp = r["province"]
        if rp not in prov_set:
            continue
        pid = r["place_id:ID"]
        meta = uri_by_place.get(pid, {})
        qid = meta.get("wikidata_qid", "") or ""
        en_url, fr_url = sitelinks_by_qid.get(qid, ("", ""))
        places.append([
            pid,
            r["name"],
            rp,
            "CSD",
            qid,
            "",  # geonames_id not available in current data; stays NULL
            en_url,
            fr_url,
        ])
        place_ids.add(pid)
    for r in read_csv(CRM / "e53_place_cd.csv"):
        rp = r.get("province", "")
        if rp not in prov_set:
            continue
        pid = r["place_id:ID"]
        meta = uri_by_place.get(pid, {})
        qid = meta.get("wikidata_qid", "") or ""
        en_url, fr_url = sitelinks_by_qid.get(qid, ("", ""))
        places.append([
            pid,
            r["name"],
            rp,
            "CD",
            qid,
            "",
            en_url,
            fr_url,
        ])
        place_ids.add(pid)

    csv_write(
        out_root / "nodes" / "place.csv",
        ["place_id", "name", "province", "place_type", "wikidata_qid",
         "geonames_id", "enwiki_url", "frwiki_url"],
        places,
    )
    print(f"  {len(places)} Place nodes ({sum(1 for p in places if p[3] == 'CSD')} CSD + {sum(1 for p in places if p[3] == 'CD')} CD)")

    # ----- Presences: ON CSDs + ON CDs, joined with measurements -----
    print("\n[2/7] Loading CSD presences + measurements...")

    # Pre-index type -> list of measurement IDs per year
    # meas_by_var[year][var_name] = set(meas_id)
    # meas_to_presence[year][meas_id] = presence_id
    # dim_value[year][dim_id] = (float_val, str_val)
    # meas_to_dim[year][meas_id] = dim_id
    var_wanted_by_year = defaultdict(set)  # year -> set(variable_name we care about)
    var_to_col_by_year = defaultdict(dict)  # year -> {variable_name: pilot_col}
    for col, year_map in VAR_MAP.items():
        for yr, vname in year_map.items():
            var_wanted_by_year[yr].add(vname)
            var_to_col_by_year[yr][vname] = col

    # Build per-year lookup: presence_id -> {col: value}
    measurement_by_presence = defaultdict(dict)  # (year, presence_id) -> {col: val}

    for year in YEARS:
        # Step A: scan p2_has_type to find measurements of our wanted variables.
        wanted_meas_ids = {}  # meas_id -> pilot_col
        for r in read_csv_iter(OBS / f"p2_has_type_{year}.csv"):
            var = r[":END_ID"]
            if var in var_wanted_by_year[year]:
                mid = r[":START_ID"]
                # Filter to province prefix on the measurement ID: MEAS_<PROV><tcpuid>_YYYY_...
                # Province codes are uniformly 2 chars in this dataset.
                if mid[5:7] not in prov_set:
                    continue
                wanted_meas_ids[mid] = var_to_col_by_year[year][var]
        if not wanted_meas_ids:
            continue

        # Step B: map each measurement to its presence via p39_measured.
        meas_to_presence = {}
        for r in read_csv_iter(OBS / f"p39_measured_{year}.csv"):
            mid = r[":START_ID"]
            if mid in wanted_meas_ids:
                meas_to_presence[mid] = r[":END_ID"]

        # Step C: map each measurement to its dimension via p40_observed_dimension.
        meas_to_dim = {}
        for r in read_csv_iter(OBS / f"p40_observed_dimension_{year}.csv"):
            mid = r[":START_ID"]
            if mid in wanted_meas_ids:
                meas_to_dim[mid] = r[":END_ID"]

        # Step D: load the dimension values.
        wanted_dim_ids = set(meas_to_dim.values())
        dim_values = {}
        for r in read_csv_iter(OBS / f"e54_dimensions_{year}.csv"):
            did = r["dimension_id:ID"]
            if did in wanted_dim_ids:
                float_str = r.get("value:float", "")
                str_str = r.get("value_string", "")
                dim_values[did] = (float_str, str_str)

        # Step E: stitch it all together.
        for mid, col in wanted_meas_ids.items():
            presence_id_short = meas_to_presence.get(mid)
            if not presence_id_short:
                continue
            # presence_id in p39 is like "ON001001_1851" (no year if file is year-specific? let's trust the file)
            # The measurements file is year-scoped, so presence_id includes the year.
            did = meas_to_dim.get(mid)
            if not did:
                continue
            fval, sval = dim_values.get(did, ("", ""))
            # Pick the right value based on column type.
            if col == "cd_name":
                if sval:
                    measurement_by_presence[(year, presence_id_short)][col] = sval
            elif col == "pop_per_sq_mi":
                if fval:
                    measurement_by_presence[(year, presence_id_short)][col] = float(fval)
            else:
                # integer columns
                if fval:
                    try:
                        measurement_by_presence[(year, presence_id_short)][col] = int(float(fval))
                    except ValueError:
                        pass

    print(f"  Measurement rows joined: {sum(len(v) for v in measurement_by_presence.values())}")

    # Now build Presence node rows. Join with P161 → E94 for centroids.
    print("\n[3/7] Joining presence spatial projections...")
    presence_centroid = {}  # presence_id -> (lat, lon)
    for year in YEARS:
        # p161 maps presence -> space_id
        p161 = {}
        for r in read_csv_iter(CRM / f"p161_spatial_projection_{year}.csv"):
            p161[r[":START_ID"]] = r[":END_ID"]
        space_by_id = {}
        for r in read_csv_iter(CRM / f"e94_space_primitive_{year}.csv"):
            space_by_id[r["space_id:ID"]] = (
                r.get("latitude:float", "") or r.get("latitude", ""),
                r.get("longitude:float", "") or r.get("longitude", ""),
            )
        for pres_id, space_id in p161.items():
            if pres_id in presence_centroid:
                continue
            latlon = space_by_id.get(space_id)
            if latlon and latlon[0] and latlon[1]:
                try:
                    presence_centroid[pres_id] = (float(latlon[0]), float(latlon[1]))
                except ValueError:
                    pass

    print(f"  Centroids indexed: {len(presence_centroid)}")

    # Build CSD presence rows.
    print("\n[4/7] Building Presence rows...")
    presences = []
    presence_ids = set()
    cd_presence_ids = set()
    for year in YEARS:
        for r in read_csv_iter(CRM / f"e93_presence_{year}.csv"):
            pid = r["presence_id:ID"]
            # Filter to province prefix (provinces are 2 chars).
            if pid[:2] not in prov_set:
                continue
            # Source CSVs occasionally have duplicate rows for the same
            # presence_id with different polygon areas; keep the first.
            if pid in presence_ids:
                continue
            tcpuid = r.get("csd_tcpuid", "")
            area_raw = r.get("area_sqm:float", "") or r.get("area_sqm", "")
            try:
                area = float(area_raw) if area_raw else None
            except ValueError:
                area = None
            lat, lon = presence_centroid.get(pid, (None, None))
            measures = measurement_by_presence.get((year, pid), {})
            presences.append([
                pid, tcpuid, year,
                area if area is not None else "",
                lat if lat is not None else "",
                lon if lon is not None else "",
                measures.get("pop_total", ""),
                measures.get("pop_total_m", ""),
                measures.get("pop_total_f", ""),
                measures.get("pop_per_sq_mi", ""),
                measures.get("cd_name", ""),
            ])
            presence_ids.add(pid)

        # CD presences for the same year. Store separately so we can emit PART_OF_COUNTY edges.
        for r in read_csv_iter(CRM / f"e93_presence_cd_{year}.csv"):
            pid = r["presence_id:ID"]
            # CD presence IDs look like CD_ON_Addington_1871
            if not (pid.startswith("CD_") and pid[3:5] in prov_set
                    and pid[5:6] == "_"):
                continue
            if pid in presence_ids:
                continue
            cd_id = r.get("cd_id", "")
            area_raw = r.get("area_sqm:float", "") or r.get("area_sqm", "")
            try:
                area = float(area_raw) if area_raw else None
            except ValueError:
                area = None
            presences.append([
                pid, cd_id, year,
                area if area is not None else "",
                "", "",  # no centroids for CDs in this dataset path
                "", "", "", "", "",  # measurements empty for CDs in pilot
            ])
            presence_ids.add(pid)
            cd_presence_ids.add(pid)

    presence_header = [c[0] for c in PRESENCE_COLS]
    csv_write(out_root / "nodes" / "presence.csv", presence_header, presences)
    print(f"  {len(presences)} Presence rows (incl. {len(cd_presence_ids)} CD presences)")

    # ----- Names: appellations linked to our places -----
    print("\n[5/7] Loading appellations + P1 links...")
    # Collect P1 edges whose START is one of our places (CSD/CD)
    p1_links = []
    app_ids_needed = set()
    for r in read_csv_iter(CRM / "p1_is_identified_by.csv"):
        s = r[":START_ID"]
        e = r[":END_ID"]
        if not e.startswith("APP_"):
            continue
        # Accept start = a known place, or a presence in our province (for variant names).
        if s in place_ids:
            p1_links.append((s, e, "place"))
            app_ids_needed.add(e)
        elif s[:2] in prov_set and s in presence_ids:
            p1_links.append((s, e, "presence"))
            app_ids_needed.add(e)

    apps_by_id = {}
    for r in read_csv_iter(CRM / "e41_appellations.csv"):
        aid = r["appellation_id:ID"]
        if aid in app_ids_needed:
            apps_by_id[aid] = r

    name_rows = []
    for aid, r in apps_by_id.items():
        name_rows.append([
            aid,
            r.get("name", ""),
            "en",
            r.get("type", "variant"),  # canonical or variant
        ])
    csv_write(
        out_root / "nodes" / "name.csv",
        ["name_id", "label", "language", "kind"],
        name_rows,
    )
    print(f"  {len(name_rows)} Name nodes, {len(p1_links)} HAS_NAME edges")

    # ----- CensusVariable nodes (full catalog + fallback for codes referenced
    # but missing from e55_variable_types.csv).  We synthesize a minimal entry
    # for unknown var_codes so OF_VARIABLE FKs always resolve.
    var_types = {r["type_id:ID"]: r for r in read_csv(OBS / "e55_variable_types.csv")}

    # Discover every var_code actually referenced from p2_has_type files for
    # ON measurements.  This is the same scan we'll do later when emitting
    # OF_VARIABLE edges; we just collect var_codes here.
    referenced_vcodes = set()
    for year in YEARS:
        for r in read_csv_iter(OBS / f"p2_has_type_{year}.csv"):
            mid = r[":START_ID"]
            if mid[5:7] in prov_set:
                referenced_vcodes.add(r[":END_ID"])

    # Heuristic category inference from var_code prefix (e55 conventions).
    cat_hints = {
        "POP": "POP", "AGE": "AGE", "REL": "REL", "ORIG": "ETH", "ETH": "ETH",
        "BIRTH": "POP", "MAR": "POP", "FAM": "POP",
        "DTH": "DTH", "DEATH": "DTH",
        "AGR": "AGR", "FML": "AGR", "BWT": "AGR", "WHT": "AGR", "BAR": "AGR",
        "OAT": "AGR", "RYE": "AGR", "PEA": "AGR", "BEAN": "AGR", "POT": "AGR",
        "TOB": "AGR", "MAP": "AGR", "FLAX": "AGR", "WOOL": "AGR", "HAY": "AGR",
        "CRN": "AGR", "BUC": "AGR", "BTL": "AGR", "BEEF": "AGR", "PORK": "AGR",
        "MIL": "AGR", "BUT": "AGR", "CHE": "AGR", "FRU": "AGR", "ARE": "AGR",
        "HRS": "AGR", "OXEN": "AGR", "COW": "AGR", "CALF": "AGR", "SHP": "AGR",
        "PIG": "AGR", "FRM": "AGR",
        "MFG": "MFG", "FCT": "MFG", "EMP": "MFG",
        "BLD": "BLD", "HOU": "BLD", "DWL": "BLD", "BUI": "BLD",
        "FSH": "FSH", "FIS": "FSH",
        "SCH": "POP", "EDU": "POP",
    }

    def infer_category(vcode: str) -> str:
        # Strip "VAR_" prefix and "C<num>_" leading segment if present.
        stem = vcode.replace("VAR_", "", 1)
        stem = re.sub(r"^C\d+_", "", stem)
        head = stem.split("_", 1)[0].upper()
        return cat_hints.get(head, "OTHER")

    var_rows = []
    all_vcodes = set(var_types.keys()) | referenced_vcodes
    for vcode in sorted(all_vcodes):
        vt = var_types.get(vcode, {})
        if vt:
            var_rows.append([
                vcode,
                vt.get("label", vcode),
                vt.get("category", "") or infer_category(vcode),
                vt.get("unit", ""),
            ])
        else:
            # Synthetic entry so FK references resolve. Label = humanised code.
            human = vcode.replace("VAR_", "").replace("_", " ")
            var_rows.append([vcode, human, infer_category(vcode), ""])
    csv_write(
        out_root / "nodes" / "census_variable.csv",
        ["var_code", "label", "category", "unit"],
        var_rows,
    )
    synth = len(referenced_vcodes - set(var_types.keys()))
    print(f"  {len(var_rows)} CensusVariable nodes "
          f"({len(var_types)} from catalog + {synth} synthesized for missing codes)")

    # ----- Measurement nodes + MEASURED_AT (Presence→Measurement) +
    # ----- OF_VARIABLE (Measurement→CensusVariable) edges
    print("\n[5b/7] Loading all ON measurements...")
    meas_rows = []
    measured_at_rows = []
    of_variable_rows = []
    for year in YEARS:
        # Build (mid → var_code) for all in-scope-province measurements in this year.
        meas_to_var = {}
        for r in read_csv_iter(OBS / f"p2_has_type_{year}.csv"):
            mid = r[":START_ID"]
            if mid[5:7] not in prov_set:
                continue
            meas_to_var[mid] = r[":END_ID"]
        # Build (mid → presence_id) for those measurements that point at an ON presence.
        meas_to_presence = {}
        for r in read_csv_iter(OBS / f"p39_measured_{year}.csv"):
            mid = r[":START_ID"]
            if mid in meas_to_var:
                meas_to_presence[mid] = r[":END_ID"]
        # Build (mid → dim_id).
        meas_to_dim = {}
        for r in read_csv_iter(OBS / f"p40_observed_dimension_{year}.csv"):
            mid = r[":START_ID"]
            if mid in meas_to_var:
                meas_to_dim[mid] = r[":END_ID"]
        # Build (dim_id → (float, string)).
        wanted_dims = set(meas_to_dim.values())
        dim_vals = {}
        for r in read_csv_iter(OBS / f"e54_dimensions_{year}.csv"):
            did = r["dimension_id:ID"]
            if did in wanted_dims:
                dim_vals[did] = (r.get("value:float", ""), r.get("value_string", ""))
        # Stitch.
        for mid, vcode in meas_to_var.items():
            pres_id = meas_to_presence.get(mid)
            if not pres_id or pres_id not in presence_ids:
                continue
            did = meas_to_dim.get(mid)
            fval, sval = dim_vals.get(did, ("", "")) if did else ("", "")
            # Skip measurements with neither a numeric nor a string value.
            if not fval and not sval:
                continue
            meas_rows.append([mid, fval, sval])
            measured_at_rows.append([pres_id, mid])
            of_variable_rows.append([mid, vcode])

    csv_write(
        out_root / "nodes" / "measurement.csv",
        ["measurement_id", "value_float", "value_string"],
        meas_rows,
    )
    csv_write(
        out_root / "edges" / "measured_at.csv",
        ["from", "to"], measured_at_rows,
    )
    csv_write(
        out_root / "edges" / "of_variable.csv",
        ["from", "to"], of_variable_rows,
    )
    print(f"  {len(meas_rows)} Measurement nodes, "
          f"{len(measured_at_rows)} MEASURED_AT, {len(of_variable_rows)} OF_VARIABLE edges")

    # ----- Edges -----
    print("\n[6/7] Building edges...")

    # HAS_NAME (Place→Name and Presence→Name are two separate REL tables in Kuzu;
    # emit to two CSVs)
    has_name_place = [[s, e] for (s, e, kind) in p1_links if kind == "place"]
    has_name_presence = [[s, e] for (s, e, kind) in p1_links if kind == "presence"]
    csv_write(
        out_root / "edges" / "has_name_place.csv",
        ["from", "to"], has_name_place,
    )
    csv_write(
        out_root / "edges" / "has_name_presence.csv",
        ["from", "to"], has_name_presence,
    )

    # OBSERVED_IN: P166 Presence → Place
    observed_in = []
    for year in YEARS:
        for r in read_csv_iter(CRM / f"p166_was_presence_of_{year}.csv"):
            if r[":START_ID"] in presence_ids and r[":END_ID"] in place_ids:
                observed_in.append([r[":START_ID"], r[":END_ID"]])
    csv_write(out_root / "edges" / "observed_in.csv", ["from", "to"], observed_in)

    # PART_OF_COUNTY: P10 CSD presence → CD presence
    part_of_county = []
    for year in YEARS:
        for r in read_csv_iter(CRM / f"p10_csd_within_cd_presence_{year}.csv"):
            if r[":START_ID"] in presence_ids and r[":END_ID"] in presence_ids:
                part_of_county.append([r[":START_ID"], r[":END_ID"]])
    csv_write(out_root / "edges" / "part_of_county.csv", ["from", "to"], part_of_county)

    # BORDERS: P122 + border length from E54
    borders = []
    for year in YEARS:
        # length_by_pair[(a,b)] = length_m
        length_by_pair = {}
        for r in read_csv_iter(CRM / f"e54_border_dimension_{year}.csv"):
            did = r["dimension_id:ID"]  # BORDER_DIM_<A>_<B>_YYYY
            val = r.get("value:float", "")
            if not val:
                continue
            # extract pair from did; split after 'BORDER_DIM_' and before '_YYYY'
            core = did[len("BORDER_DIM_"):]
            core = core.rsplit(f"_{year}", 1)[0]
            parts = core.split("_", 1)
            if len(parts) == 2:
                a, b = parts[0], parts[1]
                # rebuild presence IDs
                a_pres = f"{a}_{year}"
                b_pres = f"{b}_{year}"
                try:
                    length_by_pair[(a_pres, b_pres)] = float(val)
                except ValueError:
                    pass
        for r in read_csv_iter(CRM / f"p122_borders_with_{year}.csv"):
            a = r[":START_ID"]; b = r[":END_ID"]
            if a not in presence_ids and b not in presence_ids:
                continue
            # Only emit borders where both sides are in our province (avoids edges to other provinces).
            if a not in presence_ids or b not in presence_ids:
                continue
            length = length_by_pair.get((a, b)) or length_by_pair.get((b, a)) or 0.0
            borders.append([a, b, length])
    csv_write(out_root / "edges" / "borders.csv", ["from", "to", "length_m"], borders)

    # CONTINUES_AS: P132 with overlap_type=SAME_AS, from presence A to presence B
    # OVERLAPS_TEMPORALLY: P132 with the other overlap types (CONTAINS, WITHIN,
    # OVERLAPS) so we can show boundary-change continuity even across SAME_AS gaps.
    continues_as = []
    overlaps_temporally = []
    for r in read_csv_iter(CRM / "p132_spatiotemporally_overlaps_with_csd.csv"):
        a = r[":START_ID"]; b = r[":END_ID"]
        if a not in presence_ids or b not in presence_ids:
            continue
        otype = r.get("overlap_type", "")
        iou_raw = r.get("iou:float", "") or r.get("iou", "")
        try:
            iou = float(iou_raw) if iou_raw else 1.0
        except ValueError:
            iou = 1.0
        if otype == "SAME_AS":
            continues_as.append([a, b, iou])
        else:
            year_from = r.get("year_from:int", "") or r.get("year_from", "")
            year_to = r.get("year_to:int", "") or r.get("year_to", "")
            try:
                yf = int(year_from) if year_from else 0
            except ValueError:
                yf = 0
            try:
                yt = int(year_to) if year_to else 0
            except ValueError:
                yt = 0
            overlaps_temporally.append([a, b, otype, iou, yf, yt])
    csv_write(out_root / "edges" / "continues_as.csv", ["from", "to", "iou"], continues_as)
    csv_write(
        out_root / "edges" / "overlaps_temporally.csv",
        ["from", "to", "overlap_type", "iou", "year_from", "year_to"],
        overlaps_temporally,
    )

    # SPLIT_FROM / MERGED_INTO: from place_lineage.csv (Place → Place)
    split_from = []
    merged_into = []
    for r in read_csv_iter(CRM / "place_lineage.csv"):
        lt = r.get("lineage_type", "")
        s = r[":START_ID"]; e = r[":END_ID"]
        year = r.get("change_year:int", "") or r.get("change_year", "")
        if s not in place_ids and e not in place_ids:
            continue
        try:
            yr = int(year) if year else 0
        except ValueError:
            yr = 0
        if lt == "SPLIT_FROM" and s in place_ids and e in place_ids:
            split_from.append([s, e, yr])
        elif lt == "MERGED_INTO" and s in place_ids and e in place_ids:
            merged_into.append([s, e, yr])
    csv_write(out_root / "edges" / "split_from.csv", ["from", "to", "change_year"], split_from)
    csv_write(out_root / "edges" / "merged_into.csv", ["from", "to", "change_year"], merged_into)

    print(f"  OBSERVED_IN={len(observed_in)} PART_OF_COUNTY={len(part_of_county)} "
          f"BORDERS={len(borders)} CONTINUES_AS={len(continues_as)} "
          f"SPLIT_FROM={len(split_from)} MERGED_INTO={len(merged_into)}")

    # ----- schema.cypher -----
    # Use only // comments (Cypher standard). Avoid embedding ';' in comments.
    schema_ddl = """\
// Three-Model KG Pilot -- Approach C (KuzuDB)
// Strict typing: every column explicitly typed, CSV column order must match
// See pilot/variables.md for the five pilot measurement columns

CREATE NODE TABLE Place (
  place_id STRING,
  name STRING,
  province STRING,
  place_type STRING,
  wikidata_qid STRING,
  geonames_id STRING,
  enwiki_url STRING,
  frwiki_url STRING,
  PRIMARY KEY (place_id)
);

CREATE NODE TABLE Presence (
  presence_id STRING,
  tcpuid STRING,
  year INT64,
  area_sqm DOUBLE,
  centroid_lat DOUBLE,
  centroid_lon DOUBLE,
  pop_total INT64,
  pop_total_m INT64,
  pop_total_f INT64,
  pop_per_sq_mi DOUBLE,
  cd_name STRING,
  PRIMARY KEY (presence_id)
);

CREATE NODE TABLE Name (
  name_id STRING,
  label STRING,
  language STRING,
  kind STRING,
  PRIMARY KEY (name_id)
);

CREATE NODE TABLE CensusVariable (
  var_code STRING,
  label STRING,
  category STRING,
  unit STRING,
  PRIMARY KEY (var_code)
);

CREATE NODE TABLE Measurement (
  measurement_id STRING,
  value_float DOUBLE,
  value_string STRING,
  PRIMARY KEY (measurement_id)
);

CREATE REL TABLE HAS_NAME_PLACE (FROM Place TO Name);
CREATE REL TABLE HAS_NAME_PRESENCE (FROM Presence TO Name);
CREATE REL TABLE OBSERVED_IN (FROM Presence TO Place);
CREATE REL TABLE PART_OF_COUNTY (FROM Presence TO Presence);
CREATE REL TABLE BORDERS (FROM Presence TO Presence, length_m DOUBLE);
CREATE REL TABLE CONTINUES_AS (FROM Presence TO Presence, iou DOUBLE);
CREATE REL TABLE OVERLAPS_TEMPORALLY (FROM Presence TO Presence, overlap_type STRING, iou DOUBLE, year_from INT64, year_to INT64);
CREATE REL TABLE SPLIT_FROM (FROM Place TO Place, change_year INT64);
CREATE REL TABLE MERGED_INTO (FROM Place TO Place, change_year INT64);
CREATE REL TABLE MEASURED_AT (FROM Presence TO Measurement);
CREATE REL TABLE OF_VARIABLE (FROM Measurement TO CensusVariable);
"""
    (out_root / "schema.cypher").write_text(schema_ddl)

    # ----- Build Kuzu DB -----
    print("\n[7/7] Building Kuzu database...")
    import ladybug as kuzu  # Ladybug = maintained Kuzu fork; drop-in API
    db_path = out_root / "on.kuzu"
    if db_path.exists():
        shutil.rmtree(db_path)
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    # Strip // comments line-by-line BEFORE splitting on ';' (so ';' inside
    # a comment doesn't break statements).
    clean_lines = []
    for line in schema_ddl.split("\n"):
        if "//" in line:
            line = line[: line.index("//")]
        clean_lines.append(line)
    stripped = "\n".join(clean_lines)
    for stmt in stripped.split(";"):
        s = stmt.strip()
        if not s:
            continue
        conn.execute(s + ";")

    # COPY FROM for each loader CSV.
    copy_plan = [
        ("Place",            "nodes/place.csv"),
        ("Presence",         "nodes/presence.csv"),
        ("Name",             "nodes/name.csv"),
        ("CensusVariable",   "nodes/census_variable.csv"),
        ("Measurement",      "nodes/measurement.csv"),
        ("HAS_NAME_PLACE",   "edges/has_name_place.csv"),
        ("HAS_NAME_PRESENCE","edges/has_name_presence.csv"),
        ("OBSERVED_IN",      "edges/observed_in.csv"),
        ("PART_OF_COUNTY",   "edges/part_of_county.csv"),
        ("BORDERS",          "edges/borders.csv"),
        ("CONTINUES_AS",     "edges/continues_as.csv"),
        ("OVERLAPS_TEMPORALLY", "edges/overlaps_temporally.csv"),
        ("SPLIT_FROM",       "edges/split_from.csv"),
        ("MERGED_INTO",      "edges/merged_into.csv"),
        ("MEASURED_AT",      "edges/measured_at.csv"),
        ("OF_VARIABLE",      "edges/of_variable.csv"),
    ]
    for table, rel in copy_plan:
        full = (out_root / rel).resolve()
        print(f"  COPY {table} FROM {rel}...", end="")
        # Kuzu's default CSV parser doesn't always handle quoted embedded commas
        # out of the box (e.g. a cd_name = "Kingston, City"). Force QUOTE='"'
        # and ESCAPE='"' per RFC 4180 / Python csv.writer output.
        conn.execute(
            f'COPY {table} FROM "{full}" '
            '(HEADER=TRUE, DELIM=",", QUOTE=\'"\', ESCAPE=\'"\');'
        )
        # Report row count.
        try:
            rc = conn.execute(f"MATCH (n:{table}) RETURN count(n) AS c;")
            print(f" OK ({rc.get_next()[0]} rows)")
        except Exception:
            rc = conn.execute(
                f"MATCH ()-[r:{table}]->() RETURN count(r) AS c;"
            )
            print(f" OK ({rc.get_next()[0]} edges)")

    # Spot-check Westmeath 1871 population.
    print("\n--- Verification ---")
    result = conn.execute(
        "MATCH (p:Place)<-[:OBSERVED_IN]-(pr:Presence {year: 1871}) "
        "WHERE p.name = 'Westmeath' "
        "RETURN p.place_id, p.wikidata_qid, pr.pop_total, pr.pop_total_m, pr.pop_total_f LIMIT 5;"
    )
    while result.has_next():
        print("  Westmeath 1871:", result.get_next())

    # Null-vs-zero probe: Westmeath 1851 pop_per_sq_mi should be NULL (not recorded in 1851)
    result = conn.execute(
        "MATCH (p:Place)<-[:OBSERVED_IN]-(pr:Presence {year: 1851}) "
        "WHERE p.name = 'Westmeath' "
        "RETURN pr.pop_per_sq_mi IS NULL AS is_null, pr.pop_per_sq_mi;"
    )
    while result.has_next():
        print("  Null-vs-zero probe (Westmeath 1851 pop_per_sq_mi):", result.get_next())

    print(f"\nDone. Database at {db_path}")
    print(f"Loader CSVs at {out_root}/")


if __name__ == "__main__":
    main()
