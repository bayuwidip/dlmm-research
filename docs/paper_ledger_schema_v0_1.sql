-- Paper-Ledger Schema v0.1 — USDC-SOL paper simulation (SCHEMA REFERENCE ONLY)
-- safety_phase: READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY
--
-- ⛔ THIS FILE IS A DESIGN REFERENCE ONLY. IT IS NOT EXECUTED BY ANY PIPELINE SCRIPT.
--    See docs/paper_simulation_design_v0_1.md for the plain-language model.
--
-- This DDL defines the COLUMNS of two FUTURE, paper-only tables. Committing this
-- file:
--   - creates NO table (nothing runs this SQL in the current phase),
--   - writes NO row,
--   - writes NO runtime DuckDB,
--   - does NOT touch `future_position_events` (that reserved table stays at count 0),
--   - authorizes NO paper entry, live entry, wallet, private key, signing, swap,
--     LP add/remove, rebalance, or on-chain execution.
--
-- SEPARATION RULE (critical): `paper_positions` and `paper_position_events` are
-- SEPARATE from the reserved `future_position_events` table in
-- scripts/init_runtime_db.py. This schema does not modify, extend, or write
-- `future_position_events`.
--
-- Every row would carry `safety_phase` and an `is_live` guard column that is ALWAYS
-- FALSE in this phase, so this ledger can never be mistaken for a live ledger.
--
-- No wallet. No private key. No signing. No swap. No LP. No rebalance.
-- No live execution. No LIVE_ELIGIBLE_*.

-- ---------------------------------------------------------------------------
-- paper_positions (FUTURE) — one row per hypothetical position.
-- notional is hypothetical USD (default 50); all prices/fees/P&L are SIMULATED.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS paper_positions (
    paper_position_id   TEXT PRIMARY KEY,
    pair_key            TEXT NOT NULL,
    pair_label          TEXT,
    candidate_source    TEXT,
    notional_usd        DOUBLE,              -- hypothetical; default 50, simulation-only
    entry_time          TEXT,                -- ISO-8601 UTC (simulated)
    entry_price         DOUBLE,              -- simulated entry price (quote per base)
    entry_range_low     DOUBLE,              -- LP range lower bound
    entry_range_high    DOUBLE,              -- LP range upper bound
    range_width_pct     DOUBLE,              -- REQUIRES_MANUAL_CALIBRATION (owner sets from real USDC-SOL OHLCV)
    stop_loss_pct       DOUBLE,              -- default 0.05 (5%), owner-decided
    stop_loss_value     DOUBLE,              -- entry_value * (1 - stop_loss_pct); simulated
    entry_fee_velocity  DOUBLE,              -- baseline fee accrual rate at entry (simulated)
    fee_decay_window    TEXT,                -- REQUIRES_MANUAL_CALIBRATION (owner sets from real USDC-SOL OHLCV)
    fee_decay_threshold DOUBLE,              -- REQUIRES_MANUAL_CALIBRATION (owner sets from real USDC-SOL OHLCV)
    max_hold_seconds    BIGINT,              -- always NULL: no time-based max-hold in v0.1
    status              TEXT,                -- DESIGN_ONLY (this phase) | SIMULATED_OPEN | SIMULATED_CLOSED
    exit_time           TEXT,                -- ISO-8601 UTC (simulated); NULL until closed
    exit_price          DOUBLE,              -- simulated; NULL until closed
    exit_reason         TEXT,                -- RANGE_EXIT | STOP_LOSS | FEE_VELOCITY_DECAY | NONE
    simulated_pnl_usd   DOUBLE,              -- hypothetical P&L; never a real balance
    simulated_fees_usd  DOUBLE,              -- hypothetical accrued fees
    is_live             BOOLEAN NOT NULL,    -- guard: ALWAYS FALSE in this phase
    safety_phase        TEXT NOT NULL,       -- exact phase string
    notes               TEXT,
    created_at          TEXT NOT NULL        -- bookkeeping timestamp
);

-- ---------------------------------------------------------------------------
-- paper_position_events (FUTURE) — append-only lifecycle events.
-- SEPARATE from future_position_events. Append-only simulation step / state log.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS paper_position_events (
    paper_event_id      TEXT PRIMARY KEY,
    paper_position_id   TEXT NOT NULL,       -- references paper_positions.paper_position_id
    pair_key            TEXT,
    event_time          TEXT NOT NULL,       -- ISO-8601 UTC (simulated)
    event_type          TEXT NOT NULL,       -- SIM_OPEN | SIM_PRICE_SAMPLE | SIM_FEE_SAMPLE
                                             --   | SIM_EXIT_RANGE | SIM_EXIT_STOP_LOSS
                                             --   | SIM_EXIT_FEE_DECAY | SIM_CLOSE
    price               DOUBLE,              -- simulated price at the event
    in_range            BOOLEAN,             -- simulated price within the LP range?
    fee_velocity        DOUBLE,              -- simulated fee accrual rate at the event
    fee_velocity_ratio  DOUBLE,              -- fee_velocity / entry_fee_velocity (scale-free)
    drawdown_pct        DOUBLE,              -- simulated value drawdown vs entry
    exit_condition_met  TEXT,                -- RANGE_EXIT | STOP_LOSS | FEE_VELOCITY_DECAY | NONE
    event_payload_json  TEXT,               -- free-form JSON for extra simulated detail
    is_live             BOOLEAN NOT NULL,    -- guard: ALWAYS FALSE in this phase
    safety_phase        TEXT NOT NULL,       -- exact phase string
    created_at          TEXT NOT NULL        -- bookkeeping timestamp
);
