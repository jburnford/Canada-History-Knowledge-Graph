#!/usr/bin/env python3
"""Check static assets/internal links and preserve published biographical text."""
import argparse
from collections import Counter
from functools import lru_cache
import html
import json
from pathlib import Path
import re
from urllib.parse import quote, urljoin, urlsplit

from _config import CONFIG, REPO_ROOT
from _site_urls import BASE, ORIGIN, UrlRegistry, page_file

ATTR = re.compile(r'<(?:a|link|script|img)\b[^>]*?\b(?:href|src)\s*=\s*["\']([^"\']+)["\']', re.I)
IDS = re.compile(r'\bid\s*=\s*["\']([^"\']+)["\']')
TABLES = re.compile(r'<table\b[^>]*class=["\'][^"\']*dcb-persons[^"\']*["\'][^>]*>.*?</table>', re.S | re.I)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--site', type=Path, default=REPO_ROOT / 'data_quality/rdf_site')
    ap.add_argument('--published', type=Path, default=CONFIG.hgiscanada_repo)
    ap.add_argument('--report', type=Path, default=REPO_ROOT / 'data_quality/rdf_site_links_validation.json')
    args = ap.parse_args()
    findings, counts = [], Counter()

    @lru_cache(maxsize=250000)
    def exists(path):
        return page_file(args.site, path).is_file()

    @lru_cache(maxsize=256)
    def anchors(path):
        return set(IDS.findall(page_file(args.site, path).read_text()))

    for file in args.site.rglob('*.html'):
        rel = file.relative_to(args.site).as_posix()
        path = BASE + '/' + quote(rel[:-10] if rel.endswith('index.html') else rel, safe='/_-.~')
        text = file.read_text()
        local_ids = None
        for raw in set(ATTR.findall(text)):
            href = html.unescape(raw)
            if href.startswith(('http://', 'https://')) and not href.startswith(ORIGIN + BASE + '/'):
                continue
            target = urlsplit(urljoin(ORIGIN + path, href))
            if target.scheme not in {'http', 'https'} or target.netloc != urlsplit(ORIGIN).netloc:
                continue
            if not target.path.startswith(BASE + '/'):
                continue
            counts['internal_links'] += 1
            if not exists(target.path):
                findings.append(dict(page=path, target=href, reason='missing_internal_file'))
            elif target.fragment:
                if target.path == path:
                    if local_ids is None:
                        local_ids = set(IDS.findall(text))
                    ids = local_ids
                else:
                    ids = anchors(target.path)
                if target.fragment not in ids:
                    findings.append(dict(page=path, target=href, reason='missing_fragment'))
        counts['html_pages'] += 1
        if counts['html_pages'] % 10000 == 0:
            print(f'Checked links in {counts["html_pages"]:,} pages', flush=True)
    for old in UrlRegistry().rows.values():
        if old['people_links'] and not old['redirect_path']:
            before = page_file(args.published, old['path']).read_text()
            after = page_file(args.site, old['path']).read_text()
            for table in TABLES.findall(before):
                if table not in after:
                    findings.append(dict(page=old['path'], reason='biographical_table_changed'))
                counts['biographical_tables'] += 1
    report = dict(**counts, errors=len(findings), findings=findings)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'findings'}, indent=2))
    raise SystemExit(bool(findings))


if __name__ == '__main__':
    main()
