**NEXT TASK ->** scheduled-readonly-runner — build a safe scheduled read-only diagnostics runner for VPS automation. Read-only only; no wallet, signing, swap, LP add/remove, rebalance, live execution, signal generation, paper position creation, or `future_position_events` writes.

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

Merged earlier in this storage track (PRs #12 to #16):

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
  continue-on-error behavior is unchanged.
- **#16 — Checkpoint updated for the risk policy runner integration.**

Newly merged (this update — PRs #17 and #18):

- **#17 — Risk decisions DuckDB importer.** Added `scripts/import_risk_decisions_to_db.py`
  (+ `tests/test_import_risk_decisions_to_db.py`). A standalone, offline import/bookkeeping
  tool that imports an existing `data/risk_decisions.csv` (produced by
  `apply_risk_policy.py`) into a new `risk_decisions` table in the runtime DuckDB.
  - The runtime DuckDB schema now defines a `risk_decisions` table, and
    `inspect_runtime_db.py` reports its row count.
  - The importer validates required columns, the decision/action/`max_allowed_action`
    enums, the exact `safety_phase`, and forbidden execution-authorization semantics before
    writing anything.
  - Supports `--dry-run` (validates + prints counts, writes nothing) and `--upsert`
    (idempotent replace by deterministic `risk_decision_id`). A default (non-upsert)
    duplicate import **fails** rather than duplicating rows.
  - Writes **only** to `risk_decisions`. It never writes `pipeline_runs`,
    `pipeline_steps`, `strategy_observations`, `risk_flags`, or `future_position_events`.
- **#18 — Optional risk decisions DB import wired into the runner.**
  `run_readonly_pipeline.py` gained `--import-risk-decisions-db` (with
  `--risk-decisions-csv`, default `data/risk_decisions.csv`).
  - `--import-risk-decisions-db` requires `--write-db`; default runner behavior is
    unchanged.
  - Dry-run writes no DB and only shows the planned risk decisions import.
  - The runner imports risk decisions **after** the pipeline produces
    `data/risk_decisions.csv` (post-pipeline existence check; the runner never creates the
    CSV), using **upsert** so repeated imports do not fail on duplicates.
  - A risk decisions import failure makes the runner exit non-zero (it never converts a
    failed pipeline into a pass). Observation DB import and `risk_flags` import behavior are
    unchanged. No `future_position_events` write is introduced.

Full runner command (all optional imports enabled):

```bash
python3 scripts/run_readonly_pipeline.py \
  --write-db runtime/dlmm.duckdb \
  --import-observations-db \
  --import-risk-flags \
  --import-risk-decisions-db
```

Newly merged (this update — PRs #19 to #25):

- **#19 — Checkpoint updated for risk decisions DB import.**
- **#20 — Runtime risk dashboard report builder.** Read-only DuckDB history dashboard
  (no execution authority).
- **#21 — Hermes proposal-only design.** Design-only document for a proposal-only,
  read-only historical reviewer.
- **#22 — ARGUS proposal-only reviewer.** The reviewer (renamed from Hermes — see §3c).
- **#23 — ARGUS proposal report builder.**
- **#24 — Fee pool blocker diagnostics** (`NO_ELIGIBLE_FEE_POOL`).
- **#25 — Pair stability diagnostics.**

See §3b–§3h below for the detailed 2026-06-30 checkpoint state.

---

## 3b. ARGUS Rename and Role (2026-06-30)

- The internal working name **Hermes** was renamed to **ARGUS** to avoid confusion with
  external Hermes agent projects.
- **ARGUS is a proposal-only historical reviewer.**
- ARGUS may **observe, summarize, and propose** to human / council.
- ARGUS has:
  - **no execution authority**
  - **no trading authority**
  - **no DB write authority**
  - **no code-edit authority**
  - **no risk-policy authority**

(The legacy design document `docs/argus_reviewer_design.md` still carries the historical
"Hermes" name in places; the binding name going forward is ARGUS.)

---

## 3c. Current Runtime Evidence (2026-06-30)

Runtime DB path: `runtime/dlmm.duckdb`

Latest confirmed runtime state:

| Table | Count |
|---|---|
| `pipeline_runs` | 5 |
| `pipeline_steps` | 35 |
| `strategy_observations` | 1441 |
| `risk_flags` | 2897 |
| `risk_decisions` | 213 |
| `future_position_events` | **0** |

- All latest runtime runs were **SUCCESS**.
- The safety boundary holds because **`future_position_events` remains 0**.

---

## 3d. ARGUS 5-Run Report (2026-06-30)

- Evidence sufficiency moved from **INSUFFICIENT** to **SUFFICIENT**.
- **SUFFICIENT means sufficient for risk-pattern / diagnostic review only.**
- It does **NOT** authorize paper simulation, paper entries, paper trades, open positions,
  wallet usage, signing, swaps, LP actions, rebalances, or live execution.
- ARGUS proposals after 5 runs (proposals to human / council only):
  - `RECURRING_BLOCKER_REVIEW`
  - `CLASSIFICATION_CHURN_REVIEW`
  - `DATA_QUALITY_REVIEW`
  - `SAFETY_BOUNDARY_REVIEW`
- **No automatic action authorized.**

---

## 3e. NO_ELIGIBLE_FEE_POOL Diagnostics (2026-06-30)

Summary:

- pipeline run count: 5
- `future_position_events` count: 0
- total `NO_ELIGIBLE_FEE_POOL` flags: 286
- total `NO_ELIGIBLE_FEE_POOL` decisions: 44
- affected pair count: 70

Interpretation:

- The blocker mostly affects `NOT_EVALUATED` / `BLOCKED` / `REJECT` / `NONE` pairs.
- It does **not** currently appear to be blocking the strongest `CORE` / `CLEAN` review
  candidates.
- It looks more like a useful filter for noisy / low-quality / unready pairs than a reason
  to loosen rules.

Council decision:

- Do **not** loosen fee-pool thresholds.
- Do **not** change risk policy.
- Do **not** unblock `NO_ELIGIBLE_FEE_POOL` pairs.
- Treat this blocker as **valid** unless manual data-quality review proves otherwise.

---

## 3f. Pair Stability Diagnostics (2026-06-30)

Summary:

- pipeline run count: 5
- distinct runs in observation history: 7
- `future_position_events` count: 0
- total observation rows: 1441
- total risk-decision rows: 213
- total pairs analysed: 250
- evidence sufficiency: **SUFFICIENT**

Stability labels:

| Label | Count |
|---|---|
| `STABLE_REVIEW_CANDIDATE` | 6 |
| `STABLE_OBSERVE_ONLY` | 149 |
| `CHURNING_CLASS` | 9 |
| `MOSTLY_BLOCKED` | 43 |
| `ONE_OFF` | 43 |

The diagnostic remains **read-only** and does **not** authorize paper entries, live entries,
wallet use, swaps, LP actions, rebalances, threshold changes, risk-policy changes, or
candidate-status changes.

---

## 3g. Stable Review Candidate Shortlist (2026-06-30)

The 6 stable review candidates:

- HYPE-SOL
- HYPE-USDC
- JUP-SOL
- TRUMP-USDC
- USDC-SOL
- USDC-cbBTC

Observed common pattern across all six:

- `observation_count`: 7
- `distinct_run_count`: 7
- `strategy_class`: `CORE`
- `lane`: `CLEAN`
- `strategy_class_change_count`: 0
- `lane_change_count`: 0
- `latest_risk_decision`: `PAPER_REVIEW_CANDIDATE`
- `latest_max_allowed_action`: `FUTURE_PAPER_SIMULATION_REVIEW`
- `blocked_count`: 0

**Important caveat:** `paper_review_candidate_count` is still only **1** for each pair.
Therefore they are stable `CORE` / `CLEAN` candidates, but **not** automatically ready for
paper simulation.

Correct status:

- **human / council may review for future paper-simulation design consideration**

Incorrect status (these do NOT apply):

- not paper entry
- not paper trade
- not open position
- not live
- not approved

### Suggested candidate review priority (human / council review only)

1. **USDC-SOL** — benchmark pair
2. **JUP-SOL** — Solana ecosystem candidate
3. **USDC-cbBTC** — wrapped / bridged BTC / data-source review needed
4. **HYPE-USDC** — token / pool validation needed
5. **HYPE-SOL** — token / pool validation needed
6. **TRUMP-USDC** — highest narrative / meme / political-risk sensitivity

This priority is for human / council review only.

---

## 3h. Current Council Decision (2026-06-30)

- Do **not** go live.
- Do **not** create paper positions.
- Do **not** write `future_position_events`.
- Do **not** change risk policy.
- Do **not** change thresholds.
- Do **not** change candidate statuses.
- Do **not** loosen `NO_ELIGIBLE_FEE_POOL`.
- **Continue diagnostic work.**
- **Next best task:** Manual Council Review Matrix for the 6 stable review candidates
  (see §3i).

---

## 3i. Checkpoint: Candidate Evidence Pack Completed (2026-06-30)

Latest merged features:

- Candidate Deep Review v0.2
- Candidate Evidence Pack v0.1

Diagnostic summary:

- 6 stable review candidates
- pipeline run count: 5
- distinct observation run count: 7
- `future_position_events`: **0**
- evidence sufficiency: **SUFFICIENT**
- all 6 candidates are `CORE` / `CLEAN`
- all 6 candidates have `observation_count = 7`
- all 6 candidates have `distinct_run_count = 7`
- all 6 candidates have zero runtime risk flags and zero blockers
- all 6 candidates have `token_identity_status = NEEDS_MANUAL_REVIEW`
- all 6 candidates have `pool_identity_status = NEEDS_MANUAL_REVIEW`

Candidate evidence verdicts:

| Candidate | Verdict |
|---|---|
| USDC-SOL | `REVIEW_ONLY_PASS` |
| JUP-SOL | `NEEDS_MORE_DATA` |
| USDC-cbBTC | `NEEDS_MORE_DATA` |
| HYPE-USDC | `NEEDS_MORE_DATA` |
| HYPE-SOL | `NEEDS_MORE_DATA` |
| TRUMP-USDC | `NEEDS_MORE_DATA` |

Safety interpretation:

- `REVIEW_ONLY_PASS` means **human/council may review for future paper-simulation design
  consideration**.
- This does **not** authorize paper simulation.
- This does **not** authorize paper entry, paper trade, open position, signal, wallet use,
  signing, swap, LP add/remove, rebalance, or live execution.
- No `future_position_events` writes are allowed.
- The project remains diagnostic-only.

Next recommended phase:

- Manual Council Review Matrix
- Token/pool identity review
- Pool legitimacy/depth/fee-tier/bin review
- OHLCV continuity/freshness review
- Liquidity/volume/volatility manual review
- Only after explicit council approval may a future paper-simulation design task be
  proposed.

Current decision:

- Do **not** build paper engine yet.
- Do **not** create paper positions.
- Do **not** change thresholds.
- Do **not** change risk policy.
- Do **not** change candidate status.
- End diagnostic feature batch.

---

## 3j. Manual Council Review Matrix Merged (2026-07-01)

The **Manual Council Review Matrix** milestone is complete and merged (PR #32,
`manual-council-review-matrix`).

- `scripts/build_manual_council_review_matrix.py` and its tests
  (`tests/test_build_manual_council_review_matrix.py`) are merged.
- Running the script produces `reports/runtime/manual_council_review_matrix.md` and
  `reports/runtime/manual_council_review_matrix.csv`. These are **local generated
  artifacts** under `reports/runtime/` and are **not committed** (see §7 cleanup rule).
- Every cell in the matrix starts as `PENDING_MANUAL_REVIEW`.
- The report is **read-only**: it changes **no candidate status** and does **not** touch
  `future_position_events` (which remains **0**).

**Filling in the manual answers is a human task.** Neither this report nor any script in the
pipeline answers the review questions automatically — the matrix only lays out the
`PENDING_MANUAL_REVIEW` cells for the human / council to complete. No script promotes,
approves, or resolves any cell on its own.

The script has been wired into the runtime runner as an optional post-pipeline step
(PR #35, `wire-matrix-into-pipeline`). The next queued task is now
`scheduled-readonly-runner`, see `docs/task_queue.md`.

---

## 4. Current Pipeline

Core pipeline (always runs, in order):

```
1. fetch_meteora_pools.py
2. build_watchlist.py
3. fetch_ohlcv_top_pairs.py
4. classify_strategy.py
5. observe_strategy.py
6. apply_risk_policy.py
7. validate_watchlist.py
```

Optional DB-import steps (only when the matching flags are passed, and all require
`--write-db`; they run after the core pipeline, never inside it):

```
8.  run summary DB import        (--write-db)
9.  observations DB import       (--import-observations-db)
10. risk_flags import            (--import-risk-flags, with observations import)
11. risk_decisions import        (--import-risk-decisions-db)
```

`validate_watchlist.py` remains the final validator. `apply_risk_policy.py` runs after
observation and before validation (the validator now validates `data/risk_decisions.csv`, so
the risk step must produce it first). A risk policy failure fails the runner; OHLCV
continue-on-error behavior is unchanged. Any optional import failure also makes the runner
exit non-zero.

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
- `scripts/import_risk_decisions_to_db.py` — import risk decisions into DuckDB (`risk_decisions` only; offline import, `--dry-run`/`--upsert`)

---

## 6. Runtime / Storage Flow

Current manual/runtime storage flow (local VPS, read-only):

```
run_readonly_pipeline.py --write-db runtime/dlmm.duckdb
  → pipeline_runs
  → pipeline_steps
  → (optional --import-observations-db)   strategy_observations
  → (optional --import-risk-flags)        risk_flags
  → (optional --import-risk-decisions-db) risk_decisions

import_strategy_observations_to_db.py
  → strategy_observations
  → optional risk_flags

import_risk_decisions_to_db.py
  → risk_decisions

inspect_runtime_db.py
  → audit database state (now includes the risk_decisions count)
```

Runtime DuckDB tables:

- `runtime_schema_meta`
- `pipeline_runs`
- `pipeline_steps`
- `strategy_observations`
- `risk_flags`
- `risk_decisions`
- `future_position_events` — **reserved / display-only** (never written in this phase)

Runtime / storage milestone status (DuckDB, local VPS):

- runtime runner — **exists**
- DuckDB schema — **exists**
- run summary import — **exists**
- strategy observation import — **exists**
- optional risk flag import — **exists**
- risk decisions DuckDB import — **exists** (standalone importer #17 + optional runner flag
  #18; writes only `risk_decisions`, upsert in the runner)
- `inspect_runtime_db` — **exists** (reports the `risk_decisions` count)
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
- Current DB writes are limited to: runtime metadata, pipeline runs/steps, strategy
  observations, optional risk flags, and risk decisions.
- Risk decisions (`data/risk_decisions.csv`) are imported into the `risk_decisions` table
  via the standalone importer or the optional `--import-risk-decisions-db` runner flag.
- `future_position_events` remains schema-only/reserved and must not be written by the
  current pipeline.

**Cleanup rule (generated artifacts):**

- Generated outputs should usually **not** be committed unless explicitly approved.
- Runtime diagnostic outputs under `reports/runtime/` and ARGUS outputs under
  `reports/argus/` are **local generated artifacts** and should be **removed before code
  commits** unless explicitly approved.

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

**Risk decisions storage status — imported (read-only):**

- `scripts/import_risk_decisions_to_db.py` imports the validated CSV into the
  `risk_decisions` table; the runner can do this automatically via
  `--import-risk-decisions-db` (requires `--write-db`, upsert). The importer re-validates
  columns/enums/`safety_phase`/forbidden tokens before writing and writes only to
  `risk_decisions`. This is read-only bookkeeping — it confers no execution authority and
  never writes `future_position_events`.

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

These are the recommended next milestones. Each preserves the §2 safety boundary. None of
them authorizes paper entry or live execution.

**Done (PRs #17–#25):**
- ~~Risk decisions DuckDB importer~~ — merged (`scripts/import_risk_decisions_to_db.py`, #17).
- ~~Runtime runner optional risk DB import~~ — merged (`--import-risk-decisions-db`, #18).
- ~~Runtime / Risk Dashboard Report~~ — merged (#20, read-only DuckDB history dashboard).
- ~~ARGUS proposal-only reviewer + report builder~~ — merged (#21–#23).
- ~~NO_ELIGIBLE_FEE_POOL fee-pool blocker diagnostics~~ — merged (#24).
- ~~Pair stability diagnostics~~ — merged (#25).

**Done — Candidate Deep Review Report + Candidate Evidence Pack**

Candidate Deep Review v0.2 and Candidate Evidence Pack v0.1 are merged. See §3i for the
completed diagnostic summary and verdicts. The Manual Council Review Matrix is DONE.
The active next task is the **scheduled-readonly-runner** automation task.

**Earlier milestone (already merged) — Runtime / Risk Dashboard Report (#20)**

A **read-only** dashboard that summarizes the DuckDB history (local-only, no execution
authority). It reports:
- pipeline run success/failure
- pipeline step failures
- latest observation counts
- risk flag counts
- risk decision distribution
- repeated `PAPER_REVIEW_CANDIDATE` candidates
- repeated `BLOCKED` / `REJECTED` reasons
- `CORE` / `TACTICAL` stability over time
- `future_position_events` count must remain **0** (asserted, display-only)

**Before any paper-simulation implementation, the project still needs:**
- historical dashboard / reporting (the milestone above)
- paper accounting design
- position lifecycle design
- risk limits design
- council / human approval rule

Each of these is design/reporting only and must not authorize paper entry or live execution.
Later, a paper-simulation design document and a Telegram control-room design document (both
design-only; read-only observer first) remain on the roadmap.

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

---

## Checkpoint: Task Queue Synced After Matrix Pipeline Wiring

Status: documentation sync after PR #35.

Completed and merged:
- manual-council-review-matrix
- wire-matrix-into-pipeline

Current task queue state:
- DONE: manual-council-review-matrix
- DONE: wire-matrix-into-pipeline
- READY: scheduled-readonly-runner

Current next task:
- scheduled-readonly-runner

Reason:
The project objective is automation-first. The next safe automation step is a scheduled read-only diagnostics runner for VPS automation. This reduces manual copy-paste without introducing paper positions, wallet usage, signing, swaps, LP add/remove, rebalance, or live execution.

Scope of next task:
- read-only diagnostics only
- local lock file to prevent overlapping runs
- local logs
- dry-run mode
- future_position_events count check
- no wallet
- no private key
- no seed phrase
- no signing
- no swap
- no LP add/remove
- no rebalance
- no live execution
- no signal generation
- no paper position creation
- no future_position_events writes
- no threshold changes
- no risk-policy changes
- no candidate-status changes

Important:
scheduled-readonly-runner is not a paper engine and not a live bot. It is only an automation wrapper for read-only diagnostics.
