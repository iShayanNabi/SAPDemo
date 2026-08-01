# SAP AI Application Lab - production-quality image.
#
# Docker is OPTIONAL. Everything in this project runs with a plain virtualenv:
#
#     python3.12 -m venv .venv && source .venv/bin/activate
#     pip install -r requirements.txt
#     uvicorn app.main:app --reload
#
# The image exists for deployment and for reproducing the runtime elsewhere.
# It builds one image that can run either process:
#
#     docker build -t sap-ai-lab .
#     docker run -p 8000:8000 sap-ai-lab                      # FastAPI (default)
#     docker run -p 8501:8501 sap-ai-lab lab-streamlit         # Streamlit UI
#
# Two stages: the first compiles wheels (pandas/numpy/scikit-learn need build
# tooling on some platforms), the second copies only the installed packages so
# no compiler ends up in the runtime image.

# ---------------------------------------------------------------------------
# Stage 1 - build the dependency tree
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Dependencies are installed into their own prefix so stage 2 can copy exactly
# the site-packages tree and nothing else.
COPY requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2 - runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="SAP AI Application Lab" \
      org.opencontainers.image.description="Local workbench of ten SAP-focused AI applications. Demo data only; not connected to any SAP system." \
      org.opencontainers.image.licenses="Proprietary"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    APP_HOME=/app

# curl is used by the container HEALTHCHECK below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR ${APP_HOME}

# Application code. The .dockerignore keeps local uploads, exports, the SQLite
# file and any .env out of the build context, so no secret can be baked in.
COPY app ./app
COPY streamlit_app ./streamlit_app
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini pyproject.toml README.md ./
COPY data/sample ./data/sample

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Run as a non-root user. The writable runtime directories are created and
# handed over before the drop, so a mounted empty volume still works.
RUN groupadd --system --gid 1001 lab \
    && useradd --system --uid 1001 --gid lab --home ${APP_HOME} lab \
    && mkdir -p ${APP_HOME}/data/uploads ${APP_HOME}/data/exports \
    && chown -R lab:lab ${APP_HOME}

USER lab

EXPOSE 8000 8501

# The health endpoint reports the database and the resolved AI provider, so a
# container that is up but cannot reach its database is reported unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["lab-api"]
