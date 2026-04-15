# Decision: Model P122_borders_with at the Presence Level, Not the Place Level

**Status**: Tentative — to be discussed at HGIS-to-LOD workshop 2026-04-16.
**Date drafted**: 2026-04-15
**Affects**: `scripts/build_neo4j_cidoc_crm.py`, all `p122_borders_with_*.csv` outputs, the RDF export.

---

## The problem

The current v2 CIDOC-CRM export carries border information on P122 as edge properties:

```
:START_ID,:END_ID,during_period,shared_border_length_m:float,:TYPE
PLACE_MB008010_1901,PLACE_MB008013,CENSUS_1901,19604.84,P122_borders_with
```

Two things are wrong for RDF publication:

1. **RDF has no edge properties.** The `during_period` and `shared_border_length_m` columns silently vanish on Turtle export. A downstream consumer sees "MB008010 borders MB008013" with no year and no length.
2. **Borders are not a property of timeless places.** "Brantford borders Paris" is only meaningful relative to a specific moment — the 1901 polygons border each other; the 1911 polygons may not. The current CSVs already implicitly acknowledge this by splitting the edges into per-year files, but the endpoints are still E53_Place nodes, which in our model represent the timeless synthesis across all census years.

## Two options we considered

### Option 1 (chosen): move P122 to the presence level + reify the length as a measurement

- Edges run `E93_Presence → P122_borders_with → E93_Presence` (e.g., `MB008010_1901 → MB008013_1901`), mirroring how `P10_falls_within` already expresses CSD→CD hierarchy at the presence level.
- Each edge spawns a small measurement cluster recording the length:

  ```
  BORDER_MEAS_MB008010_MB008013_1901 a E16_Measurement
      P39_measured       → MB008010_1901
      P40_observed_dim   → BORDER_DIM_MB008010_MB008013_1901

  BORDER_DIM_MB008010_MB008013_1901 a E54_Dimension
      P90_has_value      → 19604.84
      P91_has_unit       → UNIT_METRE

  UNIT_METRE a E58_Measurement_Unit
      rdfs:label         "metre"
      owl:sameAs         wikidata:Q11573
  ```

**Pros**
- Consistent with how `P10_falls_within` already models per-year hierarchy in v2. One precedent, one mental model.
- Matches the physical reality: borders are between specific polygons at specific moments.
- The length survives RDF export as a first-class queryable value. SPARQL queries like "longest shared border in 1901," "CSDs whose border length changed between 1901 and 1911," and "total perimeter of Brantford 1901" all become possible.
- The E16/E54/E58 reification pattern is the same one we need for C4 (census observations). Building it here gives us the template for population, acreage, etc.
- No edge properties anywhere — clean RDF throughout.

**Cons**
- CIDOC-CRM's formal definition of P122 puts its domain and range on E53_Place. Strict ontology validators may flag `E93_Presence → P122 → E93_Presence` as a domain violation. Our working assumption is that `lincs-validate` cares about RDF structure more than strict domain checking, but this is worth confirming with the LINCS team at the workshop.

### Option 2 (rejected): keep P122 on E53_Place as a timeless edge, reify year + length as a measurement

- `PLACE_MB008010 → P122 → PLACE_MB008013` — one edge, asserting "these two places were ever adjacent."
- All the temporal and quantitative detail lives in a measurement node with a time-span and a length.

**Pros**
- Formally clean: P122 stays on its defined domain.

**Cons**
- The edge becomes semantically weak — "these two places were adjacent at *some point*" isn't very useful, and it obscures the actual case where two places were adjacent in some years and not in others.
- Inconsistent with how P10 is already modelled (presence-level). Two different hierarchy patterns for two different relationship types is a cognitive cost every query author pays.
- Queries become more awkward — instead of "find all borders in 1901" you need "find P122 edges whose associated measurement's time-span includes 1901."

## Why we chose Option 1

The user's framing settled this: **the messy realities of history don't fit the clean ontological distinction between "place" and "place-in-time."** CSDs were redrawn, amalgamated, split, and renumbered constantly between 1851 and 1921. An E53_Place in our model is already a synthesis we constructed — it is not a ground-truth identity in the source data. The things that actually exist in the sources are the per-year polygons (our E93_Presence nodes). P122 belongs there because that's where the data lives.

We accept the formal domain-violation risk in exchange for:
1. Consistency with P10 (one mental model for per-year relationships).
2. Semantic honesty about what the data actually records.
3. A reusable reification template for all other per-year quantitative claims (C4 census observations).

## Revert conditions

If the LINCS team (or `lincs-validate` running on a real SK Turtle export) flags the E93→P122→E93 pattern as unacceptable, fall back to Option 2. The change is local to one script (`build_neo4j_cidoc_crm.py`) and would take ~1 hour to invert. This decision is deliberately structured as reversible.

## What this document does not cover

- **P89_falls_within** is being dropped entirely in the same C3 pass (it is redundant with the presence-level P10 that already exists). That is a separate, less controversial change and does not need discussion at the workshop.
- **Border-measurement sharing across two presences**: one edge `A → P122 → B` could spawn a single E16 linked to both, or two E16s (one per direction). The current plan is one E16 per undirected edge, with `P39_measured` pointing at the lexically-smaller-tcpuid endpoint by convention.
- **Why metres and not a Getty AAT unit URI**: we are using `wikidata:Q11573` (metre) as the unit's `owl:sameAs` target. Wikidata has coverage for SI units; Getty AAT's coverage is less consistent. If LINCS prefers AAT, this is a one-row change in `e58_measurement_unit.csv`.
