"""Canonical fields for the three datasets the Invoice Validator joins.

The module works with three data contracts:

* **Invoices** - 16 canonical fields, declared here from scratch. The invoice
  header/line fields (supplier, PO reference, dates, amounts, tax, freight,
  currency, payment terms, goods-receipt reference) have no equivalent in the
  earlier modules, so they get their own registry.
* **Purchase orders** - *reused* from the Purchase Order Risk Checker
  (:data:`app.modules.po_risk.field_definitions.REGISTRY`), extended with a
  single ``po_status`` field so a "closed PO" can be detected. This honours the
  project convention: reuse the purchase-order model, do not redefine it.
* **Goods receipts** - 7 canonical fields, declared here from scratch.

All three registries feed the same shared mapping/parsing services the other
modules use, so a file with SAP technical headers (``BELNR``, ``EBELN``,
``MBLNR`` ...) maps automatically.
"""

from __future__ import annotations

from app.modules.po_risk.field_definitions import REGISTRY as PO_RISK_REGISTRY
from app.services.tabular.field_registry import (
    FieldDefinition,
    FieldRegistry,
    FieldType,
    normalize_header,
)

__all__ = [
    "INVOICE_REGISTRY", "INVOICE_FIELD_DEFINITIONS",
    "GOODS_RECEIPT_REGISTRY", "GOODS_RECEIPT_FIELD_DEFINITIONS",
    "PO_REGISTRY", "PO_STATUS_FIELD",
    "INVOICE_CANONICAL_FIELDS", "GOODS_RECEIPT_CANONICAL_FIELDS", "PO_CANONICAL_FIELDS",
    "FieldDefinition", "FieldType", "normalize_header",
]


