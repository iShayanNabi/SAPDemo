# API overview

Base URL (local): `http://127.0.0.1:8000`
Versioned prefix: `/api/v1`
Interactive docs: <http://127.0.0.1:8000/docs>

Every endpoint the Streamlit UI uses is public and documented here, which is what makes the UI
replaceable.

---

## Response envelope

Every JSON response has the same shape.

```json
{
  "success": true,
  "data": { },
  "error": null,
  "meta": {
    "timestamp": "2026-07-30T09:15:00Z",
    "request_id": "3f9c...",
    "api_version": "v1"
  }
}
```

On failure:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "file_validation_error",
    "message": "This file type is not supported. Upload a .csv, .xlsx or .json file.",
    "details": { "extension": ".pdf" }
  },
  "meta": { "timestamp": "...", "request_id": "...", "api_version": "v1" }
}
```

Messages are safe to display: no paths, stack traces or driver output. `request_id` also appears
in the `X-Request-ID` header and in the server log.

Binary downloads (exports, sample files) return the file itself, not an envelope.

| Code | Status | Meaning |
| --- | --- | --- |
| `validation_error` | 422 | Request or mapping failed validation |
| `file_validation_error` | 400 | File type, size or content problem |
| `not_found` | 404 | Unknown analysis or upload |
| `analysis_error` | 422 | The analysis could not be completed |
| `ai_provider_error` | 502 | AI provider failed (findings are unaffected) |
| `internal_error` | 500 | Unexpected error; see the log with the request ID |

---

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Service index and module list |
| GET | `/api/v1/health` | Health, database and AI provider status |
| POST | `/api/v1/po-risk/upload` | Upload a file, get a column-mapping suggestion |
| POST | `/api/v1/po-risk/analyze` | Run the analysis |
| GET | `/api/v1/po-risk/analyses` | List past analyses |
| GET | `/api/v1/po-risk/analyses/{id}` | One analysis with KPIs |
| GET | `/api/v1/po-risk/analyses/{id}/findings` | Findings, filterable and paginated |
| GET | `/api/v1/po-risk/analyses/{id}/export` | Download xlsx, csv or json |
| GET | `/api/v1/po-risk/rules` | Rule catalogue with configured thresholds |
| GET | `/api/v1/po-risk/fields` | Canonical fields and their SAP aliases |
| GET | `/api/v1/po-risk/sample` | Download the demo file |
| GET | `/api/v1/po-risk/sample/info` | Describe the demo dataset |
| GET | `/api/v1/po-risk/ai-status` | Active AI provider (never a key) |

### Spend Analytics Dashboard

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/spend/upload` | Upload transactions, get a column-mapping suggestion |
| POST | `/api/v1/spend/analyze` | Run the analysis with optional filters |
| GET | `/api/v1/spend/analyses` | List past analyses |
| GET | `/api/v1/spend/analyses/{id}` | Metrics, breakdowns, opportunities, narrative |
| GET | `/api/v1/spend/analyses/{id}/transactions` | Drill down into transactions |
| GET | `/api/v1/spend/analyses/{id}/opportunities` | Modelled savings opportunities |
| GET | `/api/v1/spend/analyses/{id}/export` | Download xlsx, csv or json |
| GET | `/api/v1/spend/fields` | Canonical fields and their aliases |
| GET | `/api/v1/spend/savings-rules` | Savings rules and their assumptions |
| GET | `/api/v1/spend/methodology` | How every figure is calculated |
| GET | `/api/v1/spend/sample` | Download the demo file |
| GET | `/api/v1/spend/sample/info` | Describe the demo dataset |

