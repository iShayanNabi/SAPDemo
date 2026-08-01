#!/usr/bin/env bash
#
# Shared helpers for the self-hosted scripts.
#
# Sourced, never executed. Every script in scripts/*_selfhosted.sh and
# scripts/reset_public_demo.sh starts by sourcing this file, so the environment
# validation, the compose invocation and the "never print a secret" rule are
# written once.
#
#   . "$(dirname "$0")/lib/selfhosted.sh"
#
# Deliberately bash rather than sh: `set -o pipefail` and arrays are both used
# below, and macOS ships bash 3.2 which supports both.

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SELFHOSTED_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SELFHOSTED_LIB_DIR}/../.." && pwd)"
readonly SELFHOSTED_LIB_DIR PROJECT_ROOT

COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.selfhosted.yml"
DEBUG_COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.debug.yml"
ENV_FILE="${SAPDEMO_ENV_FILE:-${PROJECT_ROOT}/.env.selfhosted}"
readonly COMPOSE_FILE DEBUG_COMPOSE_FILE ENV_FILE

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
# Colour only when writing to a terminal, so a redirected log is not full of
# escape sequences.
if [ -t 1 ]; then
    C_RED=$'\033[0;31m'; C_GREEN=$'\033[0;32m'; C_YELLOW=$'\033[0;33m'
    C_BLUE=$'\033[0;34m'; C_RESET=$'\033[0m'
else
    C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_RESET=''
fi
readonly C_RED C_GREEN C_YELLOW C_BLUE C_RESET

info()  { printf '%s\n' "${C_BLUE}==>${C_RESET} $*"; }
ok()    { printf '%s\n' "${C_GREEN}  ok${C_RESET} $*"; }
warn()  { printf '%s\n' "${C_YELLOW}  !!${C_RESET} $*" >&2; }
fail()  { printf '%s\n' "${C_RED}  FAIL${C_RESET} $*" >&2; }

die() {
    fail "$1"
    exit "${2:-1}"
}

# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------
# Anything a script echoes back from the environment goes through this. It is
# not a substitute for not printing secrets - it is the second line, for the
# case where somebody adds a helpful "here is your configuration" block later.
redact() {
    local value="${1:-}"
    if [ -z "${value}" ]; then
        printf '(not set)'
    else
        printf '(set, %d characters)' "${#value}"
    fi
}

# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------
require_docker() {
    command -v docker >/dev/null 2>&1 \
        || die "Docker is not installed, or not on PATH. Install Docker Desktop."

    docker compose version >/dev/null 2>&1 \
        || die "The 'docker compose' plugin is unavailable. Update Docker Desktop."

    # `docker info` fails when the daemon is not running, which on macOS means
    # Docker Desktop has not been started. That is the single most common
    # reason these scripts fail after a reboot, so it gets its own message.
    docker info >/dev/null 2>&1 \
        || die "Docker is installed but not running. Start Docker Desktop and wait for the whale icon to stop animating, then retry."
}

require_files() {
    [ -f "${COMPOSE_FILE}" ] \
        || die "docker-compose.selfhosted.yml is missing from ${PROJECT_ROOT}."
    [ -f "${ENV_FILE}" ] \
        || die "${ENV_FILE} does not exist. Copy .env.selfhosted.example to .env.selfhosted and fill it in."
}

