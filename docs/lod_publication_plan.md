# Linked Open Data Conversion and Publication Plan

This living document breaks the Linked Open Data (LOD) roll-out into concrete work packages. It assumes that the cleaned Canadian census datasets (years 1851–1921) already live in Neo4j following the CIDOC CRM model, and that CSV exports under `neo4j_cidoc_crm/`, `neo4j_census_v2/`, and `neo4j_provenance/` represent the canonical state of record. The goal is to produce validated RDF datasets, publish them with dereferenceable URIs, and document how partners can reuse them.

## 0. Project Setup (Week 0)

| Task | Output | Lead / Support | Notes |
| --- | --- | --- | --- |
| Kick-off meeting | Shared understanding of scope, priorities, and success metrics | Project lead, data engineer, curator | Review this plan, confirm data range (1851–1921), agree on communication cadence. |
| Tooling inventory | Checklist of required tooling versions | Data engineer | Confirm availability of Java (RMLMapper), Python (PySHACL), Docker (Fuseki), GitHub Actions runners. |
| Repository prep | `lod/` workspace with README and issue templates | Project lead | Create issue labels (`LOD`, `mapping`, `QA`, `publication`). |

## 1. Data Groundwork and Quality Gate (Week 0–1)

| Task | Detailed steps | Output |
| --- | --- | --- |
| Dataset inventory | Catalogue CSV exports by census year and entity types; produce counts per file using `scripts/test_census_queries.sh` to confirm parity with Neo4j | `docs/lod_inventory.md` |
| Schema profiling | Run Cypher `CALL db.schema.visualization()` and `db.propertyKeys` exports; store results in `lod/reference/schema/` | `schema_labels.csv`, `schema_relationships.csv` |
| Data QA gate | Spot-check 5% random sample of records per class to ensure identifiers, dates, and coordinates conform to expectations; log issues in GitHub | Issue list + acceptance report |
| URI policy draft | Define URI patterns per class (`Place`, `Presence`, `Measurement`, `Dimension`, `Actor`, etc.), base domain, and versioning strategy | `docs/uri_strategy.md` |

## 2. Mapping Specification (Week 1–3)

### 2.1 Entity and Relationship Alignment

1. **Class alignment matrix**
   - Produce a table mapping each Neo4j label (e.g., `E53_Place`, `E93_Presence`, `Indicator`, `Source`) to CIDOC CRM, GeoSPARQL, SKOS, or PROV-O URIs.
   - Store in `lod/mappings/class_alignment.xlsx` (or CSV) with notes on any modelling deviations.

2. **Property dictionary**
   - For each CSV column, record datatype, cardinality, and target RDF predicate.
   - Highlight transformations (e.g., concatenating `given_name` + `surname` into `crm:P131_is_identified_by`).

3. **Controlled vocabularies**
   - Decide how to handle enumerations such as occupations, religions, and relationships by linking to existing SKOS vocabularies or minting local URIs under `chkg:concept/`.

### 2.2 Transformation Blueprint

| Task | Detailed steps | Output |
| --- | --- | --- |
| YARRRML authoring | Create modular YARRRML files per entity family (places, presences, persons, measurements). Include shared prefix files and parameterize file paths via environment variables. | `lod/mappings/*.yarrrml.yml` |
| RML compilation | Use `yarrrml-parser` to compile to `.rml.ttl`. Commit compiled files for traceability. | `lod/mappings/*.rml.ttl` |
| SHACL shapes | Draft shapes for identity uniqueness, temporal completeness, geometry validity, and measurement consistency. | `lod/shapes/core_shapes.ttl` |

### 2.3 Prototype Conversion

1. Select a pilot slice (e.g., Saskatchewan 1901 presence + measurement data).
2. Run RMLMapper locally:
   ```bash
   java -jar tools/rmlmapper.jar -m lod/mappings/presence.rml.ttl -o tmp/saskatchewan-1901.ttl -s turtle
   ```
3. Validate with `pyshacl` against `lod/shapes/core_shapes.ttl` and document findings.
4. Review output with the curation team; gather feedback on URI design and vocabulary choices.

