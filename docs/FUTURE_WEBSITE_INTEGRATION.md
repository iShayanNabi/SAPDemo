# Future website integration

How to replace the Streamlit interface with a React or Next.js site without rewriting business
logic.

---

## The short version

There is nothing to port. The Streamlit page is a thin HTTP client: it imports an API client and
some formatting helpers, and nothing else from the project. Every number it displays came from a
JSON response. A website calls the same endpoints and receives the same JSON.

```text
Today                              Later
┌────────────────┐                 ┌────────────────┐
│ Streamlit page │                 │ Next.js app    │
└───────┬────────┘                 └───────┬────────┘
        │ HTTP                             │ HTTP
        ▼                                  ▼
┌──────────────────────────────────────────────────┐
│                FastAPI backend                    │  ← unchanged
│   rules · engine · services · database            │
└──────────────────────────────────────────────────┘
```

This was enforced from the start: the Streamlit page cannot import a rule, so it cannot
accidentally become the place where logic lives.

---

## What already works

| Concern | Status |
| --- | --- |
| Versioned REST API (`/api/v1`) | Ready |
| Consistent JSON envelope | Ready |
| OpenAPI schema at `/openapi.json` | Ready - generate a typed client from it |
| CORS | Ready - configured from `CORS_ORIGINS` |
| Stable error codes and safe messages | Ready |
| Request IDs for support and tracing | Ready |
| File upload over `multipart/form-data` | Ready |
| Binary downloads with correct content types | Ready |
| Output-origin labels for honest UI | Ready |

---

## What must be added before a public launch

These are deliberately absent from a local lab. Do not skip them.

### 1. Authentication and authorisation

There is none today. Any caller can upload and read every analysis.

Add at minimum: user accounts, an owner column on `po_analyses` and `uploaded_files`, and a
dependency that scopes every query to the caller. `GET /analyses` currently returns everything -
that becomes a data leak the moment there is more than one user.

Session cookies or JWT both work; the API is stateless apart from the database.

### 2. Rate limiting and quotas

Analysis is CPU-bound and upload storage is unbounded. Add per-user limits on request rate,
upload size and total stored files, plus a retention policy that deletes old uploads.

### 3. Background jobs for large files

Analysis runs inside the request and takes a few seconds on ~1,200 rows. Larger files will exceed
sensible HTTP timeouts.

Suggested shape - the response model already includes `status`, so this is an additive change:

```text
POST /analyze          → 202 { "analysis_id": "...", "status": "queued" }
GET  /analyses/{id}    → { "status": "running" | "completed" | "failed" }
```

A worker (Celery, RQ, or a simple task table) runs `run_analysis()` unchanged.

### 4. Storage

Local disk does not survive a container restart and does not scale horizontally. Move uploads and
exports to object storage (S3 or equivalent) behind the existing `services/files/storage.py`
interface, and serve downloads with signed URLs.

### 5. PostgreSQL

Change `DATABASE_URL` and run `alembic upgrade head`. The models avoid dialect-specific types and
migrations use batch mode, so no code changes are expected - but verify the first run by hand,
because CI only exercises SQLite.

### 6. Observability

Structured logging exists (`LOG_JSON=true`). Add metrics (analysis duration, findings per run, AI
latency and cost) and error tracking. Every response already carries a request ID to correlate
with logs.

### 7. Security hardening

HTTPS only; a strict CORS allow-list rather than a permissive one; virus scanning for uploads if
the site is public; secrets from a manager rather than a `.env` file; and a check that AI usage
costs are attributable per user before enabling a real provider.

---

## Suggested front-end structure

```text
web/
  app/
    po-risk/
      page.tsx              upload and mapping
      [analysisId]/
        page.tsx            dashboard
        findings/page.tsx   filterable table
    spend/
      page.tsx              upload, mapping and filters
      [analysisId]/
        page.tsx            KPI cards and charts
        transactions/page.tsx   drill-down table
        opportunities/page.tsx  savings list
  components/
    FileUpload.tsx
    ColumnMapper.tsx        built from GET /{module}/fields - works for both modules
    SeverityBadge.tsx
    OriginLabel.tsx         renders rule_based vs mock_ai vs ai_generated
    EstimateBadge.tsx       renders is_estimate on every savings figure
    RiskKpiCards.tsx
    SpendKpiCards.tsx
    FindingsTable.tsx
    DrilldownTable.tsx      takes dimension + value, calls /transactions
  lib/
    api.ts                  generated from /openapi.json
```

