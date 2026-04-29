# Adding Census Divisions to the HGIS Canada Knowledge Graph

Bootstrap notes for a fresh session. Written 2026-04-25 after v9.3 shipped (CSD layer is now mature; CDs are the obvious next gap).

## Where things stand (post-v9.3)

The static site at jimclifford.ca/hgiscanada and the Kuzu / RDF projections cover **Census Subdivisions (CSDs)** end-to-end:
- 8,749 persistent CSD chains across 1851–1921
- Split-aware chain construction with first-class ancestor chains
- 3,694 Wikidata-grounded; 5,055 minted URIs (page URLs); 100% identifier coverage
- ~28,900 pages rendered, sitemap submitted to Google
- Indian Reserve handling kept generic per OCAP considerations

**Census Divisions (CDs) — the parent counties/districts that contain CSDs — are partially modeled but not first-class:**
- `neo4j_cidoc_crm_v2/e53_place_cd.csv` has 579 CD nodes (year-scoped, not chained)
- Kuzu `Place` table includes them (`place_type='CD'`)
- `PART_OF_COUNTY` rel links each CSD-presence to its CD
- **No CD-level pages render** (page generator filters to `place_type='CSD'`)
- **No CD chains** (no year-to-year persistent identity)
- **No CD Wikidata grounding** (the disambig pipeline is CSD-only)
- **No CD-level census aggregates surfaced** (V1T1 CD-aggregate rows with `CSD_NO=0` are explicitly filtered out)

## Why CDs matter

Counties / census districts are the natural mid-level navigational unit between province and CSD. Most users browsing 1881 Pictou County, Nova Scotia want a CD page that lists all the CSDs in it that year, with aggregate population, a map, and Wikidata link. Today they have to bounce through the province index. A LINCS / Track-A consumer also needs CD-level entities to model `crm:P89_falls_within` properly across the geographic hierarchy.

## What's already in the data

GDB attributes per year layer (verified against `CANADA_1921_CSD`):
- `TCPUID_CSD_<year>` — CSD-level ID (what we use today)
- `NAME_CSD_<year>` — CSD name
- `NAME_CD_<year>` — CD name (the parent district), e.g. "Hants", "Halifax", "Saskatoon"
- `PR_<year>` — province

There's no `TCPUID_CD_<year>` field — CD identity is currently inferred from a NAME_CD + PR pair. The cidoc builder mints CD place_ids deterministically (likely something like `CD_<prov>_<cd_no>` derived from the CSD TCPUID prefix; check `scripts/build_neo4j_cidoc_crm_v2.py`).

V1T1 census Excel files include CD-aggregate rows with `CSD_NO=0` and `PR_CD_CSD` = just the CD name (e.g. row `SK216000` "Saskatoon", pop 51,145 = whole CD). These rows are currently discarded by `build_census_observations_v2.py` to avoid double-counting if naively summed with CSD rows.

## Suggested phasing

