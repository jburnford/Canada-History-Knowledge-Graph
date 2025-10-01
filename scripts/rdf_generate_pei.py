#!/usr/bin/env python3
"""
Generate RDF (Turtle) for PEI 1911 census subdivisions:
- Population total from V1T1 (generated/ca_1911/observations.csv)
- Wheat production (bushels) if provided in data/pei_wheat_1911.csv

Outputs:
- generated/rdf/pei_1911.ttl

Notes:
- No external deps; emits Turtle as text.
- Base URIs use https://example.org/1911/ (customize via --base).
"""
import csv
from pathlib import Path
import argparse


def load_places(csv_path):
    places = {}
    with open(csv_path, newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            if row.get('province_code') == 'PE':
                places[row['id']] = row
    return places


def load_pop_observations(csv_path, pei_place_ids):
    pop = {}
    with open(csv_path, newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            if row.get('place_id') in pei_place_ids and row.get('year') == '1911':
                pop[row['place_id']] = row.get('pop_total_1911') or ''
    return pop


def load_wheat(csv_path, pei_place_ids):
    data = {}
    p = Path(csv_path)
    if not p.exists():
        return data
    with open(p, newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        # Expect columns: place_id,year,wheat_bushels
        for row in r:
            if row.get('place_id') in pei_place_ids and row.get('year') == '1911':
                data[row['place_id']] = row.get('wheat_bushels') or ''
    return data


def ttl_escape(s: str) -> str:
    return s.replace('"', '\"')


def generate_ttl(base, places, pop, wheat):
    lines = []
    add = lines.append
    add("@prefix qb: <http://purl.org/linked-data/cube#> .")
    add("@prefix sdmx: <http://purl.org/linked-data/sdmx/2009/dimension#> .")
    add("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .")
    add("@prefix skos: <http://www.w3.org/2004/02/skos/core#> .")
    add(f"@prefix ex: <{base}> .\n")

    add(f"ex:dataset/v1t1 a qb:DataSet ;")
    add(f"  skos:prefLabel \"1911 Volume 1 Table 1\" ;")
    add(f"  skos:note \"Population and area by geography\" .\n")

    add(f"ex:indicator/populationTotal a skos:Concept ;")
    add(f"  skos:prefLabel \"Population Total\" .\n")

    add(f"ex:indicator/wheatBushels a skos:Concept ;")
    add(f"  skos:prefLabel \"Wheat Production (bushels)\" .\n")

    for pid, p in places.items():
        name = ttl_escape(p.get('name',''))
        add(f"ex:place/{pid} a ex:Place ; skos:prefLabel \"{name}\" ; ex:provinceCode \"PE\" .")

    # Observations for population
    for pid, val in pop.items():
        if not val:
            continue
        obs_uri = f"ex:obs/v1t1/{pid}"
        add(f"{obs_uri} a qb:Observation ;")
        add(f"  qb:dataSet ex:dataset/v1t1 ;")
        add(f"  sdmx:refArea ex:place/{pid} ;")
        add(f"  sdmx:refPeriod \"1911\"^^xsd:gYear ;")
        add(f"  ex:populationTotal {val} .")

    # Observations for wheat
    for pid, val in wheat.items():
        if not val:
            continue
        obs_uri = f"ex:obs/agri1911/{pid}"
        add(f"{obs_uri} a qb:Observation ;")
        add(f"  qb:dataSet ex:dataset/agri1911 ;")
        add(f"  sdmx:refArea ex:place/{pid} ;")
        add(f"  sdmx:refPeriod \"1911\"^^xsd:gYear ;")
        add(f"  ex:wheatBushels {val} .")

    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='https://example.org/1911/', help='Base URI for RDF resources')
    ap.add_argument('--places', default='generated/ca_1911/places.csv')
    ap.add_argument('--observations', default='generated/ca_1911/observations.csv')
    ap.add_argument('--wheat', default='data/pei_wheat_1911.csv', help='Optional CSV with columns: place_id,year,wheat_bushels')
    ap.add_argument('--out', default='generated/rdf/pei_1911.ttl')
    args = ap.parse_args()

    places = load_places(args.places)
    pop = load_pop_observations(args.observations, set(places.keys()))
    wheat = load_wheat(args.wheat, set(places.keys()))

    ttl = generate_ttl(args.base, places, pop, wheat)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(ttl, encoding='utf-8')
    print(f"Wrote {out_path} ({len(ttl.splitlines())} lines) | places={len(places)} pop_obs={len([v for v in pop.values() if v])} wheat_obs={len([v for v in wheat.values() if v])}")

if __name__ == '__main__':
    main()

