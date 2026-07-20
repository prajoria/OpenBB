#!/usr/bin/env bash
# docker/e2e/scripts/build_desktop.sh
#
# Validates the desktop web bundle builds. Runs `npm ci && npm run build`
# in a scratch copy of /workspace/desktop (the source volume is read-only).

set -uo pipefail

STAGE_DIR="/artifacts/${RUN_ID}/desktop"
mkdir -p "${STAGE_DIR}"
exec > >(tee -a "${STAGE_DIR}/stdout.log") 2> >(tee -a "${STAGE_DIR}/stderr.log" >&2)

WORK=/tmp/desktop
rm -rf "${WORK}"
cp -r /workspace/desktop "${WORK}"
cd "${WORK}"

echo "==> npm ci"
npm ci --no-audit --no-fund
RC1=$?
if [[ ${RC1} -ne 0 ]]; then
  echo "fail" > "${STAGE_DIR}/status"
  exit 1
fi

echo "==> npm run build"
npm run build
RC2=$?

if [[ ${RC2} -eq 0 && -d dist ]]; then
  echo "pass" > "${STAGE_DIR}/status"
else
  echo "fail" > "${STAGE_DIR}/status"
  exit 1
fi
