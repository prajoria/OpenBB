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

# ---------------------------------------------------------------
# Secret-scrubbing helper. The stderr/stdout excerpts we embed in
# bug files can contain provider API keys, GH tokens, MySQL creds,
# etc. — either because a stage crashed while printing config, or
# because the underlying library (pymysql, requests, aiohttp) put
# the connection string / URL in its traceback. Redact before write.
#
# Anything matching the known patterns is replaced with a fixed
# marker. New secret shapes should be added here as we encounter them.
# Deliberately conservative: false-positives (over-redaction) are
# better than a leaked key in a bug file that ends up in a GH issue.
# ---------------------------------------------------------------
scrub() {
  # NOTE on portability:
  #   * `\s` is a gawk extension; use POSIX `[[:space:]]` so this works
  #     under mawk (the default awk in most slim base images).
  #   * env-var values (GH_TOKEN, MYSQL_*) are matched as LITERAL
  #     strings via index()/substr() — NOT via gsub() — because gsub
  #     interprets its 1st arg as a regex, so any metacharacter in the
  #     env value would cause misbehavior (a token with `.` matches
  #     anything, a value with unbalanced `[` throws).
  #
  #   Deliberately conservative: over-redaction (false positive) is
  #   always safer than a leaked key in a bug file that ends up on GH.
  awk -v gh_token="${GH_TOKEN:-}" \
      -v mysql_pw="${MYSQL_PASSWORD:-}" \
      -v mysql_root_pw="${MYSQL_ROOT_PASSWORD:-}" \
      -v fmp_api_key="${FMP_API_KEY:-}" \
  '
    # Literal-string replace all occurrences of `needle` in `s` with
    # `marker`. Uses index() which does substring (not regex) match.
    # Empty/short needles are skipped so we do not redact every
    # occurrence of a common word — needles must be ≥8 chars for
    # redaction to fire. This means passwords <8 chars ARE at risk
    # of leaking through the scrubber. Mitigation: enforce ≥8-char
    # passwords in .env for any shared/CI use of the harness.
    function litreplace(s, needle, marker,   out, i, nlen) {
      nlen = length(needle)
      if (nlen < 8) return s
      out = ""
      while ((i = index(s, needle)) > 0) {
        out = out substr(s, 1, i - 1) marker
        s = substr(s, i + nlen)
      }
      return out s
    }

    {
      line = $0

      # 1. GitHub tokens: gho_/ghp_/ghs_/ghu_/ghr_ + 20+ base62
      gsub(/gh[opsur]_[A-Za-z0-9_]{20,}/, "<REDACTED_GH_TOKEN>", line)

      # 2. Bearer / Basic auth (POSIX-safe: [[:space:]] instead of \s)
      gsub(/[Aa]uthorization:[[:space:]]+[Bb]earer[[:space:]]+[A-Za-z0-9._-]+/, "Authorization: Bearer <REDACTED>", line)
      gsub(/[Aa]uthorization:[[:space:]]+[Bb]asic[[:space:]]+[A-Za-z0-9+\/=]+/, "Authorization: Basic <REDACTED>", line)

      # 3. api_key / apikey / *_api_key assignments (POSIX-safe)
      gsub(/["'\'']?(fmp_api_key|fmp_cached_api_key|openai_api_key|api_key|apikey)["'\'']?[[:space:]]*[:=][[:space:]]*["'\'']?[A-Za-z0-9_-]{16,}["'\'']?/, "<REDACTED_KEY_ASSIGNMENT>", line)

      # 4. URL-embedded credentials: scheme://user:PASSWORD@host
      #    Use character classes explicitly (no \s).
      gsub(/:\/\/[^:@\/[:space:]]+:[^@\/[:space:]]+@/, "://<REDACTED_URL_CREDS>@", line)

      # 5. Session-live values — LITERAL match, not regex.
      #    Must run AFTER the pattern-based passes so we do not double-
      #    redact something already turned into `<REDACTED_...>`.
      if (length(gh_token) >= 8)      line = litreplace(line, gh_token,      "<REDACTED_GH_TOKEN>")
      if (length(mysql_pw) >= 8)      line = litreplace(line, mysql_pw,      "<REDACTED_MYSQL_PW>")
      if (length(mysql_root_pw) >= 8) line = litreplace(line, mysql_root_pw, "<REDACTED_MYSQL_ROOT_PW>")
      if (length(fmp_api_key) >= 8)   line = litreplace(line, fmp_api_key,   "<REDACTED_FMP_API_KEY>")

      print line
    }
  '
}

write_bug_file() {
  local stage="$1"
  local stage_dir="${ARTIFACTS}/${stage}"
  local bug_file="${BUGS_DIR}/${stage}.md"

  local stderr_head="" stdout_tail="" summary_json=""
  if [[ -f "${stage_dir}/stderr.log" ]]; then
    stderr_head="$(head -c 6000 "${stage_dir}/stderr.log" 2>/dev/null | scrub || true)"
  fi
  if [[ -f "${stage_dir}/stdout.log" ]]; then
    stdout_tail="$(tail -c 4000 "${stage_dir}/stdout.log" 2>/dev/null | scrub || true)"
  fi
  if [[ -f "${stage_dir}/summary.json" ]]; then
    summary_json="$(scrub < "${stage_dir}/summary.json" 2>/dev/null || true)"
  fi

  # Grep the junit XML for failing test names, if any.
  local junit_failures=""
  for junit in "${stage_dir}"/junit*.xml; do
    [[ -f "${junit}" ]] || continue
    junit_failures+="$(grep -oE '<(failure|error) [^>]+' "${junit}" 2>/dev/null | head -20)"
  done

  {
    echo "# Bug candidate: stage \`${stage}\`"
    echo
    echo "> **⚠ SECURITY: raw evidence, review before sharing.** This file was"
    echo "> written by the docker/e2e harness. The stderr/stdout excerpts below"
    echo "> have passed through the scrubber in \`scripts/report_and_file.sh\`"
    echo "> (redacts GH tokens, api_key assignments, URL-embedded creds, and"
    echo "> the session's live MYSQL/GH env vars) but no scrubber is complete."
    echo "> Before copying this into a tracker issue, do a final visual pass"
    echo "> for anything key-shaped, path-with-username, or IP address you"
    echo "> don't want public."
    echo ">"
    echo "> The claim below is unvalidated raw output. Cross-check against"
    echo "> the actual repo tree before filing (see the two-phase rule in"
    echo "> \`~/.claude/CLAUDE.md\`)."
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