### Supplier Recommendation Engine

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/suppliers/upload` | Upload a supplier master file into a catalogue |
| GET | `/api/v1/suppliers` | List suppliers (filter by material, region, plant, contract) |
| GET | `/api/v1/suppliers/{supplier_id}` | One supplier's master data |
| GET | `/api/v1/suppliers/catalogs` | List uploaded catalogues |
| GET | `/api/v1/suppliers/fields` | Canonical supplier fields and their aliases |
| GET | `/api/v1/suppliers/sample` | Download the demo supplier file |
| GET | `/api/v1/suppliers/sample/info` | Describe the demo catalogue |
| POST | `/api/v1/supplier-recommendations/recommend` | Rank suppliers for a requirement |
| GET | `/api/v1/supplier-recommendations` | List past recommendations |
| GET | `/api/v1/supplier-recommendations/{id}` | One recommendation with ranked results |
| GET | `/api/v1/supplier-recommendations/{id}/export` | Download xlsx, csv or json |
| GET | `/api/v1/supplier-recommendations/scoring` | Weights, formulas and eligibility filters |
| GET | `/api/v1/supplier-recommendations/ai-status` | Active AI provider (never a key) |

The `recommend` body is `{catalog_id?, requirement, weights?, top_n?, generate_ai_summary?,
include_ineligible?}`. `weights` must total 100% (nine dimensions: cost, delivery, quality,
capacity, risk, esg, contract, geographic, past_performance) or the request is rejected with a
`validation_error` (422). When `catalog_id` is omitted the most recent catalogue is used.

### Supplier Risk Copilot

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/supplier-risk/upload` | Upload risk profiles (`dataset=profiles`) or dated risk events (`dataset=events`) |
| POST | `/api/v1/supplier-risk/calculate` | Score every supplier across the ten risk categories |
| GET | `/api/v1/supplier-risk/suppliers` | Assessed suppliers, highest risk first |
| GET | `/api/v1/supplier-risk/suppliers/{supplier_id}` | One supplier's full risk profile |
| POST | `/api/v1/supplier-risk/chat` | Ask the copilot a question, with citations |
| GET | `/api/v1/supplier-risk/datasets` | List uploaded risk datasets |
| GET | `/api/v1/supplier-risk/assessments` | List past assessments |
| GET | `/api/v1/supplier-risk/assessments/{id}` | One assessment with ranked suppliers |
| GET | `/api/v1/supplier-risk/scoring` | Categories, weights, metrics, bands, missing-data behaviour |
| GET | `/api/v1/supplier-risk/fields` | Canonical risk fields and their aliases |
| GET | `/api/v1/supplier-risk/sample` | Download a demo file (`dataset=profiles\|events`) |
| GET | `/api/v1/supplier-risk/sample/info` | Describe the demo dataset |
| GET | `/api/v1/supplier-risk/ai-status` | Active AI provider (never a key) |

### Module 6 - Contract Assistant

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/contracts/upload` | Upload a PDF/DOCX/TXT contract and extract its text |
| POST | `/api/v1/contracts/{contract_id}/analyze` | Extract clauses, dates, obligations and risks |
| GET | `/api/v1/contracts/{contract_id}` | The full analysis |
| GET | `/api/v1/contracts/{contract_id}/clauses` | The clause table (`present_only`, `clause_type`, `min_confidence`) |
| POST | `/api/v1/contracts/{contract_id}/questions` | Ask a question, get an answer with citations |
| GET | `/api/v1/contracts/{contract_id}/export` | Download the report (`xlsx\|csv\|json`) |
| GET | `/api/v1/contracts` | List uploaded contracts, newest first |
| GET | `/api/v1/contracts/methodology` | Clause catalogue, rules, confidence formula, date settings |
| GET | `/api/v1/contracts/extractors` | Readable formats and OCR availability (never a credential) |
| GET | `/api/v1/contracts/sample` | Download a demo contract (`name`, `format=pdf\|docx\|txt`) |
| GET | `/api/v1/contracts/sample/info` | Describe the demo contracts |
| GET | `/api/v1/contracts/ai-status` | Active AI provider (never a key) |

Every clause, risk, obligation and answer carries a **source reference**: `page_number`,
`section_heading`, `excerpt` and a deterministic `confidence`. Upload returns
`status: needs_ocr` for a document with no extractable text, and analyse refuses it rather than
returning an empty contract.

The `calculate` body is `{dataset_id?, weights?, as_of_date?, generate_ai_summary?}`. `weights` must
total 100% across the ten categories (delivery, quality, financial, spend_concentration, contract,
invoice, compliance, esg, geographic, operational) or the request is rejected. When `dataset_id` is
omitted the most recent dataset is used; `as_of_date` defaults to today and drives contract expiry
and the trend windows.

The `chat` body is `{question, assessment_id?, supplier_id?, generate_ai_summary?}`. Pass
`supplier_id` so follow-ups like *"why is this supplier high risk?"* resolve. The response carries
`answer`, `intent`, `data_available`, `unavailable_reason`, `citations[]` and
`suppliers_referenced[]`. **Every risk score is `rule_based`**; the optional `ai_narrative` is a
separate field and never replaces a computed figure.

Risk scores run **0 = no risk to 100 = maximum risk**. A supplier whose data supports fewer than
three categories has `overall_score: null` rather than a score computed from a fragment.

### Module 7 - Inventory Predictor

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/inventory/upload` | Upload an inventory history and load it into a dataset |
| POST | `/api/v1/inventory/forecast` | Forecast demand and plan replenishment |
| GET | `/api/v1/inventory/forecasts/{forecast_id}` | One forecast run with its materials |
| GET | `/api/v1/inventory/forecasts/{forecast_id}/export` | Download the report (`xlsx\|csv\|json`) |
| GET | `/api/v1/inventory/forecasts/{forecast_id}/items` | Materials in a run, filtered and paged |
| GET | `/api/v1/inventory/forecasts/{forecast_id}/item` | One material's full forecast (`material`, `plant`, `storage_location?`) |
| GET | `/api/v1/inventory/forecasts` | List past runs, newest first |
| GET | `/api/v1/inventory/datasets` | List uploaded inventory datasets |
| GET | `/api/v1/inventory/fields` | Canonical inventory fields and their SAP aliases |
| GET | `/api/v1/inventory/methods` | Every forecasting method with its assumptions, plus selection rules, reorder formulae and stock thresholds |
| GET | `/api/v1/inventory/sample` | Download the demo history (`format=csv\|xlsx\|json`) |
| GET | `/api/v1/inventory/sample/info` | Describe the demo dataset |
| GET | `/api/v1/inventory/ai-status` | Active AI provider (never a key) |