## 3. Automated Export Pipeline (Week 3–5)

| Task | Detailed steps | Output |
| --- | --- | --- |
| Export scripts | Add `scripts/export_rdf/export_year.sh` to orchestrate CSV retrieval (from Neo4j or existing exports), run RMLMapper per mapping, and split outputs into Turtle and N-Triples. | Shell scripts + README |
| Validation harness | Implement `scripts/export_rdf/validate.py` to run SHACL + SPARQL smoke tests (entity counts, orphan detection). | Python validation script |
| CI integration | Configure `.github/workflows/lod_export.yml` with matrix over census years; cache Maven/Java dependencies for RMLMapper; publish artifacts as workflow outputs. | Workflow file + passing run |
| Storage hand-off | Automate upload to object storage (S3/MinIO) using GitHub OIDC or deployment credentials. | Deployment instructions |

## 4. Publication Packaging (Week 5–6)

1. **Dataset assembly**
   - Structure `dist/lod/{year}/` directories with `ttl`, `nt`, and `jsonld` serializations, plus checksum files.
   - Generate DCAT metadata using [Frictionless Data Package](https://frictionlessdata.io/) descriptors or `rdf-dataset-catalog`. Store aggregated catalog at `dist/lod/catalog.ttl`.

2. **Dereferenceable infrastructure**
   - Configure static hosting (e.g., AWS CloudFront + S3 or GitHub Pages) with content negotiation via Lambda@Edge or Apache `RewriteRule`.
   - Produce HTML entity pages with Hugo or MkDocs using templates that embed JSON-LD snippets referencing the canonical URIs.

3. **Triple store deployment**
   - Containerize Apache Jena Fuseki with the exported RDF loaded; expose SPARQL endpoint at `https://sparql.canada-history.ca/`.
   - Write Helm or Docker Compose definitions under `deploy/`.
   - Prepare monitoring (UptimeRobot ping, CloudWatch logs) and weekly snapshot scripts.

## 5. Documentation, Outreach, and Support (Week 6–7)

| Task | Audience | Output |
| --- | --- | --- |
| Technical reference | Developers | `docs/lod_mapping_reference.md`, `docs/lod_validation_report.md`, `docs/sparql_examples.md` |
| Onboarding guides | Researchers, educators | Notebooks in `docs/notebooks/` demonstrating RDFLib, SPARQLWrapper, and GIS integrations (e.g., QGIS via SPARQL). |
| Governance notes | Project stakeholders | Update `README.md` with release policy, licensing (e.g., CC BY 4.0), citation text, and contribution process for LOD consumers. |
| Outreach plan | External partners | Blog post, mailing list announcement, webinar slides stored in `docs/outreach/`. |

## 6. Release and Continuous Improvement (Week 7+)

1. **Release v1.0**
   - Tag repository (`v1.0.0-lod`), publish GitHub Release with RDF artifacts, SHACL reports, and documentation bundle.
   - Archive release package in Zenodo to mint DOI; include metadata aligning with DCAT fields.

2. **Post-release operations**
   - Monitor SPARQL endpoint uptime; log usage metrics (queries per day, response times).
   - Schedule quarterly data refresh job aligned with Neo4j ETL updates; document changes in `CHANGELOG.md` under an LOD section.

3. **Roadmap for enhancements**
   - Plan linking to external datasets (Wikidata, VIAF, GeoNames) using reconciliation tools (OpenRefine, Ontotext Refine).
   - Evaluate advanced serializations (HDT, RDF-star) for performance and provenance modelling.
   - Assess integration with IIIF for census images and align with PROV-O for provenance depth.

## 7. Immediate Next Steps Checklist

- [ ] Approve URI policy draft and create redirect infrastructure ticket.
- [ ] Raise issues for mapping tasks per entity family and assign owners.
- [ ] Build prototype RML mapping for a single year and review with stakeholders.
- [ ] Document validation requirements and success criteria before scaling to all years.
- [ ] Establish publication storage (S3 bucket or equivalent) with appropriate access controls.

---
Last updated: initiated detailed work plan to convert existing CIDOC CRM datasets (1851–1921) into RDF/LOD formats.
