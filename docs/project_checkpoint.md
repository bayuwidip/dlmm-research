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
- No signal generation
- No paper position creation
- No `future_position_events` writes

The Risk Policy Engine has **veto / reporting authority only — no execution authority**.
It can stop and shrink; it can never place, sign, or send anything.

---

## 3. Latest Merged Milestones

Earlier milestones (through #11):

- Strategy Classification v0.2 (#1-related)
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
- Project checkpoint updated for runtime storage (#11)

Newly merged (this update — PRs #12 to #15):

- **#12 — Optional observation DB import to runner.** `run_readonly_pipeline.py` can
  optionally import strategy observations into DuckDB. `--import-observations-db` requires
  `--write-db`; optional `--import-risk-flags` imports risk flags. It does **not** write
  `future_position_events`. Default runner behavior is unchanged.
- **#13 — Risk policy engine skeleton.** Added `scripts/apply_risk_policy.py` (+
  `tests/test_apply_risk_policy.py`). Read-only / veto-only / reporting-only. Consumes
  `data/strategy_classification_v2.csv` and produces explainable risk decisions
  (`BLOCKED`, `OBSERVE_ONLY`, `PAPER_REVIEW_CANDIDATE`, `NOT_EVALUATED`, `REJECTED`).
  Generated outputs: `data/risk_decisions.csv` + `reports/risk_decisions.md`.
  `PAPER_REVIEW_CANDIDATE` means **future paper-simulation review only** — it does not
  authorize paper entry, live entry, LP actions, swaps, rebalances, wallet use, signing, or
  execution.
- **#14 — Risk decisions validation.** `scripts/validate_watchlist.py` now validates
  `data/risk_decisions.csv` (+ `tests/test_validate_risk_decisions.py`). Checks required
  columns, enums, `safety_phase`, `max_allowed_action`, and forbidden
  `LIVE_ELIGIBLE_*` / entry / execution semantics. Risk decisions now have a validator gate.
- **#15 — Risk policy step wired into the runtime runner.** `run_readonly_pipeline.py`
  now runs `scripts/apply_risk_policy.py` after `observe_strategy.py` and before
  `validate_watchlist.py`. `apply_risk_policy` failure fails the runner; OHLCV
  continue-on-error behavior is unchanged. No `risk_decisions` DuckDB import yet; no
  `future_position_events` write.

---

## 4. Current Pipeline

```
fetch_meteora_pools.py
  → build_watchlist.py
  → fetch_ohlcv_top_pairs.py
  → classify_strategy.py
  → observe_strategy.py
  → apply_risk_policy.py
  → validate_watchlist.py
```

`validate_watchlist.py` remains the final validator. `apply_risk_policy.py` runs after
observation and before validation (the validator now validates `data/risk_decisions.csv`, so
the risk step must produce it first). A risk policy failure fails the runner; OHLCV
continue-on-error behavior is unchanged.

---

## 5. Important Scripts

**Pipeline (read-only screening):**
- `scripts/fetch_meteora_pools.py`
- `scripts/build_watchlist.py`
- `scripts/fetch_ohlcv_top_pairs.py`
- `scripts/classify_strategy.py`
- `scripts/observe_strategy.py`
- `scripts/apply_risk_policy.py` — Risk Policy Engine skeleton v0.1 (read-only, veto/reporting only)
- `scripts/validate_watchlist.py` — final validator (now also validates `data/risk_decisions.csv`)

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
  → (optional --import-observations-db) strategy_observations
  → (optional --import-risk-flags)     risk_flags

import_strategy_observations_to_db.py
  → strategy_observations
  → optional risk_flags

inspect_runtime_db.py
  → audit database state
```

Runtime / storage milestone status (DuckDB, local VPS):

- runtime runner — **exists**
- DuckDB schema — **exists**
- run summary import — **exists**
- strategy observation import — **exists**
- optional risk flag import — **exists**
- `inspect_runtime_db` — **exists**
- risk decisions DuckDB import — **NOT yet** (`data/risk_decisions.csv` is generated and
  validated, but not imported to DuckDB)
- `future_position_events` — **schema-only / reserved**; the current pipeline must **not**
  write it

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
- Risk decisions (`data/risk_decisions.csv`) are **not** imported to DuckDB yet.
- `future_position_events` remains schema-only/reserved and must not be written by the
  current pipeline.

---

## 8. Important Data / Report Outputs

**Data:**
- `data/pools_watchlist.csv`
- `data/pair_watchlist.csv`
- `data/ohlcv_top_pairs.csv`
- `data/strategy_classification_v2.csv`
- `data/observations/strategy_observations.jsonl`
- `data/risk_decisions.csv` — risk policy engine output (read-only, veto/reporting only)

**Reports:**
- `reports/latest_pool_report.md`
- `reports/ohlcv_report.md`
- `reports/strategy_classification_v2.md`
- `reports/observations/observation_summary.md`
- `reports/observations/observation_summary.csv`
- `reports/risk_decisions.md` — explainable risk decisions report

---

## 8b. Risk Policy + Validation Status

**Risk policy milestone — implemented (skeleton v0.1):**

- `scripts/apply_risk_policy.py` consumes `data/strategy_classification_v2.csv` and emits
  explainable risk decisions only.
- Allowed `risk_decision` enum: `BLOCKED`, `OBSERVE_ONLY`, `PAPER_REVIEW_CANDIDATE`,
  `NOT_EVALUATED`, `REJECTED`.
- `PAPER_REVIEW_CANDIDATE` = **future paper-simulation review only**. It is **not** a paper
  entry, **not** a paper trade, and **not** live readiness.
- Authority boundary: the risk engine has **veto / reporting authority only — no execution
  authority**. It does not create positions, generate signals, call a wallet, sign, swap,
  add/remove LP, rebalance, or execute anything, and it does not write to DuckDB.

**Risk validation status — gated:**

- `scripts/validate_watchlist.py` now validates `data/risk_decisions.csv` via
  `validate_risk_decisions()`.
- Checks: required columns, decision/action/max enums, exact `safety_phase`,
  `max_allowed_action` consistency per decision, hard-block flags, and forbidden
  `LIVE_ELIGIBLE_*` / entry / execution tokens in any cell.
- If `apply_risk_policy.py` exists but `data/risk_decisions.csv` is missing, validation
  **fails** (the output is required once the layer exists).

---

## 9. Validation Commands

```bash
python3 -m unittest tests/test_observe_strategy.py
python3 -m unittest tests/test_classify_strategy.py
python3 -m unittest tests/test_apply_risk_policy.py
python3 -m unittest tests/test_validate_risk_decisions.py
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

**Current readiness statement:** the system is ready for **continued read-only observation**
and **future paper-simulation review candidate tracking** (via the risk policy engine's
`PAPER_REVIEW_CANDIDATE`). It is **not** ready for paper entry and **not** ready for live.

- It does **not** mean paper-trade ready.
- It does **not** mean live ready.
- It does **not** authorize LP, swap, wallet, signing, or execution.

Runtime/storage + risk safety clarifications:

- **Observation import does not mean paper trading.**
- **DB write does not mean execution.**
- **The runner does not authorize live execution.**
- **A `PAPER_REVIEW_CANDIDATE` is a future paper-simulation review candidate only — not a
  paper entry, not a paper trade, not live readiness.**
- **The risk engine has veto / reporting authority only — no execution authority.**
- No wallet / private key / signing / swap / LP / rebalance / live execution.
- No signal generation, no paper position creation, no `future_position_events` writes.

---

## 13. Next Recommended Milestones

These are the recommended next milestones, in dependency order. Each preserves the §2 safety
boundary. None of them authorizes paper entry or live execution.

**A. Risk decisions DuckDB importer**
- Import `data/risk_decisions.csv` into a new/defined `risk_decisions` table.
- Read-only metadata only.
- No `future_position_events`.

**B. Runtime runner optional risk DB import**
- Only after the risk decisions importer (A) exists.
- Optional flag only; requires `--write-db`.
- Default runner behavior stays unchanged.

**C. Observation dashboard / reporting layer**
- Summarize historical runs, observations, and risk decisions.
- Local-only, read-only.

**D. Paper simulation design document**
- Design only — no implementation yet.
- Must define paper accounting before any paper engine is built.

**E. Telegram control room design document**
- Design only.
- No commands that alter positions or execution; read-only observer first.

**Still open (operational):**
- Set up a VPS scheduled runner later — not GitHub Actions as runtime
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
