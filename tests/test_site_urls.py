"""Publication contracts: names may change; citations and resident anchors survive."""
import csv
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import _site_urls as site_urls
from _site_urls import BASE, FIELDS, UrlRegistry, inspect_page, local_path
from site_url_inventory import audit, audit_fact_links
from _site_legacy import render_legacy


PATH = BASE + "/places/on/old-name-on001001-1881/"


def page(path=PATH, content="", redirect="", key="presence:ON001001_1881"):
    target = redirect or path
    refresh = f'<meta http-equiv="refresh" content="0; url={target}">' if redirect else ""
    text = f'<head><link rel="canonical" href="https://jimclifford.ca{target}">{refresh}</head>{content}'
    row = inspect_page(text, path)
    row.update(entity_key=key, in_sitemap="0" if redirect else "1")
    return row


def registry(tmp_path, rows, assignments=()):
    p = tmp_path / "urls.csv"
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    a = tmp_path / "assignments.csv"
    with a.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["entity_key", "published_path", "reason"])
        w.writeheader()
        w.writerows(assignments)
    return UrlRegistry(p, a)


def test_name_and_province_corrections_do_not_change_published_address(tmp_path):
    r = registry(tmp_path, [page()])
    assert r.resolve("presence:ON001001_1881", BASE + "/places/qc/corrected-name/", BASE) == PATH
    assert r.resolve("presence:ON001001_1881", "/preview/new-name/", "/preview") == PATH.replace(BASE, "/preview")


def test_reviewed_identifier_replacement_reuses_old_url(tmp_path):
    r = registry(tmp_path, [page()], [dict(entity_key="place:new", published_path=PATH, reason="Reviewed one-to-one correction")])
    assert r.resolve("place:new", BASE + "/new/") == PATH
    with pytest.raises(ValueError, match="collision"):
        r.resolve("presence:ON001001_1881", PATH)


def test_new_entity_cannot_take_an_existing_address(tmp_path):
    r = registry(tmp_path, [page()])
    with pytest.raises(ValueError, match="overwrite"):
        r.resolve("place:unrelated", PATH)


def test_new_entities_cannot_collide(tmp_path):
    r = registry(tmp_path, [])
    r.resolve("place:first", PATH)
    with pytest.raises(ValueError, match="collision"):
        r.resolve("place:second", PATH)


def test_hidden_census_detail_gets_new_address_but_residents_stay(tmp_path, monkeypatch):
    old_place = page(key="place:PLACE_ON001001_1881")
    residents_path = PATH + "residents/"
    resident = page(residents_path, key="residents:ON001001_1881:")
    r = registry(tmp_path, [old_place, resident])
    monkeypatch.setattr(site_urls, "registry", lambda: r)
    census = site_urls.presence_url("Old Name", "ON001001", 1881)
    assert census == PATH + "census-1881/"
    assert site_urls.residents_url("ON001001", census) == residents_path
    assert r.resolve("place:PLACE_ON001001_1881", PATH) == PATH


def test_intentionally_noindex_resident_leaf_is_preserved():
    path = PATH + "residents/a/b/"
    old = dict(page(path, key="residents:ON001001_1881:a/b/"), noindex=True, in_sitemap="0")
    assert not audit({path: old}, {path: old})


def test_archival_page_keeps_original_links_and_rejects_tampering():
    original = '<html><head></head><body><a href="/hgiscanada/source/">Source record</a></body></html>'
    record = dict(path=PATH, kind="archive", published_html=original,
                  published_html_sha256=hashlib.sha256(original.encode()).hexdigest())
    path, body = render_legacy(record)
    assert path == PATH
    assert '<a href="/hgiscanada/source/">Source record</a>' in body
    assert "Archived census district page" in body
    record["published_html"] += "unexpected change"
    with pytest.raises(ValueError, match="hash mismatch"):
        render_legacy(record)


