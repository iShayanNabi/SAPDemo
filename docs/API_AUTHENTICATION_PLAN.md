# API authentication plan

How this API grows from "one local user, no accounts" into something a public
website can sit in front of — and what already exists so that change is small.

**Nothing in this document is implemented.** The seams described in
[`app/core/auth.py`](../app/core/auth.py) are, and `GET /api/v1/auth-status`
reports the current state honestly: authentication is off, every request
resolves to a demo principal holding every role.

---

## Why write this down before building it

Two of the decisions below are cheap now and expensive later, and both are
about *queries* rather than about login screens.

**Tenant scoping.** `GET /api/v1/po-risk/analyses` returns every analysis in the
database. With one local user that is correct. With two customers it is a data
leak, and the fix is not a middleware — it is a `WHERE organization_id = ?` on
every list query, every detail lookup and every export. Retrofitting that clause
into a codebase that never had one means finding all of them, and the one that
gets missed is the one nobody notices until a customer sees another customer's
supplier names. `tenant_scope()` exists so the question is already asked.

**Who approved this.** Modules 8, 9 and 10 record an approver's name, and the
project's own rule is that an approval whose subject has changed must be flagged
rather than quietly kept. Today `approved_by` is a free-text field a caller
supplies — which is fine for a demo and is not an audit trail. When accounts
exist, that field becomes a foreign key to a user, and the difference between
"Ingrid typed her name" and "Ingrid was authenticated" is the difference between
a demo and a record.

---

## What exists today

| Piece | Where | State |
| --- | --- | --- |
| `Principal` (subject, org, workspace, roles) | `app/core/auth.py` | Built, always the demo principal |
| `get_principal` dependency | `app/core/auth.py` | Built, never raises |
| `require_roles(...)` dependency factory | `app/core/auth.py` | Built, passes (the demo principal holds every role) |
| `tenant_scope(principal)` | `app/core/auth.py` | Built, returns the demo org/workspace, used by nothing yet |
| `AuthorizationError` → HTTP 403 | `app/core/auth.py` | Built, distinct from 401 |
| `bearerAuth` security scheme | `app/api/openapi.py` | Declared in OpenAPI, marked optional |
| `Authorization` in the CORS allow list | `app/main.py` | Configured |
| `GET /api/v1/auth-status` | `app/api/v1/router.py` | Reports all of the above |

The demo principal holds every role deliberately. The permission checks *run* on
every request and pass; they are not bypassed. So the branch that will one day
return 403 is exercised code, not code that has never executed.

---

## 1. JWT authentication

### The token

A short-lived access token, a longer-lived refresh token, both signed.

```json
{
  "iss": "https://api.example.com",
  "sub": "usr_01HQ8...",
  "org": "org_01HQ7...",
  "ws":  "ws_01HQ9...",
  "roles": ["analyst", "approver"],
  "iat": 1785312000,
  "exp": 1785315600,
  "jti": "tok_01HQA..."
}
```

Decisions worth stating rather than defaulting into:

- **Asymmetric signing (RS256/EdDSA), not HS256.** The API verifies with a
  public key; only the issuer holds the private one. With HS256 every service
  that verifies a token can also mint one, so a read-only service becomes a
  credential-issuing service by accident.
- **15-minute access tokens, 30-day refresh tokens, refresh rotation.** A stolen
  access token expires on its own. A stolen refresh token is detectable: when a
  rotated token is presented twice, the family is revoked.
- **`org` and `ws` in the claims.** Not looked up per request. The scope of a
  query must not depend on a second database round trip that could fail open.
- **`jti` and a revocation list.** "Log out everywhere" and "this employee left"
  both need a token to stop working before it expires.

### Where it plugs in

One function changes:

```python
def get_principal(authorization: str | None = Header(None)) -> Principal:
    if not authentication_enabled():
        return DEMO_PRINCIPAL                      # today
    token = _bearer(authorization)                  # 401 if absent or malformed
    claims = verify_jwt(token, public_key, issuer)  # 401 if invalid or expired
    return Principal(
        subject=claims["sub"],
        organization_id=claims["org"],
        workspace_id=claims["ws"],
        roles=frozenset(Role(r) for r in claims["roles"]),
        is_anonymous=False,
    )
```

Every route and every query that already asks for a `Principal` keeps working.

