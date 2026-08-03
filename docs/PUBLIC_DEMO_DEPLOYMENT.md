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

## Arriving at one module

The public website links to individual tools rather than to the demonstration
home page: `https://demo.solveaihub.com/?module=invoice-validator` opens the
Invoice Validator, and `https://demo.solveaihub.com/` still opens the home page.

The parameter is matched against a fixed list of ten identifiers and is used for
nothing else - anything unrecognised lands on the home page with a short
message. It is navigation only: **Cloudflare Access still authenticates every
request to this origin**, with or without a query string, before the application
sees it.

The route format, the ten identifiers, the rerun and back-button behaviour, and
the manual test matrix that still has to be worked through after deployment are
in [`DEMO_MODULE_ROUTING.md`](DEMO_MODULE_ROUTING.md).

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

## The contact form

The website's contact page is `mailto:` links by default, and the switches above
have nothing to do with it - it belongs to the Next.js site, not the API. It is
governed by its own flag, which is **off** unless every variable it needs is
also set:

| Variable | Where it is read | What it does |
| --- | --- | --- |
| `CONTACT_FORM_ENABLED` | Run time | `false` by default. Off means `mailto:` links and a 404 endpoint. |
| `CONTACT_RECIPIENT_EMAIL` | Run time | The mailbox submissions are delivered to. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` | Run time | Delivery. Default to `smtp.gmail.com`, `465` and `solveaihub@gmail.com`. |
| `SMTP_APP_PASSWORD` | Run time | The Gmail **App Password**, never the account password. No default. |
| `SMTP_SECURE` | Run time | `true`, matching implicit TLS on 465. Blank decides from the port. |
| `SMTP_FROM` | Run time | Optional; defaults to `SMTP_USER`, the only `From` Gmail will not rewrite. |
| `TURNSTILE_SECRET_KEY` | Run time | Verified with Cloudflare on every submission. |
| `NEXT_PUBLIC_TURNSTILE_SITE_KEY` | **Build** *and* run time | The public widget key. Compiled into the bundle by `next build`, and read again at run time by the server-side readiness gate. `PUBLIC_TURNSTILE_SITE_KEY` is the superseded spelling and is still accepted. |
| `CONTACT_SITEVERIFY_TIMEOUT_MS` | Run time | How long the Cloudflare verification may take. Defaults to 5000. Never a build argument. |
| `TURNSTILE_EXPECTED_HOSTNAMES` | Run time | Hostnames a token may be solved on. Blank skips the check. |
| `TURNSTILE_EXPECTED_ACTION` | Run time | The widget's declared action, `contact`. Blank skips the check. |
| `CONTACT_RATE_LIMIT_MAX` | Run time | Submissions per window per bucket. Defaults to 5. |
| `CONTACT_RATE_LIMIT_WINDOW_SECONDS` | Run time | Window length. Defaults to 3600. |
| `CONTACT_RATE_LIMIT_SECRET` | Run time | HMAC key for the rate-limit bucket identifiers. |

Two things follow from that build/run-time split, and both have bitten this
project before in other variables:

- **The site key is passed twice, and either one alone works.**
  `NEXT_PUBLIC_*` values are compiled in by `next build`, so the build argument
  is what puts the key in the browser bundle and changing it wants
  `./scripts/start_selfhosted.sh --build`. It is *also* under `environment`,
  because the gate that decides whether the form renders at all is server-side:
  the contact page is `force-dynamic` and hands the key to the widget as a
  prop, so a key supplied only at run time still produces a working form on a
  `docker compose up -d`. `lib/contact/config.ts` reads it both ways and
  explains why the runtime read is written the way it is. Everything else takes
  effect on `docker compose up -d`.
- **The secret key must never become a build argument.** Docker records build
  arguments in the image history, so a secret placed there is readable by anyone
  who can pull the image. Only the *site* key appears under `build.args` in
  `docker-compose.selfhosted.yml`; `TURNSTILE_SECRET_KEY`, `SMTP_APP_PASSWORD`
  and `CONTACT_RATE_LIMIT_SECRET` are runtime-only, and
  `tests/integration/test_selfhosted_deployment.py` asserts it.

### It fails closed, and that is the whole design

Setting `CONTACT_FORM_ENABLED=true` is not sufficient on its own. If any
variable above is missing, the site behaves exactly as it does with the form off
- `mailto:` links, and `/api/contact` returning 404 - and the server log names
the missing variable:

```
[contact] outcome=misconfigured missing=TURNSTILE_SECRET_KEY
```

The browser is told only "Not found". There is deliberately no state in which a
form renders without an anti-spam check behind it, and no `NODE_ENV` bypass:
a missing secret, a `siteverify` timeout, a malformed response and a rejected
token all mean the message is not delivered, in every environment.

### Two rate-limit buckets, charged at different points

The address bucket is charged on **every** attempt, before Turnstile, so probing
the endpoint costs the same quota as using it and a flooder cannot make the
server spend an outbound HTTPS round trip per request.

The email bucket is charged **only after Turnstile passes**, and that ordering is
a security property rather than a tidiness one. The email address is simply what
somebody typed into the form. Charging it earlier would let anyone enter a third
party's address, fire `CONTACT_RATE_LIMIT_MAX` requests carrying junk tokens, and
lock that person out of the contact form for a whole window - an unauthenticated
denial of service against someone else, costing the attacker nothing but their
own IP quota.

### The site key is public, so a `success` is not enough

Cloudflare confirms a token is genuine. It does not, on its own, confirm the
token came from *this* form: the site key is readable in the page source, so
anyone can host the same widget, have a real challenge solved on their page, and
replay the token here. `TURNSTILE_EXPECTED_HOSTNAMES` and
`TURNSTILE_EXPECTED_ACTION` are what make the confirmation specific - Cloudflare
reports where the token was solved and which action it was solved for, and a
mismatch on either prevents delivery.

Both are configuration rather than a `NODE_ENV` branch, for the same reason the
verification itself is: an environment-dependent branch in security-critical code
is one mis-set variable away from being live in the wrong place. Blank skips the
pin (the local-development case, since the test keys report neither
meaningfully); `success` is still required regardless.

### Nothing a visitor submits is stored

The message is composed in memory, handed to SMTP and dropped. There is no
database row, no file and no log of its contents - the logs carry outcome codes
only. The rate limiter holds keyed HMAC digests of the client address and the
submitted email in process memory; the raw values are never written anywhere,
and the counters reset on restart.

That last point is a real limitation rather than a footnote: **the counters are
per process and are not shared between replicas.** This is correct for the
current single-instance deployment and would need shared state (Redis or
equivalent) before scaling the website service out.

For local development, Cloudflare publishes always-passing test credentials, so
the form works without a Cloudflare account - see `frontend/.env.example`. The
test secret accepts *any* token, including a forged one, so it must never reach
a deployment.

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