`ColumnMapper` is worth building once. Both modules expose the same field-catalogue shape
(`name`, `label`, `field_type`, `required`, `aliases`), so one component serves every module the
lab will ever add.

Generating the client from the OpenAPI schema is worth doing - it keeps the front end honest about
what the API actually returns:

```bash
npx openapi-typescript http://127.0.0.1:8000/openapi.json -o web/lib/api-types.ts
```

### A minimal call

```ts
const form = new FormData();
form.append("file", file);

const uploadRes = await fetch(`${API}/api/v1/po-risk/upload`, {
  method: "POST",
  body: form,
});
const { success, data, error } = await uploadRes.json();
if (!success) throw new Error(error.message);   // already safe to display

const analysisRes = await fetch(`${API}/api/v1/po-risk/analyze`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ upload_id: data.upload_id, generate_ai_summary: true }),
});
```

---

## The seven calls, in TypeScript

A runnable client and a worked example of every one of these lives in
[`examples/typescript-client/`](../examples/typescript-client/). `npm run demo` performs the whole
journey against a local API using the bundled demo dataset, so it needs no file of your own.

The snippets below use that client. Everything it does is plain `fetch`; read
[`src/client.ts`](../examples/typescript-client/src/client.ts) if you would rather copy the
handling than the wrapper.

```ts
import SapAiLabClient, { ApiError, saveToDisk } from './client';

const client = new SapAiLabClient({
  baseUrl: process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:8000',
  token: () => getAccessToken(),   // ignored today; the seam costs nothing now
});
```

### 1. Health check

Call it on app start. "The API is not running" and "your file was rejected" are different
problems, and a user should never see the second message for the first cause.

```ts
const health = await client.health();
// { status: 'ok', database_connected: true, ai_provider: 'mock', ai_is_mock: true, ... }
```

### 2. File upload

```ts
const upload = await client.upload('/po-risk/upload', file);

// Modules that need a form field alongside the file:
await client.upload('/invoices/upload', file, { dataset: 'invoices' });
await client.upload('/supplier-risk/upload', file, { dataset: 'events', dataset_id: datasetId });
```

`suggested_mapping` is a *suggestion*: show it and let the user correct it. `is_analyzable: false`
with a populated `missing_required_fields` is a form to fill in, not an error - do not render it
as a failure.

### 3. Starting an analysis

```ts
const analysis = await client.analyze('/po-risk/analyze', {
  upload_id: upload.upload_id,
  column_mapping_overrides: { VENDOR_NO: 'supplier_id' },   // the user's corrections
  generate_ai_summary: true,
});
```

Analyses are **synchronous** today: the promise resolves with a completed analysis. On a large file
that can take a while, so show a spinner rather than a progress bar you cannot fill in.

### 4. Polling analysis status

Not needed today, and worth writing against anyway - it is the part of the contract most likely to
change. When large uploads move to a background worker, `analyze()` will start returning `pending`
and this loop is what copes.

```ts
const finished = await client.pollUntilComplete(
  () => client.get(`/po-risk/analyses/${analysis.analysis_id}`),
  { intervalMs: 1_000, timeoutMs: 5 * 60_000, onProgress: (a) => setStatus(a.status) },
);
```

`status` is one of `pending`, `running`, `completed`, `failed` - the same four words in every
module, so one status component serves all ten.

### 5. Retrieving findings

```ts
const page = await client.get(`/po-risk/analyses/${id}/findings`, {
  severity: ['critical', 'high'],   // repeated query keys
  limit: 25,
  offset: 0,
});
// { total, limit, offset, findings: [...] }

// Or every page of them:
const all = await client.listAll(`/po-risk/analyses/${id}/findings`, 'findings');
```

Findings come back most serious first, then by exposure. The order is stable, which is what makes
paging safe - without it, a row can appear on two pages and another on none.

### 6. Downloading an export

```ts
const report = await client.downloadExport(`/po-risk/analyses/${id}/export`, 'xlsx');
saveToDisk(report);   // report.filename came from Content-Disposition
```

