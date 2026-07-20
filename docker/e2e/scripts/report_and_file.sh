#!/usr/bin/env bash
# docker/e2e/scripts/report_and_file.sh
#
# Runs LAST and ALWAYS. Reads /artifacts/${RUN_ID}/*/status and each
# stage's stderr/junit/summary, and writes a STRUCTURED BUG FILE per
# failure to /artifacts/${RUN_ID}/bugs/<stage>.md.
#
# This script deliberately does NOT call `gh issue create` or touch any
# tracker. Filing is a manual second step (see docker/e2e/scripts/review_bugs.sh
# and the "two-phase" rule in ~/.claude/CLAUDE.md). Rationale:
#   - the harness can produce evidence but can't tell noise from signal;
#   - it can't cross-check the claim against the current source tree;
#   - it can't propose a fix grounded in the actual code;
#   - it can't dedupe intelligently against existing open issues.
#
# Contract this script consumes (written by each runner stage):
#   /artifacts/${RUN_ID}/<stage>/status         -> "pass" | "fail" | "skipped"
#   /artifacts/${RUN_ID}/<stage>/stdout.log
#   /artifacts/${RUN_ID}/<stage>/stderr.log
#   /artifacts/${RUN_ID}/<stage>/junit-*.xml    (optional)
#   /artifacts/${RUN_ID}/<stage>/summary.json   (optional)
#
# Contract this script writes:
#   /artifacts/${RUN_ID}/summary.md             -> human-readable overview
#   /artifacts/${RUN_ID}/bugs/<stage>.md        -> one per failure, ready to review

set -uo pipefail

ARTIFACTS="/artifacts/${RUN_ID}"
SUMMARY="${ARTIFACTS}/summary.md"
BUGS_DIR="${ARTIFACTS}/bugs"
mkdir -p "${BUGS_DIR}"

{
  echo "# OpenBB develop E2E report"
  echo
  echo "- Run ID: \`${RUN_ID}\`"
  echo "- develop SHA: \`${DEVELOP_SHA:-unknown}\`"
  echo "- Repo: \`${GH_REPO:-prajoria/OpenBB}\`"
  echo
  echo "## Stage results"
  echo
  echo "| Stage | Status |"
  echo "|-------|--------|"
} > "${SUMMARY}"

FAILED_STAGES=()
for status_file in "${ARTIFACTS}"/*/status; do
  [[ -f "${status_file}" ]] || continue
  stage="$(basename "$(dirname "${status_file}")")"
  read -r status < "${status_file}"
  echo "| ${stage} | ${status} |" >> "${SUMMARY}"
  if [[ "${status}" = "fail" ]]; then
    FAILED_STAGES+=("${stage}")
  fi
done

echo >> "${SUMMARY}"

if [[ ${#FAILED_STAGES[@]} -eq 0 ]]; then
  echo "## Verdict" >> "${SUMMARY}"
  echo >> "${SUMMARY}"
  echo "_All stages passed. develop @ ${DEVELOP_SHA:-unknown} is green._" >> "${SUMMARY}"
  echo "==> All stages passed for ${DEVELOP_SHA:-unknown}"
  exit 0
fi

# ---------------------------------------------------------------
# For each failed stage, write a local bug file with evidence.
# The reviewer (Claude / a human) will cross-check + file the issue.
# ---------------------------------------------------------------
echo "## Bug files written" >> "${SUMMARY}"
echo >> "${SUMMARY}"

write_bug_file() {
  local stage="$1"
  local stage_dir="${ARTIFACTS}/${stage}"
  local bug_file="${BUGS_DIR}/${stage}.md"

  local stderr_head="" stdout_tail="" summary_json=""
  [[ -f "${stage_dir}/stderr.log" ]] && stderr_head="$(head -c 6000 "${stage_dir}/stderr.log" 2>/dev/null || true)"
  [[ -f "${stage_dir}/stdout.log" ]] && stdout_tail="$(tail -c 4000 "${stage_dir}/stdout.log" 2>/dev/null || true)"
  [[ -f "${stage_dir}/summary.json" ]] && summary_json="$(cat "${stage_dir}/summary.json" 2>/dev/null || true)"

  # Grep the junit XML for failing test names, if any.
  local junit_failures=""
  for junit in "${stage_dir}"/junit*.xml; do
    [[ -f "${junit}" ]] || continue
    junit_failures+="$(grep -oE '<(failure|error) [^>]+' "${junit}" 2>/dev/null | head -20)"
  done

  {
    echo "# Bug candidate: stage \`${stage}\`"
    echo
    echo "> **This file was written by the docker/e2e harness.** It is"
    echo "> raw evidence, not a validated issue. Review the claims against"
    echo "> the actual repo tree before filing to any tracker."
    echo
    echo "## Metadata"
    echo
    echo "- Run ID: \`${RUN_ID}\`"
    echo "- develop SHA: \`${DEVELOP_SHA:-unknown}\`"
    echo "- Stage: \`${stage}\`"
    echo "- Full artifacts: \`docker/e2e/artifacts/${RUN_ID}/${stage}/\`"
    echo "- Timestamp: $(date -u +%FT%TZ)"
    echo
    if [[ -n "${summary_json}" ]]; then
      echo "## Stage summary.json"
      echo
      echo '```json'
      echo "${summary_json}"
      echo '```'
      echo
    fi
    if [[ -n "${junit_failures}" ]]; then
      echo "## Junit failure markers"
      echo
      echo '```'
      echo "${junit_failures}"
      echo '```'
      echo
    fi
    echo "## stderr (first 6KB)"
    echo
    echo '```'
    echo "${stderr_head:-<empty>}"
    echo '```'
    echo
    echo "## stdout (last 4KB)"
    echo
    echo '```'
    echo "${stdout_tail:-<empty>}"
    echo '```'
    echo
    echo "## Reviewer checklist (fill in before filing)"
    echo
    echo "- [ ] Reproduced against a fresh checkout (not just artifacts)"
    echo "- [ ] Root-cause file/line identified in current \`develop\`"
    echo "- [ ] Not already covered by an open issue on the tracker"
    echo "- [ ] Proposed fix drafted and validated (or marked as investigation-only)"
    echo "- [ ] Impact statement written (what breaks, for whom, when)"
  } > "${bug_file}"

  echo "  wrote ${bug_file}"
  echo "- \`${stage}\` -> \`bugs/${stage}.md\`" >> "${SUMMARY}"
}

for s in "${FAILED_STAGES[@]}"; do write_bug_file "${s}"; done

echo >> "${SUMMARY}"
echo "## Next step" >> "${SUMMARY}"
echo >> "${SUMMARY}"
echo "\`docker/e2e/scripts/review_bugs.sh ${RUN_ID}\` lists all bug" >> "${SUMMARY}"
echo "files ready for review. Claude (or the on-call engineer) reads" >> "${SUMMARY}"
echo "each, validates against current source, drafts a fix, and files" >> "${SUMMARY}"
echo "the tracker issue by hand — the harness never files directly." >> "${SUMMARY}"

echo "==> Reporter done. ${#FAILED_STAGES[@]} bug file(s) written to ${BUGS_DIR}"
exit 1
