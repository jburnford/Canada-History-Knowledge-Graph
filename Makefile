# =============================================================================
# HGIS Canada Knowledge Graph — pipeline orchestrator
#
# Default target `make all` builds the RDF-aligned site in data_quality/rdf_site/.
# The legacy pipeline below rebuilds rag_site/ from the spatial-linking output
# (year_links_output/ + cd_links_output/), the GDB + Excel data at
# config.toml [paths].data_root, and the LINCS dump.
#
# The spatial linking step itself takes ~70 minutes and requires the conda
# `geo` environment + the GDB; it is broken out as `make link` and is NOT a
# dependency of `make all` so casual rebuilds don't re-run it.
#
# Usage:
#   make all       — build the current RDF-aligned website in isolation
#   make site      — same as all (assumes validated RDF staging is current)
#   make rdf-site-check — validate an existing RDF-site build
#   make legacy-site — rebuild the older Kuzu-based website for comparison
#   make dcb       — rebuild DCB person links (Stage 5) only
#   make link      — re-run spatial linking (slow; needs GDB + geo env)
#   make deploy    — validate the current RDF-site build, then publish it
#   make clean     — remove generated outputs (keeps registries)
#   make distclean — remove EVERYTHING regenerable (including registries)
#   make config-check — print resolved config paths
# =============================================================================

# ---- Configuration ---------------------------------------------------------

PYTHON       := python3
CONDA_RUN    := conda run -n geo
YEARS        := 1851,1861,1871,1881,1891,1901,1911,1921

GDB          := $(shell $(PYTHON) -c 'from scripts._config import CONFIG; print(CONFIG.gdb_path)' 2>/dev/null)
DATA_ROOT    := $(shell $(PYTHON) -c 'from scripts._config import CONFIG; print(CONFIG.data_root)' 2>/dev/null)
LINCS_TTL    := $(shell $(PYTHON) -c 'from scripts._config import CONFIG; print(CONFIG.lincs_ttl)' 2>/dev/null)
HGIS_REPO    := $(shell $(PYTHON) -c 'from scripts._config import CONFIG; print(CONFIG.hgiscanada_repo)' 2>/dev/null)

# ---- Phony targets ---------------------------------------------------------

.PHONY: all site dcb link link-csds link-cds deploy clean distclean config-check residents
.PHONY: gis-audit gis-stage-links gis-validate
.PHONY: lod-model-pilot lod-model-check
.PHONY: lod-identities lod-1911-reporting
.PHONY: lod-census-sources lod-census-source-rdf
.PHONY: lod-source-bindings

all: rdf-site

site: rdf-site

.PHONY: rdf-site rdf-site-check rdf-site-test rdf-site-serve rdf-site-editorial legacy-site
RDF_SITE ?= data_quality/rdf_site

# Source RDF must already be exported/validated. The builder rejects changed
# databases, exporter code, or identity evidence, and retains the previous build.
rdf-site: scripts/build_rdf_site.py scripts/_site_urls.py scripts/_config.py data/published_site_urls.csv data/site_url_assignments.csv data/site_legacy_records.json data_quality/lod_census_sources/rdf-catalog.json data_quality/lod_identity/manifest.json data_quality/lod_source_bindings/manifest.json
	$(PYTHON) scripts/build_rdf_site.py --out $(RDF_SITE)

rdf-site-test:
	$(PYTHON) -m pytest -q tests/test_rdf_site.py tests/test_site_urls.py

rdf-site-serve: scripts/serve_rdf_site.py
	$(PYTHON) scripts/serve_rdf_site.py --site $(RDF_SITE)

rdf-site-editorial: scripts/build_rdf_site.py
	$(PYTHON) scripts/build_rdf_site.py --out $(RDF_SITE) --editorial-only

# Deliberately validate the artifact being reviewed, without silently rebuilding
# it at deployment time. Full source reconciliation includes the published RDF.
rdf-site-check: rdf-site-test scripts/validate_rdf_site.py scripts/check_rdf_site_links.py scripts/site_url_inventory.py
	$(PYTHON) scripts/validate_rdf_site.py --site $(RDF_SITE) --rdf-cache data_quality/rdf_site_validation.json
	$(PYTHON) scripts/site_url_inventory.py check --site $(RDF_SITE) --require-build-manifest --report data_quality/rdf_site_urls_validation.json
	$(PYTHON) scripts/check_rdf_site_links.py --site $(RDF_SITE)

legacy-site: rag_site/index.html

