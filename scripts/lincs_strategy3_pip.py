"""Strategy 3: Point-in-polygon match for DCB cohort events.

For each cohort person's birth/death event:
  1. Resolve event coords via geonames_coords.csv (built earlier).
  2. Reproject to the GDB CRS (ESRI:102002 Canada Lambert Conformal Conic).
  3. Year-align each event to the closest census year [1851..1921].
  4. Spatial-join against that year's CSD polygon layer.
  5. Map tcpuid → persistent_place_id and emit a link row.

Inputs:
  data/lincs_dcb_persons.json
  data/geonames_coords.csv
  TCP GDB (path resolved via scripts/_config.py CONFIG.gdb_path)
  persistent_places_output/tcpuid_year_to_place.csv

Output:
  data/lincs_strategy3_links.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from _config import CONFIG  # noqa: E402

COHORT = REPO / "data" / "lincs_dcb_persons.json"
COORDS = REPO / "data" / "geonames_coords.csv"
TCPUID_MAP = REPO / "persistent_places_output" / "tcpuid_year_to_place.csv"
OUT = REPO / "data" / "lincs_strategy3_links.csv"

DEFAULT_GDB = str(CONFIG.gdb_path)
CENSUS_YEARS = [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921]


def closest_census_year(year: int) -> int:
    """Closest of [1851..1921]. Below-range clamps to 1851; above clamps to 1921."""
    if year <= CENSUS_YEARS[0]:
        return CENSUS_YEARS[0]
    if year >= CENSUS_YEARS[-1]:
        return CENSUS_YEARS[-1]
    return min(CENSUS_YEARS, key=lambda y: abs(y - year))


def year_priority_list(event_year: int) -> list[int]:
    """Census years to try, in preference order: closest first, then walk forward
    (later in time) until 1921, then walk backward (earlier) toward 1851.

    Forward-first because territorial polygons mature over time — Manitoba acquires
    real CSDs at 1871, Saskatchewan/Alberta at 1881. A pre-1871 prairie event
    misses on 1851/1861 placeholders and finds a real CSD at 1871+.
    """
    closest = closest_census_year(event_year)
    closest_idx = CENSUS_YEARS.index(closest)
    forward = CENSUS_YEARS[closest_idx + 1:]      # 1881, 1891, ...
    backward = list(reversed(CENSUS_YEARS[:closest_idx]))  # 1841, 1831, ... (none below 1851)
    return [closest] + forward + backward


def is_placeholder_tcpuid(tcpuid: str | None) -> bool:
    """GDB stub for unsurveyed/Indigenous territory: tcpuid contains '999999'."""
    if tcpuid is None:
        return True
    return "999999" in str(tcpuid)


def load_coords_cache(path: Path) -> dict[int, tuple[float, float, str]]:
    out = {}
    with open(path) as fh:
        r = csv.DictReader(fh)
        for row in r:
            try:
                gid = int(row["id"])
                lat = float(row["lat"])
                lon = float(row["lon"])
            except (KeyError, ValueError):
                continue
            out[gid] = (lat, lon, row.get("name", ""))
    return out


def load_tcpuid_map(path: Path) -> dict[tuple[str, int], str]:
    out = {}
    with open(path) as fh:
        r = csv.DictReader(fh)
        for row in r:
            tcpuid = row["tcpuid"]
            year = int(row["year"])
            out[(tcpuid, year)] = row["persistent_place_id"]
    return out


def event_year_int(event: dict | None) -> int | None:
    if not event:
        return None
    for k in ("dateBegin", "dateEnd", "date"):
        v = event.get(k)
        if not v:
            continue
        head = str(v)[:4]
        if head.isdigit():
            y = int(head)
            if 1000 <= y <= 2100:
                return y
    return None


def collect_event_points(persons: list[dict],
                         coords: dict[int, tuple[float, float, str]]) -> pd.DataFrame:
    """Build one row per (person, event_type) with first-resolved coords."""
    rows = []
    for p in persons:
        for ev_field, ev_type in [("birthEvent", "birth"), ("deathEvent", "death")]:
            ev = p.get(ev_field)
            if not ev:
                continue
            year = event_year_int(ev)
            # Try each place in the event until we find one with coords.
            for place in ev.get("places") or []:
                gid = None
                lat = lon = None
                gname = None
                if "latitude" in place and "longitude" in place \
                        and place["latitude"] is not None and place["longitude"] is not None:
                    lat = float(place["latitude"])
                    lon = float(place["longitude"])
                    gname = place.get("name", "")
                else:
                    if place.get("type") == "geonames" and "id" in place:
                        gid = int(place["id"])
                    elif "geonamesId" in place:
                        gid = int(place["geonamesId"])
                    if gid is not None and gid in coords:
                        lat, lon, gname = coords[gid]
                if lat is None or lon is None:
                    continue
                rows.append({
                    "person_id": p["personId"],
                    "name": p.get("name", ""),
                    "wikidata_qid": p.get("wikidataQid"),
                    "dcb_url": p.get("dcb_url", ""),
                    "event_type": ev_type,
                    "event_year": year,
                    "geonames_id": gid,
                    "geonames_name": gname,
                    "lat": lat,
                    "lon": lon,
                })
                break  # First resolved place wins for this event.
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gdb", default=DEFAULT_GDB)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    print(f"[1/5] Loading cohort + coords cache + tcpuid map", file=sys.stderr)
    with open(COHORT) as fh:
        persons = json.load(fh)["persons"]
    coords = load_coords_cache(COORDS)
    tcpuid_to_place = load_tcpuid_map(TCPUID_MAP)
    print(f"      cohort: {len(persons)}, coords: {len(coords)}, "
          f"tcpuid_map: {len(tcpuid_to_place)}", file=sys.stderr)

    print(f"[2/5] Building event-point dataframe", file=sys.stderr)
    df = collect_event_points(persons, coords)
    print(f"      events with coords: {len(df)}", file=sys.stderr)
    if df.empty:
        print("ERROR: no events with coords", file=sys.stderr)
        return 1

    df = df[df["event_year"].notna()].copy()
    df["event_year"] = df["event_year"].astype(int)
    print(f"      events with year (after drop NaN): {len(df)}", file=sys.stderr)

    print(f"[3/5] Reprojecting points to GDB CRS", file=sys.stderr)
    points_4326 = gpd.GeoDataFrame(
        df, geometry=[Point(lon, lat) for lon, lat in zip(df["lon"], df["lat"])],
        crs="EPSG:4326",
    )
    # GDB CRS = ESRI:102002 (Canada Lambert)
    points_proj = points_4326.to_crs("ESRI:102002").reset_index(drop=True)

    print(f"[4/5] Sjoin against every census year (forward-fall logic per event)",
          file=sys.stderr)
    # year → {point_idx: (tcpuid, csd_name)}
    year_matches: dict[int, dict[int, tuple[str, str]]] = {}
    for year in CENSUS_YEARS:
        layer = f"CANADA_{year}_CSD"
        polys = gpd.read_file(args.gdb, layer=layer)
        polys = polys[polys.geometry.notna()].copy()
        polys["geometry"] = polys.geometry.buffer(0)
        tcpuid_col = f"TCPUID_CSD_{year}"
        name_col = next((c for c in polys.columns
                         if c.lower() == f"name_csd_{year}".lower()), None)
        keep = [tcpuid_col, "geometry"]
        if name_col:
            keep.append(name_col)
        polys = polys[keep].rename(columns={tcpuid_col: "tcpuid_csd",
                                            **({name_col: "csd_name"} if name_col else {})})
        joined = gpd.sjoin(points_proj, polys, how="inner", predicate="within")
        per_year: dict[int, tuple[str, str]] = {}
        for idx, row in joined.iterrows():
            # If a point lands in multiple polygons (rare), keep the first.
            if idx not in per_year:
                per_year[idx] = (row["tcpuid_csd"], row.get("csd_name", "") or "")
        year_matches[year] = per_year
        n_real = sum(1 for v in per_year.values() if not is_placeholder_tcpuid(v[0]))
        print(f"      {year}: {len(per_year)} matches ({n_real} non-placeholder)",
              file=sys.stderr)

    print(f"[5/5] Per-event year-priority resolution → {args.out}", file=sys.stderr)
    n_links = 0
    n_no_persistent_map = 0
    n_only_placeholder = 0
    n_no_match_anywhere = 0
    fallthrough_dist: dict[int, int] = {}  # how often we walked N years away
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "person_id", "person_name", "person_qid", "dcb_url",
            "event_type", "event_year", "census_year",
            "geonames_id", "geonames_name",
            "tcpuid_csd", "csd_name", "place_id",
            "match_strategy", "confidence",
        ])
        for idx, event in points_proj.iterrows():
            event_year = int(event["event_year"])
            priority = year_priority_list(event_year)
            chosen_year = None
            chosen_tcpuid = None
            chosen_name = None
            placeholder_fallback = None  # (year, tcpuid, name) — used only if no real hit

            for y in priority:
                m = year_matches[y].get(idx)
                if m is None:
                    continue
                tcpuid, csd_name = m
                if is_placeholder_tcpuid(tcpuid):
                    if placeholder_fallback is None:
                        placeholder_fallback = (y, tcpuid, csd_name)
                    continue
                chosen_year, chosen_tcpuid, chosen_name = y, tcpuid, csd_name
                break

            if chosen_year is None:
                if placeholder_fallback:
                    n_only_placeholder += 1
                    # Skip emitting placeholder-only matches (combine.py also drops them).
                else:
                    n_no_match_anywhere += 1
                continue

            place_id = tcpuid_to_place.get((chosen_tcpuid, chosen_year))
            if place_id is None:
                n_no_persistent_map += 1
                continue

            distance = abs(chosen_year - closest_census_year(event_year))
            fallthrough_dist[distance] = fallthrough_dist.get(distance, 0) + 1

            geonames_id = event.get("geonames_id")
            w.writerow([
                event["person_id"], event["name"], event.get("wikidata_qid") or "",
                event.get("dcb_url", ""),
                event["event_type"],
                event_year, chosen_year,
                int(geonames_id) if pd.notna(geonames_id) else "",
                event.get("geonames_name", "") or "",
                chosen_tcpuid, chosen_name,
                place_id,
                "pip", "high",
            ])
            n_links += 1

    print(f"      links emitted:                     {n_links}", file=sys.stderr)
    print(f"      no persistent_place mapping:       {n_no_persistent_map}", file=sys.stderr)
    print(f"      placeholder-only (no real CSD):    {n_only_placeholder}", file=sys.stderr)
    print(f"      no match in any year:              {n_no_match_anywhere}", file=sys.stderr)
    print(f"      fallthrough distance distribution:", file=sys.stderr)
    for d, n in sorted(fallthrough_dist.items()):
        print(f"        Δ{d:2d} census-step{'s' if d != 1 else ' '}: {n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
