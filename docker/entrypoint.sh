#!/usr/bin/env sh
#
# Container entrypoint for the SAP AI Application Lab.
#
# One image, three commands:
#
#   lab-api        FastAPI on 0.0.0.0:8000 (default)
#   lab-streamlit  Streamlit UI on 0.0.0.0:8501
#   lab-migrate    Run "alembic upgrade head" and exit
#
# Anything else is executed verbatim, so `docker run ... sh` still works.
#
# The API command applies Alembic migrations first when RUN_MIGRATIONS is not
# "false". Migrations are the source of truth for the schema; the application's
# own init_db() only ever creates missing tables, which is fine locally but is
# not a substitute for a migration history.

set -eu

RUN_MIGRATIONS="${RUN_MIGRATIONS:-true}"
API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8000}"
API_WORKERS="${API_WORKERS:-1}"
STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"

apply_migrations() {
    if [ "${RUN_MIGRATIONS}" = "false" ]; then
        echo "[entrypoint] RUN_MIGRATIONS=false - skipping alembic upgrade."
        return 0
    fi
    echo "[entrypoint] Applying database migrations..."
    # A failed migration must stop the container rather than start an API
    # against a half-built schema.
    alembic upgrade head
}

wait_for_database() {
    # Only relevant for a server database; SQLite is a local file.
    case "${DATABASE_URL:-sqlite}" in
        postgresql*|postgres*) ;;
        *) return 0 ;;
    esac
    echo "[entrypoint] Waiting for the database to accept connections..."
    attempt=1
    while [ "${attempt}" -le 30 ]; do
        if python -c "
import sys
from sqlalchemy import create_engine, text
from app.core.config import settings
try:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        connection.execute(text('SELECT 1'))
except Exception:
    sys.exit(1)
" >/dev/null 2>&1; then
            echo "[entrypoint] Database is ready."
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 2
    done
    echo "[entrypoint] Database did not become reachable in time." >&2
    return 1
}

prepare_demo_data() {
    # Demonstration data lifecycle. This lives here rather than in the FastAPI
    # lifespan for two reasons: app/ must not import scripts/, and "does a
    # restart wipe the database" should be answerable by reading one file.
    #
    # Two switches, and the defaults are the safe ones:
    #
    #   DEMO_RESET_ON_START  default false. A restart must never destroy data.
    #   DEMO_SEED_ON_EMPTY   default true.  A fresh volume comes up populated;
    #                        a restart does nothing, because the database is
    #                        no longer empty.
    if [ "${DEMO_MODE:-false}" != "true" ]; then
        return 0
    fi

    if [ "${DEMO_RESET_ON_START:-false}" = "true" ]; then
        echo "[entrypoint] DEMO_RESET_ON_START=true - resetting the demonstration database."
        # --force because the container sets ENVIRONMENT to something other
        # than "local"; the reset script refuses a non-local environment
        # without it, which is the correct default for a human running it.
        python scripts/reset_demo.py --yes --force || return 1
    fi

    if [ "${DEMO_SEED_ON_EMPTY:-true}" = "true" ]; then
        echo "[entrypoint] Seeding the demonstration data if the database is empty..."
        # --if-empty exits 0 when there is already data, so a restart is a
        # no-op rather than a failure or a duplicate set.
        python scripts/seed_database.py --if-empty --yes || {
            # A seeding failure must not stop the API: an empty demonstration
            # is a worse outcome than no demonstration only if nobody is told,
            # and this line tells them.
            echo "[entrypoint] WARNING: seeding did not complete. The API will start with" >&2
            echo "[entrypoint] whatever the database already holds." >&2
        }
    fi
}

case "${1:-lab-api}" in
    lab-api)
        wait_for_database
        apply_migrations
        prepare_demo_data
        echo "[entrypoint] Starting FastAPI on ${API_HOST}:${API_PORT}"
        exec uvicorn app.main:app \
            --host "${API_HOST}" \
            --port "${API_PORT}" \
            --workers "${API_WORKERS}" \
            --proxy-headers
        ;;
    lab-streamlit)
        echo "[entrypoint] Starting Streamlit on 0.0.0.0:${STREAMLIT_PORT}"
        exec streamlit run streamlit_app/Home.py \
            --server.address=0.0.0.0 \
            --server.port="${STREAMLIT_PORT}" \
            --server.headless=true \
            --browser.gatherUsageStats=false
        ;;
    lab-migrate)
        wait_for_database
        exec alembic upgrade head
        ;;
    *)
        exec "$@"
        ;;
esac