### Phase 1 — chain CDs across years
- New script `scripts/build_persistent_cds.py` (or extend `build_persistent_places.py`).
- CD boundaries are more stable than CSD boundaries (counties don't split as often), but they DO change — Saskatchewan was carved out of NWT, new districts created, etc.
- Spatial overlap chain construction analogous to CSD chains; lower threshold likely fine since polygons are larger.
- Output: `persistent_cds_output/` with `persistent_cd_registry.csv` and `tcpuid_year_to_cd.csv`.
- Verify: Pictou County NS chains 1851–1921 as a single persistent CD; Saskatchewan CDs created 1905 don't appear before that.

### Phase 2 — Wikidata grounding for CDs
- Most counties / census districts have stable Wikidata entries (Q-numbers like Q1428562 for Pictou County). Add a CD disambiguation queue parallel to the CSD one.
- Reuse `scripts/csd-disambig` skill / MCP search workflow but target the CD registry.
- ~579 entities total; should drain in a single batch.

### Phase 3 — CD pages on the static site
- URL pattern proposal: `/cds/<prov>/<cd-slug>-<cd-id>/` (separate namespace from `/places/` to avoid slug collisions).
- Per-CD index page: list of all CSDs in this CD by year, aggregate population trajectory, Wikidata link, ancestor/descendant CDs.
- Per-CD-year page (one per (CD, year)): list of CSDs in this CD that year, neighbour CDs (other CDs sharing a border).
- Province index pages add a "Census Divisions" section above the CSD list.
- CSD pages add a "Part of: [CD link]" line in the metadata.

### Phase 4 — CD-level census aggregates
- Re-include V1T1 `CSD_NO=0` rows but route them to CD measurements, not CSD.
- Or compute aggregates by summing CSD measurements per CD per year (more derivable, less cluttered).
- Either way: every CD-year has a `pop_total`, `pop_total_m`, `pop_total_f`, `area_sqm`.
- Render in the CD page like CSD pages render their own measurements.

### Phase 5 — RDF + URI integration
- CDs get the same minted-URI treatment as CSDs: `https://jimclifford.ca/hgiscanada/cds/<prov>/<slug>-<id>/`.
- `e53_place_uri.csv` already has the structure; just needs CD entries populated by the parallel join script.
- Both RDF projections (`export_rdf.py`, `export_rdf_lite.py`) already iterate over E53_Place — they'll pick up CDs automatically once Place entries have URIs.
- Add `crm:P89_falls_within` triples from each CSD presence to its CD presence (same year).

## Critical files

| Path | Role |
|---|---|
| `scripts/build_neo4j_cidoc_crm_v2.py` | Already produces `e53_place_cd.csv` (579 CD nodes). Read first to understand current CD identity model. |
| `scripts/build_persistent_places.py` | Reference for chain construction; pattern to mirror for CDs. |
| `scripts/csd_name_normalize.py` | Reuse `_aggressive_base_normalize`, `grouping_key`, `is_indian_reserve` helpers. |
| `scripts/generate_rag_pages.py` | Filters to `place_type='CSD'` today; needs CD rendering paths added. |
| `scripts/join_wikidata_to_places.py` | URI assignment for CSDs; mirror for CDs (separate JSONL grounding file). |
| `scripts/build_census_observations_v2.py` | Currently filters out CD-aggregate rows (`_is_zero(CSD_NO)`); revisit for CD measurements. |
| `wikidata_grounding/csd_verified_matches.jsonl` | CSD pattern; create `cd_verified_matches.jsonl` parallel. |
| `persistent_places_output/` | CSD chain outputs; create `persistent_cds_output/` parallel. |
| TCP GDB at `/home/jic823/GraphRAG_test/TCP_CANADA_CSD_202306/...gdb` | Source. CD names live in `NAME_CD_<year>` columns. |

## Open design questions

1. **CD identity across years**: do we mint `PLACE_CD_<prov>_<name_canonical>` (name-stable) or `PLACE_CD_<prov>_<earliest_tcpuid_prefix>` (deterministic but less semantic)? Current cidoc builder picks something — check first.
2. **CD URL namespace**: `/cds/` vs `/places/<prov>/cd-<slug>/` vs `/counties/`. The first is cleanest semantically; the second avoids any new top-level path. Probably `/cds/`.
3. **Splits / merges for CDs**: do counties experience the same kind of splits as CSDs? (Saskatoon CD splitting in 1921, etc.) If yes, reuse the 1-to-N split detection from `build_persistent_places.py`. If rare enough, simpler chain rules suffice.
4. **CD-aggregate vs sum-of-CSDs**: where the V1T1 CD row exists, prefer it (authoritative published total) or always sum (consistency)? Compare values for a few cases — if they match, sum is fine.
5. **NWT predecessor problem**: pre-1905 prairie CDs are NWT districts; they later became AB/SK CDs. Are these the same persistent CD or a new one each time? Probably "transformed into" via lineage edges, not chained.

## Memory worth re-checking before starting

Already saved in `~/.claude/projects/-home-jic823-Canada-History-Knowledge-Graph/memory/`:
- `project_three_outputs_one_source.md` — Kuzu source-of-truth, RDF + RAG pages derived
- `project_canonical_grounding_year_1921.md` — 1921 is canonical for grounding/URI minting
- `project_uri_minting_github_pages.md` — URI scheme decision (jimclifford.ca/hgiscanada page URLs)
- `project_grounding_scope_persistent_places.md` — grounding is per persistent place, not per (TCPUID, year)
- `feedback_grounding_status_source.md` — `csd_verified_matches.jsonl` is the truth, not the queue
- `feedback_kuzu_strict_typing.md` — Kuzu DDL typing rules
- `feedback_pid_preservation.md` — never collapse Wikidata/GeoNames IDs to bare strings

## Refresh workflow (after CD changes land)

Same as v9.3:
```bash
cd ~/Canada-History-Knowledge-Graph
python3 scripts/build_persistent_places.py --audit          # CSD chains
python3 scripts/build_persistent_cds.py --audit             # NEW: CD chains
conda run -n geo python3 scripts/build_neo4j_cidoc_crm_v2.py --gdb /home/jic823/GraphRAG_test/TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306.gdb --out neo4j_cidoc_crm_v2
python3 scripts/join_wikidata_to_places.py                  # CSD + CD URI minting
python3 scripts/export_kuzu_pilot.py
python3 scripts/export_rdf.py --pilot on_1851_1921
python3 scripts/export_rdf_lite.py
python3 scripts/generate_rag_pages.py --all                 # now also renders /cds/...
# sync ~/Canada-History-Knowledge-Graph/rag_site → ~/hgiscanada
cd ~/hgiscanada && git add -A && git commit -m "..." && git push
```

## Quick sanity command

To see what CDs exist today and how they're keyed:

```bash
head -5 ~/Canada-History-Knowledge-Graph/neo4j_cidoc_crm_v2/e53_place_cd.csv
wc -l ~/Canada-History-Knowledge-Graph/neo4j_cidoc_crm_v2/e53_place_cd.csv
```

That's the starting point. From there, decide on chain identity (Phase 1) and the rest cascades naturally.
