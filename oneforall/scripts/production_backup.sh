#!/usr/bin/env bash
set -Eeuo pipefail

# Production PostgreSQL backup for the host-managed ThemisIQ database.
#
# The script is intentionally independent of Docker and application secrets. It
# runs pg_dump/pg_restore as the local postgres account, restores every new dump
# into a disposable database, and publishes the file only after that restore
# succeeds. Run as root from cron or a hardened systemd oneshot service.

umask 077

readonly BACKUP_DIR="${THEMISIQ_BACKUP_DIR:-/project/backups}"
readonly SOURCE_DB="${THEMISIQ_DATABASE:-themisiq}"
readonly PG_PORT="${THEMISIQ_PG_PORT:-5434}"
readonly PG_RUNNER="/usr/sbin/runuser"
readonly PG_DUMP="/usr/bin/pg_dump"
readonly PG_RESTORE="/usr/bin/pg_restore"
readonly PSQL="/usr/bin/psql"
readonly CREATEDB="/usr/bin/createdb"
readonly DROPDB="/usr/bin/dropdb"

if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: production_backup.sh must run as root" >&2
    exit 1
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
drill_db="themisiq_backup_verify_${stamp,,}"
final_path="${BACKUP_DIR}/themisiq_${stamp}_verified.dump"
partial_path="${final_path}.partial"
checksum_path="${final_path}.sha256"
checksum_partial="${checksum_path}.partial"
staging_path=""
drill_created=0

cleanup() {
    if [[ "${drill_created}" -eq 1 ]]; then
        case "${drill_db}" in
            themisiq_backup_verify_*)
                "${PG_RUNNER}" -u postgres -- "${DROPDB}" \
                    --if-exists --force --port="${PG_PORT}" "${drill_db}" \
                    >/dev/null 2>&1 || true
                ;;
        esac
    fi
    [[ -z "${staging_path}" ]] || rm -f -- "${staging_path}"
    rm -f -- "${partial_path}" "${checksum_partial}"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM

install -d -o root -g root -m 0700 "${BACKUP_DIR}"
if [[ -e "${final_path}" || -e "${checksum_path}" ]]; then
    echo "ERROR: refusing to overwrite existing backup ${final_path}" >&2
    exit 1
fi

staging_path="$(
    "${PG_RUNNER}" -u postgres -- \
        /usr/bin/mktemp /var/lib/postgresql/.themisiq-backup.XXXXXX
)"

"${PG_RUNNER}" -u postgres -- "${PG_DUMP}" \
    --port="${PG_PORT}" \
    --dbname="${SOURCE_DB}" \
    --format=custom \
    --compress=6 \
    --no-owner \
    --no-privileges \
    --file="${staging_path}"

[[ -s "${staging_path}" ]] || {
    echo "ERROR: pg_dump produced an empty backup" >&2
    exit 1
}

"${PG_RUNNER}" -u postgres -- "${PG_RESTORE}" \
    --list "${staging_path}" >/dev/null

"${PG_RUNNER}" -u postgres -- "${CREATEDB}" \
    --port="${PG_PORT}" "${drill_db}"
drill_created=1

"${PG_RUNNER}" -u postgres -- "${PG_RESTORE}" \
    --port="${PG_PORT}" \
    --dbname="${drill_db}" \
    --exit-on-error \
    --no-owner \
    --no-privileges \
    "${staging_path}"

table_count="$(
    "${PG_RUNNER}" -u postgres -- "${PSQL}" \
        --port="${PG_PORT}" \
        --dbname="${drill_db}" \
        --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
        --command="SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema');"
)"
invalid_indexes="$(
    "${PG_RUNNER}" -u postgres -- "${PSQL}" \
        --port="${PG_PORT}" \
        --dbname="${drill_db}" \
        --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
        --command="SELECT count(*) FROM pg_catalog.pg_index WHERE NOT indisvalid;"
)"
restored_size="$(
    "${PG_RUNNER}" -u postgres -- "${PSQL}" \
        --port="${PG_PORT}" \
        --dbname="${drill_db}" \
        --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
        --command="SELECT pg_size_pretty(pg_database_size(current_database()));"
)"

if ! [[ "${table_count}" =~ ^[0-9]+$ ]] || (( table_count == 0 )); then
    echo "ERROR: restored backup contains no application tables" >&2
    exit 1
fi
if [[ "${invalid_indexes}" != "0" ]]; then
    echo "ERROR: restored backup contains ${invalid_indexes} invalid indexes" >&2
    exit 1
fi

install -o root -g root -m 0600 "${staging_path}" "${partial_path}"
mv -- "${partial_path}" "${final_path}"
sha256sum "${final_path}" > "${checksum_partial}"
chmod 0600 "${checksum_partial}"
mv -- "${checksum_partial}" "${checksum_path}"

"${PG_RUNNER}" -u postgres -- "${DROPDB}" \
    --force --port="${PG_PORT}" "${drill_db}"
drill_created=0
rm -f -- "${staging_path}"
staging_path=""

trap - EXIT
echo "backup=PASS"
echo "file=${final_path}"
echo "tables=${table_count}"
echo "restored_size=${restored_size}"
echo "invalid_indexes=${invalid_indexes}"
