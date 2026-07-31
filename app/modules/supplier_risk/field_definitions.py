"""Canonical fields for the Supplier Risk Copilot.

Module 5 assesses *the suppliers module 3 already describes*, so it does not
redefine the supplier master contract: it inherits module 3's registry with
``FieldRegistry.extend()`` and appends the risk-specific facts that a risk
profile needs (delivery counts, invoice exceptions, financial indicators,
compliance findings, concentration and operational metrics).

That means a supplier extract that maps cleanly for the Recommendation Engine
also maps cleanly here, and the shared fields - ``OTD``, ``QUALITY_SCORE``,
``DEFECT_RATE``, ``ESG_SCORE``, ``CONTRACT_STATUS``, ``CONTRACT_EXPIRATION``,
``ORDER_COUNT``, ``HISTORICAL_SPEND`` - keep exactly one meaning across the lab.

**Alias care.** ``FieldRegistry`` resolves aliases with ``setdefault``, so the
inherited declarations win. The appended fields below therefore avoid every
alias module 3 already claims: ``regions_served`` owns ``REGION``/``GEOGRAPHY``
(so ``country`` uses ``LAND1``), ``historical_spend`` owns ``TOTAL_SPEND``,
``historical_order_count`` owns ``PO_COUNT``/``ORDER_COUNT``, ``defect_rate``
owns ``DEFECTS``, ``available_capacity`` owns ``CAPACITY`` and
``contract_status`` owns ``CONTRACT``.

A second, much smaller registry describes the optional *risk events* file - the
individual dated internal records (a late delivery, an invoice exception, a
compliance finding) that the copilot cites and the trend calculation reads.
"""

from __future__ import annotations

from app.modules.supplier_reco.field_definitions import (
    REGISTRY as SUPPLIER_MASTER_REGISTRY,
)
from app.services.tabular.field_registry import (
    FieldDefinition,
    FieldRegistry,
    FieldType,
    normalize_header,
)

__all__ = [
    "ALIAS_LOOKUP",
    "CANONICAL_FIELDS",
    "EVENT_ALIAS_LOOKUP",
    "EVENT_CANONICAL_FIELDS",
    "EVENT_FIELD_DEFINITIONS",
    "EVENT_REGISTRY",
    "EVENT_REQUIRED_FIELDS",
    "FIELD_BY_NAME",
    "INHERITED_FIELDS",
    "LIST_FIELDS",
    "PROFILE_FIELD_DEFINITIONS",
    "REGISTRY",
    "REQUIRED_FIELDS",
    "FieldDefinition",
    "FieldType",
    "normalize_header",
]