The `forecast` body is `{dataset_id?, horizon_periods?, confidence_level?, model?, as_of_date?,
materials?, plants?, generate_ai_summary?}`. A dataset is uploaded once and can be forecast
repeatedly: changing the horizon, the confidence level or the model needs no re-upload.

- `model` is `auto` (default) or one of the five methods. A forced method that cannot be applied to
  a material falls back to automatic selection **for that material only**, and the response says
  why.
- `confidence_level` must be one of the levels with a configured z-score (see
  `/inventory/methods`); an unconfigured level is rejected rather than silently defaulting to 1.96.
- `as_of_date` defaults to the end of each material's own history, so a historical file is analysed
  as at its own end rather than as at today.

The item list supports `material`, `plant`, `supplier_id`, `model`, `status`, `movement_class`,
`shortage_only`, `reorder_only`, `overstock_only`, `dead_stock_only` and
`sort=shortage|reorder|demand|accuracy|material`. Material and plant are **query** parameters on
the item detail route, not path segments, because a material number can contain a slash.

Every forecast figure is labelled `output_origin: forecast` - a statistical estimate about the
future, distinct from `rule_based` findings about a file. The optional `ai_narrative` keeps its own
`ai_generated`/`mock_ai` label and never produces a number.

`mape` is `null` whenever the comparison window contains a zero-demand period, with
`mape_unavailable_reason` explaining why; `smape` and `mase` are always present. A material with
too little history is returned with `status: insufficient_data` and its warning rather than being
dropped or estimated.