Exports return the file itself rather than the envelope, because a browser cannot stream a base64
blob to disk. `Content-Disposition` is in the CORS expose list, so a `fetch` can read the filename
the API chose - a folder full of `export.xlsx` helps nobody.

### 7. Sending a copilot question

```ts
const reply = await client.askSupplierRiskCopilot({
  question: 'Why is supplier 0000390001 rated high risk?',
  supplier_id: '0000390001',
});

if (!reply.data_available) {
  show(`Not answerable from the loaded records: ${reply.unavailable_reason}`);
} else {
  show(reply.answer, reply.citations, reply.output_origin);
}
```

**Render the second branch.** Both copilots tell you when the loaded data does not support an
answer; showing `answer` regardless turns "I do not have that" into what reads like a considered
response.

---

## Handling errors

Every failure - network, timeout, a non-JSON body, an HTTP error, an error envelope - has the same
shape, so one handler covers the whole API:

```ts
try {
  await client.upload('/po-risk/upload', file);
} catch (error) {
  if (!(error instanceof ApiError)) throw error;

  if (error.isUserFixable) {        // 400 / 422 - the input was the problem
    toast(error.message);           // already safe to show: no paths, no stack traces
  } else if (error.isRetryable) {   // 5xx, 429, or unreachable
    toast('Something went wrong. Please try again.');
  } else if (error.code === 'not_found') {
    router.push('/analyses');
  }
  console.error(error.code, error.requestId);   // the id is in the server log
}
```

The codes worth branching on: `file_validation_error`, `validation_error`,
`request_validation_error`, `not_found`, `unsafe_path`, `analysis_error`, `ai_provider_error`,
`configuration_error`, `internal_error`.

`meta.request_id` is on every response, success or failure, and matches the `X-Request-ID` header.
Show it on an error screen: it is what turns "it broke this morning" into a log line.

---

## Authentication, organisations and signed URLs

### Authenticating users

There is none today, deliberately, and `GET /api/v1/auth-status` says so rather than leaving you to
infer it from requests succeeding. The `bearerAuth` scheme is declared in the OpenAPI document as
*optional*, the `Authorization` header is in the CORS allow-list, and the example client already
sends one when you give it a token.

So the front-end work is: put the token behind a function today, and change nothing later.

```ts
const client = new SapAiLabClient({ token: () => getAccessToken() });
```

The full model - JWT shape, refresh rotation, the user, organisation and workspace tables, the role
set, and the order the work has to happen in - is in
[`docs/API_AUTHENTICATION_PLAN.md`](API_AUTHENTICATION_PLAN.md). Two points that affect the front
end directly:

- **401 and 403 are different.** 401 means get a new token (refresh, then retry once). 403 means the
  token was fine and this user is not allowed - retrying is a loop. Both arrive in the standard
  envelope with codes `unauthorized` and `forbidden`.
- **404 is used where 403 would leak.** Asking for another organisation's analysis returns "not
  found", because "forbidden" confirms the id is real.

### Managing organisations

The backend model is organisation → workspaces → resources, with a user's role held on their
*membership* of an organisation rather than on the user. That shapes three things in the UI:

- an organisation switcher, because one person can belong to several with different roles;
- a workspace selector inside it, because a workspace is what keeps one team's 400 analyses out of
  another team's list;
- a members screen (invite, change role, deactivate) available only to `admin`.

Until that exists, `auth-status` reports `org_local_demo` / `ws_local_demo` for every request. Build
against those fields now and the switcher is additive rather than a refactor.

### Signed file URLs

Uploads and exports currently stream through the API from local disk. That is right for a laptop and
wrong for a public site: a 25 MB download occupies a worker for its whole duration.

The shape to move to, when files live in object storage:

```ts
// 1. Ask the API where to put the file. It returns a short-lived signed URL.
const { url, fields, upload_id } = await client.post('/po-risk/uploads/presign', {
  filename: file.name, content_type: file.type, size_bytes: file.size,
});

// 2. Upload straight to storage. The bytes never touch the API.
const form = new FormData();
for (const [k, v] of Object.entries(fields)) form.append(k, v);
form.append('file', file);
await fetch(url, { method: 'POST', body: form });

// 3. Tell the API the object is there, and analyse it.
await client.post('/po-risk/analyze', { upload_id });
```

