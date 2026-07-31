# Architecture

How the lab is put together, why, and where each kind of code belongs.

---

## 1. Layers

Each layer may only call the one below it. Nothing calls upward.

```text
┌──────────────────────────────────────────────────────────────────┐
│ Presentation      streamlit_app/   (temporary; a website later)  │
│                   Talks HTTP only. Zero business logic.          │
├──────────────────────────────────────────────────────────────────┤
│ API               app/api/v1/      Routes, status codes,         │
│                   dependency wiring. No calculations.            │
├──────────────────────────────────────────────────────────────────┤
│ Module logic      app/modules/po_risk/                           │
│                   service.py, engine.py, rules/ (20 rules),      │
│                   normalizer.py, thresholds.py, ai_narrative.py  │
│                                                                  │
│                   app/modules/spend/                             │
│                   service.py   orchestration                     │
│                   metrics.py   deterministic KPIs                │
│                   analytics.py breakdowns for charts/drill-down  │
│                   filters.py   one filter applied everywhere     │
│                   savings.py   6 configurable savings models     │
│                   normalizer.py, thresholds.py, ai_narrative.py  │
│                                                                  │
│                   app/modules/supplier_reco/                     │
│                   eligibility.py, scoring.py, engine.py          │
│                                                                  │
│                   app/modules/invoice_validator/                 │
│                   matching.py, engine.py, rules/ (17 rules)      │
│                                                                  │
│                   app/modules/supplier_risk/                     │
│                   app/modules/contract_assistant/                │
│                   scoring.py  metric -> category -> overall      │
│                   engine.py   assessment, trend, actions         │
│                   copilot.py  deterministic Q&A with citations   │
│                   normalizer.py, thresholds.py, ai_narrative.py  │
│                                                                  │
│                   app/modules/inventory/                         │
│                   periods.py     frequency inference, grids      │
│                   forecasting.py the 5 statistical models        │
│                   accuracy.py    MAE/RMSE/MAPE/sMAPE/MASE        │
│                   selection.py   backtesting, eligibility        │
│                   projection.py  stock walk, reorder policy      │
│                   engine.py      per-series orchestration        │
│                   normalizer.py, thresholds.py, ai_narrative.py  │
├──────────────────────────────────────────────────────────────────┤
│ Shared services   app/services/                                  │
│                   tabular/ field registry, mapping, parsing      │
│                   files/ validation, readers, storage            │
│                   exports/ xlsx, csv, json builders              │
│                   ai/ provider abstraction, prompts              │
├──────────────────────────────────────────────────────────────────┤
│ Data & contracts  app/models/ (SQLAlchemy)                       │
│                   app/schemas/ (Pydantic)                        │
├──────────────────────────────────────────────────────────────────┤
│ Core              app/core/  config, logging, exceptions,        │
│                   security                                       │
└──────────────────────────────────────────────────────────────────┘
```

### Why the separation is enforced, not just recommended

The Streamlit page imports exactly two things from the project: an HTTP client and formatting
helpers. It cannot reach a rule even if someone wanted it to. That means when the Streamlit UI is
replaced by a website, there is no logic to port - the new front end calls the same endpoints and
gets the same JSON.

---

## 2. Data flow of one analysis

```text
   file bytes
       │
       ▼
┌──────────────────────┐  extension allow-list, size limit, magic-byte sniff,
│ files/validation.py  │  filename sanitisation, SHA-256
└──────────┬───────────┘
           ▼
┌──────────────────────┐  CSV (delimiter sniffing) │ XLSX (openpyxl) │ JSON
│ files/readers.py     │  → pandas DataFrame, all columns read as text
└──────────┬───────────┘
           ▼
┌──────────────────────┐  EBELN → po_number ... three strategies:
│ column_mapping.py    │  exact alias (1.00) → token containment (0.80) → fuzzy (≥0.82)
└──────────┬───────────┘  user overrides win over every suggestion
           ▼
┌──────────────────────┐  numbers (EU/US separators, parentheses-negative, "12 EUR"),
│ normalizer.py        │  dates (ISO, DD.MM.YYYY, SAP YYYYMMDD), IDs keep leading zeros,
│                      │  derive total_value, convert to base currency,
└──────────┬───────────┘  unreadable values → DataQualityIssue, never a crash
           ▼
┌──────────────────────┐  20 rules, each isolated in try/except.
│ engine.py            │  Severity may escalate on value bands.
│  └── rules/*.py      │  Aggregates: risk score, KPIs, supplier roll-up.
└──────────┬───────────┘
           ▼
┌──────────────────────┐  persists analysis + findings + records
│ service.py           │  optionally calls ai_narrative.py
└──────────┬───────────┘
           ▼
      API response  →  Streamlit  /  future website  /  export file
```

