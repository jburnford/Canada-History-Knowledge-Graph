# Published URL preservation

The HTML migration retains published addresses independently of display names,
graph identifiers, and RDF modelling changes. The URL registry is a versioned
publication input; rebuilding the data must not regenerate it.

## Publication baseline

`data/published_site_urls.csv` was captured from the deployment checkout at
commit `9275f55eec5eac1dd501792998bf8f6a273abdde`. Its sitemap was compared
byte-for-byte with the live sitemap on 2026-09-05. The accompanying JSON records
source and inventory hashes.

The inventory includes all 69,116 HTML pages, including 6,976 redirects and
33,974 resident pages. The live sitemap has 31,237 entries but only 30,241
distinct addresses. Pages omitted from the sitemap are protected too.
Google's verification file is excluded because deployment preserves it
separately.

The baseline records biography destinations on 5,141 pages and fingerprints
4,258,989 individual resident anchors. These protect the prominent-person
sections and the individual-level 1881 census, including leaf pages that are
intentionally marked `noindex,follow`. They are distinct from the aggregate
census-table RDF rebuild.

## URL ownership

`scripts/_site_urls.py` resolves census snapshots by TCPUID/year, all-years
pages by their published place identifier, and district pages by their CD
identifier. It reads embedded identifiers when capturing HTML; a year suffix
alone cannot distinguish a snapshot from an all-years page.

Published paths take precedence over newly calculated slugs. Names and even
province labels can be corrected without changing an address. The page
generator, facts export (through the shared page helpers), and resident URI
builder use this resolver. Resident overview addresses remain independently
pinned when the parent census detail address changes.

The old generator wrote census-year and all-years pages to the same address in
996 cases. The all-years page was written last and is the published owner.
That page keeps its URL; the previously overwritten year detail is generated
at `<existing-address>/census-<year>/`. Resident pages beneath the original
address keep their URLs and person anchors.

When a graph identifier changes and there is a reviewed one-to-one continuity,
add a row to `data/site_url_assignments.csv` with the new entity key, published
path, and evidence/reason. Two active entities cannot claim the same address.
An old chain that resolves to several units needs an explanatory page at its
old address; it must not silently redirect to one selected successor.

Existing HTML redirects are recreated and pointed to current canonical pages
when their recorded endpoint can be resolved. Static HTML refresh redirects
are retained for this GitHub Pages deployment; this code does not configure
server-side HTTP 301 responses.

`data/site_legacy_records.json` explicitly preserves 48 earlier district pages
that the current renderer no longer emits. Their original published HTML is
hashed and retained with an archive notice, including the original constituent
records and citations. Another 57 entries provide fallback explanations for
broken published redirects, identifying the associated boundary source record.
An explanation is used only while a rendered replacement is unavailable. These
carry the record from the staged representation inventory and its source-file
hash. They do not infer populations, turn NO DATA coverage into communities,
or establish historical identity from an old redirect.

The Verdun check also distinguishes the chain identifier's apparent year/code
from the actual 1881 snapshot. Resident links are attached only to the chain's
recorded 1881 TCPUID, avoiding a link to a nonexistent resident collection on
a formerly overwritten census-detail page.

The facts check also found nine census snapshots with statistics but no
population total. The main generator now includes snapshots with any exported
measurements, so those fact subjects have actual census-detail pages.

## Checks and local preview

```bash
make site-url-test
make site-url-migration
make site-url-preview
make site-url-check
```

The preview starts with the deployment checkout's supporting files and
resident pages, then regenerates the main site into
`data_quality/site_url_preview/`. It uses the existing database to verify URL
behaviour; it does not claim to migrate the new source RDF into the website.
It does not publish. The two full census datasets must remain distinct while
the corrected geographic and historical-identity associations are integrated.

`make deploy` now runs the preservation check before rsync or git push. It
requires the full-build manifest, which distinguishes regenerated primary
pages and recreated aliases from stale HTML left in a warm output directory.
The check rejects missing published addresses, redirect loops or missing
targets, incorrect canonical addresses, accidental noindex/sitemap changes,
removed biography or resident links, and changed resident citation anchors.
It also checks the subject URLs in every emitted facts JSONL file.
The main generator retains resident overview sitemap entries when carrying
forward their HTML. A clean build must also run `make residents` before it can
pass the deployment check.

Intentional changes to biography associations or resident anchor membership
require reviewing and updating the publication baseline; they cannot be
silently accepted by a normal build. Anchor fingerprints check membership,
including replacement of one person by another at the same row count; they
do not validate all resident attribute values. The URL audit is not a full
historical-identity or observation-provenance validator.

To capture a later publication without overwriting the existing baseline:

```bash
make site-url-capture SITE_URL_CAPTURE=data_quality/site_urls/next_publication.csv
# Review the diff and source metadata before adopting a new baseline.
```

The migration report is `data_quality/site_urls/migration_review.csv`. It
lists every old URL and its proposed treatment against the staged identity
crosswalk, including biography/resident flags. It is a review queue, not an
automatic approval of historical identity mappings.

A representative resident rebuild uses New Glasgow's actual 1881 source data:
its 943 person anchors remain at the published resident address while the
parent census detail uses the newly disambiguated `census-1881/` address.
The full preview audit reports preservation of all baseline biography and
resident links and all 4,258,989 baseline resident anchors; these checks do not
reassign those people to the new LOD historical identities.

The completed 2026-09-05 preview contains 70,121 HTML pages. All 69,116
published addresses pass preservation checks, and all 20,403 subject URLs in
858,422 exported facts resolve to pages. The final audit reports zero errors;
the focused URL regression suite passes 18 tests. This is a local preview,
not a publication or completion of the RDF-to-HTML data migration.

The About page, homepage, and province introductions now distinguish the earlier
HTML database from the rebuilt source RDF. They document the biography and 1881
resident sources, URL preservation, archived records, and the limits of cross-year
identity and population comparisons. Regenerating these supporting pages does
not complete the pending data integration.
