"""Shared name normalization for chain matching across the pipeline.

`normalize_for_match()` is the loose-equality key used by the CD chain builder
(Rules 1-3 + Rule 4-NAME / split-detect / Rule 4-BRIDGE), the CSD chain builder
(name-bridge pass), and the Wikidata grounding sibling-inheritance pass.

Folds diacritics (Châteauguay → chateauguay), unifies straight and curly
apostrophes plus backticks, treats hyphen as space (Jacques-Cartier matches
Jacques Cartier), collapses whitespace, lowercases. Used only for matching —
does NOT replace canonical_*_name as displayed.
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
