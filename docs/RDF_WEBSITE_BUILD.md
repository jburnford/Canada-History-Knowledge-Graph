# RDF-aligned historical evidence website

The current website build reads the same validated source-cell SQLite databases
as the national source RDF exporter. It does not read aggregate statistics from
the older Kuzu database. Published addresses remain a separate, versioned input.

## Build and review

```sh
make rdf-site       # also the default make all / make site
make rdf-site-check # full RDF, HTML, retrieval, URL and internal-link checks
make rdf-site-serve # local preview at http://127.0.0.1:8000/hgiscanada/
```

`make rdf-site-editorial` refreshes About, home and province indexes for an
unchanged data edition. Original province values remain intact in source rows;
navigation trims whitespace, recognizes PEI as PE, and does not mint province
pages from country codes or unevaluated spreadsheet formulas.

`make rdf-site-wikidata` rebuilds the external-link assessment and refreshes
continuity-group pages, About and data downloads in the existing preview. It
requires unchanged source databases, published URL inventory, boundaries,
continuity groups and source bindings. Refreshes update the preview in place;
publication still requires the complete validation below.

The output is `data_quality/rdf_site/`. A build first writes a fresh sibling
directory, then replaces the previous completed preview. The preceding completed
build is retained as `data_quality/rdf_site.previous/`. Failed builds leave the
completed preview intact. The builder refuses to replace the live website
checkout, `rag_site/`, or a directory without its own build manifest.

The source workbooks must already have been staged, exported and validated with
`make lod-census-sources`, `make lod-census-source-rdf`, and
`make lod-source-bindings`; the identity inventory and equal-area GIS audit must
also be current. The builder rejects database hashes that differ from the RDF
export or geographic assessment, changed RDF exporter code, and changed evidence
behind the identity inventory. It does not silently regenerate these assessments.

`make legacy-site` retains the older Kuzu-based build for comparison.
`make deploy` validates the RDF-site artifact before syncing it to the configured
`hgiscanada` checkout and pushing that repository. Building and checking do not
publish anything. The pipeline repository and the published-file repository are
separate repositories; committing the former does not publish the latter.

## What each page means

| Page | Subject and evidence |
| --- | --- |
| `/sources/<workbook>/rows/<Excel-row>/` | One source reporting row, with exact cell anchors, definitions, original reporting level, geography vintage, reference-period and unit status, and source metadata. |
| Existing census-year URL, or `/snapshots/<level>/<id>/` | A map representation with qualified links to source rows, all positive cross-year polygon intersections, and continuity/area-separation assessments. |
| Retained unchanged group URL, or `/units/<level>/<id>/` | A current qualified census continuity group. This does not assert that the group is a historical municipality. |
| Earlier group URL whose membership changed | An explanatory page linking to the revised groups and individual representations. Earlier statistical series are not repeated as current facts. |
| Existing `/residents/…` URL and `#p-…` anchor | The separately published individual 1881 transcription, preserved with its existing geographic grouping. |

The homepage, province indexes, About page and data instructions are rebuilt.
Biographical tables retain the published names, lifespans, connection labels and
DCB links. They are labelled as a separate LINCS/biographical layer and are not
automatically assigned to every new census identity.

The source RDF currently represents source statements. The website also exposes
the revised geographic and identity assessments as **qualified supplemental
evidence**. It does not claim those assessment CSVs are already assertions in the
source RDF, or turn their candidate map links into `sameAs` relationships.

## Wikidata reference links

Established links remain usable without requiring individual human review.
The assessment carries forward cached CSD, district and presence verification,
as well as earlier curated corrections for retained identities. Confirmations
in `data/wikidata_link_confirmations.csv` apply to an exact unit/QID pair.
They do not propagate automatically to groups split from an earlier identifier.

Automated checks use census names, cached entity types and descriptions, and
available census centroids attached to earlier verified matches. Historical
spelling variants and aliases are retained. A different name within 10 km of
an earlier verified census location can retain an established reference link;
the name difference stays in its evidence metadata. This is contextual support,
not proof of identity. Inherited matches more than 50 km from every available
verified census location are flagged. These are comparisons of census-area
centroids, not a new live Wikidata-coordinate verification. Large or changing
areas can need clarification even when their link is correct.

Other concrete flags include incompatible township/settlement types, conflicting
provincial context, unsupported different names, explicit later founding dates,
and unresolved warnings from earlier verification. Municipal incorporation after
a census does not by itself conflict with an older settlement. Missing metadata
is recorded as an evidence gap and does not create a review requirement.