# Published addresses are versioned inputs. Capture is an explicit operation;
# never refresh the baseline automatically as part of a build or deployment.
.PHONY: site-url-capture site-url-check site-url-migration site-url-test site-url-preview site-url-preview-facts
SITE_URL_CAPTURE ?= data/published_site_urls.csv
SITE_URL_PREVIEW ?= data_quality/site_url_preview

site-url-capture: scripts/site_url_inventory.py scripts/_site_urls.py
	$(PYTHON) scripts/site_url_inventory.py capture --output $(SITE_URL_CAPTURE)

site-url-check: data/published_site_urls.csv scripts/site_url_inventory.py scripts/_site_urls.py
	$(PYTHON) scripts/site_url_inventory.py check

site-url-migration: data/published_site_urls.csv scripts/site_url_inventory.py
	$(PYTHON) scripts/site_url_inventory.py migration

site-url-test:
	$(PYTHON) -m pytest -q tests/test_site_urls.py

# Use the published residents pages and supporting files while testing the
# URL-aware generator. This does not rebuild GIS/source data or publish.
site-url-preview: scripts/generate_rag_pages.py scripts/_site_urls.py scripts/_site_legacy.py data/published_site_urls.csv data/site_url_assignments.csv data/site_legacy_records.json
	mkdir -p $(SITE_URL_PREVIEW)
	rsync -a --exclude='.git/' --exclude='google*.html' $(HGIS_REPO)/ $(SITE_URL_PREVIEW)/
	$(PYTHON) scripts/generate_rag_pages.py --all --out $(SITE_URL_PREVIEW)
	$(PYTHON) scripts/emit_facts_jsonl.py --out $(SITE_URL_PREVIEW)
	$(PYTHON) scripts/site_url_inventory.py check --site $(SITE_URL_PREVIEW) --require-build-manifest --report data_quality/site_urls/preview_validation.json

site-url-preview-facts: scripts/emit_facts_jsonl.py scripts/_site_urls.py data/published_site_urls.csv data/site_url_assignments.csv
	$(PYTHON) scripts/emit_facts_jsonl.py --out $(SITE_URL_PREVIEW)

dcb: data/lincs_person_csd_links.csv

link: link-csds link-cds

# Review geometry evidence independently of the historical identity registries.
gis-audit:
	$(CONDA_RUN) $(PYTHON) scripts/audit_gis_connections.py

# Rebuild into staging so source comparisons remain available before promotion.
gis-stage-links:
	OUT_DIR=data_quality/gis_rebuild/csd $(CONDA_RUN) bash scripts/link_all_years.sh
	OUT_DIR=data_quality/gis_rebuild/cd $(CONDA_RUN) bash scripts/link_cd_all_years.sh

gis-validate:
	$(PYTHON) scripts/validate_gis_rebuild.py

# Model migration specimen; does not overwrite existing national exports.
lod-model-pilot:
	$(CONDA_RUN) $(PYTHON) scripts/build_lod_model_pilot.py
	$(PYTHON) scripts/validate_lod_model.py data_quality/lod_model_pilot/model.ttl

lod-model-check:
	$(PYTHON) -m pytest -q tests/test_lod_model.py tests/test_lod_migration.py tests/test_gis_connections.py tests/test_census_sources.py

lod-identities:
	$(PYTHON) scripts/build_lod_identity_inventory.py

lod-1911-reporting:
	$(PYTHON) scripts/stage_1911_reporting_units.py
	$(PYTHON) scripts/export_1911_reporting_rdf.py
	$(PYTHON) scripts/validate_reporting_rdf.py \
		--database data_quality/lod_1911_reporting/source_observations.sqlite \
		--rdf data_quality/lod_1911_reporting/source_observations.nt.gz

lod-census-sources:
	$(PYTHON) scripts/stage_census_sources.py
	$(PYTHON) scripts/audit_census_sources.py

lod-census-source-rdf: lod-census-sources
	$(PYTHON) scripts/export_census_sources.py

lod-source-bindings: lod-census-sources lod-identities
	$(PYTHON) scripts/build_source_spatial_bindings.py

config-check:
	@echo "=== Resolved config ==="
	@$(PYTHON) scripts/_config.py

# ---- Stage 1: Spatial linking (slow; not in `all` graph) -------------------

link-csds: $(GDB)
	$(CONDA_RUN) bash scripts/link_all_years.sh

link-cds: $(GDB)
	$(CONDA_RUN) bash scripts/link_cd_all_years.sh
	$(CONDA_RUN) $(PYTHON) scripts/dump_cd_inventory.py

# ---- Stage 2: Persistent identity registries -------------------------------
# Reads cd_links_output/ + year_links_output/ (committed); writes the chain
# registries that downstream stages key against.

