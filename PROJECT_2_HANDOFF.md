# Project 2 Handoff

**SAP AI Application Lab** — state of the repository after Project 2.

Packaged: 2026-07-31 · Tests: **394 passing** · Modules complete: **2 of 10**

---

## 1. Completed modules

### Shared foundation

Built during Project 1 and extended during Project 2. Every future module uses this.

| Component | Location | Purpose |
| --- | --- | --- |
| Central configuration | `app/core/config.py` | Env vars, PostgreSQL-ready URL, mock-AI fallback |
| Central logging | `app/core/logging.py` | Includes API-key redaction filter |
| Exception hierarchy | `app/core/exceptions.py` | Safe messages, mapped status codes |
| Security helpers | `app/core/security.py` | Filename sanitisation, path containment, prompt-injection filtering |
| Response envelope | `app/schemas/common.py` | `ApiResponse`, `OutputOrigin`, `Severity` |
| **Tabular services** | `app/services/tabular/` | Field registry, column mapping, parsing — **new in Project 2** |
| File services | `app/services/files/` | Validation (extension, size, magic bytes), readers, storage |
| AI abstraction | `app/services/ai/` | Mock / Anthropic / OpenAI, versioned prompts, retries, cost tracking |
| Export builders | `app/services/exports/` | XLSX, CSV, JSON for both modules |
| Database | `app/models/`, `migrations/` | SQLite now, PostgreSQL by URL change |

### Module 1 — Purchase Order Risk Checker

Upload an SAP-style PO extract; get transparent, rule-based risk findings; export a report.

- 25 canonical fields with SAP aliases (`EBELN`, `LIFNR`, `MENGE`, `NETPR`, …)
- **20 deterministic rules** (PO-R001…PO-R020) across duplication, splitting, pricing, contracts, approvals, delivery, data quality and supplier risk
- Severity low/medium/high/critical with configurable value-band escalation
- 13 API routes · Streamlit page · 1,238-row demo dataset with **89 documented anomalies**

### Module 2 — Spend Analytics Dashboard

Upload procurement transactions; analyse spend; filter; drill into any figure; review modelled savings.

- Inherits module 1's 25 fields, adds 8 (transaction date, category, subcategory, contract status, preferred supplier status, baseline price, current price, payment status)
- **18 metrics** — total/contracted/non-contracted/maverick spend, spend under management, HHI concentration, top-1 and top-5 share, tail spend, price variance, estimated savings, spend by currency, PO/line/supplier counts, average and median PO value
- **13 filters** applied once, before every calculation
- **15 analytics breakdowns**, each carrying `dimension`/`value` for drill-down
- **6 configurable savings models** (SAV-01…SAV-06)
- 12 API routes · Streamlit page · 3,640-transaction / 24-month dataset with **8 documented scenarios**

---

## 2. Important architectural decisions

### Deterministic logic decides; AI only describes

No figure in either module comes from a model. Rules and metrics are ordinary Python; AI writes prose *about* results that already exist, in separate fields, labelled with an `OutputOrigin`. An AI failure degrades to an error string and never fails an analysis.

**Mock AI is the default** whenever no key is configured, so the lab always runs offline.

### Thresholds live in configuration, not code

`app/modules/po_risk/config/po_risk_rules.json` and `app/modules/spend/config/spend_rules.json` hold every threshold, classification list and savings assumption, validated by Pydantic at load. Both modules have a test proving a JSON edit changes the outcome with no code change.

### Base-currency conversion before every comparison

Both modules convert to a configured base currency before aggregating or comparing, so a mixed-currency dataset behaves correctly. Rates are in the config files.

### Savings are models, never promises

Every `SavingsOpportunity` carries `is_estimate: true`, a `realization_factor`, and a `method` string stating its arithmetic in words so a category manager can check the number instead of trusting it. The disclaimer appears in the API response, the red XLSX header and the UI.

### One filter, applied once

`apply_filter()` runs before metrics, analytics and savings. This is why a filtered dashboard cannot show a KPI that disagrees with its own chart — and two integration tests assert that reconciliation.

### Streamlit is disposable

Pages import only an HTTP client and formatting helpers. Deleting `streamlit_app/` would not break a single test. A React front end calls the same endpoints and receives the same JSON.

### Rule and model isolation

Engines wrap each rule in `try/except`; one failure lands in `rule_errors` / `savings_errors` and the rest still return results.

---

## 3. Shared tabular services (new in Project 2)

Module 2 was the first real test of whether the foundation was reusable. Copying the column mapper would have been the easy path; extracting it was the right one.

```
app/services/tabular/
  field_registry.py   FieldRegistry: names, required fields, alias lookup,
                      .extend(), .with_required()
  mapping.py          three-strategy matcher (exact alias 1.00 → token
                      containment 0.80 → fuzzy ≥0.82), registry-driven
  parsing.py          parse_number, parse_date, parse_boolean, parse_string,
                      coerce_types, check_required_completeness,
                      build_canonical_frame, frame_to_records
```