def test_resident_section_is_attached_to_the_actual_1881_snapshot(monkeypatch):
    import generate_rag_pages as pages
    monkeypatch.setattr(pages, "_residents_1881_counts", lambda: {"place": 278})
    monkeypatch.setattr(pages, "_residents_1881_snapshots", lambda: {"place": {"QC091009"}})
    monkeypatch.setattr(pages, "residents_url", lambda *args: BASE + "/correct/residents/")
    assert pages.render_residents_1881_link("place", 1881, PATH, "QC076015") == ""
    assert BASE + "/correct/residents/" in pages.render_residents_1881_link("place", 1881, PATH, "QC091009")


def test_year_suffix_on_all_years_page_is_not_a_snapshot():
    row = inspect_page('<head></head><strong>Persistent place ID:</strong><code>PLACE_ON001001_1881</code>', PATH)
    assert row["entity_key"] == "place:PLACE_ON001001_1881"
    row = inspect_page('<head></head><strong>TCP UID:</strong><code>ON001001</code>', PATH)
    assert row["entity_key"] == "presence:ON001001_1881"
    row = inspect_page('<head></head><strong>TCP UID:</strong><code>QC20N001</code>',
                       BASE + "/places/qc/abitibi-qc20n001-1911/")
    assert row["entity_key"] == "presence:QC20N001_1911"


def test_biographies_and_resident_links_cannot_silently_disappear():
    bio = "https://www.biographi.ca/en/bio/example_1E.html"
    residents = PATH + "residents/"
    old = page(content=f'<a href="{bio}">Person</a><a href="{residents}">Residents</a>')
    errors = audit({PATH: page()}, {PATH: old})
    assert {e["reason"] for e in errors} == {"biography_link_removed", "resident_link_removed"}


def test_resident_anchors_are_checked_even_when_row_counts_are_equal():
    path = PATH + "residents/a/a/"
    old = page(path, '<tr id="p-123"></tr>', key="residents:ON001001_1881:a/a/")
    new = page(path, '<tr id="p-456"></tr>', key=old["entity_key"])
    assert audit({path: new}, {path: old})[0]["reason"] == "resident_citation_anchors_changed"
    assert not audit({path: old}, {path: old})


def test_missing_url_and_stale_output_fail():
    old = page()
    assert audit({}, {PATH: old})[0]["reason"] == "published_url_missing"
    assert audit({PATH: old}, {PATH: old}, set())[0]["reason"] == "published_page_not_handled_by_build"


def test_facts_cannot_reference_a_missing_census_page(tmp_path):
    (tmp_path / "facts").mkdir()
    (tmp_path / "facts/1881.jsonl").write_text(json.dumps({"subject": "https://jimclifford.ca" + PATH}) + "\n")
    assert audit_fact_links(tmp_path, {PATH: page()}) == (1, [])
    count, errors = audit_fact_links(tmp_path, {})
    assert count == 1
    assert errors[0]["reason"] == "missing_fact_subject_page"


def test_redirect_resolves_to_canonical_content_and_preserves_features():
    bio = '<a href="https://www.biographi.ca/en/bio/example_1E.html">Person</a>'
    target = BASE + "/corrected/"
    old = page(content=bio)
    rows = {PATH: page(redirect=target), target: page(target, bio)}
    assert not audit(rows, {PATH: old})
    rows[target] = page(target, redirect=PATH)
    assert "redirect_cycle" in {e["reason"] for e in audit(rows, {PATH: old})}
    del rows[target]
    assert "missing_redirect_target" in {e["reason"] for e in audit(rows, {PATH: old})}


def test_sitemap_and_noindex_regressions_fail():
    old = page()
    new = dict(old, in_sitemap="0", noindex=True)
    assert {e["reason"] for e in audit({PATH: new}, {PATH: old})} == {
        "published_canonical_missing_from_sitemap", "published_page_became_noindex"}


@pytest.mark.parametrize("path", [BASE + "/../outside/", BASE + "/%2e%2e/outside/", "https://example.com" + PATH])
def test_registry_cannot_escape_site(path):
    with pytest.raises(ValueError):
        local_path(path)
