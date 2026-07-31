# Implementation status

Last updated: 2026-07-31

---

## Summary

| | |
| --- | --- |
| Modules complete | 2 of 10 |
| Tests | 394 passing (239 unit, 95 API, 60 integration) |
| Python source | ~18,000 lines across `app/`, `streamlit_app/`, `scripts/`, `tests/` |
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

## Modules 3-10 - not started

No code exists for these yet. Nothing has been stubbed, and there are no placeholder pages or
non-functional buttons.

| # | Module | Deterministic part | AI part |
| --- | --- | --- | --- |
| 3 | Supplier Recommendation Engine | Weighted scoring, ranking | Explaining a ranking |
| 4 | Invoice Validator | Three-way match, tolerances | Explaining a mismatch |
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

**Module 4 - Invoice Validator.** Three-way matching reuses the purchase order contract a third
time and adds a genuinely new capability: joining two uploaded files rather than analysing one.
That is the next real test of the foundation, and it is the natural companion to modules 1 and 2 in
a procurement story.

**Module 3 (Supplier Recommendation Engine)** is the alternative: it consumes the supplier roll-up
module 2 already produces, so it is the cheaper build. Weighted scoring and ranking are
deterministic; AI would only explain a ranking.

Worth weighing against both: the operational work listed under limitations - authentication, a job
queue, and a PostgreSQL run. Two modules now share one database and one upload table, so the cost
of adding authentication grows with each module rather than staying flat.
