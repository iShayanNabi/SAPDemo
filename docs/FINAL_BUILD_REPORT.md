# Final build report — Phases 5 and 6

What exists, what it was hardened against, what it still cannot do, and what to
build next.

Phase 5 added no modules. It integrated the ten that existed, made them agree
with each other, drove every one of them by hand, and fixed what that turned up.

---

## 1. Architecture summary

Six layers. Nothing ever calls upward.

```text
Presentation   streamlit_app/          HTTP only, zero business logic
API            app/api/v1/             routes, status codes, wiring
Module logic   app/modules/<name>/     rules, metrics, engines, orchestration
Shared         app/services/           tabular/ files/ documents/ exports/ ai/
Data           app/models/ app/schemas/
Core           app/core/               config, logging, exceptions, security, auth, rounding
```

The separation is structural rather than aspirational: a Streamlit page cannot
import a rule, so it cannot quietly become the place logic lives. Deleting
`streamlit_app/` breaks no test — which is the property that makes a future
website a re-skin rather than a rewrite.

**197 Python modules in `app/`, 135 endpoints, 33 tables, 10 migrations, 1,698 tests.**

### The three decisions everything else follows from

**Code computes, AI explains.** Every number — every score, saving, ranking,
exception, forecast and mark — is produced by ordinary Python from the uploaded
file. A model is asked for language, never for a value. Modules 8 and 9 move
that line rather than erase it: there the AI writes the artefact, and code
writes its skeleton first, so the same request produces the same identifiers,
the same coverage and the same priorities with a real model, with the mock, or
with `use_ai=false`. Module 10 moves it back the other way, because the
deliverable is a *score* and a score that moves because a provider was slow is
not a score.

**Thresholds live in JSON.** Every rule reads its numbers from
`app/modules/<module>/config/*.json`, validated by Pydantic at load. Each module
has a test proving a configuration edit changes the outcome with no code change.

**Every output says where it came from.** `rule_based`, `forecast`,
`ai_generated`, `mock_ai` or `demo_data`, on every value a user sees. A UI that
drops those labels breaks the honesty the design rests on, which is why the
integration doc lists rendering them as an obligation rather than a suggestion.

### What Phase 5 changed structurally

| Added | Why |
| --- | --- |
| `app/core/context.py` | A request-id ContextVar, so every envelope carries the id in the `X-Request-ID` header |
| `app/core/auth.py` | Principal, roles, `require_roles`, `tenant_scope` — declared, exercised, enforcing nothing |
| `app/api/openapi.py` | The description, tag metadata, shared error responses and the auth placeholder |
| `app/models/base.py::UtcDateTime` | Timestamps that are UTC and aware whichever database is underneath |
| `app/models/ordering.py` | Severity ordering as SQL, so paging does not read the whole result set |
| `app/services/exports/workbook.py` | One place that normalises a workbook before saving it |
| `app/services/files/uploads.py` | A size limit enforced while reading rather than after buffering |

---

## 2. Completed modules

All ten, each with rules or models, sample data with a documented manifest, a
recorded baseline, tests at three levels and an end-to-end journey.

| # | Module | What it does | Deterministic core |
| --- | --- | --- | --- |
| 1 | Purchase Order Risk Checker | Finds risks in an SAP-style PO export | 20 rules |
| 2 | Spend Analytics Dashboard | Spend under management, leakage, concentration, savings | 27 metrics, 8 savings models |
| 3 | Supplier Recommendation Engine | Ranks eligible suppliers for a requirement | 9 normalised scores, 7 eligibility filters |
| 4 | Invoice Validator | Three-way match with configurable tolerances | 17 rules |
| 5 | Supplier Risk Copilot | Portfolio risk scoring, then questions answered from the records | 10 weighted categories |
| 6 | Contract Assistant | Clauses, dates, obligations and risks from a document | Clause specs with negation patterns, per-page citations |
| 7 | Inventory Predictor | Demand forecast, stock projection, reorder plan | 5 models chosen by backtesting |
| 8 | SAP Test Case Generator | An editable test suite across 8 test types | Planning, allocation, identifiers, priorities |
| 9 | SAP Blueprint Generator | A 30-section blueprint, editable, versioned | Section graph, 6 computed sections |
| 10 | SAP Interview Coach | Scored, explained interview practice | Keyword rubric across 4 dimensions |