# ---------------------------------------------------------------------------
# Invoices (16 fields)
# ---------------------------------------------------------------------------
INVOICE_FIELD_DEFINITIONS: tuple[FieldDefinition, ...] = (
    FieldDefinition(
        name="invoice_number",
        label="Invoice Number",
        field_type=FieldType.STRING,
        required=True,
        description="Supplier invoice / document number (SAP RBKP-BELNR or vendor reference XBLNR).",
        aliases=(
            "BELNR", "INVOICE_NUMBER", "INVOICE_NO", "INVOICE", "INVOICE_ID", "XBLNR",
            "VENDOR_INVOICE", "VENDOR_INVOICE_NUMBER", "REFERENCE_DOCUMENT", "INV_NO", "INV_NUMBER",
        ),
        max_length=40,
    ),
    FieldDefinition(
        name="supplier_id",
        label="Supplier ID",
        field_type=FieldType.STRING,
        required=False,
        description="Supplier / vendor account number on the invoice (SAP LIFNR).",
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
        description="Supplier name on the invoice (SAP LFA1-NAME1).",
        aliases=("NAME1", "VENDOR_NAME", "SUPPLIER_NAME", "VENDOR_DESCRIPTION", "LIEFERANT", "NAME"),
        max_length=120,
    ),
    FieldDefinition(
        name="po_number",
        label="Purchase Order Number",
        field_type=FieldType.STRING,
        required=False,
        description="Referenced purchasing document number (SAP EKKO-EBELN).",
        aliases=(
            "EBELN", "PURCHASE_ORDER", "PURCHASE_ORDER_NUMBER", "PURCHASING_DOCUMENT",
            "PO", "PO_NUMBER", "PO_NO", "PURCHASE_ORDER_REFERENCE", "PO_REFERENCE", "ORDER_NUMBER",
        ),
        max_length=20,
    ),
    FieldDefinition(
        name="po_item",
        label="Purchase Order Item",
        field_type=FieldType.STRING,
        required=False,
        description="Referenced purchasing document item (SAP EKPO-EBELP).",
        aliases=(
            "EBELP", "PO_ITEM", "PURCHASE_ORDER_ITEM", "LINE_ITEM", "ITEM_NUMBER", "PO_LINE",
            "POSITION", "ITEM",
        ),
        max_length=10,
    ),
    FieldDefinition(
        name="invoice_date",
        label="Invoice Date",
        field_type=FieldType.DATE,
        required=False,
        description="Date the supplier issued the invoice (SAP RBKP-BLDAT).",
        aliases=(
            "BLDAT", "INVOICE_DATE", "DOCUMENT_DATE", "DOC_DATE", "BILLING_DATE", "INV_DATE",
            "INVOICE_DOCUMENT_DATE",
        ),
    ),
    FieldDefinition(
        name="posting_date",
        label="Posting Date",
        field_type=FieldType.DATE,
        required=False,
        description="Date the invoice is posted to the ledger (SAP RBKP-BUDAT).",
        aliases=(
            "BUDAT", "POSTING_DATE", "GL_DATE", "POST_DATE", "ACCOUNTING_DATE", "ENTRY_DATE",
        ),
    ),
    FieldDefinition(
        name="quantity",
        label="Invoiced Quantity",
        field_type=FieldType.NUMBER,
        required=False,
        description="Quantity billed on the invoice line (SAP RSEG-MENGE).",
        aliases=(
            "MENGE", "QUANTITY", "INVOICED_QUANTITY", "INVOICE_QUANTITY", "BILLED_QUANTITY",
            "QTY", "INVOICED_QTY", "BILLED_QTY",
        ),
    ),
    FieldDefinition(
        name="unit_price",
        label="Unit Price",
        field_type=FieldType.NUMBER,
        required=False,
        description="Invoiced price per unit (SAP RSEG-effective price).",
        aliases=(
            "NETPR", "UNIT_PRICE", "PRICE", "PRICE_PER_UNIT", "NET_PRICE", "UNIT_COST",
            "INVOICE_UNIT_PRICE", "INVOICED_UNIT_PRICE",
        ),
    ),
    FieldDefinition(
        name="subtotal",
        label="Subtotal (Net)",
        field_type=FieldType.NUMBER,
        required=False,
        description="Net line/invoice amount before tax and freight (SAP RSEG-WRBTR).",
        aliases=(
            "WRBTR", "SUBTOTAL", "NET_AMOUNT", "NET", "NET_VALUE", "ITEM_AMOUNT", "LINE_AMOUNT",
            "NET_TOTAL", "AMOUNT_NET",
        ),
    ),
    FieldDefinition(
        name="tax",
        label="Tax Amount",
        field_type=FieldType.NUMBER,
        required=False,
        description="Tax amount on the invoice (SAP BSET-FWSTE / MWSTS).",
        aliases=(
            "MWSTS", "TAX", "TAX_AMOUNT", "VAT", "VAT_AMOUNT", "SALES_TAX", "TAX_VALUE", "MWST",
        ),
    ),
    FieldDefinition(
        name="freight",
        label="Freight Amount",
        field_type=FieldType.NUMBER,
        required=False,
        description="Freight / delivery charge on the invoice.",
        aliases=(
            "FREIGHT", "FREIGHT_AMOUNT", "SHIPPING", "SHIPPING_COST", "DELIVERY_CHARGE",
            "FRACHT", "CARRIAGE", "FREIGHT_CHARGE",
        ),
    ),
    FieldDefinition(
        name="currency",
        label="Currency",
        field_type=FieldType.CURRENCY_CODE,
        required=False,
        description="Invoice currency (SAP RBKP-WAERS).",
        aliases=("WAERS", "CURRENCY", "CURRENCY_KEY", "DOC_CURRENCY", "CURR", "INVOICE_CURRENCY"),
        max_length=3,
    ),
    FieldDefinition(
        name="total_amount",
        label="Total Amount (Gross)",
        field_type=FieldType.NUMBER,
        required=False,
        description="Gross invoice total including tax and freight (SAP RBKP-RMWWR).",
        aliases=(
            "RMWWR", "TOTAL_AMOUNT", "TOTAL", "GROSS_AMOUNT", "GROSS_TOTAL", "INVOICE_TOTAL",
            "INVOICE_AMOUNT", "AMOUNT", "GROSS", "TOTAL_VALUE",
        ),
    ),
    FieldDefinition(
        name="payment_terms",
        label="Payment Terms",
        field_type=FieldType.STRING,
        required=False,
        description="Terms of payment key on the invoice (SAP RBKP-ZTERM).",
        aliases=(
            "ZTERM", "PAYMENT_TERMS", "TERMS_OF_PAYMENT", "PAYMENT_TERM", "PAY_TERMS", "TERMS",
        ),
        max_length=20,
    ),
    FieldDefinition(
        name="gr_reference",
        label="Goods-Receipt Reference",
        field_type=FieldType.STRING,
        required=False,
        description="Goods-receipt / material document the invoice refers to (SAP RSEG-LFBNR).",
        aliases=(
            "LFBNR", "GR_REFERENCE", "GOODS_RECEIPT_REFERENCE", "GOODS_RECEIPT", "GR_NUMBER",
            "GR_NO", "RECEIPT_REFERENCE", "MATERIAL_DOCUMENT", "DELIVERY_NOTE",
        ),
        max_length=40,
    ),
)

INVOICE_REGISTRY = FieldRegistry(INVOICE_FIELD_DEFINITIONS)
INVOICE_CANONICAL_FIELDS: tuple[str, ...] = INVOICE_REGISTRY.names