### Endpoints to add

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/auth/register` | Create a user and an organisation |
| `POST` | `/api/v1/auth/login` | Exchange credentials for a token pair |
| `POST` | `/api/v1/auth/refresh` | Rotate the refresh token |
| `POST` | `/api/v1/auth/logout` | Revoke the presented refresh token family |
| `GET` | `/api/v1/auth/me` | The current principal (already shaped by `auth-status`) |
| `POST` | `/api/v1/auth/password-reset` | Request and complete a reset |

Passwords hashed with Argon2id (or bcrypt), never anything faster.

---

## 2. The data model

Four tables, added in one Alembic revision alongside the columns that reference
them.

### `organizations`

The billing and isolation boundary. Everything a customer owns hangs off one.

| Column | Notes |
| --- | --- |
| `id` | `org_` prefixed |
| `name`, `slug` | Slug unique, used in URLs |
| `plan` | `free` / `team` / `enterprise` |
| `created_at`, `updated_at` | |

### `users`

| Column | Notes |
| --- | --- |
| `id` | `usr_` prefixed |
| `email` | Unique, case-folded on write |
| `password_hash` | Argon2id. Never logged, never serialised |
| `display_name` | What appears in `approved_by` |
| `is_active` | Deactivation without deletion, so history survives |
| `last_login_at` | |

A user belongs to organisations through `organization_members`
(`organization_id`, `user_id`, `role`), so somebody can be an analyst in one and
an admin in another. Their role is a property of the *membership*, not of the
person.

### `workspaces`

A workspace is a folder inside an organisation: "EMEA procurement", "FY26 audit".
It is what keeps one team's 400 analyses out of another team's list.

| Column | Notes |
| --- | --- |
| `id` | `ws_` prefixed |
| `organization_id` | FK, cascade |
| `name`, `slug` | Slug unique per organisation |

Every organisation gets a `default` workspace on creation, so the concept never
has to be explained to a single-team customer.

### Ownership columns

Every table that today has no owner gets three columns:

```
organization_id  FK -> organizations, NOT NULL, indexed
workspace_id     FK -> workspaces,    NOT NULL, indexed
created_by       FK -> users,         NULL until backfilled
```

on `uploaded_files`, `po_analyses`, `spend_analyses`, `supplier_catalogs`,
`supplier_recommendations`, `invoice_validations`, `supplier_risk_datasets`,
`supplier_risk_assessments`, `contracts`, `inventory_datasets`,
`inventory_forecasts`, `test_suites`, `blueprints` and `interview_sessions`.

Child tables (`po_findings`, `contract_clauses`, …) do **not** get them: they
reach their organisation through their parent, and a denormalised copy is a
second source of truth that will eventually disagree with the first.

**The backfill is why the demo constants exist.** Existing rows are updated to
`org_local_demo` / `ws_local_demo` in the same migration that adds the columns,
so they can be `NOT NULL` immediately. A nullable tenant column is a column that
will hold a null, and a null tenant matches every filter written with `!=`.

---

## 3. Role-based access control

| Role | Can |
| --- | --- |
| `viewer` | Read analyses, findings, dashboards and exports |
| `analyst` | Everything a viewer can, plus upload, analyse, generate and edit |
| `approver` | Everything an analyst can, plus approve a test case or a blueprint section |
| `admin` | Everything, plus manage members, workspaces and organisation settings |

Applied per route:

```python
@router.post("/upload", dependencies=[Depends(require_roles(Role.ANALYST))])
@router.post("/{id}/approve", dependencies=[Depends(require_roles(Role.APPROVER))])
```

Approval is a separate role from editing on purpose. "I wrote this test case and
I approved it" is the situation the approval field exists to prevent being
invisible, and the same reasoning that gave module 8 its stale-approval flag
gives module 8 a separate permission.

---

## 4. Tenant isolation

The rule: **a query that can return a row belonging to another organisation is a
bug, whatever else it does correctly.**

Three layers, because one is not enough:

1. **Every list query filters.** `select(PoAnalysis).where(**tenant_scope(principal))`.
2. **Every detail lookup verifies after fetching.** `db.get()` by primary key
   cannot filter, so the ownership check is a separate line — and it returns
   **404, not 403**, because "this analysis belongs to someone else" tells an
   attacker the id is real.
3. **A test that tries.** Two organisations, one analysis each, and an assertion
   that each 404s on the other's id — for every module. This is the test that has
   to exist before the first customer, not after the first incident.

The database-level backstop worth considering for PostgreSQL is row-level
security: a policy on `organization_id` and a session variable set per request.
It costs a little and it turns a missed `WHERE` clause from a leak into an empty
result.

---

## 5. API permissions beyond roles

Two things roles do not cover, both worth a plan before they are needed:

- **API keys for machine callers.** A scheduled job that uploads a nightly spend
  export should not hold a user's password. A key is a principal with a fixed
  role, an organisation, an expiry and a last-used timestamp, presented as
  `Authorization: Bearer sk_live_...`. Same `Principal`, different resolver.
- **Rate limits, per principal rather than per IP.** Analysis is the expensive
  operation and an IP is shared by an office. Limits belong on
  `POST /*/analyze`, `/validate`, `/forecast`, `/generate` and the AI-backed
  chat and question endpoints. This is the one place Redis earns its keep — a
  counter shared across API replicas — which is why the compose file declares
  the service and leaves it off.

---

## 6. What must not change

Three properties the current API has that authentication must not cost it:

- **`GET /api/v1/health` stays open.** A healthcheck cannot log in. The
  container, the load balancer and the uptime monitor all poll it.
- **The response envelope stays the same.** `401` and `403` are
  `{success, data, error, meta}` like everything else, with codes
  `unauthorized` and `forbidden`. A front end's error handler must not need a
  special case for auth.
- **Local demo mode keeps working.** `AUTH_ENABLED=false` (the default) must
  keep the whole lab runnable with no accounts, no database of users and no
  token — because that is what makes it possible to clone the repository and see
  something work in five minutes.

---

## 7. Order of work

1. `organizations`, `users`, `workspaces`, `organization_members` + the ownership
   columns, backfilled to the demo constants. **No behaviour change.**
2. Real `get_principal`, behind `AUTH_ENABLED`. Login, refresh, logout, me.
3. Tenant filters in every query, with the cross-organisation 404 test per
   module. Still with `AUTH_ENABLED=false` in local development.
4. `require_roles` on the routes that change something.
5. API keys and rate limits.

Steps 1 and 3 are the ones that must not be skipped or reordered: the columns
have to exist before the filters can use them, and the filters have to exist
before a second organisation does.