The line each module draws between code and a model is documented per module in
[`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md) and summarised in the
README.

---

## 3. API endpoint inventory

**135 endpoints in 11 tag groups.** Every one has a summary and a description;
every module's routes declare the 400/404/422/500 shapes. The full document is
committed at [`openapi.json`](openapi.json) and as a Postman collection at
[`postman_collection.json`](postman_collection.json), both regenerated by
`python scripts/generate_api_collection.py`.

| Group | Count | Shape |
| --- | --- | --- |
| System | 3 | `GET /`, `/health`, `/auth-status` |
| Purchase Order Risk Checker | 11 | upload → analyze → analyses → findings → export, plus rules/fields/sample |
| Spend Analytics Dashboard | 12 | upload → analyze → transactions/opportunities → export, plus methodology |
| Supplier Recommendation Engine | 13 | suppliers upload/list/detail, recommend → detail → export |
| Invoice Validator | 11 | three uploads → validate → exceptions → export |
| Supplier Risk Copilot | 14 | upload → calculate → suppliers → chat → export |
| Contract Assistant | 12 | upload → analyze → clauses → questions → export |
| Inventory Predictor | 13 | upload → forecast → items → item → export |
| SAP Test Case Generator | 16 | generate, then edit/approve/execute/duplicate/regenerate → export |
| SAP Blueprint Generator | 19 | generate, sections CRUD, approve, versions, compare → export |
| SAP Interview Coach | 11 | start → answer → complete → export, questions, sessions, performance |

Shared conventions, asserted across all of them in
`tests/e2e/test_cross_module_contract.py`:

- One envelope: `{success, data, error, meta}` on every JSON route.
- One error shape, from all four layers — Starlette's router, FastAPI's
  validator, the application's own exceptions, and the unexpected.
- `meta.timestamp` (UTC, aware), `meta.request_id` (matches `X-Request-ID`),
  `meta.api_version` on every response, success or failure.
- Every paged endpoint takes bounded `limit`/`offset` and echoes `total`,
  `limit`, `offset` back.
- Exports return the file itself with `Content-Disposition`, exposed to
  cross-origin clients.

---

## 4. Database model inventory

**33 tables, 10 Alembic revisions, SQLite by default and PostgreSQL-ready.**

| Module | Tables |
| --- | --- |
| Shared | `uploaded_files` (carries a `module` column) |
| 1 | `po_analyses`, `po_findings`, `po_records` |
| 2 | `spend_analyses`, `spend_transactions`, `spend_opportunities` |
| 3 | `supplier_catalogs`, `suppliers`, `supplier_recommendations`, `supplier_recommendation_entries` |
| 4 | `invoice_validations`, `invoice_exceptions` |
| 5 | `supplier_risk_datasets`, `supplier_risk_records`, `supplier_risk_assessments`, `supplier_risk_profiles` |
| 6 | `contracts`, `contract_pages`, `contract_clauses`, `contract_risks`, `contract_obligations` |
| 7 | `inventory_datasets`, `inventory_records`, `inventory_forecasts`, `inventory_forecast_items` |
| 8 | `test_suites`, `test_cases` |
| 9 | `blueprints`, `blueprint_sections`, `blueprint_versions` |
| 10 | `interview_sessions`, `interview_answers` |

Verified by `tests/integration/test_database_schema.py`, which builds the
database the way a deployment does — Alembic from empty, not `create_all`:

- migrations run from an empty database and reverse to nothing;
- autogenerate finds **no drift** between the migrations and the models;
- the PostgreSQL DDL renders (offline, no server needed), including
  `TIMESTAMP WITH TIME ZONE`;
- **every** foreign key is `ON DELETE CASCADE` and indexed;
- SQLite really enforces them (the pragma is set per connection);
- the columns every list endpoint sorts by are indexed.

---

## 5. Test results

```text
1,698 passed in ~3 min
```

| Suite | Tests | Asks |
| --- | --- | --- |
| `tests/unit` | 832 | Does this rule, metric or model do the right arithmetic? |
| `tests/api` | 434 | Does this endpoint behave — status codes, validation, persistence? |
| `tests/integration` | 313 | Does the engine find everything the manifest says is there? Do the migrations, the deployment files and the docs still match? |
| `tests/e2e` | 119 | Does the *journey* work, and do the ten modules agree? |

Phase 5 added 249 tests, almost all of them cross-cutting: one workflow per
module, and five contract suites that read the generated OpenAPI document so a
new module is covered the moment it registers a route. The last 71 came with the
two missing exports, and one of them asserts the *set* of modules that have an
export route rather than a count, so the gap this closed cannot silently reopen.

### Quality gates

`python scripts/check_quality.py`

| Gate | Result |
| --- | --- |
| Lint (`ruff check`) | **Pass** — clean across `app`, `tests`, `scripts`, `streamlit_app`, `migrations` |
| Secret scan | **Pass** — 370 tracked files, nothing credential-shaped, `.env` not tracked |
| Dependency audit (`pip-audit`) | **Pass** — no known vulnerabilities |
| Tests | **Pass** — 1,698 |

`ruff format` is **not** adopted, and `pyproject.toml` says why next to the
configuration: it expands the frozen data tables the regression fixtures are
built from — the 54 values whose mean lands on a rounding tie, the SAP header
maps — into one value per line, turning a nine-line table that can be read at a
glance into fifty-four lines that cannot.

### The eleven defects Phase 5 found

Every one of these passed a green test suite. Nine were found by driving the API
or the UI by hand, or by writing a test that compared two things nobody had
compared before.

| # | Defect | How it was found |
| --- | --- | --- |
| 1 | **Timestamps were naive.** `DateTime(timezone=True)` is a request, not a promise: PostgreSQL honours it, SQLite drops it. The same API served `2026-08-01T01:43:18` locally and `…+00:00` in production, and a browser reads the first as *local* time. | Writing an e2e assertion that `created_at` is parseable and aware |
| 2 | **Every XLSX export would have raised against PostgreSQL.** openpyxl refuses aware datetimes; each builder stripped tzinfo in its own helper, and the summary sheets wrote straight in. | Fixing #1 made the latent failure immediate |
| 3 | **Error responses had no `meta.timestamp`.** Successes were built from `ApiResponse`, failures from a hand-written dict. A client rendering "received at" worked until the first error. | The e2e envelope helper |
| 4 | **A mistyped URL returned `{"detail": "Not Found"}`** — a second error shape, produced by the one request every client makes by accident. | The four-error-shapes test |
| 5 | **`meta.request_id` was on failures and null on successes** — backwards: the response nobody captured a header for is the one that succeeded but looked wrong. | Reading one response top to bottom |
| 6 | **Supplier-risk uploads 500'd on an unparseable number.** The shared normaliser publishes `field`; that module's schema declared `field_name` with no alias and built itself straight from the dict. Every demo file is clean, so nothing hit it. | Consolidating six divergent copies of one schema |
| 7 | **`GET /spend/.../opportunities` paged but never echoed `limit`/`offset`** — a client holding 100 of 137 could not tell that from holding all of them. | Auditing the pagination contract across all 18 paged endpoints |
| 8 | **Module 1's ORM relationships contradicted its own schema.** The tables declare `ON DELETE CASCADE`; the relationships lacked `passive_deletes`, so deleting an upload tried to NULL a NOT NULL column. | The cascade test in the database suite |
| 9 | **`migrations/env.py` overwrote whatever URL it was given** with the one from `.env`, so a caller asking to migrate a temporary database silently migrated the developer's real one. | A test that tried to migrate a temp file |
| 10 | **Uploaded document text was interpolated into raw HTML.** The contract page prints the section heading it found, through `unsafe_allow_html` — so a heading reading `<img src=x onerror=…>` is a one-line edit to a PDF somebody emails to a reviewer. | Reading every `unsafe_allow_html` call and asking where each value came from |
| 11 | **The prompt-injection detector required its words to be adjacent** — it caught "disregard all above rules" and missed "disregard **the** above rules", the way an English speaker writes it. | Parameterising the detector test over realistic phrasings |

Two more worth recording because of what they say about testing:

- **The rounding suite asserted its defect through `sum()`**, which CPython 3.12
  quietly fixed with compensated summation. The test had stopped testing
  anything the day the project moved to 3.12. The defect is alive in every
  `for`-loop accumulation and in the pandas mean module 5 shipped it through;
  the test now asserts it there.
- **A "fast path" that skipped every text column.** The vectorised cell cleaner
  was routed on `series.dtype != object` — but pandas 3.0 returns a dedicated
  `StringDtype` from `read_csv(dtype=str)`, so the guard skipped every text
  column in the project and returned it untrimmed. That version passed the whole
  suite. It was caught by a new test comparing the vectorised and per-cell paths
  cell by cell.

---

## 6. Security notes

### What is enforced

| Concern | Implementation |
| --- | --- |
| File type | Extension allow-list **plus** magic-byte sniff — a `.csv` that is really a ZIP is refused |
| Two allow lists | Tabular and document lists are separate, with a test that growing one does not widen the other |
| Size | Enforced **while reading** (`read_upload_within_limit`), so an oversized POST costs one 512 KB chunk rather than its full size |
| Row count | 200,000, refused by the reader before any analysis |
| Filenames | Sanitised: no directories, no `..`, no unicode tricks, no control characters |
| Paths | Every read and write resolves through a containment check |
| Secrets | Environment only; `repr=False` on every key field; a redacting log filter as the backstop |
| Errors | Safe messages — no paths, no stack traces, no provider payloads. Detail is in the log against a request id |
| CORS | Named origins, named methods and headers. A `*` origin automatically disables credentials |
| Prompt injection | Filtered before any content reaches a model; module 9 additionally drops the whole *sentence* around a marker, because a marker is the lead-in to a payload |
| Rendering | Document text is HTML-escaped before it reaches the UI |
| AI | 30s timeout, 2 retries, and a failure that degrades to the deterministic result |
| Dependencies | `pip-audit` in the gate |

Driven over HTTP in `tests/e2e/test_security_contract.py` (41 tests).

### Dependencies upgraded

`pip-audit` found **43 advisories across four pinned dependencies**, two of them
squarely in this application's attack path:

| Package | Was | Now | Advisories | Why it matters here |
| --- | --- | --- | --- | --- |
| `pypdf` | 5.9.0 | 6.14.2 | 35 | Parses every uploaded contract |
| `python-multipart` | 0.0.20 | 0.0.31 | 6 | Parses every upload body |
| `pydantic-settings` | 2.13.0 | 2.14.2 | 1 | |
| `pytest` | 9.0.1 | 9.0.3 | 1 | |

The audit is now clean and the suite is green on all four.

### What is deliberately absent

**There is no authentication.** Every caller can read every analysis and every
uploaded file. Correct for a local lab, unacceptable for anything on a network.

Also absent: rate limiting, upload quotas, virus scanning, background job
processing, and any multi-tenant isolation. The seams for the first and the last
are built and exercised (`app/core/auth.py`, `GET /api/v1/auth-status`); the plan
is [`API_AUTHENTICATION_PLAN.md`](API_AUTHENTICATION_PLAN.md).

---

## 7. Deployment options

Four paths, covered in full in [`DEPLOYMENT_OPTIONS.md`](DEPLOYMENT_OPTIONS.md).

| Option | For | Effort | Notes |
| --- | --- | --- | --- |
| Local virtualenv | Development, the demo | 5 min | The supported path; what the tests run on |
| Docker Compose | Reproducing the runtime, exercising PostgreSQL | 1 command | Optional services behind profiles |
| A single VM | An internal deployment behind a VPN | An afternoon | uvicorn + nginx/Caddy + PostgreSQL |
| A container platform | A public website's backend | A day + prerequisites | Needs object storage and PostgreSQL; watch request timeouts |

The image is two-stage, runs as a non-root user, applies migrations on start and
declares a healthcheck. `tests/integration/test_deployment_files.py` runs with no
Docker daemon and asserts the healthcheck polls a route the app actually serves —
a check that outlives its route reports *unhealthy* forever while the logs show
nothing wrong.

**Redis is declared and off.** Nothing uses it. Two things will genuinely need
it — a job queue for large uploads, and a rate-limit counter shared across
replicas — and both are named in the plans so the seam is not a surprise.

---

## 8. Acceptance criteria

| # | Criterion | Result |
| --- | --- | --- |
| 1 | FastAPI starts | **Yes** — verified by `uvicorn` on a clean database and driven with `curl` |
| 2 | Streamlit starts | **Yes** — all ten pages load against a live API |
| 3 | Database migrations work | **Yes** — from empty, reversible, no drift, PostgreSQL DDL renders |
| 4 | Demo reset works | **Yes** — `scripts/reset_demo.py` |
| 5 | Sample data generation works | **Yes** — ten generators; `data/sample/` is committed so a fresh clone needs none of them |
| 6 | All ten modules work | **Yes** — one e2e journey each, plus `scripts/seed_database.py` driving all ten |
| 7 | All APIs are documented | **Yes** — 135 endpoints, every one with a summary and description; errors documented; collection generated |
| 8 | Mock AI works without keys | **Yes** — the default, deterministic, asserted |
| 9 | Real AI providers configurable | **Yes** — Anthropic and OpenAI, with timeout, retries, cost tracking and safe degradation |
| 10 | Reports download successfully | **Yes** — all ten modules export (XLSX/CSV/JSON, plus PDF, DOCX and Markdown where they fit). Modules 5 and 10 were the last two; both were driven over the API and through their Streamlit pages before this was marked passed. |
| 11 | Tests pass | **Yes** — 1,698 |
| 12 | Linting passes | **Yes** — `ruff check` clean |
| 13 | Formatting passes | **Qualified** — `ruff check` (including `E` and `I`) is the enforced style gate and passes; `ruff format` is deliberately not adopted, with the reason recorded in `pyproject.toml` |
| 14 | No secrets in source control | **Yes** — 370 tracked files scanned, `.env` git-ignored and excluded from the Docker build context |
| 15 | A future website can use the API without moving business logic | **Yes** — the Streamlit UI already is that website: it imports no business logic and talks HTTP. `examples/typescript-client` performs the same journey and its `npm run demo` passes against a live server. |

### How each one was verified

Not from the test suite. A clean database, both processes started, and the API
driven with `curl` — which is the step this project's own history says finds the
bugs a green suite does not.

```text
alembic upgrade head            10 revisions, empty -> 33 tables
scripts/reset_demo.py --yes     dropped, re-migrated, uploads and exports cleared
scripts/seed_database.py        all ten modules, 0 failures
uvicorn app.main:app            /api/v1/health -> ok, database connected, ai_provider mock
streamlit run Home.py           /_stcore/health -> 200, / -> 200
GET /                           module_count 10, every one "available"
```

Then, by hand:

| Checked | Result |
| --- | --- |
| 13 export downloads across 8 modules, 6 formats | all `200`, all with a `Content-Disposition` filename, 17 KB – 683 KB |
| Module 2: the drill-down against the figure it drills into | `3,227,036.93` over 120 transactions, both sides — the pair that once read 329,444,859 for 7 |
| Module 2: contracted + non-contracted against the total | exact to the cent |
| Module 8: approve, execute, then rewrite the script | approval cleared, verdict kept, `execution_is_stale: true`, counted separately in the summary |
| Module 9: approve the summary, then rewrite the scope | `approved_by` kept, `approval_is_stale: true`, `stale_approved_count: 1` |
| Module 9: save a version, change a section, compare | 1 modified, 29 unchanged, matched by key |
| Module 10: the study plan against the dashboard it sits on | both quote `20.23`; the reason names the topic, not the branch |
| Every no-argument method on the Streamlit API client | 48 of 48 returned; 78 need arguments and are covered by the e2e journeys |
| The server log across 132 requests | nothing at WARNING or above |

Two provider checks, because "configurable" has to mean more than "the setting exists":

```text
AI_PROVIDER=anthropic, no key          -> resolves to mock (and says so)
AI_PROVIDER=anthropic, key set         -> resolves to anthropic; the key is not in repr()
AI_ENABLED=false                       -> resolves to mock
AI_PROVIDER=anthropic, invalid key     -> HTTP 200, status completed, 131 findings,
                                          ai_narrative.available false,
                                          "The AI provider rejected the request (HTTP 401)."
```

The last line is the guarantee that matters: a real provider returning a real 401
cost the analysis nothing. The findings are all there and the failure is reported
in its own field.

One observation worth recording because it looks like a problem and is not: a
regenerated `.xlsx` always shows as modified in `git status` even when the data
is identical, because openpyxl stamps a creation time into `docProps/core.xml`.
Re-running `generate_supplier_sample_data.py` reproduced the CSV, the JSON and
the recorded baseline byte for byte; only that timestamp differed.

### Criterion 10, and how the gap was closed

Modules 5 (Supplier Risk Copilot) and 10 (Interview Coach) shipped without an
export endpoint. That was a gap in the original modules rather than something
Phase 5 introduced, and it was recorded as a known limitation instead of being
quietly counted as a pass. It has since been closed:

| Module | Route | Formats |
| --- | --- | --- |
| 5 | `GET /supplier-risk/assessments/{id}/export` | `xlsx`, `csv`, `json`; `supplier_id=` narrows the report to one supplier |
| 10 | `GET /interviews/{session_id}/export` | `xlsx`, `csv`, `json`, `pdf` |

No new pipeline was built. Both reuse `workbook_to_bytes`, `build_text_pdf` and
`sanitize_filename`, and both routes follow the shape the other eight already
used — a `format` query parameter, the file itself rather than the envelope, and
a `Content-Disposition` filename. The one genuinely new piece is
`app/services/exports/styling.py`, which holds the header fills, fonts and
value-coercion helpers that had been copy-pasted into seven builders. The seven
existing builders were deliberately **not** migrated onto it: rewriting working
exports to satisfy tidiness is a redesign, and Phase 5 is not that.

Two module-specific rules the shared code could not supply:

- A supplier risk category with no data is written as **unscored**, never as
  zero, and the category sheet prints score, weight, renormalised weight and
  contribution side by side so the overall score can be rebuilt from the file.
  A supplier whose score was withheld entirely (SRK-09) exports with the score
  absent and `limited_data` set, rather than with the fragment it does have
  presented as a total.
- An interview report prints the **keyword that credited each concept**, and a
  dimension the question did not test as *not applicable* rather than zero. A
  mark somebody may disagree with has to be arguable with away from the screen.

Marked passed only after both were driven over a live API and through their
Streamlit pages, not from the test suite alone.

**Criterion 13.** See §5.

---

## 9. Known limitations

Ordered by how likely they are to matter.

1. **No authentication, and therefore no isolation.** Every caller sees
   everything. This is the one that must be fixed before anything is reachable
   by a second person.
2. **Analyses are synchronous.** A large file occupies a worker for the whole
   analysis, and a load balancer with a 60-second timeout will cut it off. The
   `pending`/`running`/`completed` states and the client's polling helper exist
   for the day a background worker is added; nothing uses them yet.
3. **File storage is local disk.** Fine on a VM with a volume, wrong on an
   ephemeral container. The presigned-URL shape is sketched in the integration
   doc.
4. **`approved_by` is free text.** Modules 8, 9 and 10 record who approved
   something as a string a caller supplies. That is a demo, not an audit trail;
   it becomes a foreign key when users exist.
5. **Keyword matching has a ceiling.** Module 10's rubric credits a concept when
   a keyword matches. It handles line breaks, plurals and nearby negation, and
   it will still miss a correct answer phrased in words the rubric does not
   know. The module says so on the page and prints the keyword that credited
   each concept, rather than leaving a candidate to argue with a number.
6. **Forecast quality is bounded by the demo history.** 30 monthly periods is
   enough to backtest and not enough to be confident about a seasonal pattern.
   The adjusted-R² gate and the complexity margin exist to stop the model
   claiming more than the data supports.
7. **No OCR by default.** A scanned contract is reported as `needs_ocr` rather
   than analysed as an empty one. The three provider seams exist and are
   unconfigured.
8. **PostgreSQL is verified, not exercised.** The migrations render, the DDL is
   correct and the timestamp handling is tested — but no test suite has been run
   against a live PostgreSQL server. That is a one-command gap
   (`docker compose --profile postgres up`) worth closing before a deployment.
9. **Single-currency assumptions in places.** Spend converts to a base currency
   with a fixed rate table. Real rate history is out of scope for a lab.

---

## 10. Recommended next steps for building the website

In the order that makes each step cheap.

### Before writing any front-end code

**1. Implement authentication and tenant isolation** — steps 1 and 3 of
[`API_AUTHENTICATION_PLAN.md`](API_AUTHENTICATION_PLAN.md). Not because the
front end needs it, but because every query in the backend changes shape and
doing that after a UI exists means doing it twice. The cross-organisation 404
test per module is the deliverable that matters.

**2. Run the suite against PostgreSQL.** One command, and it closes the last gap
between "verified" and "exercised". Do it before the schema has real data in it.

### The first slice of the website

**3. Generate the client and build one module end to end.**

```bash
npx openapi-typescript docs/openapi.json -o web/lib/schema.ts
```

Start with **module 1**: it has the simplest journey (upload → analyse →
findings → export) and exercises every cross-cutting concern — file upload,
column mapping, a paged and filtered table, severity badges, origin labels, a
binary download. Get those six components right once and the other nine modules
are mostly composition. `examples/typescript-client/src/examples.ts` is the
reference for each call.

**4. Build the six shared components first**, because every module needs them:

| Component | Built from |
| --- | --- |
| `FileUpload` | The upload response's `missing_required_fields` and `is_analyzable` |
| `ColumnMapper` | `GET /{module}/fields` — the same shape in all ten modules |
| `OriginLabel` | `output_origin` — five values, one legend |
| `SeverityBadge` | `Severity` and `IssueSeverity` — two scales, deliberately different |
| `PagedTable` | `total`/`limit`/`offset`, identical everywhere |
| `ErrorBoundary` | The single error envelope, keyed on `error.code`, showing `request_id` |

**5. Then the modules, in this order** — increasing UI complexity, not module
number: 1 (tables) → 4 (three uploads) → 3 (a form and a ranking) → 2 (charts and
drill-down) → 7 (time-series charts and confidence bands) → 5 and 6 (chat with
citations) → 10 (a stateful session) → 8 and 9 (editable documents).

Modules 8 and 9 last for a reason: they need inline editing, approval state and
version comparison, and they are the two where the UI has to render a *pair* of
fields honestly — an approval that is kept **and** flagged as stale. Build that
when the rest of the vocabulary is settled.

### Not front-end work, but needed before launch

**6. Move analysis to a background worker** once real file sizes are known. The
API contract is already shaped for it.

**7. Move uploads and exports to object storage** with presigned URLs, and run
the validation at the presign step — after the upload, the file is already in
the bucket.

**8. Add rate limits per principal** on `/analyze`, `/validate`, `/forecast`,
`/generate` and the two chat endpoints. This is where Redis earns its place.

**9. Only then enable a real AI provider.** An open `/analyze` endpoint with a
real key is an open invoice, and every response already records the tokens and
an estimated cost so usage is visible before it is a bill.

### What not to do

**Do not move any business logic into the front end.** The reason a website is a
re-skin rather than a rewrite is that every number comes from the API. The first
time a percentage is computed in TypeScript, there are two implementations of it
and they will disagree — and the one on the screen will be the one nobody tested.

**Do not drop the labels.** `output_origin`, `is_estimate`, the methodology
block and the standing disclaimer are what make the software honest about what
it is: a demo, on fictional data, not connected to any SAP system, with no
output validated in a live SAP environment. A front end that omits them is
making claims the software does not support.

---

# Phase 6 — the public website and the self-hosted demonstration

Phase 6 built no modules and changed none of the ten. It added a website that
explains them and a mode that makes the existing application safe to publish.

## What changed, in one paragraph

`DEMO_MODE=true` refuses uploads server-side, forces the mock AI provider and
runs everything on the bundled fictional data. A guided-demonstration route hands
each module the sample file an upload would have provided, by calling that
module's own upload handler. A Next.js site describes all ten modules from a
typed content module and never calls the API from a browser, which is why the API
needs no public hostname. A five-service compose file publishes no port at all.

## Verification performed

| Gate | Result |
| --- | --- |
| `python scripts/check_quality.py` | **PASS** — lint, secret scan, pip-audit, tests |
| `pytest` | **1928 passed** (baseline 1698; 230 added) |
| `pip-audit` | **No known vulnerabilities** |
| `npm run lint` / `typecheck` / `test` / `build` | **PASS** / **PASS** / **112 passed** / **25 routes** |
| `npm audit` | **3 high**, all transitive via Next — assessed below |
| `docker compose config` | Valid, both the deployed file and the debug overlay |
| `docker compose build` | Both images built (`sapdemo-api` 1.48 GB, `sapdemo-website` 381 MB) |
| `./scripts/verify_selfhosted.sh` | **20 passed, 0 failed** in the deployed configuration |
| Persistence | 4,558 rows survived a full `down` / `up` cycle |
| Backup + disposable restore | 34 tables, ~4,558 rows restored into a throwaway database and dropped |
| Reset | Refused with exit 2 outside demo mode; idempotent inside it |
| Corrupt backup | Refused on checksum before any restore |

## Dependency findings, reported rather than hidden

**Python — `pip-audit`: clean.**

**Frontend — `npm audit`: 3 high, 0 critical.** All three are transitive through
`next@16.2.12`, and the only offered remediation is `next@9.3.3`, a seven-major
downgrade. That is not a fix, so both are accepted residual risk with mitigation:

| Advisory | Package | Runtime attack path | Disposition |
| --- | --- | --- | --- |
| GHSA-qx2v-qp2m-jg93, GHSA-6g55-p6wh-862q, GHSA-r28c-9q8g-f849 | `postcss` 8.4.31, **nested inside `next`** | Build-time CSS processing of CSS authored in this repository. Not reachable at runtime. The top-level `postcss` (8.5.25, used by Tailwind) is already patched. | **Accepted.** Not in a runtime path. |
| GHSA-f88m-g3jw-g9cj (4 libvips CVEs) | `sharp` | Next's image optimizer. | **Mitigated.** `images.unoptimized: true` in `next.config.ts` — the site ships no images, so the optimizer has no reachable entry point. The package is still traced into the standalone output; the code path is not invoked. Revisit when `sharp` clears the advisory. |

No dependency could not be upgraded for any other reason.

## Bugs found by running it

Four, none visible to a green suite.

1. **`ai_prompt_version` too narrow for its own value.** SQLite ignores `VARCHAR`
   length; PostgreSQL does not. Two of ten modules failed to seed on the first
   real-database start. Fixed by migration `b8e6a24f1d35` and a new
   engine-independent test.
2. **The demo-mode upload guard blocked the demonstration's own Load Demo
   button.** The guard was keyed on "is the seeder running" rather than on "did
   these bytes come from the repository". Renamed `trusted_ingest()`.
3. **The debug overlay's API port was never published.** Docker cannot publish
   from a container attached only to an `internal: true` network — it accepts the
   entry, reports healthy, and creates no mapping.
4. **The website's Launch Demo button pointed at the deployment hostname when
   served locally.** `NEXT_PUBLIC_*` is compiled in at build time.

Two more were found by tests written in this phase: a heading-order accessibility
defect on four pages (axe-core), and three of my own assertions that were wrong
rather than strict.

## Known limitations

- **No authentication.** One visitor's records are visible to another through the
  API. Session-scoped views are a display filter, and every surface says so.
- **A single machine.** With FileVault on, an unattended reboot leaves the site
  down until a person logs in at the keyboard.
- **Mock AI prose is illustrative.** It is composed from the computed results and
  labelled `mock_ai`; it is not model output.
- **Not production-ready**, and not described as such anywhere.

## Manual steps still required

Nothing below has been done, and no script here does any of it.

**Cloudflare** — add the domain; verify MX/SPF/DKIM/DMARC/verification records
were imported; create a remotely-managed tunnel; add three public hostnames and
**no `api.` hostname**; create an Access application on the demonstration with an
exact email allow list, one-time PIN and a default-deny; paste the token into
`.env.selfhosted` only.

**GoDaddy** — record the existing zone, then change nameservers, then re-test
mail in both directions.

**The MacBook** — Docker Desktop resources (3 CPU / 8 GB / 2 GB swap) and
start-at-login; prevent sleep on power while letting the display sleep; keep the
lid open; Ethernet; turn off automatic macOS updates; attach an encrypted backup
drive; test a full reboot recovery once, deliberately.

## Recommended next step after merge

Run the Python suite against PostgreSQL in CI. The column-width bug is the whole
argument: five phases of green tests on SQLite hid a schema defect that broke two
modules on the first real database. A second engine in the test matrix costs one
service and closes an entire class of bug that this project has now demonstrated
it is exposed to.
