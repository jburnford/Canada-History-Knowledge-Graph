# Phase C Status — Per-Presence Wikidata Grounding

**Status**: Complete. 4,431/4,431 queue chains processed across 42 batches.
**Verify gate**: 833 good, 6 expected FAR warnings, **0 bad**.

## Pipeline context

Three-phase grounding for the per-presence model:

1. **Phase A** (`build_presence_inheritance.py`) — pure-Python inheritance from
   spatial year-links + tier_root+province name match. Grounded ~580 chains.
2. **Phase B** (`verify_inherited_grounding.py`) — REST verify of Phase A's
   QIDs against P31/P131/P625. Promoted ~430, demoted ~64 false positives
   (e.g. "St. Laurent" → Saint-Laurent-de-l'Île-d'Orléans 326 km off).
3. **Phase C** (this work) — MCP search + verify for the 4,431 residual
   chains. Output appended to the same
   `wikidata_grounding/presence_verified_matches.jsonl`.

## Final tally

**Output file**: `wikidata_grounding/presence_verified_matches.jsonl`
(6,732 presence-level records across 4,862 unique chains).

| Status     | Records | Share | Outcome |
|------------|--------:|------:|---------|
| `matched`  |  1,926  | 28.6% | `wd:Q…` authority URI |
| `mint_uri` |  4,186  | 62.2% | LINCS-minted URI under `jimclifford.ca/hgiscanada/places/<chain>/` |
| `skip`     |    620  |  9.2% | No URI emitted (NO DATA / aggregate / institution-level enum) |

## Per-province breakdown (presence-level)

| Prov | Total | Matched | Mint  | Skip | %match |
|------|------:|--------:|------:|-----:|-------:|
| AB   |   155 |     116 |    30 |    9 |  74.8% |
| BC   |   126 |      41 |    84 |    1 |  32.5% |
| MB   |   208 |      90 |   104 |   14 |  43.3% |
| NB   |   219 |     119 |    84 |   16 |  54.3% |
| NL   |    12 |       0 |     0 |   12 |   0.0% |
| NS   |   720 |     171 |   467 |   82 |  23.8% |
| NT   |   436 |     116 |   302 |   18 |  26.6% |
| ON   | 1,774 |     340 | 1,318 |  116 |  19.2% |
| PE   |   171 |     161 |     5 |    5 |  94.2% |
| QC   | 2,577 |     544 | 1,769 |  264 |  21.1% |
| SK   |   331 |     227 |    23 |   81 |  68.6% |
| YT   |     3 |       1 |     0 |    2 |  33.3% |

PEI is high because every historic Township maps cleanly to a modern Lot Q.
SK/AB are high because Prairie villages have strong Wikidata coverage.
ON/QC are low because most rural townships and parishes are
compounds/splits/wards/pre-amalgamation enumeration units that lack
separate WD entities — those mint URIs.

## Per-census-year match rate

| Year | Matched | Total | %match |
|------|--------:|------:|-------:|
| 1851 |      70 |   407 |  17.2% |
| 1861 |     108 |   547 |  19.7% |
| 1871 |     220 |   818 |  26.9% |
| 1881 |     260 |   897 |  29.0% |
| 1891 |     285 |   990 |  28.8% |
| 1901 |     325 | 1,367 |  23.8% |
| 1911 |     651 | 1,510 |  43.1% |
| 1921 |       7 |   196 |   3.6% |

1911 is the high-water mark because Phase C surfaced incorporated villages
(esp. Saskatchewan) where Wikidata coverage is dense. 1921 is low because
the residual queue at 1921 is dominated by Indian-reserve CD-level rollups
and prairie aggregates that mint or skip.

## Top mint/skip reasons (volume)

| Records | Reason |
|--------:|--------|
| 1,078 | Historic Quebec parish/township, no separate WD entity |
|   322 | Compound multi-parish/township enumeration unit |
|   234 | Compound multi-township enumeration unit |
|   210 | NO DATA placeholder |
|   187 | Historic Ontario geographic township, no separate WD entity |
|   134 | Historic Quebec township directional split (N/S/E/W) |
|   117 | Pre-amalgamation municipal ward subdivision |
|    60 | Historic Ontario township directional split (Front/Rear) |
|    55 | CD-level Indian reserves rollup |
|    52 | Quebec City / Montreal ward-quartier subdivision |
|    42 | Single Indian reserve enumeration |
|    38 | Maisonneuve / Montreal historic ward |
|    32 | Halifax-area Cumberland Polling District (1891) |
|    31 | Halifax-area Cumberland Polling District (1901) |
|    30 | Aggregate / Unorganized enumeration |

## Methods that worked

1. **Pattern-driven minting**. Once compound/ward/split/IR/NO-DATA patterns
   were templated, batches of historic ON township aggregates and QC parish
   compounds processed at 70–90 mints per 100 chains with 5–10 targeted
   searches per batch.