# ---------------------------------------------------------------------------
# Goods receipts (7 fields)
# ---------------------------------------------------------------------------
GOODS_RECEIPT_FIELD_DEFINITIONS: tuple[FieldDefinition, ...] = (
    FieldDefinition(
        name="gr_number",
        label="Goods-Receipt Number",
        field_type=FieldType.STRING,
        required=False,
        description="Material document number of the goods receipt (SAP MKPF-MBLNR).",
        aliases=(
            "MBLNR", "GR_NUMBER", "GOODS_RECEIPT_NUMBER", "GOODS_RECEIPT", "MATERIAL_DOCUMENT",
            "GR_NO", "RECEIPT_NUMBER", "GR_DOCUMENT",
        ),
        max_length=40,
    ),
    FieldDefinition(
        name="po_number",
        label="Purchase Order Number",
        field_type=FieldType.STRING,
        required=True,
        description="Purchase order the receipt was posted against (SAP MSEG-EBELN).",
        aliases=(
            "EBELN", "PURCHASE_ORDER", "PURCHASE_ORDER_NUMBER", "PO", "PO_NUMBER", "PO_NO",
            "PURCHASING_DOCUMENT", "ORDER_NUMBER",
        ),
        max_length=20,
    ),
    FieldDefinition(
        name="po_item",
        label="Purchase Order Item",
        field_type=FieldType.STRING,
        required=False,
        description="Purchase order item the receipt was posted against (SAP MSEG-EBELP).",
        aliases=(
            "EBELP", "PO_ITEM", "PURCHASE_ORDER_ITEM", "LINE_ITEM", "ITEM_NUMBER", "PO_LINE",
            "POSITION", "ITEM",
        ),
        max_length=10,
    ),
    FieldDefinition(
        name="receipt_date",
        label="Receipt Date",
        field_type=FieldType.DATE,
        required=False,
        description="Date the goods were received / posted (SAP MKPF-BUDAT).",
        aliases=(
            "BUDAT", "RECEIPT_DATE", "GR_DATE", "GOODS_RECEIPT_DATE", "POSTING_DATE",
            "DELIVERY_DATE", "RECEIVED_DATE", "DOCUMENT_DATE",
        ),
    ),
    FieldDefinition(
        name="received_quantity",
        label="Received Quantity",
        field_type=FieldType.NUMBER,
        required=False,
        description="Quantity received in the goods movement (SAP MSEG-MENGE).",
        aliases=(
            "MENGE", "RECEIVED_QUANTITY", "RECEIVED_QTY", "GR_QUANTITY", "DELIVERED_QUANTITY",
            "DELIVERED_QTY", "QUANTITY", "RECEIPT_QUANTITY",
        ),
    ),
    FieldDefinition(
        name="accepted_quantity",
        label="Accepted Quantity",
        field_type=FieldType.NUMBER,
        required=False,
        description="Quantity accepted after inspection (received minus rejected).",
        aliases=(
            "ACCEPTED_QUANTITY", "ACCEPTED_QTY", "ACCEPTED", "QTY_ACCEPTED", "PASSED_QUANTITY",
            "GOOD_QUANTITY",
        ),
    ),
    FieldDefinition(
        name="rejected_quantity",
        label="Rejected Quantity",
        field_type=FieldType.NUMBER,
        required=False,
        description="Quantity rejected / returned at inspection.",
        aliases=(
            "REJECTED_QUANTITY", "REJECTED_QTY", "REJECTED", "QTY_REJECTED", "RETURNED_QUANTITY",
            "RETURNED_QTY", "SCRAP_QUANTITY",
        ),
    ),
)

GOODS_RECEIPT_REGISTRY = FieldRegistry(GOODS_RECEIPT_FIELD_DEFINITIONS)
GOODS_RECEIPT_CANONICAL_FIELDS: tuple[str, ...] = GOODS_RECEIPT_REGISTRY.names


# ---------------------------------------------------------------------------
# Purchase orders (reuse module 1, add a status field)
# ---------------------------------------------------------------------------
#: The one field the PO Risk Checker does not carry: whether the PO line is
#: closed / delivery-complete, needed to detect invoicing a closed PO.
PO_STATUS_FIELD = FieldDefinition(
    name="po_status",
    label="PO Status",
    field_type=FieldType.STRING,
    required=False,
    description=(
        "Processing status of the purchase order line (open / closed / delivery complete). "
        "SAP EKPO-ELIKZ (delivery complete) or a documented status label."
    ),
    aliases=(
        "PO_STATUS", "ORDER_STATUS", "DOCUMENT_STATUS", "PROCESSING_STATUS", "COMPLETION_STATUS",
        "DELIVERY_COMPLETE", "ELIKZ", "CLOSED", "PO_STATE", "LINE_STATUS",
    ),
    max_length=40,
)

#: Reuse the 25 purchase-order fields from module 1, append the status field,
#: and require only the two join keys (number + item). The PO Risk Checker
#: additionally requires quantity/price/order-date, but for validation those are
#: optional inputs whose absence is reported, not a reason to reject the file.
PO_REGISTRY = PO_RISK_REGISTRY.extend((PO_STATUS_FIELD,)).with_required(("po_number", "po_item"))
PO_CANONICAL_FIELDS: tuple[str, ...] = PO_REGISTRY.names
