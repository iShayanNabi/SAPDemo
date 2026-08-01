"""Everything that makes ``/docs`` and ``openapi.json`` useful to a front end.

The OpenAPI document is not decoration here - it is the contract a future React,
Next.js, Vue or mobile client will generate its types from, and the thing a
reviewer reads before writing a line of it. So the description, the tag list and
the shared error responses live in one place rather than being scattered over
130 route decorators.

Three things are declared here that a generated client needs and cannot infer:

* the **shared envelope**, so a reader knows ``data`` is where the payload is;
* the **error responses** every route can return, so a client's error handling
  is written once against a documented shape rather than discovered in
  production;
* an **authentication placeholder**. No endpoint requires a credential today -
  local demo mode is the point - but the scheme is declared as optional so a
  generated client already has the ``Authorization`` seam, and so nobody has to
  guess later which header the API will want. See
  ``docs/API_AUTHENTICATION_PLAN.md``.
"""

from __future__ import annotations

from typing import Any

API_DESCRIPTION = """
A local workbench of ten SAP-focused AI applications. Everything runs on one
machine: **no SAP system, no SAP credentials, no paid API and no AI API key are
required.**

## What this API is, and is not

Every figure this API returns - every risk score, saving, ranking, exception,
forecast and mark - is calculated by ordinary, inspectable Python from the file
you uploaded. AI is used for *language*: explaining a finding, summarising a
result, drafting the prose of a test case or a blueprint section. It never
decides a number, and its output always lands in its own fields.

**No output here has been validated in a live SAP environment, and no data comes
from one.** The bundled datasets are fictional and were written for this lab.

## The response envelope

Every JSON endpoint returns the same four keys, so a client writes one response
handler and one error handler:

```json
{
  "success": true,
  "data": { "...": "the payload, or null on failure" },
  "error": null,
  "meta": { "timestamp": "2026-08-01T09:12:33.481Z",
            "request_id": "4864bdb5c1e0",
            "api_version": "v1" }
}
```

On a failure, `success` is `false`, `data` is `null` and `error` carries
`{code, message, details}`. The `message` is always safe to show a user: it
never contains a file path, a stack trace or a provider payload. `request_id`
matches the `X-Request-ID` response header and appears in the server log, so a
user can quote it in a support request.

**Downloads are the one exception.** `/export` and `/sample` routes return the
file itself with a `Content-Disposition` header, because a browser cannot stream
a base64 blob out of a JSON envelope. `Content-Disposition` is in the CORS
`Access-Control-Expose-Headers` list so a `fetch` client can read the filename.

## Where every value came from

Anything a user sees carries an `output_origin`:

| Value | Meaning |
| --- | --- |
| `rule_based` | Computed by deterministic Python. |
| `forecast` | Produced by a statistical model, with its interval. |
| `ai_generated` | Written by a configured AI provider. |
| `mock_ai` | Written by the built-in deterministic mock. |
| `demo_data` | Comes from the bundled fictional sample data. |

## Paging, filtering and sorting

Every list endpoint takes `limit` and `offset` (both bounded), and every list
response echoes `total`, `limit` and `offset` back - so a client can tell 100 of
137 from all 100. Filters are query parameters and are documented per endpoint.
Ordering is fixed per endpoint and stated in its description, because a caller
paging through a result set needs it to be stable.

## Authentication

There is none, deliberately: this is a local lab. The `bearerAuth` scheme is
declared as *optional* so a generated client already carries the seam.
`docs/API_AUTHENTICATION_PLAN.md` describes the JWT, user, organisation,
workspace and tenant-isolation model that would fill it in.

## AI providers

The mock provider is the default and needs no key. Set `AI_PROVIDER` and the
matching key to use Anthropic or OpenAI. An AI failure is never fatal: the
deterministic result is returned regardless and the failure is reported in the
narrative's `error` field. `GET /{module}/ai-status` reports which provider is
active - never the key.
"""

