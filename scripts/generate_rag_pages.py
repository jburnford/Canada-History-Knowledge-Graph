#!/usr/bin/env python3
"""
Generate per-CSD-year HTML pages for a static GitHub Pages site,
sourced from the pilot Kuzu database.

Output: stand-alone HTML files (no Jekyll build step required) at
  places/on/<name>-<tcpuid>-<year>/index.html
plus an index.html and a sitemap.xml at the root.

Each page contains: title, meta description, Open Graph tags, Wikidata
authority <link>, prose body for embedding-based RAG, population summary,
cross-year trajectory with internal links, neighbour list with internal
links, source citation, and Schema.org JSON-LD.

Usage:
    # Demo: generate three sample pages
    python3 scripts/generate_rag_pages.py --samples

    # Single page
    python3 scripts/generate_rag_pages.py --presence ON031005_1851

    # Full corpus (every ON presence with population data) + index + sitemap
    python3 scripts/generate_rag_pages.py --all

The site URL and base path are configurable via flags (default matches the
hgiscanada repo published at jimclifford.ca/hgiscanada).
"""

import argparse
import csv
import html
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from csd_name_normalize import (
    QUALIFIER_TIER_MAP,
    _parse_csd_name,
    _aggressive_base_normalize,
    grouping_key,
    display_name_for_group,
    is_indian_reserve,
)


# Methodological note prepended to every Indian-Reserve page. Frames the entity
# as a census artifact and points to better sources. Deliberately generic:
# does not assert modern band identity, does not list specific First Nations,
# does not display a Wikidata QID even when one was matched. Census naming and
# enumeration of First Nations was inconsistent and reflects federal
# administrative classification, not the communities' own identities.
IR_NOTE_HTML = (
    '<div class="meta" style="border-left-color:#aa6600">'
    '<strong>Note on Indian Reserves in the Census of Canada.</strong> '
    'The 1851–1921 censuses enumerated First Nations populations on reserves '
    'inconsistently across years and regions, sometimes naming individual '
    'reserves and sometimes aggregating them under a generic "Indian Reserves" '
    'bundle per Census District. This page reflects the historical census '
    'record as published; it is not an authoritative description of any '
    'specific First Nation, band, or reserve. For accurate information, '
    'consult the annual reports of the Department of Indian Affairs '
    '(1864–present, available through Library and Archives Canada), the '
    'Indigenous Services Canada First Nation Profiles, and First Nations '
    'communities directly.'
    '</div>'
)

REPO = Path(__file__).resolve().parents[1]
DB_PATH = REPO / "pilot" / "on_kuzu" / "on.kuzu"
OUT_DIR = REPO / "rag_site"

DEFAULT_SITE_URL = "https://jimclifford.ca"
DEFAULT_BASE_PATH = "/hgiscanada"

# Map 2-letter province codes to display names.
PROVINCE_NAMES = {
    "ON": "Ontario", "QC": "Quebec", "NS": "Nova Scotia",
    "NB": "New Brunswick", "PE": "Prince Edward Island",
    "BC": "British Columbia", "AB": "Alberta", "SK": "Saskatchewan",
    "MB": "Manitoba", "YT": "Yukon", "NT": "Northwest Territories",
    "NL": "Newfoundland and Labrador",
}

SAMPLES = [
    "ON031005_1851",  # Alfred (Wikidata-grounded rural township)
    "ON082003_1871",  # Westmeath (Wikidata-grounded, validated)
    "ON006004_1851",  # Darlington (ungrounded — non-Wikidata path)
]


def slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def fmt_pop(n):
    if n is None:
        return "—"
    return f"{n:,}"


def fmt_thousand(n):
    if n is None:
        return ""
    return f"{n:,}"


def url_for_presence(name: str, tcpuid: str, year: int, base: str,
                     province: str = "on") -> str:
    """Return the absolute URL path (including base) for a presence's page."""
    return f"{base}/places/{province.lower()}/{slugify(name)}-{tcpuid.lower()}-{year}/"


def url_for_place(name: str, place_id: str, base: str,
                  province: str = "on") -> str:
    """Return the URL for a per-Place index page (aggregate across all years)."""
    stem = slugify(place_id.replace("PLACE_", ""))
    return f"{base}/places/{province.lower()}/{slugify(name)}-{stem}/"


REDIRECT_STUB_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Moved: {name}</title>
<link rel="canonical" href="{site_url}{new_url}">
<meta http-equiv="refresh" content="0; url={site_url}{new_url}">
<meta name="robots" content="noindex">
</head>
<body>
<p>This persistent place chain merged into a longer-lived chain.
Redirecting to <a href="{site_url}{new_url}">{name}</a>…</p>
</body>
</html>
"""


def _write_stub(out_dir: Path, base: str, old_url: str, new_url: str,
                 site_url: str, name: str,
                 fresh_urls: set[str] | None = None) -> bool:
    """Write a single meta-refresh stub. Returns True if written.

    Won't clobber a page the renderer just wrote in this run (membership
    checked via fresh_urls). Stale pages from previous builds ARE
    overwritten — that's the point of the redirect stub.

    fresh_urls contains absolute URLs ({site_url}{path}); old_url is a path
    starting with `base`. Compare with the absolute form."""
    if fresh_urls is not None and f"{site_url}{old_url}" in fresh_urls:
        return False
    rel_path = old_url[len(base):].lstrip("/")
    stub_dir = out_dir / rel_path
    target = stub_dir / "index.html"
    stub_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(REDIRECT_STUB_TEMPLATE.format(
        name=html.escape(name),
        site_url=site_url,
        new_url=new_url,
    ))
    return True


def write_redirect_stubs(out_dir: Path, site_url: str, base: str,
                          redirects_csv: Path,
                          known_chain_ids: set[str],
                          fresh_urls: set[str] | None = None) -> int:
    """Emit meta-refresh stubs for chain ids subsumed by the bridge pass.

    For each row in place_chain_redirects.csv (Track A output), build the
    OLD URL the renderer used to emit (using old_canonical_name + old_place_id)
    and write a 0-second meta-refresh HTML pointing to the NEW chain's URL.
    Returns count of stubs written.
    """
    if not redirects_csv.exists():
        return 0
    written = 0
    with redirects_csv.open() as f:
        for r in csv.DictReader(f):
            old_pid = r["old_place_id"]
            new_pid = r["new_place_id"]
            if old_pid in known_chain_ids:
                continue
            old_url = url_for_place(
                r["old_canonical_name"], old_pid, base, r["province"])
            new_url = url_for_place(
                r["new_canonical_name"], new_pid, base, r["province"])
            if _write_stub(out_dir, base, old_url, new_url, site_url,
                            r["old_canonical_name"], fresh_urls):
                written += 1
    return written


def write_presence_redirect_stubs(out_dir: Path, site_url: str, base: str,
                                    redirects_csv: Path,
                                    fresh_urls: set[str] | None = None) -> int:
    """Emit meta-refresh stubs for per-presence URLs that broke when their
    chain's canonical_name changed via a bridge merge.

    The presence URL embeds the chain's canonical_name as a slug
    (e.g. `peterborough-town-of-on093012-1861`). When the bridge merges
    PLACE_ON093012 ("Peterborough, Town of") into PLACE_ON138017
    ("Peterborough, C"), the 1861 presence is now rendered at
    `peterborough-c-on093012-1861` and the old URL would 404. This emits
    a meta-refresh stub at the old URL so existing inbound links keep working.
    """
    if not redirects_csv.exists():
        return 0
    written = 0
    with redirects_csv.open() as f:
        for r in csv.DictReader(f):
            tcpuid = r["tcpuid"]
            year = int(r["year"])
            prov = r["province"]
            old_name = r["old_canonical_name"]
            new_name = r["new_canonical_name"]
            old_url = url_for_presence(old_name, tcpuid, year, base, prov)
            new_url = url_for_presence(new_name, tcpuid, year, base, prov)
            if old_url == new_url:
                # bridge_normalize differs but slugify(name) coincides — no
                # actual URL change.
                continue
            if _write_stub(out_dir, base, old_url, new_url, site_url, old_name,
                            fresh_urls):
                written += 1
    return written


# Populated by main() after prefetch_cd_data so render_page (CSD year pages)
# can resolve raw NAME_CD strings to the canonical CD chain URL. Empty falls
# back to name-based URL (pre-Phase-1 behavior).
_CD_CHAIN_BY_RAW_YEAR: dict = {}
_CD_CHAIN_URL_SLUG: dict = {}  # chain_id -> last path segment ("renfrew-north")
_CD_CANONICAL_BY_CHAIN: dict = {}
# chain_id -> display label. Bare canonical_name when unique within the
# province; "<canonical_name> (<year qualifier>)" when two or more chains
# in the same province share a canonical_name (e.g. Toronto East 1871 and
# Toronto East 1911 are both real but distinct CDs).
_CD_DISPLAY_LABEL: dict = {}


def url_for_cd(cd_name: str, province: str, base: str, *, year: int = None,
               chain_place_id: str = None) -> str:
    """Return the URL for a per-CD index page.

    When chain lookups are populated (post-Phase-1) AND either an explicit
    chain_place_id is provided OR a year is provided that lets us derive the
    raw cd_id, return the chain's canonical URL (which handles collision
    disambiguators like `york-1921`). Otherwise fall back to name-based URL
    (pre-Phase-1 behavior, may 404 if a chain canonicalized to a different
    slug)."""
    chain_id = chain_place_id
    if not chain_id and year is not None and _CD_CHAIN_BY_RAW_YEAR:
        raw_cd_id = f"CD_{province}_{cd_name.replace(' ', '_')}"
        chain_id = _CD_CHAIN_BY_RAW_YEAR.get((raw_cd_id, int(year)))
    if chain_id and chain_id in _CD_CHAIN_URL_SLUG:
        return f"{base}/cds/{province.lower()}/{_CD_CHAIN_URL_SLUG[chain_id]}/"
    return f"{base}/cds/{province.lower()}/{slugify(cd_name)}/"


def cd_link_label(raw_cd_name: str, year: int = None, province: str = "") -> str:
    """Return the link text for a CSD page's "Part of: <CD>" line.

    Uses the disambiguated display label when the raw cd_name resolves to a
    chain that shares its canonical_name with another chain in the same
    province (e.g. "Toronto East (1871)"). Falls back to canonical_name when
    the chain is unique, or raw_cd_name when no chain mapping is available."""
    if year is None or not _CD_CHAIN_BY_RAW_YEAR:
        return raw_cd_name
    raw_cd_id = f"CD_{province}_{raw_cd_name.replace(' ', '_')}"
    chain_id = _CD_CHAIN_BY_RAW_YEAR.get((raw_cd_id, int(year)))
    if chain_id:
        return _CD_DISPLAY_LABEL.get(
            chain_id,
            _CD_CANONICAL_BY_CHAIN.get(chain_id, raw_cd_name),
        )
    return raw_cd_name


# Canonical HTML template for a Presence page. Hard-coded baseurl baked in
# at generation time so no client-side templating is needed.
PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">

<meta property="og:type" content="article">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{canonical}">
{og_geo}
{wikidata_link}

<style>
  body {{ font-family: -apple-system, "Segoe UI", sans-serif; max-width: 760px;
         margin: 2em auto; padding: 0 1em; line-height: 1.55; color: #222; }}
  h1 {{ border-bottom: 1px solid #ddd; padding-bottom: 0.3em; margin-bottom: 0.5em; }}
  h2 {{ margin-top: 1.6em; }}
  table {{ border-collapse: collapse; margin: 0.5em 0; }}
  th, td {{ border: 1px solid #ddd; padding: 4px 10px; }}
  th {{ background: #f5f5f5; }}
  td:nth-child(2) {{ text-align: right; }}
  .crumbs {{ font-size: 0.9em; color: #666; margin-bottom: 0.5em; }}
  .crumbs a {{ color: #0055aa; }}
  .meta {{ background: #f8f9fa; padding: 0.7em 1em; border-left: 3px solid #0066cc;
         margin: 1em 0; font-size: 0.9em; }}
  ul {{ padding-left: 1.5em; }}
  a {{ color: #0055aa; }}
  footer {{ margin-top: 3em; font-size: 0.8em; color: #666;
           border-top: 1px solid #ddd; padding-top: 1em; }}
</style>
</head>
<body>
<article>
<div class="crumbs"><a href="{home_url}">HGIS Canada</a> › <a href="{prov_index_url}">{province}</a> › <a href="{place_index_url}">{name_html}</a> › {year}</div>
<div class="meta">
<strong>Year:</strong> {year}
&nbsp;|&nbsp; <strong>Province:</strong> {province}
{county_meta}{wikidata_meta}
</div>

<h1>{heading}</h1>

{intro}

{population_section}
{trajectory_section}
{overlaps_section}
{neighbours_section}
{measurements_section}
{persons_section}

<h2>Identifiers</h2>
<ul>
<li><strong>TCP UID:</strong> <code>{tcpuid}</code> — year-scoped identifier from the Canadian Census Subdivision boundary file</li>
<li><strong>Persistent place ID:</strong> <code>{place_id}</code> — computed from spatial-overlap chains across census years</li>
{wikidata_id}
</ul>

<h2>Sources</h2>
<p>Census tabulations from the {year} Census of Canada, transcribed and georeferenced by the
<a href="https://borealisdata.ca/dataverse/canadiansubdivisions">Canadian Peoples / TCP</a> project,
hosted at the <a href="https://hgiscanada.usask.ca/">HGIS Lab, University of Saskatchewan</a>.
Persistent place identity computed from spatial-overlap chains across all available census years (1851–1921).
Identity grounding to Wikidata performed via the
<a href="https://github.com/jburnford/Canada-History-Knowledge-Graph">HGIS Canada Knowledge Graph</a>
project's MCP-assisted disambiguation pipeline. See the <a href="{about_url}">About / Methodology</a>
page for the full data pipeline.</p>

<h2>Cite this page</h2>
<blockquote style="border-left:3px solid #ccc;margin:1em 0;padding:0.2em 0 0.2em 1em;color:#444;font-size:0.95em;">
Clifford, J. (2026). "{name_html}, {province} ({year} census)" in <em>HGIS Canada Knowledge Graph</em>.
Retrieved from <a href="{canonical}">{canonical}</a>.
</blockquote>

<script type="application/ld+json">
{jsonld}
</script>

<footer>
<a href="{place_index_url}">↑ All years for {name_html}</a>
&nbsp;|&nbsp; <a href="{home_url}">All Census Subdivisions</a>
&nbsp;|&nbsp; Generated from the
<a href="https://github.com/jburnford/Canada-History-Knowledge-Graph">Canada History Knowledge Graph</a>.
</footer>
</article>
</body>
</html>
"""


PLACE_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">

<meta property="og:type" content="article">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{canonical}">
{wikidata_link}

