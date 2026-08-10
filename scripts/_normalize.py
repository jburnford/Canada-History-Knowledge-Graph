"""Shared name normalization for chain matching across the pipeline.

`normalize_for_match()` is the loose-equality key used by the CD chain builder
(Rules 1-3 + Rule 4-NAME / split-detect / Rule 4-BRIDGE), the CSD chain builder
(name-bridge pass), and the Wikidata grounding sibling-inheritance pass.

Folds diacritics (Châteauguay → chateauguay), unifies straight and curly
apostrophes plus backticks, treats hyphen as space (Jacques-Cartier matches
Jacques Cartier), collapses whitespace, lowercases, expands the 19th-century
"boro" abbreviation to "borough" (Peterboro 1851 → Peterborough 1861;
Marlboro/Scarboro likewise). Used only for matching — does NOT replace
canonical_*_name as displayed.
"""

from __future__ import annotations

import re
import unicodedata


def normalize_for_match(name: str) -> str:
    if not name:
        return ""
    # Unify quote variants BEFORE diacritic folding: curly apostrophe is not
    # ASCII, so the encode("ascii", "ignore") step below would strip it
    # entirely — silently breaking equality between "L'Islet" (curly) and
    # "L'Islet" (straight).
    s = name.replace("’", "'").replace("‘", "'").replace("`", "'")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip().lower()
    # Expand "boro" suffix to "borough". \b anchors to word end so we catch
    # "peterboro" / "peterboro," / "peterboro park" (all → "peterborough...")
    # while leaving "peterborough" unchanged (no word boundary inside it) and
    # "boroville" unchanged (boro not at word end). Same place: 1851 GDB
    # spells the Ontario county "Peterboro"; 1861+ spells it "Peterborough".
    s = re.sub(r"boro\b", "borough", s)
    return s


# Admin-tier suffixes safe to strip for cross-chain matching of CSDs that
# share a modern identity but drift in their TCP encoding ("Peterborough,
# Town of" 1861 vs "Peterborough, C" 1921). Stripped after a leading comma
# so we never eat real name fragments. Keeps directionals (N/S/E/W,
# North—Nord) and wards (Ward—Quartier No. X) intact — those genuinely
# distinguish places. "T" and "C" are TCP single-letter codes for Town and
# City; anchored to the comma-prefix so we don't strip e.g. "Mont T...".
_BRIDGE_SUFFIX_RE = re.compile(
    r",\s*("
    r"Town\s+of|"
    r"Town[—\-]\s*Ville|"
    r"T[—\-]V|"
    r"City[—\-]\s*Cit[ée]|"
    r"Village[—\-]\s*Village|"
    r"Township[—\-]\s*Canton|"
    r"Parish[—\-]\s*Paroisse|"
    r"Reserve[—\-]\s*R[ée]serve|"
    r"Town|City|Village|Township|Parish|Reserve|Hamlet|"
    r"Cit[ée]|Ville|Canton|Paroisse|R[ée]serve|"
    r"par\.|"
    r"VL|TP|PAR|"
    r"C|T"
    r")\s*$",
    re.IGNORECASE,
)


def bridge_normalize(name: str) -> str:
    """Aggressive name-match key for cross-year CSD bridging and grounding
    sibling-inheritance.

    Strips admin-tier suffixes ("Town of" / "City—Cité" / single-letter "C")
    so that "Peterborough, Town of", "Peterborough, Town—Ville" and
    "Peterborough, C" all key as "peterborough". Then applies
    `normalize_for_match` (diacritics, case, whitespace).
    """
    if not name:
        return ""
    s = name
    for _ in range(3):
        new = _BRIDGE_SUFFIX_RE.sub("", s).rstrip().rstrip(",")
        if new == s:
            break
        s = new
    return normalize_for_match(s)


# Suffix → tier mapping. Pairs to bridge_normalize: bridge_normalize collapses
# all admin-tier variants to one root, suffix_tier records which tier they
# came from so sibling-inheritance can avoid the Brantford problem (city-tier
# Q34180 and bare-tier Township Q115260922 collapsing to one bucket and
# dropping each other as a conflict).
_TIER_PATTERNS = [
    ("URBAN", re.compile(
        r",?\s+("
        r"City[—\-]\s*Cit[ée]|Cit[ée]|City|"
        r"Town\s+of|Town[—\-]\s*Ville|T[—\-]V|Town|Ville|"
        r"C|T"
        r")\s*$",
        re.IGNORECASE)),
    ("TOWNSHIP", re.compile(
        r",?\s+(Township[—\-]\s*Canton|Township|Canton|TP)\s*$",
        re.IGNORECASE)),
    ("VILLAGE", re.compile(
        r",?\s+(Village[—\-]\s*Village|Village|VL)\s*$",
        re.IGNORECASE)),
    ("PARISH", re.compile(
        r",?\s+(Parish[—\-]\s*Paroisse|Parish|Paroisse|PAR|par\.?)\s*$",
        re.IGNORECASE)),
    ("RESERVE", re.compile(
        r",?\s+(Reserve[—\-]\s*R[ée]serve|Reserve|R[ée]serve)\s*$",
        re.IGNORECASE)),
    ("HAMLET", re.compile(
        r",?\s+Hamlet\s*$",
        re.IGNORECASE)),
]


def suffix_tier(name: str) -> str:
    """Classify a CSD name's admin-tier suffix.

    Returns one of URBAN, TOWNSHIP, VILLAGE, PARISH, RESERVE, HAMLET, BARE.
    Used by sibling-inheritance to avoid collapsing distinct entities that
    happen to share a root name (the Brantford City Q34180 vs. Township
    Q115260922 case).

    Loose about the leading comma — handles both "Saskatoon, C" (proper) and
    "Saskatoon c" (no-comma OCR variant) as URBAN. Tier checks run in priority
    order; first match wins. BARE means no recognizable suffix found.
    """
    return tier_root(name)[1]


def tier_root(name: str) -> tuple[str, str]:
    """Return (normalized_root_name, tier) by stripping the admin-tier suffix.

    Bridges the comma vs. no-comma variants (e.g., "Saskatoon, C" and
    "Saskatoon c" both → ("saskatoon", "URBAN")) so sibling-inheritance keys
    line up across OCR drift. Tier is one of URBAN/TOWNSHIP/VILLAGE/PARISH/
    RESERVE/HAMLET/BARE.

    Distinct from `bridge_normalize`: bridge_normalize requires a leading
    comma to strip suffixes, which fails on "Saskatoon c". `tier_root` matches
    suffixes after either comma or whitespace, so it's robust to that drift.
    """
    if not name:
        return ("", "BARE")
    s = name.strip()
    for tier, pat in _TIER_PATTERNS:
        m = pat.search(s)
        if m:
            root = s[: m.start()].rstrip().rstrip(",").rstrip()
            return (normalize_for_match(root), tier)
    return (normalize_for_match(s), "BARE")