### Base currency conversion

Rules compare values against thresholds, so every monetary comparison happens in the configured
base currency (default EUR). The normaliser adds `total_value_base` and `unit_price_base`
alongside the document-currency values, using the rates in the rule configuration. Without this,
a 40,000 USD order and a 40,000 GBP order would be treated as equal.

---

## 3. Deterministic rules vs AI

This is the decision the whole project is organised around.

**Rules decide. AI describes.**

| Concern | Implementation |
| --- | --- |
| Is this a duplicate? | `rules/duplication.py` - pandas grouping and comparison |
| How severe is it? | Rule base severity + configured value bands |
| Confidence score | Fixed per rule in the configuration |
| Financial exposure | Arithmetic on the line or order value |
| Risk score | `points / records × 10`, capped at 100 |
| Executive summary text | AI (or the mock provider) |
| Business-friendly restatement of a finding | AI (or the mock provider) |

Consequences of this split:

1. **Reproducible.** The same file always produces the same findings. The integration suite
   asserts exact per-rule counts against a recorded baseline.
2. **Explainable.** Every finding carries `evidence`, including the threshold that was applied,
   so a buyer can see *why* the line was flagged.
3. **Works offline.** No API key is needed for the analytical result. AI is additive.
4. **AI failure is survivable.** If the provider times out, `ai_narrative.py` returns an error
   string and the analysis still completes.

### Output labelling

Every user-visible value carries an origin: `rule_based`, `ai_generated`, `mock_ai`, `forecast`
or `demo_data` (`app/schemas/common.py`). The AI rewrite of a finding is stored in a *separate*
column (`ai_explanation`) - it never overwrites the rule-based explanation.

---

## 3a. What the two modules share

Module 2 was the first real test of whether the foundation was reusable. The answer forced one
refactor and produced a genuinely shared layer.

### `app/services/tabular/` - extracted, not duplicated

The column mapper and the parsing/coercion pass were originally written inside `po_risk`. Building
spend analytics would have meant copying them, so they were lifted into a registry-driven service
instead:

| Module | Contents |
| --- | --- |
| `field_registry.py` | `FieldRegistry`: names, required fields, alias lookup, `.extend()`, `.with_required()` |
| `mapping.py` | The three-strategy column matcher, now parameterised by a registry |
| `parsing.py` | `parse_number`, `parse_date`, `parse_boolean`, `coerce_types`, `frame_to_records` |

`po_risk/column_mapping.py` became a thin binding of the shared matcher to the purchase order
registry, and its public API did not change - the 217 existing tests passed unmodified, which is
the only evidence worth having that a refactor was safe.

### The field contract is inherited, not rewritten

`spend/field_definitions.py` imports the purchase order definitions and appends eight fields. One
conflict had to be resolved explicitly: in an ME2N export `CATEGORY` usually labels the *material
group*, while in a spend cube it means the *procurement category*. Because a registry resolves
aliases with `setdefault`, the spend registry strips that alias from `material_group` so it lands
where a spend analyst expects.

The payoff is testable, and it is tested: `test_po_risk_sample_file_also_works_here` uploads the
*module 1* sample file to the *module 2* endpoint and gets a valid analysis, because contract
status falls back to the contract number and the order date stands in for the transaction date.

### Requirements differ by module

Risk rules need the document keys, the quantity, the price and the date. Spend analysis needs
less: a document number, a supplier, *a* date (transaction or order) and *a* value basis (a total,
or quantity and unit price). That is expressed in `_missing_requirements()` rather than by forcing
one rigid required-field list on both modules.

---

## 3b. Spend analytics data flow

```text
   file bytes -> validate -> read -> map -> normalise
                                              │
                    derive: spend_base, effective_date, spend_month,
                            is_contracted, is_preferred_supplier,
                            is_maverick, is_under_management,
                            price_variance_base / _pct
                                              │
                                              ▼
                                      apply_filter()          ← applied ONCE
                                              │
                 ┌────────────────────────────┼────────────────────────────┐
                 ▼                            ▼                            ▼
          calculate_metrics()          build_analytics()          calculate_savings()
          18 headline KPIs             15 breakdowns              6 configurable models
                 └────────────────────────────┼────────────────────────────┘
                                              ▼
                             persist analysis + transactions + opportunities
                                              │
                                    optional AI narrative
```

