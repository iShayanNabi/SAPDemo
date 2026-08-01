# Testing

**1,698 tests, about two minutes, no network and no API key.**

```bash
pytest                              # everything
pytest tests/unit                   # 832
pytest tests/api                    # 434
pytest tests/integration            # 313
pytest tests/e2e                    # 119
pytest -k duplicate -v              # by name
pytest tests/unit/test_rules.py::test_split_purchase_detected
```

---

## How the suite is organised

| Layer | Count | Answers |
| --- | --- | --- |
| `tests/unit` | 832 | Does each rule, metric, score and forecast produce the right number - and stay quiet on healthy data? Do eligibility, weighting, mapping, parsing, filtering, model selection, security and the AI abstraction behave? |
| `tests/api` | 434 | Do the endpoints return the right status, envelope and payload, and reject bad input? |
| `tests/integration` | 313 | Over the full demo datasets, is every documented anomaly, scenario and anchor actually detected, end to end through HTTP? |
| `tests/e2e` | 119 | Does the whole *journey* work - and do the ten modules still agree with each other about envelopes, errors, identifiers, timestamps, paging and exports? |

| File | Covers |
| --- | --- |
| `tests/unit/test_rules.py` | The 20 PO risk rules |
| `tests/unit/test_pipeline.py` | Mapping, parsing, security, AI abstraction, engine |
| `tests/unit/test_spend_metrics.py` | Classification, aggregation, concentration, tail, variance, filters |
| `tests/unit/test_spend_savings.py` | The six savings models and the configuration |
| `tests/api/test_po_risk_api.py` | PO risk endpoints |
| `tests/api/test_spend_api.py` | Spend endpoints, drill-down, exports |
| `tests/unit/test_supplier_scoring.py` | The 9 scores, weight validation, ranking, determinism |
| `tests/unit/test_supplier_eligibility.py` | The 7 eligibility filters |
| `tests/api/test_supplier_reco_api.py` | Supplier endpoints, recommend, weight validation, exports |
| `tests/integration/test_sample_data_anomalies.py` | PO risk anomaly manifest |
| `tests/integration/test_spend_sample_data.py` | Spend scenario manifest |
| `tests/integration/test_supplier_sample_data.py` | Supplier anchor manifest and ranking baseline |
| `tests/unit/test_supplier_risk_scoring.py` | Metric normalisation, category weighting, missing data, bands, trend, actions, config |
| `tests/unit/test_supplier_risk_copilot.py` | Intent detection, supplier resolution, citations, unavailable answers |
| `tests/api/test_supplier_risk_api.py` | Supplier risk endpoints, calculate, chat, filters |
| `tests/integration/test_supplier_risk_sample_data.py` | Supplier risk anchor manifest and scoring baseline |
| `tests/unit/test_rounding.py` | The central rounding policy: half-up ties, exact decimal sums, order independence, repeated-run stability |
| `tests/unit/test_contract_extraction.py` | PDF/DOCX/TXT extraction, page segmentation, needs-OCR detection, document upload validation, OCR capability reporting |
| `tests/unit/test_contract_clauses.py` | Section detection, clause extraction, structured values, date parsing, source references, the 20 risk rules, configuration-driven behaviour |
| `tests/unit/test_contract_qa.py` | Question intent routing, answers and citations, prompt-injection resistance, AI-is-additive-only |
| `tests/api/test_contract_api.py` | Contract endpoints, upload/analyse/clauses/questions/export, cross-format agreement |
| `tests/integration/test_contract_sample_data.py` | All 21 documented contract scenarios, the recorded baseline, end-to-end through the API |
| `tests/unit/test_inventory_forecasting.py` | The five models checked by hand, warm-up handling, interval growth, MAE/RMSE/MAPE/sMAPE/MASE, the MAPE-with-zeros refusal, period inference and calendar grids, seasonal-strength detection, model selection and eligibility |
| `tests/unit/test_inventory_planning.py` | Shortage dates, open-PO handling and expediting, safety stock and reorder point formulas, order quantities, confidence intervals, overstock/slow-moving/dead-stock classification, missing periods, insufficient data, series isolation, configuration-driven behaviour |
| `tests/api/test_inventory_api.py` | Inventory endpoints, upload/forecast/items/detail/export, filters, forced models, rejected inputs |
| `tests/integration/test_inventory_sample_data.py` | All 14 documented inventory anchors, the recorded baseline, repeat-run determinism, cross-format agreement |
| `tests/unit/test_test_case_planning.py` | Test-type allocation, identifier issue and reissue, priority derivation and escalation caps, summary and coverage arithmetic, configuration-driven behaviour |
| `tests/unit/test_test_case_generation.py` | Template build, mock drafting, structured-output validation, field-by-field repair, and every recovery path from a bad or missing draft |
| `tests/api/test_test_case_api.py` | Test case endpoints: generate, read, edit, add, duplicate, delete, regenerate, approve, execute, all four export formats |
| `tests/integration/test_test_case_sample_data.py` | All 7 documented test-case scenarios, the recorded deterministic baseline, repeat-run determinism |
| `tests/unit/test_blueprint_planning.py` | The section skeleton, canonical ordering, derived items, missing-input detection, custom-section numbering, configuration-driven behaviour |
| `tests/unit/test_blueprint_generation.py` | Template build, "needs input" build, mock drafting, batched drafting recovery, structured-output validation, field-by-field repair, the discard of items drafted for a derived section, injection filtering of printed text |
| `tests/unit/test_blueprint_versioning.py` | Snapshot immutability, section matching by key, item matching by title, capped narrative diffs |
| `tests/api/test_blueprint_api.py` | Blueprint endpoints: generate, read, edit, section edit/regenerate/approve/add/delete, versions, comparison, all four export formats, and the approved-but-stale pair |
| `tests/integration/test_blueprint_sample_data.py` | All 6 documented blueprint scenarios, the recorded deterministic baseline, the demo projects driven through the real API |
| `tests/unit/test_export_builders.py` | The two Phase 5 export builders: every format, empty and partial payloads, contributions that rebuild a score, an unscored category that is not a zero, the credited keyword, PDF page count, the disclaimer in every format |
| `tests/integration/test_export_journeys.py` | Both new exports driven over HTTP against the bundled datasets, comparing the *file* to the *API response* rather than to a fixture |

