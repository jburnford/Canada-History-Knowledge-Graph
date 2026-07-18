# Linked Open Data Conversion and Publication Plan

This plan describes how to turn the Canada History Knowledge Graph holdings (Canadian census data, 1851–1921) that already follow the CIDOC CRM model into publishable RDF/Linked Open Data packages.

## 1. Groundwork and Inventory (Week 0–1)
1. **Confirm datasets in scope**
   - Spatial graph CSVs under `neo4j_cidoc_crm/` (E53 Place, E93 Presence, E94 Space Primitive, etc.).
   - Measurement graph CSVs under `neo4j_census_v2/` (E16 Measurement, E54 Dimension, E55 Type, temporal entities).
   - Provenance CSVs under `neo4j_provenance/` (actors, rights, sources).
2. **Profile existing Neo4j instances**
   - Snapshot the CIDOC CRM database to verify label/property usage and ensure counts match README totals.
   - Produce Cypher exports listing each label, property key, and relationship type used.
3. **Establish URI policy**
   - Mint persistent URIs under `https://data.canada-history.ca/{entity}/{identifier}` for every exported node class.
   - Reserve namespace prefixes: `chkg:` for project-specific terms, reuse `crm:`, `geo:`, `prov:`, `dcterms:`, `qb:` as needed.
   - Document URI patterns, versioning, and redirection rules in `docs/uri_strategy.md`.

## 2. Mapping CIDOC CRM Graph to RDF (Week 1–3)
1. **Define class → URI templates**
   - Map each Neo4j label (e.g., `E53_Place`, `E93_Presence`, `E16_Measurement`) to the exact CIDOC CRM URI (`crm:E53_Place` etc.).
   - Align supplemental labels (e.g., indicator types, spatial geometries) with SKOS/Data Cube terms.
2. **Design property mappings**
   - For each CSV column/property, specify the RDF predicate (mostly CIDOC CRM properties, supplemented with GeoSPARQL for coordinates and RDF Data Cube for measurements).
   - Capture time-spans as `crm:P82a_begin_of_the_begin` and `crm:P82b_end_of_the_end`, or Data Cube `sdmx-dimension:timePeriod` for observations.
3. **Create transformation specification**
   - Author RML mappings (YARRRML YAML compiled to RML) referencing the CSV exports, or alternatively Cypher-to-RDF templates using the `n10s` plugin if running directly from Neo4j.
   - Store mapping artifacts in `lod/mappings/` with clear version control.
4. **Prototype conversion**
   - Run the mapping on one province/year subset (e.g., Saskatchewan 1901) to produce Turtle and JSON-LD outputs.
   - Validate resulting RDF with SHACL shapes targeting key constraints (unique URIs, mandatory relationships, datatype ranges).

## 3. Automation Pipeline (Week 3–5)
1. **Export automation**
   - Extend existing scripts (`scripts/build_*`) or author new ones in `scripts/export_rdf/` that: 
     1. Execute Cypher queries to output canonical CSVs (or use current CSV directories).
     2. Trigger the RML engine (e.g., [RMLMapper](https://github.com/RMLio/rmlmapper-java)) to produce RDF dumps per dataset (Turtle + N-Triples for large volumes).
   - Parameterize exports by census year to allow incremental regeneration.
2. **Validation and QA**
   - Integrate SHACL validation (via `pyshacl` or TopBraid SHACL) into the export script.
   - Add SPARQL-based smoke tests (count entities per type, verify mandatory links).
3. **Continuous integration**
   - Create a GitHub Actions workflow (`.github/workflows/lod_export.yml`) that runs on demand and on tagged releases:
     - Checkout repository, provision Java (for RMLMapper) and Python (for QA scripts).
     - Execute export + transform + validate steps.
     - Publish artifacts to the workflow summary and attach RDF dumps to a GitHub release draft or push to object storage (e.g., S3 bucket).

## 4. Publication Packaging (Week 5–6)
1. **Dataset organization**
   - Produce per-year packages containing:
     - `census-{year}.ttl` (core RDF graph: places, presences, measurements, provenance links).
     - `census-{year}.jsonld` (JSON-LD serialization for web reuse).
     - `catalog.json` or DCAT record summarizing the dataset (title, description, license, version, issued/modified dates).
   - Aggregate cross-year materials (e.g., place identity, temporal overlaps) into shared files.
2. **Dereferenceable URIs**
   - Host RDF files in an S3 bucket or static web server with content negotiation; configure HTTP redirects from canonical URIs to HTML or RDF representations.
   - Provide HTML landing pages (generated via static site generator) summarizing each entity class with embedded JSON-LD.
3. **Triple store deployment**
   - Load combined dataset into a SPARQL endpoint (e.g., Apache Jena Fuseki or GraphDB) to enable interactive querying.
   - Publish SPARQL examples and query templates in `docs/sparql_examples.md`.

## 5. Documentation and Communication (Week 6–7)
1. **Technical docs**
   - Update `README.md` with export workflow overview and links to published datasets.
   - Add `docs/lod_mapping_reference.md` capturing every mapping rule, namespace, and controlled vocabulary usage.
   - Provide SHACL constraints and validation results in `docs/lod_validation_report.md` for transparency.
2. **Usage guidance**
   - Create tutorial notebooks under `docs/notebooks/` showing how to load and query the RDF with RDFLib/SPARQLWrapper.
   - Explain versioning policy, citation guidance, and data license.
3. **Stakeholder engagement**
   - Coordinate announcement and feedback loop with the Canadian Historical GIS community; gather integration requests for future releases (e.g., linking to Wikidata, GeoNames).

## 6. Release and Iteration (Week 7+)
1. **Publish v1.0 LOD release**
   - Tag the repository, upload RDF dumps, SHACL report, and documentation.
   - Issue DOI via Borealis or Zenodo for the packaged RDF dataset.
2. **Post-release monitoring**
   - Track access logs and SPARQL endpoint health; schedule quarterly refreshes aligned with Neo4j updates.
   - Maintain changelog noting new census years, corrected geometries, or schema refinements.
3. **Future enhancements**
   - Enrich with external links (Wikidata IDs, GeoNames URIs) using reconciliation workflows.
   - Explore HDT or RDF-star serializations for performance and provenance use cases.

---
Last updated: revised to focus on converting existing CIDOC CRM data (1851–1921) into RDF/LOD formats.
