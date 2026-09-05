"""Published URL ownership, independent of display names and graph identifiers.

The committed inventory is a publication baseline, not a disposable build output.
Only an explicit capture updates it. All site producers use the same resolver.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import re
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "data" / "published_site_urls.csv"
ASSIGNMENTS = REPO / "data" / "site_url_assignments.csv"
ORIGIN = "https://jimclifford.ca"
BASE = "/hgiscanada"
FIELDS = ["path", "entity_key", "canonical_path", "redirect_path", "in_sitemap", "noindex",
          "people_links", "resident_links", "resident_anchor_count", "resident_anchor_sha256"]


def local_path(url: str, origin: str = ORIGIN, base: str = BASE) -> str:
    parsed = urlsplit(url)
    if parsed.netloc and parsed.netloc != urlsplit(origin).netloc:
        raise ValueError(f"External URL is not a site address: {url}")
    path = parsed.path
    if not path.startswith(base + "/"):
        raise ValueError(f"URL outside site prefix: {url}")
    decoded = unquote(path)
    if "\\" in decoded or any(p in {".", ".."} for p in decoded.split("/")):
        raise ValueError(f"Unsafe URL path: {url}")
    return path


def page_file(root: Path, path: str, base: str = BASE) -> Path:
    # Static servers decode URL escapes before looking up filesystem names.
    rel = unquote(local_path(path, base=base)[len(base):]).lstrip("/")
    return root / rel / "index.html" if path.endswith("/") else root / rel


def sitemap_paths(root: Path, origin: str = ORIGIN, base: str = BASE) -> set[str]:
    pending, seen, paths = [root / "sitemap.xml"], set(), set()
    while pending:
        file = pending.pop()
        if file in seen:
            raise ValueError(f"Repeated or cyclic sitemap: {file}")
        seen.add(file)
        tree = ET.parse(file)
        locations = [local_path(e.text, origin, base) for e in tree.iter()
                     if e.tag.rsplit("}", 1)[-1] == "loc" and e.text]
        if tree.getroot().tag.rsplit("}", 1)[-1] == "sitemapindex":
            pending.extend(page_file(root, path, base) for path in locations)
        else:
            paths.update(locations)
    return paths


class Head(HTMLParser):
    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.canonical = ""
        self.redirect = ""
        self.noindex = False
        end = re.search(r"</head\s*>", text, re.I)
        self.feed(text[:end.start()] if end else text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and "canonical" in (a.get("rel") or "").lower().split():
            self.canonical = a.get("href") or ""
        if tag == "meta":
            if (a.get("name") or "").lower() == "robots":
                self.noindex = "noindex" in (a.get("content") or "").lower()
            if (a.get("http-equiv") or "").lower() == "refresh":
                m = re.search(r"url\s*=\s*(.*)", a.get("content") or "", re.I)
                if m:
                    self.redirect = m[1].strip().strip("\"'")


def inspect_page(text: str, path: str, origin: str = ORIGIN, base: str = BASE) -> dict:
    head = Head(text)
    def address(url):
        return local_path(urljoin(origin + path, url), origin, base) if url else ""
    links = {html.unescape(m[1]) for m in re.findall(
        r"<a\b[^>]*\bhref\s*=\s*([\"'])(.*?)\1", text, re.I | re.S)}
    people = sorted(u for u in links if urlsplit(u).hostname in {"biographi.ca", "www.biographi.ca"}
                    and "/bio/" in urlsplit(u).path)
    residents = sorted({address(u) for u in links
                        if "/residents/" in urlsplit(u).path
                        and urlsplit(urljoin(origin + path, u)).netloc == urlsplit(origin).netloc})
    anchors = sorted(re.findall(r"\bid\s*=\s*[\"'](p-[^\"']+)[\"']", text))
    # Source TCPUID/year identifies the published map snapshot even if its
    # all-years chain or display name changes. Never infer a chain from a slug.
    m = re.search(r"-([a-z]{2}[a-z0-9]+)-(18\d{2}|19\d{2})/", path, re.I)
    key = ""
    tcpuid = re.search(r"TCP UID:</strong>\s*<code>([^<]+)</code>", text)
    place_id = re.search(r"Persistent place ID:</strong>\s*<code>([^<]+)</code>", text)
    if m and "/residents/" in path:
        key = f"residents:{m[1].upper()}_{m[2]}:" + path.split("/residents/", 1)[1]
    elif m and tcpuid:
        if m[1].upper() != tcpuid[1].upper():
            raise ValueError(f"Published URL and embedded TCPUID disagree: {path}")
        key = f"presence:{m[1].upper()}_{m[2]}"
    elif "/places/" in path and place_id:
        key = "place:" + html.unescape(place_id[1])
    elif "/cds/" in path:
        m = re.search(r"HGIS Canada CD ID:</strong>\s*<code>([^<]+)</code>", text)
        if m:
            key = "cd:" + html.unescape(m[1])
    return dict(path=path, entity_key=key, canonical_path=address(head.canonical),
                redirect_path=address(head.redirect), in_sitemap="0",
                people_links=json.dumps(people, separators=(",", ":")) if people else "",
                resident_links=json.dumps(residents, separators=(",", ":")) if residents else "",
                resident_anchor_count=str(len(anchors)),
                resident_anchor_sha256=hashlib.sha256("\n".join(anchors).encode()).hexdigest() if anchors else "",
                noindex=head.noindex)


class UrlRegistry:
    def __init__(self, registry: Path = REGISTRY, assignments: Path = ASSIGNMENTS):
        with registry.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.rows = {r["path"]: r for r in rows}
        if len(self.rows) != len(rows):
            raise ValueError("Duplicate published URL in registry")
        self.by_entity = {}
        self.claims = {}
        candidates = {}
        for row in rows:
            local_path(row["path"])
            key = row["entity_key"]
            if key and not row["redirect_path"] and row["canonical_path"] == row["path"]:
                candidates.setdefault(key, []).append(row)
        for key, choices in candidates.items():
            preferred = [r for r in choices if r["in_sitemap"] == "1"] or choices
            if len(preferred) != 1:
                raise ValueError(f"Ambiguous published URLs for {key}: {[r['path'] for r in preferred]}")
            self.by_entity[key] = preferred[0]["path"]
        if assignments.exists():
            with assignments.open(newline="", encoding="utf-8") as f:
                seen = set()
                for row in csv.DictReader(f):
                    key, path = row["entity_key"], row["published_path"]
                    if key in seen or path not in self.rows or not row["reason"].strip():
                        raise ValueError(f"Invalid reviewed URL assignment: {row}")
                    seen.add(key)
                    self.by_entity[key] = path

    def resolve(self, key: str, proposed: str, base: str = BASE) -> str:
        original = self.by_entity.get(key)
        path = original or BASE + proposed[len(base):]
        local_path(path)
        owner = self.claims.setdefault(path, key)
        if owner != key:
            raise ValueError(f"URL collision: {path} claimed by {owner} and {key}")
        reserved = self.rows.get(path)
        if not original and reserved and reserved["entity_key"] != key:
            raise ValueError(f"New entity {key} would overwrite published URL {path}")
        self.by_entity[key] = path
        return base + path[len(BASE):]


@lru_cache(maxsize=1)
def registry() -> UrlRegistry:
    return UrlRegistry()


def presence_url(name: str, tcpuid: str, year: int, base: str = BASE, province: str = "on") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    proposed = f"{base}/places/{province.lower()}/{slug}-{tcpuid.lower()}-{year}/"
    key = f"presence:{tcpuid.upper()}_{year}"
    owner = registry().rows.get(BASE + proposed[len(base):])
    if key not in registry().by_entity and owner and owner["entity_key"] != key:
        # The old generator sometimes overwrote a year page with an all-years
        # page at the same URL. Preserve the actually published owner and give
        # the previously hidden year detail a distinct, subordinate address.
        proposed += f"census-{year}/"
    return registry().resolve(key, proposed, base)


def residents_url(tcpuid: str, presence_path: str, base: str = BASE) -> str:
    return registry().resolve(f"residents:{tcpuid.upper()}_1881:",
                              presence_path + "residents/", base)
