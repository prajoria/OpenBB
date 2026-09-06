#!/usr/bin/env bash
# docker/e2e/mysql/restore_dump.sh
#
# Restores a mysqldump-style all-databases dump into the running
# `mysql` compose service. Streams the dump over stdin via
# `docker compose exec -T` so we don't have to copy the 330MB dump
# into the repo tree or fight Windows/WSL bind-mount quirks.
#
# We restore ONLY the openbb_fmp_cache* databases — the `mysql` system
# schema in the dump would clobber the users/grants created by our
# init.d/00-bootstrap.sql.
#
# Usage:
#   ./docker/e2e/mysql/restore_dump.sh /h/DBBackup/mysql_all_databases.sql
#   ./docker/e2e/mysql/restore_dump.sh                    # uses default path below
#
# Wall-clock: ~30-90s for a 330MB dump on SSD.

set -euo pipefail

DEFAULT_DUMP="/h/DBBackup/mysql_all_databases.sql"
DUMP_PATH="${1:-${DEFAULT_DUMP}}"

if [[ ! -f "${DUMP_PATH}" ]]; then
  echo "ERROR: dump not found: ${DUMP_PATH}" >&2
  echo "  Pass a path or place the file at ${DEFAULT_DUMP}" >&2
  exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="$(cd "${HERE}/.." && pwd)"
cd "${COMPOSE_DIR}"

# Preflight — daemon + mysql service must be up.
if ! docker info >/dev/null 2>&1; then
  echo "ERROR: docker daemon not reachable. Start Docker Desktop and retry." >&2
  exit 3
fi
if ! docker compose ps --services --filter status=running | grep -q '^mysql$'; then
  echo "==> mysql service not running; starting it"
  # `RUN_ID` is required by the compose file for downstream services;
  # for the mysql-only bring-up, a placeholder is fine.
  RUN_ID="${RUN_ID:-restore-$(date -u +%Y%m%dT%H%M%SZ)}" \
    REPO_ROOT="$(cd "${COMPOSE_DIR}/../.." && pwd)" \
    HOME="${HOME:-${USERPROFILE:-}}" \
    docker compose up -d mysql
fi

echo "==> Waiting for mysql to be healthy"
for _ in {1..60}; do
  state="$(docker compose ps --format '{{.Service}} {{.Health}}' mysql 2>/dev/null | awk '$1=="mysql"{print $2}')"
  [[ "${state}" = "healthy" ]] && break
  sleep 2
done
if [[ "${state:-}" != "healthy" ]]; then
  echo "ERROR: mysql never reached healthy state (last: ${state:-unknown})" >&2
  exit 4
fi

DUMP_BYTES=$(stat -c%s "${DUMP_PATH}" 2>/dev/null || stat -f%z "${DUMP_PATH}")
echo "==> Restoring app databases (skipping mysql system schema) from"
echo "    ${DUMP_PATH} (${DUMP_BYTES} bytes)"

# Filter chain, all in one pipe (no temp files):
#   1. awk on the host: drop the `mysql`-system-DB section of the dump
#      (from `-- Current Database: `mysql`` up to the next
#      `-- Current Database:` marker for an openbb_* schema).
#   2. docker exec -T: stream the filtered SQL into `mysql` inside the
#      container as root. We use --defaults-extra-file via <(printf ...)
#      so the root password never appears on the command line inside
#      the container process list.
awk '
  BEGIN { skip = 0 }
  /^-- Current Database: `mysql`/                    { skip = 1; next }
  /^-- Current Database: `openbb_fmp_cache`/         { skip = 0 }
  /^-- Current Database: `openbb_fmp_cache_test`/    { skip = 0 }
  skip == 0 { print }
' "${DUMP_PATH}" | docker compose exec -T mysql sh -c '
  set -eu
  # The mysql:8.4 official image sets $MYSQL_ROOT_PASSWORD in the
  # container env from the compose environment. Feed it to the mysql
  # client via MYSQL_PWD (mysql-cli-standard env var) so the literal
  # never appears in argv where `ps` / `docker top` would show it.
  #
  # NOTE: `mysql -p"$X"` was the earlier attempt and is WRONG —
  # shell expansion places the password in argv before exec, defeating
  # the point. MYSQL_PWD keeps it in environ (which requires
  # /proc/<pid>/environ access to read — meaningfully harder for a
  # co-tenant than `ps`).
  #
  # The mysql client itself does emit a "WARNING: Using a password
  # on the command line interface can be insecure" — that warning
  # comes from MYSQL_PWD usage too but is spurious in a container
  # where the env is not shared with any other process.
  : "${MYSQL_ROOT_PASSWORD:=rootpw}"
  export MYSQL_PWD="${MYSQL_ROOT_PASSWORD}"
  mysql -uroot
'

echo "==> Restore complete — verifying"
docker compose exec -T mysql sh -c '
  : "${MYSQL_PASSWORD:=e2e_fmppw_change_me}"
  export MYSQL_PWD="${MYSQL_PASSWORD}"
  mysql -ufmp_user -e "
    SELECT table_schema AS db, COUNT(*) AS tables
    FROM information_schema.tables
    WHERE table_schema IN ('"'"'openbb_fmp_cache'"'"','"'"'openbb_fmp_cache_test'"'"')
    GROUP BY table_schema;
  "
' 2>&1 | grep -vE "Using a password|^mysql:" || true
