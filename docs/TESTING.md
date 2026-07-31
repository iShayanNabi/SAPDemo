# Testing

**394 tests, about 60 seconds, no network and no API key.**

```bash
pytest                              # everything
pytest tests/unit                   # 239
pytest tests/api                    # 95
pytest tests/integration            # 60
pytest -k duplicate -v              # by name
pytest tests/unit/test_rules.py::test_split_purchase_detected
```

---

## How the suite is organised

| Layer | Count | Answers |
| --- | --- | --- |
| `tests/unit` | 239 | Does each rule and metric produce the right number - and stay quiet on healthy data? Do mapping, parsing, filtering, security and the AI abstraction behave? |
| `tests/api` | 95 | Do the endpoints return the right status, envelope and payload, and reject bad input? |
| `tests/integration` | 60 | Over the full demo datasets, is every documented anomaly and scenario actually detected, end to end through HTTP? |

| File | Covers |
| --- | --- |
| `tests/unit/test_rules.py` | The 20 PO risk rules |
| `tests/unit/test_pipeline.py` | Mapping, parsing, security, AI abstraction, engine |
| `tests/unit/test_spend_metrics.py` | Classification, aggregation, concentration, tail, variance, filters |
| `tests/unit/test_spend_savings.py` | The six savings models and the configuration |
| `tests/api/test_po_risk_api.py` | PO risk endpoints |
| `tests/api/test_spend_api.py` | Spend endpoints, drill-down, exports |
| `tests/integration/test_sample_data_anomalies.py` | PO risk anomaly manifest |
| `tests/integration/test_spend_sample_data.py` | Spend scenario manifest |

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

One caveat worth repeating: both of the worst bugs found so far passed every test at the time and
only appeared when the API was driven by hand. Tests are necessary, not sufficient - run the thing.
