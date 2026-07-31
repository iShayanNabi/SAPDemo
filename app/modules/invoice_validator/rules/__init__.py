"""Registry of every deterministic invoice validation rule.

Adding a rule means: implement the class, add it to :data:`RULE_CLASSES` and add
its thresholds to ``config/invoice_validator_rules.json``. The engine picks it up
automatically.
"""

from __future__ import annotations

from app.modules.invoice_validator.rules.amounts import (
    FreightMismatchRule,
    OverbillingRule,
    PriceMismatchRule,
    QuantityMismatchRule,
    TaxMismatchRule,
)
from app.modules.invoice_validator.rules.base import (
    BaseInvoiceRule,
    ExceptionFinding,
)
from app.modules.invoice_validator.rules.consistency import (
    CurrencyMismatchRule,
    PaymentTermMismatchRule,
    SupplierMismatchRule,
)
from app.modules.invoice_validator.rules.dates import (
    FutureInvoiceDateRule,
    InvoiceBeforePurchaseOrderRule,
    InvoiceBeforeReceiptRule,
)
from app.modules.invoice_validator.rules.duplicates import (
    DuplicateInvoiceNumberRule,
    DuplicateInvoiceRule,
)
from app.modules.invoice_validator.rules.matching_rules import (
    ClosedPurchaseOrderInvoicingRule,
    MissingGoodsReceiptRule,
    MissingPurchaseOrderRule,
    ThreeWayMatchRule,
)

RULE_CLASSES: tuple[type[BaseInvoiceRule], ...] = (
    DuplicateInvoiceRule,               # IV-R001
    DuplicateInvoiceNumberRule,         # IV-R002
    MissingPurchaseOrderRule,           # IV-R003
    MissingGoodsReceiptRule,            # IV-R004
    PriceMismatchRule,                  # IV-R005
    QuantityMismatchRule,               # IV-R006
    TaxMismatchRule,                    # IV-R007
    CurrencyMismatchRule,               # IV-R008
    SupplierMismatchRule,               # IV-R009
    FreightMismatchRule,                # IV-R010
    PaymentTermMismatchRule,            # IV-R011
    ThreeWayMatchRule,                  # IV-R012
    OverbillingRule,                    # IV-R013
    InvoiceBeforePurchaseOrderRule,     # IV-R014
    InvoiceBeforeReceiptRule,           # IV-R015
    FutureInvoiceDateRule,              # IV-R016
    ClosedPurchaseOrderInvoicingRule,   # IV-R017
)

RULE_IDS: tuple[str, ...] = tuple(rule_class.rule_id for rule_class in RULE_CLASSES)

#: Rules that need the purchase order dataset to produce any exception.
PO_DEPENDENT_RULES: frozenset[str] = frozenset(
    {"IV-R003", "IV-R005", "IV-R008", "IV-R009", "IV-R011", "IV-R013", "IV-R014", "IV-R017"}
)
#: Rules that need the goods receipt dataset to produce any exception.
GR_DEPENDENT_RULES: frozenset[str] = frozenset({"IV-R004", "IV-R012", "IV-R015"})

__all__ = [
    "BaseInvoiceRule",
    "ExceptionFinding",
    "RULE_CLASSES",
    "RULE_IDS",
    "PO_DEPENDENT_RULES",
    "GR_DEPENDENT_RULES",
]