The e2e layer adds a check worth knowing about: `test_cross_module_contract.py`
asserts the **set** of modules exposing an export route, not a count. Modules 5
and 10 shipped without one for a whole phase, and a count would have been
satisfied by any tenth module gaining one.

### Isolation

`tests/conftest.py` sets environment variables **before** any application module is imported,
because the settings singleton is built at import time:

```python
TEST_ROOT = Path(tempfile.mkdtemp(prefix="sap_ai_lab_tests_"))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ROOT / 'test.db'}"
os.environ["UPLOAD_DIR"] = str(TEST_ROOT / "uploads")
os.environ["AI_PROVIDER"] = "mock"
```

Each session gets a throwaway database and upload/export directories, removed afterwards. Running
the suite never touches your local data. The mock AI provider means no network call and no key.

---

## Unit tests

### Rules (`tests/unit/test_rules.py`, 58 tests)

Every rule has at least a positive and a negative case. The negative case matters as much as the
positive one: a rule that fires on healthy data is worse than no rule.

```python
def test_duplicate_purchase_order_detected(rule_config):
    rows = [
        make_row(po_number="4500000001", quantity=50, unit_price=200.0),
        make_row(po_number="4500000002", quantity=50, unit_price=200.0,
                 order_date=BASE_DATE + timedelta(days=3)),
    ]
    findings = DuplicatePurchaseOrderRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    assert findings[0].evidence["original_po_number"] == "4500000001"
    assert findings[0].evidence["days_apart"] == 3
```

Also covered: severity escalation by value band, severity scaling with delay length, and the
invariant that every finding is labelled `rule_based` with an explanation, an action, a bounded
confidence score and a non-negative exposure.

`tests/factories.py` supplies the defaults, so a test writes only the fields it cares about and
reads like a sentence.

### Everything else (`tests/unit/test_pipeline.py`, 79 tests)

- **Column mapping** - SAP technical names, business labels, casing and separator variants, typo
  tolerance, unknown columns reported rather than guessed, override precedence, duplicate-target
  rejection.
