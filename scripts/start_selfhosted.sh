#!/usr/bin/env bash
#
# Start the SAPDemo self-hosted stack.
#
#   ./scripts/start_selfhosted.sh              # the published configuration
#   ./scripts/start_selfhosted.sh --debug      # + ports bound to 127.0.0.1
#   ./scripts/start_selfhosted.sh --build      # rebuild the images first
#
# Safe to run repeatedly: `compose up -d` reconciles to the desired state
# rather than starting a second copy of anything.

. "$(cd "$(dirname "$0")" && pwd)/lib/selfhosted.sh"

BUILD=0
for arg in "$@"; do
    case "${arg}" in
        --debug) export SAPDEMO_DEBUG=1 ;;
        --build) BUILD=1 ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) die "Unknown option: ${arg}. Try --help." 2 ;;
    esac
done

info "SAPDemo - starting the self-hosted stack"
require_docker
ok "Docker is running."

validate_env || die "Fix ${ENV_FILE} and try again." 2
ok "Environment file validated (no values printed)."

if demo_mode_enabled; then
    ok "Public demonstration mode is ON: uploads refused, mock AI, bundled data."
else
    warn "DEMO_MODE is not 'true'. This stack is intended to be published;"
    warn "without demo mode it will accept uploads from anyone who can reach it."
fi

if [ -z "$(env_value CLOUDFLARE_TUNNEL_TOKEN)" ]; then
    warn "CLOUDFLARE_TUNNEL_TOKEN is empty. The stack will start and everything"
    warn "is reachable locally with --debug, but nothing will be published and"
    warn "the cloudflared container will restart in a loop. That is expected"
    warn "until the tunnel has been created - see docs/CLOUDFLARE_TUNNEL_SETUP.md."
fi

if [ "${BUILD}" -eq 1 ]; then
    info "Building images (this takes a while on a quad-core i5)..."
    compose build || die "The build failed. The stack was not started."
    ok "Images built."
fi

info "Starting services..."
compose up -d --remove-orphans || die "docker compose up failed."

# The first start of a fresh volume runs migrations and then seeds ten modules.
# 600s is generous on purpose: a timeout here that is too short reports a
# failure for a stack that was merely still working.
wait_for_health database 120 || exit 1
wait_for_health api 600 || exit 1
wait_for_health streamlit 180 || exit 1
wait_for_health website 120 || exit 1

info "Stack is up."
printf '\n'
if [ "${SAPDEMO_DEBUG:-0}" = "1" ]; then
    website_port="$(env_value DEBUG_WEBSITE_PORT)"
    streamlit_port="$(env_value DEBUG_STREAMLIT_PORT)"
    api_port="$(env_value DEBUG_API_PORT)"
    printf '  Website    http://127.0.0.1:%s\n' "${website_port:-3000}"
    printf '  Demo UI    http://127.0.0.1:%s\n' "${streamlit_port:-8501}"
    printf '  API docs   http://127.0.0.1:%s/docs\n' "${api_port:-8000}"
    printf '\n'
    printf '  These bind to loopback only. Nothing is published to the network.\n'
else
    printf '  No ports are published. Reach the services through the tunnel, or\n'
    printf '  restart with --debug to bind them to 127.0.0.1 for local testing.\n'
fi
printf '\n'
printf '  Status     ./scripts/status_selfhosted.sh\n'
printf '  Logs       ./scripts/logs_selfhosted.sh\n'
printf '  Verify     ./scripts/verify_selfhosted.sh\n'
