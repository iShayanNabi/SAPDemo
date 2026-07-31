# Local setup

Everything runs locally. You do **not** need SAP credentials, an AI API key, a paid API, Docker or
PostgreSQL.

**Requirements:** Python 3.12+ and about 500 MB of disk space.

---

## macOS

```bash
# 1. Python 3.12 (skip if `python3 --version` already reports 3.12+)
brew install python@3.12

# 2. Get into the project folder
cd sap-ai-lab

# 3. Virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# 4. Dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 5. Optional settings file (defaults work without it)
cp .env.example .env

# 6. Health check (the demo datasets already ship with the repository)
python scripts/verify_setup.py
```

On Apple Silicon everything installs as native arm64 wheels; no Rosetta needed.

---

## Windows (PowerShell)

```powershell
# 1. Install Python 3.12 from python.org or:
winget install Python.Python.3.12

# 2. Project folder
cd sap-ai-lab

# 3. Virtual environment
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1

# 4. Dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# 5. Optional settings file
Copy-Item .env.example .env

# 6. Health check (the demo datasets already ship with the repository)
python scripts\verify_setup.py
```

If activation is blocked:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Use `python` (not `python3`) inside an activated venv on Windows, and backslashes in paths.

---

## Linux (Debian / Ubuntu)

```bash
# 1. Python 3.12 and venv support
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip

# 2. Project folder
cd sap-ai-lab

# 3. Virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# 4. Dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 5. Optional settings file
cp .env.example .env

# 6. Health check (the demo datasets already ship with the repository)
python scripts/verify_setup.py
```

Fedora/RHEL: `sudo dnf install python3.12 python3-pip`.

---

## Demo data

**The demo datasets are committed to the repository, so a fresh clone already has them.** You do not
need to run any generator before `python scripts/verify_setup.py`, before `pytest`, or before using
the app - all three work on a clean checkout.

`data/sample/` ships one dataset per module, each as CSV, XLSX and JSON, together with the scenario
manifests and the recorded baselines the integration tests assert against:

| Script | Produces |
| --- | --- |
| `scripts/generate_sample_data.py` | `sample_purchase_orders.*` and the anomaly manifest (module 1) |
| `scripts/generate_spend_sample_data.py` | `sample_spend_transactions.*` (module 2) |
| `scripts/generate_supplier_sample_data.py` | `sample_suppliers.*` (module 3) |
| `scripts/generate_invoice_sample_data.py` | `sample_invoices.*`, `sample_invoice_purchase_orders.*`, `sample_goods_receipts.*` (module 4) |
| `scripts/generate_supplier_risk_sample_data.py` | `sample_supplier_risk_profiles.*`, `sample_supplier_risk_events.*` (module 5) |
| `scripts/generate_contract_sample_data.py` | `sample_contract_*.{txt,pdf,docx}` - six fictional contracts (module 6) |

You only need to run one of them if you have deleted or edited the files in `data/sample/`, or if
you are changing a generator itself. Every generator is seeded, so re-running it reproduces the same
data byte for byte - and also rewrites that module's `expected_*_baseline.json`, which is what the
integration tests compare against.

---

## Running the lab

Two processes, two terminals. Both need the virtual environment activated.

**Terminal 1 - the API**

```bash
uvicorn app.main:app --reload
```

- API root: <http://127.0.0.1:8000>
- Interactive docs: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/api/v1/health>

**Terminal 2 - the interface**

```bash
streamlit run streamlit_app/Home.py
```

- UI: <http://localhost:8501>

Open the UI, choose **PO Risk Checker** or **Spend Analytics**, download the sample file from the
left panel, upload it, and run the analysis.

The Streamlit app shows a clear error if the API is not running - it never fabricates results.

---

## First run walkthrough

1. Download `sample_purchase_orders.csv` from the sample panel (it uses SAP technical headers).
2. Upload it. The mapper should map all 25 columns with no manual correction.
3. Review the preview and the confidence shown under each mapped column.
4. Click **Run analysis**. Expect roughly 131 findings on the demo data, and a risk score near 8.
5. Filter the findings table by severity `critical`.
6. Download the Excel report - five sheets, including Methodology.
7. Compare a finding against `data/sample/ANOMALY_MANIFEST.md` to see the anomaly that was
   deliberately planted.

