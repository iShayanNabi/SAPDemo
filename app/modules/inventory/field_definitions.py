"""Canonical fields for the Inventory Predictor.

Modules 1-5 all describe *documents* - a purchase order line, a spend
transaction, a supplier, an invoice. Module 7 describes something different: a
**time series**. One row is one material, in one plant, in one period, and the
row only means anything next to the rows either side of it.

That is why this module declares its own registry instead of extending module
1's purchase order contract: a purchase order line has no starting inventory, no
period and no reorder point, and an inventory bucket has no net value, no
approver and no contract number. Sharing the definitions would have meant a
registry where three quarters of the fields never apply.

What *is* shared is the vocabulary. ``MATNR``/``MATERIAL`` means the same thing
here as it does in module 1, ``WERKS``/``PLANT`` the same as in module 2, and
``LIFNR``/``VENDOR`` the same as in modules 3 and 5, so an extract that maps
cleanly for one module maps cleanly here.

**Alias care.** :class:`FieldRegistry` resolves aliases with ``setdefault``, so
the field declared *first* wins a contested alias. Two contests matter here:

* ``LOCATION`` belongs to ``storage_location``, not ``plant``. Module 1 gives
  ``plant`` the alias ``LOCATION`` because a purchase order has no storage
  location to confuse it with; an inventory extract always does, and a column
  called "Location" next to a column called "Plant" is the storage location
  every time.
* ``DATE`` belongs to ``period_date``, the bucket the movements are counted in,
  not to ``po_expected_date``. ``period_date`` is therefore declared first.
"""

from __future__ import annotations

from app.services.tabular.field_registry import (
    FieldDefinition,
    FieldRegistry,
    FieldType,
    normalize_header,
)

__all__ = [
    "ALIAS_LOOKUP",
    "CANONICAL_FIELDS",
    "FIELD_BY_NAME",
    "FIELD_DEFINITIONS",
    "REGISTRY",
    "REQUIRED_FIELDS",
    "SERIES_KEY_FIELDS",
    "FieldDefinition",
    "FieldType",
    "normalize_header",
]


