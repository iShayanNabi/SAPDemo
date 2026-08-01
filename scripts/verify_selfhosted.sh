#!/usr/bin/env bash
#
# Verify the SAPDemo self-hosted deployment.
#
#   ./scripts/verify_selfhosted.sh
#
# Read-only. It changes nothing, so it is safe to run against the published
# deployment and safe to schedule.
#
# It checks the things that are wrong silently: a database port that got
# published, a demo mode that is off, an upload path that still accepts files,
# an AI provider that is not the mock, a secret in a log. Every one of those
# looks completely normal from the outside.
#
# Exit codes:
#   0  every check passed
#   1  at least one check failed

. "$(cd "$(dirname "$0")" && pwd)/lib/selfhosted.sh"

PASS=0
FAILED=0
SKIPPED=0

check() {
    local label="$1"; shift
    if "$@" >/dev/null 2>&1; then
        ok "${label}"
        PASS=$((PASS + 1))
    else
        fail "${label}"
        FAILED=$((FAILED + 1))
    fi
}

check_out() {
    # Like check(), but the command prints the reason it failed.
    local label="$1"; shift
    local output
    if output="$("$@" 2>&1)"; then
        ok "${label}"
        PASS=$((PASS + 1))
    else
        fail "${label}"
        [ -n "${output}" ] && printf '        %s\n' "${output}" >&2
        FAILED=$((FAILED + 1))
    fi
}

skip() {
    warn "SKIPPED: $1"
    SKIPPED=$((SKIPPED + 1))
}

info "SAPDemo - verifying the self-hosted deployment"
require_docker
require_files

# ---------------------------------------------------------------------------
info "1. Compose file and environment"
# ---------------------------------------------------------------------------
check_out "docker-compose.selfhosted.yml is valid" compose config -q
check_out "Required settings are present" validate_env

# ---------------------------------------------------------------------------
info "2. Services"
# ---------------------------------------------------------------------------
for service in database api streamlit website; do
    health="$(service_health "${service}")"
    if [ "${health}" = "healthy" ]; then
        ok "${service} is healthy"
        PASS=$((PASS + 1))
    else
        fail "${service} is '${health}', expected 'healthy'"
        FAILED=$((FAILED + 1))
    fi
done

tunnel_token="$(env_value CLOUDFLARE_TUNNEL_TOKEN)"
if [ -z "${tunnel_token}" ]; then
    skip "cloudflared - no tunnel token configured yet, so nothing is published (expected before the tunnel exists)"
else
    check "cloudflared is running" bash -c '[ "$(service_state cloudflared)" = "running" ]'
fi

# ---------------------------------------------------------------------------
info "3. Network boundaries"
# ---------------------------------------------------------------------------
ports="$(compose ps --format '{{.Service}} {{.Ports}}' 2>/dev/null || true)"

# Whether the local debug overlay is loaded. It binds ports to loopback and, to
# make that possible at all, attaches the API to the edge network - so two of
# the boundary checks below describe the deployed file rather than what is
# running right now. Reporting them as failures here would train everybody to
# ignore this script's output.
DEBUG_OVERLAY=0
if printf '%s' "${ports}" | grep -E '^api' | grep -q '127.0.0.1'; then
    DEBUG_OVERLAY=1
fi

if printf '%s' "${ports}" | grep -qE '^(database).*->'; then
    fail "The database is publishing a port to the host. It must never."
    FAILED=$((FAILED + 1))
else
    ok "The database publishes no port"
    PASS=$((PASS + 1))
fi

if printf '%s' "${ports}" | grep -qE '0\.0\.0\.0:|\[::\]:'; then
    fail "A service is published on all interfaces:"
    printf '%s\n' "${ports}" | grep -E '0\.0\.0\.0:|\[::\]:' >&2
    FAILED=$((FAILED + 1))
else
    ok "No service is published on 0.0.0.0"
    PASS=$((PASS + 1))
fi

# The API must not be published in the deployed configuration. With the debug
# overlay it is bound to loopback deliberately, so that is reported rather than
# failed.
if printf '%s' "${ports}" | grep -qE '^api.*->'; then
    if [ "${DEBUG_OVERLAY}" -eq 1 ]; then
        warn "The API is bound to 127.0.0.1 - the debug overlay is loaded. Do not run the published deployment this way."
        SKIPPED=$((SKIPPED + 1))
    else
        fail "The API is published beyond loopback."
        FAILED=$((FAILED + 1))
    fi
else
    ok "The API publishes no port"
    PASS=$((PASS + 1))
fi

# The website must not be able to reach the API: it is not on that network.
if [ "${DEBUG_OVERLAY}" -eq 1 ]; then
    skip "website-cannot-reach-API - the debug overlay puts the API on the edge network so its port can be published. This check only means something without the overlay."
elif compose exec -T website node -e "fetch('http://api:8000/api/v1/health').then(()=>process.exit(0)).catch(()=>process.exit(1))" >/dev/null 2>&1; then
    fail "The website container can reach the API. It should be on the edge network only."
    FAILED=$((FAILED + 1))
else
    ok "The website cannot reach the API (correct: it never calls it)"
    PASS=$((PASS + 1))
fi

# Streamlit must be able to reach the API, by service name, privately.
check "Streamlit reaches the API over the private network" \
    compose exec -T streamlit curl -fsS http://api:8000/api/v1/health