The downloadable `wikidata_associations.csv` records acceptance, basis, detailed
evidence, gaps and conflict reasons. `wikidata_review_queue.csv` contains only
flagged associations. `wikidata_qa_sample.csv` selects up to three accepted links
per acceptance-status/province stratum using a stable unit/QID hash. Sampling
supports ongoing QA; it is not a publication gate or a claim that every link
has been reviewed. Input checksums and counts are in the identity manifest.

Accepted links appear under **Wikidata**, with the linked entity's label and
available type. Flagged links remain visible with a specific plain-language
explanation. Both HTML and downloads distinguish reference-link acceptance
from asserting `owl:sameAs` for a census representation; `identity_asserted`
remains false. The source-cell RDF and statistics are unaffected.

## Retrieval contract

Each workbook provides `cells.jsonl.gz`, with one record per preserved statistical
cell, plus a byte-identical `source.nt.gz` RDF download. JSONL records include:

- `citation_url`, exact `rdf_id`, `source_reporting_unit`, and `source_document`;
- original workbook filename/checksum, worksheet, source cell and column position;
- source label/code/province and reporting level;
- source definition and definition evidence;
- reporting geography vintage, reference year, reference-period kind and wording;
- raw value JSON, numeric lexical value, value status, unit and unit status.

`rdf_decimal` is an exact decimal **string**, or null for nonnumeric cells. It must
not be parsed through binary floating point when precision matters. A missing
reference year is not replaced by the census vintage. Blanks are not zeros.
Repeated variable labels remain separate column-position identities. District,
province and country totals must not be added to their constituent CSD totals.

A concrete example is `1911_V1T1_PUB_202306`, row 2, cell `M2`: Canada population
**5,371,315**, reference year **1901**, reporting geography vintage **1911**. Its
citation is `/hgiscanada/sources/1911_V1T1_PUB_202306/rows/2/#cell-M`.
Another row, 9866 in that workbook, reports survey township `T24 R1 MW3` with
source code `SK216003`. Its statistics are not assigned to Saskatoon merely
because a map record reuses the code.

Chunk source rows or individual cells with their reporting context. Preserve
qualifications in retrieved passages and cite cell URLs. The JSONL files contain
aggregate source cells; biographies and individual residents remain separate
retrieval sources. `/data/` documents the contract and links the evidence files;
`llms.txt` is an additional discovery aid, not a replacement for HTML navigation.

## Validation and publication

The independent reconciler checks every JSONL record and every rendered source
cell against SQLite, including visible text, value, date, unit, definition,
reporting subject and citation anchor. It stream-parses all published source RDF
and reconciles data-cube observations and CRM quantities/assignments against the
same databases. It verifies downloaded supplemental evidence by checksum.

The URL audit checks every baseline address, redirects, canonical URLs, sitemap
membership, biography/resident links and resident anchor fingerprints. The
internal-link checker also compares the original biographical tables verbatim
and checks assets and citation fragments. Tests cover retrospective dates,
unknown values/units, repeated headers, numeric precision, markup escaping,
accented paths and sitemap-index traversal.

For parallel verification or repeat checks, the reconciler supports
`--rdf-only`, `--html-only`, and `--rdf-cache <report>`. Cached RDF results are
accepted only for the identical RDF bytes, source database and validator code.
A partial or failed RDF report cannot bypass validation.

Canonical URLs are split across sitemap files of at most 40,000 entries and
linked by `sitemap.xml`. This stays within Google's 50,000-URL / 50-MB limit for
individual sitemaps ([Google sitemap guidance](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap)).
URL preservation helps retain citations and crawl paths; it does not guarantee
that Google will retain every page's ranking after content corrections.

## National validation, 2026-09-05

The complete local build contains 158,690 HTML pages and 119,920 indexed canonical
URLs. Validation reconciled all 1,783,554 cells and 36,001,307 RDF triples. All
69,116 protected publication addresses survived, including 4,258,989 individual
resident anchors. The internal-link audit checked 3,487,505 links and verified
4,853 original biographical tables verbatim, with no errors. The complete test
suite passed 80 tests. Detailed reports are generated under `data_quality/`.

The publication baseline is website commit
`9275f55eec5eac1dd501792998bf8f6a273abdde`; it identifies the pre-rebuild site for
rollback comparison.
