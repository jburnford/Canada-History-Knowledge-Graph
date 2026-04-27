# RAG Optimization Plan — Phases B and C

**Status as of 2026-04-27**: Phase A complete and shipped. This doc is the cold-start handoff for a fresh Claude session to take Phase B and Phase C from here.

## What this is

`hgiscanada` exists to help RAG systems answer historical-Canada questions accurately. The site renders one page per (CSD, year) and per (CD, chain) under <https://jimclifford.ca/hgiscanada/>. Pages are generated from a Ladybug graph DB built from the TCP/LPC Canadian Peoples Project tables (1851–1921).

The phases below are about making those pages *better at supporting accurate retrieval* — not about adding more data. Read in order.

---

## Phase A baseline (done — what a Phase B session inherits)

### Goal that Phase A achieved
Replace ingestion-artifact variable codes (e.g. `TUR BU`, `C103_Between_90_and_100_years_Married_F`) with canonical Mastvar codes. Pages now show e.g. "Bushels of turnips produced in the past year — 9,779" instead of "TUR BU = 9,779".

### What changed
- **Ingestion (`scripts/build_census_observations_v2.py`)**:
  - File-format filter at line ~441: reads only `*_CSD_*.xlsx` for years ≤1901 and only `*_PUB_*.xlsx` for 1911/1921. Previously read all formats indiscriminately, producing PUB↔CSD code duplicates and OCR multi-row-header artifacts.
  - Extended metadata-column filter at line ~267: added `CSD_TYPE`, `LINE_NO`, `PR_CD`, `NAME_COUNTY_<year>`, `NUMBER_CD_<year>`, plus a regex match for table-self-id columns (`V1T1_1911`, `V3T3_1921`, etc.).
  - Conditional `CSD_NO` row-skip at line ~304: only skip on `CSD_NO IS NULL` *if* the column exists. This skips the CD-level 1921 V3T3 Housing table without breaking 1851–1901 CSD-format files (which use TCPUID, not CSD_NO).
  - Pandas duplicate-column-suffix normalization in `normalize_column_name`: collapse `POP_FX_N.1` → `POP_FX_N` (these are duplicate xlsx columns with identical values; pandas auto-disambiguates).

- **Mastvar supplement**: `data/mastvar_supplement_1911_1921.csv` — 108 rows extending the 490-row Mastvar to cover 1911 V1T1/V1T2/V2T2/V2T7/V2T28 and 1921 V1T16/V1T27/V1T38/V3T3 PUB-format codes. Same schema as Mastvar (`Name | Description | Category | 1911 | 1921`).

- **Vocabulary loader (`scripts/build_census_observations.py:load_master_variables` and `scripts/build_census_observations_v2.py:load_master_variables`)**: both load `data/mastvar_supplement_1911_1921.csv` and merge with Mastvar (drop duplicates on Name, Mastvar wins).

- **Ladybug export (`scripts/export_kuzu_pilot.py`)**: VAR_MAP for `pop_total`/`pop_total_m`/`pop_total_f` updated to use CSD-format codes (`POP_XX_N`/`POP_MX_N`/`POP_FX_N`) for years 1851–1901. Previously used PUB-format `POP_TOT`/`POP_M`/`POP_F` which no longer exists for 1861/1881/1891/1901 after the format filter — caused empty `pop_total` for those years and silently dropped pages from generation.

### Numbers to know
| | Before A | After A |
|---|---|---|
| Distinct CensusVariable codes in Ladybug DB | 1389 | 598 |
| Synthesized labels (codes lacking Mastvar metadata) | ~900 | 0 |
| Total measurements | ~860K | 855,434 |
| Per-year orphan codes (sum across years) | 900 | 0 |
| Canonical pages on disk | ~29.5K w/ stale | 28,988 (zero stale) |

### Sensitive-term framing convention
The supplement encodes historic enumerator categories using the pattern:
> Persons recorded under the [year] official census category "<term>"; [modern interpretation]. [Period-context note when needed.]

User-confirmed phrasing ("official census term", not "enumerator term"). Examples: `INDIAN`, `NEGRO`, `HINDU`, `PAGANS`, `JEWISH`, `EUR_HEBREW` all carry this framing. `NEGRO` additionally carries explicit "Term is now considered offensive and is preserved here only as the historical source label."

