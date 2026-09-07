"""Read-only census reconciliation and independently reproducible panel algebra.

Run from the repository root. The county names and codes are checked together;
no historical continuity or GIS identity is inferred. Subdivision sums are
explicitly observed-cell subtotals: blanks never become asserted zeros.
"""
from pathlib import Path
from decimal import Decimal
from collections import defaultdict, Counter
import csv, gzip, hashlib, json, sqlite3, unicodedata, re
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
KEYS = ["1851_V2T6_CD_202306", "1851_V2T6_CSD_202306"]
VARIABLES = ["WHT_XX_A", "WHT_XX_B", "OAT_XX_A", "OAT_XX_B",
             "FML_XX_A", "FRMLU_CLT_A", "FRMLU_CRP_A", "FRMLU_PST_A"]

def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z]", "", s)
    return {"twomountain": "twomountains", "vaundreuil": "vaudreuil",
            "montmerenci": "montmorency", "montmorenci": "montmorency",
            "sandstead": "stanstead", "standstead": "stanstead"}.get(s, s)

def dump_csv(name, rows):
    if rows:
        with (OUT / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

def read(key):
    dbpath = ROOT / "data_quality/lod_census_sources" / key / "source_observations.sqlite"
    with sqlite3.connect(f"file:{dbpath}?mode=ro", uri=True) as c:
        c.row_factory = sqlite3.Row
        source = dict(c.execute("SELECT * FROM source").fetchone())
        rows = {r["unit_id"]: dict(r) for r in c.execute(
            "SELECT * FROM reporting_units WHERE province='QC'")}
        defs = {r["column_key"]: dict(r) for r in c.execute("SELECT * FROM source_columns")}
        cells = []
        for r in c.execute("SELECT * FROM observations WHERE variable IN (%s)" %
                           ",".join("?" for _ in VARIABLES), VARIABLES):
            if r["unit_id"] not in rows:
                continue
            r = dict(r); u = rows[r["unit_id"]]
            m = json.loads(u["source_metadata_json"])
            r.update(county_code=m["TCPUID_CD_1851"], county=m["NAME_CD_1851"],
                     label=u["label"], excel_row=u["excel_row"], source_key=key)
            r["definition"] = defs[r["column_key"]]["definition"]
            cells.append(r)
        return source, rows, cells

def main():
    provenance, allcells, evidence = [], [], []
    for key in KEYS:
        source, rows, cells = read(key)
        assert source["census_vintage"] == 1851
        expected_level = "census_division_total" if "_CD_" in key else "census_subdivision_reporting_unit"
        assert {u["reporting_level"] for u in rows.values()} == {expected_level}
        provenance.append(source)
        allcells.extend(cells)
        selected = {(c["unit_id"], c["column_key"]): c for c in cells}
        found = set()
        path = ROOT / "data_quality/rdf_site/sources" / key / "cells.jsonl.gz"
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                j = json.loads(line); pair = (j["unit_id"], j["column_key"])
                if pair not in selected: continue
                cell = selected[pair]
                assert j["rdf_decimal"] == cell["numeric_value"]
                assert j["workbook_sha256"] == source["sha256"]
                cell["citation_url"] = j["citation_url"]
                evidence.append(j); found.add(pair)
        assert found == selected.keys()
    with gzip.open(OUT / "source_cells.jsonl.gz", "wt", encoding="utf-8") as f:
        for j in evidence: f.write(json.dumps(j, ensure_ascii=False) + "\n")

    grouped = defaultdict(list)
    for c in allcells: grouped[(c["source_key"], c["county_code"], c["variable"])].append(c)
    reports = []
    for (key, county, var), cs in grouped.items():
        if key != KEYS[0]: continue
        assert len(cs) == 1
        cd = cs[0]; sub = grouped[(KEYS[1], county, var)]
        assert {norm(x["county"]) for x in sub} == {norm(cd["county"])}
        numeric = [x for x in sub if x["numeric_value"] is not None]
        subtotal = sum((Decimal(x["numeric_value"]) for x in numeric), Decimal(0)) if numeric else None
        published = Decimal(cd["numeric_value"]) if cd["numeric_value"] is not None else None
        reports.append(dict(county_code=county, county=cd["county"], variable=var,
                            county_reported=published, subdivision_observed_subtotal=subtotal,
                            subtotal_minus_county=None if subtotal is None or published is None else subtotal-published,
                            subdivision_rows=len(sub), numeric_rows=len(numeric),
                            nonnumeric_rows=len(sub)-len(numeric),
                            status="complete_numeric_comparison" if len(numeric)==len(sub) else "partial_observed_subtotal",
                            county_citation=cd["citation_url"]))
    dump_csv("county_reconciliation.csv", reports)

    # Independently read the four workbook cells implicated by the printed page.
    from openpyxl import load_workbook
    src = provenance[0]
    wb = load_workbook(src["path"], read_only=True, data_only=True)
    assert hashlib.sha256(Path(src["path"]).read_bytes()).hexdigest() == src["sha256"]
    ws = wb[src["sheet"]]
    printed = [(69,"St. Maurice","S",12531,10217), (69,"St. Maurice","T",70060,80711),
               (70,"Saguenay","S",10217,12531), (70,"Saguenay","T",80711,70060)]
    direct = []
    for row, county, col, exported, original in printed:
        assert Decimal(str(ws[f"{col}{row}"].value)) == Decimal(exported)
        cell = next(c for c in allcells if c["source_key"]==KEYS[0] and c["excel_row"]==row and c["column_key"]==col)
        assert Decimal(cell["numeric_value"]) == exported
        direct.append(dict(county=county, workbook_cell=f"{col}{row}", workbook_value=exported,
                           english_print_value=original, printed_page=131, pdf_page=189,
                           citation=cell["citation_url"], verification="visual inspection of printed page plus workbook/SQLite/JSONL equality"))
    wb.close(); dump_csv("verified_print_discrepancies.csv", direct)

    # Algebraic identification check, not an estimated historical regression.
    # Linear settlement duration is exactly calendar year minus settlement date.
    years = np.array([1739,1784,1831]); starts = np.array([1608,1642,1680,1710,1730])
    year = np.tile(years,len(starts)); place = np.repeat(np.arange(len(starts)),len(years))
    duration = year - np.repeat(starts,len(years))
    X = np.column_stack([np.ones(len(year)), *[(place==i).astype(float) for i in range(1,len(starts))],
                         *[(year==y).astype(float) for y in years[1:]]])
    b = np.linalg.lstsq(X,duration,rcond=None)[0]
    residual = duration-X@b
    assert max(abs(residual)) < 1e-9
    rank = int(np.linalg.matrix_rank(X)); rank_plus = int(np.linalg.matrix_rank(np.column_stack([X,duration])))
    assert rank == rank_plus
    validation = dict(source_cells=len(evidence), selected_sqlite_jsonl_mismatches=0,
                      verified_workbook_cells=4, confirmed_print_discrepancies=4,
                      reconciliation_rows=len(reports),
                      equation2_linear_duration_check=dict(example_is_synthetic=True,rank_without_duration=rank,
                        rank_with_duration=rank_plus,max_abs_duration_residual=float(max(abs(residual)))),
                      historical_regressions_replicated=False,
                      conclusion="The linear duration term adds no independent variation to place and date fixed effects; this does not invalidate separately estimated date effects.")
    (OUT / "validation.json").write_text(json.dumps(validation,indent=2)+"\n")
    (OUT / "provenance.json").write_text(json.dumps(provenance,indent=2)+"\n")
    print(json.dumps(validation,indent=2))

if __name__ == "__main__": main()
