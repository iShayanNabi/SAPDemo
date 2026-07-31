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
| 5 | **Supplier Risk Copilot** | **Implemented** |
| 6 | **Contract Assistant** | **Implemented** |
| 7 | **Inventory Predictor** | **Implemented** |
| 8 | **SAP Test Case Generator** | **Implemented** |
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

# 3. Check the installation
python scripts/verify_setup.py

# 4. Start the API (terminal 1)
uvicorn app.main:app --reload       # http://127.0.0.1:8000/docs

# 5. Start the UI (terminal 2)
streamlit run streamlit_app/Home.py # http://localhost:8501
```

**No data generation step is needed.** The fictional demo datasets are committed to the repository,
so a fresh clone can run `verify_setup.py`, `pytest` and the app straight away. The generator
scripts under `scripts/` only need re-running if you delete or edit the files in `data/sample/`, or
if you change a generator itself - see [Sample data](#sample-data).

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

## Module 5 - Supplier Risk Copilot

Aggregates the supplier information the lab already holds into a transparent, per-supplier risk
profile, and lets you **ask questions about the loaded data**.

**Workflow:** upload the supplier risk profiles (and optionally the dated risk events) -> calculate
-> portfolio KPIs -> pick a supplier -> risk score, category breakdown, trend, supporting metrics,
contracts, delivery and invoice issues, recommended actions -> ask the copilot.

**Reuses the supplier master.** The field contract inherits module 3's 19 supplier fields through
`FieldRegistry.extend()` and appends 25 risk facts, so `OTD`, `QUALITY_SCORE`, `DEFECT_RATE`,
`ESG_SCORE`, `CONTRACT_STATUS`, `ORDER_COUNT` and `HISTORICAL_SPEND` keep exactly one meaning across
the lab. 44 canonical fields in total; only `supplier_id` is required.

### The eleven risk figures

Ten weighted categories plus the overall blend. **The scale is always 0 = no risk, 100 = maximum
risk**, so a reader never has to remember which direction a metric runs.

| Category | Default weight | Driven by |
| --- | --- | --- |
| Delivery risk | 15% | on-time rate, late-delivery share, average delay |
| Quality risk | 15% | quality score, defect rate, quality incidents |
| Financial risk | 14% | credit score, payment defaults, distress flag |
| Spend concentration risk | 10% | share of category spend, single-source materials, alternatives |
| Compliance risk | 10% | open findings, certification status, audit status |
| Contract risk | 8% | contract status, days to expiry |
| Invoice risk | 8% | invoice exception rate, disputed invoices |
| Operational risk | 8% | capacity utilisation, lead-time variability, lead time |
| ESG risk | 6% | recorded ESG score |
| Geographic risk | 6% | country risk index, regions served |
| **Overall supplier risk** | 100% | the weighted blend of the ten above |

### Transparent scoring

Every figure carries its own audit trail. For each input metric the API returns the **raw value**,
the **weight**, the **normalised 0-100 score**, the **contribution** to the category, and a plain
sentence saying how it was reached (`74 % against best 99 / worst 70 -> 86.2`). Category
contributions sum to the overall score, and the tests assert that they do.

### Missing data is never invented

A metric with no value is dropped and the remaining metric weights in its category are
renormalised; a category with no data at all is excluded and the category weights are renormalised.
If fewer than three categories can be scored, the **overall score is withheld** rather than computed
from a fragment. Suppliers below the configured completeness are flagged `limited_data`.

### Risk trend

Derived from the dated internal records: the severity-weighted volume of risk events in the recent
window against the window immediately before it. Without enough dated records the trend is reported
as `unknown` - it is not guessed.

### The copilot

A **deterministic** question answerer - not a language model. It classifies a question against a
fixed intent table, answers from the computed assessment, and **cites the internal records it used**:

| Question | Answered from |
| --- | --- |
| Show supplier ABC's risk. | the supplier's computed profile |
| Why is this supplier high risk? | the top contributing categories and their metrics |
| Which suppliers have the most delivery issues? | the delivery category ranking |
| Which suppliers have contracts expiring soon? | contract expiry against the as-of date |
| Which alternative supplier has lower risk? | same-category / shared-material suppliers scoring lower |
| What action should procurement take? | the rule-based recommended actions |

Because the copilot and the supplier page read the same computed profile, **an answer can never
disagree with the page**. When a supplier is not in the loaded records, or a question is outside
what the data supports, it says so plainly instead of producing a plausible sentence.

> **No live external data.** No financial, credit, ESG, sanctions or news service is contacted.
> Every figure comes from the uploaded internal records, and nothing here has been validated in a
> live SAP environment.

---

## Module 6 - Contract Assistant

Reads a contract document and turns it into a structured, **verifiable** record: the clauses, the
key dates, the obligations and the risks - each one carrying the page it came from, the heading it
sat under, a short supporting excerpt and a confidence score. Then answers questions from those
same extractions, with citations.

**Workflow:** upload -> file validation -> text extraction -> page segmentation -> section
detection -> clause extraction -> structured validation -> risk analysis -> question answering ->
export.

### Supported documents

| Format | Works out of the box | Notes |
| --- | --- | --- |
| Text-based PDF | Yes | via `pypdf`; one entry per real page |
| DOCX | Yes | via `python-docx`; headings and tables are read |
| TXT / MD | Yes | form feeds become pages, otherwise a paragraph-safe character budget |
| Scanned PDF / images | Only with OCR configured | reported as `needs_ocr`, never analysed as empty |

Extraction lives in `app/services/documents/` behind a `DocumentExtractor` interface, with an OCR
seam (`ocr.py`) that declares **local OCR (Tesseract)**, **AWS Textract** and **Azure AI Document
Intelligence**. All three are unconfigured by default and say so - `GET /api/v1/contracts/extractors`
reports exactly what this installation can and cannot read, without ever revealing a credential.

> **A scanned file is not silently accepted.** If no text can be extracted and no OCR provider is
> configured, the upload comes back with `status: needs_ocr` and an explanation, and the analyse
> endpoint refuses rather than returning an empty contract.

### What is extracted

Seventeen clause types - contract term, auto-renewal, termination and notice, payment terms,
pricing, service levels, penalties, limitation of liability, indemnification, confidentiality,
data privacy, insurance, governing law, dispute resolution, force majeure, assignment and audit
rights - plus the contract title, the parties and their roles, the key dates, the obligations,
the **missing clauses** and the **potential risks**.

Structured values are parsed out of the clause text where they exist: `net_days`, an early-payment
discount, notice periods, renewal terms, liability caps and their currency, an availability
percentage, a named jurisdiction. Anything that cannot be parsed is simply absent - never a zero
that would read as a real figure.

### Every claim carries its source

The module's unit of output is a value **plus a source reference**:

| Field | Meaning |
| --- | --- |
| `page_number` | 1-based, as a reader sees it |
| `section_heading` | quoted verbatim from the document (`"4. TERMINATION"`) |
| `excerpt` | a short quotation, clamped to the clause's own section |
| `confidence` | a deterministic 0-1 score |

Confidence is **built, not guessed**: a base value, plus a bonus when the clause sits under a
heading that names it, plus the defining phrase, plus capped bonuses for supporting phrases and for
a value that actually parsed, minus a penalty when the only evidence is scattered across unrelated
pages. The weights live in `contract_rules.json`, and a clause below the review threshold is
flagged `needs_review` rather than presented as certain.

### Key dates, and how they were reached

`effective_date`, `expiration_date`, `renewal_date`, `notice_deadline` and `signature_date`, each
with a `*_basis` saying whether it was **stated** in the document or **derived** (`derived_from_term`,
`derived_from_expiration_and_notice`). A derived date is never presented as one the contract
printed. Dates are parsed from the formats contracts actually use - `1 January 2026`,
`January 1, 2026`, `the 1st day of January 2026`, `2026-01-01`, `01/01/2026` - with the ambiguous
numeric case resolved by the configurable `day_first` setting, and reported on the result.

### Risk rules

Twenty deterministic rules (`CA-R001`-`CA-R020`) covering renewal traps, short notice periods,
missing required clauses, uncapped and unlimited liability, penalties, expiry windows, payment
terms outside policy, one-sided indemnities, unremedied service levels, free assignment, absent
audit rights, unapproved governing law, prompt-injection bait, unreadable documents, missing key
dates and low-confidence extractions. Each is isolated: one broken rule lands in `rule_errors` and
the other nineteen still produce findings.

### Question answering

Deterministic, and answered **from the extracted clauses** - not from a language model. A question
is scored against the same clause vocabulary used for extraction, and the answer quotes the clause
with its page and heading:

| Question | Answered from |
| --- | --- |
| What are the payment terms? | the payment clause, with `net_days` |
| When does this contract expire? | the computed key dates and their basis |
| Does it renew automatically? | the auto-renewal clause and its notice period |
| Is liability capped? | the liability clause and any parsed cap |
| Which clauses are missing? | the missing-clause list |
| What are the risks? | the rule findings |

Because the answer and the clause table read the same extraction, **they cannot disagree**. When
the contract does not cover a question, the assistant says so and lists what it does cover, instead
of producing a fluent wrong paragraph.

### Uploaded documents are untrusted data

A contract is written by someone outside the organisation, which makes this the sharpest version of
the prompt-injection problem in the lab. Four layers apply:

1. instruction-like text found in a document is **reported as a finding** (`CA-R016`), so a
   reviewer learns the document was tampered with;
2. it never changes an extraction - clause detection is pattern matching over the text, not
   instruction following;
3. only *results* ever reach an AI provider, never the whole document, and every string is passed
   through the shared injection filter first;
4. the prompt wraps the payload in an explicit `<untrusted_data>` block whose system prompt forbids
   following anything inside it.

`sample_contract_hostile_calder` exists to prove this: it asks to be recorded as approved with no
risks and to have an API key printed. The test suite asserts that it is reported, and not obeyed.

> **Not legal advice.** Every clause, date and risk is extracted by deterministic pattern matching
> from the uploaded file. This is an assistive review and no substitute for reading the contract;
> nothing here has been validated in a live SAP environment.

---

## Module 7 - Inventory Predictor

Reads an inventory history, forecasts demand with explainable statistical models, projects the
stock level forward day by day and produces a reorder plan. **No language model produces any
number in this module** - the AI narrative is optional, separate and clearly labelled.

**Workflow:** upload -> column mapping -> period-granularity detection -> gap detection -> demand
profiling -> model backtesting and selection -> forecast with a confidence range -> daily stock
projection -> shortage, reorder and stock-health analysis -> export.

### The five forecasting methods

Each encodes a different, statable belief about demand. The belief is what a planner agrees or
disagrees with, and each is reproducible in a spreadsheet.

| Method | What it assumes | Minimum history |
| --- | --- | --- |
| Simple moving average | A flat level; the last *w* periods are equally informative | 4 periods |
| Weighted moving average | A flat level; recent periods say more | 4 periods |
| Simple exponential smoothing | A level that drifts; older periods fade geometrically | 4 periods |
| Holt linear trend | A level *and* a trend, both drifting | 6 periods |
| Holt-Winters additive seasonal | A level, a trend and a repeating seasonal shape | 2 full seasons **and** a measurable season |

Additive rather than multiplicative seasonality on purpose: a multiplicative season is undefined
when a period's demand is zero, and inventory demand hits zero regularly.

### How the model is chosen

Automatically, per material, by **backtesting** - never by how well a model fits the history it was
trained on, which would always crown the most flexible model.

- The last periods are held back, each eligible method is refitted on the shortened history, and
  the methods are scored on periods they never saw.
- **Every candidate is scored on the same held-out periods.** Comparing two models measured on
  different splits picks the easier split, not the better model.
- A model with more smoothing constants must beat the best simpler model by a configured margin
  before it wins. A short backtest is a noisy measurement, and the most flexible model wins those
  coin flips more often than it deserves.
- Holt-Winters is only offered when the position in the season explains enough of the variation
  **after paying for every seasonal factor it fits**. Twelve monthly factors fitted to 30
  observations explain about 12/30 of the variance by chance, so an unadjusted test calls pure
  noise seasonal. Periods that were missing from the file are excluded from that measurement -
  two missing Augusts look exactly like an August dip.
- Trend and seasonal models are not offered at all for intermittent demand, where a run of zeros
  makes both fit noise.

The API returns every candidate, its parameters, its backtest score and - for the ones that were
never tried - the sentence explaining why.

### What you get per material

| Output | Notes |
| --- | --- |
| Demand forecast | Per period, over the chosen horizon |
| Confidence interval | `forecast ± z × σ × factor(h)`; flat for moving averages, widening for the smoothing family, per the standard formulae |
| Future inventory level | Projected stock per period, plus a best/worst band from the demand interval |
| Predicted shortage date | A **real date**, interpolated inside the period from the daily demand rate |
| Recommended reorder date | The day the projected inventory *position* falls to the reorder point |
| Recommended reorder quantity | Order-up-to level minus the projected position at that date |
| Recommended safety stock | `z(service level) × σ × √(lead time / period length)`, next to the material-master figure |
| Overstock risk | From days of cover, with the excess quantified |
| Slow-moving classification | From annualised turnover and the share of zero-demand periods |
| Dead-stock indicator | Consecutive zero-demand periods with stock still on hand |
| Model used and its assumptions | Plus every candidate that lost |
| Data-quality warnings | Per material, on top of the file-level issues |
| Forecast accuracy | MAE, RMSE, MAPE, sMAPE, MASE |

### Accuracy, and the MAPE trap

MAPE divides by the actual value, so it is undefined the moment a period had zero demand.
Computing it "over the non-zero periods only" is the usual workaround and it is dishonest: for an
intermittent material it silently drops exactly the periods the forecast found hardest.

**MAPE is therefore reported only when every period in the comparison window has non-zero demand.**
Otherwise it is `null`, the reason is stated in the response, and sMAPE and MASE carry the answer.
MASE below 1 means the model beat a naive same-as-last-period forecast - the one metric that says
whether the modelling was worth doing.

### Two positions, not one

Stock on hand answers *have I run out?*. Inventory position - stock on hand plus what is already on
order - answers *should I order more?*. Using stock on hand for the reorder trigger is the classic
way to order twice for the same shortage.

This is also why a material can show a shortage with no new order recommended: the quantity is
already on order and simply expected too late. That case is flagged as **expedite the existing
order**, with the reason, rather than raising a second one.

### Missing data is reported, never invented

- A material with too little history is returned with status `insufficient_data`, its history and
  a warning saying how many periods it has and how many it needs - never dropped, and never
  forecast from three points.
- A file with no ending-inventory column still gets a demand forecast and its accuracy; the
  projection reports itself unavailable with a reason, and no shortage date or reorder quantity is
  invented.
- Open purchase-order quantities with no usable expected date are reported but never placed on the
  projection - there is no honest date to place them on.
- Periods absent from the file are laid out on the grid, filled, and reported, so the periods
  either side keep their real positions on the time axis.

> **Estimates, not commitments.** Every figure is a statistical estimate from the uploaded history.
> Actual demand will differ, and nothing here has been validated in a live SAP environment.

---

## Module 8 - SAP Test Case Generator

Describe an SAP business process; get a structured test suite you can edit, approve, execute and
export. This is the first module where the AI output *is* the deliverable rather than a commentary
on one, so the deterministic/AI split is drawn in a different place - and drawn hard.

**Workflow:** process form -> test-type selection -> deterministic plan -> optional AI drafting ->
field-by-field repair -> editable test-case table -> step editor -> approval -> execution results
-> export.

### What is decided by code, and what is written by a model

| Decided by deterministic Python | Written by the AI provider |
| --- | --- |
| How many test cases each requested type receives | The title of each case |
| Every test-case identifier and its numbering | The objective |
| Which aspect of the process each case covers | The preconditions and test data |
| The priority of every case | The wording of each step |
| The step numbering | The expected result |
| Every status, approval and execution record | |
| The complete fallback case when a draft is unusable | |

The consequence is the property the module is built around: **run the same request twice, with a
real model or with none at all, and you get the same identifiers, the same type coverage and the
same priorities.** Only the prose can differ - and every case says which produced it.

### The eight test types

| Type | ID | What it proves |
| --- | --- | --- |
| System Integration Test | `TC-SIT-nnn` | The configured process runs end to end inside SAP and produces the documents the design calls for |
| User Acceptance Test | `TC-UAT-nnn` | The business can use it, in business language |
| Negative Test | `TC-NEG-nnn` | Invalid input is refused cleanly, with a message, and nothing is posted |
| Integration Test | `TC-INT-nnn` | The message crosses the system boundary, maps correctly and returns a status |
| Regression Test | `TC-REG-nnn` | A change did not break what worked, measured against a recorded baseline |
| Security Test | `TC-SEC-nnn` | The documented controls hold, refusals are logged and no data leaks |
| Authorization Test | `TC-AUT-nnn` | The role grants exactly what the process needs - no more, no less |
| Data Migration Test | `TC-MIG-nnn` | Loaded data reconciles with the signed-off source |

### Priority is derived, never guessed

Each type has a configured base priority, raised by at most one level when the process context says
so: financial vocabulary in the description, three or more integrations, four or more roles. Which
signals apply to which types is in the JSON. A quiet single-role process keeps every base priority;
a payment-bearing, heavily integrated one pushes its process tests to critical - so the scale
actually discriminates between two processes instead of marking everything urgent.

### Every failure mode ends with a usable test case

A test case is planned before anything is drafted, so there is always somewhere to put a fallback:

| What went wrong | What happens |
| --- | --- |
| No API key, or `use_ai=false` | The configured templates write every case. The suite is complete and labelled `rule_based` |
| The provider is down or times out | Same, plus the error is reported on the suite |
| The response is not JSON, or is the wrong shape | Same |
| The response skips a slot | That slot is filled from the template; the others keep their drafts |
| A returned case names a slot that does not exist | It is discarded and reported |
| A drafted case has a blank title, no steps, 200 steps or wrongly numbered steps | Repaired field by field against the configured limits, with every repair recorded on the case |

### Editing rules worth knowing

- **An identifier points at one test forever.** Delete `TC-SIT-002` and the next added case takes
  `TC-SIT-004`. A gap in the numbering beats one name for two different tests.
- **A script edit and an execution record are separate operations.** Regenerating never erases what
  a tester recorded; recording a result never rewrites the script.
- **Editing the script clears the approval.** An approval describes the script that was read.
- **A verdict recorded against a script that has since changed is flagged, not deleted.** It stays
  in the suite - a tester wrote it - marked as predating the current steps, and the flag clears
  when the test is run again. A suite that reports "1 failed" against steps nobody can find is
  worse than one that says so.
- **Deleting the last case of a test type reports the coverage the suite just lost.**

### Exports

CSV (the test-case table, ready to paste into a test management tool), XLSX (Summary, Test Cases,
Steps, Coverage and Methodology sheets), JSON (everything) and PDF (the readable test script, one
section per case, with the execution record printed underneath).

> **Drafts, not validated tests.** Every test case is drafted from a process description typed into
> this application. Nothing has been executed or validated in a live SAP system, and the generator
> is told never to name a transaction code, table or program the process description did not.


---

## Deterministic rules vs AI

This separation is the core design decision of the project.

| | Deterministic Python | AI (optional) |
| --- | --- | --- |
| Detecting risk | ✅ | ❌ never |
| Severity and confidence | ✅ | ❌ never |
| Calculations, aggregation, ranking | ✅ | ❌ never |
| Forecasting demand and projecting stock | ✅ | ❌ never |
| Planning a test suite: identifiers, coverage, priorities, numbering | ✅ | ❌ never |
| Rewriting a finding in business language | | ✅ |
| Executive summary | | ✅ |
| Drafting the wording of a test case | | ✅ |

**Mock mode is the default.** With no API key the lab uses a deterministic mock provider that
templates the real rule results into narrative text. Output is labelled `mock_ai`, so nobody
mistakes it for a model response. Configure `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` plus
`AI_PROVIDER` to use a real model; structured responses are validated with Pydantic before being
stored, and an AI failure never blocks the rule-based results.

Every value that reaches a user is labelled: `rule_based`, `ai_generated`, `mock_ai`, `forecast`
or `demo_data`.

---

## Sample data

Everything below is already committed under `data/sample/`, so you do not need to run any of these
scripts to use the lab or the test suite. Each generator is seeded and reproducible: re-running one
recreates its dataset byte for byte, and rewrites that module's `expected_*_baseline.json`.

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

`python scripts/generate_contract_sample_data.py` produces **six fictional contracts, each in
three formats** (`.txt`, a real text-based `.pdf`, and a `.docx` with real heading styles and a
table), plus
[`data/sample/CONTRACT_SCENARIO_MANIFEST.md`](data/sample/CONTRACT_SCENARIO_MANIFEST.md) and
`expected_contract_baseline.json`:

| Contract | What it demonstrates |
| --- | --- |
| `msa_nordwind` | auto-renewal, a 14-day termination notice, liquidated damages, net 90 payment terms |
| `supply_ravenna` | no data-privacy clause, unlimited liability, assignment without consent, Singapore law |
| `saas_helvetia` | service levels with credits, an expiry inside the warning window, a renewal notice deadline that has already passed |
| `services_baltic` | a clean, well-drafted agreement - the negative control |
| `nda_meridian` | a short NDA that genuinely lacks most clause types |
| `hostile_calder` | prompt-injection bait inside the contract text |

The same agreement exists in all three formats so the tests can prove PDF, DOCX and TXT extraction
reach **identical** conclusions. 21 documented scenarios are asserted by name, and the baseline is
recorded by reading the written files back through the real extractor - not from the generator's
in-memory strings.

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

`python scripts/generate_inventory_sample_data.py` produces the inventory history:

- **450 rows** covering **16 material/plant/storage-location series** across 15 materials and 3
  plants, over **30 monthly periods** (January 2024 to June 2026), in three formats
- 30 periods rather than 24 on purpose: Holt-Winters needs two complete seasons before it is
  offered at all, and the selector then holds back two folds of three periods to backtest on, so a
  24-period file would let the seasonal model exist with nothing to test it against
- **14 documented anchor materials** - seasonal, upward trend, stable, intermittent, a shortage, an
  overstock, slow-moving, dead stock, missing periods, too little history, an open PO expected too
  late, a demand-only extract with no stock column, periods that do not balance, and the same
  material stocked in two plants - listed in
  [`data/sample/INVENTORY_SCENARIO_MANIFEST.md`](data/sample/INVENTORY_SCENARIO_MANIFEST.md)
- `expected_inventory_baseline.json`, the exact model, shortage date and classification the current
  engine produces for every series

`python scripts/generate_test_case_sample_data.py` produces the demo **process definitions** the
Test Case Generator works from - this module has no dataset, its input is a form:

- **four fictional SAP process definitions** (a Procure-to-Pay purchase order, a plant-maintenance
  notification, a vendor-master migration cutover and a Fiori approval app), each ready to post
  straight to `POST /api/v1/test-cases/generate`
- each one is chosen so a deterministic decision is observable: all three priority escalation
  signals firing, none firing, a shortfall of test cases against test types, and role-count
  escalation touching only the access test types
- **7 documented scenarios** in
  [`data/sample/TEST_CASE_SCENARIO_MANIFEST.md`](data/sample/TEST_CASE_SCENARIO_MANIFEST.md)
- `expected_test_case_baseline.json`, recorded with **AI drafting switched off**, so it pins the
  identifiers, allocation, priorities, focus areas and step counts - the things that must not move
  when a provider, a key or a model changes. Drafted prose is deliberately not baselined, because
  it is the one part that is allowed to differ.

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
  modules/supplier_risk/ field definitions, normaliser, scoring, engine, copilot, service
  modules/contract_assistant/ segmentation, clauses, dates, obligations, risk rules, qa, engine
  modules/inventory/ field definitions, periods, normaliser, forecasting, accuracy, selection, projection, engine, service
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
pytest                    # everything (1,165 tests, ~80s)
pytest tests/unit         # 666 - rules, metrics, savings, scoring, eligibility, risk categories, copilot intents, tolerances, mapping, parsing, document extraction, clause extraction, date parsing, question answering, forecasting models, accuracy metrics, model selection, reorder policy, prompt-injection resistance, test-case planning, drafting recovery, security, AI
pytest tests/api          # 314 - endpoints against a temporary database
pytest tests/integration  # 185 - full journeys over all eight sample datasets
```

The integration suites read the anomaly, scenario, supplier, invoice, supplier-risk, contract,
inventory and test-case manifests and assert that every documented condition is actually detected. Details in [`docs/TESTING.md`](docs/TESTING.md).

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
| `MAX_UPLOAD_BYTES` | 25 MB | Tabular upload size limit (modules 1-5) |
| `MAX_DOCUMENT_BYTES` | 20 MB | Contract document size limit (module 6) |
| `ALLOWED_DOCUMENT_EXTENSIONS` | `.pdf,.docx,.txt,.md` | Document allow list, separate from the tabular one |
| `OCR_PROVIDER` | `none` | `none`, `local`, `aws_textract` or `azure_document_intelligence` |
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