#: The risk-specific facts appended to module 3's supplier master contract.
PROFILE_FIELD_DEFINITIONS: tuple[FieldDefinition, ...] = (
    FieldDefinition(
        name="country",
        label="Country",
        field_type=FieldType.STRING,
        required=False,
        description=(
            "Country the supplier operates from (SAP LFA1-LAND1). Drives the geographic "
            "risk score through the configured country risk index."
        ),
        aliases=(
            "LAND1", "COUNTRY", "COUNTRY_CODE", "COUNTRY_KEY", "SUPPLIER_COUNTRY",
            "VENDOR_COUNTRY", "LOCATION_COUNTRY", "ISO_COUNTRY",
        ),
        max_length=40,
    ),
    FieldDefinition(
        name="spend_category",
        label="Spend Category",
        field_type=FieldType.STRING,
        required=False,
        description=(
            "Procurement category the supplier is bought from. Used to group suppliers "
            "when looking for lower-risk alternatives."
        ),
        aliases=(
            "SPEND_CATEGORY", "CATEGORY", "MATKL", "MATERIAL_GROUP", "COMMODITY",
            "COMMODITY_GROUP", "PURCHASING_CATEGORY", "CATEGORY_NAME",
        ),
        max_length=80,
    ),
    FieldDefinition(
        name="open_purchase_order_count",
        label="Open Purchase Orders",
        field_type=FieldType.INTEGER,
        required=False,
        description="Purchase orders currently open with the supplier.",
        aliases=(
            "OPEN_PO_COUNT", "OPEN_PURCHASE_ORDERS", "OPEN_ORDERS", "OPEN_POS",
            "ACTIVE_PO_COUNT", "OUTSTANDING_ORDERS",
        ),
    ),
    FieldDefinition(
        name="active_contract_count",
        label="Active Contracts",
        field_type=FieldType.INTEGER,
        required=False,
        description="Number of outline agreements currently active with the supplier.",
        aliases=(
            "ACTIVE_CONTRACTS", "ACTIVE_CONTRACT_COUNT", "CONTRACT_COUNT", "NUM_CONTRACTS",
            "AGREEMENTS", "OUTLINE_AGREEMENTS",
        ),
    ),
    FieldDefinition(
        name="contract_number",
        label="Contract Number",
        field_type=FieldType.STRING,
        required=False,
        description="Reference of the leading outline agreement (SAP EKKO-KONNR).",
        aliases=(
            "KONNR", "CONTRACT_NUMBER", "CONTRACT_NO", "AGREEMENT_NUMBER",
            "OUTLINE_AGREEMENT", "CONTRACT_ID", "AGREEMENT_ID",
        ),
        max_length=20,
    ),
    FieldDefinition(
        name="delivery_count",
        label="Deliveries",
        field_type=FieldType.INTEGER,
        required=False,
        description="Total deliveries received from the supplier in the assessed period.",
        aliases=(
            "DELIVERY_COUNT", "DELIVERIES", "NUM_DELIVERIES", "GR_COUNT",
            "GOODS_RECEIPTS", "RECEIPT_COUNT", "SHIPMENTS",
        ),
    ),
    FieldDefinition(
        name="late_delivery_count",
        label="Late Deliveries",
        field_type=FieldType.INTEGER,
        required=False,
        description="Deliveries that arrived after the confirmed date.",
        aliases=(
            "LATE_DELIVERY_COUNT", "LATE_DELIVERIES", "DELAYED_DELIVERIES", "NUM_LATE",
            "LATE_SHIPMENTS", "OVERDUE_DELIVERIES",
        ),
    ),
    FieldDefinition(
        name="average_delay_days",
        label="Average Delay (days)",
        field_type=FieldType.NUMBER,
        required=False,
        description="Mean lateness of the late deliveries, in days.",
        aliases=(
            "AVG_DELAY_DAYS", "AVERAGE_DELAY_DAYS", "AVG_DELAY", "MEAN_DELAY",
            "AVERAGE_LATENESS", "DELAY_DAYS",
        ),
    ),
    FieldDefinition(
        name="quality_incident_count",
        label="Quality Incidents",
        field_type=FieldType.INTEGER,
        required=False,
        description="Formal quality incidents / non-conformance reports raised against the supplier.",
        aliases=(
            "QUALITY_INCIDENTS", "QUALITY_INCIDENT_COUNT", "NCR_COUNT", "NCRS",
            "COMPLAINTS", "QUALITY_NOTIFICATIONS", "NONCONFORMANCES",
        ),
    ),
    FieldDefinition(
        name="invoice_count",
        label="Invoices",
        field_type=FieldType.INTEGER,
        required=False,
        description="Invoices received from the supplier in the assessed period.",
        aliases=(
            "INVOICE_COUNT", "INVOICES", "NUM_INVOICES", "BILLING_DOCUMENTS",
            "INVOICE_VOLUME",
        ),
    ),
    FieldDefinition(
        name="invoice_exception_count",
        label="Invoice Exceptions",
        field_type=FieldType.INTEGER,
        required=False,
        description=(
            "Invoice exceptions raised against the supplier - the same exception concept "
            "module 4 (Invoice Validator) produces."
        ),
        aliases=(
            "INVOICE_EXCEPTIONS", "INVOICE_EXCEPTION_COUNT", "INVOICE_ISSUES",
            "BLOCKED_INVOICES", "INVOICE_ERRORS", "EXCEPTION_COUNT",
        ),
    ),
    FieldDefinition(
        name="disputed_invoice_count",
        label="Disputed Invoices",
        field_type=FieldType.INTEGER,
        required=False,
        description="Invoices formally disputed with the supplier.",
        aliases=(
            "DISPUTED_INVOICES", "DISPUTED_INVOICE_COUNT", "DISPUTES", "INVOICE_DISPUTES",
            "CONTESTED_INVOICES",
        ),
    ),
    FieldDefinition(
        name="credit_score",
        label="Credit Score",
        field_type=FieldType.NUMBER,
        required=False,
        description=(
            "Internally recorded credit / financial standing score on a 0-100 scale "
            "(higher is stronger). This is a stored internal figure, not a live credit feed."
        ),
        aliases=(
            "CREDIT_SCORE", "CREDIT_RATING", "FINANCIAL_SCORE", "CREDIT_INDEX",
            "SOLVENCY_SCORE", "FINANCIAL_STRENGTH",
        ),
    ),
    FieldDefinition(
        name="days_payable_outstanding",
        label="Days Payable Outstanding",
        field_type=FieldType.NUMBER,
        required=False,
        description="Average days taken to settle the supplier's invoices.",
        aliases=(
            "DPO", "DAYS_PAYABLE_OUTSTANDING", "DAYS_PAYABLE", "AVG_PAYMENT_DAYS",
            "PAYMENT_DAYS", "DSO",
        ),
    ),
    FieldDefinition(
        name="payment_default_count",
        label="Payment Defaults",
        field_type=FieldType.INTEGER,
        required=False,
        description="Recorded payment defaults or failures to deliver against prepayment.",
        aliases=(
            "PAYMENT_DEFAULTS", "PAYMENT_DEFAULT_COUNT", "DEFAULTS", "ARREARS_COUNT",
            "MISSED_PAYMENTS",
        ),
    ),
    FieldDefinition(
        name="financial_distress_flag",
        label="Financial Distress Flag",
        field_type=FieldType.BOOLEAN,
        required=False,
        description=(
            "Internal flag raised when finance recorded a distress signal for the supplier "
            "(for example an insolvency notice logged in the vendor master)."
        ),
        aliases=(
            "FINANCIAL_DISTRESS", "DISTRESS_FLAG", "FINANCIAL_ALERT", "INSOLVENCY_FLAG",
            "FINANCIAL_WATCHLIST", "DISTRESS",
        ),
    ),
    FieldDefinition(
        name="category_spend_share",
        label="Category Spend Share",
        field_type=FieldType.NUMBER,
        required=False,
        description=(
            "Percentage of the category's total spend that goes to this supplier (0-100). "
            "The primary input to the spend concentration risk."
        ),
        aliases=(
            "CATEGORY_SPEND_SHARE", "SPEND_SHARE", "SHARE_OF_CATEGORY", "SPEND_PCT",
            "CATEGORY_SHARE", "WALLET_SHARE", "SPEND_CONCENTRATION",
        ),
    ),
    FieldDefinition(
        name="single_source_material_count",
        label="Single-source Materials",
        field_type=FieldType.INTEGER,
        required=False,
        description="Materials for which this supplier is the only approved source.",
        aliases=(
            "SINGLE_SOURCE_MATERIALS", "SINGLE_SOURCE_COUNT", "SOLE_SOURCE_MATERIALS",
            "SOLE_SOURCE_COUNT", "SINGLE_SOURCED",
        ),
    ),
    FieldDefinition(
        name="compliance_finding_count",
        label="Compliance Findings",
        field_type=FieldType.INTEGER,
        required=False,
        description="Open compliance findings recorded against the supplier.",
        aliases=(
            "COMPLIANCE_FINDINGS", "COMPLIANCE_FINDING_COUNT", "COMPLIANCE_ISSUES",
            "OPEN_FINDINGS", "VIOLATIONS", "COMPLIANCE_BREACHES",
        ),
    ),
    FieldDefinition(
        name="certification_status",
        label="Certification Status",
        field_type=FieldType.STRING,
        required=False,
        description=(
            "State of the supplier's required certifications (valid, expiring, expired, "
            "missing). Interpreted through the configured value lists."
        ),
        aliases=(
            "CERTIFICATION_STATUS", "CERTIFICATION", "CERT_STATUS", "CERTIFICATE_STATUS",
            "CERTIFICATIONS", "QUALIFICATION_STATUS",
        ),
        max_length=40,
    ),
    FieldDefinition(
        name="audit_status",
        label="Audit Status",
        field_type=FieldType.STRING,
        required=False,
        description="Outcome of the most recent supplier audit (passed, conditional, failed, none).",
        aliases=(
            "AUDIT_STATUS", "AUDIT_RESULT", "LAST_AUDIT_RESULT", "AUDIT_OUTCOME",
            "AUDIT_RATING", "SUPPLIER_AUDIT",
        ),
        max_length=40,
    ),
    FieldDefinition(
        name="last_audit_date",
        label="Last Audit Date",
        field_type=FieldType.DATE,
        required=False,
        description="Date of the most recent supplier audit.",
        aliases=(
            "LAST_AUDIT_DATE", "AUDIT_DATE", "LAST_AUDITED", "AUDITED_ON",
            "LAST_ASSESSMENT_DATE",
        ),
    ),
    FieldDefinition(
        name="capacity_utilization",
        label="Capacity Utilisation",
        field_type=FieldType.NUMBER,
        required=False,
        description=(
            "How much of the supplier's capacity is already committed, as a percentage. "
            "High utilisation leaves no headroom and raises operational risk."
        ),
        aliases=(
            "CAPACITY_UTILIZATION", "CAPACITY_UTILISATION", "UTILIZATION", "UTILISATION",
            "CAPACITY_USED_PCT", "LOAD_FACTOR",
        ),
    ),
    FieldDefinition(
        name="lead_time_variability_days",
        label="Lead Time Variability (days)",
        field_type=FieldType.NUMBER,
        required=False,
        description="Standard deviation of the supplier's actual lead times, in days.",
        aliases=(
            "LEAD_TIME_VARIABILITY", "LEAD_TIME_STDDEV", "LEAD_TIME_DEVIATION",
            "DELIVERY_VARIABILITY", "LEAD_TIME_SPREAD", "LT_VARIABILITY",
        ),
    ),
    FieldDefinition(
        name="alternative_supplier_count",
        label="Alternative Suppliers",
        field_type=FieldType.INTEGER,
        required=False,
        description="Qualified alternative suppliers available for what this supplier provides.",
        aliases=(
            "ALTERNATIVE_SUPPLIERS", "ALTERNATIVE_SUPPLIER_COUNT", "ALTERNATIVES",
            "BACKUP_SUPPLIERS", "SECOND_SOURCES", "QUALIFIED_ALTERNATIVES",
        ),
    ),
)