### Module 8 - SAP Test Case Generator

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/test-cases/generate` | Generate a suite from a business process description |
| GET | `/api/v1/test-cases/suites/{suite_id}` | One suite with its coverage, summary and test cases |
| PUT | `/api/v1/test-cases/{test_case_id}` | Edit one test case (partial) |
| DELETE | `/api/v1/test-cases/{test_case_id}` | Delete one test case |
| POST | `/api/v1/test-cases/{test_case_id}/regenerate` | Redraft one test case's script |
| GET | `/api/v1/test-cases/suites/{suite_id}/export` | Download the suite (`xlsx\|csv\|json\|pdf`) |
| POST | `/api/v1/test-cases/suites/{suite_id}/test-cases` | Add a test case by hand |
| POST | `/api/v1/test-cases/{test_case_id}/duplicate` | Copy a test case into a new row |
| POST | `/api/v1/test-cases/{test_case_id}/approve` | Approve or un-approve a test case |
| POST | `/api/v1/test-cases/{test_case_id}/execution` | Record a pass/fail result |
| GET | `/api/v1/test-cases/{test_case_id}` | One test case |
| GET | `/api/v1/test-cases/suites` | List generated suites, newest first |
| GET | `/api/v1/test-cases/catalog` | The eight test types, the limits and the deterministic rules |
| GET | `/api/v1/test-cases/sample` | Load one fictional demo process definition (`name=`) |
| GET | `/api/v1/test-cases/sample/info` | Describe the demo process definitions |
| GET | `/api/v1/test-cases/ai-status` | Active AI provider (never a key) |

The `generate` body is `{context, test_case_count, test_types, suite_name?, default_owner?,
use_ai?}`, where `context` carries the twelve process inputs: `sap_product`, `sap_module`,
`business_process`, `process_description`, `preconditions`, `business_rules`, `systems_involved`,
`integrations`, `user_roles` and `test_data_requirements`. Every list also accepts a
newline-separated string, which is what a form sends.

- **`test_types` order matters.** Types are covered in the order given. When `test_case_count` is
  smaller than the number of types, the ones listed last go without a case and come back in
  `uncovered_test_types` with a note - they are never dropped silently.
- **`use_ai: false` still returns a complete suite**, built from the configured templates and
  labelled `rule_based`. So does a provider outage; the failure lands in `ai.error` and in
  `generation_issues`.
- **`generation_issues`** lists every drafting problem that was recovered from, with a `stage` of
  `provider`, `payload` or `content`. An empty list means nothing needed repairing.

Each test case carries two provenance fields: `output_origin` (`rule_based`, `ai_generated` or
`mock_ai` - what produced the words) and `source` (`ai_generated`, `template`, `manual` or
`duplicated` - how the row entered the suite). `validation_notes` lists what the deterministic
repair had to fix in a drafted case.

Editing has consequences the response reports rather than hides:

- editing any script field clears `approved_by`/`approved_at` and returns the case to `draft`;
- a verdict recorded before a script change is kept and flagged with `execution_is_stale`, counted
  in `summary.stale_execution_count`, and cleared when the test is run again;
- deleting a case returns `lost_test_types` - the types the suite no longer covers at all;
- changing a case's test type reissues its identifier, because the identifier encodes the type.

`POST /test-cases/{id}/regenerate` takes `{instruction?, test_type?, use_ai?,
keep_execution_record?}`. It keeps the identifier and the sequence, always clears the approval, and
keeps the execution record unless told otherwise.


### Module 9 - SAP Blueprint Generator

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/blueprints/generate` | Generate a blueprint from a structured project request |
| GET | `/api/v1/blueprints/{blueprint_id}` | One blueprint with its summary and all sections |
| PUT | `/api/v1/blueprints/{blueprint_id}` | Edit the blueprint, or replace its project request |
| POST | `/api/v1/blueprints/{blueprint_id}/sections/{section_id}/regenerate` | Redraft one section |
| GET | `/api/v1/blueprints/{blueprint_id}/versions` | The version history, newest first |
| GET | `/api/v1/blueprints/{blueprint_id}/export` | Download (`markdown\|json\|docx\|pdf`) |
| POST | `/api/v1/blueprints/{blueprint_id}/sections` | Add a custom section |
| GET | `/api/v1/blueprints/{blueprint_id}/sections/{section_id}` | One section |
| PUT | `/api/v1/blueprints/{blueprint_id}/sections/{section_id}` | Edit one section (partial) |
| DELETE | `/api/v1/blueprints/{blueprint_id}/sections/{section_id}` | Delete one **custom** section |
| POST | `/api/v1/blueprints/{blueprint_id}/sections/{section_id}/approve` | Approve or un-approve |
| POST | `/api/v1/blueprints/{blueprint_id}/versions` | Save the current state as a version |
| GET | `/api/v1/blueprints/{blueprint_id}/versions/{version_number}` | One version with its snapshot |
| GET | `/api/v1/blueprints/{blueprint_id}/versions/compare` | Compare two versions (`from=`, `to=`) |
| GET | `/api/v1/blueprints` | List generated blueprints, newest first |
| GET | `/api/v1/blueprints/catalog` | The thirty sections, the project fields and the rules |
| GET | `/api/v1/blueprints/sample` | Load one fictional demo project request (`name=`) |
| GET | `/api/v1/blueprints/sample/info` | Describe the demo project requests |
| GET | `/api/v1/blueprints/ai-status` | Active AI provider (never a key) |

