# SAP AI Application Lab

A local workbench for building and testing SAP-focused AI applications before any of them
reaches a public website.

Everything runs on your machine. **No SAP credentials, no paid APIs, no AI API key and no Docker
are required.**

> **Demo software.** Each module analyses only the file you give it. Nothing here connects to an
> SAP system, and no output has been validated in a live SAP environment.

---

## Status

| # | Module | Status |
| --- | --- | --- |
| 1 | **Purchase Order Risk Checker** | **Implemented** |
| 2 | **Spend Analytics Dashboard** | **Implemented** |
| 3 | **Supplier Recommendation Engine** | **Implemented** |
| 4 | **Invoice Validator** | **Implemented** |
| 5 | Supplier Risk Copilot | Planned |
| 6 | Contract Assistant | Planned |
| 7 | Inventory Predictor | Planned |
| 8 | SAP Test Case Generator | Planned |
| 9 | SAP Blueprint Generator | Planned |
| 10 | SAP Interview Coach | Planned |

Detailed progress: [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).

---

## Quick start

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Generate the fictional demo datasets
python scripts/generate_sample_data.py            # PO risk
python scripts/generate_spend_sample_data.py      # spend analytics
python scripts/generate_supplier_sample_data.py   # supplier catalogue
python scripts/generate_invoice_sample_data.py    # invoices, POs, goods receipts

# 4. Check the installation
python scripts/verify_setup.py

# 5. Start the API (terminal 1)
uvicorn app.main:app --reload       # http://127.0.0.1:8000/docs

# 6. Start the UI (terminal 2)
streamlit run streamlit_app/Home.py # http://localhost:8501
```

Platform-specific instructions (macOS, Windows, Linux) are in
[`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md).

---

## Module 1 - Purchase Order Risk Checker

Upload an SAP-style purchase order extract, get transparent risk findings, download a report.

**Workflow:** upload → file validation → preview → automatic column mapping → manual correction →
type validation → missing-data warnings → risk analysis → summary dashboard → detailed findings →
export.

**Supported files:** CSV, XLSX, JSON (up to 25 MB).

**Column mapping** recognises SAP technical names out of the box - `EBELN`, `EBELP`, `LIFNR`,
`MATNR`, `MATKL`, `BUKRS`, `EKORG`, `EKGRP`, `WERKS`, `MENGE`, `MEINS`, `NETPR`, `WAERS` and many
business-label variants. Anything it gets wrong you can correct in the UI or through the API.

### The 20 rules

| Rule | Name | Category |
| --- | --- | --- |
| PO-R001 | Duplicate purchase orders | Duplication |
| PO-R002 | Duplicate line items | Duplication |
| PO-R003 | Split purchases | Split and threshold avoidance |
| PO-R004 | Order value just below an approval threshold | Split and threshold avoidance |
| PO-R005 | Unusual unit price increase | Pricing |
| PO-R006 | Price variance for the same material | Pricing |
| PO-R007 | Off-contract purchase | Contract compliance |
| PO-R008 | Missing contract reference | Contract compliance |
| PO-R009 | High value order without approval | Approval and governance |
| PO-R010 | Late delivery | Delivery performance |
| PO-R011 | Requested delivery before order date | Data quality |
| PO-R012 | Actual delivery before order date | Data quality |
| PO-R013 | Quantity anomaly | Data quality |
| PO-R014 | Currency anomaly | Data quality |
| PO-R015 | Missing required fields | Data quality |
| PO-R016 | Unusual payment terms | Contract compliance |
| PO-R017 | Excessive manual changes | Approval and governance |
| PO-R018 | Supplier concentration | Supplier risk |
| PO-R019 | Maverick spending | Contract compliance |
| PO-R020 | Purchase from a high-risk supplier | Supplier risk |

Every threshold lives in
[`app/modules/po_risk/config/po_risk_rules.json`](app/modules/po_risk/config/po_risk_rules.json).
Edit a number there and the next analysis uses it - no code change, no redeploy.

### What each finding contains

Finding ID · Analysis ID · PO number · Item · Supplier · Risk category · Rule ID · Severity
(low/medium/high/critical) · Explanation · Supporting evidence · Recommended action · Confidence
score · Estimated financial exposure · Created date.

---

## Module 2 - Spend Analytics Dashboard

Upload procurement transactions, analyse spend, filter it, drill into any figure and review
modelled savings opportunities.

**Workflow:** upload → validation → preview → column mapping → filters → analysis → KPI dashboard
→ charts → drill-down → savings opportunities → export.

**Reuses module 1's field contract.** The 25 purchase order fields are shared, so a PO extract that
works with the Risk Checker analyses here unchanged - contract status is derived from the contract
number and the order date stands in for the transaction date. Eight fields are added on top:
transaction date, category, subcategory, contract status, preferred supplier status, baseline
price, current price and payment status.

