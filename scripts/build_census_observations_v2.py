#!/usr/bin/env python3
"""
Build Census Observations for CIDOC-CRM v2.0 Knowledge Graph

Generates proper E16_Measurement nodes with E54_Dimension, E58_Measurement_Unit,
E52_Time-Span, and E73_Information_Object provenance.

Based on Codex feedback for CIDOC-CRM compliance.

Author: Claude Code
Date: September 30, 2025
Version: 2.0
"""

import argparse
import pandas as pd
import geopandas as gpd
from pathlib import Path
import sys
from collections import defaultdict
import re
import hashlib


# ============================================================================
# Unit Mapping
# ============================================================================

UNIT_REGISTRY = {
    'UNIT_PERSONS': {'label': 'persons', 'symbol': 'ppl'},
    'UNIT_ACRES': {'label': 'acres', 'symbol': 'ac'},
    'UNIT_SQUARE_MILES': {'label': 'square miles', 'symbol': 'sq mi'},
    'UNIT_DOLLARS': {'label': 'dollars', 'symbol': '$'},
    'UNIT_BUSHELS': {'label': 'bushels', 'symbol': 'bu'},
    'UNIT_HEAD': {'label': 'head (livestock)', 'symbol': 'head'},
    'UNIT_FARMS': {'label': 'farms', 'symbol': 'farms'},
    'UNIT_TONS': {'label': 'tons', 'symbol': 'tons'},
    'UNIT_BARRELS': {'label': 'barrels', 'symbol': 'bbl'},
    'UNIT_PERCENT': {'label': 'percent', 'symbol': '%'},
    'UNIT_COUNT': {'label': 'count', 'symbol': 'count'},
}


def infer_unit_id(variable_name):
    """Infer measurement unit ID from variable name."""
    name_upper = variable_name.upper()

    if any(x in name_upper for x in ['POP', 'AGE_', 'RELIGION', 'BIRTH', 'LANG', 'RACE', 'OCCUPATION', 'HOUSE']):
        return 'UNIT_PERSONS'
    elif 'ACRES' in name_upper or 'ARE_' in name_upper:
        return 'UNIT_ACRES'
    elif 'SQ_MI' in name_upper or 'SQMI' in name_upper:
        return 'UNIT_SQUARE_MILES'
    elif 'BUSHEL' in name_upper:
        return 'UNIT_BUSHELS'
    elif 'DOLLAR' in name_upper or 'VALUE' in name_upper:
        return 'UNIT_DOLLARS'
    elif 'TON' in name_upper:
        return 'UNIT_TONS'
    elif 'BARREL' in name_upper:
        return 'UNIT_BARRELS'
    elif 'HEAD' in name_upper or 'LIVESTOCK' in name_upper or 'CATTLE' in name_upper or 'HORSE' in name_upper:
        return 'UNIT_HEAD'
    elif 'FARM' in name_upper and ('COUNT' in name_upper or '_N' in name_upper):
        return 'UNIT_FARMS'
    elif 'PERCENT' in name_upper or 'PCT' in name_upper:
        return 'UNIT_PERCENT'
    else:
        return 'UNIT_COUNT'  # Default


# ============================================================================
# Shared Data Structures
# ============================================================================

class CensusDataV2:
    """Container for all v2.0 CIDOC-CRM entities."""

    def __init__(self):
        # Nodes
        self.measurements = []        # E16_Measurement
        self.dimensions = []          # E54_Dimension
        self.timespans = []           # E52_Time-Span
        self.periods = []             # E4_Period
        self.info_objects = []        # E73_Information_Object

        # Relationships
        self.p39_measured = []        # E16 → E93_Presence
        self.p40_observed_dimension = []  # E16 → E54
        self.p91_has_unit = []        # E54 → E58
        self.p2_has_type = []         # E16 → E55
        self.p4_measurement_timespan = []  # E16 → E52
        self.p4_period_timespan = []  # E4 → E52
        self.p70_documents = []       # E73 → E16

        # Tracking
        self.source_files = set()
        # Dedup: the same (tcpuid, year, var) may be reported by multiple
        # source tables. We emit one canonical E16/E54 per key and append an
        # extra P70_documents edge for each additional source that reports it.
        self.emitted_measurements: set[str] = set()
        # Counters for the final summary
        self.rows_skipped_non_csd = 0
        self.duplicate_measurements = 0


