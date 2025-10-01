#!/bin/bash
#
# Link Census Divisions across all census years (1851-1921)
#

GDB="TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306.gdb"
OUT="cd_links_output"

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
        --out "$OUT"
done

echo ""
echo "✓ All CD temporal links generated in $OUT/"