### Metrics (all deterministic)

Total spend · purchase order count · line item count · supplier count · average PO value ·
median PO value · contracted spend · non-contracted spend · maverick spend · spend under
management · supplier concentration (HHI) · top supplier share · top five supplier share ·
tail spend · price variance · estimated savings opportunity · spend by currency.

### Filters

Date range plus supplier, material, material group, category, subcategory, plant, company code,
purchasing organisation, purchasing group, currency, contract status and preferred supplier
status. Filters are applied **before** every calculation, so the KPI cards, charts, drill-downs
and opportunity list always describe the same slice.

### Analytics

Monthly spend · by supplier · by category · by material group · by plant · by company code ·
by purchasing org · by purchasing group · top materials · tail-spend suppliers · supplier
concentration · contract leakage · maverick spend · purchase price variance.

Every breakdown row carries a `dimension` and a `value`, which is what makes drill-down work:
send those back to the transactions endpoint and you get exactly the lines behind the number.

### Savings rules

| Rule | Model |
| --- | --- |
| SAV-01 | Price harmonisation - pay the target percentile price on lines above it |
| SAV-02 | Contract compliance - bring non-contracted spend under contract |
| SAV-03 | Supplier consolidation - concentrate a fragmented material group |
| SAV-04 | Tail spend reduction - price leakage plus transaction handling cost |
| SAV-05 | Move to preferred suppliers - where one already sells the same material cheaper |
| SAV-06 | Reduce price variance - pay the baseline price on lines bought above it |

> **Savings figures are modelled estimates, never guarantees.** Each opportunity carries the
> arithmetic that produced it (`method`), the assumptions applied, a realization factor and
> `is_estimate: true`. Nothing has been negotiated with a supplier or validated in SAP.

All assumptions live in
[`app/modules/spend/config/spend_rules.json`](app/modules/spend/config/spend_rules.json).


---

## Module 3 - Supplier Recommendation Engine

Upload a supplier master file, describe a purchasing requirement, tune the scoring weights and get
a transparent ranking of the eligible suppliers.

**Workflow:** upload supplier catalogue → requirement form → weight controls (validated to 100%) →
eligibility filtering → weighted scoring → ranked cards → comparison table → score breakdown →
radar chart → optional AI summary → export.

**Supported files:** CSV, XLSX, JSON (up to 25 MB). The 19 supplier fields reuse the shared
[`FieldRegistry`](app/services/tabular/field_registry.py) and SAP alias conventions (`LIFNR`,
`WAERS`, `ZTERM`), so a supplier extract with technical headers maps with no manual correction.
Materials, plants and regions served are multi-valued columns, split into lists by the normaliser.

### Eligibility filters (applied *before* ranking)

Material match · plant served · minimum available capacity (and capacity covering the quantity) ·
minimum quality score · risk tolerance (low/medium/high ceilings) · sustainability requirement
(minimum ESG) · contract requirement. Each filter maps to a requirement field, can be switched off
in configuration, and every rejection carries a human-readable reason.

### The nine normalized scores

| Score | Formula (all 0-100, higher is better) |
| --- | --- |
| Cost | min-max (lower price is better) of the unit price in base currency |
| Delivery | on-time-delivery-rate blended with lead-time fitness |
| Quality | quality score blended with a defect-rate penalty |
| Capacity | available capacity against `quantity x target coverage ratio` |
| Risk | `100 - risk score` |
| ESG | the ESG score directly |
| Contract | fixed score per contract status (active / expiring / none / unknown) |
| Geographic | share of the specified region/plant criteria the supplier satisfies |
| Past performance | historical order count blended with historical spend |

Users set the nine weights; the API **rejects any set that does not total 100%**. The overall
score is the weighted sum. Every weight and formula lives in
[`app/modules/supplier_reco/config/supplier_reco_rules.json`](app/modules/supplier_reco/config/supplier_reco_rules.json)
and is echoed back by `GET /api/v1/supplier-recommendations/scoring`.

### What each ranked result contains

Rank · supplier · eligibility status · overall score · the nine sub-scores · estimated total cost ·
estimated delivery date · contract status · advantages · risks · a rule-based explanation. AI may
summarise the ranking, but **the ranking is entirely deterministic - AI never decides the order.**

> **Estimated costs and delivery dates are indicative planning figures, not quotations.** Nothing
> here has been negotiated with a supplier or validated in SAP.

---

## Module 4 - Invoice Validator

Upload **three** files - invoices, purchase orders and goods receipts - and three-way match them
with configurable deterministic rules. This is the first module that joins several uploaded
datasets rather than analysing one.

**Workflow:** upload each file (with its own column mapping) → set tolerances → validate → summary
metrics → exception charts → filterable exception table → three-way-match comparison → export.

