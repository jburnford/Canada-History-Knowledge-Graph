# Canadian Census CIDOC-CRM RDF Data

**Generated**: November 5, 2025
**Format**: RDF/Turtle (TTL)
**Standard**: CIDOC-CRM 7.1.x
**Coverage**: Canadian Census 1851-1921 (8 census years)

## Overview

This directory contains RDF Turtle files generated from CIDOC-CRM compliant CSV data. The RDF represents:
- **Spatial structure**: Canadian Census Subdivisions (CSDs) and Census Divisions (CDs)
- **Temporal manifestations**: Place presences during specific census years
- **Spatial projections**: Geographic coordinates (WGS84 centroids)
- **Administrative hierarchy**: CSD within CD relationships
- **Spatial adjacency**: Border relationships with shared lengths
- **Temporal continuity**: Spatiotemporal overlaps across census years

## Files Generated

### canada_cidoc_places_1851_1921.ttl
**Size**: 25 MB
**Lines**: 605,332 triples

**Contents**:
- **5,363 E53_Place (CSD)**: Census Subdivision places
- **222 E53_Place (CD)**: Census Division places
- **8 E4_Period**: Census years (1851, 1861, 1871, 1881, 1891, 1901, 1911, 1921)
- **20,811 E93_Presence**: Temporal manifestations of CSDs
- **20,811 E94_Space_Primitive**: Centroid coordinates (WGS84 lat/lon)

**Relationships**:
- **20,811 P166_was_a_presence_of**: Presence → Place
- **20,811 P164_is_temporally_specified_by**: Presence → Period
- **20,811 P161_has_spatial_projection**: Presence → Space
- **20,811 P89_falls_within**: CSD → CD hierarchy
- **45,142 P122_borders_with**: Border adjacency with lengths
- **17,060 P132_spatiotemporally_overlaps_with**: Temporal continuity

**Special Features**:
- **476 canonical name corrections** applied for OCR errors
- Includes overlap metadata (IoU, fractions, relationship types)
- Border lengths in meters for spatial adjacency
- Full temporal chain linking from 1851 to 1921

## RDF Structure

### Namespaces

```turtle
@prefix crm: <http://www.cidoc-crm.org/cidoc-crm/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix geo: <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix ex: <https://canada.census.example.org/> .
```

### Entity Examples

#### E53_Place (Census Subdivision)
```turtle
ex:place/ON038001 a crm:E53_Place ;
  rdfs:label "Toronto" ;
  ex:placeType "CSD" .
```

#### E4_Period (Census Year)
```turtle
ex:period/CENSUS_1901 a crm:E4_Period ;
  rdfs:label "1901 Canadian Census" ;
  ex:year "1901"^^xsd:gYear ;
  crm:P82a_begin_of_the_begin "1901-01-01"^^xsd:date ;
  crm:P82b_end_of_the_end "1901-12-31"^^xsd:date .
```

#### E93_Presence (Temporal Manifestation)
```turtle
ex:presence/ON038001_1901 a crm:E93_Presence ;
  ex:csdTcpuid "ON038001" ;
  ex:censusYear 1901 ;
  ex:areaSqM "123456789.12"^^xsd:decimal ;
  ex:canonicalName "Toronto" .
```

#### E94_Space_Primitive (Centroid)
```turtle
ex:space/ON038001_1901 a crm:E94_Space_Primitive ;
  geo:lat "43.6532"^^xsd:decimal ;
  geo:long "-79.3832"^^xsd:decimal ;
  ex:crs "EPSG:4326" .
```

### Relationship Examples

#### P132_spatiotemporally_overlaps_with (Temporal Continuity)
```turtle
ex:presence/ON038001_1901 crm:P132_spatiotemporally_overlaps_with ex:presence/ON038001_1911 ;
  ex:overlapType "SAME_AS" ;
  ex:intersectionOverUnion "1.0"^^xsd:decimal ;
  ex:fromFraction "1.0"^^xsd:decimal ;
  ex:toFraction "1.0"^^xsd:decimal ;
  ex:yearFrom 1901 ;
  ex:yearTo 1911 .
```

#### P122_borders_with (Spatial Adjacency)
```turtle
ex:place/ON038001 crm:P122_borders_with ex:place/ON038002 ;
  ex:sharedBorderLengthM "5420.15"^^xsd:decimal ;
  ex:duringPeriod ex:period/CENSUS_1901 .
```

## SPARQL Query Examples

### Find all temporal manifestations of a place
```sparql
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX ex: <https://canada.census.example.org/>

SELECT ?year ?area ?lat ?lon
WHERE {
  ex:place/ON038001 ^crm:P166_was_a_presence_of ?presence .
  ?presence ex:censusYear ?year ;
           ex:areaSqM ?area ;
           crm:P161_has_spatial_projection ?space .
  ?space geo:lat ?lat ;
         geo:long ?lon .
}
ORDER BY ?year
```

### Find places that split between census years
```sparql
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX ex: <https://canada.census.example.org/>

SELECT ?place1 ?place2 ?year1 ?year2
WHERE {
  ?pres1 crm:P132_spatiotemporally_overlaps_with ?pres2 .
  ?pres1 ex:overlapType "CONTAINS" ;
         ex:censusYear ?year1 ;
         crm:P166_was_a_presence_of ?place1 .
  ?pres2 ex:censusYear ?year2 ;
         crm:P166_was_a_presence_of ?place2 .
}
ORDER BY ?year1 ?year2
```

