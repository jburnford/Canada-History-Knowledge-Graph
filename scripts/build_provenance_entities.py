#!/usr/bin/env python3
"""
Generate CIDOC-CRM provenance entities for Canadian Census dataset.

Creates:
- E33_Linguistic_Object: Citations and DOIs
- E30_Right: License information (CC BY 4.0)
- E39_Actor: Dataset creators and contributors
- E65_Creation: Dataset creation activity

Author: Claude Code
Date: September 30, 2025
"""

import pandas as pd
from pathlib import Path
import argparse
import sys


def create_e33_citations() -> pd.DataFrame:
    """
    E33_Linguistic_Object - Citations and DOIs for dataset components.
    """
    citations = []

    # Main spatial boundary dataset
    citations.append({
        'citation_id:ID': 'CITATION_TCP_SPATIAL',
        ':LABEL': 'E33_Linguistic_Object',
        'citation_text': 'Cunfer, Geoff; Billard, Rhianne; McClean, Sauvelm; Richard, Laurent; St-Hilaire, Marc, 2023, "The Canadian Historical GIS (Temporal Census Polygons)", Borealis, V1',
        'doi': 'https://doi.org/10.5683/SP3/PKUZJN',
        'version': 'V1',
        'publication_date': '2023-06'
    })

    # Census year datasets
    census_years = {
        1851: ('SP3/NRPFY5', 'V3', '2023-10', 'Cunfer, Geoff; Billard, Rhianne; McClean, Sauvelm'),
        1861: ('SP3/1I1C59', 'V2', '2023-10', 'Cunfer, Geoff; Billard, Rhianne; McClean, Sauvelm'),
        1871: ('SP3/IYAR1W', 'V2', '2023-10', 'Cunfer, Geoff; Billard, Rhianne; McClean, Sauvelm'),
        1881: ('SP3/SFG7UI', 'V2', '2023-10', 'Cunfer, Geoff; Billard, Rhianne; McClean, Sauvelm'),
        1891: ('SP3/QA4AKE', 'V2', '2023-10', 'The Canadian Peoples / Les populations canadiennes Project; Cunfer, Geoff; Billard, Rhianne; McClean, Sauvelm'),
        1901: ('SP3/6XFJNU', 'V2', '2023-10', 'Cunfer, Geoff; Billard, Rhianne; McClean, Sauvelm'),
        1911: ('SP3/7ZG4XV', 'V2', '2023-10', 'Cunfer, Geoff; Richard, Laurent; St-Hilaire, Marc'),
        1921: ('SP3/JPGS9B', 'V2', '2023-10', 'Cunfer, Geoff; Richard, Laurent; St-Hilaire, Marc')
    }

    for year, (doi_suffix, version, date, authors) in census_years.items():
        citations.append({
            'citation_id:ID': f'CITATION_CENSUS_{year}',
            ':LABEL': 'E33_Linguistic_Object',
            'citation_text': f'{authors}, 2023, "The Canadian Historical GIS, {year} [Aggregate data]", Borealis, {version}',
            'doi': f'https://doi.org/10.5683/{doi_suffix}',
            'version': version,
            'publication_date': date
        })

    return pd.DataFrame(citations)


def create_e30_rights() -> pd.DataFrame:
    """
    E30_Right - License information for the dataset.
    """
    rights = [{
        'right_id:ID': 'LICENSE_CC_BY_4_0',
        ':LABEL': 'E30_Right',
        'label': 'Creative Commons Attribution 4.0 International',
        'access_rights': 'Open Access',
        'license_uri': 'https://creativecommons.org/licenses/by/4.0/',
        'description': 'Permits use, sharing, and adaptation with attribution'
    }]

    return pd.DataFrame(rights)


def create_e39_actors() -> pd.DataFrame:
    """
    E39_Actor - Dataset creators and contributors.
    """
    actors = []

    # Principal Investigators
    pis = [
        ('ACTOR_CUNFER_GEOFF', 'Geoff Cunfer', 'E21_Person', 'University of Saskatchewan'),
        ('ACTOR_BILLARD_RHIANNE', 'Rhianne Billard', 'E21_Person', 'University of Saskatchewan'),
        ('ACTOR_MCCLEAN_SAUVELM', 'Sauvelm McClean', 'E21_Person', 'University of Saskatchewan'),
        ('ACTOR_RICHARD_LAURENT', 'Laurent Richard', 'E21_Person', 'Université Laval'),
        ('ACTOR_ST_HILAIRE_MARC', 'Marc St-Hilaire', 'E21_Person', 'Université Laval')
    ]

    for actor_id, name, actor_type, affiliation in pis:
        actors.append({
            'actor_id:ID': actor_id,
            ':LABEL': 'E39_Actor',
            'name': name,
            'type': actor_type,
            'affiliation': affiliation,
            'orcid': '',  # Not available in public metadata
            'role': 'Principal Investigator'
        })

    # Project organization
    actors.append({
        'actor_id:ID': 'ACTOR_CANADIAN_PEOPLES_PROJECT',
        ':LABEL': 'E39_Actor',
        'name': 'The Canadian Peoples / Les populations canadiennes Project',
        'type': 'E74_Group',
        'affiliation': 'Multi-institutional collaboration',
        'orcid': '',
        'role': 'Project Organization',
        'website': 'https://thecanadianpeoples.com/team/'
    })

    # Repository
    actors.append({
        'actor_id:ID': 'ACTOR_BOREALIS_DATAVERSE',
        ':LABEL': 'E39_Actor',
        'name': 'Borealis - Canadian Dataverse Repository',
        'type': 'E74_Group',
        'affiliation': 'Scholars Portal',
        'orcid': '',
        'role': 'Data Repository',
        'website': 'https://borealisdata.ca/dataverse/census'
    })

    return pd.DataFrame(actors)


