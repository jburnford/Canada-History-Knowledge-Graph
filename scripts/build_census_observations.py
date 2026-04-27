#!/usr/bin/env python3
"""
Build Census Observations for CIDOC-CRM Knowledge Graph

Processes historical Canadian census tables (1851-1921) to create:
- E13_Attribute_Assignment nodes (census observations)
- E55_Type nodes (variable type taxonomy)
- Relationships: P140, P4, P2

Author: Claude Code
Date: September 30, 2025
"""

import argparse
import pandas as pd
import geopandas as gpd
from pathlib import Path
import sys
from collections import defaultdict
import re


_UNIT_PREFIX_PATTERNS = [
    ('acres of', 'acres'),
    ('bushels of', 'bushels'),
    ('barrels of', 'barrels'),
    ('pounds of', 'pounds'),
    ('tons of', 'tons'),
    ('gallons of', 'gallons'),
    ('quintals of', 'quintals'),
    ('yards of', 'yards'),
    ('feet of', 'feet'),
    ('fathoms of', 'fathoms'),
    ('value of', 'dollars'),
    ('total area', 'acres'),
    ('area in acres', 'acres'),
    ('area in square miles', 'square_miles'),
    ('capacity of', 'gallons'),
    ('deaths in the past year', 'deaths'),
    ('deaths among', 'deaths'),
    ('deaths,', 'deaths'),
]

_HEAD_NOUN_TO_UNIT = {
    # persons
    **{w: 'persons' for w in (
        'males', 'females', 'persons', 'men', 'women', 'children',
        'adult', 'adults', 'single', 'married', 'widowed', 'divorced',
        'french', 'indigenous', 'negroes', 'jews', 'jewish',
        'protestants', 'catholics', 'presbyterians', 'methodists',
        'baptists', 'anglicans', 'lutherans', 'quakers', 'christians',
        'hindus', 'pagans', 'mennonites', 'unitarians',
        'employees', 'hands', 'operatives', 'apprentices',
        'members',
    )},
    # buildings
    **{w: 'buildings' for w in (
        'houses', 'dwellings', 'churches', 'schoolhouses', 'schools',
        'homes', 'shanties',
    )},
    # establishments
    **{w: 'establishments' for w in (
        'factories', 'mills', 'shops', 'kilns', 'breweries', 'distilleries',
        'works', 'establishments', 'tanneries', 'foundries', 'forges',
        'refineries', 'creameries', 'cheeseries', 'bakeries',
    )},
    # head of livestock
    **{w: 'head' for w in (
        'oxen', 'cattle', 'sheep', 'swine', 'hogs', 'lambs', 'calves',
        'horses', 'cows', 'pigs', 'colts', 'milch', 'bulls', 'steers',
    )},
    # vessels
    **{w: 'vessels' for w in ('boats', 'vessels', 'ships', 'barges')},
    # households (CD-level supplement codes)
    'households': 'households',
}


def _infer_unit_from_name(variable_name):
    """Legacy name-based inference; used as fallback when no description."""
    name_upper = (variable_name or '').upper()
    if any(x in name_upper for x in ['POP', 'AGE_', 'RELIGION', 'BIRTH', 'LANG', 'RACE', 'OCCUPATION']):
        return 'persons'
    elif 'ACRES' in name_upper:
        return 'acres'
    elif 'SQ_MI' in name_upper or 'SQMI' in name_upper:
        return 'square_miles'
    elif 'BUSHEL' in name_upper:
        return 'bushels'
    elif 'DOLLAR' in name_upper or 'VALUE' in name_upper:
        return 'dollars'
    elif 'TON' in name_upper:
        return 'tons'
    elif 'HEAD' in name_upper or 'LIVESTOCK' in name_upper or 'CATTLE' in name_upper:
        return 'head'
    elif 'FARM' in name_upper and 'COUNT' in name_upper:
        return 'farms'
    elif 'PERCENT' in name_upper or 'PCT' in name_upper:
        return 'percent'
    else:
        return 'unknown'