#: Tag metadata. The order here is the order the tags appear in ``/docs``.
OPENAPI_TAGS: list[dict[str, Any]] = [
    {
        "name": "System",
        "description": (
            "Health, the module index and the OpenAPI document. `GET /api/v1/health` "
            "reports the database and the resolved AI provider and needs no credential - "
            "it is what a container healthcheck polls."
        ),
    },
    {
        "name": "Purchase Order Risk Checker",
        "description": (
            "**Module 1.** Upload an SAP-style purchase order export and get findings from "
            "20 deterministic rules: duplicates, split orders, price anomalies, missing "
            "approvals, contract gaps, late deliveries and data quality problems. Every "
            "finding carries its rule, its evidence, a severity and an estimated exposure. "
            "Upload → analyse → read findings → download the report."
        ),
    },
    {
        "name": "Spend Analytics Dashboard",
        "description": (
            "**Module 2.** Turn a procurement transaction export into the figures a category "
            "manager asks for: spend under management, maverick spend, contract leakage, "
            "supplier concentration, price variance and modelled savings. Every opportunity "
            "is labelled an estimate and states the assumption behind it. The drill-down "
            "endpoint returns exactly the transactions behind any chart element."
        ),
    },
    {
        "name": "Supplier Recommendation Engine",
        "description": (
            "**Module 3.** Rank the suppliers that can meet a requirement, using nine "
            "normalised scores and configurable weights. Eligibility is applied *before* "
            "ranking, and a supplier that was excluded says why."
        ),
    },
    {
        "name": "Invoice Validator",
        "description": (
            "**Module 4.** Three-way match invoices against purchase orders and goods "
            "receipts with configurable tolerances, and raise exceptions from 17 rules: "
            "quantity and price mismatches, duplicates, overbilling, date problems and "
            "missing documents. Upload the three datasets, then validate."
        ),
    },
    {
        "name": "Supplier Risk Copilot",
        "description": (
            "**Module 5.** Score a supplier portfolio across ten risk categories with a "
            "transparent weighted model, then ask questions answered *from the loaded "
            "records* with citations. A question the data cannot answer is refused and "
            "says why, rather than being guessed."
        ),
    },
    {
        "name": "Contract Assistant",
        "description": (
            "**Module 6.** Extract clauses, key dates, obligations and risks from a "
            "text-based PDF, DOCX or TXT contract. Every claim carries a page number, a "
            "section heading, an excerpt and a deterministic confidence score. A scanned "
            "document is reported as needing OCR rather than analysed as an empty contract. "
            "Uploaded documents are treated strictly as data."
        ),
    },
    {
        "name": "Inventory Predictor",
        "description": (
            "**Module 7.** Forecast demand per material and plant with five explainable "
            "statistical models chosen by backtesting, project stock forward over real "
            "calendar days, and get shortage dates, reorder plans and stock "
            "classifications. No AI produces any number here."
        ),
    },
    {
        "name": "SAP Test Case Generator",
        "description": (
            "**Module 8.** Describe an SAP business process and get an editable test suite "
            "across eight test types. The identifiers, the type coverage, the priorities "
            "and the step numbering are decided by code before a provider is contacted; "
            "only the wording is drafted. Edit, approve, record execution results, export."
        ),
    },
    {
        "name": "SAP Blueprint Generator",
        "description": (
            "**Module 9.** Describe an SAP implementation project and get a thirty-section "
            "blueprint you can edit, approve, version and compare. Sections computed from "
            "the project request cannot be invented by a model, and a section with no input "
            "says so instead of being filled in."
        ),
    },
    {
        "name": "SAP Interview Coach",
        "description": (
            "**Module 10.** Practise SAP interview questions and get a scored, explained "
            "result. The rubric marks the answer; a provider is only ever asked for the "
            "prose around a finished verdict, so the same answer scores the same with a "
            "real model, with the mock, or with no AI at all. An answer key never travels "
            "with an unanswered question."
        ),
    },
]

#: The security scheme placeholder. Declared, referenced as optional, enforced
#: nowhere - see the module docstring.
SECURITY_SCHEMES: dict[str, Any] = {
    "bearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": (
            "**Not enforced.** No endpoint in this lab requires a credential; it runs "
            "locally with no user accounts. The scheme is declared so a generated client "
            "already carries the `Authorization: Bearer <token>` seam, and so the shape of "
            "the future contract is written down rather than guessed. "
            "See `docs/API_AUTHENTICATION_PLAN.md`."
        ),
    }
}


