"""Retain explicitly inventoried legacy pages without inventing identity links."""
import hashlib
import html
import json
from pathlib import Path

from _site_urls import BASE, ORIGIN, REPO, page_file

LEGACY_RECORDS = REPO / "data/site_legacy_records.json"


def render_legacy(record, site_url=ORIGIN, base=BASE):
    path = base + record["path"][len(BASE):]
    if record["kind"] == "archive":
        body = record["published_html"]
        if hashlib.sha256(body.encode()).hexdigest() != record["published_html_sha256"]:
            raise ValueError(f"Archived publication hash mismatch: {path}")
        note = ('<aside class="meta"><strong>Archived census district page.</strong> '
                'This page preserves an earlier published grouping of census subdivisions. '
                'Its correspondence to the revised district records is under review. '
                'The original census years, constituent records, and source references '
                'are retained below.</aside>')
        marker = "<article>" if "<article>" in body else "<body>"
        body = body.replace(marker, marker + "\n" + note, 1)
        body = body.replace(ORIGIN + BASE + "/", site_url + base + "/")
        body = body.replace('"' + BASE + "/", '"' + base + "/")
        return path, body
    if record["kind"] != "source_record":
        raise ValueError(f"Unknown legacy page treatment: {record['kind']}")
    r = record["source_record"]
    title = f"{r['name']} — {r['year']} census boundary record"
    coverage = r["is_coverage_record"] == "True"
    explanation = (
        'The boundary source marks this area as NO DATA. It is retained as a coverage '
        'record; it does not establish a community identity or a population of zero.'
        if coverage else
        'This boundary record is retained in the census inventory. Statistical '
        'observations have not yet been linked to this page; no population total is '
        'inferred from the boundary or from another place with a similar name.')
    body = f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="canonical" href="{html.escape(site_url + path)}">
<style>body {{font-family:system-ui,sans-serif;max-width:760px;margin:2em auto;padding:0 1em;line-height:1.6}} dt {{font-weight:bold}} dd {{margin-bottom:0.7em}}</style>
</head><body><article>
<p><a href="{base}/">HGIS Canada</a></p>
<h1>{html.escape(title)}</h1>
<p>This address previously redirected to a census page that was unavailable.
It now identifies the boundary source record associated with that redirect.
The source label is shown below; an older name in this URL is retained for existing citations.</p>
<p>{explanation}</p>
<dl><dt>Source boundary identifier</dt><dd>{html.escape(r['source_id'])}</dd>
<dt>Census vintage</dt><dd>{html.escape(r['year'])}</dd>
<dt>Source label</dt><dd>{html.escape(r['name'])}</dd>
<dt>Province or territory code in the boundary inventory</dt><dd>{html.escape(r['province'])}</dd>
<dt>District label in the boundary inventory</dt><dd>{html.escape(r['cd_name'])}</dd>
<dt>Record status</dt><dd>{'Source coverage record' if coverage else 'Census boundary representation; statistical linkage pending'}</dd></dl>
<h2>Sources and interpretation</h2>
<p>The record comes from the Canadian Peoples / TCP census boundary inventory,
preserved in the project's national representation inventory as
<code>{html.escape(r['snapshot_id'])}</code>.
The association recorded by the older redirect does not establish that different
place labels refer to the same historical community.</p>
<p><a href="https://borealisdata.ca/dataverse/canadiansubdivisions">Canadian Peoples / TCP source data</a>
 · <a href="{base}/about/">Project methodology</a></p>
</article></body></html>'''
    return path, body


def write_legacy_pages(out: Path, handled: set[str], site_url=ORIGIN, base=BASE):
    written = set()
    for record in json.loads(LEGACY_RECORDS.read_text())["pages"]:
        path = base + record["path"][len(BASE):]
        if path in handled:
            continue
        path, body = render_legacy(record, site_url, base)
        file = page_file(out, path, base)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(body)
        written.add(path)
    return written