<style>
  body {{ font-family: -apple-system, "Segoe UI", sans-serif; max-width: 760px;
         margin: 2em auto; padding: 0 1em; line-height: 1.55; color: #222; }}
  h1 {{ border-bottom: 1px solid #ddd; padding-bottom: 0.3em; margin-bottom: 0.5em; }}
  h2 {{ margin-top: 1.6em; }}
  table {{ border-collapse: collapse; margin: 0.5em 0; }}
  th, td {{ border: 1px solid #ddd; padding: 4px 10px; }}
  th {{ background: #f5f5f5; }}
  td:nth-child(2), td:nth-child(3) {{ text-align: right; }}
  .crumbs {{ font-size: 0.9em; color: #666; margin-bottom: 0.5em; }}
  .crumbs a {{ color: #0055aa; }}
  .meta {{ background: #f8f9fa; padding: 0.7em 1em; border-left: 3px solid #0066cc;
         margin: 1em 0; font-size: 0.9em; }}
  ul {{ padding-left: 1.5em; }}
  a {{ color: #0055aa; }}
  footer {{ margin-top: 3em; font-size: 0.8em; color: #666;
           border-top: 1px solid #ddd; padding-top: 1em; }}
</style>
</head>
<body>
<article>
<div class="crumbs"><a href="{home_url}">HGIS Canada</a> › <a href="{prov_index_url}">{province}</a> › {name_html}</div>
<div class="meta">
<strong>Province:</strong> {province}
&nbsp;|&nbsp; <strong>Years recorded:</strong> {year_range}
{wikidata_meta}
</div>

<h1>{heading}</h1>

{intro}

{lineage_section}

<h2>Population trajectory across census years</h2>
<table>
<tr><th>Census year</th><th>Population</th><th>Page</th></tr>
{trajectory_rows}
</table>
<p><em>Cross-year identity established by spatial polygon overlap (SAME_AS chains
across the Canadian Census Subdivision boundary files).</em></p>

{persons_aggregate_section}

<h2>Identifiers</h2>
<ul>
<li><strong>Persistent place ID:</strong> <code>{place_id}</code> — assigned to this enduring entity by chaining year-scoped TCP UIDs through spatial overlap</li>
{wikidata_id}
</ul>

<h2>Sources</h2>
<p>Census tabulations from the 1851–1921 Census of Canada series, transcribed and georeferenced by the
<a href="https://borealisdata.ca/dataverse/canadiansubdivisions">Canadian Peoples / TCP</a> project.
Each year's detail page (linked above) cites the specific source table.</p>

<script type="application/ld+json">
{jsonld}
</script>

<footer>
<a href="{home_url}">← All Census Subdivisions</a>
&nbsp;|&nbsp; Generated from the
<a href="https://github.com/jburnford/Canada-History-Knowledge-Graph">Canada History Knowledge Graph</a>.
</footer>
</article>
</body>
</html>
"""


INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HGIS Canada Knowledge Graph — Census Subdivisions, 1851–1921</title>
<meta name="description" content="An academic knowledge graph of Canadian Census Subdivisions across the 1851–1921 censuses, building on the Canadian Peoples / TCP project. Per-place prose summaries, Wikidata grounding, cross-year boundary continuity, full census record, and structured data.">
<link rel="canonical" href="{site_url}{base}/">

<meta property="og:type" content="website">
<meta property="og:title" content="HGIS Canada Knowledge Graph — Census Subdivisions, 1851–1921">
<meta property="og:description" content="Academic knowledge graph of Canadian Census Subdivisions, 1851–1921. Built on the Canadian Peoples / TCP project at hgiscanada.usask.ca.">

<style>
  body {{ font-family: -apple-system, "Segoe UI", sans-serif; max-width: 780px;
         margin: 2em auto; padding: 0 1em; line-height: 1.6; color: #222; }}
  h1 {{ border-bottom: 1px solid #ddd; padding-bottom: 0.3em; margin-bottom: 0.3em; }}
  .tagline {{ font-size: 1.05em; color: #555; margin-top: 0; }}
  h2 {{ margin-top: 1.8em; }}
  a {{ color: #0055aa; }}
  .card-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
              gap: 0.5em 1em; margin: 0.8em 0; }}
  .card-grid a {{ padding: 0.45em 0.7em; border: 1px solid #ddd; border-radius: 4px;
              text-decoration: none; color: #0055aa; background: #fafbfc; }}
  .card-grid a:hover {{ background: #e8f1fb; }}
  .card-grid .count {{ color: #888; font-size: 0.85em; }}
  table {{ border-collapse: collapse; margin: 0.5em 0; }}
  th, td {{ border: 1px solid #ddd; padding: 4px 12px; text-align: right; }}
  th:first-child, td:first-child {{ text-align: left; }}
  blockquote {{ border-left: 3px solid #ccc; margin: 1em 0; padding: 0.2em 0 0.2em 1em;
              color: #555; }}
  footer {{ margin-top: 3em; font-size: 0.85em; color: #666;
           border-top: 1px solid #ddd; padding-top: 1em; }}
</style>
</head>
<body>
<article>
<h1>HGIS Canada Knowledge Graph</h1>
<p class="tagline">Canadian Census Subdivisions, 1851–1921 — every place, every census, the full record.</p>

<p>An academic knowledge graph of Canadian historical Census Subdivisions, designed for both human
researchers and machine readers (search engines, AI assistants, citation-grounded RAG). This site
publishes one page per Census Subdivision per census year, plus an aggregate page per persistent
place across all eight censuses, drawn from the
<a href="https://borealisdata.ca/dataverse/canadiansubdivisions">Canadian Peoples / TCP</a>
boundary files and census tabulations.</p>

<p>Built on the work of the <strong>HGIS Lab</strong> at the University of Saskatchewan and the
<a href="https://hgiscanada.usask.ca/">hgiscanada.usask.ca</a> project, which provides the
underlying georeferenced boundary polygons and census-table transcriptions. This site reorganises
those data as a queryable knowledge graph and a browseable web of per-place prose pages.</p>

<h2>Browse by province</h2>
<div class="card-grid">
{province_links}
</div>

<h2>What's on each page</h2>
<ul>
<li>A prose summary describing the place in that census year</li>
<li>Population total + sex split, where the census recorded them</li>
<li>The <strong>full census record</strong> — every variable recorded for that subdivision in that year, grouped into collapsible category tables (Population, Age, Ethnic origin, Religion, Buildings, Agriculture, Manufacturing, Fisheries, Deaths)</li>
<li>Cross-year population trajectory linking the <em>same</em> place across all 8 censuses, stitched together by spatial polygon overlap</li>
<li>Neighbouring CSDs in that census year, internally linked</li>
<li><strong>Boundary continuity</strong> links to overlapping CSDs in adjacent census years (CONTAINS / WITHIN / OVERLAPS) so chains across boundary changes are traceable</li>
<li>Wikidata grounding where available, plus internal persistent place IDs and the source TCP UID</li>
<li>Schema.org JSON-LD for structured-data crawlers</li>
<li>Source citation pointing back to the underlying TCP / Borealis dataset</li>
</ul>

<h2>Coverage</h2>
<table>
<tr><th>Census year</th><th>CSD pages</th></tr>
{coverage_rows}
<tr><th>Total year-pages</th><th>{total_pages}</th></tr>
</table>
<p>Plus an aggregate per persistent place across all years (~{total_places} place-index pages).</p>

<h2>Sample pages</h2>
<ul>
{sample_links}
</ul>

<h2>For researchers</h2>
<p>This site is the human-readable surface of a larger knowledge-graph project. The underlying
data is also published as:</p>
<ul>
<li>A <strong>KuzuDB</strong> property graph (for researchers using coding agents like Claude Code, or for SPARQL/Cypher-style queries against the full dataset)</li>
<li>A <strong>CIDOC-CRM Turtle</strong> export (for the LINCS Linked Open Data ecosystem and other LOD consumers)</li>
<li>The <strong>per-place pages on this site</strong> (for citation-grounded research, classroom use, and chatbot retrieval)</li>
</ul>
<p>See the <a href="{about_url}">About / Methodology</a> page for the full data pipeline,
identity model, and grounding methodology, or visit the
<a href="https://github.com/jburnford/Canada-History-Knowledge-Graph">project repository</a>
for code, the knowledge graph itself, and reproducibility.</p>

<h2>How to cite</h2>
<blockquote>
Clifford, J. (2026). <em>HGIS Canada Knowledge Graph: Census Subdivisions, 1851–1921</em>
[Web resource]. Built on the Canadian Peoples / TCP project. Available at
<a href="{site_url}{base}/">{site_url}{base}/</a>.
</blockquote>
<p>For specific places, cite the page directly using its URL — each year-page and place-index page
has a stable canonical URL.</p>

<h2>Acknowledgments</h2>
<p>The underlying census polygons and tabulations are from the
<a href="https://borealisdata.ca/dataverse/canadiansubdivisions">Canadian Peoples / TCP project</a>,
hosted by Borealis Dataverse and developed at the
<a href="https://hgis.usask.ca/">HGIS Lab</a>, University of Saskatchewan. Wikidata grounding is
performed via an MCP-assisted disambiguation pipeline. Spatial overlap chains and persistent-place
identification follow methodology developed within the
<a href="https://github.com/jburnford/Canada-History-Knowledge-Graph">project</a>.</p>

<footer>
<a href="{about_url}">About / Methodology</a> &nbsp;·&nbsp;
<a href="https://github.com/jburnford/Canada-History-Knowledge-Graph">Source code &amp; data</a> &nbsp;·&nbsp;
<a href="https://hgiscanada.usask.ca/">hgiscanada.usask.ca</a> (parent project)
</footer>
</article>
</body>
</html>
"""


PROVINCE_INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{province_name} — Census Subdivisions, 1851–1921 | HGIS Canada</title>
<meta name="description" content="All Census Subdivisions in {province_name} across the 1851–1921 Census of Canada. {place_count} persistent places, {presence_count} year-specific records.">
<link rel="canonical" href="{canonical}">

<meta property="og:type" content="website">
<meta property="og:title" content="{province_name} — Census Subdivisions, 1851–1921">
<meta property="og:description" content="All Census Subdivisions in {province_name} across the 1851–1921 Census of Canada.">

<style>
  body {{ font-family: -apple-system, "Segoe UI", sans-serif; max-width: 900px;
         margin: 2em auto; padding: 0 1em; line-height: 1.55; color: #222; }}
  h1 {{ border-bottom: 1px solid #ddd; padding-bottom: 0.3em; margin-bottom: 0.3em; }}
  .crumbs {{ font-size: 0.9em; color: #666; margin-bottom: 0.5em; }}
  .crumbs a {{ color: #0055aa; }}
  h2 {{ margin-top: 1.6em; }}
  .alphabet {{ position: sticky; top: 0; background: white; padding: 0.5em 0;
             border-bottom: 1px solid #eee; z-index: 10; font-size: 0.95em; }}
  .alphabet a {{ display: inline-block; min-width: 1.5em; text-align: center;
              padding: 0.1em 0.3em; margin: 0 0.05em; color: #0055aa;
              text-decoration: none; border: 1px solid transparent; border-radius: 3px; }}
  .alphabet a:hover {{ background: #e8f1fb; border-color: #cdd; }}
  h3.letter {{ background: #f5f7fa; padding: 0.3em 0.6em; margin-top: 1.5em;
             border-left: 4px solid #0066cc; }}
  ul.places {{ columns: 2; column-gap: 2em; padding-left: 1.4em; }}
  ul.places li {{ break-inside: avoid; }}
  .place-name {{ font-weight: 500; }}
  .years-active {{ color: #888; font-size: 0.85em; }}
  footer {{ margin-top: 3em; font-size: 0.85em; color: #666;
           border-top: 1px solid #ddd; padding-top: 1em; }}
  a {{ color: #0055aa; }}
</style>
</head>
<body>
<article>
<div class="crumbs"><a href="{home_url}">HGIS Canada</a> › {province_name}</div>
<h1>{province_name}</h1>
<p>All Census Subdivisions in {province_name} across the 1851–1921 Census of Canada series.
<strong>{place_count}</strong> persistent places, <strong>{presence_count}</strong> year-specific
records. Each place links to its aggregate page (across years) and from there to the per-year
detail pages.</p>

{cds_section}

<h2>Census Subdivisions</h2>
<div class="alphabet">{alphabet_nav}</div>

{letter_sections}

<script type="application/ld+json">
{jsonld}
</script>

<footer>
<a href="{home_url}">← All provinces</a> &nbsp;·&nbsp;
<a href="{about_url}">About / Methodology</a>
</footer>
</article>
</body>
</html>
"""


ABOUT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>About / Methodology | HGIS Canada Knowledge Graph</title>
<meta name="description" content="About the HGIS Canada Knowledge Graph: methodology, data sources, identity model, and citation guidance for the 1851–1921 Canadian Census Subdivision knowledge graph.">
<link rel="canonical" href="{canonical}">

<meta property="og:type" content="article">
<meta property="og:title" content="About / Methodology — HGIS Canada Knowledge Graph">
<meta property="og:description" content="Methodology, data sources, identity model, and citation guidance.">

<style>
  body {{ font-family: -apple-system, "Segoe UI", sans-serif; max-width: 780px;
         margin: 2em auto; padding: 0 1em; line-height: 1.6; color: #222; }}
  h1 {{ border-bottom: 1px solid #ddd; padding-bottom: 0.3em; margin-bottom: 0.3em; }}
  h2 {{ margin-top: 1.8em; }}
  h3 {{ margin-top: 1.4em; }}
  .crumbs {{ font-size: 0.9em; color: #666; margin-bottom: 0.5em; }}
  .crumbs a {{ color: #0055aa; }}
  blockquote {{ border-left: 3px solid #ccc; margin: 1em 0; padding: 0.2em 0 0.2em 1em;
              color: #555; }}
  code {{ background: #f5f5f5; padding: 0.1em 0.3em; border-radius: 2px; font-size: 0.9em; }}
  a {{ color: #0055aa; }}
  footer {{ margin-top: 3em; font-size: 0.85em; color: #666;
           border-top: 1px solid #ddd; padding-top: 1em; }}
</style>
</head>
<body>
<article>
<div class="crumbs"><a href="{home_url}">HGIS Canada</a> › About / Methodology</div>
<h1>About / Methodology</h1>

<h2>What this is</h2>
<p>The HGIS Canada Knowledge Graph is an academic resource that publishes the Canadian
Census Subdivision (CSD) record, 1851–1921, as a queryable knowledge graph and a
browseable corpus of per-place web pages. It is designed to serve three audiences:</p>
<ul>
<li><strong>Historians and historical geographers</strong> who want to look up a township, follow boundary changes across the eight censuses, or compare neighbours, without downloading and parsing the raw boundary files</li>
<li><strong>The Linked Open Data community</strong>, who can consume the same data as CIDOC-CRM-compliant Turtle published for LINCS interoperability</li>
<li><strong>AI assistants and citation-grounded RAG systems</strong> (Gemini, Claude, ChatGPT, Copilot), which can read the per-place pages — with their prose summaries and Schema.org structured data — to answer citizen questions about Canadian local history with citable sources</li>
</ul>

<h2>Relationship to hgiscanada.usask.ca</h2>
<p>This project builds directly on the
<a href="https://hgiscanada.usask.ca/">Canadian Peoples / TCP project</a> hosted at the
<a href="https://hgis.usask.ca/">HGIS Lab</a>, University of Saskatchewan. That project
provides:</p>
<ul>
<li>Georeferenced polygon boundaries for every Canadian Census Subdivision in each census from 1851 through 1921</li>
<li>Transcribed census tables (population, ethnic origin, religion, agriculture, etc.) joined to the polygons by TCP UID</li>
<li>The original record-pages with raw key-value census data for each CSD-year</li>
</ul>
<p>The HGIS Canada Knowledge Graph reorganises those source files into:</p>
<ul>
<li>A property-graph knowledge base (KuzuDB) with explicit Place / Presence / Measurement / CensusVariable nodes and typed edges (OBSERVED_IN, BORDERS, CONTINUES_AS, OVERLAPS_TEMPORALLY, SPLIT_FROM, MERGED_INTO, MEASURED_AT, OF_VARIABLE, PART_OF_COUNTY)</li>
<li>Per-place prose pages with the full census record, neighbours, cross-year continuity, and Wikidata grounding</li>
<li>A CIDOC-CRM RDF/Turtle export for LINCS publication</li>
</ul>
<p>The TCP project is the data source; this project is a knowledge-graph layer on top of it.
Use this site for browsing, citing, or pointing AI assistants at; use the parent project for
the underlying GIS layers and primary record pages.</p>

<h2>Data model</h2>
<p>Each page describes a <strong>Place</strong> (the enduring concept, e.g. "Westmeath
Township" as a thing that existed across multiple censuses) in a specific
<strong>Presence</strong> (its 1871 census manifestation, with that year's polygon, that
year's tabulated values, that year's neighbours).</p>

<h3>Identity across years</h3>
<p>Identity from one census to the next is established by <strong>spatial polygon overlap</strong>,
not name match. A township that was renamed (Berlin → Kitchener, 1916) or whose census-name
spelling drifted (Pembroke / Pembroke Town–Ville) still threads through to the same enduring
Place if its 1871 polygon overlaps its 1881 polygon at IoU ≥ 0.98 (a strict SAME_AS chain).
This is fundamentally more reliable than name-matching for historical data.</p>

<p>When boundaries shifted enough that the strict SAME_AS chain broke (typically because
a township split off a town or annexed neighbouring land), the
<strong>Boundary continuity</strong> section on each year-page surfaces the partial overlaps
(CONTAINS, WITHIN, OVERLAPS) to adjacent census years. The Pembroke 1851 → Pembroke 1861 +
Pembroke Town–Ville 1861 split is a representative example.</p>

<h3>Wikidata grounding</h3>
<p>Where a persistent Place can be identified with a modern Wikidata entity, the
<code>owl:sameAs</code> link to that Wikidata QID becomes the canonical external identifier
for the place. This means questions about the deep-time meaning of a place (its modern
location, its current administrative status, its name in other languages) inherit from
Wikidata rather than being modelled here. Where Wikidata's coverage is thin (pre-1850 phases,
small townships that were dissolved, conflations of city / metro / county boundaries), this
graph inherits the thinness — we do not attempt to reconstruct what Wikidata does not
provide.</p>

<p>Grounding is performed via an MCP-assisted disambiguation pipeline that uses spatial
distance, name similarity, and entity-type filtering to validate Wikidata candidates. The
~1,000+ verified Ontario matches were produced by this pipeline; the rest of Canada is
in progress. Where no Wikidata match exists, places get a permanent minted URI per LINCS
conventions (this work is staged separately).</p>

<h2>How to cite</h2>
<p>For the project as a whole:</p>
<blockquote>
Clifford, J. (2026). <em>HGIS Canada Knowledge Graph: Census Subdivisions, 1851–1921</em>
[Web resource]. Built on the Canadian Peoples / TCP project. Available at
<a href="{site_url}{base}/">{site_url}{base}/</a>.
</blockquote>

<p>For a specific place-year, cite the page directly using its canonical URL — every page
has a stable URL of the form
<code>{site_url}{base}/places/&lt;prov&gt;/&lt;name&gt;-&lt;tcpuid&gt;-&lt;year&gt;/</code>.
For the underlying TCP source data, cite:</p>
<blockquote>
St-Hilaire, M., Sweeney, S., Inwood, K., et al. <em>Canadian Census Subdivisions, 1851–1921</em>
[Dataset]. Borealis Dataverse.
<a href="https://borealisdata.ca/dataverse/canadiansubdivisions">borealisdata.ca/dataverse/canadiansubdivisions</a>.
</blockquote>

<h2>Reproducibility &amp; source code</h2>
<p>The full pipeline — boundary processing, persistent-place identification via spatial
overlap, Wikidata grounding, knowledge-graph construction in KuzuDB, RDF/Turtle export, and
the page generator behind this site — is in the
<a href="https://github.com/jburnford/Canada-History-Knowledge-Graph">Canada History
Knowledge Graph</a> repository. The pipeline is parametric on province + census year; running
it against an updated TCP release produces a refreshed site in approximately 30 seconds for
the page generation step plus a few minutes for the KuzuDB rebuild.</p>

<h2>Limitations</h2>
<ul>
<li><strong>Boundaries</strong> are derived from TCP's polygon files; any errors there propagate here. Boundary uncertainty for some pre-1881 northern and prairie CSDs is significant.</li>
<li><strong>Census tabulations</strong> are transcribed by the TCP project from the original schedules; transcription errors and OCR artifacts in some early censuses propagate here. Where we found systematic OCR errors in CSD names (e.g. "Wesfwd" → "Westwood"), we corrected them via a canonical-name pass; row-level census values are unchecked.</li>
<li><strong>Wikidata grounding coverage</strong> varies by province — Ontario is essentially complete; other provinces are in progress.</li>
<li><strong>Major cities</strong> (Toronto, Montreal, Halifax) are fragmented across many ward-level CSDs in the source data, so a single "Toronto" page does not exist — instead, dozens of ward pages link to each other. A future iteration may add city-aggregate pages.</li>
<li>The knowledge graph models 1851–1921 only; pre-1850 history is delegated to Wikidata's QID-level depth, and post-1921 census records are out of scope.</li>
</ul>

<h2>Acknowledgments</h2>
<p>This project would not exist without the
<a href="https://hgiscanada.usask.ca/">Canadian Peoples / TCP project</a> at the
<a href="https://hgis.usask.ca/">HGIS Lab</a>, University of Saskatchewan, and the years of
GIS, transcription, and methodological work behind it. Wikidata grounding uses the
WikidataMCP service developed by the Wikimedia Foundation. Knowledge-graph construction is
in <a href="https://kuzudb.com/">KuzuDB</a>. CIDOC-CRM modelling follows the
<a href="https://www.lincsproject.ca/">LINCS</a> application profile.</p>

<footer>
<a href="{home_url}">← Home</a> &nbsp;·&nbsp;
<a href="https://github.com/jburnford/Canada-History-Knowledge-Graph">Source code &amp; data</a>
</footer>
</article>
</body>
</html>
"""


# Display order for census categories. POP and AGE come first because they're
# the most commonly searched, then ETH/REL, then economic data, then DTH, then
# the OTHER bucket of catalog-missing codes last.
CATEGORY_ORDER = ["POP", "AGE", "ETH", "REL", "BLD", "AGR", "MFG", "FSH", "DTH", "OTHER"]
CATEGORY_LABELS = {
    "POP": "Population & families",
    "AGE": "Age structure",
    "ETH": "Ethnic origin",
    "REL": "Religion",
    "BLD": "Buildings & housing",
    "AGR": "Agriculture",
    "MFG": "Manufacturing & industry",
    "FSH": "Fisheries",
    "DTH": "Deaths & mortality",
    "OTHER": "Other recorded variables",
}


def fmt_value(fval, sval):
    """Render a measurement value. Float-as-int when whole, str when present."""
    if sval:
        return html.escape(sval)
    if fval is None:
        return "—"
    if fval == int(fval):
        return f"{int(fval):,}"
    return f"{fval:,.2f}"


# Mastvar labels often end with " produced in the past year" — strip for prose.
_LABEL_SUFFIX_NOISE = re.compile(
    r'\s+(produced\s+in\s+the\s+past\s+year|in\s+the\s+past\s+year)\s*$',
    re.IGNORECASE,
)
_UNIT_PREFIX_WORDS = (
    'Bushels', 'Acres', 'Pounds', 'Tons', 'Gallons', 'Quintals',
    'Yards', 'Feet', 'Fathoms', 'Barrels',
)
# Labels longer than this render as their own sentence (avoids run-on commas
# for sensitive-term descriptions like NEGRO/INDIAN/JEWISH/etc.)
_LONG_LABEL_THRESHOLD = 70


def _humanize_phrase(value_str: str, label: str, unit: str) -> str:
    """Render one (value, label, unit) tuple as a natural-language fragment.

    Heuristics (try in order):
      "Number of X"       -> "<value> X"
      "<UnitWord> of X"   -> "<value> <unitword> of X"   (lowercases prefix)
      "Value of X"        -> "$<value> value of X"
      starts with "Total" -> "<label>: <value>"
      everything else     -> "<label>: <value>"
    """
    if not label:
        return f"{value_str} ({unit or 'count'})"
    s = _LABEL_SUFFIX_NOISE.sub('', label.strip())
    s_low = s.lower()
    if s_low.startswith('number of '):
        return f"{value_str} {s[len('Number of '):]}"
    if s_low.startswith('number or '):
        return f"{value_str} {s[len('Number or '):]}"
    for w in _UNIT_PREFIX_WORDS:
        if s.startswith(w + ' '):
            return f"{value_str} {w.lower()}{s[len(w):]}"
    if s.startswith('Value of '):
        return f"${value_str} value{s[len('Value of'):]}"
    # Natural-language pre-pend for these phrasings ("Total population",
    # "Average size of families", "Population per square mile", "Area in acres",
    # "Persons aged 5 and over who can both read and write", etc.). Lowercase
    # only the leading word so proper nouns (Indigenous, V1T1, Indian Act) are
    # preserved.
    PREPEND_PREFIXES = (
        'total ', 'average ', 'population ', 'area ', 'persons ',
        'rural ', 'urban ',
    )
    if any(s_low.startswith(p) for p in PREPEND_PREFIXES):
        first, _, rest = s.partition(' ')
        first_lc = first[:1].lower() + first[1:] if first else first
        decapped = f"{first_lc} {rest}" if rest else first_lc
        return f"{value_str} {decapped}"
    return f"{s}: {value_str}"


def _source_tables_for_year(source_tables_str: str, year: int):
    """Parse 'YYYY:Vxxx,YYYY:Vxxx' and return the table for `year`, or None."""
    if not source_tables_str:
        return None
    for entry in source_tables_str.split(','):
        y, _, t = entry.partition(':')
        if y.strip() == str(year):
            return t.strip()
    return None


def _format_citation(year: int, tables: set) -> str:
    """'(Source: 1881 Census of Canada, V1T1; V3T24.)' — empty if no tables."""
    if not tables:
        return ''
    joined = '; '.join(sorted(tables))
    return f' <em>(Source: {year} Census of Canada, {joined}.)</em>'


# ---------------------------------------------------------------------------
# DCB persons section
#
# Surfaces people with Dictionary of Canadian Biography entries on the CSD
# pages where they had a birth/death/burial event, for every census year their
# lifespan overlaps. Sourced from data/lincs_person_csd_links.csv (Strategy 1
# Wikidata-QID match + Strategy 3 GeoNames point-in-polygon, deduped) and
# data/lincs_dcb_persons.json (full per-person metadata: birth/death years,
# occupations, DCB URL).
#
# Framing is deliberately neutral. The DCB cohort includes both celebrated
# figures and people whose biographies exist because they were anti-heroes or
# victims — labelling the section "Notable Canadians" would impose a value
# judgment the source doesn't make. Heading reads as a sourcing statement
# rather than an editorial pick.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
LINCS_LINKS_CSV = REPO_ROOT / "data" / "lincs_person_csd_links.csv"
LINCS_PERSONS_JSON = REPO_ROOT / "data" / "lincs_dcb_persons.json"
CENSUS_YEARS_FOR_PERSONS = [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921]


def _closest_census_year(year):
    if year is None:
        return None
    if year <= CENSUS_YEARS_FOR_PERSONS[0]:
        return CENSUS_YEARS_FOR_PERSONS[0]
    if year >= CENSUS_YEARS_FOR_PERSONS[-1]:
        return CENSUS_YEARS_FOR_PERSONS[-1]
    return min(CENSUS_YEARS_FOR_PERSONS, key=lambda y: abs(y - year))


def _connection_tag(event_types: set) -> str:
    has_birth = "birth" in event_types
    has_death = "death" in event_types
    has_burial = "burial" in event_types
    if has_birth and (has_death or has_burial):
        return "born and died here" if has_death else "born here, buried here"
    if has_birth:
        return "born here"
    if has_death:
        return "died here"
    if has_burial:
        return "buried here"
    return ""


def _format_lifespan(birth_year, death_year) -> str:
    if birth_year and death_year:
        return f"{birth_year}–{death_year}"
    if birth_year:
        return f"b. {birth_year}"
    if death_year:
        return f"d. {death_year}"
    return ""


def _join_with_and(items: list) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def prefetch_persons():
    """Load DCB-cohort person records + place links.

    Returns:
      persons_by_place_year: dict[(place_id, year)] -> list of person dicts
      persons_by_place:      dict[place_id] -> list of person dicts (all years)

    Empty defaultdicts are returned silently if the link CSV / persons JSON
    aren't on disk, so the renderer falls back to the no-section case.
    """
    if not LINCS_LINKS_CSV.exists() or not LINCS_PERSONS_JSON.exists():
        print("[prefetch] DCB person data not found, skipping persons section",
              flush=True)
        return defaultdict(list), defaultdict(list)

    print("[prefetch] DCB persons + place links...", flush=True)

    with open(LINCS_PERSONS_JSON) as f:
        cohort = json.load(f)["persons"]
    person_meta = {p["personId"]: p for p in cohort}

    # Aggregate the multi-row link table into one entry per (place_id, person_id)
    # so a person who has both a birth and a death link at the same place
    # collapses to a single record with combined event_types.
    by_place_person: dict = {}
    with open(LINCS_LINKS_CSV) as f:
        for row in csv.DictReader(f):
            place_id = row["place_id"]
            pid = row["person_id"]
            key = (place_id, pid)
            if key not in by_place_person:
                meta = person_meta.get(pid, {})
                by_place_person[key] = {
                    "person_id": pid,
                    "name": row.get("person_name") or meta.get("name") or "Unknown",
                    "dcb_url": row.get("dcb_url") or meta.get("dcb_url"),
                    "wikidata_qid": row.get("person_qid") or meta.get("wikidataQid"),
                    "birth_year": meta.get("birthYear"),
                    "death_year": meta.get("deathYear"),
                    "event_types": set(),
                    "occupations": meta.get("occupations") or [],
                }
            by_place_person[key]["event_types"].add(row["event_type"])

    persons_by_place: dict = defaultdict(list)
    for (place_id, _), entry in by_place_person.items():
        persons_by_place[place_id].append(entry)

    # Lifespan-overlap surface rule: a person appears on (place, census_year)
    # for every census year their [birth_year, death_year] interval covers.
    # Skip persons whose lifespan we don't have at all — without dates we
    # can't responsibly say "this person was alive in {year}".
    persons_by_place_year: dict = defaultdict(list)
    for place_id, entries in persons_by_place.items():
        for entry in entries:
            by = entry["birth_year"]
            dy = entry["death_year"]
            if by is None and dy is None:
                continue
            for cy in CENSUS_YEARS_FOR_PERSONS:
                if by is not None and cy < by:
                    continue
                if dy is not None and cy > dy:
                    continue
                persons_by_place_year[(place_id, cy)].append(entry)

    print(f"[prefetch]   {len(persons_by_place)} places with DCB persons, "
          f"{sum(len(v) for v in persons_by_place_year.values())} (place,year) entries",
          flush=True)
    return persons_by_place_year, persons_by_place


def _person_link(person: dict) -> str:
    name = html.escape(person["name"])
    url = person.get("dcb_url")
    if url:
        return f'<a href="{html.escape(url)}">{name}</a>'
    return name


def _persons_table(persons: list) -> str:
    """Three-column HTML table: Name | Lifespan | Connection.

    Sorted by birth_year ascending (chronological), then name. Stable across
    runs so the rendered HTML diffs are minimal.
    """
    sorted_persons = sorted(
        persons,
        key=lambda p: (p.get("birth_year") or 9999, p["name"].lower()),
    )
    rows = []
    for p in sorted_persons:
        name_cell = _person_link(p)
        lifespan = html.escape(_format_lifespan(p.get("birth_year"),
                                                 p.get("death_year")))
        tag = html.escape(_connection_tag(p["event_types"]))
        rows.append(
            f"<tr><td>{name_cell}</td><td>{lifespan}</td>"
            f"<td>{tag}</td></tr>"
        )
    return (
        "<table class=\"dcb-persons\">\n"
        "<tr><th>Name</th><th>Lifespan</th><th>Connection</th></tr>\n"
        + "\n".join(rows)
        + "\n</table>"
    )


def render_persons_section(persons: list, year: int) -> str:
    """Per-year section (slotted between measurements and Identifiers).

    Renders every person whose lifespan covers `year`. No cap — this is bonus
    content where the DCB link itself is the value; comprehensiveness matters
    more than prose density.
    """
    if not persons:
        return ""
    intro = (
        f"<p>The "
        f'<a href="https://www.biographi.ca/">Dictionary of Canadian Biography</a> '
        f"includes biographies of {len(persons)} "
        f"{'person' if len(persons) == 1 else 'people'} "
        f"connected to this place who were alive in {year}, listed below by "
        f"birth year. Each name links to that person's DCB entry.</p>"
    )
    return (
        "<h2>People with Dictionary of Canadian Biography entries</h2>\n"
        + intro + "\n"
        + _persons_table(persons)
    )


def render_persons_aggregate_section(persons: list) -> str:
    """Full list of persons connected to a persistent place across all years."""
    if not persons:
        return ""
    intro = (
        f'<p>The <a href="https://www.biographi.ca/">Dictionary of Canadian '
        f"Biography</a> includes biographies of {len(persons)} "
        f"{'person' if len(persons) == 1 else 'people'} connected to this "
        f"place across the 1851–1921 period, listed below by birth year. "
        f"Each name links to that person's DCB entry; the connection tag "
        f"indicates whether the documented event was a birth, death, or "
        f"burial at this place.</p>"
    )
    return (
        "<h2>People with Dictionary of Canadian Biography entries</h2>\n"
        + intro + "\n"
        + _persons_table(persons)
    )


def _persons_jsonld_mentions(persons: list) -> list:
    """Build Schema.org Person entries for the JSON-LD `mentions` array.

    No cap — `mentions` is machine-readable; the size cost is small per-Person
    and bots benefit from completeness.
    """
    out = []
    for p in persons:
        entry = {
            "@type": "Person",
            "name": p["name"],
        }
        urls = []
        if p.get("dcb_url"):
            entry["url"] = p["dcb_url"]
            urls.append(p["dcb_url"])
        if p.get("wikidata_qid"):
            urls.append(f"https://www.wikidata.org/entity/{p['wikidata_qid']}")
        if urls:
            entry["sameAs"] = urls if len(urls) > 1 else urls[0]
        if p.get("birth_year"):
            entry["birthDate"] = str(p["birth_year"])
        if p.get("death_year"):
            entry["deathDate"] = str(p["death_year"])
        out.append(entry)
    return out


def render_measurements_section(measurements: list, year: int) -> str:
    """measurements is a list of 8-tuples:
        (category, label, fval, sval, var_code, unit, source_tables, quality)

    Renders one prose paragraph per category. Within each paragraph:
      - Signal-quality vars listed by descending value, comma-joined.
      - Long-label vars (sensitive-term descriptions) get their own sentence.
      - Sparse-quality vars folded into a per-category footnote.
      - Source-table citation appended in italics.
    """
    if not measurements:
        return ""
    by_cat: dict = {}
    for cat, label, fval, sval, var_code, unit, source_tables, quality in measurements:
        by_cat.setdefault(cat or "OTHER", []).append(
            (label, fval, sval, var_code, unit, source_tables, quality)
        )

    ordered = [c for c in CATEGORY_ORDER if c in by_cat] + \
              sorted(c for c in by_cat if c not in CATEGORY_ORDER)

    total = sum(len(v) for v in by_cat.values())
    blocks = [
        f"<h2>Full census record, {year}</h2>",
        f"<p>The {year} census recorded <strong>{total}</strong> "
        f"measurements for this Census Subdivision across "
        f"<strong>{len(by_cat)}</strong> "
        f"categor{'ies' if len(by_cat) != 1 else 'y'}.</p>",
    ]

    for cat in ordered:
        rows = by_cat[cat]
        cat_label = CATEGORY_LABELS.get(cat, cat)

        signal = [r for r in rows if (r[6] or '').lower() != 'sparse']
        sparse = [r for r in rows if (r[6] or '').lower() == 'sparse']

        # Sort signal by descending numeric value; non-numeric/strings drop to
        # the end. Stable secondary sort by label for determinism.
        def _sort_key(r):
            fval = r[1]
            try:
                v = float(fval) if fval is not None else float('-inf')
            except (TypeError, ValueError):
                v = float('-inf')
            return (-v, (r[0] or '').lower())
        signal.sort(key=_sort_key)

        # Build phrases and gather per-row source tables for the current year.
        short_phrases = []
        long_sentences = []
        tables_year = set()
        for label, fval, sval, var_code, unit, src_tbls, _q in signal:
            phrase = _humanize_phrase(fmt_value(fval, sval), label or '', unit or '')
            tbl = _source_tables_for_year(src_tbls or '', year)
            if tbl:
                tables_year.add(tbl)
            # Use the cleaned label length (post suffix-strip) so AGR variants
            # like "Bushels of clover, timothy, or other grass seed produced in
            # the past year" don't get split off into their own sentence just
            # because of the boilerplate suffix.
            cleaned = _LABEL_SUFFIX_NOISE.sub('', (label or '').strip())
            if len(cleaned) > _LONG_LABEL_THRESHOLD:
                # Avoid double-period when the label itself ends with one.
                ending = '' if phrase.rstrip().endswith('.') else '.'
                long_sentences.append(phrase + ending)
            else:
                short_phrases.append(phrase)

        # Body: short fragments comma-joined as one sentence + long entries
        # as their own sentences.
        body_parts = []
        if short_phrases:
            joined = ', '.join(html.escape(p) for p in short_phrases)
            body_parts.append(f"This community's record includes {joined}.")
        for s in long_sentences:
            body_parts.append(html.escape(s))

        body = ' '.join(body_parts) if body_parts else ''
        citation = _format_citation(year, tables_year)

        # Sparse footnote — collapsed to one trailing sentence.
        footnote = ''
        if sparse:
            sparse_phrases = []
            for label, fval, sval, var_code, unit, _src, _q in sparse:
                sparse_phrases.append(
                    _humanize_phrase(fmt_value(fval, sval), label or '', unit or '')
                )
            joined = ', '.join(html.escape(p) for p in sparse_phrases)
            footnote = (
                f' <span class="sparse-footnote"><em>The {year} enumerator '
                f'also recorded {joined} — single-county tallies of limited '
                f'cross-year comparability.</em></span>'
            )

        if not body and not footnote:
            continue

        blocks.append(
            f'<p><strong>{cat_label} ({year}).</strong> {body}{citation}{footnote}</p>'
        )

    return "\n".join(blocks)


def render_overlaps_section(overlaps, year, base, prov_code):
    """Render an "Earlier/later boundary forms" section from OVERLAPS_TEMPORALLY
    edges (CONTAINS / WITHIN / OVERLAPS — non-SAME_AS spatial chains).

    overlaps = list of (direction, overlap_type, iou, other_year, other_tcpuid,
                        other_name, other_province)
    """
    if not overlaps:
        return ""

    # Forward = this place's territory in a LATER year overlapping with `other`.
    # Backward = this place was reached by `other`'s territory from an EARLIER year.
    # We re-bucket purely by other_year ↔ year for readability.
    earlier = []
    later = []
    for direction, otype, iou, other_year, other_tcpuid, other_name, other_prov in overlaps:
        if other_year == year:
            continue
        href = url_for_presence(other_name, other_tcpuid, other_year, base, other_prov or prov_code)
        link = f'<a href="{href}">{html.escape(other_name)}, {other_year}</a>'
        pct = f"{iou * 100:.1f}%"
        # Verbal description per overlap_type + direction:
        if direction == "forward":
            if otype == "CONTAINS":
                desc = f"contained {link} ({pct} of this CSD's polygon)"
            elif otype == "WITHIN":
                desc = f"became part of {link} ({pct} share)"
            else:
                desc = f"partially overlapped {link} ({pct} IoU)"
        else:
            if otype == "CONTAINS":
                desc = f"was contained in {link} ({pct} share)"
            elif otype == "WITHIN":
                desc = f"contained {link} ({pct} share)"
            else:
                desc = f"partially overlapped {link} ({pct} IoU)"

        if other_year < year:
            earlier.append(desc)
        else:
            later.append(desc)

    blocks = ["<h2>Boundary continuity (non-identical overlaps)</h2>",
              "<p>Spatial polygon overlaps with adjacent census years where the boundary "
              "shifted enough that the SAME_AS chain didn't merge them. These show "
              "where the territory came from and went to even when it isn't tracked "
              "as the same persistent place.</p>"]
    if earlier:
        blocks.append("<h3>Earlier boundary forms</h3>\n<ul>")
        for d in earlier:
            blocks.append(f"<li>In an earlier year, this CSD {d}.</li>")
        blocks.append("</ul>")
    if later:
        blocks.append("<h3>Later boundary forms</h3>\n<ul>")
        for d in later:
            blocks.append(f"<li>In a later year, this CSD {d}.</li>")
        blocks.append("</ul>")
    return "\n".join(blocks)


def render_page(row, traj, neighbours, measurements, overlaps, persons, *,
                site_url: str, base: str) -> str:
    (place_id, name, qid, place_type, prov_code, tcpuid, year, area_sqm,
     lat, lon, pop, pop_m, pop_f, density, cd_name, enwiki_url, frwiki_url) = row

    province = PROVINCE_NAMES.get(prov_code, prov_code)
    page_path = url_for_presence(name, tcpuid, year, base, prov_code)
    canonical = f"{site_url}{page_path}"
    home_url = f"{base}/"

    # Tier-aware noun (city / town / village / parish / township / settlement).
    if place_type == "CD":
        kind_word = "county"
    else:
        _, _tier = _parse_csd_name(name)
        kind_word = {
            "City": "city", "Town": "town", "Village": "village",
            "Parish": "parish", "Township": "township",
            "Municipality": "municipality",
        }.get(_tier, "census subdivision")

    article = "an" if kind_word and kind_word[0].lower() in "aeiou" else "a"
    title = f"{name}, {province} ({year} census)"
    description = (
        f"{name} was {article} {kind_word} in "
        f"{cd_name + ' County, ' if cd_name else ''}{province}, "
        f"recorded in the {year} Census of Canada"
        + (f" with a population of {fmt_pop(pop)}." if pop else ".")
    )
    description_short = description[:200]

    # Indian Reserve handling: suppress Wikidata claims (the chain may have been
    # auto-matched but asserting modern band identity for a census-aggregate
    # entity would overstep). The QID stays in the underlying data; the page
    # just doesn't display it. Generic methodological note prepended below.
    is_ir = is_indian_reserve(name)

    # County meta line — link to the CD index page when a real CD name exists.
    # Pass `year` so url_for_cd can resolve the raw NAME_CD to the chain URL
    # (handles canonicalization like "Renfrew, North—Nord" → "renfrew-north"
    # and disambiguators like "york-1921").
    county_meta = ""
    if cd_name:
        cd_href = url_for_cd(cd_name, prov_code, base, year=year)
        cd_display = cd_link_label(cd_name, year=year, province=prov_code)
        county_meta = (f"\n&nbsp;|&nbsp; <strong>County:</strong> "
                       f'<a href="{cd_href}">{html.escape(cd_display)}</a>')

    # Wikidata meta line (header) — suppressed for IR pages.
    wikidata_meta = ""
    if qid and not is_ir:
        wikidata_meta = (
            f'\n&nbsp;|&nbsp; <strong>Wikidata:</strong> '
            f'<a href="https://www.wikidata.org/wiki/{qid}">{qid}</a>'
        )

    # Open Graph geo
    og_geo = ""
    if lat is not None and lon is not None:
        og_geo = (
            f'<meta property="place:location:latitude" content="{lat:.6f}">\n'
            f'<meta property="place:location:longitude" content="{lon:.6f}">'
        )

    # Wikidata <link> — suppressed for IR pages.
    wikidata_link = ""
    if qid and not is_ir:
        wikidata_link = (
            f'<link rel="alternate" type="text/html" '
            f'href="https://www.wikidata.org/wiki/{qid}" '
            f'title="Wikidata: {qid}">'
        )

    heading = title

    # Intro paragraph. For IR pages, prepend the methodological note and
    # suppress the "grounded to Wikidata" claim. Note: template no longer
    # wraps intro in <p>, so we control the paragraph structure here so the
    # IR note (a <div>) doesn't end up nested inside a <p>.
    intro_text = description
    if qid and not is_ir:
        intro_text += (
            f' The community is grounded to Wikidata '
            f'<a href="https://www.wikidata.org/wiki/{qid}">{qid}</a>.'
        )
    if lat is not None and lon is not None:
        intro_text += f" The administrative centroid was at approximately {lat:.3f}°N, {abs(lon):.3f}°W."
    intro = f"<p>{intro_text}</p>"
    if is_ir:
        intro = IR_NOTE_HTML + "\n" + intro

    # Population section. Trust the source pop_m/pop_f and pop_per_sq_mi now
    # that the V1T1 ↔ TCPUID crosswalk has eliminated the silent mis-joins.
    # The defensive checks added in v9.1 (suppress on m+f mismatch, recompute
    # density from area) were appropriate while the underlying data was wrong;
    # post-v9.2 they would mask real source-data issues and should not fire.
    population_section = ""
    if pop:
        if pop_m and pop_f:
            pop_text = (
                f"In {year}, <strong>{html.escape(name)}</strong> had a population of "
                f"<strong>{fmt_pop(pop)}</strong>: {fmt_pop(pop_m)} male and "
                f"{fmt_pop(pop_f)} female residents."
            )
        else:
            pop_text = (
                f"In {year}, <strong>{html.escape(name)}</strong> had a population of "
                f"<strong>{fmt_pop(pop)}</strong>."
            )
        if density is not None:
            pop_text += f" Population density was {density:.1f} people per square mile."
        population_section = f"<h2>Population</h2>\n<p>{pop_text}</p>"

    # Trajectory section
    trajectory_section = ""
    if len(traj) > 1:
        rows = []
        for tyr, tpop, ttcpuid in traj:
            if tyr == year:
                year_cell = f"<strong>{tyr}</strong>"
            else:
                href = url_for_presence(name, ttcpuid, tyr, base, prov_code)
                year_cell = f'<a href="{href}">{tyr}</a>'
            rows.append(f"<tr><td>{year_cell}</td><td>{fmt_pop(tpop)}</td></tr>")
        trajectory_section = (
            "<h2>Population trajectory across census years</h2>\n"
            "<table>\n<tr><th>Year</th><th>Population</th></tr>\n"
            + "\n".join(rows) + "\n</table>\n"
            "<p><em>Cross-year identity established by spatial polygon overlap "
            "(SAME_AS chains across the Canadian Census Subdivision boundary files).</em></p>"
        )

    # Full measurements (all variables in any category)
    measurements_section = render_measurements_section(measurements, year)

    # People with DCB entries connected to this place who were alive in `year`
    persons_section = render_persons_section(persons, year)

    # Boundary continuity (non-SAME_AS overlaps with adjacent census years)
    overlaps_section = render_overlaps_section(overlaps, year, base, prov_code)

    # Neighbours section
    neighbours_section = ""
    if neighbours:
        items = []
        for nname, npid, ntcpuid, nprov in neighbours:
            href = url_for_presence(nname, ntcpuid, year, base, nprov or prov_code)
            items.append(f'<li><a href="{href}">{html.escape(nname)}</a></li>')
        neighbours_section = (
            f"<h2>Neighbouring Census Subdivisions in {year}</h2>\n"
            f"<p>In the {year} census, {html.escape(name)} shared boundaries with:</p>\n"
            f"<ul>\n" + "\n".join(items) + "\n</ul>"
        )

    # Wikidata identifier list-item — includes Wikipedia links when available.
    # Suppressed for Indian Reserve pages (IR aggregates shouldn't claim
    # modern Wikidata band identity even when the chain was matched).
    if qid and not is_ir:
        wikidata_id = (
            f'<li><strong>Wikidata:</strong> '
            f'<a href="https://www.wikidata.org/wiki/{qid}">{qid}</a></li>'
        )
        if enwiki_url:
            wikidata_id += (
                f'\n<li><strong>Wikipedia (EN):</strong> '
                f'<a href="{html.escape(enwiki_url)}">{html.escape(enwiki_url)}</a></li>'
            )
        if frwiki_url:
            wikidata_id += (
                f'\n<li><strong>Wikipédia (FR):</strong> '
                f'<a href="{html.escape(frwiki_url)}">{html.escape(frwiki_url)}</a></li>'
            )
    elif is_ir:
        wikidata_id = (
            "<li><em>External authority links suppressed for Indian Reserve "
            "entries. See methodological note above.</em></li>"
        )
    else:
        wikidata_id = (
            "<li><strong>Wikidata:</strong> <em>not yet grounded.</em> "
            "This page covers a place whose persistent identity has not yet been linked to "
            "a Wikidata entity. Identification is via TCP UID and spatial polygon only.</li>"
        )

    # Schema.org JSON-LD
    jsonld_obj = {
        "@context": "https://schema.org",
        "@type": "Place",
        "name": f"{name} ({year})",
        "description": description,
        "address": {
            "@type": "PostalAddress",
            "addressRegion": province,
            "addressCountry": "CA",
        },
    }
    if lat is not None and lon is not None:
        jsonld_obj["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
        }
    if qid:
        same_as = [f"https://www.wikidata.org/entity/{qid}"]
        if enwiki_url:
            same_as.append(enwiki_url)
        if frwiki_url:
            same_as.append(frwiki_url)
        jsonld_obj["sameAs"] = same_as if len(same_as) > 1 else same_as[0]
    if cd_name:
        jsonld_obj["containedInPlace"] = {
            "@type": "AdministrativeArea",
            "name": f"{cd_name} County, {province}",
        }
    # additionalProperty: top-N signal-quality Schema.org PropertyValue
    # entries — enough for crawlers / Schema.org consumers without bloating
    # the page. The full per-measurement dataset is referenced via subjectOf
    # below so programmatic consumers can pick it up from facts/<year>.jsonl.
    JSONLD_PROPERTY_CAP = 30
    if measurements:
        signal = [m for m in measurements if (m[7] or "").lower() != "sparse"]

        def _vsort(m):
            fval = m[2]
            try:
                return -float(fval) if fval is not None else 0
            except (TypeError, ValueError):
                return 0
        signal.sort(key=_vsort)

        props = []
        for cat, label, fval, sval, var_code, unit, src_tbls, quality in signal[:JSONLD_PROPERTY_CAP]:
            value = sval if (sval is not None and sval != "") else fval
            if value is None:
                continue
            if isinstance(value, float) and value == int(value):
                value = int(value)
            bare = (var_code or "").removeprefix("VAR_") if var_code else ""
            tbl = _source_tables_for_year(src_tbls or "", year)
            entry = {
                "@type": "PropertyValue",
                "name": label or bare,
                "value": value,
            }
            if bare:
                entry["propertyID"] = f"{site_url}{base}/vocab/var/{bare}"
            if unit:
                entry["unitText"] = unit
            if cat:
                entry["valueReference"] = {
                    "@type": "DefinedTerm",
                    "name": CATEGORY_LABELS.get(cat, cat),
                    "inDefinedTermSet": f"{site_url}{base}/vocab/category/{cat}",
                }
            if tbl:
                entry["citation"] = f"{year} Census of Canada, {tbl}"
            props.append(entry)
        if props:
            jsonld_obj["additionalProperty"] = props

        # Pointer to the full per-year facts file for programmatic consumers.
        jsonld_obj["subjectOf"] = {
            "@type": "Dataset",
            "name": f"Full census measurements ({year})",
            "description": (
                f"All {len(measurements)} measurements recorded for this "
                f"Census Subdivision in {year}, in JSONL form. "
                f"Filter by tcpuid={tcpuid} and year={year} for this subject."
            ),
            "distribution": {
                "@type": "DataDownload",
                "encodingFormat": "application/x-ndjson",
                "contentUrl": f"{site_url}{base}/facts/{year}.jsonl",
            },
        }

    # Schema.org `mentions` for people with DCB entries surfaced on this page.
    # The page is *about* the place; it *mentions* the persons.
    if persons:
        mentions = _persons_jsonld_mentions(persons)
        if mentions:
            jsonld_obj["mentions"] = mentions

    return PAGE_TEMPLATE.format(
        title=html.escape(title),
        description=html.escape(description_short),
        canonical=canonical,
        og_geo=og_geo,
        wikidata_link=wikidata_link,
        year=year,
        province=province,
        county_meta=county_meta,
        wikidata_meta=wikidata_meta,
        heading=html.escape(heading),
        intro=intro,
        population_section=population_section,
        trajectory_section=trajectory_section,
        overlaps_section=overlaps_section,
        neighbours_section=neighbours_section,
        measurements_section=measurements_section,
        persons_section=persons_section,
        tcpuid=tcpuid,
        place_id=place_id,
        wikidata_id=wikidata_id,
        jsonld=json.dumps(jsonld_obj, indent=2),
        home_url=home_url,
        place_index_url=url_for_place(name, place_id, base, prov_code),
        prov_index_url=f"{base}/places/{prov_code.lower()}/",
        about_url=f"{base}/about/",
        name_html=html.escape(name),
    ), page_path


def prefetch_all_data(conn):
    """Run a handful of big queries up-front and return dicts the per-page
    rendering can look up in O(1). Trades memory for speed: ~150 MB for
    full-Canada, ~10× faster than per-page Cypher queries."""
    print("[prefetch] presence + place rows...", flush=True)
    presence_data = {}        # presence_id -> row tuple as expected by render_page
    place_to_presences = defaultdict(list)  # place_id -> [(year, pop, tcpuid)]
    res = conn.execute(
        "MATCH (pr:Presence)-[:OBSERVED_IN]->(pl:Place) "
        "RETURN pr.presence_id, pl.place_id, pl.name, pl.wikidata_qid, pl.place_type, "
        "pl.province, pr.tcpuid, pr.year, pr.area_sqm, pr.centroid_lat, pr.centroid_lon, "
        "pr.pop_total, pr.pop_total_m, pr.pop_total_f, pr.pop_per_sq_mi, pr.cd_name, "
        "pl.enwiki_url, pl.frwiki_url;"
    )
    while res.has_next():
        r = res.get_next()
        presence_id = r[0]
        # render_page expects: (place_id, name, qid, place_type, prov_code, tcpuid,
        #                       year, area_sqm, lat, lon, pop, pop_m, pop_f,
        #                       density, cd_name)
        presence_data[presence_id] = tuple(r[1:])
        place_to_presences[r[1]].append((r[7], r[11], r[6]))  # year, pop, tcpuid
    # Sort trajectories by year.
    for k in place_to_presences:
        place_to_presences[k].sort(key=lambda t: t[0] or 0)
    print(f"[prefetch]   {len(presence_data)} presences", flush=True)

    print("[prefetch] borders...", flush=True)
    # neighbours_by_presence[(place_id, year)] -> [(name, place_id, tcpuid, prov)]
    neighbours_by_presence = defaultdict(list)
    res = conn.execute(
        "MATCH (pr:Presence)-[:BORDERS]-(n:Presence)-[:OBSERVED_IN]->(np:Place) "
        "MATCH (pr)-[:OBSERVED_IN]->(plp:Place) "
        "RETURN plp.place_id, pr.year, np.name, np.place_id, n.tcpuid, np.province;"
    )
    seen = set()
    while res.has_next():
        r = res.get_next()
        key = (r[0], r[1])
        triple = (r[2], r[3], r[4], r[5])
        # Distinct + sorted (sort happens once, after).
        de_key = (key, r[3], r[4])  # by place_id + tcpuid for distinctness
        if de_key in seen:
            continue
        seen.add(de_key)
        neighbours_by_presence[key].append(triple)
    for k in neighbours_by_presence:
        neighbours_by_presence[k].sort(key=lambda t: (t[0] or "").lower())
    print(f"[prefetch]   {sum(len(v) for v in neighbours_by_presence.values())} neighbour rows", flush=True)

    print("[prefetch] measurements...", flush=True)
    # meas_by_presence[presence_id] ->
    #   [(category, label, fval, sval, var_code, unit, source_tables, quality)]
    meas_by_presence = defaultdict(list)
    res = conn.execute(
        "MATCH (pr:Presence)-[:MEASURED_AT]->(m:Measurement)-[:OF_VARIABLE]->(v:CensusVariable) "
        "RETURN pr.presence_id, v.category, v.label, m.value_float, m.value_string, "
        "v.var_code, v.unit, v.source_tables, v.quality;"
    )
    while res.has_next():
        r = res.get_next()
        meas_by_presence[r[0]].append(
            (r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8])
        )
    print(f"[prefetch]   {sum(len(v) for v in meas_by_presence.values())} measurement rows", flush=True)

    print("[prefetch] OVERLAPS_TEMPORALLY...", flush=True)
    # overlaps_by_presence[presence_id] -> [(direction, type, iou, oyear, otcpuid, oname, oprov)]
    overlaps_by_presence = defaultdict(list)
    res = conn.execute(
        "MATCH (pr:Presence)-[o:OVERLAPS_TEMPORALLY]->(other:Presence)-[:OBSERVED_IN]->(op:Place) "
        "RETURN pr.presence_id, o.overlap_type, o.iou, other.year, other.tcpuid, op.name, op.province;"
    )
    while res.has_next():
        r = res.get_next()
        overlaps_by_presence[r[0]].append(("forward", r[1], r[2], r[3], r[4], r[5], r[6]))
    res = conn.execute(
        "MATCH (other:Presence)-[o:OVERLAPS_TEMPORALLY]->(pr:Presence)-[:OBSERVED_IN]->(plp:Place) "
        "MATCH (other)-[:OBSERVED_IN]->(op:Place) "
        "RETURN pr.presence_id, o.overlap_type, o.iou, other.year, other.tcpuid, op.name, op.province;"
    )
    while res.has_next():
        r = res.get_next()
        overlaps_by_presence[r[0]].append(("backward", r[1], r[2], r[3], r[4], r[5], r[6]))
    print(f"[prefetch]   {sum(len(v) for v in overlaps_by_presence.values())} overlap rows", flush=True)

    persons_by_place_year, persons_by_place = prefetch_persons()

    return (presence_data, place_to_presences, neighbours_by_presence,
            meas_by_presence, overlaps_by_presence,
            persons_by_place_year, persons_by_place)


def page_for_presence(presence_id, prefetched, *, site_url, base):
    """Look up pre-fetched data and render the year-page."""
    (presence_data, place_to_presences, neighbours_by_presence,
     meas_by_presence, overlaps_by_presence,
     persons_by_place_year, _persons_by_place) = prefetched

    row = presence_data.get(presence_id)
    if row is None:
        return None
    place_id = row[0]
    year = row[6]

    traj = place_to_presences.get(place_id, [])
    neighbours = neighbours_by_presence.get((place_id, year), [])
    measurements = meas_by_presence.get(presence_id, [])
    overlaps = overlaps_by_presence.get(presence_id, [])
    persons = persons_by_place_year.get((place_id, year), [])

    body, page_path = render_page(row, traj, neighbours, measurements, overlaps,
                                  persons,
                                  site_url=site_url, base=base)
    rel_dir = page_path.lstrip("/").rstrip("/")
    if base and rel_dir.startswith(base.lstrip("/")):
        rel_dir = rel_dir[len(base.lstrip("/")):].lstrip("/")
    return rel_dir, body, f"{site_url}{page_path}"


def render_place_page(place_row, traj, lineage_in, lineage_out, persons, *,
                      site_url: str, base: str) -> tuple[str, str]:
    """place_row = (place_id, name, wikidata_qid, place_type, province, enwiki_url, frwiki_url)
       traj      = list of (year, pop_total, tcpuid)
       lineage_in  = list of (kind, source_place_id, source_name, source_province, change_year)
       lineage_out = list of (kind, target_place_id, target_name, target_province, change_year)
    """
    place_id, name, qid, place_type, prov_code, enwiki_url, frwiki_url = place_row
    province = PROVINCE_NAMES.get(prov_code, prov_code)
    page_path = url_for_place(name, place_id, base, prov_code)
    canonical = f"{site_url}{page_path}"
    home_url = f"{base}/"

    years_present = sorted({yr for yr, _, _ in traj})
    if years_present:
        year_range = f"{years_present[0]}–{years_present[-1]}"
    else:
        year_range = "—"

    is_ir = is_indian_reserve(name)
    if place_type == "CD":
        kind_word = "county"
    elif is_ir:
        kind_word = "Indian Reserve census entry"
    else:
        _, _tier = _parse_csd_name(name)
        kind_word = {
            "City": "city", "Town": "town", "Village": "village",
            "Parish": "parish", "Township": "township",
            "Municipality": "municipality",
        }.get(_tier, "census subdivision")
    title = f"{name}, {province} ({year_range})"
    article = "an" if kind_word and kind_word[0].lower() in "aeiou" else "a"
    description_text = (
        f"{name} was {article} {kind_word} in {province}, recorded in "
        f"{len(years_present)} census{'es' if len(years_present) != 1 else ''} "
        f"between {years_present[0]} and {years_present[-1]}."
        if years_present else f"{name} was {article} {kind_word} in {province}."
    )

    wikidata_meta = ""
    wikidata_link = ""
    wikidata_id = (
        "<li><em>External authority links suppressed for Indian Reserve "
        "entries. See methodological note above.</em></li>"
        if is_ir else
        "<li><strong>Wikidata:</strong> <em>not yet grounded.</em></li>"
    )
    if qid and not is_ir:
        wikidata_meta = (
            f'\n&nbsp;|&nbsp; <strong>Wikidata:</strong> '
            f'<a href="https://www.wikidata.org/wiki/{qid}">{qid}</a>'
        )
        wikidata_link = (
            f'<link rel="alternate" type="text/html" '
            f'href="https://www.wikidata.org/wiki/{qid}" title="Wikidata: {qid}">'
        )
        wikidata_id = (
            f'<li><strong>Wikidata:</strong> '
            f'<a href="https://www.wikidata.org/wiki/{qid}">{qid}</a></li>'
        )
        if enwiki_url:
            wikidata_id += (
                f'\n<li><strong>Wikipedia (EN):</strong> '
                f'<a href="{html.escape(enwiki_url)}">{html.escape(enwiki_url)}</a></li>'
            )
        if frwiki_url:
            wikidata_id += (
                f'\n<li><strong>Wikipédia (FR):</strong> '
                f'<a href="{html.escape(frwiki_url)}">{html.escape(frwiki_url)}</a></li>'
            )

    intro_body = description_text
    if qid and not is_ir:
        intro_body += (
            f' This place is grounded to Wikidata '
            f'<a href="https://www.wikidata.org/wiki/{qid}">{qid}</a>, '
            f'so it can be queried as a single entity even when its boundaries '
            f'or census name varied across years.'
        )
    if traj:
        first_pop = traj[0][1]
        last_pop = traj[-1][1]
        if first_pop and last_pop:
            if last_pop > first_pop * 2:
                intro_body += (
                    f" Population grew substantially across the period "
                    f"(from {fmt_pop(first_pop)} in {traj[0][0]} to "
                    f"{fmt_pop(last_pop)} in {traj[-1][0]})."
                )
            elif last_pop < first_pop * 0.7:
                intro_body += (
                    f" Population declined across the period "
                    f"(from {fmt_pop(first_pop)} in {traj[0][0]} to "
                    f"{fmt_pop(last_pop)} in {traj[-1][0]})."
                )
    intro = f"<p>{intro_body}</p>"
    if is_ir:
        intro = IR_NOTE_HTML + "\n" + intro

    # People with DCB entries — full aggregate across all census years.
    persons_aggregate_section = render_persons_aggregate_section(persons)

    # Trajectory rows with link to each year's detail page.
    traj_rows = []
    for tyr, tpop, ttcpuid in traj:
        href = url_for_presence(name, ttcpuid, tyr, base, prov_code)
        traj_rows.append(
            f"<tr><td>{tyr}</td><td>{fmt_pop(tpop)}</td>"
            f'<td><a href="{href}">View {tyr} detail →</a></td></tr>'
        )

    # Historical lineage section: ancestor and descendant chains discovered
    # via SPLIT_FROM / MERGED_INTO relationships from the chain-builder's
    # split-detection rule. Deduplicate (same ancestor can appear multiple
    # times if the source data has multiple split events to the same parent).
    lineage_blocks = []
    if lineage_in:
        seen = set()
        items = []
        for kind, sid, sname, sprov, yr in lineage_in:
            key = (kind, sid, yr)
            if key in seen:
                continue
            seen.add(key)
            href = url_for_place(sname, sid, base, sprov or prov_code)
            yr_text = f" in {yr}" if yr else ""
            verb = "split off from" if kind == "SPLIT_FROM" else "incorporates territory from"
            items.append(
                f'<li>{verb} <a href="{href}">{html.escape(sname)}</a>{yr_text}</li>'
            )
        if items:
            lineage_blocks.append(
                "<h3>Ancestor places</h3>\n<ul>\n" + "\n".join(items) + "\n</ul>"
            )
    if lineage_out:
        seen = set()
        items = []
        for kind, tid, tname, tprov, yr in lineage_out:
            key = (kind, tid, yr)
            if key in seen:
                continue
            seen.add(key)
            href = url_for_place(tname, tid, base, tprov or prov_code)
            yr_text = f" in {yr}" if yr else ""
            verb = "later split into" if kind == "SPLIT_FROM" else "merged into"
            items.append(
                f'<li>{verb} <a href="{href}">{html.escape(tname)}</a>{yr_text}</li>'
            )
        if items:
            lineage_blocks.append(
                "<h3>Descendant places</h3>\n<ul>\n" + "\n".join(items) + "\n</ul>"
            )
    lineage_section = ""
    if lineage_blocks:
        lineage_section = "<h2>Historical lineage</h2>\n" + "\n".join(lineage_blocks)

    # Schema.org JSON-LD
    jsonld_obj = {
        "@context": "https://schema.org",
        "@type": "Place",
        "name": name,
        "description": description_text,
        "address": {
            "@type": "PostalAddress",
            "addressRegion": province,
            "addressCountry": "CA",
        },
    }
    if years_present:
        jsonld_obj["temporalCoverage"] = f"{years_present[0]}/{years_present[-1]}"
    if qid and not is_ir:
        same_as = [f"https://www.wikidata.org/entity/{qid}"]
        if enwiki_url:
            same_as.append(enwiki_url)
        if frwiki_url:
            same_as.append(frwiki_url)
        jsonld_obj["sameAs"] = same_as if len(same_as) > 1 else same_as[0]

    if persons:
        mentions = _persons_jsonld_mentions(persons)
        if mentions:
            jsonld_obj["mentions"] = mentions

    body = PLACE_PAGE_TEMPLATE.format(
        title=html.escape(title),
        description=html.escape(description_text[:200]),
        canonical=canonical,
        wikidata_link=wikidata_link,
        wikidata_meta=wikidata_meta,
        wikidata_id=wikidata_id,
        province=province,
        year_range=year_range,
        heading=html.escape(title),
        intro=intro,
        home_url=home_url,
        prov_index_url=f"{base}/places/{prov_code.lower()}/",
        name_html=html.escape(name),
        trajectory_rows="\n".join(traj_rows) if traj_rows else "<tr><td colspan=3>No data</td></tr>",
        lineage_section=lineage_section,
        persons_aggregate_section=persons_aggregate_section,
        place_id=place_id,
        jsonld=json.dumps(jsonld_obj, indent=2),
    )

    rel_dir = page_path.lstrip("/").rstrip("/")
    if base and rel_dir.startswith(base.lstrip("/")):
        rel_dir = rel_dir[len(base.lstrip("/")):].lstrip("/")
    return rel_dir, body, canonical


CD_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">

<meta property="og:type" content="article">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{canonical}">
{wikidata_link}

<style>
  body {{ font-family: -apple-system, "Segoe UI", sans-serif; max-width: 820px;
         margin: 2em auto; padding: 0 1em; line-height: 1.55; color: #222; }}
  h1 {{ border-bottom: 1px solid #ddd; padding-bottom: 0.3em; margin-bottom: 0.5em; }}
  h2 {{ margin-top: 1.6em; }}
  h3 {{ margin-top: 1.4em; background: #f5f7fa; padding: 0.3em 0.6em;
       border-left: 4px solid #0066cc; }}
  table {{ border-collapse: collapse; margin: 0.5em 0; }}
  th, td {{ border: 1px solid #ddd; padding: 4px 10px; }}
  th {{ background: #f5f5f5; }}
  td:nth-child(2), td:nth-child(3) {{ text-align: right; }}
  .crumbs {{ font-size: 0.9em; color: #666; margin-bottom: 0.5em; }}
  .crumbs a {{ color: #0055aa; }}
  .meta {{ background: #f8f9fa; padding: 0.7em 1em; border-left: 3px solid #0066cc;
         margin: 1em 0; font-size: 0.9em; }}
  ul.csds {{ columns: 2; column-gap: 2em; padding-left: 1.4em; }}
  ul.csds li {{ break-inside: avoid; }}
  a {{ color: #0055aa; }}
  footer {{ margin-top: 3em; font-size: 0.8em; color: #666;
           border-top: 1px solid #ddd; padding-top: 1em; }}
</style>
</head>
<body>
<article>
<div class="crumbs"><a href="{home_url}">HGIS Canada</a> › <a href="{prov_index_url}">{province}</a> › Census Divisions › {cd_name}</div>
<div class="meta">
<strong>Census Division:</strong> {cd_name}
&nbsp;|&nbsp; <strong>Province:</strong> {province}
&nbsp;|&nbsp; <strong>Years active:</strong> {years_active}
{wikidata_meta}
</div>

<h1>{cd_name}, {province}</h1>

<p>{intro}</p>

<h2>Population trajectory across census years</h2>
<p>Aggregate population summed from constituent Census Subdivisions in this Census Division each year.
Where the published 1851–1921 census volumes report a CD-level total, the figures should match within
rounding; for cities split into wards, the per-CSD sum may diverge from the published CD aggregate.</p>
<table>
<tr><th>Year</th><th>Population</th><th>CSDs</th></tr>
{traj_rows}
</table>

<h2>Constituent Census Subdivisions by year</h2>
{years_html}

{lineage_section}

<h2>Identifiers</h2>
<ul>
<li><strong>HGIS Canada CD ID:</strong> <code>{cd_id}</code></li>
{wikidata_id}
</ul>

<h2>Sources</h2>
<p>Census Division boundaries derived from the
<a href="https://borealisdata.ca/dataverse/canadiansubdivisions">Canadian Peoples / TCP</a>
1851–1921 Census Subdivision boundary files (<code>NAME_CD_&lt;year&gt;</code> attributes,
hosted at the <a href="https://hgiscanada.usask.ca/">HGIS Lab, University of Saskatchewan</a>).
Constituent-CSD memberships use the <code>P10_falls_within</code> CIDOC-CRM relationships
emitted by the spatial CIDOC builder. Wikidata grounding for Census Divisions performed via the
<a href="https://github.com/jburnford/Canada-History-Knowledge-Graph">HGIS Canada Knowledge Graph</a>
project's MCP-assisted disambiguation pipeline. See the <a href="{about_url}">About / Methodology</a>
page for the full data pipeline.</p>

<script type="application/ld+json">
{jsonld}
</script>

<footer>
<a href="{prov_index_url}">← {province}</a> &nbsp;·&nbsp;
<a href="{home_url}">All provinces</a> &nbsp;·&nbsp;
<a href="{about_url}">About / Methodology</a>
</footer>
</article>
</body>
</html>
"""


def prefetch_cd_data(presence_data):
    """Read CDs + their constituent CSDs per year directly from CIDOC-CRM
    CSV files. Independent of Kuzu since the CSV layer is the post-Phase-2/3
    source of truth for CD chains, URIs, and lineage.

    Returns:
      cds: list of (chain_id, canonical_name, province, uri, qid, status, mint_reason, years_active)
      cd_to_csds_by_year: dict[chain_id] -> dict[year] -> list[(csd_name, csd_place_id, csd_qid, csd_pop)]
      cd_chain_url: dict[chain_id] -> URL path (from e53_place_uri.csv) — single source for CD URLs
      raw_cd_to_chain: dict[(raw_cd_id, year)] -> chain_id — for CSD presence pages to resolve cd_name → chain URL
      cd_canonical_by_chain: dict[chain_id] -> canonical_name (used for nice link text + lineage section)
      cd_lineage_by_chain: dict[chain_id] -> list of (lineage_type, other_chain_id, change_year)
    """
    import csv as _csv
    cidoc = REPO / "neo4j_cidoc_crm_v2"
    chains_dir = REPO / "persistent_cds_output"

    # 1. e53_place_uri.csv keyed on place_id for QID + URI lookup.
    uri_by_id = {}
    with (cidoc / "e53_place_uri.csv").open() as f:
        for r in _csv.DictReader(f):
            uri_by_id[r["place_id:ID"]] = r

    # 1b. Load Wikipedia sitelinks (QID -> en/fr URL). Same source the
    # CSD pages use via Ladybug Place.enwiki_url / frwiki_url; here we
    # join in directly since CD prefetch reads CSVs not Ladybug.
    wiki_by_qid = {}
    sitelinks_path = REPO / "wikidata_grounding" / "wikipedia_sitelinks.csv"
    if sitelinks_path.exists():
        with sitelinks_path.open() as f:
            for r in _csv.DictReader(f):
                wiki_by_qid[r["qid"]] = (
                    r.get("enwiki_url", "") or "",
                    r.get("frwiki_url", "") or "",
                )

    # 2. e53_place_cd.csv master list (one row per CD chain post-Phase-3).
    cds = []
    cd_canonical_by_chain = {}
    with (cidoc / "e53_place_cd.csv").open() as f:
        for r in _csv.DictReader(f):
            chain_id = r["place_id:ID"]
            canonical = r["name"]
            cd_canonical_by_chain[chain_id] = canonical
            u = uri_by_id.get(chain_id, {})
            qid = u.get("wikidata_qid", "")
            enwiki, frwiki = wiki_by_qid.get(qid, ("", ""))
            cds.append((
                chain_id, canonical, r["province"],
                u.get("uri", ""), qid,
                u.get("grounding_status", ""), u.get("mint_reason", ""),
                r.get("years_active", ""),
                enwiki, frwiki,
            ))
    print(f"[prefetch-cds] {len(cds)} CD chains "
          f"({sum(1 for c in cds if c[8])} with EN Wikipedia, "
          f"{sum(1 for c in cds if c[9])} with FR Wikipedia)", flush=True)

    # 3. Build chain URL lookup from URI sidecar. For wikidata-grounded chains,
    # synthesize the page URL from chain_id (we still want users to click into
    # the local CD index page even when the canonical URI is Wikidata).
    #
    # Slugify is lossy (folds diacritics, treats hyphen/space identically), so
    # two chains with distinct canonical names ("Jacques-Cartier" vs "Jacques
    # Cartier") can produce the same bare slug. We pass once to mint, then
    # detect bare-slug collisions and re-mint the loser with an anchor-year
    # disambiguator. Earliest-anchor wins the bare URL (most stable for inbound
    # links since the multi-year main chain has the earlier anchor).
    cd_chain_url = {}
    cd_slug_anchor = {}  # chain_id -> (province, slug, anchor_year)
    for chain_id, canonical, province, uri, qid, status, mr, ya, _en, _fr in cds:
        expected_prefix = f"CD_{province}_{canonical.replace(' ', '_')}"
        url_slug = slugify(canonical)
        if chain_id.startswith(expected_prefix + "_"):
            tail = chain_id[len(expected_prefix) + 1:]
            if tail:
                url_slug = f"{url_slug}-{slugify(tail)}"
        cd_chain_url[chain_id] = f"/hgiscanada/cds/{province.lower()}/{url_slug}/"
        years = [int(y) for y in (ya or "").split(";") if y]
        anchor = min(years) if years else 9999
        cd_slug_anchor[chain_id] = (province, url_slug, anchor, chain_id)

    # Detect bare-slug collisions and demote later-anchor chains to a slugged
    # disambiguator. Don't touch chain_ids — only URLs.
    by_url = defaultdict(list)
    for chain_id, url in cd_chain_url.items():
        by_url[url].append(chain_id)
    for url, chain_ids in by_url.items():
        if len(chain_ids) <= 1:
            continue
        # Sort: earliest anchor first; chain_id alpha breaks ties.
        ranked = sorted(chain_ids, key=lambda cid: (cd_slug_anchor[cid][2],
                                                     cd_slug_anchor[cid][3]))
        for cid in ranked[1:]:
            province, base_slug, anchor, _ = cd_slug_anchor[cid]
            new_slug = f"{base_slug}-{anchor}"
            new_url = f"/hgiscanada/cds/{province.lower()}/{new_slug}/"
            # If this fallback also collides, append chain_id-derived suffix.
            if new_url in cd_chain_url.values() and new_url != url:
                tail = slugify(cid)
                new_url = f"/hgiscanada/cds/{province.lower()}/{base_slug}-{tail}/"
            cd_chain_url[cid] = new_url
            print(f"[prefetch-cds] URL collision on {url}: "
                  f"demoted {cid} to {new_url}", flush=True)

    # Hard guard: any remaining duplicates indicate a deeper bug (e.g., two
    # chains share the exact same chain_id, or three-way collision wasn't
    # resolved by the first pass). Fail loudly so we never silently overwrite.
    final_url_counts = Counter(cd_chain_url.values())
    final_collisions = [u for u, c in final_url_counts.items() if c > 1]
    if final_collisions:
        msg = ["URL collisions remain after disambiguation pass:"]
        for url in sorted(final_collisions):
            msg.append(f"  {url}")
            for cid, u in cd_chain_url.items():
                if u == url:
                    msg.append(f"    {cid}")
        raise RuntimeError("\n".join(msg))

    # 4. Load (raw_cd_id, year) -> chain_id mapping.
    raw_cd_to_chain = {}
    chain_map_path = chains_dir / "cd_id_year_to_chain.csv"
    if chain_map_path.exists():
        with chain_map_path.open() as f:
            for r in _csv.DictReader(f):
                raw_cd_to_chain[(r["raw_cd_id"], int(r["year"]))] = r["chain_place_id"]
        print(f"[prefetch-cds] {len(raw_cd_to_chain)} raw_cd → chain mappings",
              flush=True)
    else:
        print(f"[prefetch-cds] WARNING: {chain_map_path} not found - "
              f"CSD pages will link by raw cd_name (may 404)", flush=True)

    # 5. Walk CD-CSD relationships year by year. CD presence id IS chain-based
    # post-Phase-3 (e.g., CD_ON_Renfrew_North_1881), and the cd_id column on
    # the CD presence row IS the chain place_id, so this aggregates CSDs under
    # their chain naturally.
    cd_to_csds_by_year = defaultdict(lambda: defaultdict(list))
    years_present = set()
    for year in (1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921):
        cd_pres_path = cidoc / f"e93_presence_cd_{year}.csv"
        rel_path = cidoc / f"p10_csd_within_cd_presence_{year}.csv"
        if not cd_pres_path.exists() or not rel_path.exists():
            continue
        years_present.add(year)
        cd_pres_to_chain = {}
        with cd_pres_path.open() as f:
            for r in _csv.DictReader(f):
                cd_pres_to_chain[r["presence_id:ID"]] = r["cd_id"]
        with rel_path.open() as f:
            for r in _csv.DictReader(f):
                csd_pres_id = r[":START_ID"]
                cd_pres_id = r[":END_ID"]
                chain_id = cd_pres_to_chain.get(cd_pres_id)
                if not chain_id:
                    continue
                csd_info = presence_data.get(csd_pres_id)
                if not csd_info:
                    continue
                csd_place_id = csd_info[0]
                csd_name = csd_info[1]
                csd_qid = csd_info[2]
                csd_pop = csd_info[10]
                cd_to_csds_by_year[chain_id][year].append(
                    (csd_name, csd_place_id, csd_qid, csd_pop)
                )
    print(f"[prefetch-cds] CD-CSD memberships across {len(years_present)} years",
          flush=True)

    # 6. Load CD lineage edges (Phase 1 output, copied to neo4j_cidoc_crm_v2 in Phase 3).
    cd_lineage_by_chain = defaultdict(list)
    cd_lineage_path = cidoc / "cd_lineage.csv"
    if cd_lineage_path.exists():
        with cd_lineage_path.open() as f:
            for r in _csv.DictReader(f):
                ltype = r["lineage_type"]
                start = r[":START_ID"]
                end = r[":END_ID"]
                yr_raw = r.get("change_year:int", "") or r.get("change_year", "")
                try:
                    change_year = int(yr_raw) if yr_raw else None
                except ValueError:
                    change_year = None
                # Index from BOTH endpoints so the page can render both
                # "split into" (parent's view) and "split from" (child's view).
                cd_lineage_by_chain[start].append(("out", ltype, end, change_year))
                cd_lineage_by_chain[end].append(("in", ltype, start, change_year))
        n_edges = sum(len(v) for v in cd_lineage_by_chain.values()) // 2
        print(f"[prefetch-cds] {n_edges} CD lineage edges", flush=True)

    # 7. Build the display-label dict. When a (province, canonical_name) pair
    # has more than one chain — Toronto East 1871 vs 1911, Jacques-Cartier
    # 1891 vs the 1861-1911 main chain, etc. — append a year qualifier so
    # readers and crawlers can tell the chains apart in the index, page
    # chrome, JSON-LD, and lineage links. Single chain stays bare.
    chains_by_prov_name = defaultdict(list)
    for chain_id, canonical, province, _u, _q, _s, _mr, ya, _en, _fr in cds:
        chains_by_prov_name[(province, canonical)].append((chain_id, ya))
    cd_display_label = {}
    for (_prov, name), chains in chains_by_prov_name.items():
        if len(chains) == 1:
            cd_display_label[chains[0][0]] = name
            continue
        proposed = {}
        for chain_id, years_active in chains:
            years = [y for y in (years_active or "").split(";") if y]
            if not years:
                qual = ""
            elif len(years) == 1:
                qual = years[0]
            else:
                qual = f"{years[0]}–{years[-1]}"
            proposed[chain_id] = f"{name} ({qual})" if qual else name
        # Tiebreaker: when two chains share name AND year range (e.g. ON has
        # two distinct CDs both named "Brant" both spanning only 1861, with
        # different geometries from raw cd_ids `CD_ON_Brant` vs `CD_ON_Brant_`),
        # the year qualifier alone collides. Append "(var. N)" to ties past
        # the first, ordered by chain_id for determinism.
        by_label = defaultdict(list)
        for chain_id, lbl in proposed.items():
            by_label[lbl].append(chain_id)
        for lbl, tied in by_label.items():
            if len(tied) == 1:
                cd_display_label[tied[0]] = lbl
                continue
            for i, chain_id in enumerate(sorted(tied), start=1):
                cd_display_label[chain_id] = lbl if i == 1 else f"{lbl} (var. {i})"
    n_disambig = sum(1 for v in cd_display_label.values() if "(" in v)
    print(f"[prefetch-cds] {n_disambig} CD chains given disambiguated display labels",
          flush=True)

    return (cds, cd_to_csds_by_year, cd_chain_url, raw_cd_to_chain,
            cd_canonical_by_chain, cd_lineage_by_chain, cd_display_label)


def render_cd_page(cd_row, csds_by_year, lineage_edges, *,
                   site_url: str, base: str) -> tuple[str, str, str]:
    """Return (rel_dir, body, canonical) for a CD index page.

    cd_row tuple: (chain_id, canonical_name, province, uri, qid, status,
                   mint_reason, years_active_string, enwiki_url, frwiki_url).
    lineage_edges: list of (direction, lineage_type, other_chain_id, change_year)
                   from the Phase-1 cd_lineage.csv. Empty list if none.
    """
    (cd_id, cd_name, prov_code, uri, qid, status, mint_reason,
     years_active_str, enwiki_url, frwiki_url) = cd_row
    province = PROVINCE_NAMES.get(prov_code, prov_code)
    # Display label adds a year qualifier when this chain shares its
    # canonical_name with another chain in the same province (e.g.
    # "Toronto East (1871)" vs "Toronto East (1911)"). Falls back to bare
    # cd_name when this chain is the only one with that name.
    display_name = _CD_DISPLAY_LABEL.get(cd_id, cd_name)
    page_path = url_for_cd(cd_name, prov_code, base, chain_place_id=cd_id)
    canonical = f"{site_url}{page_path}"
    home_url = f"{base}/"
    prov_index_url = f"{base}/places/{prov_code.lower()}/"
    about_url = f"{base}/about/"

    years = sorted(csds_by_year.keys())
    # Prefer years_active from registry (covers gap-spanning chains via Rule 4
    # where csds_by_year skips middle years that belonged to split children).
    if years_active_str:
        try:
            years = sorted(int(y) for y in years_active_str.split(";") if y)
        except ValueError:
            pass
    years_active = (
        f"{years[0]}–{years[-1]}" if len(years) > 1
        else (str(years[0]) if years else "—")
    )

    # Per-year sections.
    year_sections = []
    traj_rows = []
    for year in years:
        csds = sorted(csds_by_year[year], key=lambda c: (c[0] or "").lower())
        items = []
        total_pop = 0
        pop_count = 0
        for csd_name, csd_place_id, csd_qid, csd_pop in csds:
            href = url_for_place(csd_name, csd_place_id, base, prov_code)
            wd = ""
            if csd_qid:
                wd = (' <a style="color:#888;font-size:0.85em" '
                      f'href="https://www.wikidata.org/wiki/{csd_qid}" '
                      f'title="Wikidata: {csd_qid}">wd</a>')
            pop_str = ""
            if csd_pop:
                pop_str = (f' <span style="color:#888;font-size:0.9em">'
                           f'(pop {fmt_pop(csd_pop)})</span>')
                total_pop += csd_pop
                pop_count += 1
            items.append(
                f'<li><a href="{href}">{html.escape(csd_name)}</a>{wd}{pop_str}</li>'
            )
        traj_pop_cell = fmt_pop(total_pop) if pop_count else "—"
        traj_rows.append(
            f"<tr><td>{year}</td><td>{traj_pop_cell}</td><td>{len(csds)}</td></tr>"
        )
        year_sections.append(
            f'<h3 id="y{year}">{year} census</h3>\n'
            f'<ul class="csds">\n' + "\n".join(items) + "\n</ul>"
        )

    # Intro paragraph.
    article = "an" if display_name and display_name[0].lower() in "aeiou" else "a"
    intro = (
        f"<strong>{html.escape(display_name)}</strong> was {article} Census Division "
        f"in {province} as recorded in the {years_active} Canadian census series. "
        f"It comprised the constituent Census Subdivisions listed below for each "
        f"year it appears in the published volumes."
    )
    if status == "matched" and qid:
        intro += (f' This CD is grounded to Wikidata '
                  f'<a href="https://www.wikidata.org/wiki/{qid}">{qid}</a>.')
    elif status == "mint_uri" and mint_reason:
        intro += f" {html.escape(mint_reason)}"

    # Wikidata meta line + <link>.
    wikidata_meta = ""
    wikidata_link = ""
    wikidata_id = ""
    if qid:
        wikidata_meta = (f"\n&nbsp;|&nbsp; <strong>Wikidata:</strong> "
                         f'<a href="https://www.wikidata.org/wiki/{qid}">{qid}</a>')
        wikidata_link = (f'<link rel="alternate" type="text/html" '
                         f'href="https://www.wikidata.org/wiki/{qid}" '
                         f'title="Wikidata: {qid}">')
        wikidata_id = (f'<li><strong>Wikidata:</strong> '
                       f'<a href="https://www.wikidata.org/wiki/{qid}">{qid}</a></li>')
        if enwiki_url:
            wikidata_id += (
                f'\n<li><strong>Wikipedia (EN):</strong> '
                f'<a href="{html.escape(enwiki_url)}">{html.escape(enwiki_url)}</a></li>'
            )
        if frwiki_url:
            wikidata_id += (
                f'\n<li><strong>Wikipédia (FR):</strong> '
                f'<a href="{html.escape(frwiki_url)}">{html.escape(frwiki_url)}</a></li>'
            )

    description = (
        f"{display_name} Census Division in {province}, {years_active}. "
        f"Constituent Census Subdivisions listed for each census year."
    )

    # Lineage section: split-from / merged-into / split-into edges.
    # Group by (direction, lineage_type, change_year) for prose rendering.
    lineage_section = ""
    if lineage_edges:
        from collections import defaultdict as _dd
        groups = _dd(list)  # (direction, ltype, year) -> list of other_chain_id
        for direction, ltype, other_id, change_year in lineage_edges:
            groups[(direction, ltype, change_year)].append(other_id)
        # Render each group as a sentence.
        sentences = []
        for (direction, ltype, change_year), others in sorted(
            groups.items(), key=lambda kv: (kv[0][2] or 0, kv[0][0], kv[0][1])
        ):
            other_links = []
            for other_id in sorted(set(others)):
                other_canonical = _CD_CANONICAL_BY_CHAIN.get(other_id, other_id)
                # Use display label (with year qualifier when ambiguous), not
                # bare canonical_name. Otherwise "Split into Toronto East" can
                # mean either the 1871 or the 1911 chain.
                other_label = _CD_DISPLAY_LABEL.get(other_id, other_canonical)
                # Derive prov from chain id (CD_<PROV>_...).
                other_parts = other_id.split("_", 2)
                other_prov = other_parts[1] if len(other_parts) >= 2 else prov_code
                other_url = (f"{base}/cds/{other_prov.lower()}/"
                             f"{_CD_CHAIN_URL_SLUG.get(other_id, slugify(other_canonical))}/")
                other_links.append(
                    f'<a href="{other_url}">{html.escape(other_label)}</a>'
                )
            joined = ", ".join(other_links)
            yr_str = f" in {change_year}" if change_year else ""
            if direction == "out" and ltype == "SPLIT_FROM":
                sentences.append(f"<li>Split into {joined}{yr_str}.</li>")
            elif direction == "in" and ltype == "SPLIT_FROM":
                sentences.append(f"<li>Split off from {joined}{yr_str}.</li>")
            elif direction == "out" and ltype == "MERGED_INTO":
                sentences.append(f"<li>Merged into {joined}{yr_str}.</li>")
            elif direction == "in" and ltype == "MERGED_INTO":
                sentences.append(f"<li>Re-formed from {joined}{yr_str}.</li>")
        if sentences:
            lineage_section = (
                "<h2>Lineage</h2>\n"
                "<p>Boundary changes connecting this Census Division to others "
                "in the 1851–1921 series, derived from spatial polygon overlap "
                "across census-year boundary files.</p>\n"
                "<ul>\n" + "\n".join(sentences) + "\n</ul>"
            )

    jsonld_obj = {
        "@context": "https://schema.org",
        "@type": "AdministrativeArea",
        "name": f"{display_name}, {province}",
        "description": description,
        "containedInPlace": {
            "@type": "AdministrativeArea",
            "name": province,
        },
        "url": canonical,
    }
    if qid:
        same_as = [f"http://www.wikidata.org/entity/{qid}"]
        if enwiki_url:
            same_as.append(enwiki_url)
        if frwiki_url:
            same_as.append(frwiki_url)
        jsonld_obj["sameAs"] = same_as if len(same_as) > 1 else same_as[0]

    body = CD_PAGE_TEMPLATE.format(
        title=f"{display_name}, {province} — Census Division",
        description=description,
        canonical=canonical,
        home_url=home_url,
        prov_index_url=prov_index_url,
        province=province,
        cd_name=html.escape(display_name),
        years_active=years_active,
        wikidata_meta=wikidata_meta,
        wikidata_link=wikidata_link,
        wikidata_id=wikidata_id,
        intro=intro,
        traj_rows="\n".join(traj_rows),
        years_html="\n".join(year_sections),
        lineage_section=lineage_section,
        about_url=about_url,
        cd_id=cd_id,
        jsonld=json.dumps(jsonld_obj, indent=2),
    )
    rel_dir = page_path.lstrip("/").rstrip("/")
    if base and rel_dir.startswith(base.lstrip("/")):
        rel_dir = rel_dir[len(base.lstrip("/")):].lstrip("/")
    return rel_dir, body, canonical


def fetch_place_pages(conn, place_to_presences, persons_by_place, *,
                      site_url: str, base: str):
    """Iterate Places and yield (rel_dir, html, canonical) for each.
    Uses pre-fetched trajectories + batched lineage queries to avoid
    per-place Cypher round-trips."""
    print("[prefetch-places] place rows...", flush=True)
    res = conn.execute(
        "MATCH (pl:Place {place_type: 'CSD'}) "
        "RETURN pl.place_id, pl.name, pl.wikidata_qid, pl.place_type, pl.province, "
        "pl.enwiki_url, pl.frwiki_url "
        "ORDER BY pl.province, pl.name;"
    )
    place_rows = []
    while res.has_next():
        place_rows.append(res.get_next())
    print(f"[prefetch-places]   {len(place_rows)} places", flush=True)

    # Lineage prefetch.
    lineage_in_by_place = defaultdict(list)
    lineage_out_by_place = defaultdict(list)

    print("[prefetch-places] SPLIT_FROM edges...", flush=True)
    res = conn.execute(
        "MATCH (a:Place)-[s:SPLIT_FROM]->(b:Place) "
        "RETURN a.place_id, a.name, a.province, b.place_id, b.name, b.province, s.change_year;"
    )
    # build_lineage stores SPLIT_FROM with start=parent (older), end=child
    # (newer, split-off). On the parent's page, B is a descendant; on the
    # child's page, A is an ancestor.
    while res.has_next():
        a_id, a_name, a_prov, b_id, b_name, b_prov, yr = res.get_next()
        lineage_out_by_place[a_id].append(("SPLIT_FROM", b_id, b_name, b_prov, yr))
        lineage_in_by_place[b_id].append(("SPLIT_FROM", a_id, a_name, a_prov, yr))

    print("[prefetch-places] MERGED_INTO edges...", flush=True)
    res = conn.execute(
        "MATCH (a:Place)-[m:MERGED_INTO]->(b:Place) "
        "RETURN a.place_id, a.name, a.province, b.place_id, b.name, b.province, m.change_year;"
    )
    while res.has_next():
        a_id, a_name, a_prov, b_id, b_name, b_prov, yr = res.get_next()
        # On A's page: A merged into B → record under lineage_out for A.
        lineage_out_by_place[a_id].append(("MERGED_INTO", b_id, b_name, b_prov, yr))
        # On B's page: A merged into B → record under lineage_in for B.
        lineage_in_by_place[b_id].append(("MERGED_INTO", a_id, a_name, a_prov, yr))

    print("[prefetch-places] rendering...", flush=True)
    for place_row in place_rows:
        place_id = place_row[0]
        traj = place_to_presences.get(place_id, [])
        lineage_in = lineage_in_by_place.get(place_id, [])
        lineage_out = lineage_out_by_place.get(place_id, [])
        persons = persons_by_place.get(place_id, [])
        rel_dir, body, canonical = render_place_page(
            place_row, traj, lineage_in, lineage_out, persons,
            site_url=site_url, base=base,
        )
        yield rel_dir, body, canonical


def render_index(year_counts: dict, samples: list, province_counts: dict,
                 total_places: int, site_url: str, base: str) -> str:
    coverage_rows = "\n".join(
        f"<tr><td>{yr}</td><td>{fmt_thousand(year_counts[yr])}</td></tr>"
        for yr in sorted(year_counts)
    )
    sample_html = "\n".join(
        f'<li><a href="{href}">{html.escape(label)}</a> — {note}</li>'
        for label, href, note in samples
    )
    province_links_html = "\n".join(
        f'<a href="{base}/places/{prov.lower()}/">'
        f'{html.escape(PROVINCE_NAMES.get(prov, prov))} '
        f'<span class="count">({fmt_thousand(province_counts[prov])})</span></a>'
        for prov in sorted(province_counts, key=lambda p: PROVINCE_NAMES.get(p, p))
    )
    return INDEX_TEMPLATE.format(
        site_url=site_url,
        base=base,
        about_url=f"{base}/about/",
        coverage_rows=coverage_rows,
        total_pages=fmt_thousand(sum(year_counts.values())),
        total_places=fmt_thousand(total_places),
        province_links=province_links_html,
        sample_links=sample_html,
    )


def render_province_index_page(prov_code: str, places_in_prov: list,
                               *, site_url: str, base: str,
                               cds_in_prov: list | None = None
                               ) -> tuple[str, str]:
    """places_in_prov: list of (place_id, name, wikidata_qid, years_string)
    where years_string is something like '1851-1921' or '1871, 1881, 1891'.

    cds_in_prov: list of (cd_id, cd_name, qid, num_csds_max), one row per CD
    in this province. Renders into a "Census Divisions" section above the
    alphabetical CSD listing. None / [] omits the section.

    Returns (rel_dir, html, canonical).
    """
    province_name = PROVINCE_NAMES.get(prov_code, prov_code)
    page_path = f"{base}/places/{prov_code.lower()}/"
    canonical = f"{site_url}{page_path}"
    home_url = f"{base}/"
    about_url = f"{base}/about/"

    # Group by first letter of name.
    by_letter = defaultdict(list)
    presence_count = 0
    for place_id, name, qid, year_count, year_first, year_last in places_in_prov:
        first = (name[:1].upper() if name else "?")
        if not first.isalpha():
            first = "#"
        by_letter[first].append((place_id, name, qid, year_count, year_first, year_last))
        presence_count += year_count

    letters = sorted(by_letter.keys())
    # Place "#" (non-alphabetic) at the end.
    if "#" in letters:
        letters.remove("#")
        letters.append("#")

    alphabet_nav = " ".join(
        f'<a href="#L-{letter}">{letter}</a>' for letter in letters
    )

    sections = []
    for letter in letters:
        # Group by (normalised_base, tier). Same base + same tier merges
        # ("Magog, T-V" 1911 + "Magog, Town—Ville" 1891 → one urban Magog).
        # Different tier stays separate (rural Magog ≠ urban Magog), and
        # parenthetical disambiguators ("Mont Carmel (Notre Dame du)") stay
        # separate because they're part of the base, not a recognised qualifier.
        rows = sorted(by_letter[letter], key=lambda r: (r[1] or "").lower())
        by_group = defaultdict(list)
        for row in rows:
            by_group[grouping_key(row[1])].append(row)

        items = []
        # Sort groups by display name for stable order within a letter.
        def _sort_key(group_key):
            base_norm, tier = group_key
            return (base_norm, tier or "")

        for norm_key in sorted(by_group, key=_sort_key):
            tier = norm_key[1]
            variants = sorted(by_group[norm_key], key=lambda r: r[4] or 0)  # by year_first
            if len(variants) == 1:
                place_id, name, qid, year_count, year_first, year_last = variants[0]
                href = url_for_place(name, place_id, base, prov_code)
                year_span = (
                    f"{year_first}–{year_last}" if year_first != year_last else f"{year_first}"
                )
                wd_marker = (
                    " <span style='color:#888'>·</span> "
                    f'<a href="https://www.wikidata.org/wiki/{qid}" '
                    f'style="color:#888;font-size:0.85em" title="Wikidata: {qid}">wd</a>'
                ) if qid else ""
                items.append(
                    f'<li><a class="place-name" href="{href}">{html.escape(name)}</a> '
                    f'<span class="years-active">({year_span})</span>{wd_marker}</li>'
                )
            else:
                combined_first = min(v[4] or 0 for v in variants)
                combined_last = max(v[5] or 0 for v in variants)
                combined_span = (
                    f"{combined_first}–{combined_last}"
                    if combined_first != combined_last else f"{combined_first}"
                )
                display_name = display_name_for_group(variants, tier)
                sub_items = []
                for place_id, name, qid, year_count, year_first, year_last in variants:
                    href = url_for_place(name, place_id, base, prov_code)
                    year_span = (
                        f"{year_first}–{year_last}" if year_first != year_last else f"{year_first}"
                    )
                    wd_marker = (
                        " <a href=\"https://www.wikidata.org/wiki/" + qid + "\" "
                        "style=\"color:#888;font-size:0.85em\" title=\"Wikidata: " + qid + "\">wd</a>"
                    ) if qid else ""
                    # Show original full name on each sub-bullet so qualifier
                    # variation (T-V vs Town—Ville) is visible.
                    sub_items.append(
                        f'<li><a href="{href}">{year_span}</a> '
                        f'<span style="color:#888">{html.escape(name)}</span>{wd_marker}</li>'
                    )
                items.append(
                    f'<li><strong>{html.escape(display_name)}</strong> '
                    f'<span class="years-active">({combined_span}, '
                    f'{len(variants)} variants)</span>'
                    f'<ul style="columns:1;margin-top:0.2em">\n'
                    + "\n".join(sub_items)
                    + "\n</ul></li>"
                )

        sections.append(
            f'<h3 class="letter" id="L-{letter}">{letter}</h3>\n'
            f'<ul class="places">\n' + "\n".join(items) + "\n</ul>"
        )

    jsonld_obj = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": f"{province_name} — Census Subdivisions, 1851–1921",
        "description": (f"All Census Subdivisions in {province_name} across the 1851–1921 "
                        f"Census of Canada series."),
        "isPartOf": {
            "@type": "WebSite",
            "name": "HGIS Canada Knowledge Graph",
            "url": f"{site_url}{base}/",
        },
        "breadcrumb": {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "HGIS Canada", "item": f"{site_url}{home_url}"},
                {"@type": "ListItem", "position": 2, "name": province_name, "item": canonical},
            ],
        },
    }

    cds_section = ""
    if cds_in_prov:
        cd_items = []
        # Sort by display label so "(1871)" / "(1911)" qualifiers line up
        # adjacent to the bare-name siblings they disambiguate.
        for cd_id, cd_name, cd_qid, num_csds_max in sorted(
            cds_in_prov,
            key=lambda r: (_CD_DISPLAY_LABEL.get(r[0], r[1]) or "").lower()
        ):
            display_name = _CD_DISPLAY_LABEL.get(cd_id, cd_name)
            cd_href = url_for_cd(cd_name, prov_code, base, chain_place_id=cd_id)
            wd_marker = ""
            if cd_qid:
                wd_marker = (
                    " <span style='color:#888'>·</span> "
                    f'<a href="https://www.wikidata.org/wiki/{cd_qid}" '
                    f'style="color:#888;font-size:0.85em" '
                    f'title="Wikidata: {cd_qid}">wd</a>'
                )
            count_marker = ""
            if num_csds_max:
                count_marker = (f' <span style="color:#888;font-size:0.85em">'
                                f'({num_csds_max} CSDs)</span>')
            cd_items.append(
                f'<li><a href="{cd_href}">{html.escape(display_name)}</a>'
                f'{count_marker}{wd_marker}</li>'
            )
        cds_section = (
            f'<h2>Census Divisions ({len(cds_in_prov)})</h2>\n'
            f'<p>Counties, districts, and regional municipalities that group the '
            f'Census Subdivisions below. Each CD page lists its constituent CSDs '
            f'by year.</p>\n'
            f'<ul class="places">\n' + "\n".join(cd_items) + "\n</ul>"
        )

    body = PROVINCE_INDEX_TEMPLATE.format(
        province_name=html.escape(province_name),
        place_count=fmt_thousand(len(places_in_prov)),
        presence_count=fmt_thousand(presence_count),
        canonical=canonical,
        home_url=home_url,
        about_url=about_url,
        alphabet_nav=alphabet_nav,
        cds_section=cds_section,
        letter_sections="\n".join(sections),
        jsonld=json.dumps(jsonld_obj, indent=2),
    )
    rel_dir = page_path.lstrip("/").rstrip("/")
    if base and rel_dir.startswith(base.lstrip("/")):
        rel_dir = rel_dir[len(base.lstrip("/")):].lstrip("/")
    return rel_dir, body, canonical


def render_about_page(*, site_url: str, base: str) -> tuple[str, str]:
    page_path = f"{base}/about/"
    canonical = f"{site_url}{page_path}"
    home_url = f"{base}/"
    body = ABOUT_TEMPLATE.format(
        canonical=canonical, home_url=home_url, site_url=site_url, base=base,
    )
    rel_dir = page_path.lstrip("/").rstrip("/")
    if base and rel_dir.startswith(base.lstrip("/")):
        rel_dir = rel_dir[len(base.lstrip("/")):].lstrip("/")
    return rel_dir, body, canonical


def render_sitemap(urls: list, base_lastmod: str) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        lines.append(
            f"  <url><loc>{u}</loc><lastmod>{base_lastmod}</lastmod>"
            f"<changefreq>yearly</changefreq></url>"
        )
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--samples", action="store_true")
    g.add_argument("--presence", help="Generate one page for a specific presence_id")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--site-url", default=DEFAULT_SITE_URL,
                    help=f"Site URL origin, default {DEFAULT_SITE_URL}")
    ap.add_argument("--base-path", default=DEFAULT_BASE_PATH,
                    help=f"Path prefix on the site, default {DEFAULT_BASE_PATH}")
    ap.add_argument("--out", default=str(OUT_DIR), help="Output directory")
    args = ap.parse_args()

    out_dir = Path(args.out)
    site_url = args.site_url.rstrip("/")
    base = args.base_path.rstrip("/")

    import ladybug as kuzu  # Ladybug is the maintained Kuzu fork (post-Apple-acquisition)
    db = kuzu.Database(str(DB_PATH))
    conn = kuzu.Connection(db)

    out_dir.mkdir(parents=True, exist_ok=True)

    if args.samples:
        targets = SAMPLES
    elif args.presence:
        targets = [args.presence]
    else:
        # All Presences with population data, across all provinces. Province
        # is encoded as the first 2 chars of presence_id.
        res = conn.execute(
            "MATCH (pr:Presence) WHERE pr.pop_total IS NOT NULL "
            "RETURN pr.presence_id ORDER BY pr.year, pr.presence_id;"
        )
        targets = []
        while res.has_next():
            targets.append(res.get_next()[0])

    # Pre-fetch everything we need in a few big queries, then iterate in Python.
    # This avoids ~100K small Cypher round-trips and is ~10× faster at all-Canada scale.
    prefetched = prefetch_all_data(conn)
    place_to_presences = prefetched[1]

    # Pre-fetch CD chain lookups BEFORE rendering any presence pages, so the
    # CSD presence pages can build chain-aware "Part of: <CD>" links via the
    # module-level _CD_CHAIN_BY_RAW_YEAR / _CD_CHAIN_URL_SLUG globals.
    cds = []
    cd_to_csds_by_year = {}
    cd_lineage_by_chain = {}
    cds, cd_to_csds_by_year, _cd_chain_url_full, _raw_to_chain, \
        _canonical_by_chain, cd_lineage_by_chain, _display_label = \
        prefetch_cd_data(prefetched[0])
    # Populate module-level globals used by url_for_cd / cd_link_label.
    _CD_CHAIN_BY_RAW_YEAR.clear()
    _CD_CHAIN_BY_RAW_YEAR.update(_raw_to_chain)
    _CD_CANONICAL_BY_CHAIN.clear()
    _CD_CANONICAL_BY_CHAIN.update(_canonical_by_chain)
    _CD_DISPLAY_LABEL.clear()
    _CD_DISPLAY_LABEL.update(_display_label)
    # Convert full URL paths to last-segment slugs for url_for_cd lookup.
    _CD_CHAIN_URL_SLUG.clear()
    for chain_id, url_path in _cd_chain_url_full.items():
        # url_path is "/hgiscanada/cds/<prov>/<slug>/" — extract <slug>.
        parts = [p for p in url_path.split("/") if p]
        if parts:
            _CD_CHAIN_URL_SLUG[chain_id] = parts[-1]

    written_urls = []
    year_counts = {}
    for pid in targets:
        result = page_for_presence(pid, prefetched, site_url=site_url, base=base)
        if not result:
            print(f"  SKIP (no presence): {pid}", file=sys.stderr)
            continue
        rel_dir, body, canonical = result
        full_dir = out_dir / rel_dir
        full_dir.mkdir(parents=True, exist_ok=True)
        (full_dir / "index.html").write_text(body)
        written_urls.append(canonical)
        try:
            yr = int(pid.split("_")[-1])
            year_counts[yr] = year_counts.get(yr, 0) + 1
        except ValueError:
            pass

    print(f"Wrote {len(written_urls)} year-specific page(s).")

    # Per-Place index pages aggregating across years.  Only emitted in --all mode
    # because they require iteration over the full Place set.
    place_pages_written = 0
    if args.all:
        persons_by_place_for_aggregate = prefetched[6]
        for rel_dir, body, canonical in fetch_place_pages(
            conn, place_to_presences, persons_by_place_for_aggregate,
            site_url=site_url, base=base
        ):
            full_dir = out_dir / rel_dir
            full_dir.mkdir(parents=True, exist_ok=True)
            (full_dir / "index.html").write_text(body)
            written_urls.append(canonical)
            place_pages_written += 1
        print(f"Wrote {place_pages_written} per-Place index page(s).")

    # CD index pages (one per Census Division chain). --all mode only;
    # uses pre-fetched cds + cd_to_csds_by_year + cd_lineage_by_chain.
    cd_pages_written = 0
    if args.all:
        for cd_row in cds:
            cd_id = cd_row[0]
            csds_by_year = cd_to_csds_by_year.get(cd_id, {})
            if not csds_by_year:
                # Chain has no constituent CSDs in any year (rare orphan).
                continue
            lineage_edges = cd_lineage_by_chain.get(cd_id, [])
            rel_dir, body, canonical = render_cd_page(
                cd_row, csds_by_year, lineage_edges,
                site_url=site_url, base=base,
            )
            full_dir = out_dir / rel_dir
            full_dir.mkdir(parents=True, exist_ok=True)
            (full_dir / "index.html").write_text(body)
            written_urls.append(canonical)
            cd_pages_written += 1
        print(f"Wrote {cd_pages_written} per-CD index page(s).")

    # Per-province index pages, only in --all mode (need the full Place set).
    province_counts = {}  # prov_code -> place count
    if args.all:
        # Group places by province for the per-province index pages.
        places_by_prov = defaultdict(list)
        # We have place_to_presences (place_id -> [(year, pop, tcpuid)]) and
        # presence_data (presence_id -> row including province + name + qid).
        # Walk the unique places via place_to_presences keys, look up name/qid
        # from any of their presences, count years.
        place_meta = {}  # place_id -> (name, qid, province)
        for pid_str, row in prefetched[0].items():
            place_id = row[0]
            if place_id not in place_meta:
                place_meta[place_id] = (row[1], row[2], row[4])  # name, qid, province
        for place_id, presences in prefetched[1].items():
            meta = place_meta.get(place_id)
            if not meta:
                continue
            name, qid, prov_code = meta
            years = sorted({yr for yr, _, _ in presences if yr})
            if not years:
                continue
            places_by_prov[prov_code].append(
                (place_id, name, qid, len(years), years[0], years[-1])
            )
        # Group CDs by province for the province-index "Census Divisions" section.
        cds_by_prov = defaultdict(list)
        for cd_row in cds:
            cd_id = cd_row[0]
            cd_name = cd_row[1]
            prov_code = cd_row[2]
            qid = cd_row[4]
            csds_by_year = cd_to_csds_by_year.get(cd_id, {})
            num_csds_max = max((len(v) for v in csds_by_year.values()), default=0)
            if num_csds_max == 0:
                # Skip orphan CDs in the province index too.
                continue
            cds_by_prov[prov_code].append((cd_id, cd_name, qid, num_csds_max))

        for prov_code, places in places_by_prov.items():
            province_counts[prov_code] = len(places)
            rel_dir, body, canonical = render_province_index_page(
                prov_code, places, site_url=site_url, base=base,
                cds_in_prov=cds_by_prov.get(prov_code, []),
            )
            full_dir = out_dir / rel_dir
            full_dir.mkdir(parents=True, exist_ok=True)
            (full_dir / "index.html").write_text(body)
            written_urls.append(canonical)
        print(f"Wrote {len(province_counts)} per-province index page(s).")

    # About / Methodology page.
    if args.all or args.samples:
        rel_dir, body, canonical = render_about_page(site_url=site_url, base=base)
        full_dir = out_dir / rel_dir
        full_dir.mkdir(parents=True, exist_ok=True)
        (full_dir / "index.html").write_text(body)
        written_urls.append(canonical)
        print("Wrote About / Methodology page.")

    # If we wrote the full corpus, also emit index.html, sitemap.xml, .nojekyll, robots.txt.
    if args.all or args.samples:
        # Pick three sample links for the homepage.
        sample_specs = [
            ("Westmeath, Ontario (1871)",
             url_for_presence("Westmeath", "ON082003", 1871, base, "ON"),
             "Wikidata-grounded rural Ontario township, validated against pilot benchmarks"),
            ("Pembroke, Ontario (1851)",
             url_for_presence("Pembroke", "ON033009", 1851, base, "ON"),
             "Demonstrates boundary-continuity linking — Pembroke split into rural + town versions in 1861"),
            ("Alfred, Ontario (1851)",
             url_for_presence("Alfred", "ON031005", 1851, base, "ON"),
             "Wikidata-grounded, eight-year trajectory"),
        ]
        # In --samples mode we don't have province_counts; compute a quick fallback.
        if not province_counts:
            province_counts = {"ON": 1}
            total_places_n = sum(province_counts.values())
        else:
            total_places_n = sum(province_counts.values())
        index_html = render_index(year_counts, sample_specs, province_counts,
                                  total_places_n, site_url, base)
        (out_dir / "index.html").write_text(index_html)
        written_urls.insert(0, f"{site_url}{base}/")

        # robots.txt
        (out_dir / "robots.txt").write_text(
            "User-agent: *\nAllow: /\n"
            f"Sitemap: {site_url}{base}/sitemap.xml\n"
        )

        # .nojekyll so GitHub Pages serves files raw, no Jekyll build.
        (out_dir / ".nojekyll").write_text("")

        # Redirect stubs for chain ids subsumed by the bridge name-match pass.
        # The chain rebuild collapsed e.g. four Peterborough chains into one;
        # the three pre-1921 chain URLs need to redirect to the survivor so
        # existing inbound links and citations still work.
        redirects_csv = REPO / "persistent_places_output" / "place_chain_redirects.csv"
        registry_csv = REPO / "persistent_places_output" / "persistent_place_registry.csv"
        known_chain_ids: set[str] = set()
        if registry_csv.exists():
            with registry_csv.open() as f:
                for r in csv.DictReader(f):
                    known_chain_ids.add(r["persistent_place_id"])
        # Pass the set of URLs we just rendered so stubs don't clobber a
        # real page that happened to share a slug.
        fresh_url_set = set(written_urls)
        n_stubs = write_redirect_stubs(out_dir, site_url, base, redirects_csv,
                                        known_chain_ids, fresh_url_set)
        if n_stubs:
            print(f"Wrote {n_stubs} redirect stub(s) for subsumed chain ids.")

        # Per-presence URL redirects: presence URL embeds the chain's canonical
        # name slug, which changes when the bridge merges chains with different
        # canonical names. Without these stubs, inbound links to old presence
        # URLs (e.g. peterborough-town-of-on093012-1861) would 404.
        presence_redirects_csv = REPO / "persistent_places_output" / "place_presence_redirects.csv"
        n_presence_stubs = write_presence_redirect_stubs(
            out_dir, site_url, base, presence_redirects_csv, fresh_url_set)
        if n_presence_stubs:
            print(f"Wrote {n_presence_stubs} redirect stub(s) for renamed presence URLs.")

        # sitemap.xml
        if args.all:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            (out_dir / "sitemap.xml").write_text(render_sitemap(written_urls, today))
            print(f"Wrote sitemap.xml with {len(written_urls)} URLs.")

        print(f"Wrote index.html, robots.txt, .nojekyll.")


if __name__ == "__main__":
    main()
