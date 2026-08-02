# Demonstration security checklist

Work through this before the deployment is reachable by anyone else, and again
after any change to the compose file, the environment or the demonstration
switches.

`./scripts/verify_selfhosted.sh` automates most of section 1. It is necessary
and not sufficient — sections 2 to 6 need a person.

---

## 0. The threat model, stated

Who this protects against, and who it does not:

| Protected against | How |
| --- | --- |
| A stranger uploading a file | Uploads refused server-side, not hidden |
| A stranger reaching the API | No public hostname, no published port, isolated network |
| A stranger reaching the database | Same, plus `internal: true` |
| An unexpected AI bill or data egress | Provider forced to mock; no key configured |
| A malicious document | Untrusted-text handling, no OCR configured, uploads off anyway |
| Casual discovery of the demonstration | Cloudflare Access with an explicit allow list |
| Abuse of the contact form | Off by default; Turnstile verified server-side, fails closed; two rate-limit buckets; nothing stored |

| **Not** protected against | Why |
| --- | --- |
| One invited visitor seeing another's records | **There is no authentication.** Session-scoped views are a display filter. |
| An invited visitor abusing the demonstration | They were invited; the data is fictional |
| The machine, the router or the ISP failing | One laptop, one connection |
| Someone with physical access to the Mac | FileVault helps; nothing else here does |

**Do not describe this deployment as multi-tenant, authenticated or
production-ready.** It is a demonstration on fictional data with an invitation
list.

---

## 1. Automated

```bash
./scripts/verify_selfhosted.sh
```

- [ ] The compose file is valid and the environment has every required setting
- [ ] `database`, `api`, `streamlit`, `website` all report **healthy**
- [ ] The database publishes **no** port
- [ ] Nothing is published on `0.0.0.0`
- [ ] The API publishes no port (or is on `127.0.0.1` only, under the debug overlay)
- [ ] The website **cannot** reach the API — it is on the edge network only
- [ ] Streamlit reaches the API privately, by service name
- [ ] `demo_mode` is on and `uploads_enabled` is false
- [ ] A **real** upload request returns 403
- [ ] The AI provider is the mock
- [ ] All ten guided demonstrations are described, and the database holds data
- [ ] No configured secret appears in the last 500 log lines
- [ ] An API error carries no path, trace or connection string
- [ ] The named database volume exists

---

## 2. Secrets

- [ ] `git status` is clean and shows no `.env` file
- [ ] `git ls-files | grep '^\.env'` returns only `*.example` files
- [ ] `.env.selfhosted.example` contains **no** real values — the tunnel token
      line is empty and the password says `replace-me`
- [ ] `POSTGRES_PASSWORD` is generated, not the placeholder, not reused from
      anywhere else
- [ ] `DATABASE_URL` contains the same password (`validate_env` checks this)
- [ ] The Cloudflare tunnel token exists **only** in `.env.selfhosted` on the Mac
- [ ] No token, password or key has been pasted into a commit, an issue, a
      screenshot, a chat or a recorded terminal
- [ ] `python scripts/check_quality.py` passes its secret scan
- [ ] No `.dump`, `.sql.gz` or `backups/` path is tracked by git
- [ ] `SMTP_APP_PASSWORD` is a Gmail **App Password**, not the account password,
      and exists only in `.env.selfhosted`
- [ ] `TURNSTILE_SECRET_KEY` is the secret key, not the site key, and is set as
      a **runtime** variable — never a build argument, which Docker records in
      the image history
- [ ] `CONTACT_RATE_LIMIT_SECRET` is generated (`openssl rand -hex 32`) rather
      than left at any example value
- [ ] No contact variable has been given a `NEXT_PUBLIC_` prefix. Only
      `NEXT_PUBLIC_TURNSTILE_SITE_KEY` is public, and it is a site key
- [ ] The deployed bundle contains no secret:
      `docker compose -f docker-compose.selfhosted.yml run --rm --entrypoint sh website -c
      "grep -rl 'TURNSTILE_SECRET\|SMTP_APP_PASSWORD' .next/static || echo clean"`

```bash
git ls-files | grep -E '^\.env|\.dump$|^backups/|node_modules' || echo "clean"
```

---

## 3. Network boundaries

```bash
docker compose --env-file .env.selfhosted -f docker-compose.selfhosted.yml ps
```

- [ ] The `PORTS` column shows **no** `->` mapping for any service
- [ ] The debug overlay is **not** loaded (no `docker-compose.debug.yml`)
- [ ] `sapdemo-internal` is declared `internal: true`
- [ ] `api` and `database` are on `internal` only
- [ ] `website` is on `edge` only
- [ ] `cloudflared` is on `edge` only — it must not be able to route to the API
- [ ] No router port forwarding rule exists for this machine
- [ ] `docker-compose.debug.yml` binds only to `127.0.0.1`, and never the database

From another machine on the same network, confirm nothing answers:

```bash
nc -zv <mac-ip> 3000 8000 8501 5432    # all should be refused
```

---

## 4. Cloudflare

- [ ] `[DOMAIN]` and `www.[DOMAIN]` route to `website:3000`
- [ ] `demo.[DOMAIN]` routes to `streamlit:8501`
- [ ] **No `api.` hostname exists.** Check the tunnel's public hostnames *and*
      the DNS records
