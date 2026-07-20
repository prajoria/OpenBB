#!/usr/bin/env bash
# docker/e2e/run.sh
#
# Single entrypoint for the develop-branch E2E stability harness.
# See ../../plans (luminous-petting-tome.md) and README.md for design.
#
# Usage:
#   ./run.sh                  # full sweep
#   ./run.sh --skip-desktop   # skip the Tauri web-build stage
#   ./run.sh --skip-integration
#   ./run.sh --keep-volumes   # don't nuke openbb_src between runs (dev-only)
#
# Exit code: 0 iff every stage's `status` file reads `pass`. Non-zero
# otherwise — but the reporter ALWAYS runs and files GH Issues.

set -euo pipefail

# ---------------------------------------------------------------
# Resolve paths (works from any CWD, on Linux/macOS/WSL/Git-Bash).
# ---------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${SCRIPT_DIR}"

# On native Windows / Git-Bash, HOME may not point at the user profile
# where user_settings.json lives. Compose reads ${HOME} directly, so
# normalize it here.
if [[ -z "${HOME:-}" && -n "${USERPROFILE:-}" ]]; then
  export HOME="${USERPROFILE}"
fi

# ---------------------------------------------------------------
# Preflight — fail loudly if secrets aren't where compose expects.
# ---------------------------------------------------------------
USER_SETTINGS="${HOME}/.openbb_platform/user_settings.json"
if [[ ! -f "${USER_SETTINGS}" ]]; then
  echo "ERROR: ${USER_SETTINGS} not found." >&2
  echo "  Configure API keys per CLAUDE.md before running the harness." >&2
  exit 2
fi
if [[ ! -f "${REPO_ROOT}/.env" ]]; then
  # Create an empty .env so the bind mount succeeds; contents are optional.
  touch "${REPO_ROOT}/.env"
fi

# Host-side Python — must be the isolated harness venv, never the
# system interpreter. Prevents dependency drift across the multiple
# parallel OpenBB checkouts on this box. Container-side Python is
# separately isolated in the openbb_venv Docker volume; this variable
# only governs host-side helpers (e.g. review_bugs.sh --json).
export HARNESS_VENV="${REPO_ROOT}/.venv_docker_openbb"
export HARNESS_PY="${HARNESS_VENV}/Scripts/python.exe"
if [[ ! -x "${HARNESS_PY}" ]]; then
  HARNESS_PY_NIX="${HARNESS_VENV}/bin/python"    # Linux/macOS fallback
  if [[ -x "${HARNESS_PY_NIX}" ]]; then
    HARNESS_PY="${HARNESS_PY_NIX}"
  else
    echo "ERROR: harness host venv not found at ${HARNESS_VENV}" >&2
    echo "  Create with: python -m venv ${HARNESS_VENV}" >&2
    exit 2
  fi
fi
echo "==> Host Python: ${HARNESS_PY} ($(${HARNESS_PY} --version 2>&1))"

# ---------------------------------------------------------------
# Parse args.
# ---------------------------------------------------------------
SKIP_DESKTOP=0
SKIP_INTEGRATION=0
KEEP_VOLUMES=0
for arg in "$@"; do
  case "${arg}" in
    --skip-desktop)     SKIP_DESKTOP=1 ;;
    --skip-integration) SKIP_INTEGRATION=1 ;;
    --keep-volumes)     KEEP_VOLUMES=1 ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: ${arg}" >&2; exit 64 ;;
  esac
done
export SKIP_INTEGRATION

# ---------------------------------------------------------------
# Run identifier — timestamp + short hostname for uniqueness.
# ---------------------------------------------------------------
export RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$(hostname | tr -c 'a-zA-Z0-9' '_' | cut -c1-8)"
ARTIFACT_DIR="${SCRIPT_DIR}/artifacts/${RUN_ID}"
mkdir -p "${ARTIFACT_DIR}"
echo "==> Run ID: ${RUN_ID}"
echo "==> Artifacts: ${ARTIFACT_DIR}"

# ---------------------------------------------------------------
# Load .env into shell so GH_TOKEN / GH_REPO are visible to compose.
# ---------------------------------------------------------------
set -a
# shellcheck disable=SC1091
source "${REPO_ROOT}/.env" 2>/dev/null || true
set +a
export GH_REPO="${GH_REPO:-prajoria/OpenBB}"

# ---------------------------------------------------------------
# Optional volume reset — always fresh source unless --keep-volumes.
# ---------------------------------------------------------------
if [[ ${KEEP_VOLUMES} -eq 0 ]]; then
  echo "==> Removing openbb_src and openbb_venv volumes for a fully fresh run"
  # openbb_venv MUST be wiped too — editable installs (dev_install.py -e)
  # write metadata into site-packages pointing at the source paths that
  # existed at install-time. If develop later adds a module (e.g. #862
  # adding openbb_core/api/app_loader.py after we cached the old install),
  # the stale editable metadata doesn't see the new file → import fails
  # in the container even though the file is right there on the source
  # volume. Cost: dev_install.py -e re-runs (~10 min); benefit: no false
  # regressions from cache staleness masquerading as develop bugs.
  docker compose down --remove-orphans >/dev/null 2>&1 || true
  docker volume rm openbb-e2e_openbb_src  >/dev/null 2>&1 || true
  docker volume rm openbb-e2e_openbb_venv >/dev/null 2>&1 || true
fi

