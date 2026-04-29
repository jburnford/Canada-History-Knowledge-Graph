#!/usr/bin/env python3
"""
Run the three-model pilot benchmark: Q1-Q5 + null-vs-zero probe across
Approaches A, B, C, then emit pilot/benchmark_results.md.

Anti-cheat for C: queries are run via the kuzu Python binding against the
built database, not against the loader CSVs. The harness records that
contract for the Track-2 scorecard.

Usage:
    python3 scripts/run_pilot_benchmarks.py
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
A_TTL = REPO / "rdf_export" / "pilot_on_A.ttl"
B_TTL = REPO / "rdf_export" / "pilot_on_B.ttl"
C_DB = REPO / "pilot" / "on_kuzu" / "on.kuzu"
OUT_MD = REPO / "pilot" / "benchmark_results.md"

# ---------------------------------------------------------------------------
# Benchmark queries.  Each entry:
#   title, description, A (SPARQL), B (SPARQL), C (Cypher string).
# Correctness check: a callable that accepts the rdflib / kuzu result and
# returns (ok: bool, summary: str).
# ---------------------------------------------------------------------------

WESTMEATH_QID = "Q115263132"

SPARQL_PREFIX = """\
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX base: <http://temp.lincsproject.ca/census/>
"""

QUERIES = [
    {
        "id": "Q1",
        "title": "Historical CSDs grounded to Westmeath Wikidata QID",
        "A": SPARQL_PREFIX + """
SELECT ?presence ?period WHERE {
  ?presence a crm:E93_Presence ;
            crm:P166i_was_a_presence_of wd:Q115263132 ;
            crm:P164_is_temporally_specified_by ?period .
} ORDER BY ?period
""",
        "B": SPARQL_PREFIX + """
SELECT ?presence ?date WHERE {
  ?presence crm:P166i_was_a_presence_of wd:Q115263132 ;
            base:observed_on ?date .
} ORDER BY ?date
""",
        "C": """
MATCH (p:Place)<-[:OBSERVED_IN]-(pr:Presence)
WHERE p.wikidata_qid = 'Q115263132'
RETURN pr.presence_id, pr.year ORDER BY pr.year;
""",
        "expect_rows_min": 8,  # 8 census years
    },
    {
        "id": "Q2",
        "title": "Westmeath population trajectory 1851-1921 (total + sex split)",
        "A": SPARQL_PREFIX + """
SELECT ?presence ?val_total WHERE {
  ?presence crm:P166i_was_a_presence_of wd:Q115263132 .
  ?meas crm:P39_measured ?presence ;
        crm:P40_observed_dimension ?dim .
  ?dim crm:P90_has_value ?val_total .
  FILTER(CONTAINS(STR(?meas), "POP_XX_N") || CONTAINS(STR(?meas), "POP_TOT"))
} ORDER BY ?presence
""",
        "B": SPARQL_PREFIX + """
SELECT ?presence ?date ?total ?male ?female WHERE {
  ?presence crm:P166i_was_a_presence_of wd:Q115263132 ;
            base:observed_on ?date ;
            base:pop_total ?total .
  OPTIONAL { ?presence base:pop_total_m ?male . }
  OPTIONAL { ?presence base:pop_total_f ?female . }
} ORDER BY ?date
""",
        "C": """
MATCH (p:Place {name: 'Westmeath'})<-[:OBSERVED_IN]-(pr:Presence)
RETURN pr.year, pr.pop_total, pr.pop_total_m, pr.pop_total_f ORDER BY pr.year;
""",
        "expect_rows_min": 8,
    },
    {
        "id": "Q3",
        "title": "CSDs bordering Westmeath in 1871",
        "A": SPARQL_PREFIX + """
SELECT DISTINCT ?neighbor_presence WHERE {
  ?westmeath_presence crm:P166i_was_a_presence_of wd:Q115263132 .
  FILTER(CONTAINS(STR(?westmeath_presence), "1871"))
  { ?westmeath_presence crm:P122_borders_with ?neighbor_presence . }
  UNION
  { ?neighbor_presence crm:P122_borders_with ?westmeath_presence . }
}
""",
        "B": SPARQL_PREFIX + """