`app/modules/po_risk/column_mapping.py` became a thin binding of the shared matcher to the PO registry. **Its public API did not change and all 217 module 1 tests passed unmodified** — the only evidence worth having that a refactor was safe.

### How module 2 inherits the contract

```python
REGISTRY = FieldRegistry(
    _po_fields_for_spend() + SPEND_SPECIFIC_FIELDS
).with_required(BASE_REQUIRED_FIELDS)
```

**Alias conflicts matter.** Aliases resolve with `setdefault`, so declaration order wins. In an ME2N export `CATEGORY` labels the *material group*; in a spend cube it means the *procurement category*. `_po_fields_for_spend()` strips the ambiguous alias so it lands where a spend analyst expects.

**Requirements differ by module.** Risk rules need document keys, quantity, price and date. Spend needs less: a document number, a supplier, *a* date (transaction or order) and *a* value basis (a total, or quantity × price). Expressed in `_missing_requirements()` rather than forcing one rigid list on both.

The payoff is tested: `test_po_risk_sample_file_also_works_here` uploads **module 1's sample file to module 2's endpoint** and gets a valid analysis.

---

## 4. API routes

Base: `/api/v1` · Envelope: `{success, data, error, meta}` · Docs: `/docs`

### System
| Method | Path |
| --- | --- |
| GET | `/` — module index |
| GET | `/api/v1/health` |

### Purchase Order Risk Checker (13)
| Method | Path |
| --- | --- |
| POST | `/api/v1/po-risk/upload` |
| POST | `/api/v1/po-risk/analyze` |
| GET | `/api/v1/po-risk/analyses` |
| GET | `/api/v1/po-risk/analyses/{id}` |
| GET | `/api/v1/po-risk/analyses/{id}/findings` |
| GET | `/api/v1/po-risk/analyses/{id}/export` |
| GET | `/api/v1/po-risk/rules` |
| GET | `/api/v1/po-risk/fields` |
| GET | `/api/v1/po-risk/sample` · `/sample/info` |
| GET | `/api/v1/po-risk/ai-status` |

### Spend Analytics Dashboard (12)
| Method | Path |
| --- | --- |
| POST | `/api/v1/spend/upload` |
| POST | `/api/v1/spend/analyze` |
| GET | `/api/v1/spend/analyses` |
| GET | `/api/v1/spend/analyses/{id}` |
| GET | `/api/v1/spend/analyses/{id}/transactions` — drill-down |
| GET | `/api/v1/spend/analyses/{id}/opportunities` |
| GET | `/api/v1/spend/analyses/{id}/export` |
| GET | `/api/v1/spend/fields` |
| GET | `/api/v1/spend/savings-rules` |
| GET | `/api/v1/spend/methodology` |
| GET | `/api/v1/spend/sample` · `/sample/info` |

**25 paths total** in the OpenAPI schema.

---

## 5. Database changes

Seven tables across two Alembic revisions.

| Revision | Tables |
| --- | --- |
| `02d5339cd4ee` initial po risk schema | `uploaded_files`, `po_analyses`, `po_records`, `po_findings` |
| `3c761d0c43df` spend analytics schema | `spend_analyses`, `spend_transactions`, `spend_opportunities` |

- `uploaded_files` is **shared** and carries a `module` column (`po_risk` / `spend`).
- `spend_transactions` is indexed on `(analysis_id, supplier_id)`, `(analysis_id, spend_month)` and `(analysis_id, category)` so drill-down is a single indexed query rather than a re-read of the source file.
- `spend_opportunities.is_estimate` defaults to `True` and is never written as `False`.
- Batch mode is enabled so migrations run on SQLite; `upgrade head → downgrade -1 → upgrade head` was verified.
- Alembic scripts live in **`migrations/`** (`alembic.ini` sets `script_location = migrations`). There is no `alembic/` directory.

---

## 6. Test results

```
394 passed in ~60s
```

| Layer | Count | Covers |
| --- | --- | --- |
| `tests/unit` | 239 | 20 risk rules, 18 metrics, 6 savings models, mapping, parsing, security, AI abstraction, engines, configuration |
| `tests/api` | 95 | Both modules' endpoints, validation, filters, drill-down, all export formats |
| `tests/integration` | 60 | Both manifests end-to-end, format equivalence, reconciliation, baselines |

Coverage of `app/`: see the coverage summary printed at packaging time.

Runs with **no network and no API key** — the mock provider is the default and each session gets a throwaway SQLite database and upload directory.

### Bugs found during Project 2

