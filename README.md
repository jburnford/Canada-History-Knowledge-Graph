# HGIS Canada Knowledge Graph

CIDOC-CRM linked-open-data for the Canadian Census of Population, 1851–1921.
Static site at **[jimclifford.ca/hgiscanada](https://jimclifford.ca/hgiscanada/)**.

The current RDF-aligned website publishes:

- **47 source workbooks**, **77,856 reporting rows**, and **1,783,554 preserved
  statistical cells**, including **1,138,818 numeric observations**.
- Source-cell citations, original values, definitions, units, reference-period
  qualifications and provenance. Numeric RDF assertions use CRM E13/E54 and the
  RDF Data Cube; missing or textual cells remain separate evidence records.
- **22,522 census map representations** and **13,401 qualified continuity
  groups**, with geographic assessments, area intersections and separations.
  Candidate matches do not become historical-identity or Wikidata sameAs claims.
- Preserved published addresses, LINCS / Dictionary of Canadian Biography
  connections, and the separate **1881 individual census** pages and anchors.

Read [the website build and retrieval contract](docs/RDF_WEBSITE_BUILD.md) and
[the source-table rebuild](docs/LOD_SOURCE_TABLE_REBUILD.md). The website reads
the same source databases as the current source RDF; the older Kuzu pipeline is
retained for comparison. Geographic/identity assessments are qualified
supplemental layers, not unqualified assertions in the source RDF.

## Quickstart

Prerequisites:
- Python 3.11+ with `pandas`, `rapidfuzz`, `neo4j`, `rdflib` (`pip install -r requirements.txt`)
- `conda` with a `geo` env containing `geopandas`, `fiona`, `pyproj`, `shapely`, `rtree`
- The TCP/HGIS data downloads (instructions below)
- The LINCS Historical Canadians TTL + JSON dumps (for the DCB person pipeline)

```bash
# 1. Clone
git clone git@github.com:jburnford/Canada-History-Knowledge-Graph.git
cd Canada-History-Knowledge-Graph

# 2. Configure paths to external data
cp config.toml config.local.toml
# Edit config.local.toml: set [paths].data_root to where you unpacked the
# TCP_CANADA_CSD_202306.gdb + per-year Excel folders. Set lincs_ttl/lincs_json
# to your LINCS dumps. Set hgiscanada_repo to your local clone of the
# jburnford/hgiscanada repository (needed to preserve published people pages).
$EDITOR config.local.toml

# 3. Verify config resolves
make config-check

# 4. With current, validated RDF/identity/binding staging (see build guide):
make rdf-site
make rdf-site-check

# 5. Inspect locally at http://127.0.0.1:8000/hgiscanada/
make rdf-site-serve

# 6. Deploy to GitHub Pages
make deploy
```

## Legacy pipeline

The diagram below documents the retained Kuzu/CSV pipeline. The current default
website build is `make rdf-site`; its inputs and checks are documented in the
[build guide](docs/RDF_WEBSITE_BUILD.md).

The `Makefile` is the single source of truth for build order. Run
`make -n all` to print the dependency-aware command sequence.

```
                     ┌──────────────────┐
External downloads → │ TCP GDB + Excel  │ ──┐
                     └──────────────────┘   │
                                             ▼
year_links_output/  ─────────┐    ┌─ persistent_places_output/
cd_links_output/    ─────────┴──► │
(committed; rebuild              ┌─ persistent_cds_output/  ◄─ typo_merge_cds.py
 with `make link`)               │
                                  ▼
                     build_neo4j_cidoc_crm_v2.py  (CIDOC E53/E93/E94/P-* CSVs)
                     build_cd_presences.py        (CD year presences + p10)
                     build_p10_from_excel.py      (Excel-authoritative p10
                                                   for 1851–1901)
                     build_p132_overlaps.py       (P132 spatiotemporal edges)
                                  │
                                  ▼
                     join_wikidata_to_places.py   (e53_place_uri.csv:
                                                   wikidata QIDs + minted URIs)
                                  │
                                  ▼
LINCS TTL  ────► parse_lincs_dcb.py ─┐
                                      ├─► lincs_strategy1_wikidata.py ─┐
                                      ├─► lincs_strategy3_pip.py      ─┤
                                      └─► lincs_combine_links.py ◄─────┘
                                  │
                                  ▼
                     generate_rag_pages.py  ──► rag_site/
                                                ├── index.html
                                                ├── places/<prov>/...
                                                ├── cds/<prov>/...
                                                └── sitemap.xml
                                  │
                                  ▼
                            Legacy comparison output (not the deployment target)
```

Make targets:

| Target | What it does |
|--------|--------------|
| `make all` / `make site` | Build the RDF-aligned website in `data_quality/rdf_site/` |
| `make legacy-site` | Build the older Kuzu-based site for comparison |
| `make rdf-site-check` | Validate RDF, rendered cells, retrieval records, URLs and links |
| `make rdf-site-editorial` | Refresh About, home and province indexes for the unchanged data edition |
| `make dcb` | Refresh DCB person links only |
| `make link` | Re-run spatial linking (~70 min, needs `geo` env + GDB) |
| `make deploy` | Validate `data_quality/rdf_site/`, sync to the website repository and push |
| `make clean` | Drop generated outputs (keeps registries) |
| `make distclean` | Drop everything regenerable |
| `make config-check` | Print resolved paths from config.toml |

## Repo layout

```
.
├── config.toml                # Default paths (committed)
├── config.local.toml          # User-local overrides (gitignored)
├── Makefile                   # Pipeline orchestrator
├── scripts/                   # All pipeline + utility scripts
│   └── _config.py             # Loads config.toml; central path resolver
├── cd_links_output/           # Spatial-overlap output: CD year-pair links
├── year_links_output/         # Spatial-overlap output: CSD year-pair links
├── persistent_cds_output/     # CD chain registry + lineage (524 chains)
├── persistent_places_output/  # CSD persistent place registry
├── neo4j_cidoc_crm_v2/        # CIDOC-CRM CSVs (E53/E93/E94/P*)
├── neo4j_census_v2/           # Census measurements (E16/E54/E55/E58)
├── neo4j_provenance/          # E33/E39/E65/E73 provenance entities
├── wikidata_grounding/        # Wikidata match audit + sitelinks
├── data/                      # DCB pipeline outputs + geocoder cache
├── pilot/on_kuzu/             # KuzuDB / Ladybug pilot (Ontario)
├── data_quality/rdf_site/     # Current RDF-aligned website (gitignored)
├── rag_site/                  # Legacy comparison site (gitignored)
└── sandbox/                   # One-off analysis artifacts (gitignored)
```

## Data sources & attribution

### Geospatial boundaries

**The Canadian Historical GIS (Temporal Census Polygons)** — Cunfer, Billard,
McClean, Richard, St-Hilaire, *The Canadian Peoples / Les populations
canadiennes*. CC BY 4.0. DOI [10.5683/SP3/PKUZJN](https://doi.org/10.5683/SP3/PKUZJN).
[Borealis](https://borealisdata.ca/dataverse/census).

### Census aggregate data (per year)

Same authors / project / license. Individual-year DOIs:
[1851](https://doi.org/10.5683/SP3/NRPFY5) ·
[1861](https://doi.org/10.5683/SP3/1I1C59) ·
[1871](https://doi.org/10.5683/SP3/IYAR1W) ·
[1881](https://doi.org/10.5683/SP3/SFG7UI) ·
[1891](https://doi.org/10.5683/SP3/QA4AKE) ·
[1901](https://doi.org/10.5683/SP3/6XFJNU) ·
[1911](https://doi.org/10.5683/SP3/7ZG4XV) ·
[1921](https://doi.org/10.5683/SP3/JPGS9B)

### Persons

**Dictionary of Canadian Biography** (DCB) — University of Toronto / Université
Laval. Person URIs come from the **LINCS Historical Canadians** dataset
([LINCS Project](https://lincsproject.ca/)). Each person card on the rag_site
links back to the canonical DCB biography.

### Authority links

**Wikidata** (CC0) for QIDs and Wikipedia sitelinks. **GeoNames** (CC BY)
for coordinate fallbacks where Wikidata coverage is thin.

## Modelling

The current source graph distinguishes source reporting units, row/cell evidence,
numeric quantities and reported-attribute assignments. Numeric cells are also
RDF Data Cube observations. Reference periods, units, missingness and provenance
remain explicit; geographic candidates do not change the assertion subject.
See [the rebuild model](docs/LOD_REBUILD_PLAN.md) and
[identity/reporting migration](docs/LOD_IDENTITY_AND_REPORTING_MIGRATION.md).

The following patterns document the **legacy graph**, retained for comparison;
they are not the current source-RDF contract:

- `E53_Place` (chain id) — `P166_was_a_presence_of` ← `E93_Presence` (year-specific) — `P164_is_temporally_specified_by` → `E4_Period`
- `E93_Presence` — `P10_falls_within` → `E93_Presence` (CSD-in-CD per year)
- `E93_Presence` — `P132_spatiotemporally_overlaps_with` → `E93_Presence` (cross-year overlap)
- `E16_Measurement` — `P39_measured` → `E93_Presence`, `P40_observed_dimension` → `E54_Dimension`, `P91_has_unit` → `E58`

See `CLAUDE.md` for the modelling rationale and the v9/v10 history.

## Contributing & issues

The site is generated from this repo + the LINCS / TCP-HGIS upstream data.
Bug reports against the public site (broken links, wrong CSD memberships,
missing persons) belong as issues here. The deployment repo
([jburnford/hgiscanada](https://github.com/jburnford/hgiscanada)) is regenerated
by `make deploy` and shouldn't receive direct PRs.

## License

Code: MIT. Data outputs follow the upstream TCP-HGIS license (CC BY 4.0).
DCB excerpts and links: see DCB site terms.