# ============================================================================
# Data Loading
# ============================================================================

def load_master_variables(mastvar_path):
    """Load master variables file to understand variable definitions.

    The TCP Mastvar.xlsx documents codes for the regularized CSD/CD-format
    tables, which only cover censuses 1851-1901. The 1911 and 1921 census
    tables exist only in PUB format and use different (PUB-specific) variable
    codes — these are documented in data/mastvar_supplement_1911_1921.csv.
    Both are merged here so downstream code sees one unified vocabulary.
    """
    print(f"Loading master variables from {mastvar_path}...")
    df = pd.read_excel(mastvar_path)
    print(f"  Found {len(df)} variable definitions in Mastvar")

    # Load the 1911/1921 PUB supplement if present.
    supp_path = Path(__file__).resolve().parent.parent / 'data' / 'mastvar_supplement_1911_1921.csv'
    if supp_path.exists():
        supp = pd.read_csv(supp_path)
        print(f"  Found {len(supp)} additional codes in 1911/1921 PUB supplement")
        # Concat and drop duplicates on Name (Mastvar wins on conflicts).
        merged = pd.concat([df, supp], ignore_index=True, sort=False)
        merged = merged.drop_duplicates(subset='Name', keep='first')
        df = merged
        print(f"  Merged total: {len(df)} unique variable definitions")
    else:
        print(f"  WARNING: supplement not found at {supp_path}; "
              f"1911/1921 codes will lack metadata")
    print(f"  Categories: {sorted(df['Category'].dropna().unique().tolist())}")
    return df


def load_gdb_layer(gdb_path, year):
    """Load GDB layer for a specific year."""
    layer_name = f"CANADA_{year}_CSD"
    print(f"\n  Loading GDB layer: {layer_name}")

    try:
        gdf = gpd.read_file(gdb_path, layer=layer_name)
    except Exception as e:
        print(f"    ERROR loading layer: {e}")
        return None, None

    print(f"    Features: {len(gdf)}")

    tcpuid_col = f"TCPUID_CSD_{year}"
    if tcpuid_col not in gdf.columns:
        print(f"    ERROR: {tcpuid_col} not found")
        print(f"    Columns: {gdf.columns.tolist()}")
        return None, None

    print(f"    Using ID column: {tcpuid_col}")
    return gdf[[tcpuid_col]], tcpuid_col


def normalize_column_name(col):
    """Normalize column name by removing year suffix and pandas duplicate suffix.

    pandas appends ``.1``, ``.2``, etc. when an xlsx has multiple columns with
    the same header (e.g. POP_XX_N appearing in two source sections); strip
    those so the canonical variable id matches Mastvar.
    """
    s = str(col)
    s = re.sub(r'\.\d+$', '', s)        # pandas duplicate-column suffix
    s = re.sub(r'_\d{4}$', '', s)       # year suffix (1851, 1911, etc.)
    return s


# ============================================================================
# v2.0 Entity Generation
# ============================================================================

def create_measurement(tcpuid, year, var_name, category, source_name):
    """Create E16_Measurement node."""
    measurement_id = f"MEAS_{tcpuid}_{year}_{var_name}"
    return {
        'measurement_id:ID': measurement_id,
        ':LABEL': 'E16_Measurement',
        'label': f"{var_name} for {tcpuid} in {year}",
        'notes': ''
    }


def create_dimension(tcpuid, year, var_name, value_numeric, value_string):
    """Create E54_Dimension node."""
    dimension_id = f"DIM_{tcpuid}_{year}_{var_name}"
    return {
        'dimension_id:ID': dimension_id,
        ':LABEL': 'E54_Dimension',
        'value:float': value_numeric if value_numeric is not None else '',
        'value_string': value_string if value_string is not None else ''
    }


