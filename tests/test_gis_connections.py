"""Analytical fixtures for the geometry preparation and correspondence audit."""

import sys
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import GeometryCollection, LineString, Polygon, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from _gis import overlap_table, polygonal, prepare_csd_layer
from _gis import dissolve_cds
from audit_gis_connections import attach_metadata, compare_legacy
from link_csd_years_spatial_v2 import all_link_records, link_year_pair
from link_cd_years_spatial import compute_overlap, classify_links
from build_persistent_places import _gap_supported
from validate_gis_rebuild import validate_tables, compare_projections
import pandas as pd


def layer(geometries, ids=None, names=None, crs="EPSG:3347"):
    size = len(geometries)
    return gpd.GeoDataFrame({
        "TCPUID_CSD_1851": ids or [f"ON{i:06}" for i in range(size)],
        "PR_1851": ["ON"] * size,
        "Name_CD_1851": ["County"] * size,
        "Name_CSD_1851": names or ["Unit"] * size,
        "geometry": geometries,
    }, crs=crs)


def test_split_preserves_both_successors_and_exact_area_fractions():
    a = gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs=3347, index=[99])
    b = gpd.GeoDataFrame(geometry=[box(0, 0, 3, 10), box(3, 0, 10, 10)], crs=3347, index=[7, 25])
    result = overlap_table(a, b)
    assert result.frac_from.tolist() == pytest.approx([.3, .7])
    assert result.frac_to.tolist() == pytest.approx([1, 1])
    assert result.iou.tolist() == pytest.approx([.3, .7])
    assert result.overlap_sqm.sum() == pytest.approx(100)
    reverse = overlap_table(b, a)
    assert reverse.frac_from.tolist() == pytest.approx([1, 1])
    assert reverse.frac_to.tolist() == pytest.approx([.3, .7])


def test_many_to_many_redistribution_is_not_discarded_by_iou_threshold():
    a = gpd.GeoDataFrame(geometry=[box(i, 0, i + 1, 10) for i in range(10)], crs=3347)
    b = gpd.GeoDataFrame(geometry=[box(0, j, 10, j + 1) for j in range(10)], crs=3347)
    result = overlap_table(a, b)
    assert len(result) == 100
    assert result.iou.tolist() == pytest.approx([1 / 19] * 100)
    assert result.groupby("from_index").frac_from.sum().tolist() == pytest.approx([1] * 10)


def test_touching_boundaries_are_not_area_correspondences():
    a = gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)], crs=3347)
    b = gpd.GeoDataFrame(geometry=[box(1, 0, 2, 1)], crs=3347)
    assert overlap_table(a, b).empty


def test_named_cd_with_only_no_data_children_remains_a_coverage_record():
    csds = gpd.GeoDataFrame(dict(pr=['NL', 'ON', 'ON'], cd_name=['Newfoundland', 'County', 'County'],
                                csd_name=['NO DATA', 'Township', 'NO DATA'],
                                geometry=[box(0,0,1,1),box(2,0,3,1),box(3,0,4,1)]), crs=3347)
    cds = dissolve_cds(csds)
    assert bool(cds.set_index('cd_name').loc['Newfoundland', 'is_coverage_record'])
    assert not bool(cds.set_index('cd_name').loc['County', 'is_coverage_record'])
    table = attach_metadata(overlap_table(cds, cds), cds, cds, 'cd', 1851, 1861)
    assert table.set_index('name_from').loc['Newfoundland', 'involves_no_data']
    rebuilt = compute_overlap(cds, cds)
    assert rebuilt.set_index('cd_from').loc['CD_NL_Newfoundland', 'involves_no_data']


def test_duplicate_identifier_pieces_are_dissolved_with_audit():
    raw = layer([box(0, 0, 1, 1), box(2, 0, 3, 1)], ids=["QC053009"] * 2)
    clean, audit = prepare_csd_layer(raw, 1851)
    assert len(clean) == 1
    assert clean.geometry.iloc[0].area == pytest.approx(2)
    assert audit[0]["action"] == "dissolve_duplicate_id"


def test_conflicting_duplicate_metadata_is_not_silently_merged():
    raw = layer([box(0, 0, 1, 1)] * 2, ids=["ON000001"] * 2, names=["Town", "Township"])
    with pytest.raises(ValueError, match="conflicting metadata"):
        prepare_csd_layer(raw, 1851)


def test_invalid_bowtie_retains_both_polygon_parts():
    raw = layer([Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])])
    clean, audit = prepare_csd_layer(raw, 1851)
    assert clean.is_valid.all()
    assert clean.geometry.iloc[0].area == pytest.approx(2)
    assert audit[0]["action"] == "repair_geometry"


def test_geometry_collection_keeps_polygon_area():
    result = polygonal(GeometryCollection([box(0, 0, 2, 2), LineString([(3, 0), (3, 1)])]))
    assert result.area == pytest.approx(4)


@pytest.mark.parametrize("geometry", [None, Polygon(), LineString([(0, 0), (1, 1)])])
def test_missing_or_nonpolygon_geometry_fails(geometry):
    with pytest.raises(ValueError):
        polygonal(geometry)