persistent_places_output/persistent_place_registry.csv \
persistent_places_output/place_chain_redirects.csv \
persistent_places_output/place_chain_bridge_review.csv \
persistent_places_output/place_chain_bridge_skipped.csv: \
		scripts/build_persistent_places.py \
		scripts/_normalize.py \
		year_links_output/SUMMARY_ALL_YEARS.md
	$(PYTHON) scripts/build_persistent_places.py

# cd_inventory.csv is the GDB-derived (cd_id, year) universe used for
# singleton chains. It replaced the old augmentation from neo4j_cidoc_crm_v2
# downstream outputs, which re-ingested chain ids as raw CDs on any rerun.
# Regenerates only when the dump script changes (needs the geo env + GDB,
# like the rest of the link stage); the CSV itself is committed.
cd_links_output/cd_inventory.csv: scripts/dump_cd_inventory.py
	$(CONDA_RUN) $(PYTHON) scripts/dump_cd_inventory.py

persistent_cds_output/persistent_cd_registry.csv: \
		scripts/build_persistent_cds.py \
		cd_links_output/SUMMARY_CD_LINKS.md \
		cd_links_output/cd_inventory.csv
	$(PYTHON) scripts/build_persistent_cds.py

# Typo-merge post-step: collapses Renfew/Renfrew-style same-year intra-province
# OCR variants into one chain. Edits the registry in place; we use a stamp file
# so Make knows when it has run against the current registry.
persistent_cds_output/typo_merges.csv: \
		scripts/typo_merge_cds.py \
		persistent_cds_output/persistent_cd_registry.csv
	$(PYTHON) scripts/typo_merge_cds.py

# ---- Stage 3: CIDOC-CRM (CSDs + CDs) ---------------------------------------
# build_neo4j_cidoc_crm_v2.py writes ~50 CSV files under neo4j_cidoc_crm_v2/.
# We pick e53_place_csd.csv as the rebuild stamp for the whole stage.

neo4j_cidoc_crm_v2/e53_place_csd.csv: \
		scripts/build_neo4j_cidoc_crm_v2.py \
		persistent_places_output/persistent_place_registry.csv \
		persistent_cds_output/typo_merges.csv \
		$(GDB)
	$(CONDA_RUN) $(PYTHON) scripts/build_neo4j_cidoc_crm_v2.py \
		--gdb $(GDB) --years $(YEARS) --out neo4j_cidoc_crm_v2 \
		--persistent-places persistent_places_output \
		--cd-chains persistent_cds_output

# CD presences + CSD-within-CD relationships (GDB-derived baseline).
neo4j_cidoc_crm_v2/p10_csd_within_cd_presence_1921.csv: \
		scripts/build_cd_presences.py \
		neo4j_cidoc_crm_v2/e53_place_csd.csv
	$(CONDA_RUN) $(PYTHON) scripts/build_cd_presences.py \
		--gdb $(GDB) --years $(YEARS) --out neo4j_cidoc_crm_v2

# Excel-overlay p10: replaces GDB-derived p10 with Excel-authoritative
# membership for 1851-1901. 1911 and 1921 keep their GDB rows untouched.
neo4j_cidoc_crm_v2/p10_csd_within_cd_presence_1901.csv: \
		scripts/build_p10_from_excel.py \
		neo4j_cidoc_crm_v2/p10_csd_within_cd_presence_1921.csv
	$(PYTHON) scripts/build_p10_from_excel.py

# Spatiotemporal overlap edges (P132).
neo4j_cidoc_crm_v2/p132_spatiotemporally_overlaps_with_csd.csv: \
		scripts/build_p132_overlaps.py \
		year_links_output/SUMMARY_ALL_YEARS.md
	$(PYTHON) scripts/build_p132_overlaps.py --out neo4j_cidoc_crm_v2

# E41 appellations (canonical names + OCR variants tied to persistent places).
neo4j_cidoc_crm_v2/e41_appellations.csv: \
		scripts/build_e41_appellations_v2.py \
		canonical_names_final.csv \
		persistent_places_output/persistent_place_registry.csv
	$(PYTHON) scripts/build_e41_appellations_v2.py \
		--canonical-names canonical_names_final.csv \
		--persistent-places persistent_places_output \
		--out neo4j_cidoc_crm_v2

# ---- Stage 4: Wikidata grounding → URI sidecar -----------------------------

