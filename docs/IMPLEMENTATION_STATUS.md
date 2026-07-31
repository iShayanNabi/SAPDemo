# Implementation status

Last updated: 2026-07-31

---

## Summary

| | |
| --- | --- |
| Modules complete | 4 of 10 |
| Tests | 506 passing (296 unit, 129 API, 81 integration) |
| Python source | ~26,000 lines across `app/`, `streamlit_app/`, `scripts/`, `tests/` |
| Runs without SAP, keys, Docker or a paid API | Yes |

---

## Foundation - complete

Built while implementing module 1 and shared by every future module.

| Component | Location | Status |
| --- | --- | --- |
| Central configuration | `app/core/config.py` | Done - env vars, PostgreSQL-ready URL, mock AI fallback |
| Central logging | `app/core/logging.py` | Done - includes API-key redaction |
| Exception hierarchy | `app/core/exceptions.py` | Done - safe messages, status codes |
| Security helpers | `app/core/security.py` | Done - filename sanitisation, path containment, injection filtering |
| Response envelope | `app/schemas/common.py` | Done - plus the `OutputOrigin` labels |
| Database session | `app/models/session.py` | Done - SQLite now, PostgreSQL by URL change |
| Migrations | `migrations/` | Done - initial revision, upgrade and downgrade verified |
| File validation | `app/services/files/validation.py` | Done - extension, size, magic bytes |
| File readers | `app/services/files/readers.py` | Done - CSV (delimiter sniffing), XLSX, JSON |
| Upload storage | `app/services/files/storage.py` | Done - safe paths, unique names |
| AI abstraction | `app/services/ai/` | Done - mock, Anthropic, OpenAI; retries, timeouts, cost tracking |
| Prompt versioning | `app/services/ai/prompts.py` | Done - versioned, untrusted-data wrapping |
| Export builders | `app/services/exports/report_builder.py` | Done - xlsx, csv, json |
| FastAPI app | `app/main.py`, `app/api/v1/` | Done - CORS, request IDs, exception handlers |
| Streamlit shell | `streamlit_app/` | Done - API client, shared UI helpers |
| Test harness | `tests/conftest.py`, `tests/factories.py` | Done - isolated database and directories |
| Shared tabular services | `app/services/tabular/` | Done - field registry, column mapping, parsing (extracted during module 2) |

---

## Module 1 - Purchase Order Risk Checker - complete

### Requirements

| Requirement | Status |
| --- | --- |
| CSV, XLSX, JSON upload | Done |
| 25 normalised fields | Done - `field_definitions.py` |
| SAP aliases (EBELN, EBELP, LIFNR, MATNR, MATKL, BUKRS, EKORG, EKGRP, WERKS, MENGE, MEINS, NETPR, WAERS) | Done, plus business-label and typo variants |
| 11-step workflow | Done - upload → validation → preview → auto mapping → manual correction → type validation → missing-data warnings → analysis → dashboard → findings → export |
| 20 risk rules | Done - PO-R001 to PO-R020 |
| Thresholds in configuration, not code | Done - `config/po_risk_rules.json`, proven by test |
| Full finding structure | Done - 14 fields including evidence and exposure |
| Four severity levels | Done - low, medium, high, critical, with value-band escalation |
| Rule-based risk determination | Done - AI never decides risk |
| Optional AI narrative, clearly labelled | Done - separate fields, `mock_ai`/`ai_generated` origin |
| Mock AI works with no key | Done - and is the default |
| Six required API routes | Done, plus rules, fields, sample, sample/info, ai-status |
| Streamlit page with all 14 required elements | Done |
| ≥500 POs, ≥1,000 items, ≥50 suppliers | Done - 578 / 1,238 / 55 |
| Documented anomalies for every rule | Done - 89 anomalies, all 20 rules |
| Unit tests per rule | Done - 58 rule tests |
| API and integration tests | Done - 45 + 35 |

### Files

```text
app/modules/po_risk/
  field_definitions.py    25 canonical fields and their SAP aliases
  column_mapping.py       three-strategy matching, overrides, validation
  normalizer.py           type coercion, base currency, data-quality issues
  thresholds.py           Pydantic-validated configuration loader
  engine.py               rule execution, isolation, aggregation
  ai_narrative.py         optional AI layer
  service.py              orchestration and persistence
  config/po_risk_rules.json
  rules/                  base.py + 7 modules holding the 20 rules
```

### Verification performed

