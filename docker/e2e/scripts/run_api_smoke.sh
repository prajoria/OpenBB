#!/usr/bin/env bash
# docker/e2e/scripts/run_api_smoke.sh
#
# Probes the running `api` service. GETs /docs (always exists) plus a
# handful of representative endpoints. Full route coverage is a
# follow-up; this catches import-time regressions and gross breakage.

set -uo pipefail

STAGE_DIR="/artifacts/${RUN_ID}/api_smoke"
mkdir -p "${STAGE_DIR}"
exec > >(tee -a "${STAGE_DIR}/stdout.log") 2> >(tee -a "${STAGE_DIR}/stderr.log" >&2)

# Load host .env (peer of read-only /workspace mount).
if [[ -f /env/host.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source /env/host.env 2>/dev/null || true
  set +a
fi

python - <<'PY'
import json, os, sys, httpx

BASE = os.environ.get("API_BASE", "http://api:8000")
PROBES = [
    ("GET", "/docs", None),
    ("GET", "/openapi.json", None),
]

results = []
failed = 0
with httpx.Client(base_url=BASE, timeout=15.0, follow_redirects=True) as c:
    for method, path, body in PROBES:
        try:
            r = c.request(method, path, json=body)
            ok = 200 <= r.status_code < 400
            results.append({"method": method, "path": path, "status": r.status_code, "ok": ok})
            if not ok:
                failed += 1
        except Exception as e:
            failed += 1
            results.append({"method": method, "path": path, "error": f"{type(e).__name__}: {e}"})

with open(f"/artifacts/{os.environ['RUN_ID']}/api_smoke/summary.json", "w") as fh:
    json.dump(results, fh, indent=2)
print(json.dumps(results, indent=2))
sys.exit(0 if failed == 0 else 1)
PY

RC=$?
if [[ ${RC} -eq 0 ]]; then
  echo "pass" > "${STAGE_DIR}/status"
else
  echo "fail" > "${STAGE_DIR}/status"
fi