def _error_example(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build one error envelope example."""
    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message, "details": details or {}},
        "meta": {
            "timestamp": "2026-08-01T09:12:33.481Z",
            "request_id": "4864bdb5c1e0",
            "api_version": "v1",
        },
    }


#: Error responses every route can produce, documented once and attached to all
#: of them. Without these an OpenAPI reader sees only the happy path and a
#: generated client's error handling gets written against a guess.
COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "description": "The upload was rejected before anything was stored.",
        "content": {
            "application/json": {
                "examples": {
                    "wrong_type": {
                        "summary": "A file type this endpoint does not accept",
                        "value": _error_example(
                            "file_validation_error",
                            "File type '.pdf' is not supported. Allowed types: .csv, .json, .xlsx",
                            {"allowed_extensions": [".csv", ".json", ".xlsx"]},
                        ),
                    },
                    "too_large": {
                        "summary": "Past the configured size limit",
                        "value": _error_example(
                            "file_validation_error",
                            "The file is larger than the 25 MB limit.",
                            {"max_bytes": 26214400},
                        ),
                    },
                    "empty": {
                        "summary": "An empty payload",
                        "value": _error_example(
                            "file_validation_error", "The uploaded file is empty."
                        ),
                    },
                }
            }
        },
    },
    404: {
        "description": "No resource with that identifier exists.",
        "content": {
            "application/json": {
                "example": _error_example(
                    "not_found",
                    "Analysis not found.",
                    {"analysis_id": "does-not-exist"},
                )
            }
        },
    },
    422: {
        "description": (
            "The request body or a query parameter failed validation. `details.errors` "
            "lists up to ten problems, each naming the field it is about."
        ),
        "content": {
            "application/json": {
                "example": _error_example(
                    "request_validation_error",
                    "The request could not be validated.",
                    {
                        "errors": [
                            {
                                "type": "missing",
                                "loc": ["body", "upload_id"],
                                "msg": "Field required",
                            }
                        ]
                    },
                )
            }
        },
    },
    500: {
        "description": (
            "Something unexpected failed. The message is deliberately generic; the full "
            "traceback is in the server log against the `request_id` shown here."
        ),
        "content": {
            "application/json": {
                "example": _error_example(
                    "internal_error",
                    "An unexpected error occurred. Check the server log for details.",
                )
            }
        },
    },
}

#: The subset that applies to a route with no request body and no upload.
READ_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: COMMON_ERROR_RESPONSES[status] for status in (404, 422, 500)
}

#: Responses for a binary download route.
DOWNLOAD_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": (
            "The file itself, not the JSON envelope. `Content-Disposition` carries the "
            "filename to save it under and is exposed to cross-origin clients."
        ),
        "content": {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
            "text/csv": {},
            "application/json": {},
            "application/pdf": {},
        },
    },
    **READ_ERROR_RESPONSES,
}


def _restore_null_fields(node: Any) -> None:
    """Put ``"data": null`` back into every error example.

    FastAPI runs examples through an encoder that drops ``None`` values, so the
    documented error loses its ``data`` key - while the API really does send
    ``"data": null``. A front-end author reading the document would conclude the
    key is absent on failure and write ``"data" in body`` as their success test.
    The four keys are always present; the document has to say so.
    """
    if isinstance(node, dict):
        if node.get("success") is False and "data" not in node:
            node["data"] = None
        for value in node.values():
            _restore_null_fields(value)
    elif isinstance(node, list):
        for item in node:
            _restore_null_fields(item)


def customise_openapi(schema: dict[str, Any]) -> dict[str, Any]:
    """Add the pieces FastAPI cannot infer to a generated OpenAPI document."""
    _restore_null_fields(schema.get("paths", {}))
    schema.setdefault("components", {})["securitySchemes"] = SECURITY_SCHEMES
    # Declared, not required: an empty requirement alongside the scheme means
    # "this may be sent", which is exactly the state of play.
    schema["security"] = [{}, {"bearerAuth": []}]
    schema["info"]["contact"] = {"name": "SAP AI Application Lab (local demo)"}
    schema["info"]["x-disclaimer"] = (
        "Demo application. Not connected to any SAP system. No output has been validated "
        "in a live SAP environment, and no figure here is a guarantee."
    )
    return schema