The `generate` body is `{project, blueprint_name?, sections?, owner?, use_ai?}`, where `project`
carries the nineteen project inputs: `company`, `industry`, `sap_product`, `modules`,
`business_objectives`, `current_process`, `desired_process`, `countries`, `locations`,
`company_codes`, `plants`, `purchasing_organizations`, `systems_involved`, `integrations`,
`data_sources`, `user_groups`, `timeline`, `constraints` and `assumptions`. Every list also accepts
a newline-separated string, which is what a form sends.

- **`sections` is a filter, not an order.** The document always comes back in the canonical order,
  and the sections left out are reported in `excluded_sections`.
- **`use_ai: false` still returns a complete document**, written from the configured templates and
  labelled `rule_based`. So does a provider outage; the failure lands in `ai.error` and in
  `generation_issues`.
- **A section whose required project fields are empty comes back `status: "needs_input"`** with
  `missing_inputs` naming them and `items: []`. It is not drafted, not templated with invented
  content, and never sent to a provider. `summary.missing_inputs` aggregates the fields across the
  document.

Each section carries three provenance fields: `output_origin` (`rule_based`, `ai_generated` or
`mock_ai` - what produced the words), `source` (`ai_generated`, `derived`, `template` or `manual` -
how the content came to exist) and `validation_notes` (what the deterministic repair had to fix).
Each *item* carries its own `source`, so a reader can tell a company code taken from the project
request from a risk a model drafted.

Editing has consequences the response reports rather than hides:

- editing the title, narrative or items clears `approved_by`/`approved_at` and returns the section
  to `draft`; editing only the status or a comment does not;
- every section carries a `content_revision`, and `depends_on` lists the sections it describes.
  When one of those changes, the section reports it in `stale_dependencies`;
- a section that is **approved and stale** sets `approval_is_stale` and is counted in
  `summary.stale_approved_count`. The approval is kept - somebody gave it - but it was given to a
  description of something that has since changed;
- only custom sections can be deleted; the thirty standard ones return `422`;
- a custom section identifier is never reissued, even after the section is deleted;
- `PUT /blueprints/{id}` with a `project` block rebuilds the sections whose items are computed from
  the request and clears their approvals, and it unblocks any section that was waiting for input.

`GET /blueprints/{id}/versions/compare?from=2&to=0` compares a saved version with **the live
document** - version `0` means "as it stands now". Sections are matched by `section_key` and items
by title, so inserting a section or renumbering items does not report everything below as rewritten.

---

## Health

```bash
curl http://127.0.0.1:8000/api/v1/health
```

```json
{ "status": "ok", "app_name": "SAP AI Application Lab", "version": "0.1.0",
  "environment": "local", "database_connected": true,
  "ai_provider": "mock", "ai_is_mock": true }
```

---

## Upload

`multipart/form-data`, field name `file`. CSV, XLSX or JSON, up to 25 MB.

```bash
curl -F "file=@data/sample/sample_purchase_orders.csv;type=text/csv" \
     http://127.0.0.1:8000/api/v1/po-risk/upload
```

```json
{
  "upload_id": "87a5dc79603c41f281ec57aee545a811",
  "original_filename": "sample_purchase_orders.csv",
  "size_bytes": 289431,
  "row_count": 1238,
  "column_count": 25,
  "detected_columns": ["EBELN", "EBELP", "LIFNR", "..."],
  "preview_rows": [ { "EBELN": "4500001", "...": "..." } ],
  "suggested_mapping": { "EBELN": "po_number", "LIFNR": "supplier_id" },
  "mapping_suggestions": [
    { "source_column": "EBELN", "field_name": "po_number",
      "confidence": 1.0, "strategy": "exact_alias" }
  ],
  "unmapped_columns": [],
  "missing_required_fields": [],
  "is_analyzable": true,
  "parser_notes": ["Detected ',' as the CSV delimiter."]
}
```