**Supported files:** CSV, XLSX, JSON (up to 25 MB) for each of the three datasets. The invoice file
is required; the purchase order and goods receipt files are optional, and the rules that depend on a
missing dataset are reported as skipped rather than silently producing nothing.

**Reuses the purchase-order model.** The PO dataset uses the 25 purchase-order fields from module 1
(extended with a single `PO Status` field for closed-PO detection), so a PO extract with SAP
technical headers maps automatically. Invoices (16 fields) and goods receipts (7 fields) add their
own registries.

### The 17 validation rules

| Rule | Checks |
| --- | --- |
| IV-R001 | Duplicate invoices (same supplier, amount and date) |
| IV-R002 | Duplicate invoice number for a supplier |
| IV-R003 | Missing purchase order |
| IV-R004 | Missing goods receipt |
| IV-R005 | Price mismatch versus the PO |
| IV-R006 | Quantity mismatch versus the receipt (or ordered quantity) |
| IV-R007 | Tax mismatch versus the expected rate |
| IV-R008 | Currency mismatch versus the PO |
| IV-R009 | Supplier mismatch versus the PO |
| IV-R010 | Freight above the policy ceiling |
| IV-R011 | Payment-term mismatch versus the PO |
| IV-R012 | Three-way-match exception (billed above the accepted quantity) |
| IV-R013 | Overbilling (cumulative invoicing exceeds the ordered line) |
| IV-R014 | Invoice dated before the purchase order |
| IV-R015 | Invoice dated before the goods receipt |
| IV-R016 | Future invoice date |
| IV-R017 | Invoicing against a closed purchase order |

Every threshold, the four tolerances (price, quantity, tax, freight), the expected tax rate, the
freight ceiling and the closed-PO status list live in
[`app/modules/invoice_validator/config/invoice_validator_rules.json`](app/modules/invoice_validator/config/invoice_validator_rules.json).
The four tolerances can additionally be overridden per validation run through the API and the UI.

### What each exception contains

Exception ID · invoice number · supplier · purchase order · PO item · goods receipt · exception type
· severity · expected value · actual value · difference · difference amount · a rule-based
explanation · a recommended action. AI may summarise the exceptions, but **every exception is
produced by deterministic Python - AI never decides one.**

> **Difference amounts are indicative and describe the uploaded files only.** Nothing here has been
> validated in a live SAP environment.

---

## Deterministic rules vs AI

This separation is the core design decision of the project.

| | Deterministic Python | AI (optional) |
| --- | --- | --- |
| Detecting risk | ✅ | ❌ never |
| Severity and confidence | ✅ | ❌ never |
| Calculations, aggregation, ranking | ✅ | ❌ never |
| Rewriting a finding in business language | | ✅ |
| Executive summary | | ✅ |

**Mock mode is the default.** With no API key the lab uses a deterministic mock provider that
templates the real rule results into narrative text. Output is labelled `mock_ai`, so nobody
mistakes it for a model response. Configure `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` plus
`AI_PROVIDER` to use a real model; structured responses are validated with Pydantic before being
stored, and an AI failure never blocks the rule-based results.

Every value that reaches a user is labelled: `rule_based`, `ai_generated`, `mock_ai`, `forecast`
or `demo_data`.

---

## Sample data

`python scripts/generate_sample_data.py` produces a fictional dataset in `data/sample/`:

- **1,238 line items** across **578 purchase orders** and **55 suppliers**
- three formats with three different header conventions (CSV uses SAP technical names, XLSX uses
  business labels, JSON uses snake_case) so the column mapper is exercised properly
- **89 documented anomalies** covering all 20 rules, listed in
  [`data/sample/ANOMALY_MANIFEST.md`](data/sample/ANOMALY_MANIFEST.md) with the expected rule,
  expected severity and the reason each one was inserted
- `expected_findings_baseline.json`, the exact per-rule totals the current engine produces

The generator is seeded, so regenerating reproduces the identical dataset. The background
population is deliberately built *not* to trigger rules, which makes every finding traceable.

`python scripts/generate_spend_sample_data.py` produces the spend dataset:

- **3,640 transactions** across **24 months**, 64 suppliers, 124 materials and 9 categories
- five currencies, so base-currency conversion is genuinely exercised
- **8 documented scenarios** covering maverick spend, contract leakage, supplier concentration,
  price variance, tail spend, preferred-supplier price gaps, supplier fragmentation and price
  dispersion - listed in
  [`data/sample/SPEND_SCENARIO_MANIFEST.md`](data/sample/SPEND_SCENARIO_MANIFEST.md)
- `expected_spend_baseline.json`, the exact figures the current engine produces

`python scripts/generate_supplier_sample_data.py` produces the supplier catalogue:

- **55 fictional suppliers** with intentionally varied prices, lead times, quality, capacity, risk,
  ESG scores, contract status, regions and materials, across 3 currencies