def create_e65_creation() -> pd.DataFrame:
    """
    E65_Creation - Dataset creation/publication activity.
    """
    creation = [{
        'creation_id:ID': 'CREATION_CHGIS_TCP',
        ':LABEL': 'E65_Creation',
        'label': 'Creation of Canadian Historical GIS Temporal Census Polygons',
        'description': 'Development and publication of historical census subdivision boundaries and aggregate census data for Canada 1851-1921',
        'timespan_start': '2018-01-01',  # Project start (approximate)
        'timespan_end': '2023-10-31'     # Last data version publication
    }]

    return pd.DataFrame(creation)


def create_p67_refers_to() -> pd.DataFrame:
    """
    P67_refers_to: E33_Linguistic_Object -> E73_Information_Object
    Link citations to source files.
    """
    relationships = []

    # Spatial dataset citation refers to all spatial data
    relationships.append({
        ':START_ID': 'CITATION_TCP_SPATIAL',
        ':END_ID': 'SOURCE_TCP_SPATIAL_GDB',
        ':TYPE': 'P67_refers_to',
        'note': 'Citation for geospatial boundary dataset'
    })

    # Each census year citation refers to its aggregate data tables
    for year in [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921]:
        relationships.append({
            ':START_ID': f'CITATION_CENSUS_{year}',
            ':END_ID': f'SOURCE_CENSUS_{year}_AGGREGATE',
            ':TYPE': 'P67_refers_to',
            'note': f'Citation for {year} census aggregate data'
        })

    return pd.DataFrame(relationships)


def create_p104_is_subject_to() -> pd.DataFrame:
    """
    P104_is_subject_to: E73_Information_Object -> E30_Right
    Link source files to license.
    """
    relationships = []

    # Spatial dataset subject to CC BY 4.0
    relationships.append({
        ':START_ID': 'SOURCE_TCP_SPATIAL_GDB',
        ':END_ID': 'LICENSE_CC_BY_4_0',
        ':TYPE': 'P104_is_subject_to'
    })

    # Each census year dataset subject to CC BY 4.0
    for year in [1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921]:
        relationships.append({
            ':START_ID': f'SOURCE_CENSUS_{year}_AGGREGATE',
            ':END_ID': 'LICENSE_CC_BY_4_0',
            ':TYPE': 'P104_is_subject_to'
        })

    return pd.DataFrame(relationships)


def create_p14_carried_out() -> pd.DataFrame:
    """
    P14_carried_out: E39_Actor -> E65_Creation
    Link actors to creation activity.
    """
    actors = [
        'ACTOR_CUNFER_GEOFF',
        'ACTOR_BILLARD_RHIANNE',
        'ACTOR_MCCLEAN_SAUVELM',
        'ACTOR_RICHARD_LAURENT',
        'ACTOR_ST_HILAIRE_MARC',
        'ACTOR_CANADIAN_PEOPLES_PROJECT'
    ]

    relationships = []
    for actor_id in actors:
        relationships.append({
            ':START_ID': actor_id,
            ':END_ID': 'CREATION_CHGIS_TCP',
            ':TYPE': 'P14_carried_out'
        })

    return pd.DataFrame(relationships)


