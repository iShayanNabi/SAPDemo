# SAPDemo — SAP AI Application Lab

Ten SAP-focused procurement and supply-chain applications, built so that every number they
produce is ordinary code you can read, and every sentence a language model writes is labelled as
such.

Everything runs on your machine. **No SAP credentials, no paid APIs, no AI API key and no Docker
are required.**

```bash
git clone https://github.com/iShayanNabi/SAPDemo.git
cd SAPDemo
```

> **Demo software.** Each module analyses only the file you give it. Nothing here connects to an
> SAP system, and no output has been validated in a live SAP environment.

**SAP is a third-party trademark.** SAPDemo is an independent demonstration project and is not
endorsed by, certified by, sponsored by, partnered with or affiliated with SAP.

---

## Two ways to run it

| | For | Start here |
| --- | --- | --- |
| **Locally** | Development, evaluating the modules on your own files | [Quick start](#quick-start) below |
| **Self-hosted, published** | A public website plus an invitation-only interactive demonstration | [`docs/PUBLIC_DEMO_DEPLOYMENT.md`](docs/PUBLIC_DEMO_DEPLOYMENT.md) |

The published deployment adds a Next.js marketing site (`frontend/`) and a public demonstration
mode that refuses uploads server-side, forces the mock AI provider and runs entirely on the
bundled fictional data. Neither the API nor the database is ever exposed.

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
| 9 | **SAP Blueprint Generator** | **Implemented** |
| 10 | **SAP Interview Coach** | **Implemented** |

Detailed progress: [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).

---

## Quick start

**Python 3.12 or newer is required.** Check with `python3 --version`.

```bash
# 1. Create and activate a virtual environment
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Check the installation
python scripts/verify_setup.py

# 4. Load the demo data so every page has something to show (optional)
python scripts/seed_database.py

# 5. Start the API (terminal 1)
uvicorn app.main:app --reload       # http://127.0.0.1:8000/docs

# 6. Start the UI (terminal 2)
streamlit run streamlit_app/Home.py # http://localhost:8501
```

Then follow [Complete demonstration](#complete-demonstration) below to drive all ten modules
start to finish.

**No data generation step is needed.** The fictional demo datasets are committed to the repository,
so a fresh clone can run `verify_setup.py`, `pytest` and the app straight away. The generator
scripts under `scripts/` only need re-running if you delete or edit the files in `data/sample/`, or
if you change a generator itself - see [Sample data](#sample-data).

Platform-specific instructions (macOS, Windows, Linux) are in
[`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md).

---

## Complete demonstration

Fifteen minutes, start to finish, touching all ten modules. Everything below runs on a fresh
clone with **no SAP system, no API key and no Docker**, against the fictional datasets committed
in `data/sample/`.

### 0. Set up (once)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/verify_setup.py          # exits 0 when everything is ready
```

### 1. Start from a clean database

```bash
python scripts/reset_demo.py --yes      # drops every table, re-applies the migrations
python scripts/seed_database.py         # loads all ten modules with the demo data
```

`seed_database.py` drives the real HTTP API in-process, so if it succeeds, the demo works. It
prints what each module produced:

```text
  1. Purchase Order Risk Checker             ok   131 findings over 1238 lines  (3.6s)
  2. Spend Analytics Dashboard               ok   44,940,173 EUR of spend, 45 opportunities  (4.1s)
  3. Supplier Recommendation Engine          ok   55 suppliers, 30 eligible for MAT-1000  (0.3s)
  4. Invoice Validator                       ok   17 exceptions over 420 invoices  (0.4s)
  5. Supplier Risk Copilot                   ok   55 suppliers scored  (0.4s)
  6. Contract Assistant                      ok   3 contracts analysed  (0.6s)
  7. Inventory Predictor                     ok   15 materials forecast, 10 predicted shortages  (0.3s)
  8. SAP Test Case Generator                 ok   12 test cases in 'Procure to Pay - demo suite'  (0.1s)
  9. SAP Blueprint Generator                 ok   30 sections in 'Nordwind S/4HANA blueprint - demo'  (0.2s)
  10. SAP Interview Coach                    ok   1 session, 5 answers scored  (0.5s)
```

### 2. Start both processes

```bash
uvicorn app.main:app --reload           # terminal 1 - http://127.0.0.1:8000/docs
streamlit run streamlit_app/Home.py     # terminal 2 - http://localhost:8501
```

Check the API is up before anything else:

```bash
curl -s http://127.0.0.1:8000/api/v1/health
# {"success":true,"data":{"status":"ok","database_connected":true,"ai_provider":"mock",
#  "ai_is_mock":true,...},"error":null,"meta":{...}}
```

`ai_is_mock: true` is the normal state. The mock provider is deterministic, so every narrative
below is reproducible.

### 3. Walk one module end to end on the command line

Module 1, the whole journey, with nothing but `curl`:

```bash
API=http://127.0.0.1:8000/api/v1

# a. Download the bundled demo dataset (1,238 purchase order lines)
curl -s "$API/po-risk/sample?format=csv" -o /tmp/po.csv

# b. Upload it. The response suggests a column mapping; it does not demand one.
UPLOAD=$(curl -s -F "file=@/tmp/po.csv" "$API/po-risk/upload" | python3 -c \
  "import json,sys; print(json.load(sys.stdin)['data']['upload_id'])")

# c. Analyse it
ANALYSIS=$(curl -s -X POST "$API/po-risk/analyze" \
  -H 'Content-Type: application/json' \
  -d "{\"upload_id\": \"$UPLOAD\", \"generate_ai_summary\": true}" |
  python3 -c "import json,sys; print(json.load(sys.stdin)['data']['analysis_id'])")

# d. Read the most serious findings
curl -s "$API/po-risk/analyses/$ANALYSIS/findings?severity=critical&limit=3" |
  python3 -m json.tool | head -40

# e. Download the report
curl -s -OJ "$API/po-risk/analyses/$ANALYSIS/export?format=xlsx"
```

Expect **131 findings over 1,238 lines**, 21 of them critical. Every one names the rule that
raised it, the evidence, and the threshold it crossed.

Every module ends the same way. The route differs, the shape does not - a `format` query
parameter, the file itself rather than the JSON envelope, and a filename in
`Content-Disposition`:

```bash
curl -s -OJ "$API/supplier-risk/assessments/$ASSESSMENT/export?format=xlsx"
curl -s -OJ "$API/interviews/$SESSION/export?format=pdf"
```

### 4. Do the same from TypeScript

```bash
cd examples/typescript-client
npm install
npm run demo            # health -> sample -> upload -> analyse -> poll -> findings -> export -> copilot
```

That is the reference for a future website: the same seven calls, with the error handling, the
paging and the download filename all done properly. See
[`examples/typescript-client/README.md`](examples/typescript-client/README.md).

### 5. Walk the ten modules in the UI

Open <http://localhost:8501>. Each page loads its demo data from the API - the seed above means
every one has something to show immediately.

| Page | What to try | What to look for |
| --- | --- | --- |
| **1. PO Risk Checker** | Upload the demo CSV, run the analysis | 131 findings; every one shows its rule, evidence and threshold |
| **2. Spend Analytics** | Run the analysis, click a supplier in the chart | The drill-down total equals the figure you clicked |
| **3. Supplier Recommendations** | Ask for MAT-1000, 100 units, plant 1010 | 30 eligible of 55; each excluded supplier says why |
| **4. Invoice Validator** | Upload invoices, POs and goods receipts, validate | 17 exceptions; each names the two documents that disagree |
| **5. Supplier Risk Copilot** | Score the portfolio, ask "why is 0000390001 risky?", then download the XLSX | The answer cites the records it came from; the workbook rebuilds the score from its contributions |
| **6. Contract Assistant** | Upload `sample_contract_msa_nordwind.pdf`, analyse | Every clause carries a page number and an excerpt |
| **7. Inventory Predictor** | Forecast 6 periods from 2026-07-01 | 15 materials; each says which model was chosen and why |
| **8. Test Case Generator** | Generate a suite, edit a step, then look at the approval | Editing the script clears the approval it had earned |
| **9. Blueprint Generator** | Generate, approve the summary, then edit the scope | The approval is kept *and* flagged as stale |
| **10. Interview Coach** | Answer three questions, open the dashboard, then download the PDF | The study plan quotes the same averages the dashboard shows; the transcript prints the keyword that credited each concept |

### 6. Try the things that are meant to fail

The honest behaviour is easier to see than the correct behaviour:

```bash
# A PDF posted to a spreadsheet endpoint - two allow lists, deliberately separate
curl -s -F "file=@data/sample/sample_contract_msa_nordwind.pdf" "$API/spend/upload" | python3 -m json.tool
# -> 400 file_validation_error, naming the types it does accept

# A file with an unreadable number - reported, not fatal
printf 'LIFNR,NAME1,OTD,RISK_SCORE\n0000392900,Acme,95,not-a-number\n' > /tmp/bad.csv
curl -s -F "file=@/tmp/bad.csv" -F "dataset=profiles" "$API/supplier-risk/upload" |
  python3 -m json.tool | grep -A5 data_quality
# -> 200, with the problem described row by row

# A question the loaded data cannot answer
curl -s -X POST "$API/supplier-risk/chat" -H 'Content-Type: application/json' \
  -d '{"question": "What is this supplier'"'"'s share price?"}' | python3 -m json.tool
# -> data_available: false, and a reason. Not a guess.
```

In the UI, upload
[`data/sample/sample_contract_hostile_calder.pdf`](data/sample/) to the Contract Assistant. It is a
contract with prompt-injection bait written into its text. The page flags it, analyses it as data,
and the sentence the bait was trying to get printed does not appear anywhere in the result.

### 7. Check everything yourself

```bash
python scripts/check_quality.py     # lint, secret scan, dependency audit, full test suite
```

### 8. Reset

```bash
python scripts/reset_demo.py --yes --seed    # back to step 2
```

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
contracts, delivery and invoice issues, recommended actions -> ask the copilot -> export.

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

### Exports

XLSX (Summary, Portfolio, Category Scores, Evidence & Missing Data, Recommended Actions and
Methodology sheets), CSV (the ranked portfolio table, ready to paste into a supplier review deck)
and JSON (everything, including every metric's raw value and contribution). Passing
`supplier_id=` exports one supplier's profile on its own - the same route, filtered, so a
single-supplier report cannot drift from the portfolio one.

The Category Scores sheet prints the score, the weight, the renormalised weight and the
contribution side by side, so the overall score can be rebuilt from the file rather than taken on
trust. A category with no data is written as **unscored**, never as zero - a supplier marked on
four categories and one marked on ten produce the same kind of number, and only the report says
which is which.

> **No live external data.** No financial, credit, ESG, sanctions or news service is contacted.
> Every figure comes from the uploaded internal records, and nothing here has been validated in a
> live SAP environment. Every export repeats this in full: no credit bureau, sanctions list, news
> feed, court register or ESG rating agency contributed to any score in it.

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

## Module 9 - SAP Blueprint Generator

Describe an SAP implementation project; get a thirty-section blueprint you can edit, approve,
version, compare and export. Module 8 was the first where the AI output *is* the deliverable; this
one is the first where the deliverable is a **document under review** - so the interesting rules
are about what happens to it *after* it is written.

**Workflow:** project form -> deterministic skeleton -> optional AI drafting -> field-by-field
repair -> section navigator -> edit / regenerate / approve -> add or delete custom sections ->
save a version -> compare versions -> export.

### The thirty sections

Executive summary · Business objectives · Scope · Out-of-scope items · Assumptions · Current-state
process · Future-state process · Process steps · SAP products and modules · SAP Best Practice
alignment · Organizational structure · Master data · Configuration requirements · Functional
requirements · Nonfunctional requirements · Integrations · Interfaces and APIs · Data migration ·
Security roles · Controls · Reporting requirements · Test strategy · SIT scenarios · UAT scenarios
· Training · Cutover activities · Hypercare · Risks · Dependencies · Open decisions

The list, the order and the identifiers (`BP-EXEC`, `BP-SCOPE`, `BP-ORG` ...) are fixed in code and
configuration, so two blueprints from this lab can be read side by side.

### What is decided by code, and what is written by a model

| Decided by deterministic Python | Written by the AI provider |
| --- | --- |
| Which sections exist, what they are called and their order | The narrative of each section |
| Which project inputs each section requires, and whether they were supplied | The wording of the items in the sections that accept drafted items |
| The organisational structure, module list, integration register, interface list, migration sources and security roles - each computed from the project request | |
| Every section and item identifier, and the item numbering | |
| Every size limit and every repair of drafted text | |
| The completeness and approval percentages | |
| Every approval, version snapshot and version comparison | |
| Which section describes another section that has since changed | |

**A model may describe the organisational structure; it may never add a plant to it.** Six sections
are computed entirely from the project request, and a drafted item returned for one of them is
discarded and the attempt reported.

### A section with no input is not a section to invent

This is the rule the module is built around. Leave the integrations field empty and the
Integrations section comes back marked `needs_input`, naming the field to fill in - it does not
list three plausible interfaces nobody asked for. The heading stays in the document, because a
blueprint *missing* its Integrations heading reads as a project with no integrations, which is a
different claim from "nobody told us".

Supply the field later (`PUT /blueprints/{id}` with a `project` block) and the section is rebuilt.
The same call re-derives every factual section, because a blueprint whose organisational structure
disagrees with its own project request is worse than one that is out of date.

### A section that summarises another records which version it read

The executive summary describes the scope. The SIT scenarios describe the process steps. The
cutover plan describes the migration. Every section carries a `content_revision`, and a dependent
section records the revisions it was written against - so editing the scope marks the executive
summary as describing a scope that has moved on, instead of leaving it quietly wrong.

The pair that matters most is **approved + stale**. The approval is real - somebody gave it - so it
is kept, but it was given to a description of something that has since changed. It is flagged on
the section (`approval_is_stale`), counted on its own in the summary (`stale_approved_count`) and
printed next to the approver's name in every export. "Approved by Ingrid" over a scope Ingrid never
read is the single most misleading state this document can be in.

### Versions

`POST /blueprints/{id}/versions` freezes the sections as data, so editing the document tomorrow
cannot change what version 1 says today. `GET .../versions/compare?from=1&to=2` diffs them, and
`to=0` means "the blueprint as it stands now" - what have I changed since I last saved?

Two matching decisions make the diff readable: sections are matched by **key**, never by position
(insert one custom section at the top and a position-matched diff calls everything below it
rewritten), and items are matched by **title**, never by identifier (identifiers are renumbered on
every edit).

### Editing rules worth knowing

- **Custom sections can be deleted; the thirty standard ones cannot.** A reader who finds
  twenty-nine headings cannot tell whether the thirtieth was considered and dropped or never
  written. Record that a standard section does not apply by editing it.
- **A custom section identifier is never reissued.** Delete `BP-CUS-001` and the next custom
  section is `BP-CUS-002`, even when nothing is left to read the number from - a review comment
  written against a name has to keep meaning what it meant.
- **Editing the content clears the approval**; editing only the status or a comment does not.
- **A section waiting for project input cannot be approved.** Approving a heading that says
  "nothing was written here" would make the completeness figures describe a document that does not
  exist.

### Every failure mode ends with a usable document

| What went wrong | What happens |
| --- | --- |
| No API key, or `use_ai=false` | The configured templates write every section. The document is complete and labelled `rule_based` |
| The provider is down or times out | Same, plus the error is reported on the blueprint |
| The response is not JSON, or is the wrong shape | Same |
| One drafting batch of six sections fails | Only those six fall back to the template; the rest keep their drafts |
| The response skips a section, or names one that does not exist | The section is templated / the entry discarded, and both are reported |
| A drafted section has a blank narrative, or two hundred items | Repaired field by field against the configured limits, with every repair recorded |
| A drafted item arrives for a section computed from the project request | Discarded, and the attempt reported on the section |

### Exports

Markdown (the format a blueprint actually travels in - straight into a wiki or a pull request),
JSON (everything), DOCX (real heading styles, so Word can build a table of contents and a reviewer
can comment on a section) and PDF (the read-only copy that gets forwarded). Every format carries
the disclaimer, the provenance of each section, the sections still waiting for input and any
approval that predates a later change.

> **A proposal, not a validated design.** Every blueprint is drafted from a project request typed
> into this application. It requires review by qualified SAP professionals, no configuration,
> structure, interface, role or migration approach in it has been validated against a live SAP
> system, and this application is not connected to one.


---

## Module 10 - SAP Interview Coach

Practise SAP interview questions and get a structured, explainable score. Modules 8 and 9 were the
ones where the AI output *is* the deliverable. Here the deliverable is a **score about a person**,
which pushes the line back the other way: the rubric marks the answer and a model is only ever
asked for the coaching prose around a verdict it cannot revisit.

**Workflow:** pick tracks, mode, difficulty and a seed -> seeded question selection -> one question
at a time, without its marking scheme -> answer -> rubric score plus feedback -> next question ->
complete -> session summary -> performance dashboard across every session -> export.

### Tracks and modes

Nine tracks - SAP MM · SAP Ariba · SAP S/4HANA · SAP Business Network · SAP integration · SAP
architecture · Procurement · Supply chain · SAP consulting scenarios - and six modes: **practice**
(untimed, mixed difficulty), **timed** (180s per question), **technical** (accuracy weighted
highest), **architecture** (advanced and expert only, architecture weighted highest),
**behavioral** (clarity and business understanding weighted highest) and **rapid-fire** (60s, and a
narrower clarity length band, because a rapid-fire answer is not a short essay).

Each mode's question count, time limit, difficulty mix and dimension weights live in
`app/modules/interview_coach/config/interview_rules.json`.

### The question bank

104 fictional questions, each carrying a question id, track, topic, difficulty, the modes it is
offered in, the expected concepts with their keyword lists and weights, the statements known to be
wrong for it, suggested follow-ups and a reference answer.

The generator refuses to write the bank unless **every reference answer scores full concept
coverage against its own rubric**. A model answer that does not match its own keyword list is a
bank bug that would show up as a candidate losing marks for saying exactly the right thing.

### How an answer is scored

| Dimension | Comes from |
| --- | --- |
| Technical accuracy | Coverage of the technical concepts, minus the cost of any known-wrong statement |
| Completeness | Weighted coverage of every expected concept, minus missing *required* ones |
| Clarity | The shape of the answer: length, sentence length, signposting, filler |
| Business understanding | Coverage of the business concepts |
| Architecture | Coverage of the architecture concepts - **reported blank, never zero, when the question carries none** |

The overall score is the weighted mean of the dimensions that apply, and the weight of a dimension
that does not apply is shared among the rest rather than counted as a zero. Every response also
carries the strengths, the missing concepts, the incorrect statements with their corrections, an
improved sample answer, a follow-up question **chosen for the highest-weighted concept the
candidate missed**, and the topics to study.

Three details worth knowing:

- **Matching is keyword based, and the page says so.** The keyword that credited each concept is
  shown next to it, because an answer phrased in words the bank does not list will score lower than
  it deserves and a candidate is owed that fact.
- **A phrase inside a negation is not the phrase.** "The goods receipt does not update stock"
  contains the vocabulary and asserts the opposite, so a cue in the same clause within a few words
  vetoes the hit.
- **The clock never moves a score.** Time spent is recorded, reported and summarised; no dimension
  is raised or lowered by it. A rubric marks what was said.

### Sessions and the performance dashboard

Every session stores the questions asked, the answers, the scores, the feedback, the time spent and
the summary. The dashboard aggregates across sessions: average score, score by topic, by
difficulty, by track and by dimension, score over time, weak areas, strong areas, a recommended
study plan and the recent sessions.

The study plan is derived from the data, never written: the topics it names are those averaging
below the threshold, and the concepts it says to focus on are the ones those answers actually
missed, counted. A topic needs more than one answer before it can be *called* a weakness, and a
topic you are strong at never appears in the plan at all.

### Every failure mode ends with a usable result

| What went wrong | What happens |
| --- | --- |
| No API key, or `use_ai=false` | The templates write the feedback. **The scores are byte-for-byte identical** |
| The provider is down, times out, or returns rubbish | Same, plus the error is reported on the answer |
| The drafted coaching note is empty, or the sample answer is two words | Repaired field by field against the configured limits, with every repair recorded |
| A model tries to congratulate you on a concept the rubric marked missing | Discarded - the strengths, missing concepts and corrections are findings, not prose |
| The answer contains prompt-injection bait | Filtered before any provider is called, reported on the answer, and the answer is still marked normally |
| A question's rubric is retuned after a score was given | The score is kept, flagged `scoring_is_stale` and counted separately |

### Endpoints

```text
POST /api/v1/interviews/start                 start a session, serve question 1
GET  /api/v1/interviews/{session_id}          the session, its answers and its summary
POST /api/v1/interviews/{session_id}/answer   mark one answer, serve the next question
POST /api/v1/interviews/{session_id}/complete close the session, return the summary
GET  /api/v1/interviews/{session_id}/export   download the transcript and feedback
GET  /api/v1/interviews/performance           the performance dashboard
GET  /api/v1/interviews/catalog               tracks, modes, bands, the published rubric
GET  /api/v1/interviews/questions             browse the bank (never with answer keys)
GET  /api/v1/interviews/sessions              list sessions
GET  /api/v1/interviews/bank/info             describe the bundled bank
```

### Exports

XLSX (Summary, Answers, Dimension Scores, Concept Coverage and Study Plan sheets), CSV (one row
per answer), JSON (everything) and PDF (the readable transcript - one page per question with the
answer, the marks, the strengths, the missing concepts, the corrections and the improved answer
underneath it).

Two things the file has to carry that a score alone does not: the **keyword that credited each
concept**, so a mark can be argued with away from the screen, and a dimension the question did not
test printed as *not applicable* rather than as a zero. Every format states that this is practice
feedback rather than an assessment, and labels which text came from the rubric and which from an
AI provider or the mock.

> **Not a qualification.** The question bank is entirely fictional, the scores come from the rubric
> published in this repository rather than from any SAP certification scheme, and no answer here has
> been reviewed by SAP.


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
| Marking an interview answer: every dimension, the band, the study plan | ✅ | ❌ never |
| A blueprint's section list, organisational structure, interfaces, roles and versions | ✅ | ❌ never |
| Rewriting a finding in business language | | ✅ |
| Executive summary | | ✅ |
| Drafting the wording of a test case | | ✅ |
| Drafting the wording of a blueprint section | | ✅ |
| Writing the coaching note and improved answer around a finished score | | ✅ |

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

`python scripts/generate_blueprint_sample_data.py` produces the demo **project requests** the
Blueprint Generator works from - this module has no dataset either, its input is a form:

- **four fictional SAP project requests** (a procure-to-pay rollout for a wholesale distributor, a
  record-to-report project, a retail rollout and a field-services rollout), each ready to post
  straight to `POST /api/v1/blueprints/generate`
- each one is chosen so a deterministic decision is observable: a complete request where nothing
  waits for input; a request with **deliberate holes** in it, where five sections come back saying
  which field to fill in and none of them invents an interface, a source system or a role; a
  request for eight sections listed out of order, returned in the canonical document order; and a
  project description carrying prompt-injection bait
- **6 documented scenarios** in
  [`data/sample/BLUEPRINT_SCENARIO_MANIFEST.md`](data/sample/BLUEPRINT_SCENARIO_MANIFEST.md)
- `expected_blueprint_baseline.json`, recorded with **AI drafting switched off**, so it pins the
  section list, the order, the identifiers, the statuses, the missing inputs, the derived items and
  the readiness figures. Drafted prose is deliberately not baselined.

`python scripts/generate_interview_sample_data.py` produces the **question bank** the Interview
Coach marks against - this module has no dataset either, its input is typed into an answer box:

- **104 fictional interview questions** across nine tracks and four difficulties, each with its
  expected concepts and keyword lists, the statements known to be wrong for it, suggested
  follow-ups and a reference answer
- the generator **marks every reference answer against its own rubric before writing the file** and
  fails loudly if any of them does not achieve full concept coverage, because a model answer that
  cannot satisfy its own keyword list is a bank bug rather than a scoring bug
- **7 documented anchors** in
  [`data/sample/INTERVIEW_SCENARIO_MANIFEST.md`](data/sample/INTERVIEW_SCENARIO_MANIFEST.md), each
  scored four ways - the reference answer, a partial answer, an answer with a known-wrong statement
  appended, and a configured non-answer
- `expected_interview_baseline.json`, recorded with **AI switched off**, pinning every dimension
  score and the rubric fingerprint of all 104 questions. The fingerprints are what let a stored
  score report that the rubric behind it has since changed.


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
  modules/test_case_generator/ planning, builder, ai drafting, engine, service
  modules/blueprint_generator/ planning, rendering, builder, ai drafting, engine, versioning, service
  modules/interview_coach/ question bank, selection, scoring, builder, ai feedback, engine, performance, service
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
pytest                    # everything (1,698 tests, ~3 min)
pytest tests/unit         # 800 - rules, metrics, scoring, forecasting, rubric marking, parsing, rounding
pytest tests/api          # 409 - every endpoint against a temporary database
pytest tests/integration  # 300 - the ten sample datasets, the migrations, the deployment files, the docs
pytest tests/e2e          # 118 - one journey per module, plus the cross-module contracts
pytest -m "not slow"      # skip the suites that process a full dataset
```

Four suites, four questions:

| Suite | Asks |
| --- | --- |
| `tests/unit` | Does this rule, metric or model do the right arithmetic? |
| `tests/api` | Does this endpoint behave - status codes, validation, persistence? |
| `tests/integration` | Does the engine find everything the sample manifest says is there? |
| `tests/e2e` | Does the *journey* work, and do the ten modules agree with each other? |

`tests/e2e` is where the cross-cutting contracts live, and most of them read the generated OpenAPI
document, so a new module is covered the moment it registers a route:

- **`test_module_workflows.py`** - one test per module, walking the documented path from the first
  call to the downloaded report, against the bundled demo data.
- **`test_cross_module_contract.py`** - one envelope, one error shape, one pagination contract, one
  severity vocabulary, one analysis-status vocabulary, bounded confidence scores.
- **`test_security_contract.py`** - content sniffing, the two allow lists, size limits, traversal
  containment, key redaction, prompt injection, AI timeouts, CORS.
- **`test_performance_contract.py`** - statements per page, `LIMIT` reaching the database, no row
  served twice while paging, the vectorised and per-cell readers agreeing cell by cell.
- **`test_openapi_contract.py`** - every endpoint described, every error documented, the Postman
  collection current.
- **`test_auth_seams.py`** - nothing is refused today, *and* the permission machinery really runs.

The integration suites read the ten manifests and assert that every documented anomaly is actually
detected, which is what makes the sample data a regression test rather than decoration. Details in
[`docs/TESTING.md`](docs/TESTING.md).

### Quality gates

```bash
python scripts/check_quality.py            # all four
python scripts/check_quality.py --fast     # skip the dependency audit (offline)
```

| Gate | Tool |
| --- | --- |
| Lint | `ruff check` - passes clean |
| Secrets | a scan of every tracked file for credential-shaped strings |
| Dependencies | `pip-audit` - no known vulnerabilities |
| Tests | the full suite |

`ruff format` is deliberately not part of the gate; `pyproject.toml` explains why next to the
configuration.

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
| `CORS_ORIGINS` | localhost:3000, :8501 | Comma separated. `*` disables credentials automatically |
| `ENVIRONMENT` | `local` | `local`, `test`, `staging` or `production` |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `false` | Set `LOG_JSON=true` for a log aggregator |
| `MAX_ROWS_PER_UPLOAD` | 200,000 | Rejected by the reader, before any analysis runs |
| `AI_TIMEOUT_SECONDS` / `AI_MAX_RETRIES` | 30 / 2 | An AI failure never fails an analysis |

The full annotated list is in [`.env.example`](.env.example). Nothing outside
`app/core/config.py` reads `os.environ`.

Switching to PostgreSQL is a one-line change:

```bash
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/sap_ai_lab
alembic upgrade head
```

---

## Security

Every uploaded file is untrusted input, and the whole design follows from that.

| Concern | What is done |
| --- | --- |
| File type | Extension allow-list **plus** a magic-byte check - a `.csv` that is really a ZIP is refused |
| Two allow lists | Tabular (`.csv/.xlsx/.json`) and documents (`.pdf/.docx/.txt/.md`) are separate, so growing one cannot widen the other |
| Size | Enforced **while reading**, not after buffering - an oversized POST costs one chunk, not its whole size |
| Row count | 200,000 rows, refused by the reader before any analysis starts |
| Filenames | Sanitised: no directories, no `..`, no unicode tricks, no control characters |
| Paths | Every read and write resolves through a containment check |
| Secrets | Environment only. Never in source, never in a response, never in a log - a redacting log filter is the backstop |
| Errors | Safe messages: no paths, no stack traces, no provider payloads. The detail is in the log against a request id |
| CORS | Named origins. A `*` origin automatically disables credentials |
| Prompt injection | Filtered before any content reaches a model, and the module that *prints* untrusted text drops the whole sentence around a marker |
| Rendering | Text from a document is HTML-escaped before it reaches the UI |
| AI | Timeouts, a retry ceiling, and a failure that degrades to the deterministic result rather than failing the analysis |
| Dependencies | `pip-audit` in the quality gate; currently clean |

**Instructions found inside an uploaded file are never executed.** The hostile demo contract
(`data/sample/sample_contract_hostile_calder.pdf`) exists to prove it, and there is a test
asserting the payload it carries never appears in a response.

### What is deliberately absent

**There is no authentication.** Every caller can read every analysis and every uploaded file. That
is correct for a local lab and unacceptable for anything reachable from a network. The seams are
built (`app/core/auth.py`, `GET /api/v1/auth-status`) and the plan is written
([`docs/API_AUTHENTICATION_PLAN.md`](docs/API_AUTHENTICATION_PLAN.md)), but nothing is enforced.

Also absent, and deliberately: rate limiting, upload quotas, virus scanning, and background job
processing. See [`docs/DEPLOYMENT_OPTIONS.md`](docs/DEPLOYMENT_OPTIONS.md).

---

## Docker

**Docker is optional.** The lab is meant to run from a virtualenv, and the documentation is
written around that. The image exists so the runtime can be reproduced elsewhere.

```bash
docker compose up api ui                 # SQLite, the default
docker compose --profile postgres up     # + PostgreSQL
docker compose --profile cache up        # + Redis (unused today; see below)
```

- The API is on <http://localhost:8000>, the UI on <http://localhost:8501>.
- One image, three commands: `lab-api`, `lab-streamlit`, `lab-migrate`.
- Two stages, a non-root user, Alembic migrations applied on start, and a healthcheck against
  `/api/v1/health`.
- `lab-data` is a named volume, so uploads, exports and the SQLite file survive
  `docker compose down` (but not `down -v`).
- The optional services sit behind profiles, so `docker compose up` starts nothing you did not
  ask for. **Nothing in this project uses Redis** - it is declared for the day a job queue or a
  shared rate-limit counter needs one, and it is off until then.

API keys are read from your shell (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`), never written into the
compose file, and `.dockerignore` keeps `.env` out of the build context.

---

### The self-hosted public stack

A second compose file describes the published deployment: a Next.js website, the Streamlit
demonstration, FastAPI, PostgreSQL and a Cloudflare tunnel connector.

```bash
cp .env.selfhosted.example .env.selfhosted    # fill it in
./scripts/start_selfhosted.sh --build         # first run builds and seeds
./scripts/verify_selfhosted.sh                # 20 checks
```

**Nothing is published.** There is no `ports:` entry anywhere in
`docker-compose.selfhosted.yml`: the tunnel container dials out, so no host port listens and no
router forwarding exists. Two networks enforce the rest — the API and the database sit on one
declared `internal: true`, and the website is not on it at all, because it never calls them.

For local inspection, `docker-compose.debug.yml` binds the website, the demonstration and
(optionally) the API to `127.0.0.1` only. The database is deliberately absent from that overlay.

| Script | Does |
| --- | --- |
| `start_selfhosted.sh` | Validate the environment, start, wait for health |
| `stop_selfhosted.sh` | Stop. Never touches a volume |
| `restart_selfhosted.sh` | Restart. Does not reseed and does not reset |
| `status_selfhosted.sh` | What is running and how it is configured |
| `logs_selfhosted.sh` | Bounded, rotated container logs |
| `verify_selfhosted.sh` | The boundaries, demo mode, secrets, persistence |
| `reset_public_demo.sh` | Reset the demonstration. Refuses unless `DEMO_MODE=true` |
| `backup_selfhosted.sh` | `pg_dump` with a checksum, optionally verified by restoring |
| `restore_selfhosted.sh` | Restore, or verify into a throwaway database |

---

## Deployment

Four paths, in order of effort: a local virtualenv, Docker Compose, a single VM, a container
platform. Which one is appropriate depends mostly on one question - is it reachable by somebody
who is not you?

**If yes, authentication comes first.** Everything else is tuning.

[`docs/DEPLOYMENT_OPTIONS.md`](docs/DEPLOYMENT_OPTIONS.md) covers all four, plus PostgreSQL, the
AI provider decision, the full configuration reference and a pre-launch checklist.

---

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `ModuleNotFoundError` on any import | The virtualenv is not active. `source .venv/bin/activate` |
| `python: command not found` | Use `python3.12`. Check with `python3 --version` - 3.12 or newer |
| `verify_setup.py` reports missing packages | `pip install -r requirements.txt` |
| Streamlit says "API not reachable" | The backend is not running. `uvicorn app.main:app --reload` in another terminal |
| Every page is empty | Nothing is loaded yet. `python scripts/seed_database.py` |
| "The sample dataset has not been generated yet" | `data/sample/` was deleted. Re-run the matching `scripts/generate_*_sample_data.py` |
| Upload rejected: "File type '.pdf' is not supported" | Correct behaviour. Modules 1-5 and 7 take spreadsheets; only module 6 takes documents |
| Upload rejected: "does not look like a valid .csv" | The extension does not match the contents. A `.csv` that is really a workbook is refused |
| Contract reports `needs_ocr: true` | The PDF is a scan with no text layer. Set `OCR_PROVIDER`, or use a text-based PDF |
| Analysis is slow on a large file | Analyses are synchronous and CPU-bound. The limit is 200,000 rows; see the background-worker seam in the integration doc |
| `alembic upgrade head` says "already at head" but tables are missing | `alembic_version` survived a manual delete. `python scripts/reset_demo.py --yes` |
| Tests fail after editing `data/sample/` | The baselines no longer match. Re-run the generator, which rewrites `expected_*_baseline.json` |
| Port 8000 or 8501 already in use | `uvicorn app.main:app --port 8001`, or `streamlit run ... --server.port 8502` |
| `ai_is_mock: true` and you configured a key | The provider name must be set too: `AI_PROVIDER=anthropic` *and* `ANTHROPIC_API_KEY=...` |
| XLSX export fails with a timezone error | Fixed - every workbook is normalised before saving. If it recurs, a builder is bypassing `workbook_to_bytes` |

Still stuck? Every error response carries `meta.request_id`, which is also the `X-Request-ID`
header and appears in the server log. Search the log for it.

---

## Architecture

Six layers, and the rule is that nothing ever calls upward:

```text
Presentation   streamlit_app/          HTTP only, zero business logic
API            app/api/v1/             routes, status codes, wiring
Module logic   app/modules/<name>/     rules, metrics, engines, orchestration
Shared         app/services/           tabular/ files/ documents/ exports/ ai/
Data           app/models/ app/schemas/
Core           app/core/               config, logging, exceptions, security, auth
```

The separation is enforced rather than encouraged: a Streamlit page cannot import a rule, so it
cannot quietly become the place logic lives. Deleting `streamlit_app/` breaks no test.

Three decisions the whole project is organised around:

**Code computes, AI explains.** Every number - every score, saving, ranking, exception, forecast
and mark - comes from ordinary Python. A model is asked for language, never for a value, and its
output lands in separate fields labelled `ai_generated` or `mock_ai`. Modules 8 and 9 move the
line, not erase it: there the AI writes the artefact, and code writes its skeleton first.

**Thresholds live in JSON.** Every rule reads its numbers from
`app/modules/<module>/config/*.json`, validated by Pydantic on load. Each module has a test proving
a configuration edit changes the outcome with no code change.

**Every output says where it came from.** `rule_based`, `forecast`, `ai_generated`, `mock_ai` or
`demo_data`, on every value a user sees.

Full detail, including the data flow of one analysis and where a new module goes:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Documentation

| Document | Contents |
| --- | --- |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Layers, data flow, design decisions |
| [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md) | macOS, Windows and Linux setup |
| [`docs/TESTING.md`](docs/TESTING.md) | Test strategy and how to add a rule test |
| [`docs/API_OVERVIEW.md`](docs/API_OVERVIEW.md) | Endpoints, envelope, examples |
| [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) | What each module does and what it cost to build |
| [`docs/FINAL_BUILD_REPORT.md`](docs/FINAL_BUILD_REPORT.md) | The Phase 5 report: inventories, test results, limitations, next steps |
| [`docs/FUTURE_WEBSITE_INTEGRATION.md`](docs/FUTURE_WEBSITE_INTEGRATION.md) | Replacing Streamlit with React/Next.js, with TypeScript examples |
| [`docs/API_AUTHENTICATION_PLAN.md`](docs/API_AUTHENTICATION_PLAN.md) | JWT, users, organisations, workspaces, RBAC, tenant isolation |
| [`docs/DEPLOYMENT_OPTIONS.md`](docs/DEPLOYMENT_OPTIONS.md) | Four deployment paths, PostgreSQL, Redis, the pre-launch checklist |
| [`examples/typescript-client/`](examples/typescript-client/) | A runnable TypeScript client and the seven calls a front end needs |
| [`docs/openapi.json`](docs/openapi.json) | The API contract, committed so a change is a diff |
| [`docs/postman_collection.json`](docs/postman_collection.json) | Every request, in one folder per module, generated |
| [`data/sample/*_MANIFEST.md`](data/sample/) | What every deliberate anomaly in each demo dataset is |

### Publishing it

| Document | Contents |
| --- | --- |
| [`docs/PUBLIC_DEMO_DEPLOYMENT.md`](docs/PUBLIC_DEMO_DEPLOYMENT.md) | Public demonstration mode: what each switch changes, guided demonstrations, seeding and reset |
| [`docs/MACBOOK_SELF_HOSTING.md`](docs/MACBOOK_SELF_HOSTING.md) | Running it from a MacBook: Docker resources, sleep, heat, FileVault, updates, scheduling |
| [`docs/CLOUDFLARE_TUNNEL_SETUP.md`](docs/CLOUDFLARE_TUNNEL_SETUP.md) | The tunnel, the three routes, and the Access policy on the demonstration |
| [`docs/GODADDY_NAMESERVER_SETUP.md`](docs/GODADDY_NAMESERVER_SETUP.md) | Moving DNS without breaking mail |
| [`docs/DEMO_SECURITY_CHECKLIST.md`](docs/DEMO_SECURITY_CHECKLIST.md) | What to verify before anyone else can reach it |
| [`docs/BACKUP_AND_RECOVERY.md`](docs/BACKUP_AND_RECOVERY.md) | Backups, checksums, and testing a restore before you need one |
| [`docs/SELF_HOSTED_TROUBLESHOOTING.md`](docs/SELF_HOSTED_TROUBLESHOOTING.md) | Symptoms, causes and fixes |

---

## A standing caveat

This is demo software built to learn and to demonstrate. Every dataset in it is fictional and was
written for this lab. **No module connects to an SAP system, nothing here has been validated in a
live SAP environment, and every savings figure is a model under stated assumptions rather than a
guaranteed result.** The software labels all of that on every screen and in every export; anything
built on top of it should keep doing so.