# Read one value out of the environment file without sourcing it.
#
# Sourcing an env file executes it. A stray backtick or $(...) in a password
# would run as a command, and the file most likely to contain an awkward
# character is precisely the one holding a generated password.
env_value() {
    local key="$1"
    [ -f "${ENV_FILE}" ] || return 0
    sed -n "s/^[[:space:]]*${key}=//p" "${ENV_FILE}" \
        | tail -n 1 \
        | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

#: Variables without which the stack cannot start correctly.
REQUIRED_ENV_KEYS=(
    POSTGRES_DB
    POSTGRES_USER
    POSTGRES_PASSWORD
    DATABASE_URL
)

validate_env() {
    require_files

    local missing=() key value
    for key in "${REQUIRED_ENV_KEYS[@]}"; do
        value="$(env_value "${key}")"
        if [ -z "${value}" ]; then
            missing+=("${key}")
        fi
    done

    if [ "${#missing[@]}" -gt 0 ]; then
        fail "These required settings are missing or empty in ${ENV_FILE}:"
        printf '        %s\n' "${missing[@]}" >&2
        return 1
    fi

    # A placeholder password is worse than a missing one: the stack starts, and
    # the credential is one that is published in this repository.
    local password
    password="$(env_value POSTGRES_PASSWORD)"
    case "${password}" in
        *replace-me*|password|postgres|changeme|sapdemo)
            fail "POSTGRES_PASSWORD is still the example placeholder."
            printf '        Generate one:  python3 -c "import secrets; print(secrets.token_urlsafe(32))"\n' >&2
            printf '        Then update it in both POSTGRES_PASSWORD and DATABASE_URL.\n' >&2
            return 1
            ;;
    esac

    # The password appears twice - once for PostgreSQL, once inside the URL the
    # API connects with. They drift the first time somebody rotates one of them,
    # and the symptom is an API that cannot authenticate against a database that
    # started perfectly.
    local url
    url="$(env_value DATABASE_URL)"
    case "${url}" in
        *"${password}"*) ;;
        *)
            fail "DATABASE_URL does not contain POSTGRES_PASSWORD."
            printf '        The two must match, or the API cannot authenticate.\n' >&2
            return 1
            ;;
    esac
    case "${url}" in
        *@database:*) ;;
        *)
            warn "DATABASE_URL does not point at the 'database' service hostname."
            warn "Inside the stack the database is reachable as 'database', not localhost."
            ;;
    esac

    return 0
}

# ---------------------------------------------------------------------------
# Compose
# ---------------------------------------------------------------------------
# SAPDEMO_DEBUG=1 loads the debug overlay, which binds ports to 127.0.0.1.
compose() {
    local -a args=(--env-file "${ENV_FILE}" -f "${COMPOSE_FILE}")
    if [ "${SAPDEMO_DEBUG:-0}" = "1" ]; then
        args+=(-f "${DEBUG_COMPOSE_FILE}")
    fi
    ( cd "${PROJECT_ROOT}" && docker compose "${args[@]}" "$@" )
}

#: The services this stack defines, in dependency order.
SERVICES=(database api streamlit website cloudflared)

service_state() {
    compose ps --format '{{.Service}} {{.State}}' 2>/dev/null \
        | awk -v svc="$1" '$1 == svc { print $2 }' \
        | head -n 1
}

service_health() {
    local container
    container="$(compose ps -q "$1" 2>/dev/null | head -n 1)"
    [ -n "${container}" ] || { printf 'absent'; return 0; }
    docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "${container}" 2>/dev/null || printf 'unknown'
}

# Wait until a service reports healthy, or give up with a useful message.
wait_for_health() {
    local service="$1" timeout="${2:-300}" waited=0 status
    info "Waiting for '${service}' to become healthy (up to ${timeout}s)..."
    while [ "${waited}" -lt "${timeout}" ]; do
        status="$(service_health "${service}")"
        case "${status}" in
            healthy)
                ok "${service} is healthy."
                return 0
                ;;
            unhealthy)
                fail "${service} reported unhealthy."
                printf '        Logs:  ./scripts/logs_selfhosted.sh %s\n' "${service}" >&2
                return 1
                ;;
        esac
        sleep 5
        waited=$((waited + 5))
    done
    fail "${service} did not become healthy within ${timeout}s (last state: ${status:-unknown})."
    printf '        Logs:  ./scripts/logs_selfhosted.sh %s\n' "${service}" >&2
    return 1
}

# Whether demo mode is on, read from the environment file.
demo_mode_enabled() {
    [ "$(env_value DEMO_MODE)" = "true" ]
}

confirm() {
    local prompt="$1" expected="${2:-yes}" answer
    if [ ! -t 0 ]; then
        fail "This needs an interactive confirmation and stdin is not a terminal."
        return 1
    fi
    printf '%s\n' "${C_YELLOW}${prompt}${C_RESET}"
    printf 'Type %s to continue: ' "${expected}"
    read -r answer
    [ "${answer}" = "${expected}" ]
}