# ---------------------------------------------------------------
# Stage sequence. Each `docker compose run` blocks until that
# service exits; failures do NOT abort the script — we press on
# so the reporter sees every stage's status file.
# ---------------------------------------------------------------
run_stage() {
  local name="$1"; shift
  echo "==> stage: ${name}"
  # --no-deps: prevent compose from re-running dependency chain (esp.
  # `platform` which triggers dev_install.py -e; running that 3 times
  # per invocation was causing races where uvicorn started before
  # editable-install .pth files were written → phantom ModuleNotFoundError
  # for openbb_core.api.app_loader).
  if ! docker compose run --rm --no-deps "$@"; then
    echo "!! stage ${name} exited non-zero (continuing)" >&2
  fi
}

# 0. Docker daemon must be reachable — the entire rest of the run is
# `docker compose` calls, and if the daemon is down those fail non-fatal
# in the loop below, producing a zero-status-file "success" that masks
# real infrastructure failure. Fail loud, fail early.
if ! docker info >/dev/null 2>&1; then
  echo "ERROR: docker daemon not reachable. Start Docker Desktop and retry." >&2
  mkdir -p "${ARTIFACT_DIR}/harness"
  echo "docker daemon unreachable at $(date -u +%FT%TZ)" > "${ARTIFACT_DIR}/harness/stderr.log"
  echo "fail" > "${ARTIFACT_DIR}/harness/status"
  exit 3
fi

# Track which stages we EXPECT to see status files for. Any expected
# stage that has no status file at aggregation time is treated as fail
# — otherwise a `docker compose run` that never started (image build
# broken, daemon crash mid-run) silently disappears from the report.
declare -a EXPECTED_STAGES=(checkout platform pytest analysis doctor api_smoke)

# 1. Infra first — mysql needs to be healthy before anything reads it.
echo "==> Starting mysql"
docker compose up -d mysql
# wait for healthy (compose's `depends_on: service_healthy` handles it
# for downstream `run` commands, but log the state for humans).
docker compose ps mysql

# 2. Fresh checkout of origin/develop.
run_stage checkout checkout

# Capture DEVELOP_SHA so the reporter can attach it to issues.
DEVELOP_SHA="$(cat "${ARTIFACT_DIR}/checkout/develop_sha" 2>/dev/null || echo unknown)"
export DEVELOP_SHA
echo "==> develop @ ${DEVELOP_SHA}"

# 3. Build platform image + do editable install sanity check.
docker compose build platform
run_stage platform platform

# 4. Bring API up (long-running), then fan out parallel stages.
# --no-deps prevents the same platform-re-run trap that motivated
# --no-deps on the fan-out below. api's own healthcheck governs
# start_period; we explicitly wait for healthy before fan-out.
docker compose up -d --no-deps api
docker compose ps api

echo "==> waiting for api healthy"
until [[ "$(docker inspect --format '{{.State.Health.Status}}' openbb-e2e-api-1 2>/dev/null)" = "healthy" ]]; do
  sleep 2
done
echo "==> api healthy"

# Parallel fan-out: pytest, analysis, doctor, api_smoke, desktop.
# `docker compose run` in the background + wait pattern.
declare -a PIDS=()
run_stage_bg() {
  local name="$1"; shift
  # --no-deps for ALL fan-out stages: platform + mysql + api are already
  # up from earlier `run_stage` / `up -d`. Re-triggering platform via
  # depends_on chains would re-run dev_install.py during test execution.
  # Networking works fine without --no-deps here because compose reuses
  # the shared project network — the dependency chain re-trigger is the
  # only problem, and --no-deps kills it.
  ( docker compose run --rm --no-deps "$@" || echo "!! stage ${name} exited non-zero" >&2 ) &
  PIDS+=($!)
}

run_stage_bg pytest      pytest
run_stage_bg analysis    analysis
run_stage_bg doctor      doctor
run_stage_bg api_smoke   api_smoke
if [[ ${SKIP_DESKTOP} -eq 0 ]]; then
  EXPECTED_STAGES+=(desktop)
  docker compose build desktop
  run_stage_bg desktop desktop
fi

for pid in "${PIDS[@]}"; do wait "${pid}" || true; done

# 5. Tear down long-running services before reporter runs.
docker compose stop api mysql

# 6. Fill in placeholder status files for any EXPECTED stage that never
#    produced one (container failed to start, image build broke, etc.).
#    This MUST happen before the reporter runs so those stages appear
#    in summary.md and get GH issues filed.
declare -A SEEN=()
for status_file in "${ARTIFACT_DIR}"/*/status; do
  [[ -f "${status_file}" ]] || continue
  stage="$(basename "$(dirname "${status_file}")")"
  SEEN["${stage}"]=1
done
for stage in "${EXPECTED_STAGES[@]}"; do
  if [[ -z "${SEEN[$stage]:-}" ]]; then
    echo "  ${stage}: MISSING (no status file — filling placeholder before reporter)"
    mkdir -p "${ARTIFACT_DIR}/${stage}"
    echo "fail" > "${ARTIFACT_DIR}/${stage}/status"
    echo "stage did not produce a status file — likely container failed to start" \
      > "${ARTIFACT_DIR}/${stage}/stderr.log"
  fi
done

# 7. Reporter ALWAYS runs. Builds Dockerfile.runner on demand.
docker compose build reporter
docker compose run --rm reporter || true

# 8. Aggregate exit code from stage status files.
EXIT_CODE=0
for status_file in "${ARTIFACT_DIR}"/*/status; do
  [[ -f "${status_file}" ]] || continue
  read -r status < "${status_file}"
  stage="$(basename "$(dirname "${status_file}")")"
  echo "  ${stage}: ${status}"
  if [[ "${status}" != "pass" && "${status}" != "skipped" ]]; then
    EXIT_CODE=1
  fi
done

echo "==> Run ${RUN_ID} complete (exit=${EXIT_CODE})"
exit ${EXIT_CODE}
