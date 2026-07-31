"""Canonical fields for the Spend Analytics Dashboard.

The contract deliberately *reuses* the purchase order fields from module 1 -
supplier, material, plant, company code, quantity, price, currency, contract
number and so on - and adds the eight fields spend analysis needs on top.

Two consequences worth knowing:

* A purchase order extract that already works with the PO Risk Checker can be
  uploaded here unchanged. The added fields are all optional and the module
  degrades gracefully when they are absent.
* One alias conflict has to be resolved. In the PO module ``CATEGORY`` is an
  alias for *material group*, because an ME2N export often labels the material
  group that way. In a spend cube ``CATEGORY`` means the procurement category,
  which is a separate field here. :func:`_po_fields_for_spend` therefore strips
  the ambiguous aliases from ``material_group`` so ``CATEGORY`` resolves to the
  field a spend analyst expects.
"""

from __future__ import annotations

from app.modules.po_risk.field_definitions import FIELD_DEFINITIONS as PO_FIELD_DEFINITIONS
from app.services.tabular.field_registry import FieldDefinition, FieldRegistry, FieldType

#: Aliases that mean "material group" in a PO export but "procurement category"
#: in a spend export. Removed from material_group so the spend fields claim them.
_AMBIGUOUS_MATERIAL_GROUP_ALIASES = frozenset({"CATEGORY", "SPEND_CATEGORY"})


def _po_fields_for_spend() -> tuple[FieldDefinition, ...]:
    """Return the purchase order fields with spend-specific alias fixes applied."""
    adjusted: list[FieldDefinition] = []
    for definition in PO_FIELD_DEFINITIONS:
        if definition.name == "material_group":
            definition = FieldDefinition(
                name=definition.name,
                label=definition.label,
                field_type=definition.field_type,
                required=definition.required,
                description=definition.description,
                aliases=tuple(
                    a for a in definition.aliases if a not in _AMBIGUOUS_MATERIAL_GROUP_ALIASES
                ),
                max_length=definition.max_length,
            )
        adjusted.append(definition)
    return tuple(adjusted)


