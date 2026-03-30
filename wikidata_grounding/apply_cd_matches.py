#!/usr/bin/env python3
"""Apply Phase 1 CD matches found via MCP Wikidata search + SPARQL."""

import csv

INPUT = "wikidata_grounding/cd_wikidata_matches.csv"
OUTPUT = "wikidata_grounding/cd_wikidata_matches.csv"  # overwrite in place

# All new matches keyed by cd_id
NEW_MATCHES = {
    # Ontario manual fixes
    "CD_ON_Brant": ("Q384944", "County of Brant", "county of Ontario"),
    "CD_ON_Grenville": ("Q5607516", "Grenville County", "former county of Ontario"),
    "CD_ON_Haldimand": ("Q385346", "Haldimand County", "county of Ontario"),
    "CD_ON_Norfolk": ("Q385229", "Norfolk County", "county of Ontario"),
    "CD_ON_Oxford": ("Q382652", "Oxford County", "county of Ontario"),
    # Ontario - MCP search
    "CD_ON_Prince_Edward": ("Q385085", "Prince Edward County", "municipality in Ontario"),
    # Ontario - minted URI (no Wikidata entity)
    "CD_ON_Muskoka": ("", "", "MINTED_URI: no Wikidata entity for Muskoka District as historic CD"),

    # PEI
    "CD_PE_Queens": ("Q2006290", "Queens County", "county of Prince Edward Island"),
    "CD_PE_Kings": ("Q1742133", "Kings County", "county of Prince Edward Island"),
    "CD_PE_Prince": ("Q2110336", "Prince County", "county of Prince Edward Island"),

    # Quebec - from SPARQL bulk query of Q2991491 instances
    "CD_QC_Montmagny": ("Q2991338", "comté de Montmagny", "historic county of Quebec"),
    "CD_QC_Pontiac": ("Q16543141", "comté de Pontiac", "historic county of Quebec"),
    "CD_QC_L'Assomption": ("Q2991286", "comté de L'Assomption", "historic county of Quebec"),
    "CD_QC_Rimouski": ("Q2991393", "comté de Rimouski", "historic county of Quebec"),
    "CD_QC_Matane": ("Q2991318", "comté de Matane", "historic county of Quebec"),
    "CD_QC_Napierville": ("Q2991357", "comté de Napierville", "historic county of Quebec"),
    "CD_QC_Joliette": ("Q2991275", "comté de Joliette", "historic county of Quebec"),
    "CD_QC_Stanstead": ("Q2991434", "comté de Stanstead", "historic county of Quebec"),
    "CD_QC_Témiscamingue": ("Q16543153", "comté de Témiscamingue", "historic county of Quebec"),
    "CD_QC_Iberville": ("Q2991101", "comté d'Iberville", "historic county of Quebec"),
    "CD_QC_Charlevoix": ("Q2991176", "comté de Charlevoix", "historic county of Quebec"),
    "CD_QC_Maskinongé": ("Q2991316", "comté de Maskinongé", "historic county of Quebec"),
    "CD_QC_Témiscouata": ("Q2991451", "comté de Témiscouata", "historic county of Quebec"),
    "CD_QC_Huntingdon": ("Q2991267", "Huntingdon County", "historic county of Quebec"),
    "CD_QC_Beauce": ("Q2991122", "comté de Beauce", "historic county of Quebec"),
    "CD_QC_St._Hyacinthe": ("Q2991405", "comté de Saint-Hyacinthe", "historic county of Quebec"),
    "CD_QC_St._Maurice": ("Q2991407", "comté de Saint-Maurice", "historic county of Quebec"),
    "CD_QC_Gaspé": ("Q2991234", "comté de Gaspé", "historic county of Quebec"),
    "CD_QC_Montcalm": ("Q2991334", "comté de Montcalm", "historic county of Quebec"),
    "CD_QC_Lotbinière": ("Q2991307", "comté de Lotbinière", "historic county of Quebec"),
    "CD_QC_Verchères": ("Q2991456", "comté de Verchères", "historic county of Quebec"),
    "CD_QC_Frontenac": ("Q2991230", "Frontenac County", "historic county of Quebec"),
    "CD_QC_Deux_Montagnes": ("Q2991213", "comté de Deux-Montagnes", "historic county of Quebec"),
    "CD_QC_Beauharnois": ("Q2991124", "comté de Beauharnois", "historic county of Quebec"),
    "CD_QC_Châteauguay": ("Q2991186", "comté de Châteauguay", "historic county of Quebec"),
    "CD_QC_Wolfe": ("Q2991471", "comté de Wolfe", "historic county of Quebec"),
    "CD_QC_Sherbrooke": ("Q2991427", "comté de Sherbrooke", "historic county of Quebec"),
    "CD_QC_Yamaska": ("Q2991475", "comté de Yamaska", "historic county of Quebec"),
    "CD_QC_Bagot": ("Q2991115", "comté de Bagot", "historic county of Quebec"),
    "CD_QC_Rouville": ("Q2991403", "comté de Rouville", "historic county of Quebec"),
    "CD_QC_Soulanges": ("Q16543148", "comté de Soulanges", "historic county of Quebec"),
    "CD_QC_L'IsIet": ("Q2991287", "comté de L'Islet", "historic county of Quebec"),
    # QC ambiguous - using best match, flagged in type
    "CD_QC_Montmorency": ("Q2991335", "comté de Montmorency No. 1", "historic county of Quebec [NOTE: 1921 CD covers both No.1+No.2]"),
    "CD_QC_Lac_St._Jean": ("Q2991289", "comté de Lac-Saint-Jean-Est", "historic county of Quebec [NOTE: 1921 CD covers both Est+Ouest]"),
    # QC - no single entity
    "CD_QC_Montréal_&_Jésus_Islands—Iles": ("", "", "MINTED_URI: composite CD (Île de Montréal + Île Jésus)"),

    # Newfoundland/Labrador
    "CD_NL_Labrador": ("Q380307", "Labrador", "region of Newfoundland and Labrador"),
    "CD_NL_Newfoundland": ("Q48335", "Newfoundland", "island of Newfoundland and Labrador"),

    # Territories
    "CD_YT_Yukon": ("Q2009", "Yukon", "territory of Canada"),
    "CD_NT_Northwest_Territories": ("Q2007", "Northwest Territories", "territory of Canada"),

    # BC - all minted URIs (1921 census divisions based on electoral districts)
    "CD_BC_Yale": ("", "", "MINTED_URI: BC electoral district-based CD"),
    "CD_BC_Cariboo": ("", "", "MINTED_URI: BC electoral district-based CD"),
    "CD_BC_New_Westminster": ("", "", "MINTED_URI: BC electoral district-based CD"),
    "CD_BC_Burrard": ("", "", "MINTED_URI: BC electoral district-based CD"),
    "CD_BC_Vancouver_Centre": ("", "", "MINTED_URI: BC electoral district-based CD"),
    "CD_BC_Vancouver_South": ("", "", "MINTED_URI: BC electoral district-based CD"),
    "CD_BC_Comox-Alberni": ("", "", "MINTED_URI: BC electoral district-based CD"),
    "CD_BC_Nanaimo": ("", "", "MINTED_URI: BC electoral district-based CD"),
    "CD_BC_Skeena": ("", "", "MINTED_URI: BC electoral district-based CD"),
    "CD_BC_Fraser_Valley": ("", "", "MINTED_URI: BC electoral district-based CD"),
    "CD_BC_Victoria_City": ("", "", "MINTED_URI: BC electoral district-based CD"),
    "CD_BC_Kootenay_West": ("", "", "MINTED_URI: BC electoral district-based CD"),
    "CD_BC_Kootenay_East": ("", "", "MINTED_URI: BC electoral district-based CD"),
}

# Read
rows = []
with open(INPUT) as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

# Apply
applied = 0
for row in rows:
    cd_id = row["cd_id"]
    if cd_id in NEW_MATCHES:
        qid, label, wtype = NEW_MATCHES[cd_id]
        if qid or not row["wikidata_qid"]:  # don't overwrite existing match with empty
            row["wikidata_qid"] = qid
            row["wikidata_label"] = label
            row["wikidata_type"] = wtype
            applied += 1

# Write
with open(OUTPUT, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "cd_id", "cd_name", "province", "wikidata_qid", "wikidata_label", "wikidata_type",
    ])
    writer.writeheader()
    writer.writerows(rows)

# Stats
total = len(rows)
matched = sum(1 for r in rows if r["wikidata_qid"])
minted = sum(1 for r in rows if "MINTED_URI" in r.get("wikidata_type", ""))
empty = total - matched - minted
print(f"Applied {applied} new matches")
print(f"Total CDs: {total}")
print(f"  Wikidata QID: {matched}")
print(f"  Minted URI:   {minted}")
print(f"  Unmatched:    {empty}")