Downloads mirror it: `GET /.../export` returns `302` to a signed URL that expires in minutes. Three
rules make the difference between a signed URL and a public one:

- **Short expiry** - minutes, not days. A URL in a browser history is a URL somebody else has.
- **Sign the object key, not a path the client chose.** Otherwise the signature covers a traversal.
- **Validate before signing.** The extension, size and content-type checks in
  `app/services/files/validation.py` must run at the presign step; after the upload, the file is
  already in the bucket.

The API keeps its current behaviour as the fallback, because local development should not need an
object store.

---

## Using the OpenAPI schema

The document at `/openapi.json` is the contract, and it is committed as
[`docs/openapi.json`](openapi.json) so an API change shows up as a diff in code review rather than
as a surprise in a front end. Regenerate it with `python scripts/generate_api_collection.py`.

```bash
# Types for every module payload, from the server's own schema
npx openapi-typescript docs/openapi.json -o web/lib/schema.ts
```

```ts
import type { components } from './schema';
type Analysis = components['schemas']['AnalysisDetailSchema'];
type Finding  = components['schemas']['FindingSchema'];

const analysis = await client.get<Analysis>(`/po-risk/analyses/${id}`);
```

What the schema gives you beyond types:

- **The error shapes**, per endpoint - `400`, `404`, `422` and `500` are declared with examples, so
  error handling is written against the contract rather than against whatever you hit first.
- **The field catalogues.** `GET /{module}/fields` returns `name`, `label`, `field_type`, `required`
  and `aliases` in the same shape for every module, so one `ColumnMapper` component serves all ten.
- **The rule catalogues.** `GET /{module}/rules` returns every rule with its configured thresholds -
  enough to build a "why was this flagged" panel without hardcoding a single number.
- **The enums.** `OutputOrigin`, `Severity`, `IssueSeverity` and `AnalysisStatus` are shared
  components, so a badge component built from them stays correct as modules are added.

There is also a Postman/Insomnia collection at [`docs/postman_collection.json`](postman_collection.json):
132 requests in eleven folders, bodies pre-filled, generated from the same document.

---

## UI obligations that are not optional

The backend labels every value it returns. A front end that drops those labels breaks the honesty
the whole design rests on.

1. **Show the origin.** Rule-based findings and AI text must be visually distinct. Never present
   `mock_ai` output as a model response.
2. **Never imply a live SAP connection.** Results describe the uploaded file. The `methodology`
   block in every analysis response contains the disclaimer to display.
3. **Never claim SAP validation.** No recommendation here has been tested in a live SAP system.
4. **Show the evidence.** Every finding carries `evidence` including the applied threshold. Users
   should be able to see why a line was flagged.
5. **Show data-quality warnings.** If `data_quality_issues` is non-empty, the user needs to know
   some values could not be read.
6. **Surface `rule_errors` and `savings_errors`.** If a rule or a savings model failed, say so
   rather than presenting a partial result as complete.
7. **Never present a savings estimate as a saving.** Every opportunity carries `is_estimate: true`,
   a `realization_factor` and a `method` string stating its arithmetic. Show the method - a
   category manager who cannot check a number will not take it into a negotiation. The word
   "estimated" belongs in the label, not only in a footnote.

---

## Migration checklist

- [ ] Generate a typed client from `/openapi.json`
- [ ] Build upload, mapping, dashboard, findings and export screens
- [ ] Build the spend dashboard, drill-down and opportunity screens
- [ ] Render `is_estimate` and `method` on every savings figure
- [ ] Render `output_origin` labels everywhere text is shown
- [ ] Display the methodology and disclaimer on results and exports
- [ ] Add authentication and scope every query to the owner
- [ ] Add rate limiting and upload quotas
- [ ] Move analysis to a background worker; poll `status`
- [ ] Move file storage to object storage
- [ ] Switch to PostgreSQL and verify migrations
- [ ] Configure CORS for the real origin
- [ ] Add metrics and error tracking
- [ ] Delete the Streamlit app, or keep it as an internal debugging tool

The last line is the point: when the website is finished, removing `streamlit_app/` should not
break a single test.
