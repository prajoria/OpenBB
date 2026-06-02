# Session Notebook Index

Last updated: 2026-02-28

This document lists all notebooks created in this working session, with direct links and a short description of what each notebook is for.

## 1) Ideal Portfolio Proposal
- **Notebook:** [ideal_portfolio_proposal.ipynb](ideal_portfolio_proposal.ipynb)
- **Purpose:** Builds two independent portfolio proposals in one notebook:
  - Proposal A: Full Research-based allocation
  - Proposal B: Fortress (5-pillars) ETF allocation
- **What it includes:**
  - Structured position metadata (ticker, name, pillar/bucket, role, target weight)
  - Validation checks (sum of weights, pillar allocation, asset-type allocation)
  - Exported outputs:
    - `full_research_proposal_weights.csv`
    - `fortress_proposal_weights.csv`
    - `proposal_comparison_all_positions.csv`
- **How to run:**
  - Kernel: Python `.venv_win` (or any env with `pandas`)
  - Run order: Cell 1 (overview) → Cell 2 (data/proposals) → Cell 3 (validation + export)
  - Result files are written to the `Analysis/` folder

## 2) Sector ETF ROI Plan
- **Notebook:** [sector_etf_roi_plan.ipynb](sector_etf_roi_plan.ipynb)
- **Purpose:** Creates a sector ETF shortlist framework with ROI/risk context and ranking logic.
- **What it includes:**
  - Multi-sector ETF candidates
  - Return/risk comparison structure
  - Ranking workflow to support sector rotation or ETF selection planning
- **How to run:**
  - Kernel: Python `.venv_win`
  - Primary packages: `pandas`, `numpy`, `matplotlib` (and `seaborn` if plotting style is used)
  - Run all cells top-to-bottom to regenerate rankings/tables

## 3) Single-Stock Analysis Playbook Template
- **Notebook:** [00. single_stock_analysis_playbook_template.ipynb](00.%20single_stock_analysis_playbook_template.ipynb)
- **Purpose:** Standardized template for end-to-end single-stock research in this repo.
- **What it includes:**
  - Environment/setup assumptions for local OpenBB workflow
  - Structured phase flow from company quality to technicals, valuation, risk, and decisioning
  - Reusable checklist-style process for consistent analysis execution
- **How to run:**
  - Kernel: Python `.venv_win` with local OpenBB packages available
  - Start from the setup cells, then execute phase sections sequentially
  - Save outputs/charts inline per phase for a complete research record

## Quick Resume Checklist
- Open [ideal_portfolio_proposal.ipynb](ideal_portfolio_proposal.ipynb) when you want target allocations and CSV exports.
- Open [sector_etf_roi_plan.ipynb](sector_etf_roi_plan.ipynb) when you want sector-ETF comparisons and ranking refresh.
- Open [00. single_stock_analysis_playbook_template.ipynb](00.%20single_stock_analysis_playbook_template.ipynb) for deep single-name research workflow.

## Notebook Style Checklist (Use Going Forward)
- Use `##` for each major proposal/topic section.
- Use `###` for workflow steps under a proposal (for example: Build, Validate, Export).
- Keep proposal sections strictly sequential (finish Proposal A completely before starting Proposal B).
- Pair each `###` step markdown with its own executable code cell immediately after it.
- Avoid mixing two proposals inside one markdown heading block.
- Keep validation/export logic scoped to the active proposal; add combined comparison only after both proposals are complete.

---

If useful, we can keep this file as a running session log and append future notebooks at the top with date-stamped entries.