def infer_unit(variable_name, description=None, category=None):
    """Infer measurement unit, preferring the Mastvar description text.

    Order of inference:
      1. Explicit unit prefixes in the description ("Acres of …", "Bushels of …").
      2. "Number of <head noun>" — look up the head noun in known buckets.
      3. Category-default for person-heavy categories when the description
         starts with "Number of" but the head noun doesn't match a bucket.
      4. Fallback to the legacy name-based heuristic.
    """
    if description:
        d = str(description).strip().lower()
        for prefix, unit in _UNIT_PREFIX_PATTERNS:
            if d.startswith(prefix):
                return unit
        if 'population per square' in d or 'persons per square' in d:
            return 'persons_per_sq_mi'
        if d.startswith('average size of families') or d.startswith('average number'):
            return 'persons'
        if 'percentage' in d or 'per cent' in d or d.startswith('percent') or '%' in d:
            return 'percent'
        if d.startswith('total population') or d == 'population' or d.startswith('population'):
            return 'persons'
        if d.startswith('persons recorded') or d.startswith('persons aged'):
            return 'persons'
        # Generic "number of <X>" search — catches "Total (rural + urban) number
        # of dwellings", "Rural number of households", etc., not just leading
        # "Number of X". Falls through to head-noun bucket lookup below.
        nm = re.search(r'\bnumber of (\w+)', d)
        if nm:
            head_first = nm.group(1)
            if head_first in _HEAD_NOUN_TO_UNIT:
                return _HEAD_NOUN_TO_UNIT[head_first]
            if category in ('POP', 'AGE', 'ETH', 'REL', 'DTH'):
                return 'persons'
            if category == 'BLD':
                return 'buildings'
            if category == 'MFG':
                return 'establishments'
            return 'count'
        if d.startswith('number of') or d.startswith('number or'):
            head = d.replace('number of', '', 1).replace('number or', '', 1).strip()
            head_first = re.split(r'[\s,]', head, 1)[0]
            if head_first in _HEAD_NOUN_TO_UNIT:
                return _HEAD_NOUN_TO_UNIT[head_first]
            # Category-based default for "Number of X" residuals.
            if category in ('POP', 'AGE', 'ETH', 'REL', 'DTH'):
                return 'persons'
            if category == 'BLD':
                return 'buildings'
            if category == 'MFG':
                return 'establishments'
            return 'count'
        if d.startswith('deaths'):
            return 'deaths'
        if d.startswith('total number of deaths'):
            return 'deaths'
        if d.startswith('ratio of'):
            return 'ratio'
        if 'logs produced' in d or d.startswith('logs '):
            return 'logs'
    return _infer_unit_from_name(variable_name)


def load_master_variables(mastvar_path):
    """
    Load master variables file to understand variable definitions.

    Mastvar covers regularized CSD/CD-format codes for 1851-1901. The
    1911/1921 PUB-format codes are documented in
    data/mastvar_supplement_1911_1921.csv and merged here.

    Returns:
        DataFrame with columns: Name, Description, Category, {years}
    """
    print(f"Loading master variables from {mastvar_path}...")
    df = pd.read_excel(mastvar_path)
    print(f"  Found {len(df)} variable definitions in Mastvar")

    supp_path = Path(__file__).resolve().parent.parent / 'data' / 'mastvar_supplement_1911_1921.csv'
    if supp_path.exists():
        supp = pd.read_csv(supp_path)
        print(f"  Found {len(supp)} additional codes in 1911/1921 PUB supplement")
        merged = pd.concat([df, supp], ignore_index=True, sort=False)
        merged = merged.drop_duplicates(subset='Name', keep='first')
        df = merged
        print(f"  Merged total: {len(df)} unique variable definitions")
    else:
        print(f"  WARNING: supplement not found at {supp_path}")
    print(f"  Categories: {sorted(df['Category'].dropna().unique().tolist())}")
    return df


_PILOT_YEARS = (1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921)


