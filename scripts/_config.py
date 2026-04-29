"""Single source for environment-specific paths used by the pipeline scripts.

Loads `config.local.toml` if present at the repo root, else falls back to the
committed `config.toml` template. Every script that needs the GDB path, an
Excel data root, or the LINCS TTL location should `from _config import CONFIG`
instead of hardcoding `/home/jic823/...`.

The committed `config.toml` ships with one developer's paths so the repo runs
out of the box for them; collaborators copy it to `config.local.toml` (which
is gitignored) and edit values for their machine.

Usage:
    from _config import CONFIG
    gdf = gpd.read_file(CONFIG.gdb_path, layer="CANADA_1851_CSD")
    excel = pd.read_excel(CONFIG.excel_path(1901, "V1T7"))
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

try:
    # Python 3.11+ stdlib
    import tomllib
except ImportError:  # pragma: no cover — older python
    import tomli as tomllib  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[1]


class _Config:
    """Resolved pipeline configuration. All members are absolute Path objects
    or strings. Properties raise FileNotFoundError if a required input doesn't
    exist on disk — callers get a loud failure rather than a silent fallback."""

    def __init__(self, raw: dict, source_path: Path):
        paths = raw.get("paths", {})
        self._raw = raw
        self.source_path = source_path

        # External inputs
        self.data_root = Path(paths["data_root"]).expanduser().resolve()
        self.lincs_ttl = Path(paths["lincs_ttl"]).expanduser().resolve()
        self.lincs_json = Path(paths["lincs_json"]).expanduser().resolve()

        # Deploy target
        self.hgiscanada_repo = Path(paths["hgiscanada_repo"]).expanduser().resolve()

    @property
    def gdb_path(self) -> Path:
        """TCP_CANADA_CSD_202306 GeoDatabase. The double-nested directory is
        how the upstream zip extracts."""
        p = (self.data_root / "TCP_CANADA_CSD_202306"
             / "TCP_CANADA_CSD_202306" / "TCP_CANADA_CSD_202306.gdb")
        if not p.exists():
            raise FileNotFoundError(
                f"GDB not found at {p}\n"
                f"Set [paths].data_root in {self.source_path} to the directory "
                f"containing TCP_CANADA_CSD_202306/."
            )
        return p

    def excel_path(self, year: int, table: str) -> Path:
        """Path to a per-year published Excel table (e.g. 1901, 'V1T7' →
        <data_root>/1901/1901_V1T7_CSD_202306.xlsx). Raises if missing."""
        p = self.data_root / str(year) / f"{year}_{table}_CSD_202306.xlsx"
        if not p.exists():
            raise FileNotFoundError(
                f"Census Excel not found at {p}\n"
                f"Confirm [paths].data_root in {self.source_path} points at "
                f"the per-year Excel folders."
            )
        return p


def _load() -> _Config:
    local = REPO_ROOT / "config.local.toml"
    default = REPO_ROOT / "config.toml"
    source = local if local.exists() else default
    if not source.exists():
        raise FileNotFoundError(
            f"No config found. Copy {default.name}.example to "
            f"config.local.toml or commit {default.name}."
        )
    with source.open("rb") as f:
        raw = tomllib.load(f)
    return _Config(raw, source)


CONFIG = _load()


if __name__ == "__main__":
    # Self-test: print resolved paths so users can verify their config.
    print(f"Config source: {CONFIG.source_path}", file=sys.stderr)
    print(f"  data_root:       {CONFIG.data_root}")
    print(f"  gdb_path:        {CONFIG.gdb_path if CONFIG.data_root.exists() else '(unresolved)'}")
    print(f"  lincs_ttl:       {CONFIG.lincs_ttl}")
    print(f"  lincs_json:      {CONFIG.lincs_json}")
    print(f"  hgiscanada_repo: {CONFIG.hgiscanada_repo}")