`strategy` is `exact_alias` (1.00), `token_match` (0.80) or `fuzzy` (≥0.82). Show the confidence
so the user knows which suggestions to check.

The stored filename is sanitised and made unique; `original_filename` is the sanitised display
name. A traversal attempt like `../../etc/orders.csv` is stored as `orders.csv`.

---

## Analyze

```bash
curl -X POST http://127.0.0.1:8000/api/v1/po-risk/analyze \
  -H "Content-Type: application/json" \
  -d '{
        "upload_id": "87a5dc79603c41f281ec57aee545a811",
        "column_mapping_overrides": { "ZZ_CATEGORY": "material_group" },
        "generate_ai_summary": true,
        "rewrite_findings": false,
        "enabled_rules": null
      }'
```

| Field | Default | Meaning |
| --- | --- | --- |
| `upload_id` | required | From the upload response |
| `column_mapping_overrides` | `{}` | Source column → canonical field. `""` ignores a column. Overrides win over suggestions. |
| `generate_ai_summary` | `true` | Executive summary (mock unless a key is set) |
| `rewrite_findings` | `false` | AI restatement of up to ten severe findings |
| `enabled_rules` | `null` | Restrict to specific rule IDs |

Response (abridged):

```json
{
  "analysis_id": "0f2c...",
  "status": "completed",
  "record_count": 1238,
  "purchase_order_count": 578,
  "supplier_count": 55,
  "findings_count": 131,
  "critical_count": 21,
  "risk_score": 8.2,
  "total_value": 12963421.55,
  "estimated_exposure": 3472982.10,
  "base_currency": "EUR",
  "config_version": "1.0.0",
  "engine_version": "1.0.0",
  "duration_ms": 1830,
  "applied_mapping": { "EBELN": "po_number" },
  "unmapped_columns": [],
  "data_quality_issues": [],
  "rule_errors": [],
  "kpis": {
    "severity_counts": { "critical": 21, "high": 57, "medium": 42, "low": 11 },
    "category_counts": { "Duplication": 12 },
    "rule_counts": [
      { "rule_id": "PO-R020", "rule_name": "Purchase from a high-risk supplier",
        "category": "Supplier risk", "count": 29, "exposure": 483986.4 }
    ],
    "risk_score_method": "Weighted severity points per 10 line items, capped at 100.",
    "exposure_note": "Gross value of the affected lines or orders, not a confirmed loss."
  },
  "supplier_risk": [
    { "supplier_id": "0000100013", "supplier_name": "Granite Trading BV",
      "spend_base": 412300.0, "findings_count": 12, "critical_count": 2,
      "risk_points": 61, "top_risk_category": "Supplier risk" }
  ],
  "ai_narrative": {
    "available": true,
    "origin": "mock_ai",
    "provider": "mock",
    "prompt_version": "po_risk_narrative_v1.0.0",
    "summary": "The rule engine reviewed 1,238 purchase order line items ...",
    "key_risks": ["..."],
    "recommended_actions": ["..."],
    "input_tokens": 8410, "output_tokens": 1536, "estimated_cost_usd": 0.0,
    "error": null
  },
  "methodology": {
    "risk_determination": "deterministic Python rules only",
    "ai_role": "optional narrative summarisation of results that were already computed",
    "base_currency": "EUR",
    "data_disclaimer": "Results describe the uploaded file only. This application is not connected to any SAP system."
  }
}
```

Note `origin: "mock_ai"`. A client should display that label rather than presenting the text as a
model response.

---

## Findings

```bash
curl "http://127.0.0.1:8000/api/v1/po-risk/analyses/{id}/findings?severity=critical&limit=50"
```

| Parameter | Notes |
| --- | --- |
| `severity` | Repeatable: `?severity=critical&severity=high` |
| `rule_id` | e.g. `PO-R009` |
| `supplier_id` | Exact match |
| `po_number` | Exact match |
| `limit` / `offset` | Default 100 / 0; max 1000 |

