"""Mojibake repair helper for the Borealis 1881 CSV (and the parquets we
derived from it). The source CSV's text columns were double-encoded:
UTF-8 bytes interpreted as Latin-1 and then re-encoded as UTF-8, so
'Montréal' shows up as 'MontrÃ©al' on disk.

The reversible fix: encode the string as Latin-1, then decode as UTF-8.
Where that round-trip fails (the string was already clean ASCII or already
correctly UTF-8 because the corruption pattern requires non-ASCII bytes
to manifest), we keep the original.
"""
from __future__ import annotations


# Any mojibake string must contain the mis-decoded UTF-8 LEAD byte, which
# lands in U+00C2–U+00F4 under both Latin-1 and cp1252 (Â–ô). Probing on
# lead bytes (rather than the old hand-picked list, which missed â and
# therefore never repaired 'â€¦'-class strings) is complete; clean French
# text also fires the probe but then fails the round-trip closed.
_UTF8_LEAD_CHARS = frozenset(chr(c) for c in range(0xC2, 0xF5))


def fix_mojibake(s: object) -> object:
    """Idempotent: clean strings pass through unchanged."""
    if not isinstance(s, str):
        return s
    if not s:
        return s
    if not any(ch in _UTF8_LEAD_CHARS for ch in s):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    # cp1252 flavour: continuation bytes 0x80–0x9F decode to €‚ƒ„…†‡ˆ‰Š‹Œ''""
    # etc., which Latin-1 cannot re-encode ('â€¦' = …). cp1252 maps them back.
    try:
        return s.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def fix_dataframe_text(df, cols):
    """Apply fix_mojibake to each named column in-place. Returns df."""
    for c in cols:
        if c in df.columns:
            df[c] = df[c].map(fix_mojibake)
    return df
