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
