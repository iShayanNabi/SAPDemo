#!/usr/bin/env bash
#
# Show logs from the SAPDemo self-hosted stack.
#
#   ./scripts/logs_selfhosted.sh                 # last 200 lines, all services
#   ./scripts/logs_selfhosted.sh api             # one service
#   ./scripts/logs_selfhosted.sh -f api          # follow
#   ./scripts/logs_selfhosted.sh -n 1000         # more history
#
# Logs are rotated by Docker at 10 MB x 5 files per container, configured in
# docker-compose.selfhosted.yml. Without that a chatty container fills the disk
# of a machine nobody is watching.
#
# A note worth reading before pasting output anywhere: the application redacts
# credentials from its own log lines, but cloudflared and PostgreSQL are third
# party and make their own choices. Read what you are about to share.

. "$(cd "$(dirname "$0")" && pwd)/lib/selfhosted.sh"

require_docker
require_files

ARGS=(logs --tail 200)
PASSTHROUGH=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        -f|--follow) ARGS=(logs --tail 200 --follow) ;;
        -n) shift; ARGS=(logs --tail "${1:-200}") ;;
        -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) PASSTHROUGH+=("$1") ;;
    esac
    shift
done

compose "${ARGS[@]}" ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}