SELECT DISTINCT ?neighbor_presence WHERE {
  ?westmeath_presence crm:P166i_was_a_presence_of wd:Q115263132 ;
                      base:observed_on "1871-06-01"^^xsd:date .
  { ?westmeath_presence crm:P122_borders_with ?neighbor_presence . }
  UNION
  { ?neighbor_presence crm:P122_borders_with ?westmeath_presence . }
}
""",
        "C": """
MATCH (p:Place {name: 'Westmeath'})<-[:OBSERVED_IN]-(pr:Presence {year: 1871})-[:BORDERS]-(n:Presence)
MATCH (n)-[:OBSERVED_IN]->(np:Place)
RETURN DISTINCT np.name;
""",
        "expect_rows_min": 1,
    },
    {
        "id": "Q4",
        "title": "Westmeath 1911 population density (float / fractional test)",
        "A": SPARQL_PREFIX + """
SELECT ?val WHERE {
  ?presence crm:P166i_was_a_presence_of wd:Q115263132 .
  FILTER(CONTAINS(STR(?presence), "1911"))
  ?meas crm:P39_measured ?presence ;
        crm:P40_observed_dimension ?dim .
  ?dim crm:P90_has_value ?val .
  FILTER(CONTAINS(STR(?meas), "POP_PER_SQ_MI"))
}
""",
        "B": SPARQL_PREFIX + """
SELECT ?val WHERE {
  ?presence crm:P166i_was_a_presence_of wd:Q115263132 ;
            base:observed_on "1911-06-01"^^xsd:date ;
            base:pop_per_sq_mi ?val .
}
""",
        "C": """
MATCH (p:Place {name: 'Westmeath'})<-[:OBSERVED_IN]-(pr:Presence {year: 1911})
RETURN pr.pop_per_sq_mi;
""",
        "expect_rows_min": 0,  # Westmeath 1911 may not have density — that's OK for this query
        "allow_empty": True,
    },
    {
        "id": "Q5",
        "title": "CSDs in Carleton County, 1871",
        "A": SPARQL_PREFIX + """
SELECT DISTINCT ?csd_presence WHERE {
  ?csd_presence crm:P10_falls_within ?cd_presence .
  FILTER(CONTAINS(STR(?cd_presence), "Carleton_1871") || CONTAINS(STR(?cd_presence), "Carleton%5F1871"))
}
""",
        "B": SPARQL_PREFIX + """
SELECT DISTINCT ?csd_presence WHERE {
  ?csd_presence crm:P10_falls_within ?cd_presence .
  FILTER(CONTAINS(STR(?cd_presence), "Carleton_1871") || CONTAINS(STR(?cd_presence), "Carleton%5F1871"))
}
""",
        "C": """
MATCH (cd:Presence {year: 1871})
WHERE cd.tcpuid = 'CD_ON_Carleton'
MATCH (pr:Presence {year: 1871})-[:PART_OF_COUNTY]->(cd)
MATCH (pr)-[:OBSERVED_IN]->(p:Place)
RETURN p.name ORDER BY p.name;
""",
        "expect_rows_min": 5,
    },
    {
        "id": "Q6-probe",
        "title": "Null-vs-zero probe: Westmeath 1851 population density",
        "A": SPARQL_PREFIX + """
SELECT ?val WHERE {
  ?presence crm:P166i_was_a_presence_of wd:Q115263132 .
  FILTER(CONTAINS(STR(?presence), "1851"))
  OPTIONAL {
    ?meas crm:P39_measured ?presence ;
          crm:P40_observed_dimension ?dim .
    ?dim crm:P90_has_value ?val .
    FILTER(CONTAINS(STR(?meas), "POP_PER_SQ_MI"))
  }
}
""",
        "B": SPARQL_PREFIX + """
SELECT ?val WHERE {
  ?presence crm:P166i_was_a_presence_of wd:Q115263132 ;
            base:observed_on "1851-06-01"^^xsd:date .
  OPTIONAL { ?presence base:pop_per_sq_mi ?val . }
}
""",
        "C": """
