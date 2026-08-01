# Deployment options

Where this can run, what each option costs in effort, and what has to be true
before any of them is a good idea.

**Read this first:** the lab has **no authentication**. Every caller can read
every analysis and every uploaded file. Options 1 and 2 below are for a laptop
or a private network. Anything reachable from the internet needs
[`API_AUTHENTICATION_PLAN.md`](API_AUTHENTICATION_PLAN.md) implemented first —
that is not a hardening nicety, it is the difference between a demo and a data
leak.

---

## The shape of the thing being deployed

Two processes and a database:

```text
┌──────────────┐   HTTP    ┌──────────────────┐
│  Streamlit   │──────────▶│                  │
│  (optional)  │           │  FastAPI         │──▶ SQLite file
└──────────────┘           │  uvicorn         │    or PostgreSQL
                           │                  │
┌──────────────┐   HTTP    │  rules · engines │──▶ data/uploads
│ Future site  │──────────▶│  services · AI   │    data/exports
└──────────────┘           └──────────────────┘
```

The Streamlit UI is a *client*. It imports no business logic and talks to the
API over HTTP like any other front end, so deleting it breaks nothing. Deploy it
if you want the demo interface; leave it out if you are building a website.

State lives in exactly three places: the database, `data/uploads/` and
`data/exports/`. Everything else in the image is code and committed demo data.

---

## Option 1 — Local virtualenv

**For:** development, the demo, following the README.
**Effort:** five minutes. **Cost:** nothing.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/verify_setup.py

uvicorn app.main:app --reload            # terminal 1
streamlit run streamlit_app/Home.py      # terminal 2
```

SQLite, mock AI, no keys, no Docker. This is the supported path and the one the
tests run on.

**Do not put `--reload` in front of anything but your own laptop.** It watches
the filesystem and restarts on every change, which is wonderful locally and a
denial-of-service vector anywhere else.

---

## Option 2 — Docker Compose

**For:** reproducing the runtime on another machine, exercising the PostgreSQL
path without installing a database, an internal demo on a private network.
**Effort:** one command. **Cost:** nothing.

```bash
docker compose up api ui                 # SQLite, the default
docker compose --profile postgres up     # + PostgreSQL
```

The optional services sit behind profiles, so `docker compose up` starts nothing
you did not ask for. See [`docker-compose.yml`](../docker-compose.yml) for the
full set of variables; the ones that matter are `DATABASE_URL`, `AI_PROVIDER`,
`CORS_ORIGINS` and the two API keys, all read from your shell rather than
written into the file.

The image (`Dockerfile`) is two-stage, runs as a non-root user, applies Alembic
migrations on start and declares a healthcheck against `/api/v1/health`. One
image, three commands: `lab-api`, `lab-streamlit`, `lab-migrate`.

Data persists in the `lab-data` volume. `docker compose down` keeps it;
`docker compose down -v` deletes it.

**Docker is optional.** Nothing in the project requires it, and Option 1 is the
path the documentation is written around.

---

## Option 3 — A single virtual machine

**For:** a real internal deployment for a team, behind a VPN or an SSO proxy.
**Effort:** an afternoon. **Cost:** one small VM.

A 2 vCPU / 4 GB machine runs this comfortably. Analysis is CPU-bound and
in-process, so vCPUs matter more than RAM until files get large.

```text
Caddy or nginx  ──▶  uvicorn (systemd, 2-4 workers)  ──▶  PostgreSQL (same host or managed)
   TLS, gzip                                              data/ on a persistent disk
```

What has to be different from a laptop:

| Setting | Value | Why |
| --- | --- | --- |
| `ENVIRONMENT` | `staging` / `production` | Changes nothing behaviourally; it is what the logs and `reset_demo.py` check |
| `DEBUG` | `false` | |
| `LOG_JSON` | `true` | Structured logs are what a log aggregator can search |
| `DATABASE_URL` | `postgresql+psycopg://…` | See "PostgreSQL" below |
| `CORS_ORIGINS` | the real front-end origin | Never `*` — see below |
| `AI_PROVIDER` | `mock` until costs are attributable | A real provider on an open endpoint is somebody else's bill |

Run uvicorn with several workers (`--workers 4`) behind the reverse proxy, and
`--proxy-headers` so the client IP in the logs is the real one. Put TLS at the
proxy; the application does not terminate it.

Back up the database and `data/uploads/` on the same schedule. An analysis whose
source file is gone can still be read, but it cannot be re-run.

---

## Option 4 — A container platform

**For:** a public website's backend. **Effort:** a day, plus the prerequisites
below. **Cost:** from a few dollars a month upwards.

The image runs unchanged on Fly.io, Railway, Render, Google Cloud Run, AWS App
Runner, ECS or any Kubernetes. What differs is not the image, it is the four
things a container platform forces you to be honest about:

**1. The filesystem is ephemeral.** `data/uploads/` and `data/exports/` vanish on
every deploy and are not shared between replicas. Either mount a persistent
volume and run exactly one replica, or move files to object storage — the
presigned-URL shape is sketched in
[`FUTURE_WEBSITE_INTEGRATION.md`](FUTURE_WEBSITE_INTEGRATION.md).

**2. SQLite does not survive it.** A file database on ephemeral disk loses every
analysis on deploy, and two replicas each get their own copy. PostgreSQL is not
optional here.

**3. Requests have a timeout.** Cloud Run's default is 5 minutes, most load
balancers are 30–60 seconds. A synchronous analysis of a large file will exceed
it. Either cap the upload size well below the row limit, or move analysis to a
worker — the `pending`/`running`/`completed` states and the client's polling
helper already exist for that day.