**One filter, applied once.** Every figure downstream of `apply_filter()` describes the same slice,
which is why a filtered dashboard cannot show a KPI that disagrees with its own chart. Two
integration tests assert exactly that reconciliation.

**Transactions are persisted.** Drill-down queries the stored rows rather than re-reading and
re-filtering the source file, so clicking a bar is a single indexed query.

---

## 3c. Savings: models, not promises

Every savings rule follows the same shape, and the shape is the point:

```python
SavingsOpportunity(
    gross_saving_base=...,        # what the arithmetic produces
    realization_factor=0.5,       # configured haircut
    estimated_saving_base=...,    # gross x factor
    method="Target price = 25th percentile of prices paid (98.40). Gross saving = ...",
    evidence={...},               # every input, including the thresholds applied
    is_estimate=True,             # never false, anywhere
)
```

`method` states the arithmetic in words so a category manager can check the number instead of
trusting it. The API, the Excel export (red header) and the Streamlit page all repeat that these
are opportunities to investigate, not committed savings.

A savings model that fires on healthy spend is worse than no model, so every rule has a negative
test proving it stays silent on clean data, and an integration test asserts total estimated
savings stay under 25% of spend.

---

## 4. Configuration-driven thresholds

No rule contains a hardcoded limit. Every number lives in
`app/modules/po_risk/config/po_risk_rules.json`, is validated by Pydantic at load time, and is
echoed back in the finding evidence.

```json
"PO-R017": {
  "name": "Excessive manual changes",
  "category": "Approval and governance",
  "enabled": true,
  "base_severity": "medium",
  "confidence": 0.7,
  "params": { "max_changes": 5, "critical_changes": 12 }
}
```

A rule reads it like this:

```python
max_changes = int(self.param("max_changes", 5))
```

Retuning is a JSON edit. `tests/unit/test_pipeline.py::test_changing_a_threshold_changes_the_outcome`
proves it: it loads a modified config and shows the same data now produces a finding.

The file also holds the base currency and conversion rates, approval thresholds, the standard
payment-terms list, the high-risk supplier watch list, and the value bands that escalate severity.

---

## 5. Rule anatomy

```python
class ExcessiveChangesRule(BaseRule):
    rule_id = "PO-R017"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        max_changes = int(self.param("max_changes", 5))
        ...
        return findings
```

- `RuleContext` holds the normalised frame and the config, and caches derived views
  (order totals, material medians) with `cached_property` so twenty rules don't each recompute
  the same aggregation.
- `BaseRule.build_finding()` applies value-band severity escalation and attaches the standard
  fields, so a rule body stays focused on its own condition.
- The engine wraps every rule in `try/except`. A failing rule lands in `rule_errors` on the
  response; the other nineteen still return results. Tested by
  `test_engine_isolates_a_failing_rule`.

Adding a rule: write the class, register it in `rules/__init__.py`, add its configuration block,
add a unit test and a documented sample anomaly. Nothing else changes.

---

## 6. AI provider abstraction

```text
app/services/ai/
  base.py           AIProvider ABC, AIRequest/AIResponse, JSON extraction
  mock_provider.py  deterministic, no network, labelled mock_ai
  providers.py      Anthropic and OpenAI over httpx
  factory.py        picks a provider; falls back to mock without a key
  prompts.py        versioned prompt builders
```

- **Mock is the default.** `settings.resolved_ai_provider()` returns `mock` whenever the selected
  provider has no key configured, so the lab always runs.
- **Structured output is validated.** `complete_structured()` parses the response and validates
  it against a Pydantic model. A malformed response raises `AIProviderError` rather than being
  stored.
- **Timeouts and limited retries** are configured centrally; retries apply only to timeouts and
  5xx responses.
- **Prompt versioning.** Each prompt carries a version string (`po_risk_narrative_v1.0.0`) that is
  saved with the analysis, so output can be traced to the prompt that produced it.
- **Token and cost tracking** are recorded when the provider reports usage.

### Prompt-injection handling

Uploaded content is untrusted. Before any of it reaches a model it is wrapped in
`<untrusted_data>` delimiters, and every string value inside is passed through
`neutralize_prompt_injection()`, which replaces known instruction patterns with `[filtered]`. The
system prompt states explicitly that content inside the block is data, never instructions.

