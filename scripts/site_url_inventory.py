#!/usr/bin/env python3
"""Capture published addresses explicitly; audit a candidate site before deploy."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import quote

from _config import CONFIG
from _site_urls import (BASE, REGISTRY, REPO, FIELDS, UrlRegistry,
                        inspect_page, local_path, sitemap_paths)


def scan(root: Path):
    sitemap = sitemap_paths(root)
    rows = {}
    for n, file in enumerate(sorted(root.rglob("*.html")), 1):
        rel = file.relative_to(root).as_posix()
        if ".git" in file.relative_to(root).parts or rel.startswith("google"):
            continue  # hosting verification is independently preserved by rsync
        path = BASE + "/" + quote(rel[:-10] if rel.endswith("index.html") else rel, safe="/_-.~")
        row = inspect_page(file.read_text(encoding="utf-8"), path)
        row["in_sitemap"] = str(int(path in sitemap))
        rows[path] = row
        if n % 10000 == 0:
            print(f"Inspected {n:,} HTML pages", flush=True)
    missing = sitemap - rows.keys()
    if missing:
        raise ValueError(f"Sitemap addresses without HTML: {sorted(missing)[:10]}")
    return rows


def capture(root: Path, output: Path, verified_sitemap: Path | None):
    if output.exists():
        raise ValueError(f"Baseline already exists: {output}. Capture to a new file and review the diff.")
    sitemap_bytes = (root / "sitemap.xml").read_bytes()
    if verified_sitemap and verified_sitemap.read_bytes() != sitemap_bytes:
        raise ValueError("Downloaded live sitemap does not match the capture checkout")
    rows = scan(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", newline="", encoding="utf-8",
                                     dir=output.parent, delete=False) as f:
        pending = Path(f.name)
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows.values())
    try:
        # Check entity ownership before accepting a baseline. A failed capture
        # cannot leave an incomplete publication inventory at the final path.
        UrlRegistry(pending)
        pending.replace(output)
    finally:
        pending.unlink(missing_ok=True)
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            capture_output=True, text=True)
    summary = dict(
        source_commit=result.stdout.strip() if result.returncode == 0 else None,
        live_sitemap_verified=bool(verified_sitemap),
        sitemap_sha256=hashlib.sha256(sitemap_bytes).hexdigest(),
        registry_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        pages=len(rows), sitemap_urls=sum(r["in_sitemap"] == "1" for r in rows.values()),
        redirects=sum(bool(r["redirect_path"]) for r in rows.values()),
        noindex_pages=sum(r["noindex"] for r in rows.values()),
        biography_pages=sum(bool(r["people_links"]) for r in rows.values()),
        residents_pages=sum("/residents/" in p for p in rows),
        resident_anchors=sum(int(r["resident_anchor_count"]) for r in rows.values()))
    output.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


def audit(rows: dict, baseline: dict, generated_paths: set[str] | None = None) -> list[dict]:
    errors = []
    def error(path, reason, detail=""):
        errors.append(dict(path=path, reason=reason, detail=detail))

    def destination(path):
        seen = set()
        while path in rows:
            if path in seen:
                return None, "redirect_cycle"
            seen.add(path)
            row = rows[path]
            if not row["redirect_path"]:
                return row, ""
            path = row["redirect_path"]
        return None, "missing_redirect_target"

    for path, row in rows.items():
        dest, problem = destination(path)
        if problem:
            error(path, problem, row["redirect_path"])
            continue
        if row["redirect_path"]:
            if row["canonical_path"] != dest["path"]:
                error(path, "redirect_canonical_mismatch", dest["path"])
        elif row["canonical_path"] != path:
            error(path, "canonical_mismatch", row["canonical_path"])
        if row["in_sitemap"] == "1" and (row["redirect_path"] or row["noindex"]):
            error(path, "sitemap_contains_redirect_or_noindex")
        for target in json.loads(row["resident_links"] or "[]"):
            if target not in rows:
                error(path, "missing_resident_link_target", target)

    for path, old in baseline.items():
        if path not in rows:
            error(path, "published_url_missing")
            continue
        if (generated_paths is not None and old["entity_key"].startswith(("presence:", "place:", "cd:"))
                and path not in generated_paths):
            error(path, "published_page_not_handled_by_build")
        dest, problem = destination(path)
        if problem:
            continue
        if not old["redirect_path"] and old.get("noindex") not in ("True", True) and dest["noindex"]:
            error(path, "published_page_became_noindex")
        if old["in_sitemap"] == "1" and dest["in_sitemap"] != "1":
            error(path, "published_canonical_missing_from_sitemap", dest["path"])
        for field, reason in (("people_links", "biography_link_removed"),
                              ("resident_links", "resident_link_removed")):
            for link in set(json.loads(old[field] or "[]")) - set(json.loads(dest[field] or "[]")):
                error(path, reason, link)
        if old["resident_anchor_sha256"] and old["resident_anchor_sha256"] != dest["resident_anchor_sha256"]:
            error(path, "resident_citation_anchors_changed",
                  f"published={old['resident_anchor_count']}, candidate={dest['resident_anchor_count']}")
    return errors


def migration_report(baseline: dict, crosswalk: Path, output: Path):
    mapping = defaultdict(set)
    counts = Counter()
    with crosswalk.open(newline="") as f:
        for row in csv.DictReader(f):
            prefix = "place:" if row["level"] == "csd" else "cd:"
            mapping[prefix + row["legacy_unit_id"]].add(row["unit_id"] or "[coverage record]")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["path", "entity_key", "recommendation", "candidate_units",
                                             "has_biographies", "has_resident_links"])
        writer.writeheader()
        for row in baseline.values():
            if row["redirect_path"]:
                action = "retain_redirect_address"
            elif row["entity_key"].startswith(("presence:", "residents:")):
                action = "retain_snapshot_url"
            elif row["entity_key"] in mapping:
                units = mapping[row["entity_key"]]
                if len(units) > 1:
                    action = "review_split_keep_explanatory_page"
                elif "[coverage record]" in units:
                    action = "retain_url_explain_coverage"
                elif row["entity_key"].split(":", 1)[1] in units:
                    action = "retain_identity_url"
                else:
                    action = "review_single_successor_assignment"
            elif row["entity_key"].startswith(("place:", "cd:")):
                action = "review_unmatched_legacy_identity"
            else:
                action = "retain_supporting_page"
            counts[action] += 1
            writer.writerow(dict(path=row["path"], entity_key=row["entity_key"], recommendation=action,
                                 candidate_units="|".join(sorted(mapping.get(row["entity_key"], []))),
                                 has_biographies=bool(row["people_links"]),
                                 has_resident_links=bool(row["resident_links"])))
    print(json.dumps(counts, indent=2))


def audit_fact_links(root: Path, rows: dict) -> tuple[int, list[dict]]:
    subjects = set()
    for file in sorted((root / "facts").glob("*.jsonl")):
        with file.open() as f:
            for line in f:
                subjects.add(local_path(json.loads(line)["subject"]))
    return len(subjects), [dict(path=path, reason="missing_fact_subject_page", detail="")
                           for path in sorted(subjects - rows.keys())]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("capture")
    p.add_argument("--site", type=Path, default=CONFIG.hgiscanada_repo)
    p.add_argument("--output", type=Path, default=REGISTRY)
    p.add_argument("--verified-sitemap", type=Path)
    p = sub.add_parser("check")
    p.add_argument("--site", type=Path, default=REPO / "rag_site")
    p.add_argument("--registry", type=Path, default=REGISTRY)
    p.add_argument("--report", type=Path, default=REPO / "data_quality/site_urls/validation.json")
    p.add_argument("--require-build-manifest", action="store_true")
    p = sub.add_parser("migration")
    p.add_argument("--registry", type=Path, default=REGISTRY)
    p.add_argument("--crosswalk", type=Path, default=REPO / "data_quality/lod_identity/legacy_identity_crosswalk.csv")
    p.add_argument("--output", type=Path, default=REPO / "data_quality/site_urls/migration_review.csv")
    args = ap.parse_args()
    if args.command == "capture":
        capture(args.site, args.output, args.verified_sitemap)
    else:
        baseline = UrlRegistry(args.registry).rows
        if args.command == "migration":
            migration_report(baseline, args.crosswalk, args.output)
        else:
            rows = scan(args.site)
            build_manifest = args.site / ".site-build-urls.json"
            generated = set(json.loads(build_manifest.read_text())) if build_manifest.exists() else None
            errors = audit(rows, baseline, generated)
            fact_subjects, fact_errors = audit_fact_links(args.site, rows)
            errors.extend(fact_errors)
            if args.require_build_manifest and generated is None:
                errors.append(dict(path=".site-build-urls.json", reason="missing_build_manifest", detail="Run the full page generator."))
            report = dict(pages=len(rows), protected_urls=len(baseline), fact_subjects=fact_subjects, errors=len(errors),
                          error_counts=dict(Counter(e["reason"] for e in errors)), findings=errors)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps({k: v for k, v in report.items() if k != "findings"}, indent=2))
            raise SystemExit(bool(errors))


if __name__ == "__main__":
    main()