**4. Scale-to-zero costs a cold start.** The first request after idle pays for
importing pandas, numpy, scikit-learn and statsmodels — seconds, not
milliseconds. Fine for an internal tool, visible on a marketing site. Keep one
instance warm if that matters.

Minimum sensible configuration: 1 vCPU, 1 GB RAM per instance, `API_WORKERS=1`
(let the platform scale instances, not processes), `RUN_MIGRATIONS=true` on one
instance only or as a separate release step.

---

## PostgreSQL

The project is PostgreSQL-ready and tested that way: the migrations render for
the PostgreSQL dialect in the test suite, and `UtcDateTime` exists precisely
because SQLite and PostgreSQL disagree about timestamps.

```bash
# 1. Uncomment in requirements.txt
psycopg[binary]==3.2.3

# 2. Point at it
DATABASE_URL=postgresql+psycopg://sap_lab:password@localhost:5432/sap_ai_lab

# 3. Build the schema
alembic upgrade head
```

Nothing else changes. The engine picks up connection pooling automatically
(`pool_size=5, max_overflow=10`); tune it against your instance's connection
limit, remembering that every uvicorn worker holds its own pool.

Two things to check the first time, because they are what SQLite hid:

- **Timestamps come back with an offset.** Every one is UTC-aware through
  `UtcDateTime`, and the XLSX exports strip the tzinfo before writing, because
  Excel has no concept of a timezone. Both have tests.
- **Foreign keys are enforced without a pragma.** SQLite needs
  `PRAGMA foreign_keys=ON` per connection; PostgreSQL always enforces them. A
  cascade that worked locally will work, but a cascade that never *ran* locally
  will run for the first time here.

---

## Redis

Nothing in this project uses Redis, and the compose file declares it behind a
profile that is off by default.

That is a decision, not an omission. Every analysis is synchronous and finishes
in seconds; the only caches are process-local and small. Adding a broker today
buys an extra moving part, an extra failure mode and no measurable benefit.

Two things will genuinely need it, and both are named in the plan documents so
the seam is not a surprise:

- **A job queue** (Celery or RQ) when large uploads move off the request path.
- **A shared rate-limit counter**, once there is more than one API replica —
  per-process counters do not limit anything when there are four processes.

Turn it on when one of those is being built, not before.

---

## AI providers

Mock is the default and needs no key. It is deterministic, so an analysis
produces the same narrative every time — which is what makes the test suite
possible and what makes a demo reproducible.

To use a real model:

```bash
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
# or
AI_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

Before enabling one on anything public:

- **Costs are per request and attributable to nobody.** An open `/analyze`
  endpoint with a real key is an open invoice. Rate limits and authentication
  come first.
- **Keys come from the environment or a secret manager**, never from a file in
  the image. `.dockerignore` excludes `.env`, and there is a test asserting no
  credential is in the build context.
- **The failure path is already safe.** A provider outage degrades to the
  deterministic result with the error reported in the narrative's own field. No
  analysis fails because an AI call did.

Every response records the provider, the model, the prompt version, the token
counts and an estimated cost, so usage is visible before it is a bill.

---

## Configuration reference

Everything is read through `app/core/config.py`; nothing else in the codebase
touches `os.environ`. See [`.env.example`](../.env.example) for the annotated
list. The ones that change between deployments:

| Variable | Default | Notes |
| --- | --- | --- |
| `ENVIRONMENT` | `local` | `local` / `test` / `staging` / `production` |
| `DEBUG` | `true` | Turn off outside development |
| `LOG_LEVEL` | `INFO` | |
| `LOG_JSON` | `false` | `true` for a log aggregator |
| `DATABASE_URL` | SQLite file | Any SQLAlchemy URL |
| `CORS_ORIGINS` | localhost:3000, :8501 | Comma separated. Never `*` in production |
| `MAX_UPLOAD_BYTES` | 25 MB | Enforced while reading, not after |
| `MAX_ROWS_PER_UPLOAD` | 200,000 | |
| `AI_PROVIDER` | `mock` | `mock` / `anthropic` / `openai` |
| `AI_TIMEOUT_SECONDS` | 30 | |
| `AI_MAX_RETRIES` | 2 | |
| `API_BASE_URL` | 127.0.0.1:8000 | Where the Streamlit UI looks for the API |

### CORS, specifically

`CORS_ORIGINS=*` disables credentials automatically — that pairing is rejected
by browsers, and the dangerous version is a framework that reflects the caller's
origin instead of sending `*`, which lets any site read a signed-in user's data.
Name your front end's origins. There is a test for both behaviours.

---

## A deployment checklist

Before anything is reachable by someone who is not you:

- [ ] Authentication implemented (`API_AUTHENTICATION_PLAN.md`)
- [ ] Every query scoped to the caller's organisation, with a cross-tenant test
- [ ] `CORS_ORIGINS` naming the real origins
- [ ] `DEBUG=false`, `LOG_JSON=true`, `ENVIRONMENT` set
- [ ] PostgreSQL, with `alembic upgrade head` in the release step
- [ ] Uploads and exports on persistent or object storage
- [ ] TLS at the proxy; HSTS
- [ ] Rate limits on `/analyze`, `/validate`, `/forecast`, `/generate`, `/chat`
- [ ] Upload quotas per organisation
- [ ] `python scripts/check_quality.py` green (lint, secrets, dependencies, tests)
- [ ] Backups of the database *and* the uploads, restored once to prove it
- [ ] Error tracking and metrics wired to `X-Request-ID`
- [ ] The disclaimer visible on every page that shows a result

The last one is not a formality. Nothing here has been validated in a live SAP
environment, no data is real, and every savings figure is a model. A deployment
that drops the labels is making claims the software does not support.