- **7 documented anchor suppliers** covering the lowest-cost bidder, a high-risk supplier, one that
  does not supply the material, a weak-ESG supplier, one with no contract, one that cannot cover the
  quantity, and one whose contract expires before delivery - listed in
  [`data/sample/SUPPLIER_SCENARIO_MANIFEST.md`](data/sample/SUPPLIER_SCENARIO_MANIFEST.md) with a
  canonical requirement
- `expected_supplier_baseline.json`, the exact ranking the current engine produces for that
  requirement

`python scripts/generate_invoice_sample_data.py` produces the invoice datasets:

- **420 invoices**, **418 purchase order lines** and **417 goods receipts**, three formats each
  (CSV technical headers, XLSX business labels, JSON snake_case)
- most invoices match their PO and goods receipt cleanly and raise no exception; **17 documented
  anchor invoices**, one per rule, are placed deliberately - listed in
  [`data/sample/INVOICE_SCENARIO_MANIFEST.md`](data/sample/INVOICE_SCENARIO_MANIFEST.md) with a
  fixed reference date for the future-date check
- `expected_invoice_baseline.json`, the exact per-rule exception totals the current engine produces

---

## Project layout

```text
app/
  api/v1/          FastAPI routes (HTTP only)
  core/            config, logging, exceptions, security
  models/          SQLAlchemy ORM models and session
  schemas/         Pydantic request/response contracts
  services/        ai/, files/, exports/, tabular/ (shared mapping + parsing)
  modules/po_risk/ field definitions, rules, engine, service
  modules/spend/   field definitions, normaliser, metrics, analytics, filters, savings
  modules/supplier_reco/ field definitions, normaliser, eligibility, scoring, engine, service
  modules/invoice_validator/ field definitions, normalisers, matching, rules, engine, service
streamlit_app/     temporary UI - calls the API over HTTP
data/              sample/, uploads/, exports/
tests/             unit/, api/, integration/
scripts/           sample data generator, setup checker
docs/              architecture, setup, testing, API, status, website integration
migrations/        Alembic
```

Business logic never lives in a Streamlit page. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Testing

```bash
pytest                    # everything (506 tests, ~60s)
pytest tests/unit         # 296 - rules, metrics, savings, scoring, eligibility, tolerances, mapping, parsing, security, AI
pytest tests/api          # 129 - endpoints against a temporary database
pytest tests/integration  # 81  - full journeys over all four sample datasets
```

The integration suites read the anomaly, scenario, supplier and invoice manifests and assert that
every documented condition is actually detected. Details in [`docs/TESTING.md`](docs/TESTING.md).

---

## Configuration

Copy `.env.example` to `.env` and edit. Everything has a working default, so the lab runs with no
`.env` at all. Secrets are read from the environment only - never from source, and never returned
by an endpoint or written to a log.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | SQLite in `data/` | PostgreSQL-ready connection string |
| `AI_PROVIDER` | `mock` | `mock`, `anthropic` or `openai` |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | unset | Only needed for a real model |
| `MAX_UPLOAD_BYTES` | 25 MB | Upload size limit |
| `API_BASE_URL` | `http://127.0.0.1:8000` | Where Streamlit finds the API |

Switching to PostgreSQL is a one-line change:

```bash
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/sap_ai_lab
alembic upgrade head
```

---

## Security

Uploaded documents are treated as untrusted data throughout: file-type and size validation with a
magic-byte check, filename sanitisation, path-traversal protection on every read and write,
request validation with Pydantic, safe error messages that never leak paths or stack traces, and
prompt-injection filtering before any content reaches a model. Instructions found inside an
uploaded file are never executed.

---

## Documentation

| Document | Contents |
| --- | --- |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Layers, data flow, design decisions |
| [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md) | macOS, Windows and Linux setup |
| [`docs/TESTING.md`](docs/TESTING.md) | Test strategy and how to add a rule test |
| [`docs/API_OVERVIEW.md`](docs/API_OVERVIEW.md) | Endpoints, envelope, examples |
| [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) | What is done, what is next |
| [`docs/FUTURE_WEBSITE_INTEGRATION.md`](docs/FUTURE_WEBSITE_INTEGRATION.md) | Replacing Streamlit with React/Next.js |
| [`data/sample/ANOMALY_MANIFEST.md`](data/sample/ANOMALY_MANIFEST.md) | Documented PO risk anomalies |
| [`data/sample/SPEND_SCENARIO_MANIFEST.md`](data/sample/SPEND_SCENARIO_MANIFEST.md) | Documented spend scenarios |
| [`data/sample/SUPPLIER_SCENARIO_MANIFEST.md`](data/sample/SUPPLIER_SCENARIO_MANIFEST.md) | Documented supplier anchors and the canonical requirement |
