# DLMM Project Checkpoint

> Single short checkpoint for humans, Claude Code, and future AI sessions.
> Read this first so we do not repeat context or accidentally jump to live execution.

---

## 1. Current Phase

**READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY**

---

## 2. Current Hard Safety Boundary

- No wallet
- No private key
- No signing
- No swap
- No LP add/remove
- No rebalance
- No live execution
- No `LIVE_ELIGIBLE_*`

---

## 3. Latest Merged Milestones

- Strategy Classification v0.2
- Paper Observation Readiness v0.1
- GitHub Actions now runs the observation pipeline
- Pull request checks are enabled through the `pull_request` trigger
- Observation artifacts are uploaded in CI
- Target Architecture merged (`docs/target_architecture.md`)
- Read-only Runtime Orchestrator merged (`scripts/run_readonly_pipeline.py`)
- Optional DB write support for the runtime runner merged (`--write-db`)
- Runtime DuckDB schema initializer merged (`scripts/init_runtime_db.py`)
- Runtime DuckDB inspector merged (`scripts/inspect_runtime_db.py`)
- Run summary DuckDB importer merged (`scripts/import_run_summary_to_db.py`)
- Strategy observations DuckDB importer merged (`scripts/import_strategy_observations_to_db.py`)

---

## 4. Current Pipeline

```
fetch_meteora_pools.py
  → build_watchlist.py
  → fetch_ohlcv_top_pairs.py
  → classify_strategy.py
  → observe_strategy.py
  → validate_watchlist.py
```

---

## 5. Important Scripts

**Pipeline (read-only screening):**
- `scripts/fetch_meteora_pools.py`
- `scripts/build_watchlist.py`
- `scripts/fetch_ohlcv_top_pairs.py`
- `scripts/classify_strategy.py`
- `scripts/observe_strategy.py`
- `scripts/validate_watchlist.py`

**Runtime / storage (local VPS, read-only):**
- `scripts/run_readonly_pipeline.py` — runtime orchestrator (sequential runner, logs, summaries, lock file, optional `--write-db`)
- `scripts/init_runtime_db.py` — initialize the runtime DuckDB schema
- `scripts/inspect_runtime_db.py` — audit/inspect runtime DB state
- `scripts/import_run_summary_to_db.py` — import run summary into DuckDB
- `scripts/import_strategy_observations_to_db.py` — import strategy observations into DuckDB

---

## 6. Runtime / Storage Flow

Current manual/runtime storage flow (local VPS, read-only):

```
run_readonly_pipeline.py --write-db runtime/dlmm.duckdb
  → pipeline_runs
  → pipeline_steps

import_strategy_observations_to_db.py
  → strategy_observations
  → optional risk_flags

inspect_runtime_db.py
  → audit database state
```

This flow records history only. It performs no execution, holds no wallet/keys, and does
not authorize any on-chain action.

---

## 7. Storage Policy

- GitHub Actions remains **artifact-only**.
- `runtime/` is **local and git-ignored** (not committed).
- DuckDB is **local VPS runtime storage** only.
- **No automatic commit-back** of runtime history to the repo.
- **No secrets, wallet, private key, or execution data** in DuckDB.
- Current DB writes are limited to: runtime metadata, pipeline steps, strategy
  observations, and optional risk flags.

---

## 8. Important Data / Report Outputs

**Data:**
- `data/pools_watchlist.csv`
- `data/pair_watchlist.csv`
- `data/ohlcv_top_pairs.csv`
- `data/strategy_classification_v2.csv`
- `data/observations/strategy_observations.jsonl`

**Reports:**
- `reports/latest_pool_report.md`
- `reports/ohlcv_report.md`
- `reports/strategy_classification_v2.md`
- `reports/observations/observation_summary.md`
- `reports/observations/observation_summary.csv`

---

## 9. Validation Commands

```bash
python3 -m unittest tests/test_observe_strategy.py
python3 -m unittest tests/test_classify_strategy.py
python3 scripts/validate_watchlist.py
```

---

## 10. VPS Status

- Tencent Lighthouse 2C2G
- Swap 2GB enabled
- Claude Code installed
- RTK installed and active
- GitHub CLI installed and authenticated
- Tailscale installed on VPS, but laptop-side access/hardening is **not complete yet**
- **Do not close public SSH** until Tailscale SSH from laptop has been proven

---

## 11. Git Workflow

- Work on feature branches
- Use PRs
- Let GitHub Actions checks pass before merge
- Use squash merge
- Do not commit generated runtime history automatically yet unless explicitly approved

---

## 12. Current Observation Meaning

Observation readiness means **stable enough for future paper-simulation consideration only**.

- It does **not** mean paper-trade ready.
- It does **not** mean live ready.
- It does **not** authorize LP, swap, wallet, signing, or execution.

Runtime/storage safety clarifications:

- **Observation import does not mean paper trading.**
- **DB write does not mean execution.**
- **The runner does not authorize live execution.**
- No wallet / private key / signing / swap / LP / rebalance / live execution.

---

## 13. Next Planned Work

**Next decision:**
Decide whether to integrate observation import into the runner as an optional flag, or keep
observation import manual until scheduler design is settled.

**Recommended next coding task (only after this checkpoint update is merged):**
Add an optional runner flag — `--import-observations-db` or equivalent — so
`run_readonly_pipeline.py` can optionally trigger the strategy-observations DuckDB import.

**Still open:**
- Set up a VPS scheduled runner later — not GitHub Actions as runtime
- Add Telegram notification/control room later, read-only first
- Complete Tailscale laptop setup before closing public SSH

---

## 14. Operating Rule for Coding Agents

Before coding, agents must:

1. Read this checkpoint
2. Check `git status`
3. Confirm the current branch
4. Preserve the safety boundary

---

*Not financial advice. Research only. No live execution in this phase.*