### Known gotchas a fresh session must respect
1. **Format-filter coupling**: `build_census_observations_v2.py` and `export_kuzu_pilot.py` must agree on which xlsx column names exist per year. If you change one (e.g. add OCR-format reading), update VAR_MAP in the export accordingly.
2. **1921 V3T3 Housing is CD-level only** — its 9 codes (`T_/R_/U_*`) are in the supplement for documentation but are not ingested at CSD level. A future phase could add a CD-level ingestion path; for now they appear only in the e55 catalog.
3. **No Métis category exists in any digitized year** (1851–1921). TCP only digitized 1901 V1T7 (Population summary), not Origin tables. The 1911/1921 PUB Origin tables don't include Métis. **No ethnic data exists for 1901 at all** — don't try to fill this gap; the user has confirmed this is acceptable.
4. **e55_variable_types.csv is emitted by `scripts/build_census_observations.py`, not v2**. The v2 script only emits e16/e54/p2_has_type/etc. To re-emit e55 after a vocabulary change, run a small wrapper:
   ```python
   from scripts.build_census_observations import load_master_variables, create_variable_types
   from pathlib import Path
   df = load_master_variables('/tmp/hgis_docs/AggregateDocumentation/TCP_CANADA_CD-CSD_Mastvar.xlsx')
   create_variable_types(df, Path('neo4j_census_v2'))
   ```
5. **Sitemap has 471 duplicate `<loc>` entries** — minor cosmetic bug in `generate_rag_pages.py`. URLs are unique on disk; only the XML over-lists. Worth fixing but not blocking.
6. **Stale-slug page directories accumulate across runs** when canonical names change. Deletion strategy: parse `rag_site/sitemap.xml` for canonical URLs, walk `rag_site/places/` and `rag_site/cds/`, delete any directory whose path doesn't appear in the sitemap. Verified safe because canonical-prefix containment is checked (no canonical sub-path lives inside a stale dir).

---

## Phase B — Measurements section redesign + comparability/quality flags

### Why
Pages currently render measurements as 5 collapsible HTML tables grouped by Mastvar category. That's better than the pre-Phase-A code dump, but still suboptimal for RAG retrieval: tables chunk poorly, units are buried in column captions, and there's no signal for which variables are reliably comparable across years vs. one-off oddities.

### Goal
Replace the table-dump in `render_measurements_section` with category-grouped natural-language prose paragraphs that include units, source-table citations, and quality flags. Move sparse / one-off variables to a footnote.

### Target output shape
For each (presence, category) that has data, render one paragraph like:

> **Agriculture (1881).** This community's farmers reported 9,779 bushels of turnips, 6,326 bushels of oats, 6,031 bushels of spring wheat, 3,112 acres of hay (yielding 4,192 tons), and 363 bushels of barley. *(Source: 1881 Census of Canada, V3T24.)*

> **Population by marital status (1881).** 1,843 persons were unmarried (852 women, 991 men); 826 were married (413 of each); 97 were widowed (71 women, 26 men).

> **Dwellings (1881).** 464 inhabited houses, 17 uninhabited, 8 under construction; 472 occupied total. The enumerator also recorded 2 temporary shanties and 6 vessels used as dwellings.

Sparse/one-off codes (like `VAR_FISH_FX_Q` = 1 fascine fishing operation) collapsed into a footnote: *"The 1881 enumerator also recorded one fascine-fishing operation, 1 barrel of gaspereau, and 169 barrels of shad — single-county tallies of limited cross-year comparability."*

### Implementation

**Files to change**:
- `scripts/generate_rag_pages.py:718` — `render_measurements_section()`. Currently emits 5 `<details><table>` blocks per category. Rewrite to emit prose paragraphs.
- `scripts/generate_rag_pages.py:1111` — Cypher query for measurements. Currently returns `(category, label, fval, sval)`. Extend to return `(var_id, label, unit, category, subcategory, quality, comparable_across_years, value, source_table)`.
- `scripts/export_kuzu_pilot.py` — add `unit`, `quality`, `comparable_across_years`, `source_table` columns to the `census_variable.csv` and CensusVariable schema.
- `data/mastvar_supplement_1911_1921.csv` — add `Unit` column (currently lacks it). Mastvar has units inferred from `infer_unit()` heuristics; supplement should explicitly carry units to avoid heuristic gaps.

**New columns needed in the CensusVariable schema** (Ladybug):
- `unit` (e.g. `bushels`, `acres`, `persons`, `square_miles`)
- `quality` (`signal` | `sparse` | `derived`)
- `comparable_across_years` (boolean — true for stable demographic counts, false for one-off categories like `VAR_FISH_FX_Q`)
- `source_table` (e.g. `1881_V3T24`)

**Category-prose generators**: write one Python function per Mastvar category that takes a list of (label, unit, value) tuples and produces 1–3 sentences. Mirror the existing population-narrative pattern at `generate_rag_pages.py:912–924`.
- `render_pop_section()` — population, marital status, age structure
- `render_agr_section()` — crops, livestock
- `render_fsh_section()` — fisheries
- `render_bld_section()` — dwellings
- `render_mfg_section()` — manufacturing
- `render_eth_section()` — ethnic/origin
- `render_rel_section()` — religion
- `render_dth_section()` — deaths
- `render_age_section()` — age brackets