def _build_var_provenance_index(obs_dir):
    """Read p2_has_type, p70_documents, e73 CSVs from obs_dir; build:
        var_year_table[var_code][year] -> most-common source_table
        var_years[var_code] -> set of years
        var_count[var_code] -> total measurement-count across all years

    Returns (var_year_table, var_years, var_count). If any expected file is
    missing the function returns empty dicts and a warning is printed.
    """
    import csv as _csv
    from collections import defaultdict, Counter
    obs = Path(obs_dir)

    e73_path = obs / 'e73_information_objects.csv'
    if not e73_path.exists():
        print(f"  WARN: {e73_path} missing — provenance enrichment skipped")
        return {}, {}, {}
    src_table = {}
    with e73_path.open() as f:
        for r in _csv.DictReader(f):
            src_table[r['info_object_id:ID']] = r['source_table']

    var_year_table = defaultdict(lambda: defaultdict(Counter))
    var_years = defaultdict(set)
    var_count = Counter()
    for year in _PILOT_YEARS:
        p2 = obs / f'p2_has_type_{year}.csv'
        p70 = obs / f'p70_documents_{year}.csv'
        if not p2.exists():
            continue
        mid_to_var = {}
        with p2.open() as f:
            for r in _csv.DictReader(f):
                mid = r[':START_ID']
                v = r[':END_ID']
                mid_to_var[mid] = v
                var_years[v].add(year)
                var_count[v] += 1
        if p70.exists():
            with p70.open() as f:
                for r in _csv.DictReader(f):
                    sid = r[':START_ID']
                    mid = r[':END_ID']
                    v = mid_to_var.get(mid)
                    if v:
                        table = src_table.get(sid, '')
                        if table:
                            var_year_table[v][year][table] += 1
    # Collapse Counters to most-common single value per (var, year)
    flat = {}
    for v, ymap in var_year_table.items():
        flat[v] = {y: cnt.most_common(1)[0][0] for y, cnt in ymap.items()}
    return flat, dict(var_years), dict(var_count)


def _format_source_tables(var_year_table_map):
    """Render var->{year:table} as 'YYYY:Vxxx,YYYY:Vxxx' sorted by year."""
    if not var_year_table_map:
        return ''
    parts = [f"{y}:{tbl}" for y, tbl in sorted(var_year_table_map.items())]
    return ','.join(parts)


def _quality_for_count(presence_count):
    if presence_count == 0:
        return 'undocumented'
    if presence_count < 100:
        return 'sparse'
    return 'signal'


def create_variable_types(mastvar_df, output_dir, obs_dir=None):
    """
    Create E55_Type nodes for all variables.

    Enriched columns when obs_dir is provided (or defaults to output_dir):
      source_tables           - 'YYYY:Vxxx,YYYY:Vxxx' (per-year provenance)
      year_count              - number of distinct years where var appears
      comparable_across_years - true when year_count >= 2
      presence_count           - total measurement-count (nationwide)
      quality                 - undocumented | sparse | signal
    """
    print("\nCreating E55_Type variable taxonomy...")

    if obs_dir is None:
        obs_dir = output_dir
    var_year_table, var_years, var_count = _build_var_provenance_index(obs_dir)

    variable_types = []
    for _, row in mastvar_df.iterrows():
        var_name = row['Name']
        var_code = f"VAR_{var_name}"
        explicit_unit = row.get('Unit') if 'Unit' in mastvar_df.columns else None
        if explicit_unit and pd.notna(explicit_unit) and str(explicit_unit).strip():
            unit = str(explicit_unit).strip()
        else:
            unit = infer_unit(var_name, row.get('Description'), row.get('Category'))
        years = var_years.get(var_code, set())
        cnt = var_count.get(var_code, 0)
        variable_types.append({
            'type_id:ID': var_code,
            ':LABEL': 'E55_Type',
            'label': row['Description'],
            'category': row['Category'],
            'unit': unit,
            'variable_name': var_name,
            'source_tables': _format_source_tables(var_year_table.get(var_code, {})),
            'year_count': len(years),
            'comparable_across_years': 'true' if len(years) >= 2 else 'false',
            'presence_count': cnt,
            'quality': _quality_for_count(cnt),
        })

    df = pd.DataFrame(variable_types)
    output_path = output_dir / 'e55_variable_types.csv'
    df.to_csv(output_path, index=False)

    # Diagnostics
    qcounts = df['quality'].value_counts().to_dict()
    print(f"  Created {len(df)} variable types → {output_path}")
    print(f"    quality: {qcounts}")
    print(f"    comparable_across_years=true: {(df['comparable_across_years']=='true').sum()}")
    print(f"    units assigned: {(df['unit']!='unknown').sum()}/{len(df)}")
    return df


