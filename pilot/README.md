# Three-Model KG Pilot — Ontario, 1851–1921

Comparison of three knowledge-graph models built from the same slice of historical Canadian census data, to test whether full CIDOC-CRM, a CRM-lite variant, or a PID-first property graph best serves a shared knowledge graph of Canadian history post-1850.

**Pilot slice:** Ontario, all 8 census years (1851–1921). Five pilot measurement variables covering integer/float/string and varying year-coverage (always-present, early-years, single-year). See [`variables.md`](./variables.md).

**What's out of scope:** CSD→Wikidata grounding is active in `wikidata_grounding/` and consumed read-only here. The E53_Place / E93_Presence backbone is retained across all three approaches.

## The three models

| | Approach A — Full CIDOC-CRM | Approach B — CRM Lite | Approach C — KuzuDB |
|---|---|---|---|
| **Target audience** | LINCS publication, LOD consumers | LLM research collaborators, RDF flavour | Historians + Claude Code as collaborator |
| **Reification** | E16/E54/E58 per measurement | Typed datatype properties on E93 | Inline properties on Presence |
| **Time-span** | E52_Time-Span nodes + P4 | `base:observed_on` xsd:date on E93 | `Presence.year INT64` column |
| **Internal IDs** | E42_Identifier | `dcterms:identifier` literal | `place_id` primary key (STRING) |
| **External PIDs** | URI subject = Wikidata QID | `owl:sameAs wikidata:Q…` | `Place.wikidata_qid` STRING column, indexed |
| **Script** | `scripts/export_rdf.py --pilot on_1851_1921` | `scripts/export_rdf_lite.py` | `scripts/export_kuzu_pilot.py` |
| **Output** | `rdf_export/pilot_on_A.ttl` | `rdf_export/pilot_on_B.ttl` | `pilot/on_kuzu/{schema.cypher, nodes/, edges/, on.kuzu/}` |

## Size comparison

| | Approach A | Approach B | Approach C |
|---|---:|---:|---:|
| **Triples / rows / edges** | 425,323 triples | 128,620 triples | 14,899 nodes + 36,199 edges |
| **File size** | 29.6 MB (.ttl) | 8.7 MB (.ttl) | 19 MB built DB + 2.3 MB loader CSVs |
| **Reduction vs A** | (baseline) | 70% fewer triples | — (different shape) |

## Track 1 scorecard — CIDOC-CRM compliance (Approach A only)

Hard LINCS-profile checks run with rdflib against `pilot_on_A.ttl`.

| Check | Result | Status |
|---|---|---|
| Blank nodes anywhere | 0 | ✅ PASS |
| `P82a` / `P82b` typed `xsd:date` (not `xsd:string`) | 16/16 typed dates, 0 bad | ✅ PASS |
| Every `E54_Dimension` has `P90_has_value` | 0 missing | ✅ PASS |
| `E33_E41_Linguistic_Appellation` uses `P190_has_symbolic_content` | 3,881 / 3,881 | ✅ PASS |
| No relationship properties on `P122` | (not reified as edge subject) | ✅ PASS |
| `E16 → E93` via `P39_measured` | 587,657 triples in full export | ✅ PASS |
| `E41 → E53` via `P1_is_identified_by` | 3,880 linked | ✅ PASS |
| Places with Wikidata `owl:sameAs` or Wikidata URI subject | 1,044 / 3,237 = **32.3%** | ⚠️ WARN |
| Places with GeoNames `owl:sameAs` | 0 / 3,237 = **0%** | ⚠️ WARN (source-data gap) |

**Known gaps (data, not modeling):** GeoNames IDs are not available in the current `wikidata_grounding/` pipeline outputs. LINCS prefers GeoNames as primary place identifier; adding this requires extending the grounding pipeline (out of scope for this pilot).

## Track 2 scorecard — LLM-collaborator readability (Approaches B and C)

### Query ergonomics — lines of code per benchmark query

Measured by `scripts/run_pilot_benchmarks.py`. LOC excludes the shared SPARQL `PREFIX` block.

| Query | A LOC | B LOC | C LOC |
|---|---:|---:|---:|
| **Q1** Historical CSDs grounded to Westmeath QID | 5 | 4 | **3** |
| **Q2** Population trajectory 1851→1921 | 7 | 7 | **2** |
| **Q3** CSDs bordering Westmeath in 1871 | 7 | 7 | **3** |
| **Q4** Westmeath 1911 density (fractional) | 8 | 5 | **2** |
| **Q5** CSDs in Carleton County 1871 | **4** | **4** | 5 |
| **Q6** Null-vs-zero probe (1851 density) | 10 | 5 | **2** |
| **Total** | 41 | 32 | **17** |

All three backends returned identical row counts for Q1 (8 presences), Q2 (8 years), Q3 (4 neighbors), Q5 (9 CSDs). The Q4 and Q6 differences are meaningful — see next section.

### Null-vs-zero probe (the source-data type-diversity stress test)

"What was the population density of Westmeath in 1851?" Expected answer: *"That variable wasn't recorded in 1851."*

| Approach | Result | Can distinguish "not asked" from "zero"? |
|---|---|---|
| A (full CIDOC) | Empty result set (no E16_Measurement with POP_PER_SQ_MI type for 1851) | ❌ No — same shape as "asked and returned zero" |
| B (Lite) | Empty via OPTIONAL (no `base:pop_per_sq_mi` triple) | ❌ No — same limitation |
| C (Kuzu) | `pop_per_sq_mi IS NULL` returns TRUE, value is `None` | ✅ **Yes** — explicit NULL distinct from `0.0` |

