# D0 — PyneCore submodule pin + license drift defense

| Field | Value |
|---|---|
| **Status** | v1.0 — In force as of bead `OpenBBTechnical-0e9.4.3`. |
| **Bead** | `OpenBBTechnical-0e9.4.3` (parent epic `0e9`, GH #106 L0.3) |
| **Branch** | `openbb_tradingview` |
| **Parent doc** | [`temp/openbb-pine-extension-prd.md`](../../../temp/openbb-pine-extension-prd.md) — PRD §10 R4, §2.2, §2.6 |
| **Companions** | D1 (compiler), D2 (runtime bridge), D3 (platform integration) |
| **Owners** | Maintainer (license review), Build eng (CI workflow) |

> **Scope.** D0 locks the rules for the vendored PyneCore submodule at
> `third_party/pynecore/`: how it is pinned, how upstream license drift is
> detected, and the exact procedure a future bump must follow. Everything else
> about PyneCore (runtime integration, OHLCV bridge, attribution surfaces) is
> covered by D2 §1 and PRD §2.6.

---

## 1. Currently pinned

| Item | Value |
|---|---|
| Submodule path | `third_party/pynecore/` |
| Upstream | `https://github.com/prajoria/pynecore.git` |
| Pinned commit | `2919eac66f563e035987b58122db52b1957cfef1` |
| Pinned version | `6.5.2` (matches PRD §2.2 expectation) |
| Pin license | Apache-2.0 (one-way compatible with our AGPL-3.0 — PRD §2.2) |
| `NOTICE` sha256 | `42ff53bbc8d03337480d81699e424fbf58e49837c1f037ba792e9a170f5a6555` (912 bytes) |
| `LICENSE` sha256 | `80a06338645bbd84e84ee8a3438f91e4614eed5726c62d539888472ea08f1fe0` (11543 bytes) |
| Manifest of record | [`third_party/pynecore.license_manifest.json`](../../../third_party/pynecore.license_manifest.json) |

The values above mirror the manifest. When they diverge, **the manifest is
truth** — this doc should be updated as part of the bump (step 3 below).

> **Why the manifest is a *sibling* of the submodule (not inside it).** Git
> deliberately treats submodule contents as opaque to the parent repo: a file
> at `third_party/pynecore/.license_manifest.json` is owned by the *PyneCore*
> repository, not by us, and would be ignored by `git add` in the parent
> (`fatal: Pathspec '...' is in submodule`). Worse, `git submodule update`
> would wipe an untracked file added there. Keeping the manifest at
> `third_party/pynecore.license_manifest.json` (sibling, not child) makes the
> parent repo own it — which is exactly the property the SHA gate needs.

## 2. Why pinned

Two PRD risks force the pin and the CI gate:

- **PRD §10 R4 — "Vendored PyneCore upstream pivots license."** The mitigation
  the PRD names is: *submodule pinned; CI check on license SHA; fallback plan:
  fork at last Apache-2.0 commit.* D0 is the implementation of that bullet.
- **PRD §2.2 — PyneCore compliance checklist.** The §4(d) attribution
  requirement (*"Powered by PyneSys (https://pynesys.io)"*) lives in the
  upstream `NOTICE` file. If upstream silently changes what it asks for, we
  could be out of compliance the moment we ship the next bump.

A vendored submodule alone is not enough: nothing in vanilla git stops a
maintainer from running `git submodule update --remote` and committing a
SHA-different `NOTICE` without anyone reading the diff. The SHA gate forces
the diff to be reviewed.

## 3. How the defense is wired

```
+-------------------------------------------+    on PR touching third_party/pynecore
| .github/workflows/pynecore-license-check  | <----------------------------------------+
+-------------------------------------------+                                          |
                       |                                                                |
                       v                                                                |
+-------------------------------------------+                                          |
| tools/pine/verify_pynecore_license.py     | <-- reads --+                            |
+-------------------------------------------+              |                            |
                       |                                   |                            |
                       v                                   |                            |
              sha256 of NOTICE, LICENSE     third_party/pynecore.license_manifest.json |
              + git rev-parse HEAD                         ^                            |
                       |                                   |                            |
                       v                              written by:                       |
              match? exit 0 / exit 1 -------- mismatch ----+   tools/pine/refresh_pynecore_manifest.py
                                                               (requires --confirm-license-reviewed)
```

- **Manifest** (`third_party/pynecore.license_manifest.json`) is the tracked source of truth: pinned
  commit, pinned version, per-file sha256 + byte size. Schema version 1.
- **Verifier** (`tools/pine/verify_pynecore_license.py`) re-computes the SHAs
  from disk + the submodule HEAD and compares. Prints a JSON summary either
  way; exits non-zero on any drift with a verbose error that names every
  defect on the first failure.
- **Workflow** (`.github/workflows/pynecore-license-check.yml`) runs the
  verifier on every PR that touches the submodule, the manifest, the verifier
  itself, or `.gitmodules`, and on every push to `main` / `openbb_tradingview`
  that does the same. The job checks out submodules recursively so the
  on-disk HEAD is real.
- **Refresh tool** (`tools/pine/refresh_pynecore_manifest.py`) rewrites the
  manifest from the current on-disk SHAs. It refuses to run without
  `--confirm-license-reviewed`, making the act of refresh an explicit
  reviewer attestation.

## 4. How to bump PyneCore (4-step procedure)

> **Do not skip steps.** The defense exists because vendor drift is silent by
> default; the only thing protecting us is the discipline of this checklist.

1. **Update the submodule to the new tag.**
   ```bash
   cd third_party/pynecore
   git fetch origin
   git checkout <new-tag>          # e.g. v6.6.0
   cd ../..
   ```

2. **Inspect the upstream NOTICE/LICENSE diff.**
   ```bash
   git -C third_party/pynecore diff <old-sha>..<new-sha> -- NOTICE LICENSE
   ```
   Look for: change of copyright holder, new §4(d) clause, relicense, new
   patent grant terms, new attribution wording.

3. **Confirm no new compliance obligations — OR document them.**
   - If the diff is empty or cosmetic (whitespace, year bump): note that in the
     bump commit message; no further doc work needed.
   - If there is a *substantive* change (new attribution string, new
     obligation, relicense): update this doc's §1 table and PRD §2.2 / §2.6 in
     the **same commit** as the manifest refresh. If the change is a relicense
     away from Apache-2.0, escalate to the maintainer / outside counsel before
     committing — the fallback plan (PRD §10 R4) is to fork at the last
     Apache-2.0 commit, not to accept the new license silently.

4. **Refresh the manifest and commit everything together.**
   ```bash
   python tools/pine/refresh_pynecore_manifest.py --confirm-license-reviewed
   git add third_party/pynecore third_party/pynecore.license_manifest.json \
           docs/designs/openbb-pine/D0-pynecore-pin.md
   # plus any PRD edits from step 3
   git commit -m "chore(pine): bump PyneCore <old> -> <new> + refresh license manifest"
   ```
   Committing the submodule bump and the manifest in the **same commit** is
   mandatory: the CI gate only catches drift between manifest and on-disk; a
   split commit would let the bump land green on the first PR and red on the
   second.

## 5. Failure mode — what CI does, what reviewer does

When `verify_pynecore_license.py` detects drift it prints to stderr:

> `ERROR: PyneCore NOTICE or LICENSE has changed from the pinned manifest.
> Review the upstream change for new compliance obligations or relicensing,
> then update third_party/pynecore.license_manifest.json via
> tools/pine/refresh_pynecore_manifest.py and document the change in
> docs/designs/openbb-pine/D0-pynecore-pin.md.`

…followed by a bullet list of every defect (per-file sha mismatch, per-file
byte_size mismatch, submodule HEAD mismatch) and a JSON summary on stdout.

**Required reviewer action.** Do **not** suppress the failure by editing the
manifest in the same PR without going through §4 step 3. The whole point of
the gate is to force a human to read the upstream NOTICE/LICENSE diff before
the SHAs are refreshed. If the failure looks like a CI infrastructure issue
(submodule not checked out, etc.), re-trigger the workflow — don't bypass it.

## 6. Out of scope for D0

- Runtime integration with PyneCore — see **D2** (`openbb_pine/__init__.py`
  sys.path bridging, `OBBject` wrapping, attribution surfaces).
- The user-visible §4(d) attribution placement — see **PRD §2.6** (four
  surfaces: widget footer, `/pine/health` payload, CLI banner, Python API).
- The wild-corpus crawler and its CI workflow — those are bead `0e9.4.4` /
  `0e9.4.5` respectively.
- Any modification of the submodule's content. D0's posture is *strict pin +
  drift detection*; in-tree patches against PyneCore would require a separate
  design doc and a `CHANGES.md` per PRD §2.2.