For sensitive-term entries (NEGRO, INDIAN, HINDU, etc.) the prose generator should preserve the supplement's full historical-context description rather than truncating to a label. Long descriptions are a feature, not a bug — they're what makes RAG retrieval accurate on these categories.

### Comparability/quality work (Track 4)
- Determine `comparable_across_years` per code: true when the same variable measures the same thing in ≥3 censuses; false otherwise. Most Mastvar codes that span multiple years should be `true`. Most 1911/1921 PUB-only codes should be `false` (the PUB tables are topically focused, not consistent population summaries).
- Generate `data/coverage_matrix.csv` (var × year × presence count) so anyone evaluating the dataset can see which codes are populated when.
- Add a per-page "Comparable across years" badge or note where the count of comparable codes is meaningful.
- Sparse codes (`quality=sparse`) hidden from main flow, surfaced in a footnote per category.

### Verification
- Render a sample of pages locally: `python scripts/generate_rag_pages.py --presence NS018012_1881 --out /tmp/preview` and read the output. Should be paragraphs, not tables. No raw codes.
- LLM benchmark: ask GPT-OSS-120B "What was the turnip harvest in NS018012 (Maitland) in 1881?" against (a) current page (pre-B), (b) Phase-B page. Phase-B should answer cleanly with citation.
- Sparse-variable handling: confirm `VAR_FISH_FX_Q = 1` for NS018012 1881 lives in a footnote, not the main flow.

---

## Phase C — Structured fact layer for RAG / LOD

### Why
HTML pages are designed for human reading + RAG retrieval. But programmatic consumers (other RAG pipelines, LINCS-style triplestores, Wikidata-aligned tooling) ingest more reliably from structured data than from HTML scraping. Phase C makes the site dual-purpose.

### Goal
Alongside the rendered HTML, emit:
1. Per-page JSON-LD enrichment with one `additionalProperty` per measurement
2. Site-wide `facts.jsonl` (one fact per line, full provenance)
3. Published variable vocabulary at `/vocab/variables.jsonl`

Each fact carries: subject URI, variable URI, label, unit, value, year, category, source-table citation, quality flag.

### Target artifacts

**a) Per-page JSON-LD enrichment.** Extend the existing `Place` JSON-LD (`generate_rag_pages.py:995`) with one `additionalProperty` per measurement:

```json
{
  "@type": "PropertyValue",
  "propertyID": "https://jimclifford.ca/hgiscanada/vocab/var/TUR_XX_B",
  "name": "Bushels of turnips produced in the past year",
  "value": 9779,
  "unitText": "bushel",
  "valueReference": {
    "@type": "DefinedTerm",
    "name": "Agriculture",
    "inDefinedTermSet": "https://jimclifford.ca/hgiscanada/vocab/category/AGR"
  },
  "citation": "1881 Census of Canada, V3T24"
}
```

**b) `facts.jsonl` at `/hgiscanada/facts.jsonl`** (one fact per line):
```jsonl
{"subject":"https://jimclifford.ca/hgiscanada/places/ns/maitland-ns018012-1881/","var":"VAR_TUR_XX_B","label":"Bushels of turnips produced in the past year","unit":"bushel","value":9779,"year":1881,"category":"AGR","source":"1881_V3T24","quality":"signal","comparable":true}
```

**c) `vocab/variables.jsonl` at `/hgiscanada/vocab/variables.jsonl`** — one row per CensusVariable, full canonical vocabulary as JSON-LD-friendly mappings.

### Implementation

**New script**: `scripts/emit_facts_jsonl.py`
- Reads from Ladybug DB (`pilot/on_kuzu/on.kuzu`)
- Walks all `(:Presence)-[:MEASURED_AT]->(:Measurement)-[:OF_VARIABLE]->(:CensusVariable)` triples
- Writes `rag_site/facts.jsonl` and `rag_site/vocab/variables.jsonl`
- Should run after `generate_rag_pages.py --all` so subject URIs match canonical page URLs

**Modify**: `scripts/generate_rag_pages.py:995` (JSON-LD scaffold) — add per-measurement `additionalProperty` array.

**Vocabulary URI minting**: use `https://jimclifford.ca/hgiscanada/vocab/var/<NAME>` per existing project URI convention (matches the GitHub-Pages page URL pattern documented in memory). The vocabulary doesn't need separate HTML pages per term in Phase C — just the JSONL index. Optional later step: emit per-variable HTML pages so URIs dereference, and migrate to w3id.org.

### LINCS alignment check before building Track 3
Before writing `emit_facts_jsonl.py`, consult the `lincs-profile` skill to see if LINCS already recommends a pattern for emitting per-measurement structured data alongside CIDOC-CRM. The site already produces a CIDOC-CRM Turtle export via `scripts/export_rdf.py` — Phase C should align with that representation rather than diverge. If LINCS has no recommendation, we're inventing; document the rationale in the new script.