### Find CSDs with canonical name corrections
```sparql
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX ex: <https://canada.census.example.org/>

SELECT ?tcpuid ?year ?canonicalName
WHERE {
  ?presence ex:csdTcpuid ?tcpuid ;
           ex:censusYear ?year ;
           ex:canonicalName ?canonicalName .
}
```

### Find neighboring CSDs in a specific year
```sparql
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX ex: <https://canada.census.example.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?neighborLabel ?borderLength
WHERE {
  ex:place/ON038001 crm:P122_borders_with ?neighbor ;
                    ex:duringPeriod ex:period/CENSUS_1901 ;
                    ex:sharedBorderLengthM ?borderLength .
  ?neighbor rdfs:label ?neighborLabel .
}
ORDER BY DESC(?borderLength)
```

## Loading into Triple Stores

### Apache Jena Fuseki
```bash
# Start Fuseki server
fuseki-server --update --mem /canada

# Load data via HTTP PUT
curl -X PUT \
  -H "Content-Type: text/turtle" \
  --data-binary @canada_cidoc_places_1851_1921.ttl \
  http://localhost:3030/canada/data
```

### GraphDB
```bash
# Import via GraphDB Workbench UI
# 1. Create repository "canada-census"
# 2. Import > RDF > Upload RDF files
# 3. Select canada_cidoc_places_1851_1921.ttl
```

### Blazegraph
```bash
# Load via REST API
curl -X POST \
  -H "Content-Type: text/turtle" \
  --data-binary @canada_cidoc_places_1851_1921.ttl \
  http://localhost:9999/blazegraph/namespace/kb/sparql
```

## Generation Details

### Source Data
- **CSV Directory**: `neo4j_cidoc_crm/` (67 CSV files, 9.7 MB)
- **Canonical Names**: `canonical_names_final.csv` (476 OCR corrections)
- **Temporal Links**: `year_links_output/` (17,060 high-confidence links)

### Generation Command
```bash
python3 scripts/rdf_from_cidoc_csv.py \
  --csv-dir neo4j_cidoc_crm \
  --canonical canonical_names_final.csv \
  --base https://canada.census.example.org/ \
  --out generated/canada/canada_cidoc_places_1851_1921.ttl
```

### Script Features
- Reads Neo4j CSV format (`:ID`, `:LABEL`, `:START_ID`, `:END_ID`)
- Converts all CIDOC-CRM entities and properties to RDF
- Applies canonical name corrections where `should_apply=True`
- Generates proper RDF datatypes (xsd:decimal, xsd:gYear, xsd:date)
- Uses WGS84 geo vocabulary for coordinates

## Data Quality

### Canonical Names Applied
**476 corrections** from OCR errors and name variants:
- Spelling variants: "Melvern" → "Malvern"
- Apostrophe variants: "Parker Cove" → "Parker's Cove"
- Similar names: "Clarendon" → "Carleton"
- Accent variants: "St. Léonard" → "St. Leonard's"

**3,179 intentional name changes preserved**:
- Berlin → Kitchener (1916 wartime rename)
- Ward reorganizations in cities
- Municipal amalgamations

### Temporal Continuity
**17,060 spatiotemporal overlaps** classified as:
- **SAME_AS**: High overlap (IoU > 0.98), stable boundaries
- **CONTAINS**: Place split into multiple smaller places
- **WITHIN**: Place merged from larger area
- **OVERLAPS**: Partial overlap (boundary adjustments)

### Spatial Coverage
- **Provinces**: ON, QC, NS, NB, PE, MB, SK, AB, BC, NL, YT, NT
- **Eastern provinces**: Complete coverage from 1851
- **Western provinces**: MB (1871+), SK/AB (1891+), BC (1871+)
- **Coordinate precision**: 6 decimal places (~0.11 meters)
- **Area precision**: Square meters (2 decimal places)

## Next Steps

### Add Census Observation Data
Enhance with actual census measurements (population, demographics, agriculture):
```bash
python3 scripts/rdf_generate_census_observations.py \
  --places generated/canada/canada_cidoc_places_1851_1921.ttl \
  --census-zip 1901Tables.zip \
  --year 1901 \
  --out generated/canada/canada_observations_1901.ttl
```

This would add:
- **E16_Measurement**: Census observations
- **E54_Dimension**: Values with units (person, acre, bushel, etc.)
- **P39_measured**: Link measurements to E93_Presence nodes

### Load into Neo4j
Convert back to property graph for graph queries:
```bash
# Use neosemantics (n10s) plugin
CALL n10s.rdf.import.fetch(
  "file:///canada_cidoc_places_1851_1921.ttl",
  "Turtle"
);
```

### Export to Other Formats
```bash
# Convert to N-Triples
rapper -i turtle -o ntriples canada_cidoc_places_1851_1921.ttl > canada.nt

# Convert to RDF/XML
rapper -i turtle -o rdfxml canada_cidoc_places_1851_1921.ttl > canada.rdf

# Convert to JSON-LD
riot --syntax=turtle --output=jsonld canada_cidoc_places_1851_1921.ttl > canada.jsonld
```

## References

- **CIDOC-CRM**: http://www.cidoc-crm.org/
- **WGS84 Geo Vocabulary**: http://www.w3.org/2003/01/geo/wgs84_pos#
- **Statistics Canada TCP**: https://www.statcan.gc.ca/en/lode/databases/hgis
- **SPARQL 1.1**: https://www.w3.org/TR/sparql11-query/

---

**Generated by**: `scripts/rdf_from_cidoc_csv.py`
**Script version**: 1.0
**Date**: November 5, 2025
