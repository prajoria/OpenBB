#!/usr/bin/env bash
# docker/e2e/scripts/run_platform_install.sh
#
# Runs inside the `platform` service. Performs the editable install of
# openbb_platform (mirrors CLAUDE.md "After Code Changes"), then imports
# `openbb` as a smoke check.
#
# Writes status/logs to /artifacts/${RUN_ID}/platform/.

set -euo pipefail

STAGE_DIR="/artifacts/${RUN_ID}/platform"
mkdir -p "${STAGE_DIR}"
exec > >(tee -a "${STAGE_DIR}/stdout.log") 2> >(tee -a "${STAGE_DIR}/stderr.log" >&2)

# Load host .env from the bind-mounted peer path — /workspace is read-only
# so we can't mount .env inside it. Peer path /env/host.env is writable-mount-friendly.
if [[ -f /env/host.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source /env/host.env 2>/dev/null || true
  set +a
fi

# Rewrite user_settings.json mysql_host to compose service DNS name.
/scripts/patch_user_settings.sh

echo "unknown" > "${STAGE_DIR}/status"  # updated to pass/fail below

trap 'grep -q "^pass$" "${STAGE_DIR}/status" 2>/dev/null || echo fail > "${STAGE_DIR}/status"' EXIT

# openbb_src is mounted read-only. dev_install.py writes into the venv,
# which lives on the openbb_venv volume — that's writable.
cd /workspace/openbb_platform

echo "==> python dev_install.py -e"
python dev_install.py -e

echo "==> import openbb sanity check"
python -c "import openbb; print('openbb ok, providers:', len(list(openbb.obb.__dict__.keys())))"

echo "pass" > "${STAGE_DIR}/status"
