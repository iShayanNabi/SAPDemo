#!/usr/bin/env bash
#
# Back up the SAPDemo demonstration database.
#
#   ./scripts/backup_selfhosted.sh                       # to $BACKUP_DIR
#   ./scripts/backup_selfhosted.sh --dir /Volumes/Enc    # to an external drive
#   ./scripts/backup_selfhosted.sh --verify              # + restore it into a
#                                                        #   throwaway database
#
# Uses pg_dump in PostgreSQL's own custom format (-Fc): compressed, and
# restorable selectively by pg_restore. A plain SQL dump is readable but cannot
# be restored table by table, which is exactly what you want on the bad day.
#
# Every backup is written with a SHA-256 checksum beside it. A backup you have
# not checksummed is a backup you have not verified, and a truncated dump looks
# like a file until the day you need it.
#
# Retention: the newest $BACKUP_RETENTION backups are kept and older ones are
# deleted. This script is the only thing in the project that ever deletes a
# backup, and it only deletes ones it made (matching its own name pattern).
#
# **This script does not encrypt.** Point --dir at an encrypted volume - a
# FileVault-protected external disk - if the contents matter. The demonstration
# database holds only fictional data, so the default local directory is
# proportionate; a database holding anything else is not this script's job.

. "$(cd "$(dirname "$0")" && pwd)/lib/selfhosted.sh"

DEST=""
VERIFY=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dir) shift; DEST="${1:-}" ;;
        --verify) VERIFY=1 ;;
        -h|--help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Unknown option: $1. Try --help." 2 ;;
    esac
    shift
done

info "SAPDemo - backing up the demonstration database"
require_docker
validate_env || die "Fix ${ENV_FILE} and try again." 2

db_name="$(env_value POSTGRES_DB)"
db_user="$(env_value POSTGRES_USER)"

[ "$(service_state database)" = "running" ] \
    || die "The database service is not running. Start the stack first." 2

if [ -z "${DEST}" ]; then
    DEST="$(env_value BACKUP_DIR)"
    DEST="${DEST:-${PROJECT_ROOT}/backups}"
fi
case "${DEST}" in
    /*) ;;
    *) DEST="${PROJECT_ROOT}/${DEST#./}" ;;
esac

mkdir -p "${DEST}" || die "Could not create ${DEST}."
[ -w "${DEST}" ] || die "${DEST} is not writable."

# Fail before dumping rather than half way through it.
available_kb="$(df -Pk "${DEST}" | awk 'NR==2 {print $4}')"
if [ "${available_kb:-0}" -lt 262144 ]; then
    die "Less than 256 MB free at ${DEST}. Refusing to start a backup that may not finish."
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
name="sapdemo-${db_name}-${stamp}.dump"
path="${DEST}/${name}"

info "Dumping ${db_name} to ${path}"
# -Fc custom format, --no-owner/--no-privileges so the dump restores into a
# database owned by whoever restores it rather than demanding the original role.
if ! compose exec -T database pg_dump \
        -U "${db_user}" -d "${db_name}" \
        -Fc --no-owner --no-privileges > "${path}"; then
    rm -f "${path}"
    die "pg_dump failed. No backup was written."
fi

# An empty or tiny file means pg_dump wrote an error to stdout, or nothing.
size="$(wc -c < "${path}" | tr -d ' ')"
if [ "${size}" -lt 1024 ]; then
    rm -f "${path}"
    die "The dump is only ${size} bytes. Treating that as a failure rather than a backup."
fi

# The custom format starts with the magic string "PGDMP". Checking it catches a
# dump that is really an error message, which is the failure mode that looks
# most like success.
if ! head -c 5 "${path}" | grep -q 'PGDMP'; then
    rm -f "${path}"
    die "The file does not start with the PostgreSQL dump header. Discarded."
fi

if command -v shasum >/dev/null 2>&1; then
    ( cd "${DEST}" && shasum -a 256 "${name}" > "${name}.sha256" )
elif command -v sha256sum >/dev/null 2>&1; then
    ( cd "${DEST}" && sha256sum "${name}" > "${name}.sha256" )
else
    warn "Neither shasum nor sha256sum is available; no checksum was written."
fi

ok "Backup written: ${path} ($(( size / 1024 )) KB)"
[ -f "${path}.sha256" ] && ok "Checksum:       ${path}.sha256"

# ---------------------------------------------------------------------------
# Verify by restoring, if asked
# ---------------------------------------------------------------------------
if [ "${VERIFY}" -eq 1 ]; then
    info "Verifying by restoring into a throwaway database..."
    if "${PROJECT_ROOT}/scripts/restore_selfhosted.sh" --file "${path}" --into-throwaway --yes; then
        ok "The backup restored cleanly. It is a backup, not just a file."
    else
        fail "The backup did NOT restore. Do not rely on it."
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------
retention="$(env_value BACKUP_RETENTION)"
retention="${retention:-14}"
case "${retention}" in
    ''|*[!0-9]*) warn "BACKUP_RETENTION is not a number; keeping everything."; retention=0 ;;
esac

if [ "${retention}" -gt 0 ]; then
    # Only files this script made. A glob that matched more would eventually
    # delete somebody else's file that happened to be in the directory.
    count="$(find "${DEST}" -maxdepth 1 -name 'sapdemo-*.dump' -type f | wc -l | tr -d ' ')"
    if [ "${count}" -gt "${retention}" ]; then
        info "Retention: keeping the newest ${retention} of ${count} backups."
        # shellcheck disable=SC2012 - names here are generated by this script
        ls -1t "${DEST}"/sapdemo-*.dump | tail -n +"$((retention + 1))" | while read -r old; do
            rm -f "${old}" "${old}.sha256"
            ok "Removed old backup: $(basename "${old}")"
        done
    fi
fi

printf '\n'
printf '  Restore this backup:\n'
printf '    ./scripts/restore_selfhosted.sh --file %s\n' "${path}"
printf '\n'
printf '  A backup that has never been restored is a hypothesis. Test one:\n'
printf '    ./scripts/backup_selfhosted.sh --verify\n'
