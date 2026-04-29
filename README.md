# HGIS Canada Knowledge Graph

CIDOC-CRM linked-open-data for the Canadian Census of Population, 1851–1921.
Static site at **[jimclifford.ca/hgiscanada](https://jimclifford.ca/hgiscanada/)**.

What's in the graph:
- ~13,000 persistent **Census Subdivisions** (CSDs) with persistent IDs
  spanning the 1851–1921 census series — chained via spatial overlap so a
  community appears as one entity across years even when its name shifts.
- 524 persistent **Census Divisions** (counties/regions) with
  SPLIT_FROM / MERGED_INTO lineage edges.
- ~1.4 million **measurements** (population, demographics, agriculture,
  buildings, religion, ethnicity) modelled as CIDOC-CRM E16_Measurement.
- ~5,900 **Dictionary of Canadian Biography** persons linked to the CSDs
  where they were born, died, or were buried (via Wikidata + spatial join).
- **Wikidata grounding** for ~50% of CDs and most CSDs; minted persistent
  URIs at `jimclifford.ca/hgiscanada/places/...` for the rest.

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
# jburnford/hgiscanada GitHub Pages repo (only needed for `make deploy`).
$EDITOR config.local.toml

# 3. Verify config resolves
make config-check

# 4. Build the site (~15 min on a warm rebuild; ~2 hours from a clean state)
make all

# 5. Inspect locally (rag_site/index.html)
python3 -m http.server --directory rag_site 8000

# 6. Deploy to GitHub Pages
make deploy
```

## Pipeline

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
                            make deploy  ──► hgiscanada repo (GitHub Pages)
```

Make targets:

| Target | What it does |
|--------|--------------|
| `make all` | Full rebuild from registries + GDB + Excel + LINCS → rag_site/ |
| `make site` | Render rag_site/ only (skips upstream rebuilds) |
| `make dcb` | Refresh DCB person links only |
| `make link` | Re-run spatial linking (~70 min, needs `geo` env + GDB) |
| `make deploy` | rsync rag_site/ to hgiscanada repo and push |
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
├── rag_site/                  # Generated static site (gitignored)
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

The graph follows **CIDOC-CRM v7.3.1** with the LINCS application profile.
Key pattern:

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