### Verification
- `curl https://jimclifford.ca/hgiscanada/facts.jsonl | head -100 | jq` — valid JSONL, full provenance per row.
- Schema.org structured-data testing tool — JSON-LD validates without warnings.
- Demo retrieval: small standalone script that consumes `facts.jsonl` and answers "top 10 turnip-producing CSDs in 1881" without HTML parsing.

---

## Decisions already made (don't re-litigate)

- **Scope**: ship through Phase C. Phased, but the destination is full structured-fact-layer.
- **Provenance granularity**: per-table citation only (e.g., `1881_V3T24`). No per-page-number provenance — too costly.
- **Unknown-code resolution**: decoder rules first, PDF cross-reference second, ask user third. The supplement is now exhaustive for 1911/1921; this rule applies if more codes appear.
- **Sensitive-term framing**: "official census term" not "enumerator term". Keep historical codes verbatim (essential for source traceability); contextualize in description.
- **Métis / 1901 ethnic data**: skip. No data exists, no need to caveat. (User-confirmed 2026-04-27.)

---

## Critical files reference

| Path | Purpose |
|---|---|
| `scripts/build_census_observations_v2.py` | CIDOC-CRM v2 measurement ingestion. Phase B may need to attach `unit`/`source_table` to e16 emissions. |
| `scripts/build_census_observations.py` | Emits `e55_variable_types.csv`. Phase B updates schema. |
| `scripts/export_kuzu_pilot.py` | Builds Ladybug DB from CIDOC-CRM CSVs. Phase B extends CensusVariable schema. |
| `scripts/generate_rag_pages.py:718` | `render_measurements_section()` — Phase B rewrites this. |
| `scripts/generate_rag_pages.py:995` | JSON-LD scaffold — Phase C extends. |
| `scripts/generate_rag_pages.py:1111` | Cypher query for measurements — Phase B extends. |
| `data/mastvar_supplement_1911_1921.csv` | 108-row Mastvar extension. Phase B adds Unit column. |
| `neo4j_census_v2/e55_variable_types.csv` | 598-row variable catalog. Regenerated when supplement changes. |
| `pilot/on_kuzu/on.kuzu` | Ladybug DB. Rebuilt by `export_kuzu_pilot.py`. |
| `rag_site/` | Generated HTML output. Synced to `~/hgiscanada/`. |
| `~/hgiscanada/` | Separate git repo for the published site (jburnford/hgiscanada). |

## Source data references

- TCP/LPC Aggregate Documentation: <https://hgiscanada.usask.ca/sites/canadianhistoricalcensus.usask.ca/files/2023-12/AggregateDocumentation.zip>
- Mastvar canonical: `/tmp/hgis_docs/AggregateDocumentation/TCP_CANADA_CD-CSD_Mastvar.xlsx` (md5 matches the 1861 directory copy)
- Year-table xlsx files: `/home/jic823/GraphRAG_test/<year>/` or `<year>Tables/`
- GDB: `/home/jic823/GraphRAG_test/TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306.gdb`

## Reference run commands

```bash
# Re-emit e55 after vocabulary changes
python3 -c "
import sys; sys.path.insert(0, 'scripts')
from build_census_observations import load_master_variables, create_variable_types
from pathlib import Path
df = load_master_variables('/tmp/hgis_docs/AggregateDocumentation/TCP_CANADA_CD-CSD_Mastvar.xlsx')
create_variable_types(df, Path('neo4j_census_v2'))
"

# Re-run v2 ingestion (all years)
python3 scripts/build_census_observations_v2.py \
  --mastvar /tmp/hgis_docs/AggregateDocumentation/TCP_CANADA_CD-CSD_Mastvar.xlsx \
  --gdb /home/jic823/GraphRAG_test/TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306.gdb \
  --tables-dir /home/jic823/GraphRAG_test \
  --years 1851,1861,1871,1881,1891,1901,1911,1921 \
  --out neo4j_census_v2

# Rebuild Ladybug
python3 scripts/export_kuzu_pilot.py

# Regenerate site
python3 scripts/generate_rag_pages.py --all

# Stale-page cleanup (after generate)
python3 -c "
import re, shutil
from pathlib import Path
sitemap = Path('rag_site/sitemap.xml').read_text()
canon = {u[len('https://jimclifford.ca/hgiscanada'):].strip('/')
         for u in re.findall(r'<loc>([^<]+)</loc>', sitemap)
         if u.startswith('https://jimclifford.ca/hgiscanada')}
for sub in ('places', 'cds'):
    root = Path('rag_site') / sub
    if not root.exists(): continue
    for f in root.rglob('index.html'):
        rel = str(f.parent.relative_to('rag_site'))
        if rel not in canon:
            shutil.rmtree(f.parent)
"
```