```json
{
  "total": 21,
  "limit": 50,
  "offset": 0,
  "findings": [
    {
      "finding_id": "b71f...",
      "analysis_id": "0f2c...",
      "po_number": "4500123",
      "po_item": "00010",
      "supplier_id": "0000100013",
      "supplier_name": "Granite Trading BV",
      "risk_category": "Approval and governance",
      "rule_id": "PO-R009",
      "rule_name": "High value order without approval",
      "severity": "critical",
      "explanation": "Purchase order 4500123 totals 128,400.00 EUR but carries the approval status 'Not Approved' ...",
      "evidence": {
        "order_value_base": 128400.0,
        "approval_status": "Not Approved",
        "threshold_min_order_value_base": 10000.0
      },
      "recommended_action": "Confirm the release strategy was applied before the order was sent to the supplier.",
      "confidence_score": 0.95,
      "estimated_financial_exposure": 128400.0,
      "exposure_currency": "EUR",
      "output_origin": "rule_based",
      "ai_explanation": null,
      "ai_output_origin": null,
      "created_at": "2026-07-30T09:15:02Z"
    }
  ]
}
```

`evidence` always includes the threshold that was applied (`threshold_*`), so a finding can be
explained without reading the source.

`explanation` is rule-based and never overwritten. `ai_explanation` is separate and nullable.

---

## Export

```bash
curl -o report.xlsx \
  "http://127.0.0.1:8000/api/v1/po-risk/analyses/{id}/export?format=xlsx"
```

| Format | Content |
| --- | --- |
| `xlsx` | Five sheets: Summary, Findings, Supplier Risk, Methodology, Data Quality |
| `csv` | Findings table, UTF-8 with BOM for Excel |
| `json` | Full payload: analysis, findings, supplier risk, rule catalogue, disclaimer |

Every export carries the methodology and the disclaimer, so a downloaded file cannot be mistaken
for validated SAP output.

---

## Spend analysis

```bash
curl -X POST http://127.0.0.1:8000/api/v1/spend/analyze \
  -H "Content-Type: application/json" \
  -d '{
        "upload_id": "5c5562c2bb204448b41f2d67ce11c35b",
        "filters": {
          "date_from": "2025-01-01",
          "date_to": "2025-12-31",
          "category": ["IT and Telecom"]
        },
        "generate_ai_summary": true
      }'
```

| Field | Default | Meaning |
| --- | --- | --- |
| `upload_id` | required | From the upload response |
| `column_mapping_overrides` | `{}` | Source column → canonical field; `""` ignores a column |
| `filters` | `{}` | `date_from`, `date_to` plus 12 categorical fields, each a list |
| `enabled_savings_rules` | `null` | Restrict the savings engine to specific rule IDs |
| `generate_ai_summary` | `true` | Narrative (mock unless a key is set) |
| `top_n` | config default | Rows per top-N breakdown |

Filters are applied **before** every calculation, so `metrics`, `analytics`, the drill-down
endpoint and `opportunities` all describe the same slice.

Response (abridged):

```json
{
  "analysis_id": "9ac78d5b45f14fc980b6c9ec80e2412a",
  "status": "completed",
  "record_count": 3640,
  "filtered_record_count": 162,
  "period_start": "2025-01-02",
  "period_end": "2025-12-25",
  "applied_filter": { "date_from": "2025-01-01", "values": { "category": ["IT and Telecom"] } },
  "filter_options": { "category": ["Components", "Facilities"] },
  "metrics": {
    "total_spend": 2123379.44,
    "purchase_order_count": 148,
    "line_item_count": 162,
    "supplier_count": 11,
    "average_po_value": 14347.16,
    "median_po_value": 11020.5,
    "contracted_spend": 1946204.1,
    "non_contracted_spend": 177175.34,
    "maverick_spend": 121880.0,
    "maverick_spend_pct": 5.74,
    "spend_under_management": 2001499.44,
    "spend_under_management_pct": 94.26,
    "supplier_concentration_hhi": 1284.6,
    "supplier_concentration_level": "low",
    "top_supplier_share_pct": 21.4,
    "top_five_supplier_share_pct": 68.2,
    "tail_spend": 41230.9,
    "tail_spend_pct": 1.94,
    "tail_supplier_count": 4,
    "price_variance_base": 38104.2,
    "estimated_savings_opportunity": 145820.33,
    "spend_by_currency": [{ "currency": "EUR", "spend_base": 980112.4, "share_pct": 46.16 }],
    "base_currency": "EUR",
    "output_origin": "rule_based"
  },
  "analytics": {
    "monthly_spend": [
      { "dimension": "spend_month", "value": "2025-01", "spend_base": 180422.1,
        "change_vs_previous_pct": null }
    ],
    "spend_by_category": [
      { "dimension": "category", "value": "IT and Telecom", "spend_base": 2123379.44,
        "share_pct": 100.0, "transaction_count": 162 }
    ]
  },
  "opportunities": [
    {
      "opportunity_id": "SAV-01-SPM100264-007",
      "rule_id": "SAV-01",
      "title": "Harmonise the price paid for material SPM-100264",
      "method": "Target price = 25th percentile of prices paid (98.40). Gross saving = ...",
      "gross_saving_base": 78066.4,
      "realization_factor": 0.5,
      "estimated_saving_base": 39033.2,
      "confidence": 0.6,
      "is_estimate": true,
      "output_origin": "rule_based"
    }
  ],
  "methodology": { "calculation_basis": "deterministic pandas aggregation, no AI involvement" }
}
```