#: Module 3's supplier master fields, inherited unchanged.
INHERITED_FIELDS: tuple[str, ...] = SUPPLIER_MASTER_REGISTRY.names

#: The module's data contract: module 3's supplier master plus the risk facts.
REGISTRY = SUPPLIER_MASTER_REGISTRY.extend(PROFILE_FIELD_DEFINITIONS)

#: Fields that hold a delimited list rather than a single value (inherited).
LIST_FIELDS: tuple[str, ...] = ("materials_supplied", "plants_served", "regions_served")

CANONICAL_FIELDS: tuple[str, ...] = REGISTRY.names
FIELD_BY_NAME: dict[str, FieldDefinition] = REGISTRY.by_name
REQUIRED_FIELDS: tuple[str, ...] = REGISTRY.required
ALIAS_LOOKUP: dict[str, str] = REGISTRY.alias_lookup


# ---------------------------------------------------------------------------
# Risk events - the individual internal records the copilot cites
# ---------------------------------------------------------------------------

EVENT_FIELD_DEFINITIONS: tuple[FieldDefinition, ...] = (
    FieldDefinition(
        name="event_id",
        label="Event ID",
        field_type=FieldType.STRING,
        required=True,
        description="Identifier of the internal record (used when the copilot cites it).",
        aliases=("EVENT_ID", "ID", "RECORD_ID", "EVENT", "EVENT_NUMBER", "REF_ID"),
        max_length=40,
    ),
    FieldDefinition(
        name="supplier_id",
        label="Supplier ID",
        field_type=FieldType.STRING,
        required=True,
        description="Supplier the record belongs to (SAP LFA1-LIFNR).",
        aliases=(
            "LIFNR", "VENDOR", "VENDOR_ID", "VENDOR_NUMBER", "SUPPLIER", "SUPPLIER_NO",
            "SUPPLIER_NUMBER", "SUPPLIER_CODE",
        ),
        max_length=20,
    ),
    FieldDefinition(
        name="event_type",
        label="Event Type",
        field_type=FieldType.STRING,
        required=True,
        description=(
            "Kind of internal record: late_delivery, quality_incident, invoice_exception, "
            "compliance_finding, contract_event or payment_default."
        ),
        aliases=(
            "EVENT_TYPE", "TYPE", "RECORD_TYPE", "CATEGORY_TYPE", "ISSUE_TYPE", "KIND",
        ),
        max_length=40,
    ),
    FieldDefinition(
        name="event_date",
        label="Event Date",
        field_type=FieldType.DATE,
        required=False,
        description="Date the record was raised. Drives the risk trend windows.",
        aliases=(
            "EVENT_DATE", "DATE", "POSTING_DATE", "BUDAT", "RECORDED_ON", "CREATED_ON",
            "DOCUMENT_DATE",
        ),
    ),
    FieldDefinition(
        name="reference",
        label="Reference",
        field_type=FieldType.STRING,
        required=False,
        description="Source document the record points at (purchase order, invoice, contract).",
        aliases=(
            "REFERENCE", "REFERENCE_DOCUMENT", "DOCUMENT", "DOC_NUMBER", "EBELN", "BELNR",
            "SOURCE_DOCUMENT", "REF",
        ),
        max_length=40,
    ),
    FieldDefinition(
        name="severity",
        label="Severity",
        field_type=FieldType.STRING,
        required=False,
        description="Recorded severity of the event (low, medium, high, critical).",
        aliases=("SEVERITY", "PRIORITY", "CRITICALITY", "IMPACT", "SEVERITY_LEVEL"),
        max_length=20,
    ),
    FieldDefinition(
        name="description",
        label="Description",
        field_type=FieldType.STRING,
        required=False,
        description="Short free-text description of the record.",
        aliases=(
            "DESCRIPTION", "TEXT", "DETAILS", "NOTE", "COMMENT", "SHORT_TEXT", "REMARK",
        ),
        max_length=300,
    ),
    FieldDefinition(
        name="amount",
        label="Amount",
        field_type=FieldType.NUMBER,
        required=False,
        description="Monetary value attached to the record, where one applies.",
        aliases=("AMOUNT", "VALUE", "WRBTR", "NETWR", "IMPACT_VALUE", "EXPOSURE"),
    ),
    FieldDefinition(
        name="currency",
        label="Currency",
        field_type=FieldType.CURRENCY_CODE,
        required=False,
        description="Currency of the amount (SAP WAERS).",
        aliases=("WAERS", "CURRENCY", "CURRENCY_KEY", "CURR"),
        max_length=3,
    ),
)

#: Data contract for the optional risk-events file.
EVENT_REGISTRY = FieldRegistry(EVENT_FIELD_DEFINITIONS)

EVENT_CANONICAL_FIELDS: tuple[str, ...] = EVENT_REGISTRY.names
EVENT_REQUIRED_FIELDS: tuple[str, ...] = EVENT_REGISTRY.required
EVENT_ALIAS_LOOKUP: dict[str, str] = EVENT_REGISTRY.alias_lookup