neo4j_cidoc_crm_v2/e53_place_uri.csv: \
		scripts/join_wikidata_to_places.py \
		scripts/_normalize.py \
		neo4j_cidoc_crm_v2/e53_place_csd.csv \
		wikidata_grounding/csd_verified_matches.jsonl \
		wikidata_grounding/cd_verified_matches.jsonl \
		wikidata_grounding/csd_chain_qid_xrefs.csv
	$(PYTHON) scripts/join_wikidata_to_places.py

# Cross-chain QID xref: chains sharing a Wikidata QID, used by the renderer
# to emit the "Same Wikidata entity, other presences" link block.
neo4j_cidoc_crm_v2/e53_qid_xref.csv: \
		scripts/build_qid_xref.py \
		neo4j_cidoc_crm_v2/e53_place_uri.csv \
		neo4j_cidoc_crm_v2/e53_place_csd.csv \
		neo4j_cidoc_crm_v2/e53_place_cd.csv
	$(PYTHON) scripts/build_qid_xref.py

# ---- Stage 5: DCB persons (Dictionary of Canadian Biography) ---------------
# Independent of CD chains; depends only on persistent_place registries.

data/lincs_dcb_persons.json: scripts/parse_lincs_dcb.py $(LINCS_TTL)
	$(PYTHON) scripts/parse_lincs_dcb.py

data/lincs_strategy1_links.csv: \
		scripts/lincs_strategy1_wikidata.py \
		data/lincs_dcb_persons.json \
		neo4j_cidoc_crm_v2/e53_place_uri.csv
	$(PYTHON) scripts/lincs_strategy1_wikidata.py --use-cache

data/lincs_strategy3_links.csv: \
		scripts/lincs_strategy3_pip.py \
		data/lincs_dcb_persons.json \
		data/geonames_coords.csv \
		persistent_places_output/persistent_place_registry.csv
	$(CONDA_RUN) $(PYTHON) scripts/lincs_strategy3_pip.py

data/lincs_person_csd_links.csv: \
		scripts/lincs_combine_links.py \
		data/lincs_strategy1_links.csv \
		data/lincs_strategy3_links.csv
	$(PYTHON) scripts/lincs_combine_links.py

# ---- Stage 6: Site render --------------------------------------------------

# Kuzu / Ladybug pilot DB — generate_rag_pages.py reads from this. Defaults
# to all provinces (export_kuzu_pilot.py's --provinces default = all Canada).
# The directory name `on_kuzu` is historical; the DB now contains every
# province. Override via export_kuzu_pilot.py --provinces if needed.
pilot/on_kuzu/nodes/place.csv: \
		scripts/export_kuzu_pilot.py \
		neo4j_cidoc_crm_v2/e53_place_uri.csv \
		neo4j_cidoc_crm_v2/p10_csd_within_cd_presence_1901.csv \
		neo4j_cidoc_crm_v2/e41_appellations.csv
	$(PYTHON) scripts/export_kuzu_pilot.py

rag_site/index.html: \
		scripts/generate_rag_pages.py \
		scripts/_site_urls.py \
		scripts/_site_legacy.py \
		data/published_site_urls.csv \
		data/site_url_assignments.csv \
		data/site_legacy_records.json \
		neo4j_cidoc_crm_v2/e53_place_uri.csv \
		neo4j_cidoc_crm_v2/e53_qid_xref.csv \
		neo4j_cidoc_crm_v2/p10_csd_within_cd_presence_1901.csv \
		neo4j_cidoc_crm_v2/p132_spatiotemporally_overlaps_with_csd.csv \
		neo4j_cidoc_crm_v2/e41_appellations.csv \
		persistent_places_output/place_chain_redirects.csv \
		pilot/on_kuzu/nodes/place.csv \
		data/lincs_person_csd_links.csv
	$(PYTHON) scripts/generate_rag_pages.py --all
	$(PYTHON) scripts/emit_facts_jsonl.py --out rag_site

# ---- Stage 5b: 1881 Borealis residents pipeline ----------------------------
#
# Source: Borealis deposit doi:10.5683/SP3/FXZEVO (TCP/Dillon 1881 Canadian
# Census, individual-level, 4.28M rows). Renders /residents/ pages under each
# 1881 CSD presence URL. Single-shot dataset; 1891+ data is paywalled.
#
# Off the `make all` critical path so a residents-pipeline failure can't
# block the main site rebuild. Run explicitly via `make residents`.

.PHONY: residents residents-with-ttl

residents_1881_output/residents_1881_report.json: \
		scripts/prepare_1881_residents.py \
		scripts/_config.py \
		scripts/_fix_mojibake.py \
		residents_1881_output/unmatched_tcpuid_rescue.csv \
		persistent_places_output/tcpuid_year_to_place.csv \
		persistent_places_output/persistent_place_registry.csv
	$(PYTHON) scripts/prepare_1881_residents.py

