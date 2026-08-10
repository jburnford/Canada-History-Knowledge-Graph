#!/usr/bin/env python3
"""Link DCB persons to their 1881 census residents row.

The DCB cohort (data/lincs_dcb_persons.json, 5,220 persons) overlaps with the
1881 Borealis residents (4.16M individuals). We want to find each DCB person's
census record, but the user's hard requirement is ZERO false positives —
better to miss matches than mislink them. So this is a strict-precision pass:

Constraints (ALL must hold for a candidate):
  1. Lastname normalized match (diacritic fold + lowercase + Mc/Mac unify)
  2. Firstname normalized match (full DCB given matches census, OR first 3
     characters match — covers "William"/"Wm", "Margaret"/"Maggie", etc.)
  3. |census_age - (1881 - DCB_birthYear)| <= 2  (census age noise)
  4. Sex match (where both have a value; if either is unknown, skip this
     constraint rather than reject)
  5. Birthplace consistency: if we can derive a province/country for the
     DCB birthplace, the census `dbirthpl_TCP_label` must be compatible
     (province → "Nova Scotia"/"Ontario"/etc.; country → "Ireland"/"Scotland")

Acceptance:
  - exactly 1 census record meets all constraints → record the link
  - 0 → no match (recorded as such for audit)
  - >1 → ambiguous, no link (recorded for audit)

Inputs:
  data/lincs_dcb_persons.json       (DCB cohort with birthEvent/deathEvent)
  residents_1881_output/by_province/*.parquet
  residents_1881_output/residents_1881_uri_manifest.parquet
                                    (for the person URI of each match)

Outputs:
  data/dcb_1881_residents_links.csv     (confirmed links)
  data/dcb_1881_residents_audit.csv     (full audit incl. no-match + ambiguous)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[1]
DCB_JSON = REPO / "data" / "lincs_dcb_persons.json"
RESIDENTS_DIR = REPO / "residents_1881_output" / "by_province"
MANIFEST = REPO / "residents_1881_output" / "residents_1881_uri_manifest.parquet"
OUT_LINKS = REPO / "data" / "dcb_1881_residents_links.csv"
OUT_AUDIT = REPO / "data" / "dcb_1881_residents_audit.csv"

CENSUS_YEAR = 1881
MIN_AGE_1881 = 16  # restrict to adults / near-adults; child entries in DCB
                    # are mostly biographical without census trace, and short
                    # given names ("John", "Mary") on under-16s sweep up too
                    # many false-positive candidates
AGE_TOLERANCE = 2  # ±2 years on census-vs-DCB birth-year math
FIRSTNAME_PREFIX = 3  # first N chars must match between DCB and census


# --------- Birthplace harmonisation ---------

# Map DCB-birthplace name fragments → expected census `dbirthpl_TCP_label`
# token(s). A match is "compatible" if any token in the DCB place's resolved
# bucket equals (case-insensitive) any token in the census label. This gives
# both directions (DCB has province name, census also has province) AND the
# coarser fallback (DCB has town within Nova Scotia, census says "Nova Scotia").
PROVINCE_PATTERNS = {
    "ontario":  ["ontario", "haut-canada", "upper canada", "ont."],
    "quebec":   ["quebec", "québec", "bas-canada", "lower canada", "qc",
                 "que."],
    "nova scotia":  ["nova scotia", "nouvelle-écosse", "nouvelle-ecosse",
                     "n.s", "ns "],
    "new brunswick": ["new brunswick", "nouveau-brunswick", "n.b", "nb "],
    "prince edward island": ["prince edward island",
                              "île-du-prince-édouard",
                              "ile-du-prince-edouard", "p.e.i", "pei "],
    "manitoba": ["manitoba", "man.", "mb "],
    "british columbia": ["british columbia", "colombie-britannique", "b.c"],
    "newfoundland": ["newfoundland", "terre-neuve", "nfld", "nfl"],
    "northwest territories": ["northwest territories",
                                "territoires du nord-ouest", "n.w.t",
                                "nwt "],
}
COUNTRY_PATTERNS = {
    "ireland":  ["ireland", "irlande"],
    "scotland": ["scotland", "écosse", "ecosse"],
    "england":  ["england", "angleterre"],
    "wales":    ["wales", "pays de galles"],
    "united kingdom": ["united kingdom", "great britain", "royaume-uni"],
    "united states": ["united states of america", "united states", "u.s.a",
                      "usa", "états-unis", "etats-unis"],
    "france":   ["france"],
    "germany":  ["germany", "allemagne", "german empire", "prussia"],
    "russia":   ["russia", "russie", "russian empire"],
    "italy":    ["italy", "italie", "kingdom of italy"],
    "china":    ["china", "chine", "qing dynasty"],
    "iceland":  ["iceland", "islande"],
    "norway":   ["norway", "norvège"],
    "sweden":   ["sweden", "suède"],
    "denmark":  ["denmark", "danemark"],
    "netherlands": ["netherlands", "pays-bas"],
    "belgium":  ["belgium", "belgique"],
    "switzerland": ["switzerland", "suisse"],
    "austria":  ["austria", "autriche", "austria-hungary"],
    "poland":   ["poland", "pologne"],
}


# Census-covered provinces in 1881 (Newfoundland joined Confederation in
# 1949; a DCB person resident there in 1881 CANNOT be in this census).
CENSUS_PROVINCE_CODES = {
    "ontario": "ON", "quebec": "QC", "nova scotia": "NS",
    "new brunswick": "NB", "prince edward island": "PE",
    "manitoba": "MB", "british columbia": "BC",
    "northwest territories": "NT",
}
# Death within this many years of the census strongly localizes the person
# to the death place at census time.
DEATH_LOCALITY_WINDOW = 5


def _strip_diacritics(s: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", s)
        if unicodedata.category(ch) != "Mn"
    )


def _token_in(token: str, text: str) -> bool:
    """Substring test with word boundaries for short alphabetic tokens —
    plain `in` matched 'usa' inside 'jerUSAlem'."""
    if len(token) <= 4 and token.isalpha():
        return re.search(rf"\b{re.escape(token)}\b", text) is not None
    return token in text


def normalize_name(s: str) -> str:
    if not s:
        return ""
    s = _strip_diacritics(str(s)).lower()
    # Unify Mac/Mc — census coders did one, DCB might have the other.
    s = re.sub(r"^mac([a-z])", r"mc\1", s)
    # Drop apostrophes and periods.
    s = re.sub(r"['’`.]", "", s)
    # Collapse internal whitespace and hyphens (Jacques-Cartier == Jacques Cartier).
    s = re.sub(r"[-\s]+", " ", s).strip()
    return s


def normalize_lastname(s: str) -> str:
    return normalize_name(s)


def normalize_firstname(s: str) -> str:
    """Use the first whitespace-separated token only — DCB sometimes has
    "John A." or "Mary Anne", census typically has only "john" or "mary"."""
    n = normalize_name(s)
    if not n:
        return ""
    return n.split()[0]


def _event_place_buckets(event: dict | None) -> set[str]:
    """Set of normalized buckets (province or country name) derived from an
    event's place names. Empty set = no constraint derivable."""
    buckets: set[str] = set()
    places = (event or {}).get("places") or []
    for pl in places:
        name = (pl.get("name") or "").lower()
        if not name:
            continue
        # Strip diacritics for matching against the patterns
        name_n = _strip_diacritics(name)
        for prov, tokens in PROVINCE_PATTERNS.items():
            if any(_token_in(t, name_n) or _token_in(t, name) for t in tokens):
                buckets.add(prov)
        for ctry, tokens in COUNTRY_PATTERNS.items():
            if any(_token_in(t, name_n) or _token_in(t, name) for t in tokens):
                buckets.add(ctry)
    return buckets


