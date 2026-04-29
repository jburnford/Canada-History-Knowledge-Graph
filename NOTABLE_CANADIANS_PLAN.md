# Notable Canadians — Plan

**Status as of 2026-04-27**: design only. No code written yet. Phase A through C of the RAG optimization plan are shipped and live (see `RAG_OPTIMIZATION_PLAN.md` for those conventions); this is the next major feature.

## Context

`hgiscanada` currently renders place-and-period prose (population, agriculture, industry, …) with sources and structured-fact links. It says nothing about the **people** associated with each Census Subdivision. Adding a "Notable Canadians associated with this place" section would give readers (and RAG retrieval) immediate access to the human history of each CSD, with deep links to the Dictionary of Canadian Biography (DCB) for further reading and to Wikidata for graph traversal.

The Phase B+C work that just shipped (prose paragraphs + JSON-LD + per-year `facts.jsonl`) made `hgiscanada` itself a structured-data citizen of the linked-open-data web. Joining LINCS-side person data into this dataset is now mostly graph plumbing rather than schema-fitting, which is what makes this feature tractable.

Source: the LINCS Historical Canadians dataset (`hist-cdns`), modeled in CIDOC-CRM. **The Dictionary of Canadian Biography is the upstream source for hist-cdns**: each LINCS person URI corresponds to a person extracted from a DCB biographical article (typed as `crm:E33_Linguistic_Object`). Names + dates + relationships in LINCS were derived from DCB's structured biographies and then enriched with Wikidata / VIAF / GeoNames cross-references. The DOI dataset is published at <https://doi.org/10.5683/SP3/7ESLQ0>; the LINCS application profile is at <https://lincsproject.ca/docs/explore-lod/project-datasets/hist-cdns/hist-cdns-application-profile>.

A local copy already exists on this machine — the SPARQL endpoint is not on the critical path for ingestion.

---

## Data sources (already on disk)

| Path | Size | Role |
|---|---|---|
| `/home/jic823/CanadaNeo4j/LINCsDATA/hist-cdns.ttl` | 195 MB | Full Turtle dump, 3.34M triples, 25,596 persons (14,049 with data). Source of truth for occupations + DCB cross-references. |
| `/home/jic823/CanadaNeo4j/lincs_historical_canadians.json` | 12 MB | Pre-parsed JSON: name, ids (lincs/viaf/wd), birthEvent + deathEvent with GeoNames place IDs and ISO date ranges, parents, spouse. **Missing**: occupations (parser bug), DCB URLs. |
| `/home/jic823/CanadaNeo4j/lincs_historical_canadians_deduped.json` | 13 MB | Deduped variant — confirm dedup logic before using. |

**DCB embedding pattern in TTL** (verified by direct grep against `hist-cdns.ttl`):

```
<http://www.biographi.ca/en/bio/glasier_beamsley_perkins_4E.html> crm:P129_is_about lincs:… .
<http://www.biographi.ca/en/bio/brymer_alexander_6E.html>          crm:P129_is_about wd:Q26243087 .
<http://www.biographi.ca/en/bio/la_salle_nicolas_de_2E.html>       crm:P129_is_about viaf:104483491 .
<http://www.biographi.ca/en/bio/mccrae_john_14E.html>              crm:P129_is_about viaf:20600031 .
```

Each DCB URL is the URI of an `E33_Linguistic_Object` (also typed `crmdig:D1_Digital_Object`). The biography's subject is the object of `crm:P129_is_about`. Person URIs come in three flavors:

- `lincs:<id>` — LINCS-minted (the most common)
- `wd:Q…`     — when LINCS already aligned to Wikidata
- `viaf:<id>` — when LINCS already aligned to VIAF

**Total DCB articles in the TTL: 8,796 distinct `E33_Linguistic_Object` URIs.** This is the canonical "people with a DCB bio" pool. Other persons are extracted from DCB articles as mentioned associates / relatives but don't have their own bio.

---

## Cohort scoping

User-confirmed date filter: skip pre-1800 and pre-1850-death persons; CSD pages cover 1851–1921 so people whose lives wrapped before that window aren't relevant.

**Death-year distribution from the local JSON:**
| Bucket | Count | Action |
|---|---|---|
| pre-1800 | 1,649 | Skip |
| 1800–1849 | 1,517 | Skip |
| **1850–1899** | **3,002** | Keep |
| **1900–1949** | **2,809** | Keep |
| 1950+ | 95 | Keep (born ~1880s) |
| no death date | 4,977 | Keep IF birth year ≥ 1800 OR any event ≥ 1850 |

