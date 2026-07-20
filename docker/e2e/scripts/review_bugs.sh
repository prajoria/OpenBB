#!/usr/bin/env bash
# docker/e2e/scripts/review_bugs.sh
#
# Human-facing helper that lists the local bug files produced by a
# docker/e2e run so the reviewer (Claude or an engineer) can walk each
# one, cross-check against the current source tree, and file the
# tracker issue with a validated body + proposed fix.
#
# Usage:
#   ./docker/e2e/scripts/review_bugs.sh                  # latest run
#   ./docker/e2e/scripts/review_bugs.sh <run-id>         # specific run
#   ./docker/e2e/scripts/review_bugs.sh --json           # latest, JSON output
#
# This script NEVER files issues. Filing happens after the reviewer has
# opened each bug file, verified the claim in-source, and drafted a fix.
# See the "Automated test-harness bug reporting" rule in ~/.claude/CLAUDE.md.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACTS_ROOT="$(cd "${HERE}/.." && pwd)/artifacts"

JSON=0
RUN_ID=""
for arg in "$@"; do
  case "${arg}" in
    --json) JSON=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) RUN_ID="${arg}" ;;
  esac
done

if [[ -z "${RUN_ID}" ]]; then
  RUN_ID="$(ls -1 "${ARTIFACTS_ROOT}" 2>/dev/null | grep -v '^\.' | tail -1 || true)"
fi
if [[ -z "${RUN_ID}" || ! -d "${ARTIFACTS_ROOT}/${RUN_ID}" ]]; then
  echo "ERROR: no run found (looked in ${ARTIFACTS_ROOT})" >&2
  exit 2
fi

RUN_DIR="${ARTIFACTS_ROOT}/${RUN_ID}"
BUGS_DIR="${RUN_DIR}/bugs"

if [[ ! -d "${BUGS_DIR}" ]]; then
  echo "No bugs directory in ${RUN_DIR} — either the run is still in progress"
  echo "or no failures were reported. Check ${RUN_DIR}/summary.md."
  exit 0
fi

# Gather develop SHA from the checkout stage (best-effort).
DEVELOP_SHA="unknown"
if [[ -f "${RUN_DIR}/checkout/develop_sha" ]]; then
  DEVELOP_SHA="$(cat "${RUN_DIR}/checkout/develop_sha")"
fi

if [[ ${JSON} -eq 1 ]]; then
  # Prefer the isolated harness venv over system python. Falls back to
  # `python` only if HARNESS_PY isn't set (e.g. review_bugs.sh invoked
  # standalone, not from run.sh). Bail loudly on system-python fallback.
  PY="${HARNESS_PY:-}"
  if [[ -z "${PY}" ]]; then
    REPO_ROOT_GUESS="$(cd "${HERE}/../../.." && pwd)"
    for candidate in \
        "${REPO_ROOT_GUESS}/.venv_docker_openbb/Scripts/python.exe" \
        "${REPO_ROOT_GUESS}/.venv_docker_openbb/bin/python"; do
      [[ -x "${candidate}" ]] && { PY="${candidate}"; break; }
    done
  fi
  if [[ -z "${PY}" ]]; then
    echo "ERROR: harness host venv not found. Run './run.sh' once (creates .venv_docker_openbb)" >&2
    echo "       or explicitly: python -m venv \$REPO_ROOT/.venv_docker_openbb" >&2
    exit 3
  fi
  "${PY}" - "${RUN_ID}" "${DEVELOP_SHA}" "${BUGS_DIR}" <<'PY'
import json, os, sys
run_id, sha, bugs_dir = sys.argv[1], sys.argv[2], sys.argv[3]
out = {"run_id": run_id, "develop_sha": sha, "bugs": []}
for name in sorted(os.listdir(bugs_dir)):
    if not name.endswith(".md"):
        continue
    path = os.path.join(bugs_dir, name)
    out["bugs"].append({
        "stage": os.path.splitext(name)[0],
        "path": path,
        "bytes": os.path.getsize(path),
    })
print(json.dumps(out, indent=2))
PY
  exit 0
fi

echo "Run ID:      ${RUN_ID}"
echo "develop SHA: ${DEVELOP_SHA}"
echo "Bugs dir:    ${BUGS_DIR}"
echo
echo "Local bug files ready for review:"
echo
i=0
for f in "${BUGS_DIR}"/*.md; do
  [[ -f "${f}" ]] || continue
  i=$((i+1))
  stage="$(basename "${f}" .md)"
  bytes="$(wc -c < "${f}" | tr -d ' ')"
  first_line="$(sed -n '2,20p' "${f}" | head -1)"
  printf "  %d) %s (%s bytes) — %s\n" "${i}" "${stage}" "${bytes}" "${first_line}"
  printf "     %s\n" "${f}"
done

if [[ ${i} -eq 0 ]]; then
  echo "  (none — all stages passed)"
  exit 0
fi

cat <<EOF

Review workflow:
  1. cat each bug file above.
  2. Cross-check the claimed root cause in the current develop tree.
  3. Search the tracker for existing open issues on the same failure:
       gh issue list --repo prajoria/OpenBB --state open --search "<keyword>"
  4. Draft a fix (or note that investigation is required).
  5. File the issue with a validated body:
       gh issue create --repo prajoria/OpenBB --title "..." --body-file <path> \\
         --label develop_test_issues
  6. Cross-reference the harness run ID in the issue body so future runs
     can be linked back.

The harness itself does NOT file issues. That's deliberate — see the
"Automated test-harness bug reporting" rule in ~/.claude/CLAUDE.md.
EOF
