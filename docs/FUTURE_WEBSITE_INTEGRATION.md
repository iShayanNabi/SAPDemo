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