#: The eight fields the Spend Analytics Dashboard adds to the PO contract.
SPEND_SPECIFIC_FIELDS: tuple[FieldDefinition, ...] = (
    FieldDefinition(
        name="transaction_date",
        label="Transaction Date",
        field_type=FieldType.DATE,
        required=False,
        description=(
            "Date the spend is recognised (posting, invoice or accounting date). "
            "Falls back to the order date when it is not supplied."
        ),
        aliases=(
            "TRANSACTION_DATE", "POSTING_DATE", "SPEND_DATE", "INVOICE_DATE", "BLDAT",
            "ACCOUNTING_DATE", "BOOKING_DATE", "TRANSACTION_DT", "SPEND_MONTH_DATE",
        ),
    ),
    FieldDefinition(
        name="category",
        label="Category",
        field_type=FieldType.STRING,
        required=False,
        description="Procurement category (level 1 of the spend taxonomy).",
        aliases=(
            "CATEGORY", "SPEND_CATEGORY", "PROCUREMENT_CATEGORY", "CATEGORY_L1",
            "MAIN_CATEGORY", "CATEGORY_LEVEL_1", "COMMODITY_CATEGORY", "TOP_CATEGORY",
        ),
        max_length=80,
    ),
    FieldDefinition(
        name="subcategory",
        label="Subcategory",
        field_type=FieldType.STRING,
        required=False,
        description="Procurement subcategory (level 2 of the spend taxonomy).",
        aliases=(
            "SUBCATEGORY", "SUB_CATEGORY", "CATEGORY_L2", "CATEGORY_LEVEL_2",
            "SUB_COMMODITY", "SUBGROUP", "SECONDARY_CATEGORY",
        ),
        max_length=80,
    ),
    FieldDefinition(
        name="contract_status",
        label="Contract Status",
        field_type=FieldType.STRING,
        required=False,
        description=(
            "Whether the transaction is covered by a contract. Interpreted through the "
            "configured status value lists; when absent it is derived from the contract number."
        ),
        aliases=(
            "CONTRACT_STATUS", "CONTRACTED", "UNDER_CONTRACT", "CONTRACT_FLAG",
            "CONTRACT_COVERAGE", "CONTRACT_INDICATOR", "IS_CONTRACTED", "CONTRACTED_FLAG",
        ),
        max_length=40,
    ),
    FieldDefinition(
        name="preferred_supplier_status",
        label="Preferred Supplier Status",
        field_type=FieldType.STRING,
        required=False,
        description=(
            "Whether the supplier is a preferred/strategic supplier. Interpreted through the "
            "configured status value lists."
        ),
        aliases=(
            "PREFERRED_SUPPLIER_STATUS", "PREFERRED_SUPPLIER", "PREFERRED", "PREFERRED_VENDOR",
            "SUPPLIER_STATUS", "VENDOR_STATUS", "SUPPLIER_CLASSIFICATION", "STRATEGIC_SUPPLIER",
        ),
        max_length=40,
    ),
    FieldDefinition(
        name="baseline_price",
        label="Baseline Price",
        field_type=FieldType.NUMBER,
        required=False,
        description=(
            "Reference price per unit (contract, target or standard price) used as the "
            "comparison point for purchase price variance."
        ),
        aliases=(
            "BASELINE_PRICE", "BASE_PRICE", "REFERENCE_PRICE", "TARGET_PRICE", "CONTRACT_PRICE",
            "STANDARD_PRICE", "PLANNED_PRICE", "AGREED_PRICE", "BENCHMARK_PRICE",
        ),
    ),
    FieldDefinition(
        name="current_price",
        label="Current Price",
        field_type=FieldType.NUMBER,
        required=False,
        description=(
            "Price per unit actually paid. Falls back to the purchase order unit price "
            "when it is not supplied."
        ),
        aliases=(
            "CURRENT_PRICE", "ACTUAL_PRICE", "PAID_PRICE", "EFFECTIVE_PRICE",
            "INVOICE_PRICE", "ACTUAL_UNIT_PRICE", "PRICE_PAID",
        ),
    ),
    FieldDefinition(
        name="payment_status",
        label="Payment Status",
        field_type=FieldType.STRING,
        required=False,
        description="Settlement state of the transaction (paid, open, overdue, blocked).",
        aliases=(
            "PAYMENT_STATUS", "INVOICE_STATUS", "PAID_STATUS", "PAYMENT_STATE",
            "SETTLEMENT_STATUS", "PAYMENT_INDICATOR", "INVOICE_PAYMENT_STATUS",
        ),
        max_length=40,
    ),
)


#: Always required, whatever the shape of the source file.
BASE_REQUIRED_FIELDS: tuple[str, ...] = ("po_number", "supplier_id")

#: At least one of these must be mapped (checked by ``validate_spend_mapping``).
DATE_FIELD_GROUP: tuple[str, ...] = ("transaction_date", "order_date")

#: Either a ready-made value, or the ingredients to compute one.
VALUE_FIELD_GROUP: tuple[str, ...] = ("total_value",)
VALUE_INGREDIENT_FIELDS: tuple[str, ...] = ("quantity", "unit_price")

REGISTRY: FieldRegistry = FieldRegistry(
    _po_fields_for_spend() + SPEND_SPECIFIC_FIELDS
).with_required(BASE_REQUIRED_FIELDS)

CANONICAL_FIELDS: tuple[str, ...] = REGISTRY.names
FIELD_BY_NAME = REGISTRY.by_name

#: Fields a user can filter on, in the order the UI should display them.
FILTERABLE_FIELDS: tuple[str, ...] = (
    "supplier_id",
    "material",
    "material_group",
    "category",
    "subcategory",
    "plant",
    "company_code",
    "purchasing_org",
    "purchasing_group",
    "currency",
    "contract_status",
    "preferred_supplier_status",
)

#: Derived boolean/label columns the normaliser adds on top of the canonical fields.
DERIVED_COLUMNS: tuple[str, ...] = (
    "spend_base",
    "unit_price_base",
    "baseline_price_base",
    "current_price_base",
    "effective_date",
    "spend_month",
    "is_contracted",
    "is_preferred_supplier",
    "is_maverick",
    "is_under_management",
    "price_variance_base",
    "price_variance_pct",
)