- Full suite: 217 passed in ~25 s.
- Live `uvicorn` run: health, CSV and XLSX upload, analyse (131 findings, risk 8.2), Excel export
  (42 KB, HTTP 200), all 13 OpenAPI paths present.
- Both Streamlit pages executed without exceptions.
- Alembic `upgrade head` then `downgrade base` on a scratch database.
- `scripts/verify_setup.py` exits 0.

### Bugs found and fixed during the build

| Bug | Found by | Fix |
| --- | --- | --- |
| `parse_number("12 EUR")` returned `None` | Unit test | Extract the first numeric token instead of stripping characters |
| Large prompt payloads truncated mid-JSON, so the mock summary reported zeros | **Manual API run, not the tests** | Sanitise values individually and drop whole list entries; regression test added |
| Sample generator compared values in document currency while rules use base currency | Manifest coverage check | Added `_po_total_base()` and used it in every guard |
| Injections overwrote each other, so some documented anomalies were not detected | Manifest coverage check | Row-locking in the generator |
| Multi-line generated orders looked like duplicated items | Manifest coverage check | Uneven line weights |

---

## Module 2 - Spend Analytics Dashboard - complete

### Requirements

| Requirement | Status |
| --- | --- |
| CSV, XLSX, JSON upload | Done |
| Reuse purchase order fields | Done - the 25 PO fields are inherited, not redefined |
| 8 added fields (transaction date, category, subcategory, contract status, preferred supplier status, baseline price, current price, payment status) | Done |
| 18 required metrics | Done - all deterministic, all in base currency |
| 13 filters | Done - applied once, before every calculation |
| 13+ analytics breakdowns | Done - 15 produced |
| Drill from summaries into transactions | Done - every breakdown row carries `dimension`/`value` |
| 6 configurable savings models | Done - SAV-01 to SAV-06 |
| Savings never presented as guaranteed | Done - `is_estimate`, realization factor, `method` field, disclaimers in API, export and UI |
| 6 required API routes | Done, plus fields, savings-rules, methodology, sample, sample/info |
| Streamlit page with all 10 required elements | Done |
| 24+ months of sample data | Done - 24 months, 3,640 transactions |
| Controlled examples of all 6 conditions | Done - 8 documented scenarios |
| Tests for aggregation, filtering, contracted vs non-contracted, maverick, concentration, tail, variance, savings, API, export | Done - 177 new tests |

### Files created

```text
app/modules/spend/
  field_definitions.py    PO fields + 8 spend fields, alias conflict resolved
  thresholds.py           Pydantic-validated configuration loader
  normalizer.py           derived columns and classification
  filters.py              the single filter applied everywhere
  metrics.py              18 headline metrics
  analytics.py            15 breakdowns with drill-down keys
  savings.py              6 savings models + isolation engine
  ai_narrative.py         optional narrative layer
  service.py              orchestration and persistence
  config/spend_rules.json every threshold and assumption

app/api/v1/spend.py                       12 routes
app/models/spend.py                       3 tables
app/schemas/spend.py                      request/response contract
app/services/exports/spend_report_builder.py   6-sheet XLSX, CSV, JSON
app/services/tabular/                     shared registry, mapping, parsing
streamlit_app/pages/2_Spend_Analytics.py
scripts/generate_spend_sample_data.py
tests/unit/test_spend_metrics.py, tests/unit/test_spend_savings.py
tests/api/test_spend_api.py
tests/integration/test_spend_sample_data.py
migrations/versions/3c761d0c43df_spend_analytics_schema.py
```

### Files modified

`app/api/v1/router.py`, `app/main.py`, `app/models/__init__.py`, `app/models/session.py`,
`app/services/ai/prompts.py`, `app/services/ai/mock_provider.py`,
`app/modules/po_risk/{field_definitions,column_mapping,normalizer}.py` (delegate to the shared
services), `app/modules/po_risk/rules/pricing.py`, `streamlit_app/Home.py`,
`streamlit_app/components/api_client.py`, `scripts/verify_setup.py`, `tests/conftest.py`,
`tests/factories.py`, and the documentation set.

### Verification performed

- Full suite: 394 passed in ~60 s. The 217 module 1 tests passed unmodified after the shared-code
  refactor.
- Live `uvicorn` run: upload, analyse (44.9M EUR over 24 months), filtered analyse, drill-down,
  opportunities, and all three export formats.