# Rescue mapping for Borealis TCPUIDs absent from our 1881 chain registry.
# Generated from the quarantine parquet (after a first-pass prepare run);
# subsequent prepare runs apply it as a fallback join. Bootstraps via a
# guarded `make rescue` target — a fresh distclean creates it from an
# empty quarantine.
residents_1881_output/unmatched_tcpuid_rescue.csv: \
		scripts/rescue_unmatched_1881.py \
		scripts/_normalize.py \
		scripts/_fix_mojibake.py
	@if [ ! -f residents_1881_output/quarantine/unmatched_chain.parquet ]; then \
		echo "borealis_tcpuid,province,distnam,sdistnam,matched_chain,matched_chain_canonical,match_score,match_method" > $@; \
	else \
		$(PYTHON) scripts/rescue_unmatched_1881.py; \
	fi

residents_1881_output/dbirthpl_qid_xref.csv: \
		scripts/ground_dbirthpl_wikidata.py \
		residents_1881_output/residents_1881_report.json
	$(PYTHON) scripts/ground_dbirthpl_wikidata.py

residents_1881_output/csd_1881_summary.parquet: \
		scripts/aggregate_1881_residents.py \
		residents_1881_output/residents_1881_report.json
	$(PYTHON) scripts/aggregate_1881_residents.py

residents_1881_output/cidoc.stamp: \
		scripts/build_residents_cidoc.py \
		scripts/_site_urls.py \
		data/published_site_urls.csv \
		data/site_url_assignments.csv \
		residents_1881_output/residents_1881_report.json \
		residents_1881_output/dbirthpl_qid_xref.csv \
		persistent_places_output/persistent_place_registry.csv \
		persistent_places_output/tcpuid_year_to_place.csv
	$(PYTHON) scripts/build_residents_cidoc.py

# Render output is under rag_site/places/<prov>/<slug>-<tcpuid>-1881/residents/.
# We touch a stamp file to anchor the dependency. Note: depends on
# rag_site/index.html so generate_rag_pages.py runs first — that's the step
# that emits sitemap.xml from scratch, and the residents renderer augments
# the existing sitemap with overview URLs. Reverse order would lose the
# residents URLs every rebuild.
rag_site/.residents_1881_stamp: \
		scripts/render_1881_residents_pages.py \
		scripts/_fix_mojibake.py \
		residents_1881_output/cidoc.stamp \
		residents_1881_output/csd_1881_summary.parquet \
		residents_1881_output/dbirthpl_qid_xref.csv \
		rag_site/index.html
	$(PYTHON) scripts/render_1881_residents_pages.py
	@touch $@

residents: rag_site/.residents_1881_stamp

# Opt-in variant: also emit per-CSD residents.ttl sidecars for LOD harvesters.
# Adds ~500 MB to rag_site/. Only enable once GH Pages headroom confirmed.
residents-with-ttl:
	$(PYTHON) scripts/render_1881_residents_pages.py --with-ttl
	@touch rag_site/.residents_1881_stamp

# ---- Deploy -----------------------------------------------------------------

deploy: rdf-site-check
	@if [ ! -d "$(HGIS_REPO)" ]; then \
		echo "ERROR: hgiscanada repo not found at $(HGIS_REPO)"; \
		echo "Set [paths].hgiscanada_repo in config.local.toml"; exit 1; \
	fi
	rsync -av --delete \
		--exclude='.git/' --exclude='google*.html' \
		$(RDF_SITE)/ $(HGIS_REPO)/
	cd $(HGIS_REPO) && git add -A && \
		git commit -m "Deploy from $(shell git -C $(CURDIR) rev-parse --short HEAD)" && \
		git push origin main

# ---- Cleanup ----------------------------------------------------------------

# `make clean` keeps the expensive registries (persistent_*) and CIDOC CSVs
# but blows away the rendered site + DCB caches; useful for re-rendering.
clean:
	rm -rf rag_site/
	rm -f data/lincs_strategy1_links.csv data/lincs_strategy3_links.csv \
	      data/lincs_person_csd_links.csv

# `make distclean` regenerates everything except the spatial-linking output
# (year_links_output/, cd_links_output/) which is committed and slow.
distclean: clean
	rm -rf neo4j_cidoc_crm_v2/
	rm -rf persistent_cds_output/ persistent_places_output/
	rm -f data/lincs_dcb_persons.json data/lincs_dcb_links.csv
	rm -rf data_quality/
	rm -rf residents_1881_output/
