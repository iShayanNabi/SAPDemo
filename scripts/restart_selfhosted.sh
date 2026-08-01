#!/usr/bin/env bash
#
# Restart the SAPDemo self-hosted stack.
#
#   ./scripts/restart_selfhosted.sh                  # restart every service
#   ./scripts/restart_selfhosted.sh api streamlit    # restart named services
#   ./scripts/restart_selfhosted.sh --debug          # restart with the debug overlay
#
# A restart does not reseed and does not reset. DEMO_SEED_ON_EMPTY only acts on
# an empty database, and DEMO_RESET_ON_START defaults to false - so data
# survives this, which is the whole point of it defaulting that way.

. "$(cd "$(dirname "$0")" && pwd)/lib/selfhosted.sh"

TARGETS=()
for arg in "$@"; do
    case "${arg}" in
        --debug) export SAPDEMO_DEBUG=1 ;;
        -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) die "Unknown option: ${arg}. Try --help." 2 ;;
        *) TARGETS+=("${arg}") ;;
    esac
done

info "SAPDemo - restarting"
require_docker
validate_env || die "Fix ${ENV_FILE} and try again." 2

if [ "$(env_value DEMO_RESET_ON_START)" = "true" ]; then
    warn "DEMO_RESET_ON_START=true - this restart WILL wipe the demonstration"
    warn "database. If that is not what you want, set it to false first."
fi

if [ "${#TARGETS[@]}" -gt 0 ]; then
    info "Restarting: ${TARGETS[*]}"
    compose restart "${TARGETS[@]}" || die "Restart failed."
else
    info "Restarting every service..."
    compose restart || die "Restart failed."
fi

wait_for_health database 120 || exit 1
wait_for_health api 600 || exit 1
ok "Stack restarted. Run ./scripts/verify_selfhosted.sh to confirm."
