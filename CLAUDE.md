# CLAUDE.md — guidance for Claude Code sessions

This file is project-specific context for AI sessions working in this repo.
Onboarding humans: read **README.md** first.

## TL;DR

This is the **HGIS Canada Knowledge Graph** publishing pipeline. It transforms
TCP/HGIS census polygons + the published Excel tables + LINCS/DCB person data
into a CIDOC-CRM linked-open-data graph and renders that graph as the static
site at jimclifford.ca/hgiscanada/.

**Single command to rebuild everything**: `make all`. The Makefile is the
source of truth for build order; do not invent ad-hoc orchestration.

**External paths**: live in `config.toml` (committed default) and
`config.local.toml` (gitignored override). Every script reads paths via
`from _config import CONFIG`. Do not hardcode `/home/jic823/...` in new code.

## Architecture (v10.2+)

The graph is built around two persistent-identity registries:

- **`persistent_places_output/persistent_place_registry.csv`** — Census
  Subdivisions (~13,000) chained across census years via spatial overlap
  (IoU + canonical-name match). Chain id is the user-stable URL
  segment for `/places/<prov>/<slug>/`.
- **`persistent_cds_output/persistent_cd_registry.csv`** — Census Divisions
  (524 chains as of v10.2) with SPLIT_FROM / MERGED_INTO lineage edges.
  Chain id powers `/cds/<prov>/<slug>/`.

The chain-builder (`scripts/build_persistent_cds.py`,
`scripts/build_persistent_places.py`) uses Union-Find over year-pair spatial
overlap rules and a within-year typo-merge pass (`scripts/typo_merge_cds.py`)
that catches OCR variants like Renfew→Renfrew. Name matching uses
`normalize_for_match()` which folds diacritics, unifies hyphen/space, and
treats curly/straight apostrophes equivalently.

Downstream, `scripts/build_neo4j_cidoc_crm_v2.py` mints the CIDOC-CRM CSVs
(E53_Place, E93_Presence, E94_Space_Primitive, P166/P164/P161/P122/P89/P10).
`scripts/build_p10_from_excel.py` overlays the published Excel V1T1/V1T7
CD↔CSD memberships on top of the GDB-derived p10 — Excel is authoritative
for 1851–1901; 1911 and 1921 use GDB (PUB-only Excel for those years).

## Workflow rules

1. **Don't re-introduce hardcoded paths.** New code reads from
   `scripts._config.CONFIG`. The audit `grep /home/jic823 scripts/*.py`
   should return only doc/comment mentions.
2. **Don't break URLs.** Persistent place IDs (CSD chain ids and CD chain
   ids) are public URL segments. Never rename a chain in a way that
   produces a different slug, unless you also publish redirects.
3. **Use the Makefile.** When adding a new pipeline step, add a Make
   target with explicit prerequisites. Don't write a top-level shell
   script that bypasses the dependency graph.
4. **Generated artifacts stay out of git.** `rag_site/`, `pilot/on_kuzu/*.kuzu`,
   `data_quality/` are gitignored. The persistent registries
   (`persistent_*_output/`) and the CIDOC CSVs (`neo4j_cidoc_crm_v2/`) are
   tracked because they're cheap and stable.
5. **Sandbox one-off scripts.** Anything matching `analysis_*.py`,
   `*_visualization.*`, scratch CSVs at the top level → move to `sandbox/`
   (gitignored). Don't litter the root.
6. **Wikidata MCP for entity disambiguation.** The REST `wbsearchentities`
   API returns string-similarity garbage. Always use the Wikidata MCP
   vector search at `https://wd-mcp.wmcloud.org/mcp` (rate-limited to ~5
   req/min — plan accordingly). See `~/.claude/CLAUDE.md` for details.

## Key files

| Path | Role |
|------|------|
| `Makefile` | Pipeline orchestrator |
| `config.toml` | Committed default paths |
| `scripts/_config.py` | Config loader; `from _config import CONFIG` |
| `scripts/build_persistent_cds.py` | CD chain registry builder |
| `scripts/build_persistent_places.py` | CSD chain registry builder |
| `scripts/typo_merge_cds.py` | Post-step: collapse OCR-variant CD chains |
| `scripts/build_neo4j_cidoc_crm_v2.py` | CIDOC-CRM CSV emitter (CSDs) |
| `scripts/build_cd_presences.py` | CD year-presences + GDB-derived p10 |
| `scripts/build_p10_from_excel.py` | Excel-overlay p10 (1851–1901) |
| `scripts/join_wikidata_to_places.py` | Mints `e53_place_uri.csv` |
| `scripts/parse_lincs_dcb.py` + `lincs_*.py` | DCB person pipeline |
| `scripts/generate_rag_pages.py` | Static site renderer |

## Data sources (paths from config.toml)