- **Normalisation** - `1.234,56` and `1,234.56` both parse; `(500)` is negative; `"12 EUR"` is 12;
  SAP `YYYYMMDD` and `00000000` handled; leading zeros preserved; `total_value` derived when
  absent; base-currency conversion; unreadable values become data-quality issues, not crashes.
- **File handling** - extension allow-list, size limit, magic-byte sniffing (a ZIP renamed to
  `.csv` is rejected; a CSV renamed to `.xlsx` is rejected), a helpful message for legacy `.xls`,
  delimiter sniffing, wrapped and bare JSON.
- **Security** - filename sanitisation including traversal attempts, unique stored names, path
  containment, injection-marker detection and neutralisation, and the check that ordinary business
  text is left untouched.
- **AI abstraction** - mock is the default without a key; structured output validated against a
  Pydantic model; a malformed or prose response raises rather than being stored; JSON extraction
  survives code fences and chatter; the narrative layer degrades gracefully when the provider
  fails.
- **Engine** - all 20 rules execute, a subset can be selected, a deliberately broken rule is
  isolated while the rest still return findings, output is deterministic across runs, the risk
  score follows the documented formula, and findings are ordered by severity.
- **Configuration** - every registered rule has a configuration block; an invalid or missing file
  is rejected with a clear error; and changing a threshold changes the outcome with no code
  change.

---

## API tests

Run against a real `TestClient` with a real (temporary) database, so routing, validation, the
service layer, persistence and the export builders are all exercised.

Covered: health and catalogue endpoints; valid CSV, XLSX and JSON uploads; rejection of `.exe`,
`.txt`, empty files, mismatched content and malformed JSON; traversal filenames sanitised;
analysis KPIs and rule detection; manual mapping overrides; rejection of invalid mappings, of
removing a required field, of unknown rule IDs and of unknown body fields; 404s for unknown IDs;
finding filters and pagination; and all three export formats, including a check that the Excel
workbook has the expected five sheets and one row per finding.

Two checks are about honesty rather than function:

```python
def test_ai_status_never_exposes_a_key(api_client):
    body = api_client.get("/api/v1/po-risk/ai-status").json()["data"]
    serialised = json.dumps(body).lower()
    assert "api_key" not in serialised and "sk-" not in serialised
```

and error messages are asserted not to contain server paths.

---

## Integration tests

These give the sample data its purpose.

### The manifest is the specification

`scripts/generate_sample_data.py` plants 89 anomalies and writes down, for each one, the record,
the rule that should catch it, the expected severity and why it was inserted. The test reads that
file back and checks the engine:

```python
@pytest.mark.parametrize("rule_id", ["PO-R001", ..., "PO-R020"])
def test_documented_anomalies_are_detected(sample_analysis, manifest, rule_id):
    for entry in expected:
        scope = entry["expected_scope"]          # purchase_order or supplier
        target = entry["supplier_id"] if scope == "supplier" else entry["po_number"]
        actual = severities.get((rule_id, scope, target))
        assert actual, f"{rule_id} did not flag documented {scope} {target}"
        assert max(...) >= SEVERITY_RANK[entry["expected_severity"]]
```

Severity is asserted as *at least* the documented level, because the configured value bands can
legitimately escalate a medium finding to critical on a large order. Portfolio-level rules
(PO-R018) are matched by supplier, since they describe a category rather than a document.

### Other integration checks

- Dataset shape: ≥1,000 line items, ≥500 purchase orders, ≥50 suppliers.
- SAP headers map with no manual correction and no unmapped columns.
- Every rule produces at least one finding on the demo data, and no rule errors.
- Per-rule counts match `expected_findings_baseline.json` exactly - this catches an accidental
  change in either the rules or the generator.
- Every finding has evidence, an action, and a bounded confidence score.
- Every order of a watch-listed supplier is flagged by PO-R020.
- The full HTTP journey runs for CSV, XLSX and JSON, and all three produce identical counts
  despite their different header conventions.
- AI rewrites are stored separately and never overwrite the rule-based explanation.

---

## Spend analytics tests

### Metrics (`tests/unit/test_spend_metrics.py`, 71 tests)

Small datasets where the expected answer can be worked out by hand:

```python
def test_maverick_spend_calculation(spend_config):
    frame = make_spend_frame([
        make_spend_row(po_number="1", quantity=10, unit_price=100.0),
        make_spend_row(po_number="2", quantity=20, unit_price=100.0,
                       contract_status="Not contracted", contract_number=None,
                       preferred_supplier_status="Non-preferred"),
    ], spend_config)
    metrics = calculate_metrics(frame, spend_config)

    assert metrics.maverick_spend == pytest.approx(2000.0)
    assert metrics.maverick_spend_pct == pytest.approx(66.67, abs=0.01)
```

Covered: contract and preferred classification including the fallback to a contract number;
base-currency conversion; average and median computed over *order* totals rather than line totals;
contracted vs non-contracted split; maverick spend; spend under management; HHI (a monopoly scores
10,000, four equal suppliers score 2,500); top supplier and top-five share; Pareto tail
classification and its minimum-supplier guard; price variance against a baseline and its fallback
to the material median; every analytics breakdown; and all 13 filters including AND across fields,
OR within a field, and the rule that undated rows drop out when a date range is requested.

### Savings (`tests/unit/test_spend_savings.py`, 31 tests)

Every rule has a positive case and at least one negative case. The negative cases carry the weight:
a savings model that fires on healthy spend produces numbers nobody can defend in a negotiation.

Also covered: rule isolation (a deliberately broken model does not lose the other five),
opportunity ordering, the invariant that `estimated <= gross`, and that changing
`assumed_saving_pct` in the configuration doubles the estimate with no code change.

### Scenarios (`tests/integration/test_spend_sample_data.py`, 25 tests)

The scenario manifest is the specification. Each of the eight documented scenarios has a test that
reads the manifest and checks the engine produced the documented effect:

```python
def test_sc02_contract_leakage_is_detected(spend_analysis, spend_scenario_manifest):
    documented = scenario(spend_scenario_manifest, "SC-02")
    leaking = {row["value"]: row for row in analytics["contract_leakage"]}
    for supplier_id in documented["suppliers"]:
        assert supplier_id in leaking
        assert leaking[supplier_id]["leaked_spend_base"] > 0
```

Plus these cross-cutting checks:

- **Reconciliation.** The supplier breakdown, the monthly breakdown and the category breakdown each
  sum to the headline total spend, and a drill-down query returns exactly the transaction count and
  spend of the breakdown row it came from.
- **Filter consistency.** A filtered analysis has fewer rows, less spend, exactly 12 months of
  trend, and its breakdowns still reconcile.
- **Format equivalence.** CSV, XLSX and JSON produce identical metrics despite three different
  header conventions.
- **Credibility.** Total estimated savings must be above zero and below 25% of spend.
- **Cross-module reuse.** `test_po_risk_sample_file_also_works_here` uploads *module 1's* sample
  file to *module 2's* endpoint and asserts a valid analysis comes back.
- **Baseline.** Per-rule opportunity counts and ten headline metrics are compared against
  `expected_spend_baseline.json`.

---

## Bugs these tests did not catch

Worth recording honestly, because it shapes how much weight to put on a green suite.

**The drill-down cartesian product.** `select(func.sum(SpendTransaction.spend_base)).select_from(statement.subquery())`
references the outer table rather than the subquery, so SQLAlchemy joined the table again and the
totals were multiplied. The endpoint reported **329,444,859 EUR for 7 transactions**. Every unit
test passed, because the bug lived in a query the unit tests never ran. It surfaced within seconds
of driving the API by hand.

The fix added the reconciliation tests above, which now compare drill-down totals against the
breakdown they came from - the assertion that would have caught it.

**Same lesson as module 1**, where a prompt-truncation bug also survived a green suite and only
appeared under manual use. Run the thing.

**The blank integer cell.** `coerce_types` widened an INTEGER column to float64 as soon as one cell
was empty, so the integer cast received `NaN` and raised
`ValueError: cannot convert float NaN to integer`. This lived in code **every** module uses, and 506
tests were green across four modules - because modules 1-4 ship no blank integer cells. It surfaced
the first time module 5's deliberate missing-data sample supplier was loaded.

The lesson is about sample data rather than test structure: a dataset whose rows are all complete
only ever exercises the happy path. `tests/unit/test_pipeline.py::test_integer_column_survives_a_blank_cell`
is the regression test, and module 5's `SRK-09` anchor is the dataset row that keeps it honest.