def load_gdb_layer(gdb_path, year):
    """
    Load GDB layer for a specific year.

    NOTE: For 1851-1901, uses single CANADA_{year}_CSD layer.
    For 1911/1921, this needs special handling (TODO).

    Args:
        gdb_path: Path to GDB file
        year: Census year (e.g., 1901)

    Returns:
        tuple: (GeoDataFrame with TCPUID, id_column_name)
    """
    layer_name = f"CANADA_{year}_CSD"

    print(f"\n  Loading GDB layer: {layer_name}")

    try:
        gdf = gpd.read_file(gdb_path, layer=layer_name)
    except Exception as e:
        print(f"    ERROR loading layer: {e}")
        return None, None

    print(f"    Features: {len(gdf)}")

    # Find TCPUID column
    tcpuid_col = f"TCPUID_CSD_{year}"
    if tcpuid_col not in gdf.columns:
        print(f"    ERROR: {tcpuid_col} not found")
        print(f"    Columns: {gdf.columns.tolist()}")
        return None, None

    print(f"    Using ID column: {tcpuid_col}")

    # Return just the TCPUID column
    return gdf[[tcpuid_col]], tcpuid_col


def normalize_column_name(col):
    """Normalize column name by removing year suffix."""
    # Remove _1911, _1901, etc. suffixes
    return re.sub(r'_\d{4}$', '', col)


def process_census_table(table_path, year, gdf_mapping, id_col_name, mastvar_df, source_name):
    """
    Process a single census table and create observations.

    Args:
        table_path: Path to Excel file
        year: Census year
        gdf_mapping: GeoDataFrame with TCPUID column
        id_col_name: Name of ID column in GDB (e.g., 'TCPUID_CSD_1901')
        mastvar_df: Master variables DataFrame
        source_name: Source table identifier (e.g., 'V1T1')

    Returns:
        List of observation dictionaries
    """
    print(f"\n  Processing {table_path.name}...")

    # Read table - try with and without skipping header rows
    df = None
    try:
        # Try without skipping (1851-1901 format)
        df = pd.read_excel(table_path)

        # Check if we have TCPUID column - if not, try skipping rows
        if f'TCPUID_CSD_{year}' not in df.columns:
            df = pd.read_excel(table_path, skiprows=3)

    except Exception as e:
        print(f"    ERROR reading file: {e}")
        return []

    # Find ID column - try multiple patterns
    id_col = None

    # Pattern 1: TCPUID_CSD_{year} (for 1851-1901)
    tcpuid_pattern = f'TCPUID_CSD_{year}'
    if tcpuid_pattern in df.columns:
        id_col = tcpuid_pattern
    else:
        # Pattern 2: {source_name}_{year} (for 1911+)
        for col in df.columns:
            col_str = str(col)  # Convert to string in case it's numeric
            if f'{source_name}_{year}' in col_str or col_str == f'{source_name}_{year}':
                id_col = col
                break

    if not id_col:
        print(f"    ERROR: Could not find ID column")
        print(f"    Looking for: TCPUID_CSD_{year} or {source_name}_{year}")
        print(f"    Columns: {df.columns.tolist()[:15]}")
        return []

    print(f"    Using ID column: {id_col}")
    print(f"    Processing {len(df)} rows...")

    # Get list of data columns (exclude metadata columns)
    metadata_cols = {
        'ROW_ID', id_col, 'PR', 'CD_NO', 'CSD_NO', 'PR_CD_CSD', 'NOTES', 'YEAR',
        'NAME_CD_' + str(year), 'NAME_CSD_' + str(year), 'NUMBER_CSD_' + str(year),
        'TCPUID_CD_' + str(year), 'TCPUID_CSD_' + str(year)
    }
    data_cols = [col for col in df.columns if col not in metadata_cols]
    print(f"    Found {len(data_cols)} data columns")

    observations = []
    rows_processed = 0

    for idx, row in df.iterrows():
        csd_table_id = row[id_col]

        # Skip invalid rows
        if pd.isna(csd_table_id):
            continue

            # For 1851-1901, the table ID (e.g., ON001001) IS the TCPUID
        # Validate it exists in GDB layer
        if gdf_mapping is not None:
            match = gdf_mapping[gdf_mapping[id_col_name] == csd_table_id]
            if len(match) == 0:
                continue  # Skip if ID not in GDB layer

        tcpuid = csd_table_id

        # Create observations for each non-null variable
        for col in data_cols:
            value = row[col]

            # Skip null values
            if pd.isna(value):
                continue

            # Normalize column name
            var_name_normalized = normalize_column_name(col)

            # Determine value type
            if isinstance(value, (int, float)):
                value_numeric = float(value)
                value_string = None
            else:
                value_numeric = None
                value_string = str(value)

            # Look up variable metadata from master variables
            var_info = mastvar_df[mastvar_df['Name'] == var_name_normalized]
            if len(var_info) > 0:
                category = var_info.iloc[0]['Category']
                description = var_info.iloc[0]['Description']
            else:
                category = 'UNKNOWN'
                description = col

            # Create observation
            obs = {
                'observation_id': f"{tcpuid}_{year}_{var_name_normalized}",
                'variable_name': var_name_normalized,
                'variable_category': category,
                'value_numeric': value_numeric,
                'value_string': value_string,
                'unit': infer_unit(var_name_normalized),
                'source_table': source_name,
                'presence_id': f"{tcpuid}_{year}",
                'period_id': f"CENSUS_{year}",
                'variable_type_id': f"VAR_{var_name_normalized}"
            }
            observations.append(obs)

        rows_processed += 1

    print(f"    Created {len(observations)} observations from {rows_processed} CSDs")
    return observations


