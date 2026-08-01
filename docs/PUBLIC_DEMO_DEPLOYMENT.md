# Public demonstration deployment

How the ten modules become something a stranger can safely use, and what each
switch actually changes.

Read [`DEMO_SECURITY_CHECKLIST.md`](DEMO_SECURITY_CHECKLIST.md) before
publishing and [`MACBOOK_SELF_HOSTING.md`](MACBOOK_SELF_HOSTING.md) for the host
itself.

---

## The problem this solves

The lab was written for a laptop, where "upload your own spreadsheet" is the
whole point. Publishing the same application inverts that: the file a stranger
uploads is the one thing the operator cannot vouch for, and the analysis it
produces is the one thing they cannot delete on that stranger's behalf.

Demo mode is not a banner. It removes the ingestion path, forces the mock AI
provider, and says so on every page.

---

## The switches

All five are read by `app/core/config.py` and default to the safe value.
`DEMO_MODE` is the master switch; **the other four are only consulted while it
is true**, so a half-applied demo configuration cannot disable uploads on
somebody's laptop.

| Variable | Default | What it does |
| --- | --- | --- |
| `DEMO_MODE` | `false` | Turns the mode on. Everything below follows from it. |
| `DEMO_ALLOW_UPLOADS` | `false` | Whether a visitor may upload a file. |
| `DEMO_USE_MOCK_AI` | `true` | Forces the mock provider regardless of any key. |
| `DEMO_SEED_ON_EMPTY` | `true` | Load bundled records when the database is empty. |
| `DEMO_RESET_ON_START` | `false` | Wipe and reload on every start. **Leave false.** |

Set them in `.env.selfhosted` (see `.env.selfhosted.example`). Locally:

```bash
DEMO_MODE=true uvicorn app.main:app --reload
```

### `DEMO_MODE=true` changes exactly three things

**1. Uploads are refused server-side.**

Not hidden - refused. `app/core/demo.py::ensure_uploads_allowed` is called at
the two choke points every upload passes through:
`read_upload_within_limit` (before the first byte is read) and both validators
in `app/services/files/validation.py`. A route added next year is covered
without anybody remembering to cover it.

```bash
$ curl -F "file=@anything.csv" .../api/v1/po-risk/upload
HTTP/1.1 403 Forbidden
{"success": false, "error": {"code": "demo_mode_restricted", ...}}
```

Hiding the Streamlit widget stops an honest visitor and nobody else. The widget
is hidden too, because offering a control that then rejects you is a bad
experience - but the widget is not the control.

**2. The AI provider is forced to mock.**

`resolved_ai_provider()` checks demo mode *first* and does not consult the keys
at all. A public demonstration that quietly started billing an Anthropic key
because one happened to be exported is a bill and a data-egress path nobody
chose.

**3. The data is the bundled fictional data.**

There is no other data. That is what makes the disclaimer on every page true
rather than aspirational.

### What it does not change

Every calculation. The rules, scoring, matching, forecasting and marking are the
real implementations, running live. A demonstration that computes something
different from the product is a demonstration of a different product.

---

## Guided demonstrations

With uploads gone, each module needs a way to get data in. That is
`POST /api/v1/demo/load/{module}`, which reads `data/sample/` and calls the
module's **own** `handle_upload` - the same function a real upload reaches.

```
GET  /api/v1/demo/status          how this deployment is configured
GET  /api/v1/demo/modules         what each module's demonstration offers
POST /api/v1/demo/load/{module}   ingest its bundled data, return the handles
```

Seven modules take a file and have a loader. Modules 8, 9 and 10 take a
structured request, so their demonstration starts from a bundled *scenario*
their own `/sample` endpoints already serve - `POST /demo/load/` returns a 404
naming the reason rather than failing oddly.

The response carries each module's own upload payload, so a page renders its
mapping preview from exactly what an upload produces. No second code path.

**A bug worth knowing about:** the first version of the guard keyed on "is the
seeder running", and public demo mode then refused its own Load Demo button.
The block is now named `trusted_ingest()` - for the property that matters, that
these bytes came from the repository rather than from a request - and both the
seeder and the demo loader use it. There is a test asserting a request arriving
outside that block is still refused.

