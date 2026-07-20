#!/usr/bin/env bash
# docker/e2e/scripts/run_doctor.sh
#
# Uses openbb_fmp_trading.core.doctor.run to verify credentials + MySQL
# cache reachability from inside the container network. Cheap probe.

set -uo pipefail

STAGE_DIR="/artifacts/${RUN_ID}/doctor"
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

python - <<'PY'
import json, os, sys, traceback
try:
    from openbb_fmp_trading.core.doctor import run_doctor
except Exception as e:
    print(f"import failed: {type(e).__name__}: {e}", file=sys.stderr)
    traceback.print_exc()
    sys.exit(2)

report = run_doctor(
    bandwidth_state_path="/tmp/doctor_bandwidth.json",
    bandwidth_budget_bytes=10 * 1024 * 1024 * 1024,  # 10 GiB — effectively unlimited for a smoke run
)
data = {
    "ts": str(getattr(report, "ts", "")),
    "fmp_credentials_ok": getattr(report, "fmp_credentials_ok", None),
    "mysql_cache_ok": getattr(report, "mysql_cache_ok", None),
}
with open(f"/artifacts/{os.environ['RUN_ID']}/doctor/summary.json", "w") as fh:
    json.dump(data, fh, indent=2)
print(json.dumps(data, indent=2))

ok = bool(data["fmp_credentials_ok"]) and bool(data["mysql_cache_ok"])
sys.exit(0 if ok else 1)
PY

RC=$?
if [[ ${RC} -eq 0 ]]; then
  echo "pass" > "${STAGE_DIR}/status"
else
  echo "fail" > "${STAGE_DIR}/status"
fi