- Drill-down totals reconciled against the supplier roll-up to the cent.
- Alembic `upgrade head` → `downgrade -1` → `upgrade head` on a scratch database.
- Fresh-database check confirming all 7 tables are created.
- All three Streamlit pages executed without exceptions.
- `scripts/verify_setup.py` exits 0 and reports both datasets.

### Bugs found and fixed during the build

| Bug | Found by | Fix |
| --- | --- | --- |
| Drill-down and opportunity totals were multiplied by a cartesian product (329M EUR reported for 7 transactions) | **Manual API run, not the tests** | Aggregate over the subquery's columns; reconciliation tests added |
| `frame_to_records` had a missing `datetime` import and *no callers* - dead code from module 1 | Refactor + pyflakes | Moved into the shared parsing layer where the spend module uses it |
| `init_db()` imported only `app.models.po_risk`, so a fresh database would have been missing the spend tables | pyflakes | Import the `app.models` package instead |
| Sample generator never produced material group MG15, so one scenario silently vanished | Scenario count check | `groups[(index // len(CATEGORIES)) % len(groups)]` |
| `CATEGORY` resolved to `material_group`, wrong for a spend cube | Design review | Spend registry strips the ambiguous alias |


---

## Module 3 - Supplier Recommendation Engine - complete

### Requirements

| Requirement | Status |
| --- | --- |
| Requirement input (16 fields) | Done - `RequirementSchema` |
| Supplier data (18 fields + currency) | Done - `field_definitions.py`, reuses the shared registry |
| CSV, XLSX, JSON supplier upload | Done - into a persisted catalogue |
| 9 separate normalized scores | Done - cost, delivery, quality, capacity, risk, ESG, contract, geographic, past performance |
| User-modifiable weights, validated to 100% | Done - rejected with a 422 otherwise |
| Documented scoring formulas | Done - `GET /supplier-recommendations/scoring` and the config file |
| Eligibility filters applied before ranking | Done - 7 filters, each with a reason |
| Full result structure (rank, scores, cost, delivery, advantages, risks, explanation) | Done |
| AI summarises but never determines the ranking | Done - deterministic engine, separate narrative fields |
| 4 required API routes | Done, plus fields, catalogs, scoring, sample, sample/info, ai-status, export, list |
| Streamlit page with all 10 required elements | Done |
| >=50 varied sample suppliers | Done - 55 with 7 documented anchors |
| Tests: eligibility, weights, normalization, ranking, cost, lead-time, contract, risk tolerance, determinism, API | Done - 62 new tests |

### Files created

```text
app/modules/supplier_reco/
  field_definitions.py    19 supplier fields, reuses the shared registry
  thresholds.py           Pydantic-validated configuration loader + Weights
  requirement.py          the purchasing requirement dataclass
  normalizer.py           list splitting, base currency, canonical records
  eligibility.py          the 7 hard constraints, each with a reason
  scoring.py              the 9 normalized scores + weighted overall
  engine.py               eligibility -> scoring -> ranking -> advantages/risks/explanation
  ai_narrative.py         optional narrative layer
  service.py              orchestration and persistence
  config/supplier_reco_rules.json every weight, formula and threshold

app/api/v1/supplier_reco.py               two routers (suppliers, supplier-recommendations)
app/models/supplier_reco.py               4 tables
app/schemas/supplier_reco.py              request/response contract
app/services/exports/supplier_reco_report_builder.py   5-sheet XLSX, CSV, JSON
streamlit_app/pages/3_Supplier_Recommendations.py
scripts/generate_supplier_sample_data.py
tests/unit/test_supplier_scoring.py, tests/unit/test_supplier_eligibility.py
tests/api/test_supplier_reco_api.py
tests/integration/test_supplier_sample_data.py
migrations/versions/a16bad79dd24_supplier_recommendation_schema.py
```

### Verification performed

- Full suite: 456 passed. The 394 module 1+2 tests passed unchanged.
- Live `uvicorn` run: health, supplier upload (55 suppliers), list, detail, recommend (30/55
  eligible), weight-validation 422, get, all three exports, scoring, ai-status (no key leak).
- The canonical-requirement ranking reproduces `expected_supplier_baseline.json` exactly through
  HTTP, and repeated runs are byte-identical.
- Alembic `upgrade head` -> `downgrade -1` -> `upgrade head` on a scratch database; all 11 tables
  created on a fresh database.

### Bugs found and fixed during the build

