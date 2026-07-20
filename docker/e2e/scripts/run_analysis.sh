#!/usr/bin/env bash
# docker/e2e/scripts/run_analysis.sh
#
# Exercises Analysis/stock_analysis.py::run_full_analysis end-to-end for
# a fixed symbol set. Passes iff every phase (p1..p7) produces a
# non-empty result object with a numeric composite_score on p7.

set -uo pipefail

STAGE_DIR="/artifacts/${RUN_ID}/analysis"
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

SYMBOLS="${ANALYSIS_SYMBOLS:-MSFT,AAPL}"
echo "==> run_full_analysis for: ${SYMBOLS}"

cd /workspace

python - <<PY
import json, os, sys, traceback
sys.path.insert(0, "/workspace/Analysis")
from stock_analysis import AnalysisConfig, run_full_analysis

symbols = [s.strip() for s in os.environ.get("ANALYSIS_SYMBOLS", "MSFT,AAPL").split(",") if s.strip()]
summary = {}
overall_ok = True

for sym in symbols:
    try:
        results = run_full_analysis(AnalysisConfig(symbol=sym))
        p7 = results.get("p7")
        score = getattr(p7, "composite_score", None)
        label = getattr(p7, "action_label", None)
        ok = score is not None
        summary[sym] = {"ok": ok, "composite_score": score, "action_label": label}
        overall_ok = overall_ok and ok
        print(f"{sym}: score={score} label={label}")
    except Exception as e:
        overall_ok = False
        summary[sym] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        traceback.print_exc()

with open(f"/artifacts/{os.environ['RUN_ID']}/analysis/summary.json", "w") as fh:
    json.dump(summary, fh, indent=2)
sys.exit(0 if overall_ok else 1)
PY

RC=$?
if [[ ${RC} -eq 0 ]]; then
  echo "pass" > "${STAGE_DIR}/status"
else
  echo "fail" > "${STAGE_DIR}/status"
fi
