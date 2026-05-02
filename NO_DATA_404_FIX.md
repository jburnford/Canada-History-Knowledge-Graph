# NO-DATA presence pages: 404 fix

**Status:** identified, not fixed. Discovered 2026-04-30 from a Google Search
Console report flagging `https://jimclifford.ca/hgiscanada/places/nt/no-data-nt193999-1881/`
as 404.

## Symptom

Google indexed CSD presence URLs for "NO DATA" placeholder polygons (tcpuids
ending in `999`, e.g. `NT193999`). Those URLs return 404 because the page
generator emits the chain page (`/places/nt/no-data-nt193999/`) but **not**
the year-pinned presence page (`/places/nt/no-data-nt193999-1881/`).

The sitemap itself is fine — it only references the chain URL, which exists.
The 404s come from broken `<a href>` links inside neighbour pages.

## Scope

```
328 NO-DATA placeholder presences across all years (tcpuid ending 999)
274 distinct year-pinned NO-DATA URLs are linked from other pages but have no
    directory on disk
329 distinct NO-DATA link targets site-wide
~18+ pages link to no-data-nt193999-1881 alone
```

The same pattern affects every province with NO-DATA polygons (NT, MB, ON, QC,
SK, …). Expect Google to surface more 404s as it crawls neighbours.

## Root cause

`scripts/generate_rag_pages.py:2713` filters presence emission by population:

```python
res = conn.execute(
    "MATCH (pr:Presence) WHERE pr.pop_total IS NOT NULL "
    "RETURN pr.presence_id ORDER BY pr.year, pr.presence_id;"
)
```

So NO-DATA presences never get a page. But the renderers that build neighbour
links generate `url_for_presence(...)` URLs **unconditionally**:

- `render_overlaps_section` — `scripts/generate_rag_pages.py:1178`
- neighbours block — `scripts/generate_rag_pages.py:1366`

Both emit `/places/<prov>/<slug>-<tcpuid>-<year>/` for every neighbour, including
NO-DATA ones. Those URLs are 404s.

Verify:
```bash
grep 'no-data-nt193999' rag_site/places/nt/york-factory-nt193008-1881/index.html
# <li><a href="/hgiscanada/places/nt/no-data-nt193999-1881/">NO DATA</a></li>

curl -sI 'https://jimclifford.ca/hgiscanada/places/nt/no-data-nt193999-1881/' | head -1
# HTTP/2 404

curl -sI 'https://jimclifford.ca/hgiscanada/places/nt/no-data-nt193999/' | head -1
# HTTP/2 200
```

## Fix options

### Option 1 — drop the `pop_total` filter (recommended)

Emit a thin presence page for every NO-DATA polygon. Pages render with empty
population sections but still carry geometry, neighbours, lineage, and the
year context — which is actually useful ("this polygon was a CSD in 1881 with
no census data reported"). Roughly 5 lines of code; +328 pages site-wide.

```python
# scripts/generate_rag_pages.py:~2712
res = conn.execute(
    "MATCH (pr:Presence) RETURN pr.presence_id "
    "ORDER BY pr.year, pr.presence_id;"
)
```

Verify the renderer handles `pop_total IS NULL` gracefully before deploying —
`fmt_pop` already returns "—" for None, so most code paths should be fine,
but check `render_measurements_section`, `render_persons_section`, and the
JSON-LD block in `render_page` for places that assume a non-null pop.

### Option 2 — skip NO-DATA neighbour links

Filter NO-DATA neighbours out of the rendered link list. Keeps page count flat
but loses adjacency context for the boundary polygons. Two call sites to
change.

```python
# render_overlaps_section, neighbours block
if other_tcpuid.endswith("999"):
    continue
```

### Option 3 — point NO-DATA links at the chain URL

Cheapest patch: when the neighbour is NO-DATA, use `url_for_place` instead of
`url_for_presence`. URL becomes `/places/nt/no-data-nt193999/` (exists) but
loses the year qualifier on the link. Two call sites.

## Recommended sequence

1. Apply option 1 (drop the filter).
2. Rebuild: `make site` (or `make all` if anything upstream changed).
3. Spot-check `rag_site/places/nt/no-data-nt193999-1881/index.html` exists and
   renders without errors.
4. Re-run `grep -rho 'href="/hgiscanada/places/[a-z]*/no-data-[a-z]*[0-9]*-1[89][0-9]*/"' rag_site/`
   and confirm the missing-dir count is 0.
5. `make deploy`.
6. In Google Search Console, request re-indexing of the example URL
   `places/nt/no-data-nt193999-1881/` once it returns 200; the rest should
   resolve naturally on Google's next crawl.

## Related URL stability concerns

CLAUDE.md rule: *"Don't break URLs. Persistent place IDs are public URL segments.
Never rename a chain in a way that produces a different slug, unless you also
publish redirects."*

This 404 isn't a slug rename — it's a URL we never emitted in the first place
but linked to. The fix preserves every existing URL and adds the missing ones.
No redirects needed.

If we ever do need redirect stubs for genuinely renamed chains (v10.x changed
some chain ids when collisions were resolved), the GitHub Pages-compatible
pattern is a one-line meta-refresh page at the old path:

```html
<!DOCTYPE html><meta http-equiv="refresh" content="0; url=/hgiscanada/<new>/">
<link rel="canonical" href="https://jimclifford.ca/hgiscanada/<new>/">
```

That's not part of this fix; track separately if the issue surfaces.