Note `is_estimate: true` on every opportunity, and `output_origin: "rule_based"` on both the
metrics and the opportunities. The AI narrative is a separate block.

### Drill-down

Every breakdown row carries `dimension` and `value`. Send them back to get the lines behind it:

```bash
curl "http://127.0.0.1:8000/api/v1/spend/analyses/{id}/transactions?dimension=supplier&value=0000200004&limit=100"
```

| Parameter | Notes |
| --- | --- |
| `dimension` + `value` | `supplier`, `category`, `subcategory`, `material`, `material_group`, `plant`, `company_code`, `purchasing_org`, `purchasing_group`, `currency`, `spend_month` |
| `supplier_id`, `material`, `category`, `spend_month` | Direct filters, combinable |
| `contracted`, `maverick` | Boolean filters |
| `limit` / `offset` | Default 100 / 0; max 1000 |

The response carries `total` and `total_spend_base` for the *whole* matching set, not just the
returned page, so a UI can show "showing 100 of 1,240 worth 3,227,036.93 EUR". Those totals
reconcile exactly with the breakdown they came from - two integration tests assert it.

### Savings opportunities

```bash
curl "http://127.0.0.1:8000/api/v1/spend/analyses/{id}/opportunities?rule_id=SAV-02"
```

Returns the opportunities plus `total_estimated_saving_base` and the standing `disclaimer`. A
client should display that disclaimer: presenting these figures as achieved savings would
misrepresent them.

### Spend export

| Format | Content |
| --- | --- |
| `xlsx` | Six sheets: Summary, Spend Breakdowns, Suppliers, Savings Opportunities, Transactions, Methodology |
| `csv` | The transaction table, UTF-8 with BOM |
| `json` | Full payload including the savings rule catalogue and methodology |

---

## Catalogues

`GET /api/v1/po-risk/rules` returns all 20 rules with their category, severity, confidence,
recommended action and **current thresholds** - useful for showing users what the analysis
actually applied.

`GET /api/v1/po-risk/fields` returns the 25 canonical fields with their SAP aliases and whether
they are required, which is enough to build a mapping UI without hardcoding anything.

`GET /api/v1/spend/fields` returns 33 fields - the same 25 plus the eight spend-specific ones,
each flagged with `is_spend_specific`.

`GET /api/v1/spend/savings-rules` returns each savings model with its confidence, realization
factor and full parameter set, so a UI can show users exactly which assumptions produced a number.

---

## Notes for a website front end

- **Same endpoints, no logic to port.** The Streamlit page is a thin client; a React or Next.js
  app calls the identical routes.
- **CORS** is configured from the `CORS_ORIGINS` setting; add your dev origin there.
- **No authentication yet.** The lab is local-only. See
  [`FUTURE_WEBSITE_INTEGRATION.md`](FUTURE_WEBSITE_INTEGRATION.md) before exposing it publicly.
- **Analysis is synchronous** and takes a few seconds on ~1,200 rows. For much larger files a job
  queue would be the next step.
- **Always surface `output_origin`.** Presenting `mock_ai` text as a model response - or any AI
  text as the source of a risk decision - would misrepresent how the system works.