C's property-graph NULL semantics is the only one that cleanly distinguishes "question not asked in this census" from "asked and answered zero." This has real implications for historians interpreting gaps in a trajectory — is the data missing or absent?

### Sample: Westmeath 1871 population trajectory, same answer, three query shapes

**A (full CIDOC-CRM):**
```sparql
SELECT ?presence ?val_total WHERE {
  ?presence crm:P166_was_a_presence_of wd:Q115263132 .
  ?meas crm:P39_measured ?presence ;
        crm:P40_observed_dimension ?dim .
  ?dim crm:P90_has_value ?val_total .
  FILTER(CONTAINS(STR(?meas), "POP_XX_N") || CONTAINS(STR(?meas), "POP_TOT"))
}
```

**B (CRM Lite):**
```sparql
SELECT ?presence ?date ?total ?male ?female WHERE {
  ?presence crm:P166_was_a_presence_of wd:Q115263132 ;
            base:observed_on ?date ;
            base:pop_total ?total .
  OPTIONAL { ?presence base:pop_total_m ?male . }
  OPTIONAL { ?presence base:pop_total_f ?female . }
}
```

**C (Kuzu Cypher):**
```cypher
MATCH (p:Place {name: 'Westmeath'})<-[:OBSERVED_IN]-(pr:Presence)
RETURN pr.year, pr.pop_total, pr.pop_total_m, pr.pop_total_f ORDER BY pr.year;
```

All three return Westmeath's 1871 population as **2,632** (1,405 M + 1,227 F) — answers identical, query complexity very different.

## Anti-cheat protocol for Track-2 LLM evaluation

The Kuzu loader CSVs (`pilot/on_kuzu/nodes/*.csv`, `pilot/on_kuzu/edges/*.csv`) sit next to the built `.kuzu` database. When evaluating whether Claude Code can answer historian questions against Approach C, the benchmark prompt **must require the `kuzu` Python library** against the built database. A pandas-over-loader-CSV solution counts as failed even if numerically correct — it tests dataframe munging, not graph query generation.

See [`feedback_llm_benchmark_anticheat.md`](/home/jic823/.claude/projects/-home-jic823-Canada-History-Knowledge-Graph/memory/feedback_llm_benchmark_anticheat.md) in project memory for the durable version of this guidance.

## Running the full pilot end-to-end

```bash
# Build (in order — Approach C needs no inputs from A/B, but build all for the benchmark):
python3 scripts/export_rdf.py --pilot on_1851_1921    # -> rdf_export/pilot_on_A.ttl
python3 scripts/export_rdf_lite.py                    # -> rdf_export/pilot_on_B.ttl
python3 scripts/export_kuzu_pilot.py --province ON    # -> pilot/on_kuzu/on.kuzu/

# Score:
python3 scripts/run_pilot_benchmarks.py               # -> pilot/benchmark_results.md
```

The build takes ~2 minutes total on a laptop; the benchmark harness takes ~30s.

## Boundaries of the model

Place identity in this knowledge graph is delegated to **Wikidata QIDs** via `owl:sameAs` (Approaches A and B) or an indexed `wikidata_qid` column (Approach C). The depth and accuracy of that identity is whatever Wikidata provides. Where Wikidata's modeling is thin — pre-modern phases of a place, polygon evolution over centuries, conflations of city / metro / county boundaries, pre-contact and Indigenous land relationships — this graph inherits the thinness. We model temporally-scoped 19th- and early-20th-century census manifestations (`E93_Presence` / `Presence`) and link them to whatever enduring concept Wikidata supplies; we do not attempt to model the deep-time, geological, or pre-1850 layers ourselves.

A practical implication: a question like *"What was happening on this land in 1700?"* cannot be answered from this graph. A question like *"What was the population of this CSD in 1871, what county was it part of, and what's its modern Wikidata equivalent?"* can.

## What the pilot does NOT decide

- Whether Approach C's readability advantage holds at full Canada scale (all provinces, all years) — the pilot is 6,544 presences, the full graph is ~48K.
- Whether the Lite flattening generalizes past integer/decimal/string to more complex value types (e.g. codelist-valued variables).
- Whether the Kuzu database format is operationally acceptable for a shared resource (who runs the build, where does it live, how are updates distributed).
- The GeoNames grounding gap that affects all three approaches — this is a `wikidata_grounding/` pipeline extension, not a modeling choice.

## Files

- [`variables.md`](./variables.md) — the five pilot variables and why
- [`benchmark_results.md`](./benchmark_results.md) — auto-generated per-query results
- [`on_kuzu/`](./on_kuzu/) — Approach C output (schema, loader CSVs, built DB)
- `../rdf_export/pilot_on_A.ttl` — Approach A output (29.6 MB)
- `../rdf_export/pilot_on_B.ttl` — Approach B output (8.7 MB)
- `../scripts/export_rdf.py` — Approach A exporter (with `--pilot` flag)
- `../scripts/export_rdf_lite.py` — Approach B exporter
- `../scripts/export_kuzu_pilot.py` — Approach C exporter
- `../scripts/run_pilot_benchmarks.py` — benchmark harness