### Spend Analytics

1. Download `sample_spend_transactions.csv` (SAP technical / spend-cube headers).
2. Upload it. All 33 columns should map with no manual correction.
3. Click **Run analysis**. Expect roughly 45M EUR of spend over 24 months, about 3.7% maverick
   spend and around 2.3M EUR of *estimated* savings opportunity.
4. Filter to one category or a date range and watch every KPI, chart and table follow.
5. In **Drill into transactions**, pick a supplier and confirm the transaction total matches the
   figure in the supplier table.
6. Open a savings opportunity and read its **method** field - it states the arithmetic so you can
   check the number rather than trust it.
7. Compare what you see against `data/sample/SPEND_SCENARIO_MANIFEST.md`.

---

## Optional: use a real AI model

Mock mode is the default and needs nothing. To use a real model, put a key in `.env`:

```bash
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
# or
AI_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

Restart the API. `GET /api/v1/po-risk/ai-status` reports the active provider. Only narrative text
changes - risk findings are identical either way, because they never come from a model.

Keys are read from the environment only. They are never logged (the logger redacts key-shaped
strings), never returned by an endpoint, and never sent to the browser.

---

## Optional: PostgreSQL instead of SQLite

```bash
pip install "psycopg[binary]"
```

```bash
# .env
DATABASE_URL=postgresql+psycopg://sap_lab:password@localhost:5432/sap_ai_lab
```

```bash
createdb sap_ai_lab
alembic upgrade head
```

No application code changes.

---

## Database migrations

```bash
alembic upgrade head                              # apply
alembic revision --autogenerate -m "description"  # create after a model change
alembic downgrade -1                              # roll back one revision
alembic current                                   # show the applied revision
```

For local development `init_db()` also creates any missing tables at startup, so migrations are
only strictly needed when you change a model.

---

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `ModuleNotFoundError: app` | Run commands from the project root with the venv activated. |
| Streamlit: "Cannot reach the API" | The API is not running, or `API_BASE_URL` is wrong. Start `uvicorn app.main:app --reload`. |
| "No sample file yet" | The demo files ship with the repository, so this means they were deleted from `data/sample/`. Restore them with `git checkout -- data/sample/`, or re-run that module's generator (see [Demo data](#demo-data)). |
| `Address already in use` | Another process holds the port: `uvicorn app.main:app --port 8001` (then set `API_BASE_URL` to match) or `streamlit run ... --server.port 8502`. |
| Upload rejected: "does not look like a valid ... file" | The extension and the actual content disagree (for example a CSV renamed to `.xlsx`). Re-export in the right format. |
| `.xls` rejected | Legacy binary Excel is not supported. Save as `.xlsx`. |
| Analysis rejected: missing required fields | The mapper could not find PO number, item, supplier, quantity, unit price or order date. Map them by hand in the mapping panel. |
| Slow analysis on a very large file | 1,200 rows take ~2 s. Files of several hundred thousand rows will be slower; `MAX_ROWS_PER_UPLOAD` caps the size. |
| Tests skipped | A sample dataset is missing from `data/sample/`. On a clean checkout nothing is skipped, because the demo data is committed - so this means the files were deleted. Restore them with `git checkout -- data/sample/`, or re-run the generator for the module named in the skip message (see [Demo data](#demo-data)). |
| Spend: "A date column is required" | Neither a transaction date nor an order date was mapped. Map one in the mapping panel. |
| Spend: "A spend value is required" | Map a total value column, or both quantity and unit price. |
| Spend savings look too large or too small | They are modelled estimates. Tune the assumptions in `app/modules/spend/config/spend_rules.json` - especially `realization_factor` and `assumed_saving_pct`. |

---

## Resetting local state

```bash
rm -f data/*.db                       # drop the local database
rm -f data/uploads/* data/exports/*   # clear stored uploads and reports
```

That is the whole reset. `data/sample/` is committed and is never written to by the app, so there is
nothing to regenerate here - the demo datasets survive the reset untouched.

If you did edit or delete something under `data/sample/`, restore it with:

```bash
git checkout -- data/sample/
```

Nothing outside the project folder is touched. The test suite uses its own temporary directory and
database, so running `pytest` never affects your local data.