| Bug | Found by | Fix |
| --- | --- | --- |
| The generator's recorded baseline disagreed with the API: contract status `"None"` is nulled by the file reader on the CSV round-trip, so it scored `unknown` (40) via the API but `none` (20) in the in-memory baseline | **Baseline reproduction check, not the unit tests** | Use the label `"No contract"`, and compute the baseline by reading the written file back through the real reader/normaliser |

---

## Module 4 - Invoice Validator - complete

### Requirements

| Requirement | Status |
| --- | --- |
| Separate uploads for invoices, purchase orders, goods receipts | Done - one `/invoices/upload` endpoint with a `dataset` field |
| CSV, XLSX, JSON for each dataset | Done |
| 16 invoice fields, 7 goods-receipt fields | Done - `field_definitions.py` |
| Reuse the purchase-order model | Done - the 25 PO fields are inherited and extended with `po_status` |
| 17 validation rules | Done - IV-R001 to IV-R017 |
| Configurable tolerances (price, quantity, tax, freight) | Done - in config and overridable per run, proven by test |
| Full exception structure | Done - 14 output fields including expected/actual/difference |
| Four severity levels with value-band escalation | Done |
| Deterministic validation, AI only summarises | Done - AI never decides an exception |
| Five required API routes | Done, plus validations list, fields, rules, sample, sample/info, ai-status |
| Streamlit page with all required elements | Done - three uploads, previews, mapping, tolerances, charts, exception table, three-way comparison, filters, export |
| >=400 invoices, >=300 goods receipts, PO records | Done - 420 / 417 / 418 |
| Controlled example of every rule | Done - 17 documented anchors, one per rule |
| Tests for every rule, mapping, tolerance, endpoint, export | Done - 50 new tests |

### Files created

```text
app/modules/invoice_validator/
  field_definitions.py    invoice (16) + goods receipt (7) registries; reuses the PO registry
  thresholds.py           Pydantic-validated configuration loader + tolerances
  normalizer.py           three normalisers -> canonical records
  matching.py             the join indexes and the MatchContext handed to every rule
  engine.py               rule execution, isolation, aggregation, three-way-match rows
  ai_narrative.py         optional narrative layer
  service.py              orchestration and persistence over three uploads
  config/invoice_validator_rules.json
  rules/                  base.py + 5 modules holding the 17 rules

app/api/v1/invoice_validator.py              one router, 11 routes
app/models/invoice_validator.py              2 tables
app/schemas/invoice_validator.py             request/response contract
app/services/exports/invoice_validator_report_builder.py   5-sheet XLSX, CSV, JSON
streamlit_app/pages/4_Invoice_Validator.py
scripts/generate_invoice_sample_data.py
tests/unit/test_invoice_rules.py, tests/api/test_invoice_validator_api.py
tests/integration/test_invoice_sample_data.py
migrations/versions/aa9af98480ef_invoice_validator_schema.py
```

### Files modified

`app/api/v1/router.py`, `app/main.py`, `app/models/__init__.py`,
`app/services/ai/prompts.py`, `app/services/ai/mock_provider.py`,
`streamlit_app/Home.py`, `streamlit_app/components/api_client.py`, `scripts/verify_setup.py`,
`tests/conftest.py`, `tests/factories.py`, and the documentation set.

### Verification performed

- Full suite: 506 passed. The 456 module 1-3 tests passed unchanged.
- Live `uvicorn` run: three uploads, validate (17 exceptions over 420 invoices, 418 matched),
  AI narrative (mock, accurate, labelled), get, filtered exceptions, all three exports, fields,
  rules, sample download.
- The sample run reproduces `expected_invoice_baseline.json` exactly through HTTP, only the 17
  anchor invoices are flagged, and repeated runs are identical.
- Alembic `upgrade head` -> `downgrade -1` -> `upgrade head` on a scratch database, and an
  autogenerate diff confirmed the migration matches the models.

### Design notes carried forward

- **Joining three files, not one.** The invoice file is mandatory; the PO and GR files are optional,
  and any rule that needs a missing dataset is reported as skipped (in `rule_executions`) rather than
  silently producing nothing or flagging everything.
- **Rule separation to avoid double-counting.** Quantity mismatch (IV-R006) compares billed vs
  received; the three-way rule (IV-R012) compares billed vs *accepted* (received minus rejected);
  overbilling (IV-R013) is the cumulative billed vs ordered. Value-based overbilling only applies
  when a line has no ordered quantity, so a price mismatch does not also read as overbilling.
