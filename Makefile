# =============================================================================
# HGIS Canada Knowledge Graph — pipeline orchestrator
#
# Default target `make all` rebuilds rag_site/ from the spatial-linking output
# (year_links_output/ + cd_links_output/), the GDB + Excel data at
# config.toml [paths].data_root, and the LINCS dump.
#
# The spatial linking step itself takes ~70 minutes and requires the conda
# `geo` environment + the GDB; it is broken out as `make link` and is NOT a
# dependency of `make all` so casual rebuilds don't re-run it.
#
# Usage:
#   make all       — rebuild rag_site/ from inputs
#   make site      — rebuild rag_site/ only (assumes upstream artifacts current)
#   make dcb       — rebuild DCB person links (Stage 5) only
#   make link      — re-run spatial linking (slow; needs GDB + geo env)
#   make deploy    — rsync rag_site/ to hgiscanada repo and push
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

.PHONY: all site dcb link link-csds link-cds deploy clean distclean config-check

all: rag_site/index.html

site: rag_site/index.html

dcb: data/lincs_person_csd_links.csv

link: link-csds link-cds

config-check:
	@echo "=== Resolved config ==="
	@$(PYTHON) scripts/_config.py

# ---- Stage 1: Spatial linking (slow; not in `all` graph) -------------------

link-csds: $(GDB)
	$(CONDA_RUN) bash scripts/link_all_years.sh

link-cds: $(GDB)
	$(CONDA_RUN) bash scripts/link_cd_all_years.sh

# ---- Stage 2: Persistent identity registries -------------------------------
# Reads cd_links_output/ + year_links_output/ (committed); writes the chain
# registries that downstream stages key against.

persistent_places_output/persistent_place_registry.csv: \
		scripts/build_persistent_places.py \
		year_links_output/SUMMARY_ALL_YEARS.md
	$(PYTHON) scripts/build_persistent_places.py

persistent_cds_output/persistent_cd_registry.csv: \
		scripts/build_persistent_cds.py \
		cd_links_output/SUMMARY_CD_LINKS.md
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
		neo4j_cidoc_crm_v2/e53_place_csd.csv \
		wikidata_grounding/csd_verified_matches.jsonl \
		wikidata_grounding/cd_verified_matches.jsonl
	$(PYTHON) scripts/join_wikidata_to_places.py

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
		neo4j_cidoc_crm_v2/e53_place_uri.csv \
		neo4j_cidoc_crm_v2/p10_csd_within_cd_presence_1901.csv \
		neo4j_cidoc_crm_v2/p132_spatiotemporally_overlaps_with_csd.csv \
		neo4j_cidoc_crm_v2/e41_appellations.csv \
		pilot/on_kuzu/nodes/place.csv \
		data/lincs_person_csd_links.csv
	$(PYTHON) scripts/generate_rag_pages.py --all
	$(PYTHON) scripts/emit_facts_jsonl.py --out rag_site

# ---- Deploy -----------------------------------------------------------------

deploy: rag_site/index.html
	@if [ ! -d "$(HGIS_REPO)" ]; then \
		echo "ERROR: hgiscanada repo not found at $(HGIS_REPO)"; \
		echo "Set [paths].hgiscanada_repo in config.local.toml"; exit 1; \
	fi
	rsync -av --delete \
		--exclude='.git/' --exclude='README.md' --exclude='google*.html' \
		rag_site/ $(HGIS_REPO)/
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
