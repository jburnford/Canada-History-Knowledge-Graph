#!/bin/bash
#
# Link Census Divisions across all census years (1851-1921)
#

set -euo pipefail

# GDB path from config.toml (override with env var GDB if needed).
GDB="${GDB:-$(python -c 'from scripts._config import CONFIG; print(CONFIG.gdb_path)')}"
OUT="${OUT_DIR:-cd_links_output}"

# Year pairs (sequential)
PAIRS=(
    "1851 1861"
    "1861 1871"
    "1871 1881"
    "1881 1891"
    "1891 1901"
    "1901 1911"
    "1911 1921"
)

echo "Linking Census Divisions across all years..."
echo "Output directory: $OUT"
echo ""

for pair in "${PAIRS[@]}"; do
    read -r year_from year_to <<< "$pair"
    echo "Processing: $year_from → $year_to"
    python scripts/link_cd_years_spatial.py \
        --gdb "$GDB" \
        --year-from "$year_from" \
        --year-to "$year_to" \
        --crs "${GIS_CRS:-EPSG:3347}" \
        --out "$OUT"
done

echo ""
echo "✓ All CD temporal links generated in $OUT/"
