#!/usr/bin/env bash
# docker/e2e/scripts/run_pytest.sh
#
# Runs unit tests first (fast, no keys), then integration tests
# (requires bind-mounted user_settings.json + .env). Writes junit XML
# per phase so the reporter can name failing tests precisely.

set -uo pipefail   # not -e: we want both phases to run even if unit fails

STAGE_DIR="/artifacts/${RUN_ID}/pytest"
mkdir -p "${STAGE_DIR}"
exec > >(tee -a "${STAGE_DIR}/stdout.log") 2> >(tee -a "${STAGE_DIR}/stderr.log" >&2)

# Load host .env (peer of read-only /workspace mount).
if [[ -f /env/host.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source /env/host.env 2>/dev/null || true
  set +a
fi

# Rewrite user_settings.json mysql_host to compose service DNS name.
/scripts/patch_user_settings.sh

cd /workspace

PYTEST="python -m pytest"
UNIT_XML="${STAGE_DIR}/junit-unit.xml"
INTEG_XML="${STAGE_DIR}/junit-integration.xml"

echo "==> pytest -m 'not integration' (unit)"
${PYTEST} openbb_platform Analysis -m "not integration" \
    --junitxml="${UNIT_XML}" \
    --maxfail=25
UNIT_RC=$?
echo "unit rc=${UNIT_RC}"

INTEG_RC=0
if [[ "${SKIP_INTEGRATION:-0}" = "1" ]]; then
  echo "==> integration skipped (SKIP_INTEGRATION=1)"
else
  echo "==> pytest -m integration"
  ${PYTEST} openbb_platform Analysis -m "integration" \
      --junitxml="${INTEG_XML}" \
      --maxfail=10
  INTEG_RC=$?
  echo "integration rc=${INTEG_RC}"
fi

if [[ ${UNIT_RC} -eq 0 && ${INTEG_RC} -eq 0 ]]; then
  echo "pass" > "${STAGE_DIR}/status"
else
  echo "fail" > "${STAGE_DIR}/status"
fi