- [ ] No route points at `api:8000` or `database:5432`
- [ ] An Access application protects `demo.[DOMAIN]`
- [ ] Its policy uses **Emails** with exact addresses — not "Emails ending in",
      not "Everyone"
- [ ] One-time PIN is the only login method
- [ ] Session duration is reasonable (24 hours or less)
- [ ] An explicit **Block / Everyone** policy sits below the allow rule
- [ ] The marketing site is **not** behind Access
- [ ] MX, SPF, DKIM, DMARC and verification records survived the migration, and
      **mail has been tested in both directions**

Tested from cellular data, not your own wifi:

- [ ] `https://[DOMAIN]` loads without a login
- [ ] `https://demo.[DOMAIN]` prompts for Access
- [ ] An address **not** on the allow list is refused
- [ ] `https://api.[DOMAIN]` does not resolve

---

## 5. The demonstration itself

Open it and use it.

- [ ] `Public Demo — Fictional Data Only` appears on every page
- [ ] The "what you must not enter" list is present and readable
- [ ] **No file-upload control appears on any of the ten pages**
- [ ] Each module's guided demonstration loads and produces a result
- [ ] Results are labelled with their origin
- [ ] The AI narrative is labelled **Mock AI output**
- [ ] A report downloads
- [ ] No page displays a filesystem path, a stack trace or an internal hostname
- [ ] Triggering an error shows a safe message

Then try to break it:

- [ ] `curl -F "file=@x.csv" https://demo.[DOMAIN]/api/v1/po-risk/upload` — the
      API is not reachable through the demonstration hostname at all
- [ ] Open a second browser profile and confirm the history views show only that
      session's records

---

## 5a. The contact form

Skip this section entirely when `CONTACT_FORM_ENABLED` is false — the page shows
`mailto:` links and `/api/contact` returns 404, which is the shipped default and
needs no further checking.

When it **is** on, this is the only endpoint on the public site that accepts an
unauthenticated write, so check it by hand rather than by reading the config:

- [ ] The contact page renders the form **and** the Turnstile widget. A form
      without a widget means the site key is missing from the *build*, and the
      page must not be left in that state
- [ ] The privacy page describes the form. If it still says "There is no contact
      form on this site", the flag and the page disagree and one of them is lying
- [ ] Submitting with the widget untouched is refused
- [ ] A message actually arrives in `CONTACT_RECIPIENT_EMAIL`, and its
      `Reply-To` is the address that was typed
- [ ] The delivered email contains no IP address and no Turnstile token
- [ ] Submitting more than `CONTACT_RATE_LIMIT_MAX` times within
      `CONTACT_RATE_LIMIT_WINDOW_SECONDS` returns 429 with a `Retry-After`
- [ ] Repeated submissions carrying a **failed** challenge do not consume the
      allowance of the email address they name. The email bucket is charged
      only after Turnstile passes, so a stranger cannot lock somebody else out
- [ ] `TURNSTILE_EXPECTED_HOSTNAMES` and `TURNSTILE_EXPECTED_ACTION` are set.
      The site key is public, so without these a token solved on an attacker's
      own page under the same key verifies here
- [ ] `docker compose logs website | grep '\[contact\]'` shows outcome codes
      only — no message body, no visitor address, no IP, no token
- [ ] Forging a submission bypasses nothing:

```bash
curl -sS -X POST https://[DOMAIN]/api/contact \
  -H 'content-type: application/json' \
  -d '{"name":"x","email":"a@b.co","subject":"s","message":"'"$(printf 'y%.0s' {1..30})"'","turnstileToken":"forged"}'
# expect 403 and a generic message - the token is verified with Cloudflare
# server-side, so one invented here cannot pass
```

- [ ] Temporarily unset `TURNSTILE_SECRET_KEY` and restart: the endpoint returns
      **404** and the page reverts to `mailto:`. It must never serve a form with
      no challenge behind it. Restore the key afterwards

---

## 6. Before you say it is production-ready

Do not. Specifically, do not claim:

- [ ] ~~It is authenticated~~ — it is not
- [ ] ~~Visitors are isolated~~ — they are not
- [ ] ~~It is highly available~~ — it is one laptop
- [ ] ~~It is connected to SAP~~ — it is not
- [ ] ~~Its output has been validated in a live SAP environment~~ — it has not
- [ ] ~~Its savings figures are savings~~ — they are estimates, labelled as such
- [ ] ~~It is production-ready~~ — it is a demonstration

Everything in that list is stated on the public website too, on
`/demo-disclaimer` and `/terms`.

---

## If something is exposed

1. `./scripts/stop_selfhosted.sh` — this is always the first step.
2. If the tunnel token leaked: delete the tunnel in Cloudflare. The old token
   dies with it. Create a new one.
3. If the database password leaked: change it in `.env.selfhosted` (both
   `POSTGRES_PASSWORD` and `DATABASE_URL`), then recreate the volume — the data
   is fictional and reseeds in minutes.
4. If an Access policy was too broad: fix it, then check the Access logs for who
   actually reached the demonstration.
5. Only then start again, and re-run this checklist from the top.