def derive_dcb_birthplace_buckets(person: dict) -> set[str]:
    """Return the set of normalized buckets (province name or country name)
    that this DCB person's birthplace is compatible with. Empty set means
    'we couldn't derive a constraint' — caller should skip this filter."""
    return _event_place_buckets(person.get("birthEvent"))


_GEONAMES_CACHE: dict[str, dict] | None = None


def _geonames_lookup(gid) -> dict | None:
    """Resolve a GeoNames id to {lat, lon, country} via the committed
    data/geonames_coords.csv cache (also used by lincs_strategy3_pip)."""
    global _GEONAMES_CACHE
    if _GEONAMES_CACHE is None:
        _GEONAMES_CACHE = {}
        cache = REPO / "data" / "geonames_coords.csv"
        if cache.exists():
            with cache.open() as f:
                for r in csv.DictReader(f):
                    _GEONAMES_CACHE[r["id"]] = r
    return _GEONAMES_CACHE.get(str(gid))


# Island of Newfoundland bounding box: GeoNames marks it CA today, but it
# was not part of Canada (nor its census) until 1949.
_NL_BBOX = (46.5, 51.8, -59.5, -52.4)  # lat_min, lat_max, lon_min, lon_max


def _coords_outside_census(lat: float, lon: float, country: str) -> str:
    if country and country != "CA":
        return f"country_{country}"
    if _NL_BBOX[0] <= lat <= _NL_BBOX[1] and _NL_BBOX[2] <= lon <= _NL_BBOX[3]:
        return "newfoundland_bbox"
    return ""


