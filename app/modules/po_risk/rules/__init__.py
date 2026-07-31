"""Registry of every deterministic purchase order risk rule.

Adding a rule means: implement the class, add it to :data:`RULE_CLASSES` and add
its thresholds to ``config/po_risk_rules.json``. The engine picks it up
automatically.
"""

from __future__ import annotations

from app.modules.po_risk.rules.approvals import ExcessiveChangesRule, HighValueWithoutApprovalRule
from app.modules.po_risk.rules.base import BaseRule, RuleContext, RuleFinding
from app.modules.po_risk.rules.contracts import (
    MaverickSpendRule,
    MissingContractReferenceRule,
    OffContractPurchaseRule,
    UnusualPaymentTermsRule,
)
from app.modules.po_risk.rules.data_quality import (
    CurrencyAnomalyRule,
    MissingRequiredFieldsRule,
    QuantityAnomalyRule,
)
from app.modules.po_risk.rules.delivery import (
    DeliveryBeforeOrderRule,
    LateDeliveryRule,
    RequestedBeforeOrderRule,
)
from app.modules.po_risk.rules.duplication import DuplicateLineItemRule, DuplicatePurchaseOrderRule
from app.modules.po_risk.rules.pricing import MaterialPriceVarianceRule, UnitPriceIncreaseRule
from app.modules.po_risk.rules.splitting import ApprovalThresholdProximityRule, SplitPurchaseRule
from app.modules.po_risk.rules.supplier import HighRiskSupplierRule, SupplierConcentrationRule

RULE_CLASSES: tuple[type[BaseRule], ...] = (
    DuplicatePurchaseOrderRule,        # PO-R001
    DuplicateLineItemRule,             # PO-R002
    SplitPurchaseRule,                 # PO-R003
    ApprovalThresholdProximityRule,    # PO-R004
    UnitPriceIncreaseRule,             # PO-R005
    MaterialPriceVarianceRule,         # PO-R006
    OffContractPurchaseRule,           # PO-R007
    MissingContractReferenceRule,      # PO-R008
    HighValueWithoutApprovalRule,      # PO-R009
    LateDeliveryRule,                  # PO-R010
    RequestedBeforeOrderRule,          # PO-R011
    DeliveryBeforeOrderRule,           # PO-R012
    QuantityAnomalyRule,               # PO-R013
    CurrencyAnomalyRule,               # PO-R014
    MissingRequiredFieldsRule,         # PO-R015
    UnusualPaymentTermsRule,           # PO-R016
    ExcessiveChangesRule,              # PO-R017
    SupplierConcentrationRule,         # PO-R018
    MaverickSpendRule,                 # PO-R019
    HighRiskSupplierRule,              # PO-R020
)

RULE_IDS: tuple[str, ...] = tuple(rule_class.rule_id for rule_class in RULE_CLASSES)

__all__ = [
    "BaseRule",
    "RuleContext",
    "RuleFinding",
    "RULE_CLASSES",
    "RULE_IDS",
]
