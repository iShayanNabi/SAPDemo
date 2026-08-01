#!/usr/bin/env bash
#
# Stop the SAPDemo self-hosted stack.
#
#   ./scripts/stop_selfhosted.sh              # stop and remove the containers
#   ./scripts/stop_selfhosted.sh --keep       # stop, leave the containers
#
# The database volume is never touched. There is deliberately no flag on this
# script that removes it: `docker compose down -v` is one character away from
# `down` and destroys the database, so removing data is the job of a script
# whose name says so.

. "$(cd "$(dirname "$0")" && pwd)/lib/selfhosted.sh"

KEEP=0
for arg in "$@"; do
    case "${arg}" in
        --keep) KEEP=1 ;;
        -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Unknown option: ${arg}. Try --help." 2 ;;
    esac
done

info "SAPDemo - stopping the self-hosted stack"
require_docker
require_files

if [ "${KEEP}" -eq 1 ]; then
    compose stop || die "docker compose stop failed."
    ok "Containers stopped. Start them again with ./scripts/start_selfhosted.sh"
else
    # No -v. The named volumes - and the database in them - survive.
    compose down --remove-orphans || die "docker compose down failed."
    ok "Containers removed. The database volume was not touched."
fi

printf '\n  Data is preserved. To remove it you must say so explicitly:\n'
printf '    docker volume rm sapdemo-postgres      (destroys the database)\n'
