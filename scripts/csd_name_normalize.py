"""Canonical CSD name normalization shared by the page generator and the
persistent-place chain builder.

Two place-name strings that should cluster as the same place return the same
`grouping_key()`. Tier (Town / Village / City / Parish / Township / Municipality)
is preserved so rural and urban variants of the same base name stay distinct.
"""

import re
import unicodedata


# Census-type qualifier tiers. Variants WITHIN a tier are the same place
# (urban core "Magog, T-V" = "Magog, Town—Ville"), but tiers stay distinct
# (rural "Magog" township ≠ urban "Magog, Town").
QUALIFIER_TIER_MAP = {
    # Town tier (incorporated town/ville)
    "t-v": "Town", "t—v": "Town", "t v": "Town", "tv": "Town",
    "town-ville": "Town", "town—ville": "Town",
    "town and ville": "Town", "town et ville": "Town",
    "town & village": "Town", "town and village": "Town",
    "town": "Town", "ville": "Town",
    # Village tier
    "vl": "Village", "v": "Village", "village": "Village",
    # City tier
    "c": "City", "city": "City", "cité": "City", "cite": "City",
    "city—cité": "City", "city-cite": "City", "cité-city": "City",
    # Parish tier (Catholic / civil parish)
    "pr": "Parish", "par.": "Parish", "par": "Parish",
    "parish": "Parish", "paroisse": "Parish",
    # Township tier (less common as suffix; usually bare name = township)
    "tp": "Township", "tp.": "Township", "township": "Township",
    # Municipality tier
    "municipality": "Municipality", "mun.": "Municipality", "mun": "Municipality",
}


_TRAILING_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _parse_csd_name(name: str) -> tuple[str, str | None]:
    """Return (base_name, tier_label_or_None).
    Strips trailing parenthetical content first (e.g. SK 1911 convention
    "Tantallon vl (T18 R32 MW1)" — the parens hold a township-range survey
    code, not a tier qualifier)."""
    if not name:
        return ("", None)
    # Strip trailing parenthetical (one level — these don't nest in the data).
    stripped = _TRAILING_PARENS_RE.sub("", name).strip()
    if not stripped:
        stripped = name.strip()
    if "," in stripped:
        base, qualifier = stripped.rsplit(",", 1)
        qual_norm = qualifier.strip().lower()
        tier = QUALIFIER_TIER_MAP.get(qual_norm)
        if tier:
            return (base.strip(), tier)
    parts = stripped.split()
    for n in (3, 2, 1):
        if n >= len(parts):
            continue
        qual_norm = " ".join(parts[-n:]).lower()
        tier = QUALIFIER_TIER_MAP.get(qual_norm)
        if tier:
            return (" ".join(parts[:-n]), tier)
    return (stripped, None)


def _aggressive_base_normalize(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"\bsainte\b", "ste", s)
    s = re.sub(r"\bsaint\b", "st", s)
    s = re.sub(r"\bste\.\b", "ste", s)
    s = re.sub(r"\bst\.", "st", s)
    s = re.sub(r"\bno\.?\b\s*", " ", s)
    s = re.sub(r"\s*&\s*", " ", s)
    s = re.sub(r"\b(?:and|et)\b", " ", s)
    s = re.sub(r"\bquartier\b", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = " ".join(s.split())
    return s


def grouping_key(name: str) -> tuple[str, str | None]:
    """Two place-name strings that should cluster as the same place return
    the same grouping_key. Tier is preserved so rural ≠ urban variants."""
    base, tier = _parse_csd_name(name)
    return (_aggressive_base_normalize(base), tier)


def display_name_for_group(variants: list, tier: str | None) -> str:
    bases = []
    for variant in variants:
        b, _ = _parse_csd_name(variant[1])
        bases.append(b)
    base = min(bases, key=len) if bases else ""
    if tier:
        return f"{base} ({tier})"
    return base


# Tiers that can chain across each other when name+polygon evidence is strong.
# Critical principle: bare names (None tier) in TCP data are township-implicit,
# NOT a wildcard. Pairing rural "Magog" (bare) with urban "Magog, Village"
# would replicate the v7 over-correction (genuinely distinct admin entities).
# So None is treated as a township-family member, not a wildcard.
_TIER_COMPATIBILITY = {
    None: {None, "Township", "Municipality"},
    "Township": {None, "Township", "Municipality"},
    "Town": {"Town", "Village", "City", "Municipality"},
    "Village": {"Town", "Village", "Municipality"},
    "City": {"Town", "City", "Municipality"},
    "Parish": {"Parish", "Municipality"},
    "Municipality": {None, "Township", "Town", "Village", "City", "Parish", "Municipality"},
}


def tiers_compatible(tier_a: str | None, tier_b: str | None) -> bool:
    """Return True if two tiers can plausibly refer to the same enduring place
    (e.g. Township → Town promotion). Used as a guard on WITHIN/CONTAINS chain
    promotion to prevent merging genuinely distinct rural/urban entities."""
    return tier_b in _TIER_COMPATIBILITY.get(tier_a, {tier_a})


# Indian Reserve detection. Census-era CSDs encoding First Nations reserves use
# inconsistent conventions — sometimes a specific reserve name with "I R" suffix
# ("White Bear I R", "Moosomin I R"), sometimes a generic bundle ("Indian
# Reserves", "The Indian Reserves"), sometimes numbered ("Indian Reserve No.
# 71"), sometimes mixed ("Mann & Indian Reserve, I R"). The 1911 GDB favored
# specific names; the 1921 GDB largely lumped them. These entities deserve
# distinct handling: restricted chain rules (no name-only rescue across years),
# generic page rendering that doesn't assert modern band identity, and
# suppressed Wikidata QID display to respect OCAP-style sovereignty principles
# even when the underlying data has been matched. Per-band detail belongs in
# annual reports of the Indian Affairs Department, not this aggregate.
_IR_PATTERN = re.compile(
    r"\b(indian\s+reserves?|reserve\s+no\.?\s*\d|\bi\s*r\b)",
    re.IGNORECASE,
)


def is_indian_reserve(name: str) -> bool:
    """True if the CSD name represents an Indian reserve (specific or bundled)."""
    if not name:
        return False
    return bool(_IR_PATTERN.search(name))
