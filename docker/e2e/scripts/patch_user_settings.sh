#!/usr/bin/env bash
# docker/e2e/scripts/patch_user_settings.sh
#
# Called at the top of every stage that needs to reach the compose-network
# mysql. Copies the read-only host user_settings.json to a writable
# container-local path (`~/.openbb_platform/user_settings.json`) and
# rewrites `mysql_host` to `mysql` (the compose DNS name) so the
# openbb_fmp_cached provider — which reads user_settings.json DIRECTLY,
# ignoring env vars — connects to our container instead of the host's
# `localhost:3306`.
#
# Safe to source or exec; idempotent.

set -euo pipefail

SRC=/env/host_user_settings.json
DEST_DIR=/root/.openbb_platform
DEST="${DEST_DIR}/user_settings.json"

if [[ ! -f "${SRC}" ]]; then
  echo "patch_user_settings: ${SRC} missing — nothing to patch" >&2
  exit 0
fi

mkdir -p "${DEST_DIR}"

# Rewrite mysql_host + mysql_port using Python (jq isn't in Dockerfile.platform).
python - "${SRC}" "${DEST}" <<'PY'
import json, sys
src, dest = sys.argv[1], sys.argv[2]
with open(src) as f:
    data = json.load(f)
creds = data.setdefault("credentials", {})
creds["mysql_host"] = "mysql"
# UserSettings model requires str for mysql_port — writing int trips pydantic.
creds["mysql_port"] = "3306"
# Compose creates `fmp_user`/`fmp_user` on the mysql service; align the
# rewritten settings so the container reaches it. Host settings may
# carry a different password for the same user against the developer's
# host-native MySQL instance.
creds["mysql_user"] = "fmp_user"
creds["mysql_password"] = "fmp_user"
creds["mysql_database"] = "openbb_fmp_cache_test"
# Password/user/db already correct per user_settings; leave them.
with open(dest, "w") as f:
    json.dump(data, f, indent=2)
PY

echo "patch_user_settings: wrote ${DEST} (mysql_host=mysql)"
