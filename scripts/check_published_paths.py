#!/usr/bin/env python3
"""Fail if a site build would drop any path that is already published.

Persistent place and CD pages are public URLs (Google-indexed, cited), and
`make deploy` mirrors rag_site/ into the hgiscanada repo with
`rsync --delete`. A build that silently omits pages — e.g. deploying without
re-rendering the 1881 residents pages — would delete them from the live site.

The baseline, data/published_site_paths.txt, lists every file of the
published site (one site-relative path per line). It was captured from the
hgiscanada deploy 9275f55eec (Deploy from 8c821a8b3, 2026-08-10). New paths
are allowed; missing ones fail the check.

Usage:
    python3 scripts/check_published_paths.py                 # check rag_site/
    python3 scripts/check_published_paths.py --site DIR
    python3 scripts/check_published_paths.py --write-baseline --site DIR
"""
import argparse
import sys
from fnmatch import fnmatch
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_SITE = REPO / "rag_site"
DEFAULT_BASELINE = REPO / "data" / "published_site_paths.txt"

# Mirrors the rsync excludes in the Makefile `deploy` rule: these live only in
# the hgiscanada repo and are never produced by the build.
DEPLOY_EXCLUDES = ("README.md", "google*.html")
# Build-local bookkeeping that is not deployed content.
LOCAL_ONLY = (".residents_1881_stamp",)


def site_paths(site: Path) -> set[str]:
    out = set()
    for p in site.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(site).as_posix()
        if rel.startswith(".git/") or rel in LOCAL_ONLY:
            continue
        if "/" not in rel and any(fnmatch(rel, pat) for pat in DEPLOY_EXCLUDES):
            continue
        out.add(rel)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site", type=Path, default=DEFAULT_SITE)
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    ap.add_argument("--write-baseline", action="store_true",
                    help="record --site as the new baseline instead of checking")
    ap.add_argument("--show", type=int, default=25,
                    help="how many missing paths to list (default 25)")
    args = ap.parse_args()

    if not args.site.is_dir():
        print(f"ERROR: site directory not found: {args.site}", file=sys.stderr)
        return 2
    built = site_paths(args.site)

    if args.write_baseline:
        args.baseline.write_text("".join(f"{p}\n" for p in sorted(built)))
        print(f"Wrote {len(built):,} paths to {args.baseline}")
        return 0

    baseline = set(args.baseline.read_text().split())
    missing = sorted(baseline - built)
    added = len(built - baseline)
    print(f"Baseline {len(baseline):,} paths; build {len(built):,} "
          f"({added:,} new, {len(missing):,} missing)")
    if missing:
        print("ERROR: build would remove published paths:", file=sys.stderr)
        by_top = {}
        for p in missing:
            top = p.split("/", 1)[0]
            by_top[top] = by_top.get(top, 0) + 1
        for top, n in sorted(by_top.items(), key=lambda kv: -kv[1]):
            print(f"  {top}/: {n:,}", file=sys.stderr)
        for p in missing[:args.show]:
            print(f"  - {p}", file=sys.stderr)
        if len(missing) > args.show:
            print(f"  ... and {len(missing) - args.show:,} more", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