def create_info_object(source_name, year):
    """Create E73_Information_Object node with Borealis provenance."""
    info_object_id = f"SOURCE_{year}_{source_name}"

    # Construct Borealis landing page (template - actual DOIs would need to be fetched)
    landing_page = f"https://borealisdata.ca/dataset.xhtml?persistentId=doi:10.5683/SP3/PKUZJN"
    access_uri = f"https://borealisdata.ca/api/access/datafile/:persistentId/?persistentId=doi:10.5683/SP3/PKUZJN"

    return {
        'info_object_id:ID': info_object_id,
        ':LABEL': 'E73_Information_Object',
        'label': f"{year}_{source_name}_CSD_202306.xlsx",
        'source_table': source_name,
        'file_hash': '',  # Could compute from actual file
        'access_uri': access_uri,
        'landing_page': landing_page
    }


# ============================================================================
# Census Table Processing
# ============================================================================

def _load_v1t1_crosswalk(year: int):
    """Return dict v1t1_code -> tcpuid for the year, or None if no crosswalk
    file exists. Currently only 1911 is supported (the year with the
    township-pattern collision problem)."""
    from pathlib import Path as _P
    repo = _P(__file__).resolve().parents[1]
    cw_path = repo / "wikidata_grounding" / f"v1t1_{year}_crosswalk.csv"
    if not cw_path.exists():
        return None
    import csv as _csv
    out = {}
    with cw_path.open() as f:
        for row in _csv.DictReader(f):
            code = row.get("v1t1_code", "").strip()
            tcpuid = row.get("tcpuid", "").strip()
            if code and tcpuid:
                out[code] = tcpuid
    print(f"    Loaded V1T1 crosswalk: {len(out)} {year} mappings")
    return out


