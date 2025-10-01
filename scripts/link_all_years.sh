#!/bin/bash
# Link all consecutive census years using spatial overlap analysis

set -e

GDB="TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306.gdb"
OUT_DIR="year_links_output"
SCRIPT="scripts/link_csd_years_spatial_v2.py"

# Year pairs to process
YEAR_PAIRS=(
    "1851 1861"
    "1861 1871"
    "1871 1881"
    "1881 1891"
    "1891 1901"
    "1901 1911"
    "1911 1921"
)

echo "Linking all census years..."
echo "Output directory: $OUT_DIR"
echo ""

for pair in "${YEAR_PAIRS[@]}"; do
    read -r year_from year_to <<< "$pair"
    echo "=================================================="
    echo "Processing: $year_from → $year_to"
    echo "=================================================="

    python "$SCRIPT" \
        --gdb "$GDB" \
        --year-from "$year_from" \
        --year-to "$year_to" \
        --out "$OUT_DIR"

    echo ""
done

echo "All year pairs processed!"
echo ""
echo "Output files in $OUT_DIR/:"
ls -lh "$OUT_DIR/"