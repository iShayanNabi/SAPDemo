#!/usr/bin/env bash
#
# Reset the public demonstration to its bundled fictional data.
#
#   ./scripts/reset_public_demo.sh              # asks for confirmation
#   ./scripts/reset_public_demo.sh --yes        # for a scheduled run
#
# What it does, and only this:
#
#   1. drops the application tables in the demonstration database,
#   2. re-applies the Alembic migrations,
#   3. reloads the bundled fictional demonstration records,
#   4. clears the transient upload and export directories.
#
# What it will never do, whatever flags it is given: delete source files,
# migrations, configuration, secrets, backups, or the contents of data/sample/.
# Those are inputs and history, not state.
#
# It refuses to run unless DEMO_MODE=true. That refusal is the whole safety
# model: a database that is not a public demonstration is somebody's data, and
# this script cannot tell the difference by looking at it.
#
# Exit codes:
#   0  reset completed
#   1  a step failed
#   2  refused (not demo mode, bad environment, no confirmation)
#
# Idempotent: running it twice leaves the same state as running it once.
# Suitable for a scheduled run with --yes; see docs/PUBLIC_DEMO_DEPLOYMENT.md.

. "$(cd "$(dirname "$0")" && pwd)/lib/selfhosted.sh"

ASSUME_YES=0
for arg in "$@"; do
    case "${arg}" in
        --yes|-y) ASSUME_YES=1 ;;
        -h|--help) sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Unknown option: ${arg}. Try --help." 2 ;;
    esac
done

info "SAPDemo - resetting the public demonstration"

require_docker
validate_env || die "Fix ${ENV_FILE} and try again." 2

# ---------------------------------------------------------------------------
# Refuse unless this is a demonstration
# ---------------------------------------------------------------------------
if ! demo_mode_enabled; then
    fail "Refusing to reset: DEMO_MODE is not 'true' in ${ENV_FILE}."
    printf '        This script only ever runs against a public demonstration.\n' >&2
    printf '        A database that is not one holds data this script cannot\n' >&2
    printf '        distinguish from demonstration records, so it will not try.\n' >&2
    exit 2
fi
ok "DEMO_MODE=true."

# ---------------------------------------------------------------------------
# Identify the target, out loud, before destroying anything
# ---------------------------------------------------------------------------
db_name="$(env_value POSTGRES_DB)"
db_user="$(env_value POSTGRES_USER)"
[ -n "${db_name}" ] || die "POSTGRES_DB is empty. Refusing to operate on an unidentified database." 2

if [ "$(service_state database)" != "running" ]; then
    fail "The database service is not running. Start the stack first:"
    printf '        ./scripts/start_selfhosted.sh\n' >&2
    exit 2
fi

# Confirm the database really is the one named, rather than trusting the file.
actual="$(compose exec -T database psql -U "${db_user}" -d "${db_name}" -tAc 'SELECT current_database()' 2>/dev/null | tr -d '[:space:]')"
[ "${actual}" = "${db_name}" ] \
    || die "Expected to be connected to '${db_name}' but the server reports '${actual:-nothing}'. Refusing to continue." 2
ok "Connected to the expected database: ${db_name}"

printf '\n'
printf '  Target      %s (in the sapdemo-postgres volume)\n' "${db_name}"
printf '  Removes     application tables, then re-migrates and reseeds\n'
printf '  Removes     the transient upload and export directories\n'
printf '  Keeps       migrations, configuration, secrets, backups, data/sample/\n'
printf '\n'

if [ "${ASSUME_YES}" -ne 1 ]; then
    confirm "This deletes every record in the demonstration database." "reset" \
        || { info "Nothing was changed."; exit 2; }
fi

# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------
# reset_demo.py drops the tables the models declare plus alembic_version, then
# re-runs the migrations. --force because the container's ENVIRONMENT is not
# "local"; the script refuses a non-local environment without it, which is the
# right default for a person running it by hand.
info "Dropping tables and re-applying migrations..."
compose exec -T api python scripts/reset_demo.py --yes --force \
    || die "The reset failed. The database may be empty; re-run this script."
ok "Schema rebuilt at the latest migration."

info "Loading the bundled fictional demonstration data..."
# Not --if-empty: the database was just emptied, and the point of this script is
# that the data is reloaded rather than skipped.
compose exec -T api python scripts/seed_database.py --yes \
    || die "Seeding failed. The schema is present but the demonstration is empty."
ok "Demonstration data loaded."

info "Restarting the demonstration UI so no stale identifier is held in a session..."
compose restart streamlit >/dev/null 2>&1 || warn "Could not restart the UI; do it by hand if pages look stale."

printf '\n'
ok "The public demonstration has been reset."
printf '  Verify:  ./scripts/verify_selfhosted.sh\n'