def test_missing_crs_fails():
    with pytest.raises(ValueError, match="CRS"):
        prepare_csd_layer(layer([box(0, 0, 1, 1)], crs=None), 1851)


def test_self_overlap_excludes_self_and_reverse_duplicates():
    g = gpd.GeoDataFrame(geometry=[box(0, 0, 2, 2), box(1, 0, 3, 2)], crs=3347)
    result = overlap_table(g, g, same_layer=True)
    assert len(result) == 1
    assert result.overlap_sqm.iloc[0] == pytest.approx(2)


def test_empty_correspondence_audit_has_headers_and_flags():
    a, _ = prepare_csd_layer(layer([box(0, 0, 1, 1)]), 1851)
    b, _ = prepare_csd_layer(layer([box(2, 0, 3, 1)]), 1851)
    current = attach_metadata(overlap_table(a, b), a, b, "csd", 1851, 1861)
    legacy = pd.DataFrame(columns=["id_from", "id_to", "iou", "frac_from", "frac_to"])
    summary, *_ = compare_legacy(current, legacy, a, b, "csd")
    assert summary["all_positive_correspondences"] == 0


def test_production_linker_retains_weak_correspondences_separately():
    a, _ = prepare_csd_layer(layer([box(i, 0, i + 1, 10) for i in range(10)]), 1851)
    b, _ = prepare_csd_layer(layer([box(0, j, 10, j + 1) for j in range(10)]), 1851)
    records = all_link_records(a, b, 1851, 1861)
    assert len(records) == 100
    assert {r["relationship"] for r in records} == {"LOW_OVERLAP"}
    assert not any(r["historical_succession_verified"] for r in records)
    assert link_year_pair(a, b, 1851, 1861, records=records) == ([], [])


def test_empty_cd_partitions_keep_schema():
    a = gpd.GeoDataFrame({"cd_id": ["A"]}, geometry=[box(0, 0, 1, 1)], crs=3347)
    b = gpd.GeoDataFrame({"cd_id": ["B"]}, geometry=[box(2, 0, 3, 1)], crs=3347)
    links = compute_overlap(a, b)
    high, ambiguous = classify_links(links, a, b)
    assert "cd_from" in high.columns and "cd_from" in ambiguous.columns


def test_cd_correspondences_keep_small_positive_intersections():
    a = gpd.GeoDataFrame({"cd_id": ["A"]}, geometry=[box(0, 0, 1, 1)], crs=3347)
    b = gpd.GeoDataFrame({"cd_id": ["B"]}, geometry=[box(.5, 0, 1.5, 1)], crs=3347)
    result = compute_overlap(a, b)
    assert result.overlap_sqm.tolist() == pytest.approx([.5])


@pytest.mark.parametrize("centroids", [None, {}, {("A", 1851): (45., -75.)},
                                      {("A", 1851): (45., -75.), ("B", 1881): (float("nan"), -75.)}])
def test_name_bridge_fails_closed_without_centroid_evidence(centroids):
    supported, reason = _gap_supported([("A", 1851)], [("B", 1881)], {}, centroids)
    assert not supported
    assert reason == "missing_centroid_evidence"


def test_name_bridge_checks_distance_when_both_centroids_exist():
    near = {("A", 1851): (45., -75.), ("B", 1881): (45.01, -75.)}
    assert _gap_supported([("A", 1851)], [("B", 1881)], {}, near) == (True, "medium")
    far = {("A", 1851): (45., -75.), ("B", 1881): (50., -110.)}
    assert not _gap_supported([("A", 1851)], [("B", 1881)], {}, far)[0]


def comparison_fixture():
    return pd.DataFrame([dict(id_from="A", id_to="B", iou=.5, frac_from=.5,
                              frac_to=1., overlap_sqm=10000., area_from_sqm=20000.,
                              area_to_sqm=10000., area_crs="EPSG:3347",
                              evidence_kind="computed_polygon_intersection",
                              historical_succession_verified=False, material_overlap=True,
                              spatial_relation="LATER_WITHIN_EARLIER")])


def test_validation_detects_missing_pair_and_altered_metrics():
    original = comparison_fixture()
    assert validate_tables(original, original)["errors"] == 0
    assert validate_tables(original, original.iloc[:0])["errors"] > 0
    changed = original.assign(frac_from=.6)
    assert validate_tables(original, changed)["errors"] == 1
    assert validate_tables(original, original.assign(area_crs="ESRI:102001"))["errors"] == 1
    assert validate_tables(original, original.assign(historical_succession_verified=True))["errors"] == 1
    with pytest.raises(pd.errors.MergeError):
        validate_tables(original, pd.concat([original, original]))


def test_projection_comparison_does_not_hide_missing_material_pairs():
    original = comparison_fixture()
    summary, review = compare_projections(original, original.iloc[:0])
    assert summary["material_pairs_missing_in_one_projection"] == 1
    assert len(review) == 1
    summary, review = compare_projections(original, original)
    assert summary["max_fraction_delta"] == 0
    assert review.empty
