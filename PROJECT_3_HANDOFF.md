# Project 3 Handoff

**SAP AI Application Lab** — state of the repository after Project 3.

Packaged: 2026-07-31 · Tests: **456 passing** · Modules complete: **3 of 10**

---

## 1. What Project 3 added

### Module 3 — Supplier Recommendation Engine

Upload a supplier master file, describe a purchasing requirement, tune the scoring weights and get
a transparent, deterministic ranking of the eligible suppliers.

- **19 supplier fields** reusing the shared `FieldRegistry` and SAP alias conventions (`LIFNR`,
  `WAERS`, `ZTERM`); materials, plants and regions served are multi-valued columns split into lists.
- **7 eligibility filters** applied before ranking — material, plant, capacity (incl. covering the
  quantity), quality, risk tolerance, sustainability (min ESG), contract requirement — each with a
  human-readable reason and each switchable in configuration.
- **9 normalized scores** (cost, delivery, quality, capacity, risk, ESG, contract, geographic, past
  performance), combined with **user weights that must total 100%** (rejected 422 otherwise).
- Per-supplier **estimated total cost**, **estimated delivery date**, **advantages**, **risks** and a
  rule-based **explanation**. AI summarises the ranking; **it never determines it**.
- **13 API routes** across two prefixes (`/suppliers`, `/supplier-recommendations`), a Streamlit
  page, and a **55-supplier demo catalogue** with **7 documented anchors**.

---

## 2. Architecture decisions specific to module 3

### Requirement-driven, catalogue-based

Unlike modules 1 and 2 (upload one file → analyse it), module 3 scores a *requirement* against a
persisted *supplier catalogue*. Upload loads a catalogue (`supplier_catalogs` + `suppliers`);
`recommend` references a catalogue by id (defaulting to the most recent) and scores it. This is why
`GET /suppliers` and `GET /suppliers/{id}` are meaningful standalone endpoints.

### Deterministic engine, AI only describes

Eligibility, the nine scores, the weighted overall and the ranking are ordinary Python. The
`ai_narrative` layer summarises the finished ranking in separate fields, labelled with an
`OutputOrigin`, and an AI failure never blocks the recommendation. Mock AI is the default.

### Relative scoring, documented

Cost, lead time, capacity (when no quantity is given) and past performance are min-max normalised
across the *eligible pool*. A score is therefore a within-shortlist comparison, not an absolute
rating — stated in `GET /supplier-recommendations/scoring` and the methodology block. Missing data
scores 0 (conservative).

### Everything configurable

`app/modules/supplier_reco/config/supplier_reco_rules.json` holds the default weights, every
scoring blend, the eligibility toggles, the contract-status classification lists and the
advantages/risks thresholds, validated by Pydantic at load.

---

## 3. API routes (13)

Base: `/api/v1` · Envelope: `{success, data, error, meta}`

| Method | Path |
| --- | --- |
| POST | `/suppliers/upload` |
| GET | `/suppliers` · `/suppliers/{supplier_id}` · `/suppliers/catalogs` |
| GET | `/suppliers/fields` · `/suppliers/sample` · `/suppliers/sample/info` |
| POST | `/supplier-recommendations/recommend` |
| GET | `/supplier-recommendations` · `/supplier-recommendations/{id}` |
| GET | `/supplier-recommendations/{id}/export` |
| GET | `/supplier-recommendations/scoring` · `/supplier-recommendations/ai-status` |

**38 paths total** in the OpenAPI schema (25 before module 3 + 13 new); the `/` index now lists
three available modules.

---

## 4. Database changes

Four tables in one Alembic revision (`a16bad79dd24`, down-revision `3c761d0c43df`):

| Table | Holds |
| --- | --- |
| `supplier_catalogs` | one row per uploaded supplier master file |
| `suppliers` | normalised supplier master data (lists stored as JSON) |
| `supplier_recommendations` | requirement, weights, eligibility summary, AI narrative |
| `supplier_recommendation_entries` | one row per supplier: rank, 9 sub-scores, cost/delivery, advantages, risks, explanation |

`uploaded_files` is reused with `module="supplier_reco"`. Batch mode migration verified
`upgrade → downgrade -1 → upgrade`; a fresh database creates all 11 tables. Models are exported
from `app/models/__init__.py`.

---

## 5. Test results

```
456 passed in ~100s
```

| Layer | Count | New in P3 |
| --- | --- | --- |
| `tests/unit` | 270 | +31 (scoring, eligibility) |
| `tests/api` | 112 | +17 |
| `tests/integration` | 74 | +14 |

The 394 module 1+2 tests passed **unchanged** — no existing behaviour was altered. The integration
suite reads `supplier_scenario_manifest.json`, asserts each documented anchor behaves as described,
and checks the canonical ranking reproduces `expected_supplier_baseline.json` exactly, twice.

### Bug found during the build (run-the-thing)

The generator wrote no-contract suppliers with the literal string `"None"`, which the file reader
treats as a null placeholder. The value survived in the in-memory baseline but became `null` on the
CSV round-trip the API performs, so the recorded baseline disagreed with the API by one contract
score. Fixed by using the label `"No contract"` and computing the baseline from the written file
read back through the real reader/normaliser. Every unit test had passed; the baseline-reproduction
check caught it.

---

## 6. Known limitations (module 3)

- Relative scores shift as the eligible pool changes; a score is a within-shortlist comparison.
- Missing supplier attributes score 0, penalising unreported fields.
- Estimated cost/delivery are indicative planning figures, not quotations; the estimated delivery
  date needs a planned order date.
- The catalogue is global and unversioned beyond the upload; a recommendation references it by id
  but does not snapshot it.
- Currency conversion uses fixed configured rates.
- Project-wide: no auth, no rate limiting, synchronous analysis, SQLite-only CI (all as before).

---

## 7. What the next module should reuse

Everything modules 1 and 2 exposed, plus the module-3 patterns:

| Need | Use |
| --- | --- |
| Field contract | `FieldRegistry` — reuse SAP aliases; flag multi-valued columns and split in the normaliser |
| Config | `thresholds.py` + `config/*.json`, Pydantic-validated (module 3 also validates the weights) |
| Requirement-style input | a plain dataclass (`requirement.py`) the engine depends on, converted from the Pydantic request schema |
| Determinism baseline | compute it by reading the written sample file back through the real reader/normaliser, never from in-memory rows |

### Recommended next step

**Module 4 — Invoice Validator.** Three-way matching reuses the purchase order contract again and
adds the genuinely new capability of joining *two* uploaded files. Weigh it against the standing
operational work (authentication, a job queue, a PostgreSQL run), whose cost grows with each module
now that three share one database and upload table.

---

## 8. Verification commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python scripts/generate_sample_data.py
python scripts/generate_spend_sample_data.py
python scripts/generate_supplier_sample_data.py
python scripts/verify_setup.py            # exits 0

pytest -q                                 # 456 passed

alembic upgrade head

uvicorn app.main:app --reload             # http://127.0.0.1:8000/docs
streamlit run streamlit_app/Home.py       # http://localhost:8501
```