| Bug | Found by |
| --- | --- |
| Drill-down aggregate referenced the outer table, producing a cartesian product — **329,444,859 EUR reported for 7 transactions** | **Manual API run, not the tests** |
| `frame_to_records` had a missing `datetime` import *and zero callers* — dead code from module 1 | Refactor + pyflakes |
| `init_db()` imported only `app.models.po_risk`, so a fresh database would have lacked the spend tables | pyflakes |
| Sample generator never produced material group `MG15`, silently dropping a scenario | Scenario count check |
| `CATEGORY` resolved to `material_group`, wrong for a spend cube | Design review |

The first is the one to remember: **every unit test passed**, because the bug lived in a query the unit tests never ran. Reconciliation tests now exist that would have caught it.

---

## 7. Known limitations

### Project-wide
- **No authentication or authorisation.** `GET /analyses` returns every analysis to any caller. Local-only by design; this becomes a data leak the moment there is more than one user.
- No rate limiting or upload quotas.
- Analyses run **synchronously** inside the request; large files would exceed sensible HTTP timeouts.
- Uploaded files are stored unencrypted on local disk.
- Streamlit pages have **no browser-level tests** — verified only to execute without exceptions.
- PostgreSQL is supported by configuration but **not exercised in CI** (SQLite only).
- Real AI providers are implemented but not covered by automated tests, by design.

### Module 1
- Fixed FX rates from configuration, not live rates.
- High-risk supplier list is configuration, not an external risk feed.
- Duplicate detection uses exact material and near-equal value matching, not fuzzy description matching.

### Module 2
- **Savings assumptions are planning defaults, not measured values.** The 8% contract-compliance rate, the 45 EUR transaction handling cost and the realization factors are configurable guesses. The tests prove the arithmetic is correct and configurable; whether those rates are achievable is a commercial question no test can answer.
- Supplier consolidation does not test technical qualification, usually the real constraint.
- Preferred-supplier migration assumes the cheaper supplier absorbs the volume at the same price.
- Currency conversion uses configured rates, not rates at the transaction date.
- Tail classification is pure Pareto and ignores strategic importance.

---

## 8. What the next module should reuse

**Reuse, do not reimplement:**

| Need | Use | Notes |
| --- | --- | --- |
| Field contract | `app/services/tabular/field_registry.py` | `FieldRegistry(...).extend(...).with_required(...)`. Check alias conflicts. |
| Column mapping | `app/services/tabular/mapping.py` | `suggest_mapping(cols, registry)`, `validate_mapping`, `merge_mapping` |
| Parsing / coercion | `app/services/tabular/parsing.py` | `coerce_types`, `build_canonical_frame`, `frame_to_records` |
| File handling | `app/services/files/` | Validation, CSV/XLSX/JSON readers, safe storage |
| AI | `app/services/ai/` | Add a prompt builder + a mock task branch; mock stays default |
| Exports | `app/services/exports/` | Follow `spend_report_builder.py` as the newer pattern |
| Config pattern | Either module's `thresholds.py` + `config/*.json` | Pydantic-validated, no hardcoded thresholds |
| Response envelope | `app/schemas/common.py::ApiResponse` | |
| Upload table | `app.models.po_risk.UploadedFile` | Set `module="<your module>"` |
| Test harness | `tests/conftest.py`, `tests/factories.py` | Add a `<module>_config` fixture and row factories |

**Checklist for a new module:**

1. `app/modules/<name>/` with `config/<name>_rules.json` and `thresholds.py`
2. `app/models/<name>.py` — export from `app/models/__init__.py`, add an Alembic revision
3. `app/schemas/<name>.py`, `app/api/v1/<name>.py`, register in `router.py` and the `/` index
4. `streamlit_app/pages/<n>_<Name>.py` — HTTP only
5. `scripts/generate_<name>_sample_data.py` — seeded, with a manifest and a baseline
6. Tests in all three layers; integration tests read the manifest
7. Update `README.md`, `docs/IMPLEMENTATION_STATUS.md`, `CLAUDE.md`
8. **Start the server and exercise the endpoints by hand before declaring it done**

### Recommended next module

**Module 4 — Invoice Validator.** Three-way matching reuses the purchase order contract a third time and adds a genuinely new capability: joining *two* uploaded files rather than analysing one. That is the next real test of the foundation.

**Module 3 — Supplier Recommendation Engine** is the cheaper alternative: it consumes the supplier roll-up module 2 already produces, and weighted scoring is straightforwardly deterministic.

Worth weighing against both: two modules now share one database and one upload table, so the cost of retrofitting authentication grows with every module rather than staying flat.

---

## 9. Verification commands

```bash
# from the unpacked repository root
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python scripts/generate_sample_data.py
python scripts/generate_spend_sample_data.py
python scripts/verify_setup.py            # exits 0

pytest -q                                 # 394 passed

alembic upgrade head

uvicorn app.main:app --reload             # http://127.0.0.1:8000/docs
streamlit run streamlit_app/Home.py       # http://localhost:8501
```

Sample files ship inside the archive, so the generator scripts are only needed if you want to
regenerate or retune them.