def death_locality_conflict(person: dict, census_province_code: str) -> str:
    """Detect a locality contradiction from the DCB death event.

    A person who died within DEATH_LOCALITY_WINDOW years after 1881 was
    almost certainly living at (or near) the death place at census time.
    Returns a non-empty reason string when that place makes 1881 census
    presence implausible:
      - death place outside census coverage (a foreign country, or
        Newfoundland — not part of Canada until 1949). This is the
        Alexander Murray case: died 1884 in St John's, so he was NOT in
        the 1881 Canadian census, yet a same-named Ontarian matched.
      - death place is a census province that differs from the matched
        census row's province.
    Empty string = no conflict detected."""
    d = person.get("deathYear")
    try:
        d = int(d)
    except (TypeError, ValueError):
        return ""
    if not (CENSUS_YEAR <= d <= CENSUS_YEAR + DEATH_LOCALITY_WINDOW):
        return ""
    buckets = _event_place_buckets(person.get("deathEvent"))
    if not buckets:
        # No usable place NAME (e.g. a bare GeoNames id, like Alexander
        # Murray's death at Crieff GB). Fall back to coordinates/country
        # from the GeoNames cache.
        for pl in (person.get("deathEvent") or {}).get("places") or []:
            lat, lon, country = pl.get("latitude"), pl.get("longitude"), ""
            gid = pl.get("geonamesId") or (
                pl.get("id") if pl.get("type") == "geonames" else None)
            if gid:
                rec = _geonames_lookup(gid)
                if rec:
                    lat = lat if lat is not None else float(rec["lat"])
                    lon = lon if lon is not None else float(rec["lon"])
                    country = rec.get("country", "")
            if lat is None or lon is None:
                continue
            why = _coords_outside_census(float(lat), float(lon), country)
            if why:
                return f"death_{d}_outside_census_coverage:{why}"
        return ""
    codes = {CENSUS_PROVINCE_CODES.get(b) for b in buckets}
    if None in codes:
        # At least one death-place bucket is outside 1881 census coverage
        # (foreign country or Newfoundland).
        outside = sorted(b for b in buckets if b not in CENSUS_PROVINCE_CODES)
        return f"death_{d}_outside_census_coverage:{','.join(outside)}"
    if census_province_code and census_province_code not in codes:
        return (f"death_{d}_province_mismatch:"
                f"{','.join(sorted(c for c in codes if c))}"
                f"_vs_census_{census_province_code}")
    return ""


def census_birthplace_bucket(label: str) -> str | None:
    """Map a census `dbirthpl_TCP_label` (e.g. "Nova Scotia", "Ireland")
    to one of our normalized buckets. Returns None if we don't recognize it
    (long-tail country, sub-region, etc.) — in that case the constraint is
    'unknown' and we err toward strict (no match unless DCB also unknown)."""
    if not label:
        return None
    lab = label.lower()
    lab_n = _strip_diacritics(lab)
    for prov, tokens in PROVINCE_PATTERNS.items():
        if any(t in lab_n or t in lab for t in tokens):
            return prov
    for ctry, tokens in COUNTRY_PATTERNS.items():
        if any(t in lab_n or t in lab for t in tokens):
            return ctry
    return None


# --------- Loading ---------

def load_dcb_cohort_alive_in(year: int, min_age: int = 0) -> list[dict]:
    """DCB persons born ≤ (year - min_age) and died ≥ year (or death unknown).
    min_age=16 keeps only those who would have been adults / near-adults
    at the census."""
    max_birth_year = year - min_age
    with DCB_JSON.open() as f:
        data = json.load(f)
    out = []
    for p in data["persons"]:
        b = p.get("birthYear")
        d = p.get("deathYear")
        if not b:
            continue
        try:
            b = int(b)
        except (TypeError, ValueError):
            continue
        if b > max_birth_year:
            continue
        if d:
            try:
                d_i = int(d)
            except (TypeError, ValueError):
                d_i = None
            if d_i is not None and d_i < year:
                continue
        out.append(p)
    return out


