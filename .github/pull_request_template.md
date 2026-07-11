# Pull Request OpenBB

Please go to the `Preview` tab and select the appropriate PR sub-template:

* [OpenBB Platform](?expand=1&template=platform_pull_request_template.md)
* [OpenBB Platform CLI](?expand=1&template=terminal_pull_request_template.md)
* [OpenBB Developers](?expand=1&template=obb_developer_pull_request_template.md)

---

### 🎯 Portfolio Intelligence Engine contributors

If your branch name starts with **`feat/pi-`** you are working on the
[Portfolio Intelligence Engine program](../blob/portfolio/docs/Specs/Portfolio-Intelligence-Engine-Execution-Plan.md#2a-branching-model--worktree-contract-non-negotiable).

- **Base branch:** `portfolio` — **never** `develop` or `main`.
- The single `portfolio` → `develop` integration merge happens only once,
  at the M4 gate. CI (`Portfolio-Intel Base-Branch Guard`) will fail any
  `feat/pi-*` PR that targets `develop` or `main`.
- Cite the bead ID in the PR title, e.g. `feat(portfolio-intel): X (bd-qy83.1.4)`.

