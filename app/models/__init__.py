"""ORM models. Importing this package registers every table on the metadata."""

from app.models.base import Base, TimestampMixin
from app.models.contract_assistant import (
    Contract,
    ContractClause,
    ContractObligation,
    ContractPage,
    ContractRisk,
)
from app.models.invoice_validator import InvoiceException, InvoiceValidation
from app.models.po_risk import PoAnalysis, PoFinding, PoRecord, UploadedFile
from app.models.spend import SpendAnalysis, SpendOpportunity, SpendTransaction
from app.models.supplier_reco import (
    Supplier,
    SupplierCatalog,
    SupplierRecommendation,
    SupplierRecommendationEntry,
)
from app.models.supplier_risk import (
    SupplierRiskAssessment,
    SupplierRiskDataset,
    SupplierRiskProfileRow,
    SupplierRiskRecord,
)

__all__ = [
    "Base",
    "TimestampMixin",
    "UploadedFile",
    "PoAnalysis",
    "PoRecord",
    "PoFinding",
    "SpendAnalysis",
    "SpendTransaction",
    "SpendOpportunity",
    "SupplierCatalog",
    "Supplier",
    "SupplierRecommendation",
    "SupplierRecommendationEntry",
    "InvoiceValidation",
    "InvoiceException",
    "SupplierRiskDataset",
    "SupplierRiskRecord",
    "SupplierRiskAssessment",
    "SupplierRiskProfileRow",
    "Contract",
    "ContractPage",
    "ContractClause",
    "ContractRisk",
    "ContractObligation",
]