def process_census_table_v2(table_path, year, gdf_mapping, id_col_name, mastvar_df,
                            source_name, data_v2):
    """Process a single census table and create v2.0 observations."""
    print(f"\n  Processing {table_path.name}...")
    v1t1_crosswalk = _load_v1t1_crosswalk(year) if year == 1911 else None

    # Read table. Some older-year tables have three metadata rows before the
    # real header (skiprows=3); newer-year tables (1911, 1921) have the header
    # on row 0 but use `{source_name}_{year}` as the ID column instead of
    # `TCPUID_CSD_{year}`. Accept either column name as proof of a valid read.
    def _has_id_column(frame) -> bool:
        if f'TCPUID_CSD_{year}' in frame.columns:
            return True
        return any(
            str(c) == f'{source_name}_{year}' or f'{source_name}_{year}' in str(c)
            for c in frame.columns
        )

    df = None
    try:
        df = pd.read_excel(table_path)
        if not _has_id_column(df):
            df = pd.read_excel(table_path, skiprows=3)
    except Exception as e:
        print(f"    ERROR reading file: {e}")
        return

    # Find ID column
    id_col = None
    tcpuid_pattern = f'TCPUID_CSD_{year}'
    if tcpuid_pattern in df.columns:
        id_col = tcpuid_pattern
    else:
        for col in df.columns:
            col_str = str(col)
            if f'{source_name}_{year}' in col_str or col_str == f'{source_name}_{year}':
                id_col = col
                break

    if not id_col:
        print(f"    ERROR: Could not find ID column")
        print(f"    Looking for: TCPUID_CSD_{year} or {source_name}_{year}")
        print(f"    Columns: {df.columns.tolist()[:15]}")
        return

    print(f"    Using ID column: {id_col}")
    print(f"    Processing {len(df)} rows...")

    # Get data columns. PUB-format tables (1911, 1921) have additional metadata
    # columns that the CSD-format tables lack: CSD_TYPE (city/town/village text
    # marker), LINE_NO (V2T28 only), PR_CD (province-CD identifier in CD-level
    # tables), and the table-self-id column (e.g. `V2T2_1911`) which the
    # `_has_id_column` logic accepts as id_col but which still needs filtering
    # when the file ALSO has a TCPUID_CSD column.
    metadata_cols = {
        'ROW_ID', id_col, 'PR', 'CD_NO', 'CSD_NO', 'PR_CD_CSD', 'PR_CD',
        'CSD_TYPE', 'LINE_NO', 'NOTES', 'YEAR',
        'NAME_CD_' + str(year), 'NAME_CSD_' + str(year), 'NAME_COUNTY_' + str(year),
        'NUMBER_CD_' + str(year), 'NUMBER_CSD_' + str(year),
        'TCPUID_CD_' + str(year), 'TCPUID_CSD_' + str(year)
    }
    # Also drop any column whose name is a table-self-id like `V1T1_1911`,
    # `V2T2_1911`, `V3T3_1921`. These are present even when not picked as id_col.
    table_self_id_pattern = re.compile(rf'^V\d+T\d+_{year}$')
    data_cols = [col for col in df.columns
                 if col not in metadata_cols and not table_self_id_pattern.match(str(col))]
    print(f"    Found {len(data_cols)} data columns")

    # Create info object for this source
    info_obj = create_info_object(source_name, year)
    if info_obj['info_object_id:ID'] not in data_v2.source_files:
        data_v2.info_objects.append(info_obj)
        data_v2.source_files.add(info_obj['info_object_id:ID'])

    rows_processed = 0
    observations_created = 0

    for idx, row in df.iterrows():
        csd_table_id = row[id_col]

        if pd.isna(csd_table_id):
            continue

        # Skip aggregate rows (country + CD-level). We only want CSD-level
        # measurements in this output; CD and country totals can be derived
        # downstream from the CSD-level data, and including them here triples
        # any naive sum across the province (see workshop validation memo).
        # Some rows have non-numeric CD_NO like "20N" — treat those as valid
        # CSD rows (if CD_NO isn't a plain zero, it's not the aggregate row).
        def _is_zero(v) -> bool:
            if pd.isna(v):
                return False
            try:
                return int(v) == 0
            except (ValueError, TypeError):
                return False

        # Skip non-CSD-level rows. CSD-format files (1851-1901) don't have a
        # CSD_NO column — they're inherently CSD-level (joined to GDB via
        # TCPUID_CSD_{year}), so no per-row filter is needed. PUB-format files
        # (1911, 1921) DO have CSD_NO; we use it to skip country/province/CD
        # aggregate rows. The 1921 V3T3 Housing table is CD-level only (no
        # CSD_NO column at all) — when CSD_NO is absent there entirely, every
        # row is non-CSD and must be skipped.
        if 'CSD_NO' in df.columns:
            csd_no = row.get('CSD_NO')
            if csd_no is None or pd.isna(csd_no) or _is_zero(csd_no):
                data_v2.rows_skipped_non_csd += 1
                continue
            if _is_zero(row.get('CD_NO')):
                data_v2.rows_skipped_non_csd += 1
                continue

        # Bind V1T1 row to a GDB TCPUID. For 1911, use the explicit V1T1↔GDB
        # crosswalk (wikidata_grounding/v1t1_1911_crosswalk.csv) — naive string
        # equality silently mis-joins because V1T1's prairie township-level
        # codes collide with unrelated GDB CSD codes (e.g. SK216003 = "T24 R1
        # MW3" in V1T1 but "Saskatoon c" in the GDB). For other years the naive
        # join still applies; their V1T1 has no township-pattern rows.
        if year == 1911 and v1t1_crosswalk is not None:
            tcpuid = v1t1_crosswalk.get(csd_table_id)
            if not tcpuid:
                # Either dropped (township-pattern, CD-aggregate) or unmatched.
                # Either way, no measurements emitted for this V1T1 row.
                continue
        else:
            if gdf_mapping is not None:
                match = gdf_mapping[gdf_mapping[id_col_name] == csd_table_id]
                if len(match) == 0:
                    continue
            tcpuid = csd_table_id
        presence_id = f"{tcpuid}_{year}"
        timespan_id = f"TIMESPAN_{year}"

        # Process each variable
        for col in data_cols:
            value = row[col]
            if pd.isna(value):
                continue

            var_name_normalized = normalize_column_name(col)

            # Determine value type
            if isinstance(value, (int, float)):
                value_numeric = float(value)
                value_string = None
            else:
                value_numeric = None
                value_string = str(value)

            # Look up variable metadata
            var_info = mastvar_df[mastvar_df['Name'] == var_name_normalized]
            if len(var_info) > 0:
                category = var_info.iloc[0]['Category']
            else:
                category = 'UNKNOWN'

            # Infer unit
            unit_id = infer_unit_id(var_name_normalized)

            measurement_id = f"MEAS_{tcpuid}_{year}_{var_name_normalized}"
            dimension_id = f"DIM_{tcpuid}_{year}_{var_name_normalized}"
            variable_type_id = f"VAR_{var_name_normalized}"

            # Always emit a P70_documents edge for this source, even when
            # the (tcpuid, year, var) was already reported by another table.
            # That preserves full provenance without duplicating :IDs.
            data_v2.p70_documents.append({
                ':START_ID': info_obj['info_object_id:ID'],
                ':END_ID': measurement_id,
                ':TYPE': 'P70_documents'
            })

            if measurement_id in data_v2.emitted_measurements:
                data_v2.duplicate_measurements += 1
                continue
            data_v2.emitted_measurements.add(measurement_id)

            measurement = create_measurement(tcpuid, year, var_name_normalized, category, source_name)
            data_v2.measurements.append(measurement)

            dimension = create_dimension(tcpuid, year, var_name_normalized, value_numeric, value_string)
            data_v2.dimensions.append(dimension)

            data_v2.p39_measured.append({
                ':START_ID': measurement_id,
                ':END_ID': presence_id,
                ':TYPE': 'P39_measured'
            })

            data_v2.p40_observed_dimension.append({
                ':START_ID': measurement_id,
                ':END_ID': dimension_id,
                ':TYPE': 'P40_observed_dimension'
            })

            data_v2.p91_has_unit.append({
                ':START_ID': dimension_id,
                ':END_ID': unit_id,
                ':TYPE': 'P91_has_unit'
            })

            data_v2.p2_has_type.append({
                ':START_ID': measurement_id,
                ':END_ID': variable_type_id,
                ':TYPE': 'P2_has_type'
            })

            data_v2.p4_measurement_timespan.append({
                ':START_ID': measurement_id,
                ':END_ID': timespan_id,
                ':TYPE': 'P4_has_time-span'
            })

            observations_created += 1

        rows_processed += 1

    print(f"    Created {observations_created} measurements from {rows_processed} CSDs")


