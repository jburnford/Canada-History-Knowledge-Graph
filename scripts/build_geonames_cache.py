"""Build a coords cache for GeoNames IDs referenced by the DCB cohort.

Two passes:
  1. Pre-fill from inline coords in lincs_dcb_persons.json (LINCS lincs_place entries
     often carry latitude/longitude alongside a geonamesId — no API call needed).
  2. Fetch remaining IDs from the GeoNames API (username from env GEONAMES_USERNAME).

Output:
  data/geonames_coords.csv   — id, lat, lon, name, country, feature_class
  data/geonames_misses.csv   — IDs the API rejected or never resolved

Cache shape on disk is the CSV itself; re-runs append + dedupe.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
COHORT = REPO / "data" / "lincs_dcb_persons.json"
OUT_COORDS = REPO / "data" / "geonames_coords.csv"
OUT_MISSES = REPO / "data" / "geonames_misses.csv"

API_BASE = "http://api.geonames.org/getJSON"
USER_AGENT = "Canada-History-KG/0.1 (cljim22@gmail.com)"


def collect_geonames_ids(cohort_path: Path) -> tuple[set[int], dict[int, dict]]:
    """Return (all_referenced_ids, inline_coords_by_id).

    inline_coords_by_id is built from lincs_place entries that carry latitude/longitude
    inline alongside a geonamesId — those are 'free' coordinate resolutions.
    """
    with open(cohort_path) as fh:
        persons = json.load(fh)["persons"]

    all_ids: set[int] = set()
    inline: dict[int, dict] = {}
    for p in persons:
        for ev_field in ("birthEvent", "deathEvent"):
            ev = p.get(ev_field)
            if not ev:
                continue
            for place in ev.get("places") or []:
                gid = None
                if place.get("type") == "geonames" and "id" in place:
                    gid = int(place["id"])
                elif "geonamesId" in place:
                    gid = int(place["geonamesId"])
                if gid is None:
                    continue
                all_ids.add(gid)
                lat = place.get("latitude")
                lon = place.get("longitude")
                if lat is not None and lon is not None and gid not in inline:
                    inline[gid] = {
                        "id": gid,
                        "lat": float(lat),
                        "lon": float(lon),
                        "name": place.get("name", ""),
                        "country": "",
                        "feature_class": "",
                        "source": "lincs_inline",
                    }
    return all_ids, inline


def load_existing_cache(path: Path) -> dict[int, dict]:
    if not path.exists():
        return {}
    out: dict[int, dict] = {}
    with open(path) as fh:
        r = csv.DictReader(fh)
        for row in r:
            try:
                gid = int(row["id"])
            except (KeyError, ValueError):
                continue
            out[gid] = {
                "id": gid,
                "lat": float(row["lat"]) if row["lat"] else None,
                "lon": float(row["lon"]) if row["lon"] else None,
                "name": row.get("name", ""),
                "country": row.get("country", ""),
                "feature_class": row.get("feature_class", ""),
                "source": row.get("source", ""),
            }
    return out


def load_misses(path: Path) -> set[int]:
    if not path.exists():
        return set()
    out = set()
    with open(path) as fh:
        r = csv.DictReader(fh)
        for row in r:
            try:
                out.add(int(row["id"]))
            except (KeyError, ValueError):
                continue
    return out


def write_coords(path: Path, cache: dict[int, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "lat", "lon", "name", "country", "feature_class", "source"])
        for gid in sorted(cache):
            r = cache[gid]
            w.writerow([
                r["id"],
                "" if r["lat"] is None else f"{r['lat']:.6f}",
                "" if r["lon"] is None else f"{r['lon']:.6f}",
                r.get("name", ""),
                r.get("country", ""),
                r.get("feature_class", ""),
                r.get("source", ""),
            ])


def append_miss(path: Path, gid: int, reason: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with open(path, "a", newline="") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow(["id", "reason", "fetched_at"])
        w.writerow([gid, reason, time.strftime("%Y-%m-%d %H:%M:%S")])


def fetch_geoname(gid: int, username: str) -> Optional[dict]:
    qs = urllib.parse.urlencode({"geonameId": gid, "username": username})
    url = f"{API_BASE}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if "status" in data:
        # GeoNames returns {"status": {"message": "...", "value": code}} on errors.
        return {"_error": data["status"].get("message", "unknown error")}
    if "lat" not in data or "lng" not in data:
        return {"_error": "no lat/lng in response"}
    return {
        "id": gid,
        "lat": float(data["lat"]),
        "lon": float(data["lng"]),
        "name": data.get("name", ""),
        "country": data.get("countryCode", ""),
        "feature_class": data.get("fcl", ""),
        "source": "geonames_api",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--username", default=os.environ.get("GEONAMES_USERNAME", "jburnford"))
    ap.add_argument("--rate-sleep", type=float, default=1.1,
                    help="Seconds to sleep between API calls (free tier ~1/s)")
    ap.add_argument("--limit", type=int, default=0,
                    help="Stop after N API fetches (0 = no limit)")
    ap.add_argument("--inline-only", action="store_true",
                    help="Only do inline pre-fill, skip the API entirely")
    args = ap.parse_args()

    print(f"[1/3] Collecting GeoNames IDs from cohort", file=sys.stderr)
    all_ids, inline = collect_geonames_ids(COHORT)
    print(f"      distinct IDs referenced: {len(all_ids):,}", file=sys.stderr)
    print(f"      inline-resolved (free):  {len(inline):,}", file=sys.stderr)

    print(f"[2/3] Loading existing cache", file=sys.stderr)
    cache = load_existing_cache(OUT_COORDS)
    misses = load_misses(OUT_MISSES)
    print(f"      cache: {len(cache):,} hits, {len(misses):,} known misses", file=sys.stderr)

    # Merge inline into cache (don't overwrite API-sourced entries with inline)
    n_added_inline = 0
    for gid, rec in inline.items():
        if gid not in cache:
            cache[gid] = rec
            n_added_inline += 1
    print(f"      added {n_added_inline:,} inline entries to cache", file=sys.stderr)
    write_coords(OUT_COORDS, cache)

    needed = sorted(all_ids - set(cache) - misses)
    print(f"      remaining IDs to fetch from API: {len(needed):,}", file=sys.stderr)

    if args.inline_only or not needed:
        print(f"[3/3] Skipping API ({'inline-only' if args.inline_only else 'nothing to fetch'})",
              file=sys.stderr)
        return 0

    if args.limit and args.limit < len(needed):
        needed = needed[:args.limit]
        print(f"      LIMITED to first {args.limit:,}", file=sys.stderr)

    print(f"[3/3] Fetching from GeoNames API as user={args.username} "
          f"(sleep={args.rate_sleep}s)", file=sys.stderr)
    n_ok = 0
    n_err = 0
    t0 = time.time()
    for i, gid in enumerate(needed, 1):
        try:
            rec = fetch_geoname(gid, args.username)
        except Exception as e:
            rec = {"_error": str(e)}
        if rec is None or "_error" in rec:
            reason = (rec or {}).get("_error", "no result")
            append_miss(OUT_MISSES, gid, reason)
            n_err += 1
            print(f"      [{i}/{len(needed)}] {gid} MISS: {reason}", file=sys.stderr)
            # If we hit a quota/auth error, stop — re-running with a fixed username will resume.
            if "limit" in reason.lower() or "credits" in reason.lower() or "user does not exist" in reason.lower():
                print(f"      Quota or auth issue — stopping.", file=sys.stderr)
                break
        else:
            cache[gid] = rec
            n_ok += 1
            if i % 50 == 0 or i <= 5:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                print(f"      [{i}/{len(needed)}] {gid} → {rec['name']} "
                      f"({rec['lat']:.3f},{rec['lon']:.3f}) [{rate:.1f}/s]", file=sys.stderr)
        time.sleep(args.rate_sleep)

        # Periodic flush in case we crash
        if i % 100 == 0:
            write_coords(OUT_COORDS, cache)

    write_coords(OUT_COORDS, cache)
    print(f"      API fetch summary: ok={n_ok}, err={n_err}", file=sys.stderr)
    print(f"      coords cache size: {len(cache):,}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
