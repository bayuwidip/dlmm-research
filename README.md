# DLMM Research

Personal research project for screening Meteora DLMM liquidity pools on Solana
using public read-only API data from `https://dlmm.datapi.meteora.ag`.

This is **not a trading bot**. The long-term autonomous DeFi vision is parked in
`docs/VISION_PARKED.md` and is not active in the current phase.

## Current Phase

**READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY**

| Gate | Status |
|---|---|
| Owner scope gate | green |
| Validation gate | red |
| Max allowed action | PAPER_ONLY |

The project has not completed a paper-test cycle. While the validation gate is
red, every workflow must remain read-only or paper-only, and no row may be
promoted beyond `PAPER_ONLY`.

`PAPER_REVIEW_CANDIDATE` means future paper-simulation review only. It is not a
paper entry, not a paper trade, not an open position, and not live readiness.

## Forbidden Actions

Do not add, enable, or route toward:

- wallet creation, import, connection, or management
- private key, seed phrase, or signing-key handling
- transaction signing or broadcasting
- swaps through any router or DEX
- LP add/remove operations
- rebalances
- live execution
- signal generation
- paper position creation
- writes to `future_position_events`
- threshold, risk-policy, or candidate-status changes without explicit human instruction

The risk policy engine has veto and reporting authority only. It can block or
label risk; it cannot place, sign, send, trade, or create positions.

## Current Pipeline

The read-only pipeline is CI-confirmed and should not be casually rewritten. The
runtime runner executes the core scripts in this order:

```bash
python3 scripts/fetch_meteora_pools.py
python3 scripts/build_watchlist.py
python3 scripts/fetch_ohlcv_top_pairs.py
python3 scripts/classify_strategy.py
python3 scripts/observe_strategy.py
python3 scripts/apply_risk_policy.py
python3 scripts/validate_watchlist.py
```

`scripts/run_readonly_pipeline.py` orchestrates that sequence and can optionally
write run metadata to the local runtime DuckDB:

```bash
python3 scripts/run_readonly_pipeline.py \
  --write-db runtime/dlmm.duckdb \
  --import-observations-db \
  --import-risk-flags \
  --import-risk-decisions-db
```

Optional DB import flags require `--write-db`. The runner does not write
`future_position_events`, does not connect to a wallet, and does not execute
anything on-chain.

## Runtime DB And Reports

Runtime storage is local VPS bookkeeping only:

- DB path: `runtime/dlmm.duckdb`
- `runtime/` is git-ignored and should not be committed
- GitHub Actions remains artifact-only
- generated runtime reports under `reports/runtime/` and `reports/argus/` are local artifacts

Current runtime tables include:

- `pipeline_runs`
- `pipeline_steps`
- `strategy_observations`
- `risk_flags`
- `risk_decisions`
- `future_position_events` as reserved/display-only schema

The current safety invariant is that `future_position_events` remains `0`.

Read-only reporting and diagnostics currently include strategy classification,
observation summaries, risk decisions, runtime risk dashboard reporting, ARGUS
proposal reports, fee-pool diagnostics, pair stability diagnostics, candidate
evidence packs, and the manual council review matrix. These reports support
human review only; they do not approve paper entries or live action.

## Scheduled Dry-Run Docs

Safe scheduling guidance is documentation-only in
`docs/scheduled_runner_cron_dry_run.md`. It provides cron and user-systemd
examples for this dry-run command:

```bash
python3 scripts/run_scheduled_readonly_diagnostics.py \
  --dry-run \
  --db-path runtime/dlmm.duckdb
```

The guide does not install, enable, or start any schedule automatically. Any
scheduled check must keep `--dry-run`, use the documented lock/log paths, and
verify that no `future_position_events` writes occur.

## Development Loop

Primary project context lives in:

- `CLAUDE.md` — authoritative rules, phase, forbidden actions, and file policy
- `docs/project_checkpoint.md` — current checkpoint and next task
- `docs/task_queue.md` — owner-curated task queue
- `docs/decision_log.md` — append-only project decisions

Every agent session must read `CLAUDE.md` before making changes.

The normal safe loop is:

```bash
python3 -m unittest discover tests
python3 scripts/validate_watchlist.py
```

Claude Code is the normal implementation agent. Codex may be used as a fallback.
If Codex cannot create branches, commits, pushes, or PRs because `.git` metadata
is read-only in its sandbox, the change should be left validated in the working
tree. The host-side wrapper then handles the Git operations:

```bash
python3 scripts/commit_dev_loop_output.py --task-id update-readme-project-status
```

The wrapper creates the feature branch on the host, stages allowed files only,
commits, pushes, and opens a PR. It refuses generated runtime/report artifacts
unless explicitly allowed.

RTK is optional. It may be used for exploration and token saving on noisy diffs,
large logs, or broad search results, but repository tasks, tests, validation, and
agent instructions must not depend on RTK being installed. Final validation
evidence should come from the original project commands above.

## Next Safe Milestones

Current safe next steps remain diagnostic and review-oriented:

- keep the README, checkpoint, and task queue aligned with the actual phase
- run scheduled diagnostics in dry-run mode before any operational schedule
- continue manual council review of stable candidates
- complete token, pool, OHLCV, liquidity, volatility, and fee-tier reviews
- design paper-simulation accounting only after explicit human approval
- keep Telegram/control-room and live execution work parked until phase gates change

None of these milestones authorizes wallet use, signing, swaps, LP operations,
rebalances, paper positions, `future_position_events` writes, or live execution.

## Validation

For repository validation, run:

```bash
python3 -m unittest discover tests
python3 scripts/validate_watchlist.py
```

---

Not financial advice. Research only. No live execution in this phase.
