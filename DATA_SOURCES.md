# Data Sources and Attribution

## Canadian Historical Census Data

### TCP Canada Historical GIS Project
**Source**: The Canadian Century Research Infrastructure (CCRI)
**Publisher**: University of Saskatchewan
**DOI**: 10.5683/SP3/QVTLFP
**Years**: 1851-1921
**Description**: Trans-Century Polygon (TCP) geospatial census subdivision boundaries and historical census tables

### 1921 Census Tables
**Title**: Canada Tables, 1921 Census of Canada, HGIS Data
**Authors**: Geoff Cunfer, John Bonnett, Marvin McInnes, Ryan Driskell Tate, Kris Inwood
**Publisher**: Borealis, the Canadian Dataverse Repository
**Year**: 2024
**DOI**: [10.5683/SP3/JPGS9B](https://doi.org/10.5683/SP3/JPGS9B)
**URL**: https://borealisdata.ca/dataset.xhtml?persistentId=doi:10.5683/SP3/JPGS9B
**License**: CC0 1.0 Universal (Public Domain Dedication)

Files used:
- 1921_V1T16_PUB_202306.xlsx - Population by birthplace
- 1921_V1T27_PUB_202306.xlsx - Population demographics
- 1921_V1T38_PUB_202306.xlsx - Additional census variables
- 1921_V3T3_PUB_202306.xlsx - Supplementary tables
- TCP_CANADA_CD-CSD_Mastvar.xlsx - Variable crosswalk

### TCP HGIS Spatial Boundaries
**Source**: TCP_CANADA_CSD_202306.gdb
**Layers Used**:
- CANADA_1851_CSD through CANADA_1921_CSD
- Special variants: CANADA_1911_CSD_V2T2 (population-aligned spatial data)

## Linked Open Data Sources

### Wikidata
**URL**: https://www.wikidata.org
**Query Date**: October 2025
**Entities**: Canadian municipalities, cities, towns, villages
**Purpose**: Persistent identifiers (PIDs) for community linking

### GeoNames
**URL**: https://www.geonames.org
**Purpose**: Geographic cross-referencing and persistent identifiers

## Ontologies

### CIDOC Conceptual Reference Model (CRM)
**Version**: 7.1.1
**URL**: http://www.cidoc-crm.org/
**Purpose**: Cultural heritage and spatio-temporal modeling

Classes used:
- E4_Period (census years)
- E16_Measurement (census observations)
- E42_Identifier (external PIDs)
- E53_Place (geographic entities)
- E54_Dimension (measurement dimensions)
- E73_Information_Object (census tables/volumes)
- E93_Presence (temporal manifestations of places)
- E94_Space_Primitive (coordinates)

## Citation

If you use this dataset, please cite:

```bibtex
@dataset{cunfer_2024_1921,
  author    = {Cunfer, Geoff and Bonnett, John and McInnes, Marvin and
               Driskell Tate, Ryan and Inwood, Kris},
  title     = {Canada Tables, 1921 Census of Canada, HGIS Data},
  year      = {2024},
  publisher = {Borealis},
  doi       = {10.5683/SP3/JPGS9B},
  url       = {https://doi.org/10.5683/SP3/JPGS9B}
}
```

## License

This derived dataset follows the licenses of its source materials:
- 1921 Census Tables: CC0 1.0 (Public Domain)
- TCP HGIS Spatial Data: Check with University of Saskatchewan
- Wikidata: CC0 1.0 (Public Domain)
- GeoNames: CC BY 4.0

The CIDOC-CRM transformation and graph structure are licensed under CC BY 4.0.

---

**Last Updated**: October 2, 2025