# ============================================================================
# Year Processing
# ============================================================================

def process_year_tables_v2(year, tables_dir, gdb_path, mastvar_df, data_v2):
    """Process all tables for a given census year (v2.0)."""
    print(f"\n{'='*60}")
    print(f"Processing Census Year: {year}")
    print(f"{'='*60}")

    # Load GDB layer
    gdf_mapping, id_col_name = load_gdb_layer(gdb_path, year)
    if gdf_mapping is None:
        print(f"ERROR: Could not load GDB layer for {year}")
        return

    # Find Excel files
    year_dir = tables_dir / f"{year}Tables" / str(year)
    if not year_dir.exists():
        year_dir = tables_dir / str(year)

    if not year_dir.exists():
        print(f"ERROR: Year directory not found: {year_dir}")
        return

    # Per TCP_CANADA_TABLES_202306.pdf: each table comes in OCR / CD / CSD / Pub
    # Tab formats, except 1911 and 1921 which exist only in Pub Tab. CSD (and CD)
    # column headers are the regularized variable names that match Mastvar; PUB
    # uses different shortened names; OCR is raw multi-row headers that pandas
    # mangles into "C01_…", "C02_…" artifacts. Read only the canonical format
    # for each year so variable codes align with the e55 type registry.
    if year <= 1901:
        excel_files = list(year_dir.glob(f'{year}_*_CSD_*.xlsx'))
    else:
        excel_files = list(year_dir.glob(f'{year}_*_PUB_*.xlsx'))

    if len(excel_files) == 0:
        print(f"WARNING: No Excel files found in {year_dir}")
        return

    print(f"\nFound {len(excel_files)} Excel files:")
    for f in excel_files:
        print(f"  - {f.name}")

    # Create time-span for this year (once)
    timespan = {
        'timespan_id:ID': f'TIMESPAN_{year}',
        ':LABEL': 'E52_Time-Span',
        'label': f'Census Year {year}',
        'begin_of_begin': f'{year}-01-01',
        'end_of_end': f'{year}-12-31'
    }
    data_v2.timespans.append(timespan)

    # Create period for this year (using CENSUS_YYYY format to match spatial data)
    period = {
        'period_id:ID': f'CENSUS_{year}',
        'year:int': year,
        ':LABEL': 'E4_Period',
        'label': f'{year} Canadian Census'
    }
    data_v2.periods.append(period)

    # Link period to timespan
    data_v2.p4_period_timespan.append({
        ':START_ID': f'CENSUS_{year}',
        ':END_ID': f'TIMESPAN_{year}',
        ':TYPE': 'P4_has_time-span'
    })

    # Process each table
    for excel_file in excel_files:
        match = re.search(r'_([VT]\d+[A-Z]*\d*)_', excel_file.name)
        if match:
            source_name = match.group(1)
        else:
            source_name = excel_file.stem.split('_')[1] if '_' in excel_file.stem else 'UNKNOWN'

        process_census_table_v2(
            excel_file, year, gdf_mapping, id_col_name, mastvar_df, source_name, data_v2
        )


