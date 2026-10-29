# -*- coding: utf-8 -*-
# Fil: plugins/dealers_manager/synonyms.py
# Copyright © 2025 Rickard Längkvist
"""
Kolumnsynonymer för återförsäljare-import.

ANSVAR:
  - Centraliserad definition av kolumnsynonymer
  - Används av Plugin._find_column() vid Excel-import
  - Auto-detekterar kolumnnamn oavsett Excel-filens namngivning
  - Case-insensitive matchning

IMPORTER:
  typing (Final, List)

ANVÄNDS AV:
  plugins/dealers_manager/plugin.py
    → Plugin._find_column()
    → Plugin._process_excel_sheet()

EXPORTERAR:
  DN_SYNONYMS:   List[str] - Dealer Number kolumnnamn
  NAMN_SYNONYMS: List[str] - Namn/företagsnamn kolumnnamn
  T6_SYNONYMS:   List[str] - Region/T6/orgnummer kolumnnamn
"""

from __future__ import annotations

from typing import Final, List

# ══════════════════════════════════════════════════════════════════════════════
# DEALER NUMBER SYNONYMER
# ══════════════════════════════════════════════════════════════════════════════
# Matchar kolumner som innehåller återförsäljarens unika identifierare.
# Prioritetsordning: specifika först, generella sist.

DN_SYNONYMS: Final[List[str]] = [
    # Primära (vanligast)
    "dn",
    "dealer number",
    "dealer_number",
    "dealernumber",
    "dealer nr",
    "dealernr",
    "dealer code",
    "dealercode",
    "dealer id",
    "dealerid",
    # SAP/Dispatch-varianter
    "sold to dealer",
    "sold-to dealer",
    "sold-to party",
    "sold-to customer",
    "sold to customer",
    "soldtodealer",
    # Svenska varianter
    "kundnummer",
    "kundnr",
    "dnr",
    # Generella
    "customer number",
    "customer_number",
    "customernumber",
    "customerid",
    "customer id",
    "client code",
    "client_code",
    "partner code",
    "partner_code",
    # Distribution
    "distributörskod",
    "distributor code",
    "distributor_code",
    "reseller code",
    "reseller_code",
]

# ══════════════════════════════════════════════════════════════════════════════
# NAMN SYNONYMER
# ══════════════════════════════════════════════════════════════════════════════
# Matchar kolumner som innehåller återförsäljarens namn/företagsnamn.

NAMN_SYNONYMS: Final[List[str]] = [
    # Primära (vanligast)
    "namn",
    "name",
    "dealer name",
    "dealer_name",
    "dealername",
    # SAP/Dispatch-varianter
    "customer name",
    "customer_name",
    "customername",
    "sold to name",
    "sold-to name",
    "sold_to_name",
    # Svenska varianter
    "kundnamn",
    "företagsnamn",
    "foretagsnamn",
    "firma",
    "företag",
    "foretag",
    "handlare",
    "återförsäljare",
    "aterforsaljare",
    # Generella
    "company name",
    "company_name",
    "companyname",
    "business name",
    "business_name",
    "organization name",
    "organization_name",
    "organisation name",
    "organisation_name",
]

# ══════════════════════════════════════════════════════════════════════════════
# T6 / REGION / ORGNUMMER SYNONYMER
# ══════════════════════════════════════════════════════════════════════════════
# Matchar kolumner som innehåller region, T6-kod eller organisationsnummer.
# Används även som fallback för org.nr-kolumner.

T6_SYNONYMS: Final[List[str]] = [
    # Primära (vanligast)
    "t6",
    "region",
    "region code",
    "region_code",
    "regioncode",
    # Org.nr-varianter
    "orgnr",
    "org.nr",
    "org nr",
    "org_nr",
    "orgnummer",
    "organisationsnummer",
    "org number",
    "org_number",
    # SAP/Dispatch-varianter
    "sales org",
    "sales_org",
    "salesorg",
    "sales organization",
    "sales_organization",
    "sales channel",
    "sales_channel",
    "distribution channel",
    "distribution_channel",
    # Svenska varianter
    "säljorganisation",
    "saljorganisation",
    "säljregion",
    "saljregion",
    "distrikt",
    "område",
    "omrade",
    # Generella
    "territory",
    "territory code",
    "territory_code",
    "channel",
    "market",
    "market code",
    "market_code",
]