2. **Bulk SPARQL for structured names**. PEI Township No. *N* → Lot *N*
   (50 matches in one batch) and Saskatchewan 1911 villages
   (52, 60, 65 matches per batch) used a single SPARQL query against
   `wdt:P131* wd:Q1989` filtered by label, then a Python distance sieve.
3. **Verify gate as a safety net**. The P31/P131/P625 checker caught 7 bad
   QIDs in the SK village bulk match (label collisions with a lake, an
   electoral district, a Wikimedia disambiguation page, and a `Q5` human).
   These were demoted/replaced before the batch shipped.

## Known caveats

- **6 FAR warnings on verify** — all hand-checked, all correct, all due
  to queue-centroid drift on large historic CSDs:
  - `PLACE_MB007013_1891 "Landsdowne" → Q1660587` (130 km — RM Lansdowne
    polygon in 1891 was much larger than modern village; user direction:
    *"rethink Lansdowne Man; the polygons are big in 1901"*).
  - `PLACE_ON099094 "Copper Cliff t-v" → Q115178132` (201 km).
  - `PLACE_ON099102 "Sudbury t-v" → Q383434` (230 km — both Nipissing
    1911 chains have queue centroids pulled to the district centre, not
    the modern town).
  - `PLACE_QC047010 "Island of Anticosti" → Q4543508` (110 km).
  - `PLACE_QC154055 "Ile d'Anticosti" → Q4543508` (110 km — island is
    huge; centroid offset is real).
  - `PLACE_SK215022 "Lipton vl" → Q2085498` (72 km — queue centroid bug,
    real Lipton village is at the WD coords, the chain centroid is wrong
    in the queue file).
- **32 QIDs matched to 4+ chains** — all checked, all legitimate
  alt-chains for the same place across years/wards (Brantford, Calgary,
  Whitby, London, Buckingham, Regina, Port Arthur, Saint-Jérôme,
  Saint-Joseph-de-Beauce, Hatley, Ascot, Prince Albert, Kenora/Rat Portage,
  etc.). Expected for the per-presence model.
- **165 matches with zero word overlap between `csd_name` and
  `wikidata_label`** — mostly correct: typo normalisation
  (Chilliwak→Chilliwack, Esquessing→Esquesing, Sydney→Sidney,
  Pullarton→Fullarton, Hallowel→Hallowell, Moosejaw→Moose Jaw),
  saint-French normalisation (St. Bazile→Saint-Basile, St. Giles→
  Saint-Gilles), and modern-name normalisation for First Nations
  (Sarcee I R → Tsuu T'ina Nation 145, Peigan I R → Piikani 147). A
  few QC matches inherited from Phase A use the older township name
  on the WD side (St. Faustin → Wolfe — Wolfe Township became
  Saint-Faustin parish); those are technically correct.

## Lesson

Bulk SPARQL by label alone is **unsafe**. Wikidata has disambiguation
pages, electoral districts, lakes, and same-named entities of the
wrong type that share labels with settlements. The verify gate's
P31 allowlist is the only thing that keeps bulk matching honest.
Without it, the SK village SPARQL would have shipped 7 wrong QIDs
(lake, human, separation event, disambiguation page, wrong-coord
namesake).

## Outstanding minor items

- One Phase A inheritance entry where the WD label is misleading but
  the match is correct: `PLACE_QC202005 "St. Faustin" → Wolfe`
  (historic Wolfe Township was renamed Saint-Faustin parish). Not
  worth fixing, but flag for any human reviewer who lands on it.
- A handful of borderline distance matches (Allan SK 39 km,
  Saint-Côme-Linière 22 km, Plenty SK 15 km) — all hand-checked
  and correct; the queue centroids are pulled by the historic CSD
  polygon shape, not the modern village center.

## Files

- `wikidata_grounding/presence_verified_matches.jsonl` — full output
  (6,732 records).
- `wikidata_grounding/presence_disambig_queue.jsonl` — Phase C input
  queue (4,431 chains).
- `wikidata_grounding/presence_inheritance_audit.csv` — Phase A audit
  trail (don't modify).
- `wikidata_grounding/presence_verify_demoted.csv` — Phase B's 64
  demoted false positives.
- `scripts/disambiguate_presences.py` — bookkeeping CLI
  (`--prepare`, `--show-batch N`, `--verify`, `--status`).
- `scripts/disambiguate_csds.py` — defines `GOOD_P31_QIDS`,
  `PROVINCE_QIDS`, `MAX_DISTANCE_KM` used by the verify gate.

## Next pipeline step

The grounding output is ready to drive URI minting in
`build_neo4j_cidoc_crm_v2.py` (CSDs) and the Ladybug/Kuzu graph build.
Matched chains get `wd:Q<NNN>` authority URIs on E53_Place; mint_uri
chains get LINCS URIs minted under
`jimclifford.ca/hgiscanada/places/<chain>/`; skip chains emit no
authority URI (the CSD presence still exists in the graph as an
E93 node, just without a sameAs link).
