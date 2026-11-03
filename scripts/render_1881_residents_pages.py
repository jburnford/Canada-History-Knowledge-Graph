#!/usr/bin/env python3
"""Stage 5b.5 — Render per-CSD residents pages for the 1881 census.

Inputs:
  residents_1881_output/by_province/*.parquet
  residents_1881_output/csd_1881_summary.parquet
  residents_1881_output/residents_1881_uri_manifest.parquet
  residents_1881_output/dbirthpl_qid_xref.csv
  persistent_places_output/persistent_place_registry.csv

Output: rag_site/places/<prov>/<slug>-<tcpuid>-1881/residents/...
  index.html              CSD overview (always).
  residents.ttl           CIDOC-CRM Turtle for all residents of the CSD
                          (always, at CSD-overview level so a single
                          dereference covers every #p-id fragment).
  <sdistlet>/<letter>/    Leaf pages for split CSDs only.
    index.html            Per-leaf table.

Each HTML page embeds:
  - <link rel="canonical">
  - schema.org JSON-LD (page-level Dataset only; per-row triples live in
    the parent CSD's residents.ttl).
  - <link rel="alternate" type="text/turtle" href="...residents.ttl">
  - tiny client-side filter (~600 B JS).

Build-time guards:
  - rag_site/ size warn at 800 MB, hard-fail at 950 MB.
  - Every chain in the manifest gets at least an overview page.
"""
from __future__ import annotations

import argparse
import csv
import gc
import html
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fix_mojibake import fix_mojibake  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "residents_1881_output"
PROVINCE_DIR = OUT_DIR / "by_province"
SUMMARY = OUT_DIR / "csd_1881_summary.parquet"
MANIFEST = OUT_DIR / "residents_1881_uri_manifest.parquet"
DBIRTHPL_XREF = OUT_DIR / "dbirthpl_qid_xref.csv"
REGISTRY = REPO / "persistent_places_output" / "persistent_place_registry.csv"
SITE_OUT = REPO / "rag_site"

DEFAULT_SITE_URL = "https://jimclifford.ca"
DEFAULT_BASE_PATH = "/hgiscanada"

# Size guards (rag_site/ post-render, includes any pre-existing rendering).
# Baseline: the deployed 2026-05-07 build already measured 1,043 MB, so the
# old 950 MB hard cap was below reality and tripped on a +2% delta after
# the 2026-08-09 re-chaining. These caps exist to catch RUNAWAY growth
# (e.g. accidentally enabling the ~500 MB TTL sidecars), not organic drift.
WARN_SIZE_BYTES = 1100 * 1024 * 1024
FAIL_SIZE_BYTES = 1300 * 1024 * 1024

# Borealis citation
BOREALIS_DOI = "https://doi.org/10.5683/SP3/FXZEVO"
BOREALIS_CITATION = (
    "TCP / Dillon 1881 Canadian Census, deposited at Borealis "
    "(doi:10.5683/SP3/FXZEVO). Provided by Lisa Dillon and the "
    "Programme de recherche en démographie historique."
)

WIKIDATA_BASE = "http://www.wikidata.org/entity/"

# CIDOC / LINCS prefixes. The @base directive at emission time makes per-row
# fragment URIs relative — saves ~80% of the raw Turtle bytes vs absolute IRIs.
TTL_PREFIXES_TEMPLATE = """\
@base <{base}> .
@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .
@prefix crmdig: <http://www.ics.forth.gr/isl/CRMdig/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix wd: <http://www.wikidata.org/entity/> .
@prefix dcterms: <http://purl.org/dc/terms/> .

"""


# ---- HTML primitives ------------------------------------------------------

# Shared CSS extracted to a single file to avoid emitting ~1 KB of inline
# styles on every one of 33K pages (saves ~30 MB on the rendered output).
SHARED_CSS_PATH = "residents.css"  # Resolved relative to {css_href} in template
SHARED_CSS = """body{font-family:-apple-system,"Segoe UI",sans-serif;max-width:1100px;
margin:1em auto;padding:0 1em;line-height:1.4;color:#222}
h1{border-bottom:1px solid #ccc;padding-bottom:.3em;margin-bottom:.5em}
.crumbs{font-size:.9em;color:#555;margin-bottom:.5em}
.crumbs a{color:#06a}
.summary{background:#f5f7fa;border-left:3px solid #06c;padding:.5em 1em;
margin:1em 0;font-size:.92em}
.summary table{border:0;margin:.3em 0}
.summary td{padding:0 1em 0 0;border:0}
.filter{margin:1em 0}
.filter input{font-size:1em;padding:.4em .6em;width:18em;max-width:90%}
table.residents{border-collapse:collapse;font-size:.85em;width:100%}
table.residents th,table.residents td{border-bottom:1px solid #e5e5e5;
padding:3px 6px;vertical-align:top;text-align:left}
table.residents th{background:#f0f0f0;position:sticky;top:0;z-index:1}
table.residents tbody tr:target{background:#ffd}
table.residents tbody tr:hover{background:#fafafa}
.browse ul{column-count:3;list-style:none;padding-left:0}
.browse li{break-inside:avoid;padding:.15em 0}
footer{margin-top:3em;padding-top:.5em;border-top:1px solid #ddd;
font-size:.8em;color:#666}
a{color:#06a}
.mute{color:#888}
a.dcb{display:inline-block;font-size:.7em;font-weight:bold;background:#ffa;
color:#444;text-decoration:none;padding:0 4px;margin-left:4px;
border-radius:2px;border:1px solid #d8c}
a.dcb:hover{background:#ff8;color:#000}
"""