- **`data_root`** — Contains `TCP_CANADA_CSD_202306/...gdb` + per-year folders
  `1851/.../1901/` with V1T*_CSD_202306.xlsx files. 1891 uses V1T2; 1901 uses
  V1T7. 1911 and 1921 only have PUB tables (no CSD-level NAME columns), so
  the Excel-overlay step skips them and the GDB-derived p10 stands.
- **`lincs_ttl`** + **`lincs_json`** — LINCS Historical Canadians dump.
  Source data for the DCB person cohort.

## CIDOC-CRM modelling notes

- Persistent places (E53_Place) are stable across census years; year-specific
  metrics live on E93_Presence nodes (`<chain_id>_<year>`).
- CSD-within-CD per year is `P10_falls_within` between presence ids
  (presence-level, not place-level — a CSD can move between CDs over time).
- **Geometry chain (RDF)**: `E93 —P161→ E53 spatial-projection place —P168→
  WKT literal`. P161's range and P168's domain are both E53 in CRM v7.x, so
  the projection node is an E53 (the old export typed it E94 off-domain).
  The `<presence>_centroid` / `<cd_presence>_SPACE` ids are kept.
- Border edges (`P122_borders_with`) link the **year-specific spatial
  projection E53s** (P122's domain/range is E53, not E93); lengths reified
  as `E16_Measurement` + `E54_Dimension`, typed
  `base:TYPE_SHARED_BORDER_LENGTH`, with `P39_measured` to **both**
  participating presences and `P4` to the census-year time-span.
- CD presences are fully wired in RDF: P166 → CD place, P164 → time-span,
  P161 → centroid extent, P10 → census period (the `*_cd_*.csv` files;
  before Aug 2026 the exporter skipped them, leaving orphan E93s).
- Every CSD/CD E53 carries `P89_falls_within` → `base:PROV_<code>` →
  `base:PLACE_CANADA`; province nodes owl:sameAs Wikidata (QIDs verified
  via MCP 2026-08-10, listed in `export_rdf.py:PROVINCES`).
- Census variable E55s double as `skos:Concept` in scheme
  `base:VOCAB_CENSUS_VARIABLES` with `skos:broader` category concepts
  (`VARCAT_AGE` … `VARCAT_REL`).
- "NO DATA" placeholder polygons stay in the graph (borders reference them)
  but are labelled "No-data area (…)" and typed `base:TYPE_NO_DATA_UNIT`.
- P132_spatiotemporally_overlaps_with edges (chain continuity between year
  pairs) are exported for both CSD and CD presences.
- Wikidata grounding lives on E53_Place via `e53_place_uri.csv` — chains map
  to a single QID even when sub-year variants drift. 471 QIDs are shared by
  2+ chains; `wikidata_grounding/qid_collision_audit.csv` triages them
  (133 CONFLICTING-NAMES rows are the suspected mis-groundings).

## v10.2 release notes (Apr 2026)

Three classes of bug fixed in the v10.2 deploy:

1. **Same-name CD chain disambiguation** — Toronto East 1871 vs 1911 (and 52
   other province pairs) used to render with identical text in the index;
   now each gets a year qualifier ("Toronto East (1871)" / "(1911)").
2. **QC URL collisions** — 8 chain pairs whose names differed only in
   diacritics or hyphen/space (Châteauguay vs Chateauguay etc.) silently
   overwrote each other's pages. `normalize_for_match()` folds them into
   single chains. The 9th case (Jacques-Cartier 1891 split) is handled by
   a build-time URL-collision fallback in `prefetch_cd_data`.
3. **CD↔CSD membership accuracy** — Kingston City 1901 had 1 CSD in the
   GDB-derived p10 but 7 in the published V1T7 table (ward-level breakdown).
   `build_p10_from_excel.py` overlays Excel as the authoritative source.

See `data_quality/p10_excel_vs_gdb.csv` for the per-CD diff between Excel
and GDB encodings (gitignored, regenerated by `make all`).

## When something is broken

- Site rebuild fails: `make config-check` first — most failures are missing
  external inputs (GDB or LINCS dump not at the configured path).
- URL collision raised at build time: `prefetch_cd_data` raises
  `RuntimeError` listing the offending chain ids. Either add a normalization
  rule in `normalize_for_match()` or accept the auto-demoted slug.
- Chain count changed unexpectedly after a rebuild: diff
  `persistent_cds_output/persistent_cd_registry.csv` against HEAD. (The old
  e93/p10 feedback loop — chain_ids leaking back as raw_cd_ids — was closed
  in Aug 2026: the CD builder now reads `cd_links_output/cd_inventory.csv`,
  a GDB-derived universe from `scripts/dump_cd_inventory.py`, and refuses to
  fall back to downstream outputs. Rebuilds are order-independent now.)
- "1-CSD CD" complaint: cross-check the published Excel table for that
  (year, CD) — many are real (Toronto Centre City 1901 = Ward 3 (part)).
  Genuine bugs land in `build_p10_from_excel.py`.
