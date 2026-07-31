"""Canonical fields for the supplier master used by the Recommendation Engine.

Module 3 scores *supplier master data* rather than transaction lines, so it
defines its own field registry. It reuses the shared registry/mapping/parsing
services (exactly like modules 1 and 2) and reuses the established SAP alias
conventions where they overlap - ``LIFNR`` for the supplier id, ``WAERS`` for
the currency, ``ZTERM`` for payment terms - so a supplier extract with SAP
technical headers maps with no manual correction.

Three fields are multi-valued (the materials, plants and regions a supplier
serves). They are declared as strings here and split into lists by the
normaliser, using the delimiters in the configuration file.
"""

from __future__ import annotations

from app.services.tabular.field_registry import (
    FieldDefinition,
    FieldRegistry,
    FieldType,
    normalize_header,
)

__all__ = [
    "ALIAS_LOOKUP", "CANONICAL_FIELDS", "FIELD_BY_NAME", "FIELD_DEFINITIONS",
    "LIST_FIELDS", "REGISTRY", "REQUIRED_FIELDS", "FieldDefinition", "FieldType",
    "normalize_header",
]


FIELD_DEFINITIONS: tuple[FieldDefinition, ...] = (
    FieldDefinition(
        name="supplier_id",
        label="Supplier ID",
        field_type=FieldType.STRING,
        required=True,
        description="Supplier / vendor account number (SAP LFA1-LIFNR).",
        aliases=(
            "LIFNR", "VENDOR", "VENDOR_ID", "VENDOR_NUMBER", "SUPPLIER", "SUPPLIER_NO",
            "SUPPLIER_NUMBER", "SUPPLIER_CODE", "ACCOUNT_NUMBER_OF_VENDOR",
        ),
        max_length=20,
    ),
    FieldDefinition(
        name="supplier_name",
        label="Supplier Name",
        field_type=FieldType.STRING,
        required=False,
        description="Supplier name (SAP LFA1-NAME1).",
        aliases=("NAME1", "VENDOR_NAME", "SUPPLIER_NAME", "VENDOR_DESCRIPTION", "LIEFERANT", "NAME"),
        max_length=120,
    ),
    FieldDefinition(
        name="materials_supplied",
        label="Materials Supplied",
        field_type=FieldType.STRING,
        required=False,
        description=(
            "Materials or material numbers the supplier can supply, as a delimited list. "
            "Used by the eligibility filter to match a requirement's material."
        ),
        aliases=(
            "MATERIALS_SUPPLIED", "MATERIALS", "MATERIAL", "MATNR", "SUPPLIED_MATERIALS",
            "MATERIAL_LIST", "PRODUCTS", "PRODUCT_RANGE", "OFFERED_MATERIALS", "CATALOG",
        ),
        max_length=2000,
    ),
    FieldDefinition(
        name="plants_served",
        label="Plants Served",
        field_type=FieldType.STRING,
        required=False,
        description=(
            "Plants / sites the supplier delivers to, as a delimited list. Used by the "
            "eligibility filter and the geographic-fit score."
        ),
        aliases=(
            "PLANTS_SERVED", "PLANTS", "PLANT", "WERKS", "SERVED_PLANTS", "SITES",
            "SITES_SERVED", "DELIVERY_PLANTS", "SUPPLIED_PLANTS",
        ),
        max_length=500,
    ),
    FieldDefinition(
        name="regions_served",
        label="Regions Served",
        field_type=FieldType.STRING,
        required=False,
        description=(
            "Regions / territories the supplier serves, as a delimited list. Used by the "
            "geographic-fit score against the requirement's preferred region."
        ),
        aliases=(
            "REGIONS_SERVED", "REGIONS", "REGION", "SERVED_REGIONS", "TERRITORIES",
            "COVERAGE", "GEOGRAPHY", "COUNTRIES_SERVED", "MARKETS",
        ),
        max_length=500,
    ),
    FieldDefinition(
        name="unit_price",
        label="Unit Price",
        field_type=FieldType.NUMBER,
        required=False,
        description="Quoted price per unit for the requirement, in the supplier's currency.",
        aliases=(
            "NETPR", "UNIT_PRICE", "PRICE", "QUOTED_PRICE", "OFFER_PRICE", "NET_PRICE",
            "PRICE_PER_UNIT", "UNIT_COST",
        ),
    ),
    FieldDefinition(
        name="currency",
        label="Currency",
        field_type=FieldType.CURRENCY_CODE,
        required=False,
        description="Currency of the supplier's unit price (SAP WAERS).",
        aliases=("WAERS", "CURRENCY", "CURRENCY_KEY", "PRICE_CURRENCY", "CURR"),
        max_length=3,
    ),
    FieldDefinition(
        name="lead_time_days",
        label="Lead Time (days)",
        field_type=FieldType.INTEGER,
        required=False,
        description="Planned delivery lead time in days (SAP PLIFZ).",
        aliases=(
            "LEAD_TIME_DAYS", "LEAD_TIME", "LEADTIME", "PLIFZ", "DELIVERY_LEAD_TIME",
            "DELIVERY_DAYS", "LEAD_DAYS", "PLANNED_DELIVERY_TIME",
        ),
    ),
    FieldDefinition(
        name="available_capacity",
        label="Available Capacity",
        field_type=FieldType.NUMBER,
        required=False,
        description="Available supply capacity for the requirement, in the requirement's units.",
        aliases=(
            "AVAILABLE_CAPACITY", "CAPACITY", "MONTHLY_CAPACITY", "MAX_CAPACITY",
            "SUPPLY_CAPACITY", "FREE_CAPACITY", "AVAILABLE_QTY", "CAPACITY_UNITS",
        ),
    ),
    FieldDefinition(
        name="on_time_delivery_rate",
        label="On-time Delivery Rate",
        field_type=FieldType.NUMBER,
        required=False,
        description="Historical on-time delivery performance, as a percentage (0-100).",
        aliases=(
            "ON_TIME_DELIVERY_RATE", "ON_TIME_RATE", "OTD", "OTD_RATE", "ON_TIME_PCT",
            "DELIVERY_RELIABILITY", "ONTIME", "ON_TIME_DELIVERY",
        ),
    ),
    FieldDefinition(
        name="quality_score",
        label="Quality Score",
        field_type=FieldType.NUMBER,
        required=False,
        description="Supplier quality rating on a 0-100 scale (higher is better).",
        aliases=(
            "QUALITY_SCORE", "QUALITY", "QUALITY_RATING", "QSCORE", "QUALITY_INDEX",
            "QUALITY_KPI",
        ),
    ),
    FieldDefinition(
        name="defect_rate",
        label="Defect Rate",
        field_type=FieldType.NUMBER,
        required=False,
        description="Historical defect / reject rate, as a percentage (lower is better).",
        aliases=(
            "DEFECT_RATE", "DEFECTS", "REJECT_RATE", "DEFECT_PCT", "REJECTION_RATE",
            "QUALITY_DEFECT_RATE", "SCRAP_RATE",
        ),
    ),
    FieldDefinition(
        name="risk_score",
        label="Risk Score",
        field_type=FieldType.NUMBER,
        required=False,
        description="Supplier risk score on a 0-100 scale (higher means riskier).",
        aliases=(
            "RISK_SCORE", "RISK", "RISK_RATING", "SUPPLIER_RISK", "RISK_INDEX",
            "RISK_LEVEL_SCORE",
        ),
    ),
    FieldDefinition(
        name="esg_score",
        label="ESG Score",
        field_type=FieldType.NUMBER,
        required=False,
        description="Environmental, social and governance / sustainability score (0-100).",
        aliases=(
            "ESG_SCORE", "ESG", "SUSTAINABILITY_SCORE", "ESG_RATING", "SUSTAINABILITY",
            "SUSTAINABILITY_RATING", "ESG_INDEX",
        ),
    ),
    FieldDefinition(
        name="contract_status",
        label="Contract Status",
        field_type=FieldType.STRING,
        required=False,
        description="Whether an outline agreement / contract is in place (active, expiring, none).",
        aliases=(
            "CONTRACT_STATUS", "CONTRACT", "CONTRACTED", "AGREEMENT_STATUS", "CONTRACT_STATE",
            "CONTRACT_FLAG", "OUTLINE_AGREEMENT_STATUS",
        ),
        max_length=40,
    ),
    FieldDefinition(
        name="contract_expiration",
        label="Contract Expiration",
        field_type=FieldType.DATE,
        required=False,
        description="Date the current contract / outline agreement expires (SAP EKKO-KDATE).",
        aliases=(
            "CONTRACT_EXPIRATION", "CONTRACT_END", "CONTRACT_EXPIRY", "EXPIRY_DATE",
            "AGREEMENT_END", "VALID_TO", "CONTRACT_VALID_TO", "KDATE", "END_DATE",
        ),
    ),
    FieldDefinition(
        name="payment_terms",
        label="Payment Terms",
        field_type=FieldType.STRING,
        required=False,
        description="Terms of payment key (SAP ZTERM).",
        aliases=(
            "ZTERM", "PAYMENT_TERMS", "TERMS_OF_PAYMENT", "PAYMENT_TERM", "PAY_TERMS", "TERMS",
        ),
        max_length=20,
    ),
    FieldDefinition(
        name="historical_order_count",
        label="Historical Order Count",
        field_type=FieldType.INTEGER,
        required=False,
        description="Number of purchase orders historically placed with the supplier.",
        aliases=(
            "HISTORICAL_ORDER_COUNT", "ORDER_COUNT", "ORDERS", "NUM_ORDERS", "PO_COUNT",
            "HISTORICAL_ORDERS", "NUMBER_OF_ORDERS", "ORDER_HISTORY",
        ),
    ),
    FieldDefinition(
        name="historical_spend",
        label="Historical Spend",
        field_type=FieldType.NUMBER,
        required=False,
        description="Cumulative historical spend with the supplier, in the supplier's currency.",
        aliases=(
            "HISTORICAL_SPEND", "TOTAL_SPEND", "SPEND", "LIFETIME_SPEND", "CUMULATIVE_SPEND",
            "SPEND_TO_DATE", "HISTORICAL_VALUE",
        ),
    ),
)

#: Fields that hold a delimited list rather than a single value.
LIST_FIELDS: tuple[str, ...] = ("materials_supplied", "plants_served", "regions_served")

#: The module's data contract, consumed by the shared mapping/parsing services.
REGISTRY = FieldRegistry(FIELD_DEFINITIONS)

CANONICAL_FIELDS: tuple[str, ...] = REGISTRY.names
FIELD_BY_NAME: dict[str, FieldDefinition] = REGISTRY.by_name
REQUIRED_FIELDS: tuple[str, ...] = REGISTRY.required

#: Alias -> canonical field, kept as a module level name for convenience.
ALIAS_LOOKUP: dict[str, str] = REGISTRY.alias_lookup