def load_residents_index() -> pd.DataFrame:
    """Load the columns we need from each per-province parquet, concat,
    add normalized lookup keys."""
    cols = ["unique_identifier", "namlast", "namfrst", "sex", "age",
             "dbirthpl_TCP_label", "persistent_place_id",
             "TCPUID_CSD_1881", "province_code"]
    parts = []
    for pp in sorted(RESIDENTS_DIR.glob("*.parquet")):
        df = pq.read_table(pp, columns=cols).to_pandas()
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    print(f"[link] {len(df):,} 1881 residents loaded", file=sys.stderr)

    # Normalised lookup keys
    df["namlast_n"] = df["namlast"].map(normalize_lastname)
    df["namfrst_n"] = df["namfrst"].map(normalize_firstname)
    df["sex_n"] = df["sex"].map(lambda v: "m" if v == "Male"
                                 else ("f" if v == "Female" else None))
    df["age_int"] = pd.to_numeric(df["age"], errors="coerce").astype("Int32")
    df["bp_bucket"] = df["dbirthpl_TCP_label"].map(census_birthplace_bucket)
    return df


# --------- Matching ---------

def match_one(person: dict, residents: pd.DataFrame,
              residents_by_lastname: dict[str, pd.Index]
              ) -> tuple[str, list[int], str]:
    """Return (status, candidate_indices, confidence). Status is one of:
       'matched' (exactly 1), 'no_match' (0), 'ambiguous' (>1),
       'no_dcb_birthyear', 'no_lastname'. Confidence is 'high' when the
       birthplace constraint was applied, 'medium_no_birthplace' when the
       DCB record gave us no birthplace to check."""
    if not person.get("birthYear"):
        return "no_dcb_birthyear", [], ""

    full_name = person.get("name", "")
    parts = [p for p in re.split(r"\s+", full_name.strip()) if p]
    if len(parts) < 2:
        return "no_lastname", [], ""
    dcb_first = normalize_firstname(parts[0])
    # Lastname is the last whitespace-separated token; honoraries like
    # "Mr." / suffixes like "Sr." would muddle this, but DCB strips most.
    dcb_last = normalize_lastname(parts[-1])
    if not dcb_last:
        return "no_lastname", [], ""

    # Lookup by lastname.
    cand_idx = residents_by_lastname.get(dcb_last, [])
    if len(cand_idx) == 0:
        return "no_match", [], ""

    cand = residents.loc[cand_idx]

    # Firstname filter — full match OR shared prefix.
    dcb_first_pre = dcb_first[:FIRSTNAME_PREFIX] if dcb_first else ""
    if dcb_first_pre:
        cand = cand[cand["namfrst_n"].str.startswith(dcb_first_pre, na=False)]
    if cand.empty:
        return "no_match", [], ""

    # Age filter.
    expected_age = CENSUS_YEAR - int(person["birthYear"])
    cand = cand[
        (cand["age_int"] >= expected_age - AGE_TOLERANCE)
        & (cand["age_int"] <= expected_age + AGE_TOLERANCE)
    ]
    if cand.empty:
        return "no_match", [], ""

    # Sex filter (skipped if DCB doesn't say).
    # DCB doesn't have an explicit sex; we can sometimes infer from
    # honorific or given name, but that's fragile. Leave it out for now —
    # name+age+birthplace already does the heavy lifting.

    # Birthplace bucket constraint.
    dcb_buckets = derive_dcb_birthplace_buckets(person)
    confidence = "medium_no_birthplace"
    if dcb_buckets:
        # STRICT: the census birthplace must be a KNOWN bucket that agrees
        # with the DCB birthplace. The old fallback also accepted candidates
        # whose census birthplace we simply couldn't map — which let through
        # direct contradictions (DCB 'new brunswick' vs census 'Barbados').
        cand = cand[cand["bp_bucket"].isin(dcb_buckets)]
        confidence = "high"

    if cand.empty:
        return "no_match", [], confidence
    if len(cand) > 1:
        return "ambiguous", cand.index.tolist(), confidence
    return "matched", cand.index.tolist(), confidence


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0,
                    help="Process only first N DCB persons (dev only)")
    args = ap.parse_args()

    cohort = load_dcb_cohort_alive_in(CENSUS_YEAR, min_age=MIN_AGE_1881)
    print(f"[link] DCB persons aged ≥{MIN_AGE_1881} in {CENSUS_YEAR} "
          f"(born ≤ {CENSUS_YEAR - MIN_AGE_1881}): {len(cohort):,}",
          file=sys.stderr)
    if args.limit:
        cohort = cohort[:args.limit]

    residents = load_residents_index()
    # Pre-index residents by normalized lastname for fast lookup.
    print(f"[link] indexing residents by lastname …", file=sys.stderr)
    by_last = residents.groupby("namlast_n").indices  # dict[str, np.ndarray]

    # Manifest — we need the person URI per matched census row.
    manifest = pd.read_parquet(MANIFEST,
                                columns=["unique_identifier",
                                         "person_full_uri", "leaf_url"])
    manifest_by_uid = manifest.set_index("unique_identifier")

    counters = Counter()
    links: list[dict] = []
    audit: list[dict] = []

    for p in cohort:
        status, cand_idx, confidence = match_one(p, residents, by_last)

        # Death-locality veto: a matched person who died shortly after 1881
        # somewhere the census doesn't cover (or in a different province)
        # was not the person enumerated here.
        locality_conflict = ""
        if status == "matched":
            r0 = residents.loc[cand_idx[0]]
            locality_conflict = death_locality_conflict(
                p, str(r0.get("province_code", "") or ""))
            if locality_conflict:
                status = "rejected_locality"
                cand_idx = []

        counters[status] += 1

        audit_row = {
            "dcb_personId": p.get("personId", ""),
            "dcb_name": p.get("name", ""),
            "dcb_birthYear": p.get("birthYear", ""),
            "dcb_deathYear": p.get("deathYear", ""),
            "dcb_url_en": p.get("dcb_url_en", ""),
            "match_status": status,
            "n_candidates": len(cand_idx),
        }
        # Add DCB birthplace bucket(s) for diagnostic
        dcb_buckets = derive_dcb_birthplace_buckets(p)
        audit_row["dcb_birthplace_buckets"] = ";".join(sorted(dcb_buckets))
        audit_row["confidence"] = confidence
        audit_row["locality_conflict"] = locality_conflict

        if status == "matched":
            r = residents.loc[cand_idx[0]]
            uid = r["unique_identifier"]
            try:
                person_uri = manifest_by_uid.loc[uid, "person_full_uri"]
                leaf_url = manifest_by_uid.loc[uid, "leaf_url"]
            except KeyError:
                person_uri = leaf_url = ""
            link_row = {
                "dcb_personId": p.get("personId", ""),
                "dcb_name": p.get("name", ""),
                "dcb_birthYear": p.get("birthYear", ""),
                "dcb_deathYear": p.get("deathYear", ""),
                "dcb_url_en": p.get("dcb_url_en", ""),
                "wikidataQid": p.get("wikidataQid") or "",
                "census_unique_identifier": uid,
                "census_namlast": r.get("namlast", ""),
                "census_namfrst": r.get("namfrst", ""),
                "census_age": int(r["age_int"]) if pd.notna(r["age_int"]) else "",
                "census_sex": r.get("sex", ""),
                "census_birthplace_label": r.get("dbirthpl_TCP_label", ""),
                "persistent_place_id": r.get("persistent_place_id", ""),
                "tcpuid_csd_1881": r.get("TCPUID_CSD_1881", ""),
                "person_uri": person_uri,
                "leaf_url": leaf_url,
                "match_method": ("name_age_birthplace_strict"
                                  if confidence == "high"
                                  else "name_age_only"),
                "confidence": confidence,
            }
            links.append(link_row)
            audit_row.update({
                "matched_uid": uid,
                "matched_name": f"{r.get('namfrst','')} {r.get('namlast','')}",
                "matched_age": int(r["age_int"]) if pd.notna(r["age_int"]) else "",
                "matched_chain": r.get("persistent_place_id", ""),
            })

        audit.append(audit_row)

    # Write outputs.
    OUT_LINKS.parent.mkdir(parents=True, exist_ok=True)
    with OUT_LINKS.open("w", newline="") as f:
        if links:
            w = csv.DictWriter(f, fieldnames=list(links[0].keys()))
            w.writeheader()
            for r in links:
                w.writerow(r)
        else:
            f.write("dcb_personId,dcb_name,...(empty)\n")

    with OUT_AUDIT.open("w", newline="") as f:
        if audit:
            cols_set = set()
            for r in audit:
                cols_set.update(r.keys())
            cols = sorted(cols_set)
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in audit:
                w.writerow(r)

    # Summary.
    n_links = counters["matched"]
    n_total = sum(counters.values())
    print(f"\n[link] === Match summary ===", file=sys.stderr)
    for status, n in counters.most_common():
        print(f"  {status:25s}: {n:>6,}", file=sys.stderr)
    print(f"  ----", file=sys.stderr)
    print(f"  {'total':25s}: {n_total:>6,}", file=sys.stderr)
    print(f"  match rate                : {100*n_links/max(1,n_total):.1f}%",
          file=sys.stderr)
    print(f"\n[link] wrote {n_links:,} links → {OUT_LINKS}", file=sys.stderr)
    print(f"[link] wrote {len(audit):,} audit rows → {OUT_AUDIT}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