FIELD_DEFINITIONS: tuple[FieldDefinition, ...] = (
    FieldDefinition(
        name="material",
        label="Material",
        field_type=FieldType.STRING,
        required=True,
        description=(
            "Material number the row describes (SAP MARD-MATNR). Together with the plant "
            "and storage location it identifies one forecastable time series."
        ),
        aliases=(
            "MATNR", "MATERIAL", "MATERIAL_NUMBER", "MATERIAL_NO", "MATERIAL_CODE",
            "ARTICLE", "PART_NUMBER", "PART_NO", "ITEM_CODE", "SKU", "STOCK_CODE",
        ),
        max_length=40,
    ),
    FieldDefinition(
        name="material_description",
        label="Material Description",
        field_type=FieldType.STRING,
        required=False,
        description="Short text of the material (SAP MAKT-MAKTX). Display only.",
        aliases=(
            "MAKTX", "MATERIAL_DESCRIPTION", "MATERIAL_TEXT", "MATERIAL_NAME",
            "DESCRIPTION", "ITEM_DESCRIPTION", "SHORT_TEXT", "PRODUCT_NAME",
        ),
        max_length=120,
    ),
    FieldDefinition(
        name="plant",
        label="Plant",
        field_type=FieldType.STRING,
        required=True,
        description=(
            "Plant the stock is held in (SAP MARD-WERKS). Part of the series key: the same "
            "material in two plants is forecast separately."
        ),
        aliases=(
            "WERKS", "PLANT", "PLANT_CODE", "PLANT_ID", "SITE", "SITE_CODE", "FACILITY",
        ),
        max_length=10,
    ),
    FieldDefinition(
        name="storage_location",
        label="Storage Location",
        field_type=FieldType.STRING,
        required=False,
        description=(
            "Storage location within the plant (SAP MARD-LGORT). Part of the series key "
            "when the file supplies it."
        ),
        aliases=(
            "LGORT", "STORAGE_LOCATION", "STORAGE_LOC", "STOR_LOC", "SLOC", "LOCATION",
            "WAREHOUSE", "STOCK_LOCATION", "DEPOT",
        ),
        max_length=20,
    ),
    FieldDefinition(
        name="period_date",
        label="Date",
        field_type=FieldType.DATE,
        required=True,
        description=(
            "Date of the period the movements are counted in. The gap between consecutive "
            "dates is what tells the engine whether the history is daily, weekly or monthly."
        ),
        aliases=(
            "DATE", "PERIOD", "PERIOD_DATE", "PERIOD_START", "CALENDAR_DATE", "BUDAT",
            "POSTING_DATE", "MONTH", "SNAPSHOT_DATE", "BUCKET", "SPMON",
        ),
    ),
    FieldDefinition(
        name="starting_inventory",
        label="Starting Inventory",
        field_type=FieldType.NUMBER,
        required=False,
        description=(
            "Stock on hand at the start of the period. Used to check the period balance "
            "(start + receipts - issues = end)."
        ),
        aliases=(
            "STARTING_INVENTORY", "START_INVENTORY", "OPENING_STOCK", "OPENING_INVENTORY",
            "BEGINNING_INVENTORY", "BEGIN_INVENTORY", "START_STOCK", "STOCK_START",
            "OPENING_BALANCE",
        ),
    ),
    FieldDefinition(
        name="ending_inventory",
        label="Ending Inventory",
        field_type=FieldType.NUMBER,
        required=False,
        description=(
            "Stock on hand at the end of the period. The most recent value is the opening "
            "position of the projection, so without it no future stock level can be reported."
        ),
        aliases=(
            "ENDING_INVENTORY", "END_INVENTORY", "CLOSING_STOCK", "CLOSING_INVENTORY",
            "CLOSING_BALANCE", "STOCK_END", "STOCK_ON_HAND", "ON_HAND", "LABST",
            "UNRESTRICTED_STOCK", "INVENTORY", "STOCK_LEVEL",
        ),
    ),
    FieldDefinition(
        name="demand",
        label="Demand",
        field_type=FieldType.NUMBER,
        required=True,
        description=(
            "Quantity demanded in the period. This is the series that is forecast - "
            "everything else describes the stock position around it."
        ),
        aliases=(
            "DEMAND", "DEMAND_QTY", "DEMAND_QUANTITY", "CONSUMPTION", "USAGE", "SALES",
            "SALES_QTY", "REQUIREMENT", "REQUIREMENTS", "OFFTAKE",
        ),
    ),
    FieldDefinition(
        name="receipts",
        label="Receipts",
        field_type=FieldType.NUMBER,
        required=False,
        description="Quantity received into stock in the period (goods receipts).",
        aliases=(
            "RECEIPTS", "RECEIPT_QTY", "RECEIPT_QUANTITY", "GOODS_RECEIPTS", "GR_QTY",
            "RECEIVED_QTY", "RECEIVED_QUANTITY", "INBOUND", "INBOUND_QTY", "REPLENISHMENT",
        ),
    ),
    FieldDefinition(
        name="issues",
        label="Issues",
        field_type=FieldType.NUMBER,
        required=False,
        description=(
            "Quantity issued out of stock in the period (goods issues). Usually equals "
            "demand; a persistent gap between the two is reported as a data-quality warning "
            "because it normally means demand went unfilled."
        ),
        aliases=(
            "ISSUES", "ISSUE_QTY", "ISSUE_QUANTITY", "GOODS_ISSUES", "GI_QTY",
            "ISSUED_QTY", "ISSUED_QUANTITY", "OUTBOUND", "OUTBOUND_QTY", "WITHDRAWALS",
        ),
    ),
    FieldDefinition(
        name="lead_time_days",
        label="Lead Time (days)",
        field_type=FieldType.INTEGER,
        required=False,
        description=(
            "Replenishment lead time in days (SAP MARC-PLIFZ). Drives the reorder point, "
            "the safety stock and how far ahead the reorder date has to sit."
        ),
        aliases=(
            "PLIFZ", "LEAD_TIME", "LEAD_TIME_DAYS", "LEADTIME", "PLANNED_DELIVERY_TIME",
            "DELIVERY_TIME", "REPLENISHMENT_LEAD_TIME", "PDT", "LT_DAYS",
        ),
    ),
    FieldDefinition(
        name="reorder_point",
        label="Reorder Point",
        field_type=FieldType.NUMBER,
        required=False,
        description=(
            "Reorder point currently held in the material master (SAP MARC-MINBE). The "
            "engine also calculates its own and reports both, so the two can be compared."
        ),
        aliases=(
            "MINBE", "REORDER_POINT", "REORDER_LEVEL", "REORDER_QTY_POINT", "ROP",
            "MIN_STOCK", "MINIMUM_STOCK", "ORDER_POINT",
        ),
    ),
    FieldDefinition(
        name="safety_stock",
        label="Safety Stock",
        field_type=FieldType.NUMBER,
        required=False,
        description=(
            "Safety stock currently held in the material master (SAP MARC-EISBE). Compared "
            "against the safety stock the engine recommends for the configured service level."
        ),
        aliases=(
            "EISBE", "SAFETY_STOCK", "SAFETY_STOCK_QTY", "BUFFER_STOCK", "SAFETY_LEVEL",
            "SS_QTY", "MIN_SAFETY_STOCK",
        ),
    ),
    FieldDefinition(
        name="supplier_id",
        label="Supplier",
        field_type=FieldType.STRING,
        required=False,
        description="Supplier the material is replenished from (SAP LFA1-LIFNR).",
        aliases=(
            "LIFNR", "VENDOR", "VENDOR_ID", "VENDOR_NUMBER", "VENDOR_NO", "SUPPLIER",
            "SUPPLIER_ID", "SUPPLIER_NO", "SUPPLIER_NUMBER", "SUPPLIER_CODE",
        ),
        max_length=20,
    ),
    FieldDefinition(
        name="supplier_name",
        label="Supplier Name",
        field_type=FieldType.STRING,
        required=False,
        description="Name of the replenishing supplier (SAP LFA1-NAME1). Display only.",
        aliases=(
            "NAME1", "SUPPLIER_NAME", "VENDOR_NAME", "SUPPLIER_DESCRIPTION",
        ),
        max_length=120,
    ),
    FieldDefinition(
        name="open_po_quantity",
        label="Open PO Quantity",
        field_type=FieldType.NUMBER,
        required=False,
        description=(
            "Quantity already on order and not yet received. It is added to the projected "
            "stock on the purchase-order expected date, so an inbound delivery can be the "
            "reason a shortage does not happen."
        ),
        aliases=(
            "OPEN_PO_QUANTITY", "OPEN_PO_QTY", "OPEN_PO", "OPEN_PURCHASE_ORDER_QTY",
            "OPEN_PURCHASE_ORDER_QUANTITY", "OPEN_ORDER_QTY", "OPEN_ORDER_QUANTITY",
            "ON_ORDER", "ON_ORDER_QTY", "OPEN_QUANTITY", "OUTSTANDING_QTY",
        ),
    ),
    FieldDefinition(
        name="po_expected_date",
        label="PO Expected Date",
        field_type=FieldType.DATE,
        required=False,
        description=(
            "Date the open purchase-order quantity is expected to arrive (SAP EKET-EINDT). "
            "An expected date in the past is reported rather than silently treated as today."
        ),
        aliases=(
            "EINDT", "PO_EXPECTED_DATE", "EXPECTED_DATE", "EXPECTED_DELIVERY_DATE",
            "EXPECTED_RECEIPT_DATE", "PLANNED_RECEIPT_DATE", "DELIVERY_DATE",
            "PO_DELIVERY_DATE", "ETA", "ARRIVAL_DATE",
        ),
    ),
)

#: The module's data contract.
REGISTRY = FieldRegistry(FIELD_DEFINITIONS)

#: Fields that together identify one forecastable series.
SERIES_KEY_FIELDS: tuple[str, ...] = ("material", "plant", "storage_location")

CANONICAL_FIELDS: tuple[str, ...] = REGISTRY.names
FIELD_BY_NAME: dict[str, FieldDefinition] = REGISTRY.by_name
REQUIRED_FIELDS: tuple[str, ...] = REGISTRY.required
ALIAS_LOOKUP: dict[str, str] = REGISTRY.alias_lookup