PAGE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">
{ttl_link}<link rel="stylesheet" href="{css_href}">
<meta property="og:title" content="{title}">
<meta property="og:type" content="article">
<meta property="og:url" content="{canonical}">
<meta name="robots" content="{robots}">
</head>
<body>
<article>
<div class="crumbs">{crumbs}</div>
<h1>{heading}</h1>
"""

PAGE_FOOT = """
<script type="application/ld+json">
{jsonld}
</script>
<footer>
<p>Source: <a href="{borealis_doi}">{borealis_doi_label}</a> — {borealis_citation}<br>
Page generated by the <a href="https://github.com/jburnford/Canada-History-Knowledge-Graph">HGIS Canada Knowledge Graph</a>
project; this page is part of the HGIS Canada static site at
<a href="{site_url}{base_path}/">jimclifford.ca/hgiscanada</a>.</p>
</footer>
</article>
{filter_script}
</body>
</html>
"""

FILTER_SCRIPT = """
<script>
(function(){
  var q=document.getElementById('q');
  if(!q)return;
  var rows=[].slice.call(document.querySelectorAll('#rows tr'));
  rows.forEach(function(r){r.dataset.s=r.textContent.toLowerCase()});
  var t;
  q.addEventListener('input',function(){
    clearTimeout(t);
    t=setTimeout(function(){
      var v=q.value.trim().toLowerCase();
      rows.forEach(function(r){r.hidden=v&&r.dataset.s.indexOf(v)===-1});
    },150);
  });
})();
</script>
"""


# ---- Slug + URL helpers ---------------------------------------------------

SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(s: str) -> str:
    return SLUG_RE.sub("-", s.lower()).strip("-")


def hesc(s: object) -> str:
    """Mojibake-fix + HTML-escape."""
    if s is None:
        return ""
    return html.escape(str(fix_mojibake(s)))


def safe_int(v: object) -> str:
    if v is None or pd.isna(v):
        return ""
    try:
        return str(int(v))
    except (TypeError, ValueError):
        return ""


# ---- Loading sidecar data --------------------------------------------------

def load_dbirthpl_xref() -> dict[str, dict]:
    """{code -> {'qid','qid_label','status'}}."""
    out: dict[str, dict] = {}
    if not DBIRTHPL_XREF.exists():
        return out
    with DBIRTHPL_XREF.open() as f:
        rd = csv.DictReader(f)
        for row in rd:
            out[row["code"]] = {
                "qid": row.get("qid", ""),
                "qid_label": row.get("qid_label", ""),
                "status": row.get("status", "ungrounded"),
            }
    return out


DCB_LINKS_PATH = REPO / "data" / "dcb_1881_residents_links.csv"


def load_dcb_links() -> dict[str, dict]:
    """{census_unique_identifier -> {dcb_url, dcb_name}} from the strict
    DCB↔1881 matcher (scripts/link_dcb_to_1881_residents.py). Empty dict
    if the matcher hasn't been run yet — DCB icons just won't appear."""
    out: dict[str, dict] = {}
    if not DCB_LINKS_PATH.exists():
        return out
    skipped_medium = 0
    with DCB_LINKS_PATH.open() as f:
        rd = csv.DictReader(f)
        for row in rd:
            uid = row.get("census_unique_identifier", "")
            url = row.get("dcb_url_en", "")
            # The DCB badge asserts identity; only high-confidence matches
            # (name + age + birthplace agreement) meet the pipeline's
            # zero-false-positive bar. Medium (name+age only) links stay in
            # the CSV for curation but don't render.
            conf = row.get("confidence", "high")
            if conf and conf != "high":
                skipped_medium += 1
                continue
            if uid and url:
                out[uid] = {
                    "url": url,
                    "name": row.get("dcb_name", ""),
                }
    if skipped_medium:
        print(f"[render] withheld {skipped_medium} medium-confidence DCB "
              f"badges (name+age only, no birthplace corroboration)",
              file=sys.stderr)
    return out


def load_registry() -> dict[str, dict]:
    """{persistent_place_id -> {'canonical_name','province'}}."""
    out: dict[str, dict] = {}
    with REGISTRY.open() as f:
        rd = csv.DictReader(f)
        for row in rd:
            out[row["persistent_place_id"]] = {
                "canonical_name": row["canonical_name"],
                "province": row["province"].upper(),
                "anchor_year": row["anchor_year"],
                "years_active": row["years_active"],
                "num_years": int(row["num_years"]),
            }
    return out


def load_summary() -> dict[str, dict]:
    """{persistent_place_id -> summary dict}."""
    df = pd.read_parquet(SUMMARY)
    return df.set_index("persistent_place_id").to_dict(orient="index")


def load_manifest_for_chain(manifest: pd.DataFrame, pid: str) -> pd.DataFrame:
    return manifest[manifest["persistent_place_id"] == pid]


# ---- Section renderers ----------------------------------------------------

def render_summary_panel(summary: dict | None) -> str:
    if not summary:
        return ""
    total = int(summary.get("total_residents", 0))
    male = int(summary.get("sex_male", 0))
    female = int(summary.get("sex_female", 0))
    other = int(summary.get("sex_other", 0))
    unk = int(summary.get("sex_unknown", 0))
    pct = lambda n: f" ({n*100/total:.1f}%)" if total else ""
    rows = [
        f"<tr><td><strong>Total residents</strong></td>"
        f"<td>{total:,}</td></tr>",
        f"<tr><td>Male</td><td>{male:,}{pct(male)}</td></tr>",
        f"<tr><td>Female</td><td>{female:,}{pct(female)}</td></tr>",
    ]
    if other:
        rows.append(f"<tr><td>Other</td><td>{other:,}{pct(other)}</td></tr>")
    if unk:
        rows.append(f"<tr><td>Sex unknown</td><td>{unk:,}{pct(unk)}</td></tr>")

    age_buckets = ["0-4", "5-9", "10-14", "15-19", "20-24", "25-34",
                   "35-44", "45-54", "55-64", "65-74", "75+"]
    age_html = " ".join(
        f"<span><strong>{lbl}:</strong> "
        f"{int(summary.get(f'age_{lbl}', 0)):,}</span>"
        for lbl in age_buckets
    )

    def _topline(field: str, label: str, n: int = 5) -> str:
        raw = summary.get(field, "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except json.JSONDecodeError:
            items = []
        items = items[:n]
        if not items:
            return ""
        bits = ", ".join(
            f"{hesc(lbl)} ({c:,})" for lbl, c in items
        )
        return f"<p><strong>{label}:</strong> {bits}</p>"

    return (
        '<section class="summary">\n'
        '<table><tbody>' + "\n".join(rows) + '</tbody></table>\n'
        f'<p><strong>Age:</strong> {age_html}</p>\n'
        f'{_topline("top_religion", "Top religions")}'
        f'{_topline("top_origin", "Top origins")}'
        f'{_topline("top_occupation", "Top occupations", n=8)}'
        f'{_topline("top_birthplace", "Top birthplaces")}'
        '</section>'
    )


def render_residents_table(rows: pd.DataFrame, dbirthpl_xref: dict,
                            dcb_links: dict | None = None) -> str:
    """rows is a small dataframe (≤ 1000 rows). Returns the table HTML.

    Compact-row format: drops source NAC ref column (recoverable from the
    Borealis deposit), drops the permalink anchor wrapper on the line-number
    column (the row's id="p-X" still works for fragment dereferencing via
    :target CSS). Wikidata link kept on grounded birthplaces — that's the
    LOD payload of the page.

    When `dcb_links` is provided (output of scripts/link_dcb_to_1881_residents.py),
    rows whose unique_identifier matches a DCB person get a small DCB icon
    after the surname linking to the biography.
    """
    dcb_links = dcb_links or {}
    head = (
        '<table class="residents">\n<thead><tr>'
        '<th>#</th><th>Surname</th><th>Given</th>'
        '<th>Sex</th><th>Age</th>'
        '<th>Religion</th><th>Origin</th><th>Birthplace</th>'
        '<th>Occupation</th><th>HH</th>'
        '</tr></thead>\n<tbody id="rows">'
    )
    body_lines = []
    for _, r in rows.iterrows():
        rid = r["unique_identifier"]
        namlast = hesc(r.get("namlast", ""))
        namfrst = hesc(r.get("namfrst", ""))
        # DCB icon for matched persons. Strict matcher: only ~914 rows of
        # 4.16M get this, so the per-row cost is negligible.
        dcb = dcb_links.get(str(rid))
        if dcb:
            namlast = (
                f'{namlast} <a href="{html.escape(dcb["url"])}" '
                f'class="dcb" title="Dictionary of Canadian Biography: '
                f'{html.escape(dcb["name"])}">DCB</a>'
            )
        # Sex: M/F are common; emit single-char to save bytes (4M × 3 bytes).
        sex_raw = (r.get("sex") or "")
        sex = "M" if sex_raw == "Male" else ("F" if sex_raw == "Female"
                                              else hesc(sex_raw))
        age = safe_int(r.get("age"))
        religion = hesc(r.get("drelign_TCP_label", "")) or hesc(r.get("drelign", ""))
        origin = hesc(r.get("dorigin_TCP_label", "")) or hesc(r.get("dorigin", ""))
        bp_code = str(r.get("dbirthpl_TCP", "") or "")
        bp_code = bp_code.removesuffix(".0") if bp_code.endswith(".0") else bp_code
        bp_label = (r.get("dbirthpl_TCP_label", "")
                    or r.get("dbirthpl", "") or "")
        bp_label = hesc(bp_label)
        bp_match = dbirthpl_xref.get(bp_code, {}) if bp_code else {}
        bp_qid = bp_match.get("qid", "")
        if bp_qid:
            bp_html = f'<a href="{WIKIDATA_BASE}{bp_qid}">{bp_label}</a>'
        else:
            bp_html = bp_label or "—"
        occupation = hesc(r.get("doccup_TCP_label", "")) or hesc(r.get("doccup", ""))
        hhnbr = hesc(r.get("hhnbr", ""))
        line_no = safe_int(r.get("line"))
        body_lines.append(
            f'<tr id="p-{rid}">'
            f'<td>{line_no or "·"}</td>'
            f'<td>{namlast}</td><td>{namfrst}</td>'
            f'<td>{sex}</td><td>{age}</td>'
            f'<td>{religion}</td><td>{origin}</td><td>{bp_html}</td>'
            f'<td>{occupation}</td><td>{hhnbr}</td></tr>'
        )
    return head + "\n".join(body_lines) + "</tbody></table>"


def render_browse_index(leaf_groups: dict[tuple[str, str, str], int],
                         site_url: str, leaf_url_for: callable) -> str:
    """Render a 'Browse by sub-district / surname letter' index for split CSDs.
    leaf_groups: {(sdistlet, surname_letter, chunk): row_count}.
    chunk is "" for non-chunked buckets, or "1"/"2"/... for tertiary splits."""
    # Group by (sdistlet, letter), aggregating chunked sub-pages.
    by_sd: dict[str, dict[str, list[tuple[str, int]]]] = defaultdict(
        lambda: defaultdict(list))
    for (sd, ltr, chunk), n in leaf_groups.items():
        by_sd[sd][ltr].append((chunk, int(n)))
    parts = ['<section class="browse">']
    for sd in sorted(by_sd):
        parts.append(f'<h2>Sub-district {hesc(sd.upper())}</h2>')
        parts.append('<ul>')
        for ltr in sorted(by_sd[sd]):
            chunks = sorted(by_sd[sd][ltr])
            label = ltr.upper() if ltr != "-" else "(no surname)"
            if len(chunks) == 1 and chunks[0][0] == "":
                # Single page for this letter.
                _, n = chunks[0]
                href = f"{sd}/{ltr.lower()}/"
                parts.append(
                    f'<li><a href="{href}">Surnames starting {label}</a> '
                    f'<span class="mute">({n:,})</span></li>'
                )
            else:
                # Chunked: list each part separately.
                total = sum(n for _, n in chunks)
                inner = []
                for chunk, n in chunks:
                    href = f"{sd}/{ltr.lower()}-{chunk}/"
                    inner.append(
                        f'<a href="{href}">part {chunk}</a> '
                        f'<span class="mute">({n:,})</span>'
                    )
                parts.append(
                    f'<li>Surnames starting {label} '
                    f'<span class="mute">({total:,} total)</span>: '
                    + ", ".join(inner) + "</li>"
                )
        parts.append('</ul>')
    parts.append('</section>')
    return "\n".join(parts)


def render_jsonld(*, site_url: str, base: str, canonical: str,
                  csd_name: str, csd_url: str,
                  province: str, total: int,
                  is_overview: bool,
                  borealis_doi: str = BOREALIS_DOI) -> str:
    obj = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": (f"Residents of {csd_name}, 1881 Census" if is_overview
                 else f"Residents of {csd_name} (sub-page), 1881 Census"),
        "description": (
            f"List of {total:,} individuals enumerated in {csd_name}, "
            f"{province}, in the 1881 Canadian census."
        ),
        "url": canonical,
        "isBasedOn": {"@id": borealis_doi},
        "spatialCoverage": {
            "@type": "Place",
            "name": csd_name,
            "url": f"{site_url}{csd_url}",
        },
        "temporalCoverage": "1881",
        "creator": {
            "@type": "Person",
            "name": "Lisa Dillon (PRDH); Canadian Peoples / TCP project",
        },
        "license": borealis_doi,
        "publisher": {
            "@type": "Organization",
            "name": "HGIS Canada Knowledge Graph",
            "url": f"{site_url}{base}/",
        },
    }
    return json.dumps(obj, indent=None, ensure_ascii=False)


# ---- Turtle emission ------------------------------------------------------

def fragment_for_resource(person_uri: str, suffix: str) -> str:
    """Replace the '#p-XXX' fragment with '#p-XXX-suffix' for a sub-resource."""
    base, _, frag = person_uri.partition("#")
    return f"{base}#{frag}-{suffix}"


def emit_residents_ttl(rows: pd.DataFrame, csd_uri: str, base_uri: str,
                       dbirthpl_xref: dict,
                       borealis_doi: str = BOREALIS_DOI) -> str:
    """Emit a CIDOC-CRM Turtle representation of a CSD's residents.

    URIs are emitted as `<#p-XXX-...>` relative to the @base directive,
    which expands to base_uri (the residents overview page URL). This is
    standard Turtle and reduces per-row bytes by ~80% vs absolute IRIs.

    Per resident, in compact `;`-chained form:
      <#p-XXX> a crm:E21_Person ; rdfs:label "Name"@en ;
        crm:P1_is_identified_by <#p-XXX-name> .
      <#p-XXX-name> a crm:E33_E41_Linguistic_Appellation ;
        crm:P190_has_symbolic_content "Name" .
      <#p-XXX-r> a crm:E7_Activity ; crm:P2_has_type <#t-res> ;
        crm:P14_carried_out_by <#p-XXX> ;
        crm:P7_took_place_at <csd> ; crm:P4_has_time-span <#ts-1881> .
      (E67_Birth only when birthplace grounded — bare P3 note otherwise;
       E13 age only when known, value reified as E54_Dimension)
      <#p-XXX-att> a crmdig:D1_Digital_Object, crm:E73_Information_Object ;
        crm:P129_is_about <#p-XXX> ; dcterms:source <doi> .

    Shared per-file nodes: <#ts-1881> (E52 bounds of the census year),
    <#t-res> / <#t-age> (E55 types), <#u-year> (E58 unit).
    """
    lines = [TTL_PREFIXES_TEMPLATE.format(base=base_uri).rstrip()]
    lines.append("")
    # Shared nodes: without a time-span the year 1881 was asserted nowhere
    # in the RDF, and untyped E7 activities were indistinguishable from any
    # other activity.
    lines.append(
        '<#ts-1881> a crm:E52_Time-Span ; rdfs:label "Census year 1881"@en ; '
        'crm:P82_at_some_time_within "1881"^^xsd:string ; '
        'crm:P82a_begin_of_the_begin "1881-01-01T00:00:00"^^xsd:dateTime ; '
        'crm:P82b_end_of_the_end "1881-12-31T23:59:59"^^xsd:dateTime .'
    )
    lines.append(
        '<#t-res> a crm:E55_Type ; '
        'rdfs:label "residence recorded in the 1881 Census of Canada"@en .'
    )
    lines.append(
        '<#t-age> a crm:E55_Type ; rdfs:label "age at census"@en .'
    )
    lines.append(
        '<#u-year> a crm:E58_Measurement_Unit ; rdfs:label "year"@en .'
    )
    lines.append("")
    csd_iri = f"<{csd_uri}>"
    for _, r in rows.iterrows():
        rid = r["unique_identifier"]
        namlast = fix_mojibake(r.get("namlast", "") or "")
        namfrst = fix_mojibake(r.get("namfrst", "") or "")
        full_name = (f"{namfrst} {namlast}".strip()) or "Unknown"
        full_name_esc = full_name.replace("\\", "\\\\").replace('"', '\\"')

        # E21_Person + identifies-by appellation
        lines.append(
            f'<#p-{rid}> a crm:E21_Person ; rdfs:label "{full_name_esc}"@en ; '
            f'crm:P1_is_identified_by <#p-{rid}-n> .'
        )
        lines.append(
            f'<#p-{rid}-n> a crm:E33_E41_Linguistic_Appellation ; '
            f'crm:P190_has_symbolic_content "{full_name_esc}" .'
        )

        # E67_Birth (only if birthplace grounded)
        bp_code = str(r.get("dbirthpl_TCP", "") or "")
        bp_code = bp_code.removesuffix(".0") if bp_code.endswith(".0") else bp_code
        bp_match = dbirthpl_xref.get(bp_code, {}) if bp_code else {}
        bp_qid = bp_match.get("qid", "") if bp_match.get("status") == "matched" else ""
        if bp_qid:
            lines.append(
                f'<#p-{rid}-b> a crm:E67_Birth ; '
                f'crm:P98_brought_into_life <#p-{rid}> ; '
                f'crm:P7_took_place_at wd:{bp_qid} .'
            )
        else:
            # Ungrounded birthplace: keep the source label as a note rather
            # than dropping the information from the RDF entirely.
            bp_label = fix_mojibake(str(r.get("dbirthpl_TCP_label", "") or ""))
            if bp_label:
                bp_esc = bp_label.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(
                    f'<#p-{rid}-b> a crm:E67_Birth ; '
                    f'crm:P98_brought_into_life <#p-{rid}> ; '
                    f'crm:P3_has_note "Birthplace (ungrounded): {bp_esc}"@en .'
                )

        # E7 residence (always) — typed + dated via the shared nodes.
        lines.append(
            f'<#p-{rid}-r> a crm:E7_Activity ; '
            f'crm:P2_has_type <#t-res> ; '
            f'crm:P14_carried_out_by <#p-{rid}> ; '
            f'crm:P7_took_place_at {csd_iri} ; '
            f'crm:P4_has_time-span <#ts-1881> .'
        )

        # E13 age (with uncertainty implied by the Borealis OCR provenance).
        # P141's range is E1, so the value is reified as an E54_Dimension;
        # P177 says WHAT property the integer is (age), which was previously
        # unstated.
        age = safe_int(r.get("age"))
        if age:
            lines.append(
                f'<#p-{rid}-a> a crm:E13_Attribute_Assignment ; '
                f'crm:P140_assigned_attribute_to <#p-{rid}> ; '
                f'crm:P177_assigned_property_of_type <#t-age> ; '
                f'crm:P141_assigned <#p-{rid}-ad> ; '
                f'crm:P4_has_time-span <#ts-1881> .'
            )
            lines.append(
                f'<#p-{rid}-ad> a crm:E54_Dimension ; '
                f'crm:P90_has_value "{age}"^^xsd:integer ; '
                f'crm:P91_has_unit <#u-year> .'
            )

        # D1 attestation
        lines.append(
            f'<#p-{rid}-x> a crmdig:D1_Digital_Object, crm:E73_Information_Object ; '
            f'crm:P129_is_about <#p-{rid}> ; '
            f'dcterms:source <{borealis_doi}> .'
        )

    return "\n".join(lines)


# ---- Main rendering --------------------------------------------------------

DISPLAY_COLS = [
    "unique_identifier", "namlast", "namfrst",
    "sex", "age", "agemonth",
    "marst_TCP_label", "drelign_TCP_label", "dorigin_TCP_label",
    "doccup_TCP_label", "dbirthpl_TCP_label",
    "dbirthpl", "dorigin", "drelign", "doccup",
    "dbirthpl_TCP",
    "hhnbr", "pageno", "line", "url",
    "TCPUID_CSD_1881", "persistent_place_id",
    "bucket_sdistlet", "surname_initial",
]


def measure_dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def measure_residents_size(rag_site: Path) -> int:
    """Sum bytes of residents-only output. The rag_site/ tree may also
    contain pre-existing CSD presence pages from generate_rag_pages.py;
    those don't count against the residents pipeline's size budget."""
    total = 0
    for f in rag_site.rglob("residents"):
        if f.is_dir():
            for g in f.rglob("*"):
                if g.is_file():
                    total += g.stat().st_size
    return total


def render_chain(
        pid: str, residents_df: pd.DataFrame, manifest_df: pd.DataFrame,
        registry: dict, summary: dict, dbirthpl_xref: dict,
        out_root: Path, site_url: str, base: str, only: bool,
        emit_ttl: bool = False,
        css_href: str = "",
        dcb_links: dict | None = None,
        verbose: bool = False,
) -> tuple[int, int]:
    """Render all pages for one chain. Returns (pages_written, ttl_files)."""
    info = registry[pid]
    csd_name = info["canonical_name"]
    province = info["province"]

    # All residents of this chain are in residents_df. Manifest gives URLs.
    # Take TCPUID + slug from manifest (consistent with build step).
    sample = manifest_df.iloc[0]
    csd_url = sample["csd_url"]            # /hgiscanada/places/.../residents-page-base/.. wait
    # csd_url in manifest is the *parent CSD* presence URL (no /residents/);
    # the residents overview is csd_url + 'residents/'.
    overview_url = f"{csd_url}residents/"
    overview_canonical = f"{site_url}{overview_url}"
    csd_iri = f"{site_url}{csd_url}"

    # Resolve filesystem path for the overview page from overview_url.
    rel = overview_url[len(base):].lstrip("/")
    overview_dir = out_root / rel
    overview_dir.mkdir(parents=True, exist_ok=True)

    pages_written = 0
    ttls_written = 0

    # ---- Per-CSD Turtle (covers all residents regardless of leaf split) ---
    if emit_ttl:
        ttl = emit_residents_ttl(
            residents_df.merge(manifest_df[["unique_identifier", "person_full_uri"]],
                                on="unique_identifier", how="left"),
            csd_uri=csd_iri,
            base_uri=overview_canonical,
            dbirthpl_xref=dbirthpl_xref,
        )
        (overview_dir / "residents.ttl").write_text(ttl, encoding="utf-8")
        ttls_written += 1

    # ---- Overview HTML page -----------------------------------------------
    if manifest_df["needs_split"].any():
        # 3-tuple key: (sdistlet, surname_letter, chunk). chunk is "" for
        # non-chunked buckets, "1"/"2"/... for tertiary-split buckets.
        chunk_col_name = ("bucket_chunk" if "bucket_chunk" in manifest_df.columns
                          else None)
        if chunk_col_name:
            leaf_groups = (manifest_df.groupby(
                ["bucket_sdistlet", "surname_initial", chunk_col_name])
                .size().to_dict())
        else:
            # Backward-compat: synthesise empty chunk.
            leaf_groups = {
                (sd, ltr, ""): n
                for (sd, ltr), n in (
                    manifest_df.groupby(["bucket_sdistlet", "surname_initial"])
                    .size().to_dict().items())
            }
    else:
        leaf_groups = {}

    sum_panel = render_summary_panel(summary.get(pid, {}))
    crumbs = (
        f'<a href="{base}/">HGIS Canada</a> &rsaquo; '
        f'<a href="{csd_url}">{hesc(csd_name)}</a> &rsaquo; '
        f'Residents (1881)'
    )
    title = f"Residents of {csd_name} (1881 Census)"
    description = (
        f"Individuals enumerated in {csd_name}, {province}, in the 1881 "
        f"Canadian census. Source: TCP/Dillon."
    )

    if leaf_groups:
        # Split CSD: overview shows browse index, no inline table.
        body_main = render_browse_index(leaf_groups, site_url,
                                         leaf_url_for=None)
        filter_script = ""
    else:
        # Small CSD: render inline table on the overview page itself.
        # Sort by namlast, namfrst.
        df_sorted = residents_df.sort_values(["namlast", "namfrst"],
                                             na_position="last")
        body_main = (
            '<section class="filter">'
            '<input id="q" type="text" placeholder="Filter residents…">'
            '</section>\n'
            + render_residents_table(df_sorted, dbirthpl_xref,
                                       dcb_links=dcb_links)
        )
        filter_script = FILTER_SCRIPT

    jsonld = render_jsonld(
        site_url=site_url, base=base, canonical=overview_canonical,
        csd_name=csd_name, csd_url=csd_url, province=province,
        total=len(residents_df), is_overview=True,
    )
    html_out = (
        PAGE_HEAD.format(
            title=hesc(title), description=hesc(description),
            canonical=overview_canonical,
            # Only advertise the Turtle alternate when it is actually emitted;
            # otherwise 33k pages link a 404 for LOD clients.
            ttl_link=('<link rel="alternate" type="text/turtle" '
                      'href="residents.ttl">\n' if emit_ttl else ""),
            css_href=css_href,
            robots="index,follow",
            crumbs=crumbs, heading=hesc(title),
        )
        + sum_panel
        + body_main
        + PAGE_FOOT.format(
            jsonld=jsonld,
            borealis_doi=BOREALIS_DOI,
            borealis_doi_label="doi:10.5683/SP3/FXZEVO",
            borealis_citation=BOREALIS_CITATION,
            site_url=site_url, base_path=base,
            filter_script=filter_script,
        )
    )
    (overview_dir / "index.html").write_text(html_out, encoding="utf-8")
    pages_written += 1

    # ---- Leaf pages for split CSDs ----------------------------------------
    if leaf_groups:
        # Build (sdistlet, letter, chunk) -> rows from the merged frame. The
        # manifest's leaf_url already encodes the chunk segment (e.g.
        # ".../residents/d/m-2/") for oversized buckets, so we group by it
        # directly rather than re-deriving from sdistlet+letter.
        merged = residents_df.merge(
            manifest_df[["unique_identifier", "leaf_url",
                         "bucket_sdistlet", "surname_initial", "bucket_chunk",
                         "person_full_uri"]],
            on="unique_identifier", how="left",
            suffixes=("", "_m"),
        )
        bucket_col = ("bucket_sdistlet_m" if "bucket_sdistlet_m" in merged.columns
                      else "bucket_sdistlet")
        letter_col = ("surname_initial_m" if "surname_initial_m" in merged.columns
                      else "surname_initial")
        chunk_col = ("bucket_chunk_m" if "bucket_chunk_m" in merged.columns
                     else "bucket_chunk")
        for (sd, ltr, chunk), grp in merged.groupby(
                [bucket_col, letter_col, chunk_col], sort=False):
            letter_seg = ltr.lower()
            if chunk:
                letter_seg = f"{letter_seg}-{chunk}"
            leaf_rel = f"{rel}{sd}/{letter_seg}/"
            leaf_dir = out_root / leaf_rel
            leaf_dir.mkdir(parents=True, exist_ok=True)
            leaf_url = f"{base}/{leaf_rel}"
            leaf_canonical = f"{site_url}{leaf_url}"

            df_sorted = grp.sort_values(["namlast", "namfrst"],
                                         na_position="last")
            chunk_label = f", part {chunk}" if chunk else ""
            sub_crumbs = (
                f'<a href="{base}/">HGIS Canada</a> &rsaquo; '
                f'<a href="{csd_url}">{hesc(csd_name)}</a> &rsaquo; '
                f'<a href="../../">Residents (1881)</a> &rsaquo; '
                f'Sub-{hesc(sd.upper())} / {hesc(ltr.upper())}{hesc(chunk_label)}'
            )
            sub_title = (
                f"Residents of {csd_name} — Sub-district {sd.upper()}, "
                f"surnames {ltr.upper()}{chunk_label} (1881 Census)"
            )
            sub_desc = (
                f"{len(grp):,} individuals enumerated in {csd_name}, "
                f"sub-district {sd.upper()}, surnames beginning {ltr.upper()}"
                f"{chunk_label}, in the 1881 Canadian census."
            )
            body_sub = (
                '<section class="filter">'
                '<input id="q" type="text" placeholder="Filter…">'
                '</section>\n'
                + render_residents_table(df_sorted, dbirthpl_xref,
                                       dcb_links=dcb_links)
            )
            sub_jsonld = render_jsonld(
                site_url=site_url, base=base, canonical=leaf_canonical,
                csd_name=csd_name, csd_url=csd_url, province=province,
                total=len(grp), is_overview=False,
            )
            sub_html = (
                PAGE_HEAD.format(
                    title=hesc(sub_title), description=hesc(sub_desc),
                    canonical=leaf_canonical,
                    # share parent's ttl (only when emitted)
                    ttl_link=('<link rel="alternate" type="text/turtle" '
                              'href="../../residents.ttl">\n' if emit_ttl else ""),
                    css_href=css_href,
                    robots="noindex,follow",  # only overview is indexable
                    crumbs=sub_crumbs, heading=hesc(sub_title),
                )
                + body_sub
                + PAGE_FOOT.format(
                    jsonld=sub_jsonld,
                    borealis_doi=BOREALIS_DOI,
                    borealis_doi_label="doi:10.5683/SP3/FXZEVO",
                    borealis_citation=BOREALIS_CITATION,
                    site_url=site_url, base_path=base,
                    filter_script=FILTER_SCRIPT,
                )
            )
            (leaf_dir / "index.html").write_text(sub_html, encoding="utf-8")
            pages_written += 1

    if verbose:
        print(f"  {pid}: {pages_written} pages, ttl rows={len(residents_df)}",
              file=sys.stderr)
    return pages_written, ttls_written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site-url", default=DEFAULT_SITE_URL)
    ap.add_argument("--base-path", default=DEFAULT_BASE_PATH)
    ap.add_argument("--out-dir", type=Path, default=SITE_OUT)
    ap.add_argument("--only", help="Render only this persistent_place_id")
    ap.add_argument("--limit-chains", type=int, default=0,
                    help="Stop after N chains (dev only)")
    ap.add_argument("--no-size-guard", action="store_true",
                    help="Skip the rag_site/ size cap (DANGEROUS)")
    ap.add_argument("--with-ttl", action="store_true",
                    help="Emit per-CSD residents.ttl sidecars. Off by default "
                         "because Turtle adds ~500 MB to the rendered footprint; "
                         "turn on once GH Pages headroom is confirmed.")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if not MANIFEST.exists():
        sys.exit("URI manifest missing; run scripts/build_residents_cidoc.py")
    if not SUMMARY.exists():
        sys.exit("Summary missing; run scripts/aggregate_1881_residents.py")

    print("[render] loading sidecar data …", file=sys.stderr)
    registry = load_registry()
    summary = load_summary()
    manifest_all = pd.read_parquet(MANIFEST)
    dbirthpl_xref = load_dbirthpl_xref()
    dcb_links = load_dcb_links()
    if dcb_links:
        print(f"[render] loaded {len(dcb_links):,} DCB→1881 links",
              file=sys.stderr)

    out_root = args.out_dir
    out_root.mkdir(parents=True, exist_ok=True)
    base = args.base_path

    # Write the shared residents stylesheet once at the top of the rendering
    # tree. All HTML pages link to it via relative href.
    shared_css_dir = out_root / "places" / "residents-assets"
    shared_css_dir.mkdir(parents=True, exist_ok=True)
    (shared_css_dir / "residents.css").write_text(SHARED_CSS, encoding="utf-8")
    # css_href is a site-absolute path so the same string works from any
    # depth (overview at /places/<prov>/<chain>/residents/, leaves deeper).
    shared_css_href = f"{base}/places/residents-assets/residents.css"

    # Filter manifest if --only.
    if args.only:
        chains = [args.only]
        if args.only not in set(manifest_all["persistent_place_id"]):
            sys.exit(f"Chain {args.only} not in manifest")
    else:
        chains = list(manifest_all["persistent_place_id"].unique())
    print(f"[render] rendering {len(chains):,} CSD chains", file=sys.stderr)

    # Group manifest by chain for fast lookup.
    manifest_by_chain = dict(tuple(manifest_all.groupby("persistent_place_id")))

    # Iterate per-province parquet so we only load each one once.
    pages_total = 0
    ttls_total = 0
    chains_done = 0
    t0 = time.time()

    province_paths = sorted(PROVINCE_DIR.glob("*.parquet"))
    for pp in province_paths:
        prov_code = pp.stem
        chains_in_prov = [c for c in chains
                           if registry.get(c, {}).get("province") == prov_code]
        if not chains_in_prov:
            continue
        if args.only and args.only not in chains_in_prov:
            continue

        print(f"[render] {pp.name}: loading + rendering "
              f"{len(chains_in_prov):,} chains …", file=sys.stderr)
        # Load only the columns we need for HTML + Turtle + URL minting.
        cols = [c for c in DISPLAY_COLS if c]
        df_prov = pq.read_table(pp, columns=cols).to_pandas()
        df_prov = df_prov[df_prov["persistent_place_id"].isin(chains_in_prov)]

        for pid, grp in df_prov.groupby("persistent_place_id", sort=False):
            if args.only and pid != args.only:
                continue
            mf = manifest_by_chain.get(pid)
            if mf is None or mf.empty:
                continue
            n_pages, n_ttl = render_chain(
                pid, grp, mf, registry, summary, dbirthpl_xref,
                out_root, args.site_url, base, only=bool(args.only),
                emit_ttl=args.with_ttl,
                css_href=shared_css_href,
                dcb_links=dcb_links,
                verbose=args.verbose,
            )
            pages_total += n_pages
            ttls_total += n_ttl
            chains_done += 1
            if chains_done % 200 == 0:
                elapsed = time.time() - t0
                rate = chains_done / max(elapsed, 1e-6)
                print(f"[render] {chains_done:,}/{len(chains):,} chains, "
                      f"{pages_total:,} pages, {rate:.1f} chains/s",
                      file=sys.stderr)
            if args.limit_chains and chains_done >= args.limit_chains:
                break
        del df_prov
        gc.collect()
        if args.limit_chains and chains_done >= args.limit_chains:
            break

    elapsed = time.time() - t0
    print(f"[render] done: {chains_done:,} chains, {pages_total:,} HTML pages, "
          f"{ttls_total:,} ttl files, {elapsed:.1f}s",
          file=sys.stderr)

    # Augment sitemap.xml with residents overview URLs (one per CSD chain).
    # Leaf and chunked sub-pages stay out of the sitemap — the renderer
    # marks them robots="noindex,follow", and listing them would more than
    # double sitemap.xml without aiding discovery. The CSD overview is the
    # canonical entry point. generate_rag_pages.py rewrites sitemap.xml
    # whole, so this augmentation must run AFTER that step (Makefile order
    # already guarantees this).
    sitemap_path = out_root / "sitemap.xml"
    if sitemap_path.exists() and not args.only:
        from datetime import date
        today = date.today().isoformat()
        # All distinct overview URLs from the manifest.
        overview_urls = (manifest_all["csd_url"] + "residents/").drop_duplicates()
        overview_urls = sorted(overview_urls.tolist())
        xml = sitemap_path.read_text()
        if "/residents/</loc>" in xml:
            # Already augmented (re-render); strip residents entries first
            # so we don't accumulate stale or duplicate ones.
            xml = re.sub(
                r"^  <url><loc>[^<]*/residents/</loc>[^\n]*\n",
                "", xml, flags=re.M)
        new_entries = "\n".join(
            f"  <url><loc>{args.site_url}{u}</loc>"
            f"<lastmod>{today}</lastmod>"
            f"<changefreq>yearly</changefreq></url>"
            for u in overview_urls
        )
        xml = xml.replace("</urlset>", new_entries + "\n</urlset>")
        sitemap_path.write_text(xml)
        print(f"[render] augmented sitemap.xml with {len(overview_urls):,} "
              f"residents overview URLs", file=sys.stderr)

    # Size guard. Residents-only footprint: the rag_site/ tree may contain
    # pre-existing CSD pages from generate_rag_pages.py; only the residents/
    # subtrees count against this pipeline's budget.
    if not args.no_size_guard:
        residents_size = measure_residents_size(out_root)
        residents_mb = residents_size / (1024 * 1024)
        total_size = measure_dir_size(out_root)
        total_mb = total_size / (1024 * 1024)
        if residents_size > FAIL_SIZE_BYTES:
            sys.exit(f"[render] FATAL: residents output at "
                     f"{residents_mb:.0f} MB exceeds hard cap "
                     f"{FAIL_SIZE_BYTES / (1024*1024):.0f} MB")
        if residents_size > WARN_SIZE_BYTES:
            print(f"[render] WARNING: residents output at "
                  f"{residents_mb:.0f} MB approaching "
                  f"{WARN_SIZE_BYTES / (1024*1024):.0f} MB warn threshold",
                  file=sys.stderr)
        else:
            print(f"[render] residents output: {residents_mb:.1f} MB; "
                  f"total rag_site/: {total_mb:.0f} MB", file=sys.stderr)
        if total_size > 1024 * 1024 * 1024:
            print(f"[render] NOTE: total rag_site/ is {total_mb:.0f} MB, over "
                  f"the 1 GB GitHub Pages soft cap. Residents pipeline is "
                  f"NOT the source — see CSD pages from generate_rag_pages.py.",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