**The stale approval and the orphaned verdict** (module 8). Two states that no single assertion was
wrong about, and that only read as bugs with two fields of one response side by side:

- a test case whose title and every step had been replaced by hand still carried *approved by
  Ingrid* - because regenerating cleared the approval and a `PUT` edit did not;
- after fixing that, the suite summary read *1 executed, 1 failed* while every status read *draft*,
  because the verdict had been reached against a script that no longer existed.

Neither was a wrong number. Each field was individually correct and the pair was a lie. The
regression tests are
`tests/api/test_test_case_api.py::TestEditing::test_editing_the_script_clears_an_approval` and
`::test_editing_the_script_marks_the_recorded_verdict_as_stale`. The general lesson: when two
fields describe the same thing from different angles, assert the *relationship*, not each field.

---

## Adding a rule test

1. **Positive case** - the smallest dataset that must trigger the rule.
2. **Negative case** - similar data that must stay clean, usually just below the threshold.
3. **Evidence** - assert on the specific evidence keys, not just the count.
4. **Sample anomaly** - add an injection to `scripts/generate_sample_data.py` so the rule is
   covered end to end; `test_manifest_covers_every_rule` fails if a rule has no documented
   anomaly.
5. Regenerate the sample data (which refreshes the baseline) and run the suite.

```python
def test_my_new_rule_detects_the_problem(rule_config):
    rows = [make_row(some_field="problematic")]
    findings = MyNewRule(rule_config).evaluate(make_context(rows))
    assert len(findings) == 1
    assert findings[0].evidence["threshold_my_limit"] == 42


def test_my_new_rule_ignores_clean_data(rule_config):
    assert MyNewRule(rule_config).evaluate(make_context([make_row()])) == []
```

---

## What the suite does not cover

- **The Streamlit UI is not tested automatically.** All three pages are verified to execute
  without exceptions, but there is no browser-level test. Check the UI by hand after changing it.
- **Real AI providers are not called.** The Anthropic and OpenAI clients are exercised only
  through the abstraction and the mock. Their live behaviour is untested here by design - the
  suite must run without keys or network.
- **PostgreSQL is not exercised in CI.** Only SQLite. The models avoid dialect-specific types and
  migrations use batch mode, but a first PostgreSQL run deserves manual verification.
- **No load or concurrency testing.** Analyses run synchronously inside the request.

- **Savings assumptions are not validated against reality.** The tests check the arithmetic is
  correct and configurable. Whether an 8% contract-compliance saving is achievable in your
  organisation is a commercial question no test can answer.

One caveat worth repeating: every one of the worst bugs found so far passed the whole suite at the
time and only appeared when the API was driven by hand. Module 10 added two more to the list - a
response that served the question just answered while every count in it was correct, and a study
plan that recommended a topic scored 98 out of 100 while claiming it was below the threshold.
Tests are necessary, not sufficient - run the thing.

### Module 10 - SAP Interview Coach

- `tests/unit/test_interview_scoring.py` (30) - concept matching including line breaks, plurals,
  word boundaries and the negation window; every dimension; the incorrect-statement penalty landing
  on technical accuracy alone; non-answers; the four clarity components; per-mode weights; a
  configuration edit changing a score with no code change; follow-up selection.
- `tests/unit/test_interview_selection.py` (27) - track allocation in caller order, the stable
  seeded shuffle, difficulty spreading, distinct topics, session summaries, and the dashboard
  including the two rules that came out of a real bug: a topic you are strong at never enters the
  study plan, and every plan item's reason has to match that topic's real numbers.
- `tests/api/test_interview_api.py` (37) - the five specified routes end to end, a pending question
  never carrying its answer key, the served question advancing, scores identical with and without
  AI, time reported but never scored, injection reported and still marked, a frozen completed
  session, and the catalogue and browsing endpoints.
- `tests/integration/test_interview_sample_data.py` (34) - the bank contract, **every reference
  answer scoring full coverage against its own rubric**, the documented anchors against the
  recorded baseline, structured validation and repair of five malformed provider payloads, and the
  rubric-fingerprint staleness pair.