# ============================================================================
# Export Functions
# ============================================================================

def export_v2_csvs(data_v2, output_dir):
    """Export all v2.0 CIDOC-CRM CSV files."""
    print(f"\n{'='*60}")
    print(f"Exporting v2.0 CIDOC-CRM CSV files...")
    print(f"{'='*60}")

    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)

    # E58_Measurement_Unit (global - once)
    units = []
    for unit_id, unit_data in UNIT_REGISTRY.items():
        units.append({
            'unit_id:ID': unit_id,
            ':LABEL': 'E58_Measurement_Unit',
            'label': unit_data['label'],
            'symbol': unit_data['symbol']
        })
    df = pd.DataFrame(units)
    df.to_csv(output_dir / 'e58_measurement_units.csv', index=False)
    print(f"  ✓ E58 units: {len(df)} → e58_measurement_units.csv")

    # E52_Time-Span (all years)
    df = pd.DataFrame(data_v2.timespans)
    df.to_csv(output_dir / 'e52_timespans.csv', index=False)
    print(f"  ✓ E52 timespans: {len(df)} → e52_timespans.csv")

    # E4_Period (all years)
    df = pd.DataFrame(data_v2.periods)
    df.to_csv(output_dir / 'e4_periods.csv', index=False)
    print(f"  ✓ E4 periods: {len(df)} → e4_periods.csv")

    # E73_Information_Object (all years in one file — small)
    df = pd.DataFrame(data_v2.info_objects)
    df.to_csv(output_dir / 'e73_information_objects.csv', index=False)
    print(f"  ✓ E73 info objects: {len(df)} → e73_information_objects.csv")

    # Measurement/dimension nodes and their relationships are split per-year
    # to keep individual files under GitHub's 100MB hard limit. The year is
    # embedded in the measurement/dimension IDs ("MEAS_{tcpuid}_{year}_{var}"
    # and "DIM_{tcpuid}_{year}_{var}") and in the :END_ID of the period-level
    # P70_documents edges via the measurement_id. Group by parsing year out
    # of the relevant ID field.
    year_re = re.compile(r'_(\d{4})_')

    def _year_from_id_field(row: dict, field: str) -> int | None:
        m = year_re.search(str(row.get(field, '')))
        return int(m.group(1)) if m else None

    def _split_and_write(data: list, stem: str, year_field: str) -> int:
        by_year: dict[int, list] = {}
        for r in data:
            y = _year_from_id_field(r, year_field)
            if y is None:
                continue
            by_year.setdefault(y, []).append(r)
        written = 0
        for y in sorted(by_year):
            df = pd.DataFrame(by_year[y])
            path = output_dir / f'{stem}_{y}.csv'
            df.to_csv(path, index=False)
            print(f"  ✓ {stem}_{y}: {len(df):,} rows")
            written += len(df)
        return written

    print("\n  E16_Measurement (per year):")
    total_e16 = _split_and_write(data_v2.measurements, 'e16_measurements', 'measurement_id:ID')

    print("\n  E54_Dimension (per year):")
    total_e54 = _split_and_write(data_v2.dimensions, 'e54_dimensions', 'dimension_id:ID')

    for label, rows, stem, year_field in [
        ('P39 measured',          data_v2.p39_measured,            'p39_measured',            ':START_ID'),
        ('P40 observed_dimension', data_v2.p40_observed_dimension, 'p40_observed_dimension',  ':START_ID'),
        ('P91 has_unit',          data_v2.p91_has_unit,            'p91_has_unit',            ':START_ID'),
        ('P2 has_type',           data_v2.p2_has_type,             'p2_has_type',             ':START_ID'),
        ('P4 meas→timespan',      data_v2.p4_measurement_timespan, 'p4_measurement_timespan', ':START_ID'),
        ('P70 documents',         data_v2.p70_documents,           'p70_documents',           ':END_ID'),
    ]:
        print(f"\n  {label} (per year):")
        _split_and_write(rows, stem, year_field)

    # P4 period→timespan stays as a single file — one row per census year.
    df = pd.DataFrame(data_v2.p4_period_timespan)
    df.to_csv(output_dir / 'p4_period_timespan.csv', index=False)
    print(f"\n  ✓ P4 period→timespan: {len(df)} → p4_period_timespan.csv")

    # Summary
    print(f"\n  Summary:")
    print(f"    Total measurements: {len(data_v2.measurements):,}")
    print(f"    Total dimensions: {len(data_v2.dimensions):,}")
    print(f"    Unique units: {len(units)}")
    print(f"    Time-spans: {len(data_v2.timespans)}")
    print(f"    Periods: {len(data_v2.periods)}")
    print(f"    Source files: {len(data_v2.info_objects)}")
    print(f"    Non-CSD rows skipped: {data_v2.rows_skipped_non_csd:,}")
    print(f"    Duplicate (tcpuid, year, var) collapsed: "
          f"{data_v2.duplicate_measurements:,} "
          f"(extra P70 provenance edges emitted instead)")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Build census observations for CIDOC-CRM v2.0 knowledge graph'
    )
    parser.add_argument(
        '--mastvar',
        default='1911Tables/1911/TCP_CANADA_CD-CSD_Mastvar.xlsx',
        help='Path to master variables file'
    )
    parser.add_argument(
        '--gdb',
        default='TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306/TCP_CANADA_CSD_202306.gdb',
        help='Path to GDB file'
    )
    parser.add_argument(
        '--tables-dir',
        default='.',
        help='Base directory containing {year}Tables/ directories'
    )
    parser.add_argument(
        '--years',
        default='1901',
        help='Comma-separated list of years to process'
    )
    parser.add_argument(
        '--out',
        default='neo4j_census_v2',
        help='Output directory for Neo4j CSV files'
    )

    args = parser.parse_args()

    mastvar_path = Path(args.mastvar)
    gdb_path = Path(args.gdb)
    tables_dir = Path(args.tables_dir)
    output_dir = Path(args.out)

    if not mastvar_path.exists():
        print(f"ERROR: Master variables file not found: {mastvar_path}")
        return 1

    if not gdb_path.exists():
        print(f"ERROR: GDB file not found: {gdb_path}")
        return 1

    output_dir.mkdir(exist_ok=True, parents=True)
    print(f"Output directory: {output_dir.absolute()}")

    # Load master variables
    mastvar_df = load_master_variables(mastvar_path)

    # Initialize data container
    data_v2 = CensusDataV2()

    # Process each year
    years = [int(y.strip()) for y in args.years.split(',')]
    for year in years:
        process_year_tables_v2(year, tables_dir, gdb_path, mastvar_df, data_v2)

    # Export all data
    export_v2_csvs(data_v2, output_dir)

    print(f"\n{'='*60}")
    print("✓ CIDOC-CRM v2.0 census observations complete!")
    print(f"{'='*60}")
    print(f"\nOutput files in: {output_dir.absolute()}")
    print("\nNext steps:")
    print("1. Review CSV files for data quality")
    print("2. Add E33_Citation and E30_Right provenance")
    print("3. Load into Neo4j using LOAD CSV statements")
    print("4. Validate against CIDOC-CRM ontology")

    return 0


if __name__ == '__main__':
    sys.exit(main())