- **Deterministic sample baseline.** The baseline is computed by reading the written CSVs back
  through the real reader and normalisers (the same lesson as module 3), so it is exactly what the
  API produces. The future-invoice-date rule uses a fixed reference date recorded in the manifest,
  keeping the baseline reproducible.

---

## Modules 5-10 - not started

No code exists for these yet. Nothing has been stubbed, and there are no placeholder pages or
non-functional buttons.

| # | Module | Deterministic part | AI part |
| --- | --- | --- | --- |
| 5 | Supplier Risk Copilot | Metric retrieval | Question answering over retrieved facts |
| 6 | Contract Assistant | Document parsing | Clause extraction, summarisation |
| 7 | Inventory Predictor | Statistical forecasting (statsmodels) | Explaining a forecast |
| 8 | SAP Test Case Generator | Template and coverage checks | Test case drafting |
| 9 | SAP Blueprint Generator | Structure validation | Blueprint drafting |
| 10 | SAP Interview Coach | Question bank, scoring rubric | Feedback on an answer |

Each will reuse the foundation rather than duplicate it. Estimated effort per module is smaller
than module 1, because the shared layers already exist.

---

## Known limitations

**Module 1**

- Analysis is synchronous; very large files would need a job queue.
- Currency conversion uses fixed rates from the configuration file, not live rates.
- The high-risk supplier list is configuration, not an external risk feed.
- Duplicate detection uses exact material and near-equal value matching, not fuzzy description
  matching.
- PO-R018 concentration uses spend share within a material group; it does not model
  sole-source justification, which can be legitimate.

**Module 2**

- Savings figures are modelled estimates. The assumptions (saving rates, realization factors,
  transaction handling cost) are planning defaults, not measured values from any organisation.
- Supplier consolidation does not test technical qualification, which is often the real constraint.
- Preferred-supplier migration assumes the cheaper supplier can absorb the volume at the same price.
- Currency conversion uses fixed configured rates, not rates at the transaction date.
- Analysis is synchronous; a multi-million-row spend cube would need a job queue.
- Tail classification is pure Pareto; it does not consider strategic importance.

**Module 3**

- Relative scores (cost, lead time, capacity when no quantity is given, past performance) are
  min-max normalised across the *eligible pool*, so adding or removing a supplier can shift the
  scores of the others. This is transparent and documented, but it means a score is a
  within-shortlist comparison, not an absolute rating.
- Missing supplier attributes score 0 (conservative). A supplier that simply did not report a
  field is penalised as if it were the worst.
- Estimated costs and delivery dates are indicative planning figures from the supplier data, not
  quotations; the estimated delivery date needs a planned order date to be computed.
- The supplier catalogue is global and unversioned beyond the upload; a recommendation references a
  catalogue by id but does not snapshot it.
- Currency conversion uses fixed configured rates.

**Module 4**

- The tax rule assumes a single expected tax rate (configurable) for every line; it does not model
  mixed-rate or zero-rated invoices per material or country.
- The freight rule uses a policy ceiling, not a freight amount agreed on the purchase order (POs in
  this lab do not carry a freight field).
- Quantity mismatch compares an invoice against the *total* received quantity for a line; it does not
  model per-delivery invoicing schedules, so heavily split deliveries would need a GR per invoice.
- Matching joins on PO number + item only; it does not fuzzy-match on material or description when
  the PO reference is absent or wrong.
- Currency conversion uses fixed configured rates.
- Validation is synchronous; very large invoice runs would need a job queue.

**Project-wide**

- No authentication or authorisation - the lab is local-only.
- No rate limiting.
- The Streamlit UI has no automated browser tests.
- PostgreSQL is supported by configuration but not exercised in CI.
- Real AI providers are implemented but not covered by automated tests (by design: the suite runs
  without keys).
- Uploaded files are stored unencrypted in `data/uploads/`.

---

## Recommended next step

**Module 5 - Supplier Risk Copilot.** With four procurement modules now sharing one database, the
copilot is the natural next step: it retrieves supplier metrics deterministically and uses AI only
to answer questions over the retrieved facts (retrieval-grounded question answering), which is a new
shape for the lab - the AI reads structured facts rather than only summarising a finished analysis.

Worth weighing against building the next module: the operational work listed under limitations -
authentication, a job queue, and a PostgreSQL run. Four modules now share one database and one
upload table, so the cost of adding authentication grows with each module rather than staying flat.
