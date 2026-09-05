# LOD rebuild plan

Accepted direction, 2026-09-05: preserve historical identities, dated census
representations, spatial extents, survey grounding, and statistical assertions
as distinct, connected parts of the model. Research-paper files are excluded.

## Implementation sequence

1. **GIS evidence — completed.** Use the audited equal-area correspondences;
   retain small intersections, coverage qualifications, and source hashes.
2. **Model pilot — implemented and tested; national migration pending.** Exercise Westmeath and the 1911–1921
   Saskatchewan correspondence example with actual polygons and census values.
   Test identifiers, CRM property ranges, multiple predecessors, missing-data
   handling, numeric values, and separation of Wikidata mappings.
3. **Identity migration.** Preserve local identifiers. Classify existing chains
   and mappings by their evidence and referent: administrative unit, settlement,
   organization, survey unit, or census-defined reporting unit. Matching name,
   entity type, and stable extent across consecutive censuses can support
   continuity. Geometry alone cannot turn a reporting unit into a community.
   Keep a redirect/crosswalk from legacy identifiers.
   The national staging inventory now covers all 22,522 GIS representations,
   with qualified continuity and external-referent review categories. It
   includes continuity through a reduction in reporting area: the same
   township can persist after a town or village is reported separately.
4. **Dates and connections.** Give each census representation its sourced
   reference date. A connection identifies its earlier and later census
   configurations; the later reference date dates the new configuration.
   Multiple predecessors and successors are supported. This is census
   succession, not a reconstruction of municipal incorporation events.
5. **Survey grounding and observations.** Preserve source reporting units even
   when they lack a GDB polygon. Add DLS identifiers and sourced survey extents;
   connect them spatially to census units. Rebuild observations from the source
   tables with original values, variable definitions, units, source locations,
   reference periods, and missing-value statuses. CRM E13 assignments and a
   statistical query view must derive from the same observation records.
   The canonical source stage now preserves all 47 selected workbooks and
   independently reconciles their 1,783,554 statistical cells. It includes
   CD totals, duplicate columns, source definitions and qualified periods;
   see [the source-table rebuild](LOD_SOURCE_TABLE_REBUILD.md). Joining these
   source reporting units to GIS representations remains a separate step.
   The first complete assessment preserves all source rows, distinguishes
   explicit identifier agreement from contextual name candidates, and retains
   conflicts in `data_quality/lod_source_bindings/`. Publication of those
   associations requires their qualifications and source evidence to survive
   in RDF and dependent consumers.
6. **Full staged rebuild.** Rebuild spatial and observation outputs, RDF,
   database imports, and dependent site data using the corrected model. Validate
   counts, endpoints, ranges, source coverage, and representative queries before
   promoting generated files. External publication is a separate action.

## Model rules

* A historical administrative unit or settlement phenomenon can be a typed
  E4 Period. A census-defined unit without established historical identity can
  use an E92 Spacetime Volume; its known occurrence does not imply continuity.
* An E93 Presence has exactly one P166 subject, of type E92 or a subclass,
  and a P164 time-span. A separate association connects a reporting unit to a
  community it contains or represents when they are not the same entity.
* An E53 Place identifies an extent in space. Geometry is a separate
  GeoSPARQL representation. Centroids are separate point representations;
  they do not define the polygonal extent. A repeated identical extent may be
  shared; near equality does not establish identity.
* Computed correspondence assessments retain both fractions, intersection area,
  CRS, method, source, and census endpoints. They never use cross-year P132.
  “Split” and “merge” in the project vocabulary refer to census configurations.
* Wikidata mappings retain their provenance and matched entity types. No
  automatic replacement of local IDs or unconditional owl:sameAs. An uncertain
  mapping is an explicitly typed candidate assignment.
* NO DATA polygons start as source coverage records and spatial extents, without
  an assumed administrative identity, jurisdictional explanation, or zero
  population. Coverage status can be refined when source documentation supports
  an interpretation.
* E13 assigns a numerical E54 quantity using P140/P141; nonnumeric source text
  is preserved as text with an interpretation status, never as P90 numeric data.
  Project assignment dates are distinct from census reference dates.

## Findings that affect the rebuild

The existing export's date nodes use entire calendar years. Census vintage,
reference day, enumeration dates, publication date, and a variable's reporting
period must be distinguished. For example, the 1851 Ontario/Quebec census
began in January 1852; pre-Confederation dates differ by province. The pilot
uses the unambiguous June 1 reference dates for 1911 and 1921. National date
configuration needs sources specific to the census and jurisdiction.

The observation builder currently skips 1911 table rows whose survey-township
identifiers do not map to its GDB crosswalk, and excludes non-CSD aggregate
rows. The source-table rebuild must inventory those omissions and preserve
observations at their actual reporting level. Geographic availability is not
a prerequisite for retaining a statistical observation. Aggregates need an
explicit level so queries do not add totals to their constituent observations.

Existing derived observation files lack complete cell-level provenance and
may conflate repeated variables across tables. Pilot use of these files is
explicitly recorded; it does not replace the source-table rebuild.

CD aggregation must also preserve coverage status. A named CD derived entirely
from NO DATA children is a coverage record; its name cannot establish census
reporting identity. Mixed CDs retain their reporting identity without assuming
that NO DATA child areas have zero population.

## Acceptance checks

* Every snapshot has one valid temporal subject and a sourced reference span.
* Extents have polygons; coverage records cannot acquire observed populations
  or historical identities by default.
* All audited correspondence endpoints survive, including cross-province and
  coverage endpoints; many-to-many fixtures retain all contributions.
* No invalid CRM ranges, cross-year P132, nonnumeric P90, or automatic identity
  assertions to Wikidata.
* Source observation counts reconcile with exported, qualified, and rejected
  records at each reporting level. Rejections have explicit reasons.
* Density units, source definitions, and reporting periods survive export.
* Database and site consumers resolve new identifiers and retain provenance.

References: [CRM 7.1.3](https://cidoc-crm.org/html/cidoc_crm_v7.1.3.html),
[GeoSPARQL](https://docs.ogc.org/is/22-047r1/22-047r1.html),
[RDF Data Cube](https://www.w3.org/TR/vocab-data-cube/),
[1851 census](https://www.canada.ca/en/library-archives/collection/research-help/genealogy-family-history/censuses/pre-confederation/1851.html),
[1861 census](https://www.canada.ca/en/library-archives/collection/research-help/genealogy-family-history/censuses/pre-confederation/1861.html),
[official census dates, Canada Year Book](https://www66.statcan.gc.ca/eng/1927-28/192701430101_p.%20101.pdf).