Note the shape of the fix: values are filtered *individually*, then serialised. An earlier version
truncated the serialised JSON, which produced an unparseable payload and silently emptied the
model's context. `test_large_prompt_payload_remains_valid_json` guards against a regression.

---

## 7. Persistence

Four tables (`app/models/po_risk.py`):

| Table | Holds |
| --- | --- |
| `uploaded_files` | filename, stored path, SHA-256, size, detected columns |
| `po_analyses` | KPIs, applied mapping, supplier roll-up, rule executions, AI narrative |
| `po_records` | the normalised line items belonging to an analysis |
| `po_findings` | one row per finding, with evidence JSON |
| `spend_analyses` | filter applied, every metric, all breakdowns, AI narrative |
| `spend_transactions` | normalised transactions, indexed for drill-down |
| `spend_opportunities` | one row per modelled saving, with evidence and `is_estimate` |
| `supplier_catalogs` | one row per uploaded supplier master file |
| `suppliers` | normalised supplier master data (lists stored as JSON) |
| `supplier_recommendations` | requirement, weights, eligibility summary, AI narrative |
| `supplier_recommendation_entries` | one row per supplier: rank, 9 sub-scores, cost/delivery, advantages, risks |
| `invoice_validations` | tolerances, KPIs, three-way matches, rule executions, AI narrative |
| `invoice_exceptions` | one row per exception, with evidence JSON |
| `supplier_risk_datasets` | one row per uploaded risk profile file (plus the optional events file) |
| `supplier_risk_records` | normalised risk facts per supplier, with that supplier's events |
| `supplier_risk_assessments` | weights, as-of date, portfolio summary, AI narrative |
| `supplier_risk_profiles` | one row per supplier: 10 category scores, overall, band, trend, full breakdown |
| `contracts` | one row per uploaded contract: extraction metadata, title, parties, key dates, summary, AI narrative |
| `contract_pages` | the extracted text, one row per page - what keeps a citation resolvable after the upload is gone |
| `contract_clauses` | one row per clause type: present/absent, confidence, page, heading, excerpt, parsed values |
| `contract_risks` | one row per rule finding, with its evidence and references |
| `contract_obligations` | one duty sentence per row, quoted verbatim, with its party and page |
| `inventory_datasets` | one row per uploaded inventory history: mapping, data-quality issues, series and period coverage |
| `inventory_records` | normalised movement rows, so a dataset can be forecast repeatedly without the file |
| `inventory_forecasts` | one row per run: horizon, confidence and service levels, model usage, portfolio summary, AI narrative |
| `inventory_forecast_items` | one row per material/plant: model used, shortage and reorder dates, quantities, classification, accuracy, full engine payload |

``uploaded_files`` is shared by every module and carries a ``module`` column.

SQLite by default with `check_same_thread=False`; PostgreSQL works by changing `DATABASE_URL`
only. Alembic migrations use batch mode so they run on SQLite too, and the migration was verified
in both directions (`upgrade head` and `downgrade base`).

JSON columns use SQLAlchemy's portable `JSON` type, which maps to `JSONB`-compatible storage on
PostgreSQL without a code change.

---

## 8. Error handling

`app/core/exceptions.py` defines an `AppError` hierarchy, each with a status code and a safe
message. Handlers in `app/main.py` convert them into the standard envelope:

```json
{ "success": false, "data": null,
  "error": { "code": "file_validation_error", "message": "...", "details": {} },
  "meta": { "timestamp": "...", "request_id": "..." } }
```

Internal details (paths, stack traces, driver messages) are logged, never returned. Unexpected
exceptions become a generic 500 with a request ID that ties the response to the log entry. No
error is swallowed silently: a failing rule is reported in `rule_errors`, an AI failure in
`ai_narrative.error`, and unreadable cells in `data_quality_issues`.

---

## 9. Where a new module goes

Adding module 2 (Spend Analytics) means:

```text
app/modules/<name>/     logic, its own config file
app/api/v1/<name>.py    routes, registered in router.py
app/models/<name>.py    tables + an Alembic revision, exported from models/__init__.py
streamlit_app/pages/    a page that calls the API
tests/unit|api|integration/
```

Shared pieces - the tabular services, file validation, readers, exports, AI providers, config,
logging, security - are reused, not duplicated. Module 2 required exactly one change to module 1
(extracting the shared mapping/parsing code), and none to its rules.

One trap worth knowing: `init_db()` imports `app.models` as a package rather than one module by
name. Importing a single module would silently skip the other modules' tables on a fresh
database.
