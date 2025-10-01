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


# ============================================================================
# Data Loading
# ============================================================================

def load_master_variables(mastvar_path):
    """Load master variables file to understand variable definitions."""
    print(f"Loading master variables from {mastvar_path}...")
    df = pd.read_excel(mastvar_path)
    print(f"  Found {len(df)} variable definitions")
    print(f"  Categories: {df['Category'].unique().tolist()}")
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
    """Normalize column name by removing year suffix."""
    return re.sub(r'_\d{4}$', '', col)


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

def process_census_table_v2(table_path, year, gdf_mapping, id_col_name, mastvar_df,
                            source_name, data_v2):
    """Process a single census table and create v2.0 observations."""
    print(f"\n  Processing {table_path.name}...")

    # Read table
    df = None
    try:
        df = pd.read_excel(table_path)
        if f'TCPUID_CSD_{year}' not in df.columns:
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

    # Get data columns
    metadata_cols = {
        'ROW_ID', id_col, 'PR', 'CD_NO', 'CSD_NO', 'PR_CD_CSD', 'NOTES', 'YEAR',
        'NAME_CD_' + str(year), 'NAME_CSD_' + str(year), 'NUMBER_CSD_' + str(year),
        'TCPUID_CD_' + str(year), 'TCPUID_CSD_' + str(year)
    }
    data_cols = [col for col in df.columns if col not in metadata_cols]
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

        # Validate ID exists in GDB
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

            # Create E16_Measurement
            measurement = create_measurement(tcpuid, year, var_name_normalized, category, source_name)
            data_v2.measurements.append(measurement)

            # Create E54_Dimension
            dimension = create_dimension(tcpuid, year, var_name_normalized, value_numeric, value_string)
            data_v2.dimensions.append(dimension)

            # Create relationships
            measurement_id = measurement['measurement_id:ID']
            dimension_id = dimension['dimension_id:ID']
            variable_type_id = f"VAR_{var_name_normalized}"

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

            data_v2.p70_documents.append({
                ':START_ID': info_obj['info_object_id:ID'],
                ':END_ID': measurement_id,
                ':TYPE': 'P70_documents'
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

    excel_files = list(year_dir.glob('*.xlsx'))
    excel_files = [f for f in excel_files if not f.name.startswith('TCP_CANADA')]

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

    # E16_Measurement (all)
    df = pd.DataFrame(data_v2.measurements)
    df.to_csv(output_dir / 'e16_measurements_all.csv', index=False)
    print(f"  ✓ E16 measurements: {len(df):,} → e16_measurements_all.csv")

    # E54_Dimension (all)
    df = pd.DataFrame(data_v2.dimensions)
    df.to_csv(output_dir / 'e54_dimensions_all.csv', index=False)
    print(f"  ✓ E54 dimensions: {len(df):,} → e54_dimensions_all.csv")

    # E73_Information_Object (all)
    df = pd.DataFrame(data_v2.info_objects)
    df.to_csv(output_dir / 'e73_information_objects.csv', index=False)
    print(f"  ✓ E73 info objects: {len(df)} → e73_information_objects.csv")

    # Relationships
    for name, data, filename in [
        ('P39 measured', data_v2.p39_measured, 'p39_measured_all.csv'),
        ('P40 observed_dimension', data_v2.p40_observed_dimension, 'p40_observed_dimension_all.csv'),
        ('P91 has_unit', data_v2.p91_has_unit, 'p91_has_unit_all.csv'),
        ('P2 has_type', data_v2.p2_has_type, 'p2_has_type_all.csv'),
        ('P4 measurement→timespan', data_v2.p4_measurement_timespan, 'p4_measurement_timespan_all.csv'),
        ('P4 period→timespan', data_v2.p4_period_timespan, 'p4_period_timespan.csv'),
        ('P70 documents', data_v2.p70_documents, 'p70_documents_all.csv'),
    ]:
        df = pd.DataFrame(data)
        df.to_csv(output_dir / filename, index=False)
        print(f"  ✓ {name}: {len(df):,} → {filename}")

    # Summary
    print(f"\n  Summary:")
    print(f"    Total measurements: {len(data_v2.measurements):,}")
    print(f"    Total dimensions: {len(data_v2.dimensions):,}")
    print(f"    Unique units: {len(units)}")
    print(f"    Time-spans: {len(data_v2.timespans)}")
    print(f"    Periods: {len(data_v2.periods)}")
    print(f"    Source files: {len(data_v2.info_objects)}")


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