def create_e73_placeholder_sources() -> pd.DataFrame:
    """
    Create placeholder E73_Information_Object nodes for provenance linking.
    These will be used by P67 and P104 relationships.
    """
    sources = []

    # Main spatial GDB
    sources.append({
        'info_object_id:ID': 'SOURCE_TCP_SPATIAL_GDB',
        ':LABEL': 'E73_Information_Object',
        'label': 'TCP_CANADA_CSD_202306.gdb',
        'source_table': 'GDB',
        'file_hash': '',
        'access_uri': 'https://borealisdata.ca/api/access/datafile/:persistentId/?persistentId=doi:10.5683/SP3/PKUZJN',
        'landing_page': 'https://borealisdata.ca/dataset.xhtml?persistentId=doi:10.5683/SP3/PKUZJN'
    })

    # Census year aggregate datasets (placeholders)
    census_dois = {
        1851: 'SP3/NRPFY5', 1861: 'SP3/1I1C59', 1871: 'SP3/IYAR1W', 1881: 'SP3/SFG7UI',
        1891: 'SP3/QA4AKE', 1901: 'SP3/6XFJNU', 1911: 'SP3/7ZG4XV', 1921: 'SP3/JPGS9B'
    }

    for year, doi_suffix in census_dois.items():
        sources.append({
            'info_object_id:ID': f'SOURCE_CENSUS_{year}_AGGREGATE',
            ':LABEL': 'E73_Information_Object',
            'label': f'{year} Census Aggregate Data Collection',
            'source_table': 'COLLECTION',
            'file_hash': '',
            'access_uri': f'https://borealisdata.ca/api/access/datafile/:persistentId/?persistentId=doi:10.5683/{doi_suffix}',
            'landing_page': f'https://borealisdata.ca/dataset.xhtml?persistentId=doi:10.5683/{doi_suffix}'
        })

    return pd.DataFrame(sources)


def main():
    parser = argparse.ArgumentParser(description='Generate CIDOC-CRM provenance entities')
    parser.add_argument('--out', required=True, help='Output directory')
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True, parents=True)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Generating CIDOC-CRM Provenance Entities", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # Generate entity nodes
    print(f"\nCreating entity nodes...", file=sys.stderr)

    e33_citations = create_e33_citations()
    e33_file = out_dir / 'e33_linguistic_objects.csv'
    e33_citations.to_csv(e33_file, index=False)
    print(f"  ✓ E33_Linguistic_Object: {len(e33_citations)} citations → {e33_file}", file=sys.stderr)

    e30_rights = create_e30_rights()
    e30_file = out_dir / 'e30_rights.csv'
    e30_rights.to_csv(e30_file, index=False)
    print(f"  ✓ E30_Right: {len(e30_rights)} license → {e30_file}", file=sys.stderr)

    e39_actors = create_e39_actors()
    e39_file = out_dir / 'e39_actors.csv'
    e39_actors.to_csv(e39_file, index=False)
    print(f"  ✓ E39_Actor: {len(e39_actors)} actors → {e39_file}", file=sys.stderr)

    e65_creation = create_e65_creation()
    e65_file = out_dir / 'e65_creation.csv'
    e65_creation.to_csv(e65_file, index=False)
    print(f"  ✓ E65_Creation: {len(e65_creation)} creation event → {e65_file}", file=sys.stderr)

    e73_sources = create_e73_placeholder_sources()
    e73_file = out_dir / 'e73_information_objects_provenance.csv'
    e73_sources.to_csv(e73_file, index=False)
    print(f"  ✓ E73_Information_Object: {len(e73_sources)} sources → {e73_file}", file=sys.stderr)

    # Generate relationships
    print(f"\nCreating relationships...", file=sys.stderr)

    p67_refers = create_p67_refers_to()
    p67_file = out_dir / 'p67_refers_to.csv'
    p67_refers.to_csv(p67_file, index=False)
    print(f"  ✓ P67_refers_to: {len(p67_refers)} relationships → {p67_file}", file=sys.stderr)

    p104_subject = create_p104_is_subject_to()
    p104_file = out_dir / 'p104_is_subject_to.csv'
    p104_subject.to_csv(p104_file, index=False)
    print(f"  ✓ P104_is_subject_to: {len(p104_subject)} relationships → {p104_file}", file=sys.stderr)

    p14_carried = create_p14_carried_out()
    p14_file = out_dir / 'p14_carried_out.csv'
    p14_carried.to_csv(p14_file, index=False)
    print(f"  ✓ P14_carried_out: {len(p14_carried)} relationships → {p14_file}", file=sys.stderr)

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SUMMARY", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"Total provenance entities: {len(e33_citations) + len(e30_rights) + len(e39_actors) + len(e65_creation) + len(e73_sources)}", file=sys.stderr)
    print(f"  E33_Linguistic_Object: {len(e33_citations)} (citations/DOIs)", file=sys.stderr)
    print(f"  E30_Right: {len(e30_rights)} (license)", file=sys.stderr)
    print(f"  E39_Actor: {len(e39_actors)} (creators)", file=sys.stderr)
    print(f"  E65_Creation: {len(e65_creation)} (creation activity)", file=sys.stderr)
    print(f"  E73_Information_Object: {len(e73_sources)} (source files)", file=sys.stderr)
    print(f"\nTotal provenance relationships: {len(p67_refers) + len(p104_subject) + len(p14_carried)}", file=sys.stderr)
    print(f"  P67_refers_to: {len(p67_refers)}", file=sys.stderr)
    print(f"  P104_is_subject_to: {len(p104_subject)}", file=sys.stderr)
    print(f"  P14_carried_out: {len(p14_carried)}", file=sys.stderr)
    print(f"\nOutput directory: {out_dir}/", file=sys.stderr)
    print(f"", file=sys.stderr)


if __name__ == '__main__':
    main()