def process_year_tables(year, tables_dir, gdb_path, mastvar_df, output_dir):
    """
    Process all tables for a given census year.

    Args:
        year: Census year (e.g., 1901)
        tables_dir: Directory containing year's tables
        gdb_path: Path to GDB file
        mastvar_df: Master variables DataFrame
        output_dir: Output directory for CSV files
    """
    print(f"\n{'='*60}")
    print(f"Processing Census Year: {year}")
    print(f"{'='*60}")

    # Load GDB layer for this year
    gdf_mapping, id_col_name = load_gdb_layer(gdb_path, year)

    if gdf_mapping is None:
        print(f"ERROR: Could not load GDB layer for {year}")
        return

    # Find all Excel files for this year
    year_dir = tables_dir / f"{year}Tables" / str(year)
    if not year_dir.exists():
        year_dir = tables_dir / str(year)

    if not year_dir.exists():
        print(f"ERROR: Year directory not found: {year_dir}")
        print(f"  Tried: {tables_dir / f'{year}Tables' / str(year)}")
        print(f"  Tried: {tables_dir / str(year)}")
        return

    excel_files = list(year_dir.glob('*.xlsx'))
    excel_files = [f for f in excel_files if not f.name.startswith('TCP_CANADA')]

    if len(excel_files) == 0:
        print(f"WARNING: No Excel files found in {year_dir}")
        return

    print(f"\nFound {len(excel_files)} Excel files:")
    for f in excel_files:
        print(f"  - {f.name}")

    # Process each table
    all_observations = []
    for excel_file in excel_files:
        # Extract source name (e.g., V1T1 from 1901_V1T1_PUB_202306.xlsx)
        match = re.search(r'_([VT]\d+[A-Z]*\d*)_', excel_file.name)
        if match:
            source_name = match.group(1)
        else:
            source_name = excel_file.stem.split('_')[1] if '_' in excel_file.stem else 'UNKNOWN'

        observations = process_census_table(
            excel_file, year, gdf_mapping, id_col_name, mastvar_df, source_name
        )
        all_observations.extend(observations)

    print(f"\nTotal observations for {year}: {len(all_observations)}")

    # Export to CSV files
    export_year_csvs(all_observations, year, output_dir)