**Final relevant cohort** (rough estimate): ~5,900 persons with death in window + ~3,000 from the no-death-date bucket who are in-period via birth → **~8,000–9,000 candidates**.

Practical date rule for the linker:
```
keep_person(p) :=
  death_year(p) ≥ 1850
  OR (death_year is None AND birth_year ≥ 1800)
  OR any_event_year(p) ≥ 1850
```

---

## Place-matching strategy

Three matching paths, run in priority order. Each LINCS person→event becomes 0..N (CSD, year) candidate links.

### Strategy 1 — Wikidata QID match (precise, decent recall)
For LINCS persons that carry `wikidataQid`: lookup their Wikidata `P19` (place of birth) / `P20` (place of death) / `P119` (place of burial). If those QIDs are equal to a CSD's `wikidata_qid` in our Ladybug DB → direct match. **Our place coverage**: 3,986 of 9,279 places (43%) carry a Wikidata QID — including 3,693 of 8,749 CSDs (42%).
- **Pro**: zero spatial work, high precision.
- **Con**: only 22% of LINCS persons have a Wikidata QID, and many Wikidata place QIDs are coarser than a CSD ("Toronto" matches but "Mossley township" probably doesn't). Mitigation: in Strategy 1, require the matched Wikidata place to ALSO appear as a CSD-level (not CD or province) entity in our DB.
- **Cost**: ~3,100 person × ~3 properties = ~9,300 Wikidata queries. Behind the MCP rate-limit (≤5/s) that's ~30 minutes; cache aggressively.
- **MCP tools**: use `mcp__wikidata__get_statements` for per-person P19/P20/P119 lookup (single-entity, returns all P-values). For batch filter-by-property work, use `mcp__wikidata__execute_sparql`.

### Strategy 2 — GeoNames ID match (DROPPED)
**Verified 0% coverage**: zero of our 9,279 places have a populated `geonames_id`. (An earlier scout report incorrectly counted 1,575 — this was wrong.) GeoNames-on-GeoNames matching is unavailable. We always go through coordinates instead — see Strategy 3.

### Strategy 3 — Point-in-polygon (high recall, the workhorse)
For every LINCS event with a GeoNames place: resolve GeoNames id → (lat, lon), then test which CSD polygon contains that point in the relevant census year.

- **GeoNames coordinate cache**: 2,804 distinct GeoNames IDs across all events. One-time enrichment via the GeoNames "allCountries.txt" dump (~13 GB compressed, but we only need 2,804 lookups → trivial). Output: `data/geonames_coords.csv` (id, lat, lon, name, country, feature_class).
- **Polygon source**: `TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306.gdb` — the same .gdb already used by `scripts/link_csd_years_spatial_v2.py`. Year-keyed layers exist for 1851 through 1921.
- **Spatial index**: `geopandas.sjoin` with `rtree`, in the `geo` conda env that's already standard for this repo. Activate via `conda activate geo` before running spatial scripts.
- **Year resolution**: for an event in year Y, match against the polygons of the closest census year (e.g., event in 1875 → match against 1871 polygons). For per-year-page rendering, expand with a **±20-year lifespan buffer**: a person whose lifespan covers years Y₁..Y₂ surfaces on every census-year page in [Y₁, Y₂] for any CSD where any of their events landed.
- **Persistent-place lineage handling**: if a CSD splits/merges across years (per `cd_lineage.csv` and SAME_AS chains in the spatial-link CSVs), a person bound to one boundary form should ALSO surface on aggregate pages of the other forms in the same chain. Use the existing place→chain lookup that `generate_rag_pages.py` already maintains (`_CD_CHAIN_BY_RAW_YEAR`).

### Combination rule
A (person, CSD, year) link is emitted if **any** strategy fires. Strategy 3 is the dominant recall path; 1 and 2 are precision boosts and sanity checks.

Final per-person → places artifact: `data/lincs_person_csd_links.csv`
```
person_id, name, wikidata_qid, viaf_id, dcb_url,
event_type (birth|death|occupation),
event_year, event_year_begin, event_year_end,
csd_tcpuid, csd_year,
match_strategy (wd|gn|pip), confidence
```

---

## DCB linking

DCB is the source of the dataset, not just a sameAs supplement — every LINCS person traces back to one or more DCB articles. There are **8,796 distinct biographi.ca URLs** in the TTL, all typed `crm:E33_Linguistic_Object` (and `crmdig:D1_Digital_Object`). The link from a DCB article to the person it covers uses `crm:P129_is_about` (LINCS Pattern 6 — Subject).

**Extraction (run once on the local TTL with `rdflib`)**:
```sparql
SELECT ?person ?dcb_url ?label_en ?label_fr WHERE {
  ?dcb_url a crm:E33_Linguistic_Object ;
           crm:P129_is_about ?person .
  OPTIONAL { ?dcb_url rdfs:label ?label_en FILTER(LANG(?label_en) = "en") }
  OPTIONAL { ?dcb_url rdfs:label ?label_fr FILTER(LANG(?label_fr) = "fr") }
  FILTER(STRSTARTS(STR(?dcb_url), "http://www.biographi.ca/"))
}
```
Output: `data/lincs_dcb_links.csv` (person_uri, dcb_url, dcb_label_en, dcb_label_fr).

A person may have ≤1 DCB URL as a subject. Persons referenced in another DCB article (associates, relatives) connect via `oa:hasSource` on a different chain — those are mentions, not the canonical bio. Skip mention-only links for the page render; they're noise.

**Page rendering**: each name in the prose links to `<a href="<dcb_url>">Name</a>`. If a person has no DCB URL but has Wikidata, fall back to the Wikidata link. If neither: plain text. (Persons without a DCB bio AND without Wikidata are likely too obscure to surface — consider filtering them out entirely.)

**Volume note**: DCB volumes are numbered (`_12E.html`, `_14E.html`, etc.) — the volume corresponds to a death-decade window. Useful as a sanity check against the date filter.

---

## Page rendering design

### Per-CSD-year page (the 28K HTML pages)
Slot a new prose section after `measurements_section` in `PAGE_TEMPLATE` (`scripts/generate_rag_pages.py:219`). Match the prose tone of Phase B:

> **Notable Canadians (1881).** This community is associated with the lives of [John A. Macdonald](http://www.biographi.ca/en/bio/macdonald_john_alexander_12E.html) (1815–1891, born here), [George Brown](http://www.biographi.ca/en/bio/brown_george_10E.html) (1818–1880, died here), and 4 others — see this place's [aggregate page](…) for the full list.

**Cap**: top-N per page by some signal (DCB volume coverage as proxy for prominence, or just death-year-ordered). N=5 keeps prose tight; full list lives on the per-place aggregate page.

**Selection rule for which year-page a person appears on**:
- Birth event → person appears on (CSD, birth_year_round_to_census)
- Death event → person appears on (CSD, death_year_round_to_census)
- Otherwise → all year-pages where their lifespan overlaps the census year

### Per-CSD aggregate (place index) page
A "Notable Canadians ever associated with [Place]" section listing all linked persons sorted by death year (ascending). DCB link + dates + birth/death/lived flag.

### JSON-LD enrichment (Phase C alignment)
Extend the page JSON-LD with a `subjectOf.about` array (Schema.org `Person`) for the top-N notable people, each with `sameAs` to DCB + Wikidata. Keeps RAG / search-engine consumers in the loop without parsing prose.

---

## Implementation sketch

**Scope**: all 12 provinces, matching the Phase B + C deploy. Not ON-pilot-only.

**File-line references** below (e.g. `generate_rag_pages.py:219`) are approximate and will drift as the file is edited. Grep for the named functions/templates (`PAGE_TEMPLATE`, `prefetch_all_data`, `render_measurements_section`) to find the current line numbers.

Phased, each phase shippable on its own:

### D1 — Person/place linker (no rendering yet)
| Step | File | Output |
|---|---|---|
| Parse TTL for occupations + DCB URLs | `scripts/parse_lincs_persons.py` (new) | `data/lincs_persons.json` (re-parsed, occupations populated, DCB URLs attached) |
| Build GeoNames coords cache | `scripts/build_geonames_cache.py` (new) | `data/geonames_coords.csv` (~2,804 rows) |
| Wikidata batch lookup for P19/P20/P119 | `scripts/lincs_wd_birthdeath.py` (new) | `data/lincs_wd_birthdeath.csv` |
| Spatial join (Strategy 3) + apply Strategy 1 | `scripts/link_lincs_to_csd.py` (new) | `data/lincs_person_csd_links.csv` |

**RAM hint for the parser**: loading the 195 MB TTL with `rdflib.Graph().parse()` peaks around 4–6 GB RAM. Streaming alternatives if RAM is tight: `pyoxigraph` (faster, lower memory) or `rdflib.parser.NTriplesParser` line-by-line after a one-time TTL→NT conversion.

**Person URI normalization rule** (decides the PK in the eventual `Person` node table):
- Prefer `lincs:<id>` as the canonical `person_id` PK
- Fall back to `wd:Q…` if the person has no LINCS-minted URI
- Fall back to `viaf:<id>` if neither LINCS nor Wikidata is available
- Always store all three flavors as separate columns (`lincs_id`, `wikidata_qid`, `viaf_id`) regardless of which was chosen as PK, so cross-reference queries work either way

**Acceptance — spot-check these specific persons end-to-end** (name → expected birth-CSD / death-CSD):
- Sir John A. Macdonald (Q156155) — born Glasgow (out-of-Canada); died Ottawa
- Sir Wilfrid Laurier (Q102935) — born Saint-Lin, QC; died Ottawa, ON
- Louis Riel (Q360504) — born Saint-Boniface, MB; died Regina, SK
- Pauline Johnson / Tekahionwake (Q444196) — born Six Nations of the Grand River; died Vancouver
- Emily Carr (Q241646) — born Victoria, BC; died Victoria, BC
- Robertson Davies (Q377137) — born Thamesville, ON; died too late (1995, out of cohort) — should be filtered out by date rule, not surfaced
- Sir Sandford Fleming (Q453415) — Halifax → Halifax
- Sitting Bull (Q186522) — relevant for SK cross-border-period coverage

Each spot-check should show the person bound to the expected CSD page in the year-aligned closest census, with a working DCB link.

### D2 — Schema extension (Ladybug)

**Edge model (decided)**: typed-event edges land on Presence (the year-resolved subject); aggregate associations land on Place. Both ship — they serve different page types.

- `BORN_IN_PRESENCE` (Person → Presence): a person's birth is a *specific event in a specific census-year polygon*, so the year-resolved Presence is the canonical subject. One edge per person where birth event maps to a CSD-year. Drives per-year-page rendering.
- `DIED_IN_PRESENCE` (Person → Presence): same shape for death.
- `ASSOCIATED_WITH_PLACE` (Person → Place): aggregate edge for the persistent-place page — true for any year of the person's lifespan that overlaps a Presence of the place. Derived from the typed edges + lifespan-overlap rule, not a source-of-truth edge. Drives per-Place aggregate page rendering.

**Person node table**:
```
Person {
  person_id     STRING PK,    // canonical: lincs: > wd: > viaf:
  name          STRING,
  lincs_id      STRING,       // when person_id is lincs:, mirror here for symmetry
  wikidata_qid  STRING,
  viaf_id       STRING,
  dcb_url       STRING,
  birth_year    INT64,        // from dateBegin year, may be NULL
  death_year    INT64,        // from dateBegin year, may be NULL
  occupations   STRING        // pipe-separated; full list in lincs_persons.json
}
```

Update `scripts/export_kuzu_pilot.py` to load `data/lincs_person_csd_links.csv` into these new tables. The loader should accept the same all-12-provinces scope as the existing measurements load.

### D3 — Render
- Add `prefetch_persons_by_presence` to `prefetch_all_data` in `scripts/generate_rag_pages.py` (find via `grep "def prefetch_all_data"`)
- Write `render_notable_people_section()` mirroring the prose tone of `render_measurements_section`
- Slot into `PAGE_TEMPLATE` between `measurements_section` and the closing footer
- Add an aggregate "people ever associated with this place" section to `PLACE_PAGE_TEMPLATE`
- Extend the JSON-LD scaffold (find via `grep "Schema.org JSON-LD"`) with a Person sub-graph for crawlers — top-N notable people as `Schema.org Person` entries with `sameAs` to DCB + Wikidata.

#### Publish flow (after D3 regenerates pages)

The generated `rag_site/` is local staging. The live site is served from a separate publish repo at `~/hgiscanada/` (jburnford/hgiscanada on GitHub Pages, branch **`main`** — NOT master). Steps:

```bash
# 1. Mirror, preserving the publish-repo metadata files
rsync -av --delete \
  --exclude='.git/' \
  --exclude='README.md' \
  --exclude='google*.html' \
  /home/jic823/Canada-History-Knowledge-Graph/rag_site/ \
  /home/jic823/hgiscanada/

# 2. Review changes
git -C /home/jic823/hgiscanada status --short | head -20

# 3. Commit using the v10.X version-bump convention (latest published was v10.0)
git -C /home/jic823/hgiscanada add -A
git -C /home/jic823/hgiscanada commit -m "v10.X: <description>"

# 4. Push (BRANCH IS main, NOT master)
git -C /home/jic823/hgiscanada push origin main
```

GitHub Pages rebuild typically completes in 60–120 seconds. Verify with `curl -s https://jimclifford.ca/hgiscanada/places/<prov>/<slug>/` and grep for the new prose.

### D4 — Polish + alignment
- Re-emit `rag_site/facts/<year>.jsonl` with person-fact rows? (probably no — facts file is for measurements; persons may want a sibling `rag_site/persons/<year>.jsonl`)
- LINCS-side validation: each person URI in our output is dereferenceable via `lincs:` prefix
- Consider RDF export: a `lincs_links.ttl` sidecar for the existing `rdf_export/` flow

---

## Open questions to resolve before D1

1. ~~**TTL re-parse vs JSON**~~: **DECIDED 2026-04-27** — re-parse the full TTL with `rdflib`. The existing JSON has zero occupations and no DCB URLs; a 2–3 minute one-time load is the cleaner path than patching the partial parser. Output replaces `lincs_historical_canadians.json` with a self-sufficient `data/lincs_persons.json`.
2. **GeoNames coord source**: download `allCountries.txt` (large) vs use a GeoNames API key (free tier rate-limited). 2,804 IDs is small enough to use the API, but the dump is more reproducible. **Recommend**: API for first pass, switch to dump if API rate-limit becomes annoying.
3. **Non-DCB persons**: ~30%+ of LINCS persons may have no DCB article. Do we still surface them, or DCB-only? **Recommend**: surface all relevant-cohort persons; DCB link is optional (Wikidata fallback, plain text otherwise).
4. **Coarse-grained Wikidata place matches**: Strategy 1 might match P19 = "Quebec" (the province) for thousands of persons → noise. **Recommend**: in Strategy 1, require the matched Wikidata place to ALSO appear as a CSD-level (not CD or higher) entity in our DB.
5. **Disambiguation between same-name persons**: LINCS uses VIAF/Wikidata to disambiguate, but if our deduped JSON merged two distinct people we'd inherit the bug. **Recommend**: cross-check against the deduped variant only after spot-checking.
6. **Occupations rendering**: occupations make the prose much richer ("politician John A. Macdonald (1815–1891)") but require the TTL re-parse to be done first. **Recommend**: ship D1–D3 with names + dates + DCB only; occupations as a D4 polish.

---

## Verification plan

After D3 ships:
- Spot-check 10 famous Canadians (one per province) — birth/death CSD-year pages should mention them with correct DCB link.
- Spot-check 5 obscure persons — confirm Strategy 3 (point-in-polygon) finds rural birthplaces correctly.
- LLM benchmark: ask GPT against the page "who is John A. Macdonald and where was he from?" — answer should cite the DCB link from the page.
- Cross-page coherence: a person born in CSD A 1815 and died in CSD B 1891 should appear on A 1851 and B 1891 pages, with appropriate framing.

---

## Critical files reference

| Path | Role |
|---|---|
| `/home/jic823/CanadaNeo4j/LINCsDATA/hist-cdns.ttl` | TTL source (re-parse for occupations + DCB URLs) |
| `/home/jic823/CanadaNeo4j/lincs_historical_canadians.json` | JSON sample of the parsed data shape |
| `TCP_CANADA_CSD_202306/.../TCP_CANADA_CSD_202306.gdb` | Polygon source for point-in-polygon |
| `pilot/on_kuzu/on.kuzu` | Ladybug DB to extend (D2) |
| `scripts/generate_rag_pages.py:219` | PAGE_TEMPLATE — slot for new section |
| `scripts/generate_rag_pages.py:1258` | prefetch_all_data — extend for persons |
| `scripts/export_kuzu_pilot.py` | Schema extension + loader |
| `data/lincs_person_csd_links.csv` | Linker output (new artifact) |
| `data/geonames_coords.csv` | GeoNames coord cache (new artifact) |

---

**Last updated**: 2026-04-27
