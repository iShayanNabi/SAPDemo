"""Canonical purchase order fields, their data types and their SAP aliases.

This is the single source of truth for the module's data contract. Column
mapping, normalisation, rules, exports and the sample data generator all read
these definitions, so adding a field is a one-place change.

The alias lists include SAP technical field names (EBELN, LIFNR, MENGE ...)
alongside the labels commonly produced by ME2N / ME80FN exports and by
BW/analytics extracts.
"""

from __future__ import annotations

from app.services.tabular.field_registry import (
    FieldDefinition,
    FieldRegistry,
    FieldType,
    normalize_header,
)

__all__ = [
    "ALIAS_LOOKUP", "CANONICAL_FIELDS", "DATE_FIELDS", "FIELD_BY_NAME", "FIELD_DEFINITIONS",
    "NUMERIC_FIELDS", "REGISTRY", "REQUIRED_FIELDS", "FieldDefinition", "FieldType",
    "normalize_header",
]


FIELD_DEFINITIONS: tuple[FieldDefinition, ...] = (
    FieldDefinition(
        name="po_number",
        label="Purchase Order Number",
        field_type=FieldType.STRING,
        required=True,
        description="Purchasing document number (SAP EKKO-EBELN).",
        aliases=(
            "EBELN", "PURCHASING_DOCUMENT", "PURCHASE_ORDER", "PURCHASE_ORDER_NUMBER",
            "PO", "PO_NUMBER", "PO_NO", "PURCHASING_DOC", "DOCUMENT_NUMBER", "ORDER_NUMBER",
        ),
        max_length=20,
    ),
    FieldDefinition(
        name="po_item",
        label="Purchase Order Item",
        field_type=FieldType.STRING,
        required=True,
        description="Item number of purchasing document (SAP EKPO-EBELP).",
        aliases=(
            "EBELP", "ITEM", "PO_ITEM", "LINE_ITEM", "ITEM_NUMBER", "PO_LINE",
            "POSITION", "LINE_NO",
        ),
        max_length=10,
    ),
    FieldDefinition(
        name="supplier_id",
        label="Supplier ID",
        field_type=FieldType.STRING,
        required=True,
        description="Supplier / vendor account number (SAP EKKO-LIFNR).",
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
        aliases=("NAME1", "VENDOR_NAME", "SUPPLIER_NAME", "VENDOR_DESCRIPTION", "LIEFERANT"),
        max_length=120,
    ),
    FieldDefinition(
        name="material",
        label="Material",
        field_type=FieldType.STRING,
        required=False,
        description="Material number (SAP EKPO-MATNR).",
        aliases=("MATNR", "MATERIAL", "MATERIAL_NUMBER", "ARTICLE", "PART_NUMBER", "ITEM_CODE"),
        max_length=40,
    ),
    FieldDefinition(
        name="material_description",
        label="Material Description",
        field_type=FieldType.STRING,
        required=False,
        description="Short text for the purchase order item (SAP EKPO-TXZ01).",
        aliases=("TXZ01", "MAKTX", "MATERIAL_DESCRIPTION", "SHORT_TEXT", "DESCRIPTION", "ITEM_TEXT"),
        max_length=255,
    ),
    FieldDefinition(
        name="material_group",
        label="Material Group",
        field_type=FieldType.STRING,
        required=False,
        description="Material group / commodity category (SAP EKPO-MATKL).",
        aliases=("MATKL", "MATERIAL_GROUP", "COMMODITY", "COMMODITY_GROUP", "CATEGORY", "SPEND_CATEGORY"),
        max_length=20,
    ),
    FieldDefinition(
        name="company_code",
        label="Company Code",
        field_type=FieldType.STRING,
        required=False,
        description="Company code (SAP EKKO-BUKRS).",
        aliases=("BUKRS", "COMPANY_CODE", "COMPANY", "CO_CODE", "LEGAL_ENTITY"),
        max_length=10,
    ),
    FieldDefinition(
        name="purchasing_org",
        label="Purchasing Organisation",
        field_type=FieldType.STRING,
        required=False,
        description="Purchasing organisation (SAP EKKO-EKORG).",
        aliases=("EKORG", "PURCHASING_ORG", "PURCHASING_ORGANIZATION", "PURCHASING_ORGANISATION", "PURCH_ORG", "PORG"),
        max_length=10,
    ),
    FieldDefinition(
        name="purchasing_group",
        label="Purchasing Group",
        field_type=FieldType.STRING,
        required=False,
        description="Purchasing group (SAP EKKO-EKGRP).",
        aliases=("EKGRP", "PURCHASING_GROUP", "PURCH_GROUP", "BUYER_GROUP", "PGROUP"),
        max_length=10,
    ),
    FieldDefinition(
        name="plant",
        label="Plant",
        field_type=FieldType.STRING,
        required=False,
        description="Receiving plant (SAP EKPO-WERKS).",
        aliases=("WERKS", "PLANT", "PLANT_CODE", "SITE", "LOCATION"),
        max_length=10,
    ),
    FieldDefinition(
        name="quantity",
        label="Quantity",
        field_type=FieldType.NUMBER,
        required=True,
        description="Purchase order quantity (SAP EKPO-MENGE).",
        aliases=("MENGE", "QUANTITY", "ORDER_QUANTITY", "QTY", "PO_QUANTITY", "ORDERED_QTY"),
    ),
    FieldDefinition(
        name="unit_of_measure",
        label="Unit of Measure",
        field_type=FieldType.STRING,
        required=False,
        description="Order unit of measure (SAP EKPO-MEINS).",
        aliases=("MEINS", "UOM", "UNIT", "UNIT_OF_MEASURE", "BASE_UNIT", "ORDER_UNIT"),
        max_length=10,
    ),
    FieldDefinition(
        name="unit_price",
        label="Unit Price",
        field_type=FieldType.NUMBER,
        required=True,
        description="Net price per price unit (SAP EKPO-NETPR).",
        aliases=("NETPR", "UNIT_PRICE", "NET_PRICE", "PRICE", "PRICE_PER_UNIT", "NET_UNIT_PRICE"),
    ),
    FieldDefinition(
        name="currency",
        label="Currency",
        field_type=FieldType.CURRENCY_CODE,
        required=False,
        description="Document currency (SAP EKKO-WAERS).",
        aliases=("WAERS", "CURRENCY", "CURRENCY_KEY", "DOC_CURRENCY", "CURR"),
        max_length=3,
    ),
    FieldDefinition(
        name="total_value",
        label="Total Value",
        field_type=FieldType.NUMBER,
        required=False,
        description="Net order value of the item (SAP EKPO-NETWR). Recomputed when missing.",
        aliases=("NETWR", "TOTAL_VALUE", "NET_VALUE", "NET_ORDER_VALUE", "LINE_VALUE", "AMOUNT", "TOTAL_AMOUNT"),
    ),
    FieldDefinition(
        name="order_date",
        label="Order Date",
        field_type=FieldType.DATE,
        required=True,
        description="Purchasing document date (SAP EKKO-BEDAT).",
        aliases=("BEDAT", "ORDER_DATE", "PO_DATE", "DOCUMENT_DATE", "PURCHASE_DATE", "CREATED_ON"),
    ),
    FieldDefinition(
        name="requested_delivery_date",
        label="Requested Delivery Date",
        field_type=FieldType.DATE,
        required=False,
        description="Item delivery date requested from the supplier (SAP EKET-EINDT).",
        aliases=("EINDT", "REQUESTED_DELIVERY_DATE", "DELIVERY_DATE", "REQ_DELIVERY_DATE", "PLANNED_DELIVERY_DATE", "SCHEDULED_DELIVERY"),
    ),
    FieldDefinition(
        name="actual_delivery_date",
        label="Actual Delivery Date",
        field_type=FieldType.DATE,
        required=False,
        description="Goods receipt / actual delivery date (SAP MSEG-BUDAT).",
        aliases=("BUDAT", "ACTUAL_DELIVERY_DATE", "GOODS_RECEIPT_DATE", "GR_DATE", "ACTUAL_DELIVERY", "RECEIPT_DATE"),
    ),
    FieldDefinition(
        name="contract_number",
        label="Contract Number",
        field_type=FieldType.STRING,
        required=False,
        description="Outline agreement / contract reference (SAP EKPO-KONNR).",
        aliases=("KONNR", "CONTRACT", "CONTRACT_NUMBER", "OUTLINE_AGREEMENT", "AGREEMENT", "CONTRACT_NO", "OUTLINE_AGREEMENT_NUMBER"),
        max_length=20,
    ),
    FieldDefinition(
        name="payment_terms",
        label="Payment Terms",
        field_type=FieldType.STRING,
        required=False,
        description="Terms of payment key (SAP EKKO-ZTERM).",
        aliases=("ZTERM", "PAYMENT_TERMS", "TERMS_OF_PAYMENT", "PAYMENT_TERM", "PAY_TERMS", "TERMS"),
        max_length=20,
    ),
    FieldDefinition(
        name="approval_status",
        label="Approval Status",
        field_type=FieldType.STRING,
        required=False,
        description="Release / approval status of the document (SAP EKKO-FRGKE derived).",
        aliases=("FRGKE", "FRGZU", "APPROVAL_STATUS", "RELEASE_STATUS", "RELEASE_INDICATOR", "APPROVAL", "STATUS"),
        max_length=30,
    ),
    FieldDefinition(
        name="created_by",
        label="Created By",
        field_type=FieldType.STRING,
        required=False,
        description="User who created the document (SAP EKKO-ERNAM).",
        aliases=("ERNAM", "CREATED_BY", "CREATOR", "REQUESTER", "USER_CREATED", "CREATED_BY_USER"),
        max_length=30,
    ),
    FieldDefinition(
        name="changed_by",
        label="Changed By",
        field_type=FieldType.STRING,
        required=False,
        description="User who last changed the document (SAP CDHDR-USERNAME).",
        aliases=("AENAM", "CHANGED_BY", "MODIFIED_BY", "LAST_CHANGED_BY", "USERNAME"),
        max_length=30,
    ),
    FieldDefinition(
        name="change_count",
        label="Change Count",
        field_type=FieldType.INTEGER,
        required=False,
        description="Number of manual changes recorded for the document (SAP change documents).",
        aliases=("CHANGE_COUNT", "CHANGES", "NUMBER_OF_CHANGES", "CHANGE_DOCUMENTS", "NO_OF_CHANGES", "AMENDMENTS"),
    ),
)

# ---------------------------------------------------------------------------
# Registry and convenience lookups
# ---------------------------------------------------------------------------

#: The module's data contract, consumed by the shared mapping/parsing services.
REGISTRY = FieldRegistry(FIELD_DEFINITIONS)

CANONICAL_FIELDS: tuple[str, ...] = REGISTRY.names
FIELD_BY_NAME: dict[str, FieldDefinition] = REGISTRY.by_name
REQUIRED_FIELDS: tuple[str, ...] = REGISTRY.required
DATE_FIELDS: tuple[str, ...] = REGISTRY.date_fields
NUMERIC_FIELDS: tuple[str, ...] = REGISTRY.numeric_fields

#: Alias -> canonical field, kept as a module level name for backwards compatibility.
ALIAS_LOOKUP: dict[str, str] = REGISTRY.alias_lookup
