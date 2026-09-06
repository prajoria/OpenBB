#!/bin/sh
# docker/e2e/scripts/fetch_develop.sh
#
# Runs inside the `checkout` service (alpine/git). Populates the
# `openbb_src` volume with a fresh shallow clone of the configured
# remote/branch and writes ${RUN_ID}/checkout/{status,develop_sha}.
#
# Idempotent: if the target already exists, it's wiped first — we
# always want a KNOWN clean state, no `git pull` on top of stale work.

set -eu

STAGE_DIR="/artifacts/${RUN_ID}/checkout"
mkdir -p "${STAGE_DIR}"
exec > "${STAGE_DIR}/stdout.log" 2> "${STAGE_DIR}/stderr.log"

REMOTE="${DEVELOP_REMOTE:-https://github.com/prajoria/OpenBB.git}"
BRANCH="${DEVELOP_BRANCH:-develop}"

echo "fetching ${REMOTE} @ ${BRANCH} into /src"

# Wipe existing checkout for determinism. `find` avoids issues with
# hidden dotfiles at the mount root that `rm -rf /src/*` would miss.
find /src -mindepth 1 -maxdepth 1 -exec rm -rf {} +

git clone --depth=1 --branch "${BRANCH}" "${REMOTE}" /src

SHA="$(git -C /src rev-parse HEAD)"
echo "${SHA}" > "${STAGE_DIR}/develop_sha"
echo "cloned develop @ ${SHA}"

echo "pass" > "${STAGE_DIR}/status"