def export_year_csvs(observations, year, output_dir):
    """
    Export observations to Neo4j CSV files.

    Args:
        observations: List of observation dictionaries
        year: Census year
        output_dir: Output directory
    """
    print(f"\nExporting Neo4j CSV files for {year}...")

    if len(observations) == 0:
        print("  No observations to export")
        return

    # 1. E13_Attribute_Assignment nodes
    e13_nodes = []
    for obs in observations:
        e13_nodes.append({
            'observation_id:ID': obs['observation_id'],
            ':LABEL': 'E13_Attribute_Assignment',
            'variable_name': obs['variable_name'],
            'variable_category': obs['variable_category'],
            'value_numeric:float': obs['value_numeric'] if obs['value_numeric'] is not None else '',
            'value_string': obs['value_string'] if obs['value_string'] is not None else '',
            'unit': obs['unit'],
            'source_table': obs['source_table'],
            'notes': ''
        })

    df = pd.DataFrame(e13_nodes)
    output_path = output_dir / f'e13_observations_{year}.csv'
    df.to_csv(output_path, index=False)
    print(f"  ✓ E13 nodes: {len(df)} → {output_path.name}")

    # 2. P140_assigned_attribute_to relationships
    p140_rels = []
    for obs in observations:
        p140_rels.append({
            ':START_ID': obs['observation_id'],
            ':END_ID': obs['presence_id'],
            ':TYPE': 'P140_assigned_attribute_to'
        })

    df = pd.DataFrame(p140_rels)
    output_path = output_dir / f'p140_observation_to_presence_{year}.csv'
    df.to_csv(output_path, index=False)
    print(f"  ✓ P140 relationships: {len(df)} → {output_path.name}")

    # 3. P4_has_time_span relationships
    p4_rels = []
    for obs in observations:
        p4_rels.append({
            ':START_ID': obs['observation_id'],
            ':END_ID': obs['period_id'],
            ':TYPE': 'P4_has_time_span'
        })

    df = pd.DataFrame(p4_rels)
    output_path = output_dir / f'p4_observation_to_period_{year}.csv'
    df.to_csv(output_path, index=False)
    print(f"  ✓ P4 relationships: {len(df)} → {output_path.name}")

    # 4. P2_has_type relationships
    p2_rels = []
    for obs in observations:
        p2_rels.append({
            ':START_ID': obs['observation_id'],
            ':END_ID': obs['variable_type_id'],
            ':TYPE': 'P2_has_type'
        })

    df = pd.DataFrame(p2_rels)
    output_path = output_dir / f'p2_observation_to_type_{year}.csv'
    df.to_csv(output_path, index=False)
    print(f"  ✓ P2 relationships: {len(df)} → {output_path.name}")

    # Summary statistics
    print(f"\n  Summary for {year}:")
    print(f"    Observations: {len(observations):,}")
    df_obs = pd.DataFrame(observations)
    print(f"    Unique CSDs: {df_obs['presence_id'].nunique():,}")
    print(f"    Unique variables: {df_obs['variable_name'].nunique():,}")
    print(f"    Categories: {df_obs['variable_category'].nunique()}")
    print(f"      {df_obs['variable_category'].value_counts().to_dict()}")


def main():
    parser = argparse.ArgumentParser(
        description='Build census observations for CIDOC-CRM knowledge graph'
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
        default='1911',
        help='Comma-separated list of years to process (e.g., "1911,1901")'
    )
    parser.add_argument(
        '--out',
        default='neo4j_census_observations',
        help='Output directory for Neo4j CSV files'
    )

    args = parser.parse_args()

    # Convert paths
    mastvar_path = Path(args.mastvar)
    gdb_path = Path(args.gdb)
    tables_dir = Path(args.tables_dir)
    output_dir = Path(args.out)

    # Validate inputs
    if not mastvar_path.exists():
        print(f"ERROR: Master variables file not found: {mastvar_path}")
        return 1

    if not gdb_path.exists():
        print(f"ERROR: GDB file not found: {gdb_path}")
        return 1

    # Create output directory
    output_dir.mkdir(exist_ok=True, parents=True)
    print(f"Output directory: {output_dir.absolute()}")

    # Load master variables
    mastvar_df = load_master_variables(mastvar_path)

    # Create variable type taxonomy
    create_variable_types(mastvar_df, output_dir)

    # Process each year
    years = [int(y.strip()) for y in args.years.split(',')]
    for year in years:
        process_year_tables(year, tables_dir, gdb_path, mastvar_df, output_dir)

    print(f"\n{'='*60}")
    print("✓ Census observations processing complete!")
    print(f"{'='*60}")
    print(f"\nOutput files in: {output_dir.absolute()}")
    print("\nNext steps:")
    print("1. Review CSV files for data quality")
    print("2. Load into Neo4j using LOAD CSV statements")
    print("3. Validate relationships to existing E93_Presence nodes")

    return 0


if __name__ == '__main__':
    sys.exit(main())