# ---------------------------------------------------------------------------
info "4. Demonstration mode"
# ---------------------------------------------------------------------------
status_json="$(compose exec -T streamlit curl -fsS http://api:8000/api/v1/demo/status 2>/dev/null || true)"

if printf '%s' "${status_json}" | grep -q '"demo_mode":true'; then
    ok "Demo mode is ON"
    PASS=$((PASS + 1))
else
    fail "The API does not report demo mode. Uploads would be accepted from anyone."
    FAILED=$((FAILED + 1))
fi

if printf '%s' "${status_json}" | grep -q '"uploads_enabled":false'; then
    ok "Uploads are disabled"
    PASS=$((PASS + 1))
else
    fail "Uploads are enabled on a deployment intended to be public."
    FAILED=$((FAILED + 1))
fi

if printf '%s' "${status_json}" | grep -q '"ai_is_mock":true'; then
    ok "The AI provider is the local mock (no key, no egress, no cost)"
    PASS=$((PASS + 1))
else
    fail "The AI provider is not the mock."
    FAILED=$((FAILED + 1))
fi

# Hiding the widget is not the control. Prove the API refuses an actual upload.
upload_code="$(compose exec -T streamlit sh -c \
    'printf "a,b\n1,2\n" > /tmp/probe.csv; curl -s -o /dev/null -w "%{http_code}" -F "file=@/tmp/probe.csv" http://api:8000/api/v1/po-risk/upload; rm -f /tmp/probe.csv' 2>/dev/null || true)"
if [ "${upload_code}" = "403" ]; then
    ok "A real upload request is refused server-side (HTTP 403)"
    PASS=$((PASS + 1))
else
    fail "An upload returned HTTP ${upload_code:-?}, expected 403."
    FAILED=$((FAILED + 1))
fi

# ---------------------------------------------------------------------------
info "5. Demonstration data"
# ---------------------------------------------------------------------------
modules_json="$(compose exec -T streamlit curl -fsS http://api:8000/api/v1/demo/modules 2>/dev/null || true)"
module_count="$(printf '%s' "${modules_json}" | grep -o '"module":' | wc -l | tr -d ' ')"
if [ "${module_count}" = "10" ]; then
    ok "All ten guided demonstrations are described"
    PASS=$((PASS + 1))
else
    fail "The API describes ${module_count} demonstrations, expected 10."
    FAILED=$((FAILED + 1))
fi

db_name="$(env_value POSTGRES_DB)"
db_user="$(env_value POSTGRES_USER)"
row_total="$(compose exec -T database psql -U "${db_user}" -d "${db_name}" -tAc \
    "SELECT COALESCE(sum(n_live_tup), 0) FROM pg_stat_user_tables" 2>/dev/null | tr -d '[:space:]')"
if [ "${row_total:-0}" -gt 0 ]; then
    ok "The demonstration database holds data (~${row_total} rows)"
    PASS=$((PASS + 1))
else
    fail "The demonstration database is empty. Seeding may have failed - check the api logs."
    FAILED=$((FAILED + 1))
fi

# ---------------------------------------------------------------------------
info "6. Secrets"
# ---------------------------------------------------------------------------
# The token and the password must not appear in any container's log. This
# checks for the actual values, which is the only check that means anything.
leaked=0
password="$(env_value POSTGRES_PASSWORD)"
recent_logs="$(compose logs --tail 500 2>/dev/null || true)"

if [ -n "${password}" ] && printf '%s' "${recent_logs}" | grep -qF "${password}"; then
    fail "The database password appears in a container log."
    leaked=1
fi
if [ -n "${tunnel_token}" ] && printf '%s' "${recent_logs}" | grep -qF "${tunnel_token}"; then
    fail "The tunnel token appears in a container log."
    leaked=1
fi
if [ "${leaked}" -eq 0 ]; then
    ok "No configured secret appears in the last 500 log lines"
    PASS=$((PASS + 1))
else
    FAILED=$((FAILED + 1))
fi

# An error must not carry a path, a stack trace or a database URL.
error_body="$(compose exec -T streamlit curl -fsS -o - http://api:8000/api/v1/po-risk/analyses/does-not-exist 2>/dev/null || \
              compose exec -T streamlit curl -s http://api:8000/api/v1/po-risk/analyses/does-not-exist 2>/dev/null || true)"
if printf '%s' "${error_body}" | grep -qiE 'traceback|/app/|postgresql://|/Users/'; then
    fail "An API error response leaks internal detail."
    FAILED=$((FAILED + 1))
else
    ok "API errors carry no path, trace or connection string"
    PASS=$((PASS + 1))
fi

# ---------------------------------------------------------------------------
info "7. Persistence"
# ---------------------------------------------------------------------------
if docker volume inspect sapdemo-postgres >/dev/null 2>&1; then
    ok "The database volume exists (data survives a container restart)"
    PASS=$((PASS + 1))
else
    fail "The named volume sapdemo-postgres does not exist. Data is not persistent."
    FAILED=$((FAILED + 1))
fi

# ---------------------------------------------------------------------------
printf '\n'
printf '  %d passed, %d failed, %d skipped\n' "${PASS}" "${FAILED}" "${SKIPPED}"
if [ "${FAILED}" -eq 0 ]; then
    ok "Verification passed."
    exit 0
fi
fail "Verification FAILED. Do not publish until these are resolved."
exit 1