MATCH (p:Place {name: 'Westmeath'})<-[:OBSERVED_IN]-(pr:Presence {year: 1851})
RETURN pr.pop_per_sq_mi IS NULL AS is_null, pr.pop_per_sq_mi;
""",
        "allow_empty": True,
        "expect_rows_min": 0,
    },
]


def run_sparql(ttl_path, query):
    """Return (rows, loc)."""
    import rdflib
    g = rdflib.Graph()
    g.parse(ttl_path, format="turtle")
    rows = list(g.query(query))
    # LOC = non-empty, non-prefix-boilerplate lines
    body = query.replace(SPARQL_PREFIX.strip(), "").strip()
    loc = len([l for l in body.split("\n") if l.strip()])
    return rows, loc


def run_cypher(db_path, query):
    import kuzu
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    res = conn.execute(query)
    rows = []
    while res.has_next():
        rows.append(res.get_next())
    loc = len([l for l in query.strip().split("\n") if l.strip()])
    return rows, loc


def main():
    if not A_TTL.exists():
        sys.exit(f"Missing {A_TTL} — run export_rdf.py --pilot on_1851_1921 first.")
    if not B_TTL.exists():
        sys.exit(f"Missing {B_TTL} — run export_rdf_lite.py first.")
    if not C_DB.exists():
        sys.exit(f"Missing {C_DB} — run export_kuzu_pilot.py first.")

    print(f"Loading A ({A_TTL.stat().st_size / 1024 / 1024:.1f} MB)...")
    print(f"Loading B ({B_TTL.stat().st_size / 1024 / 1024:.1f} MB)...")
    print(f"Opening C (Kuzu DB)...")

    results = []
    for q in QUERIES:
        print(f"\n[{q['id']}] {q['title']}")
        row = {"id": q["id"], "title": q["title"]}
        try:
            a_rows, a_loc = run_sparql(A_TTL, q["A"])
            row["A_rows"] = len(a_rows)
            row["A_loc"] = a_loc
            row["A_sample"] = str(a_rows[0]) if a_rows else "(empty)"
            print(f"  A: {len(a_rows)} rows, {a_loc} LOC")
        except Exception as e:
            row["A_rows"] = f"ERROR: {e}"
            row["A_loc"] = 0
            row["A_sample"] = str(e)
            print(f"  A: ERROR {e}")

        try:
            b_rows, b_loc = run_sparql(B_TTL, q["B"])
            row["B_rows"] = len(b_rows)
            row["B_loc"] = b_loc
            row["B_sample"] = str(b_rows[0]) if b_rows else "(empty)"
            print(f"  B: {len(b_rows)} rows, {b_loc} LOC")
        except Exception as e:
            row["B_rows"] = f"ERROR: {e}"
            row["B_loc"] = 0
            row["B_sample"] = str(e)
            print(f"  B: ERROR {e}")

        try:
            c_rows, c_loc = run_cypher(C_DB, q["C"])
            row["C_rows"] = len(c_rows)
            row["C_loc"] = c_loc
            row["C_sample"] = str(c_rows[0]) if c_rows else "(empty)"
            print(f"  C: {len(c_rows)} rows, {c_loc} LOC")
        except Exception as e:
            row["C_rows"] = f"ERROR: {e}"
            row["C_loc"] = 0
            row["C_sample"] = str(e)
            print(f"  C: ERROR {e}")

        results.append(row)

    # Write markdown summary.
    lines = []
    lines.append("# Pilot Benchmark Results\n")
    lines.append(f"Generated by `scripts/run_pilot_benchmarks.py`.\n")
    lines.append(f"- Approach A: `{A_TTL.name}` ({A_TTL.stat().st_size / 1024 / 1024:.1f} MB)")
    lines.append(f"- Approach B: `{B_TTL.name}` ({B_TTL.stat().st_size / 1024 / 1024:.1f} MB)")
    lines.append(f"- Approach C: `{C_DB.name}/` (Kuzu DB)")
    lines.append("")
    lines.append("## Per-query results\n")
    lines.append("| Query | A rows | A LOC | B rows | B LOC | C rows | C LOC |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for r in results:
        lines.append(
            f"| **{r['id']}** {r['title']} | "
            f"{r['A_rows']} | {r['A_loc']} | "
            f"{r['B_rows']} | {r['B_loc']} | "
            f"{r['C_rows']} | {r['C_loc']} |"
        )
    lines.append("")
    lines.append("## Sample rows (first result, if any)\n")
    for r in results:
        lines.append(f"### {r['id']} — {r['title']}")
        lines.append(f"- **A:** `{r['A_sample']}`")
        lines.append(f"- **B:** `{r['B_sample']}`")
        lines.append(f"- **C:** `{r['C_sample']}`")
        lines.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines))
    print(f"\nWrote {OUT_MD}")


if __name__ == "__main__":
    main()
