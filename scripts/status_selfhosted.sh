#!/usr/bin/env bash
#
# Report the state of the SAPDemo self-hosted stack.
#
#   ./scripts/status_selfhosted.sh
#
# Read-only. It starts nothing, stops nothing and changes nothing, so it is
# safe to run at any time and safe to put on a schedule.
#
# Exit codes:
#   0  every service that should be running is running and healthy
#   1  something is wrong (the output says what)

. "$(cd "$(dirname "$0")" && pwd)/lib/selfhosted.sh"

require_docker
require_files

info "SAPDemo - self-hosted status"
printf '\n'

problems=0
tunnel_token="$(env_value CLOUDFLARE_TUNNEL_TOKEN)"

printf '  %-14s %-12s %s\n' "SERVICE" "STATE" "HEALTH"
printf '  %-14s %-12s %s\n' "-------" "-----" "------"
for service in "${SERVICES[@]}"; do
    state="$(service_state "${service}")"
    health="$(service_health "${service}")"
    printf '  %-14s %-12s %s\n' "${service}" "${state:-absent}" "${health}"

    case "${service}:${health}" in
        cloudflared:*)
            # Without a token cloudflared cannot authenticate and restarts in a
            # loop. That is the expected state before the tunnel exists, and
            # reporting it as a fault would train everybody to ignore this
            # script.
            if [ -z "${tunnel_token}" ]; then
                continue
            fi
            ;;
    esac

    case "${health}" in
        healthy|running) ;;
        *) problems=$((problems + 1)) ;;
    esac
done

printf '\n'
info "Configuration"
printf '  Demo mode          %s\n' "$(env_value DEMO_MODE)"
printf '  Uploads allowed    %s\n' "$(env_value DEMO_ALLOW_UPLOADS)"
printf '  Seed on empty      %s\n' "$(env_value DEMO_SEED_ON_EMPTY)"
printf '  Reset on start     %s\n' "$(env_value DEMO_RESET_ON_START)"
# Never the value. Length only, so "is it set" is answerable without the token
# reaching a terminal, a scrollback buffer or a screenshot.
printf '  Tunnel token       %s\n' "$(redact "${tunnel_token}")"

printf '\n'
info "Published ports"
published="$(compose ps --format '{{.Service}} {{.Ports}}' 2>/dev/null | grep -v '^\s*$' || true)"
if printf '%s' "${published}" | grep -qE '0\.0\.0\.0|\[::\]'; then
    fail "A service is published on all interfaces:"
    printf '%s\n' "${published}" | grep -E '0\.0\.0\.0|\[::\]' >&2
    problems=$((problems + 1))
else
    ok "Nothing is published on 0.0.0.0."
fi
if printf '%s' "${published}" | grep -qE '(database|postgres).*->'; then
    fail "The database is publishing a port. It must not."
    problems=$((problems + 1))
else
    ok "The database publishes no port."
fi

printf '\n'
info "Disk"
docker system df 2>/dev/null | sed 's/^/  /' || warn "docker system df was unavailable."

printf '\n'
if [ "${problems}" -eq 0 ]; then
    ok "No problems detected."
    exit 0
fi
fail "${problems} problem(s) detected. Logs: ./scripts/logs_selfhosted.sh"
exit 1