---

## Seeding and reset

Decided in `docker/entrypoint.sh` rather than in the FastAPI lifespan, for two
reasons: `app/` must not import `scripts/`, and *"does a restart wipe the
database"* should be answerable by reading one file.

```
lab-api:
  wait_for_database
  apply_migrations              alembic upgrade head
  prepare_demo_data             only when DEMO_MODE=true
      DEMO_RESET_ON_START=true  -> reset_demo.py --yes --force
      DEMO_SEED_ON_EMPTY=true   -> seed_database.py --if-empty --yes
  exec uvicorn
```

`--if-empty` exits 0 when the database already holds analyses, so a restart is a
no-op rather than a failure or a duplicate set. A seeding failure logs a warning
and lets the API start - an empty demonstration is bad, an unexplained empty
demonstration is worse.

### Explicit reset

```bash
./scripts/reset_public_demo.sh          # asks for confirmation
./scripts/reset_public_demo.sh --yes    # for a scheduled run
```

It **refuses to run unless `DEMO_MODE=true`** and exits 2. That refusal is the
whole safety model: a database that is not a public demonstration holds somebody's
data, and the script cannot tell the difference by looking at it. It also asks
the server `SELECT current_database()` and refuses if the answer disagrees with
`POSTGRES_DB` - never operate on an unidentified database.

It never deletes source files, migrations, configuration, secrets, backups or
`data/sample/`. Those are inputs and history, not state.

Idempotent, so it is safe on a schedule. A nightly reset via `launchd` is
documented in [`MACBOOK_SELF_HOSTING.md`](MACBOOK_SELF_HOSTING.md).

**There is no reset endpoint.** An unauthenticated destructive HTTP route on a
public hostname needs no further comment.

---

## Visitor isolation, stated honestly

There are no user accounts. Records created by one visitor are visible to
another through the API. Three things reduce that exposure, and none of them is
authentication:

1. **The API has no public hostname.** It publishes no port and sits on a
   network with no internet route. The only thing that talks to it is the
   demonstration UI, over a private Docker network.
2. **The demonstration hostname sits behind Cloudflare Access** with an explicit
   email allow list, so visitors are invited rather than anonymous.
3. **List and history views are scoped to the browser session.** The Streamlit
   pages record the identifiers they created in `st.session_state` and show only
   those.

Point 3 is a **display filter**, not a security control, and the page says so in
its own caption. Per-visitor ownership needs the model in
[`API_AUTHENTICATION_PLAN.md`](API_AUTHENTICATION_PLAN.md), which is not built.
Do not describe this deployment as multi-tenant.

---

## What a visitor sees

- **`Public Demo — Fictional Data Only`** across every page.
- An expander listing what must not be entered: confidential information,
  personal information, real SAP data, real supplier/PO/invoice/contract data,
  proprietary company data.
- No upload control; a note explaining where it went and how to run the project
  locally instead.
- Every result labelled with its origin: `rule_based`, `forecast`,
  `ai_generated`, `mock_ai`, `demo_data`.
- Errors that carry no path, stack trace, database URL, provider payload or
  internal hostname.

---

## Turning demo mode off

```bash
# .env.selfhosted
DEMO_MODE=false
```

then `./scripts/restart_selfhosted.sh`. Uploads are accepted again and a
configured provider key is used again.

**Do not do this while the deployment is publicly reachable.** It means
accepting arbitrary files from strangers into an application with no user
accounts. If you need to analyse your own data, run the project locally - the
README has the commands, and the same code produces the same answers.

---

## Verifying

```bash
./scripts/verify_selfhosted.sh
```

It checks demo mode is on, uploads are refused *by making a real upload request*,
the provider is the mock, all ten demonstrations are described, the database
holds data, no configured secret appears in any log, and no error response leaks
internal detail.

A green run is necessary and not sufficient. Open the demonstration and use it -
this project's own history is that its worst bugs passed a fully green suite and
appeared the first time somebody drove the thing by hand.
