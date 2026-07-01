# Paper Simulation Design v0.1 — USDC-SOL (DESIGN + SCHEMA ONLY)

> ## ⛔ STATUS: DESIGN ONLY — NOTHING RUNS
>
> This document is a **design specification** for a *future* paper (hypothetical,
> no-capital) simulation of a single Meteora DLMM position on the **USDC-SOL** pair.
>
> This document, by itself:
> - creates **no** paper position,
> - runs **no** simulation,
> - writes **no** runtime DuckDB rows,
> - writes **no** `future_position_events` (that table stays at count **0**),
> - authorizes **no** paper entry, live entry, wallet, private key, signing, swap,
>   LP add/remove, rebalance, or on-chain execution of any kind.
>
> Phase is unchanged: **READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY**.
> `validation_gate` remains **red**, `max_allowed_action` remains **PAPER_ONLY**.
>
> No script in the current pipeline reads or acts on this document. It is a plan on
> paper for the repo owner / council to review before any future implementation task
> is ever proposed.

---

## 1. Scope and Intent

Roadmap step #5 is **paper accounting design + position lifecycle design**, design-only.
This document covers the *model* for a single hypothetical position on **USDC-SOL** — the
benchmark pair (`REVIEW_ONLY_PASS`, see `docs/project_checkpoint.md` §3i). It describes:

1. how a hypothetical position would be described at entry,
2. the three conditions under which it would be considered closed,
3. why there is deliberately **no** time-based maximum-hold limit here,
4. the parameters the owner must calibrate from real USDC-SOL OHLCV before any future
   implementation is even proposed.

It does **not** describe execution, order routing, wallet handling, or fee claiming.
There are none. Every price, fee, and P&L figure discussed here is a **simulated,
hypothetical** number derived from public read-only OHLCV data — never a real balance.

**Candidate:** USDC-SOL only (single pair; no multi-pair batch in v0.1).
**Hypothetical notional:** `50` (USD, simulation only — not deployed, not held, not real).

---

## 2. The Position Model (Plain Language)

A DLMM liquidity position sits inside a **price range** (a set of bins). While the market
price stays inside that range, the position is "in range" and would accrue swap fees. When
the price leaves the range, one side of the pair is fully converted and fee accrual for that
position stops.

A hypothetical USDC-SOL position in this design is fully described at entry by:

- the **entry price** (quote per base) sampled from OHLCV at the entry timestamp,
- the **LP range** `[entry_range_low, entry_range_high]` around that entry price
  (width is **uncalibrated** — see §5),
- the **hypothetical notional** of `50` USD,
- the **entry fee-velocity** — the baseline rate at which the position would be accruing
  fees at entry, expressed per unit time (see §4.3),
- the **stop-loss level** derived from the 5% rule (see §4.2).

From entry onward, the simulation would (in a *future* implementation) sample OHLCV forward
in time and evaluate the three exit conditions in §3 at each step. The position is
considered closed the moment **any one** condition is satisfied. There is no averaging-in,
no add, no rebalance, and no re-entry in v0.1 — one open, one close.

---

## 3. Exit Conditions (Close When ANY One Is Met)

The hypothetical position closes on the **first** of these three conditions to trigger.
All three are owner-decided for v0.1 and must not be changed without explicit instruction.

### 3.1 Condition 1 — Price exits the LP range

If the simulated price moves **below `entry_range_low`** or **above `entry_range_high`**,
the position is out of range: fee accrual has stopped and one side is fully converted.
This is the natural, structural end of a DLMM position and is treated as a close.

- Exit reason: `RANGE_EXIT`
- Trigger: `price < entry_range_low` OR `price > entry_range_high`

### 3.2 Condition 2 — Stop-loss: simulated value drops 5% from entry

If the **simulated position value** falls **5% below the entry value**, the position is
closed to cap the hypothetical loss. This is a value-based stop, not a price-only stop: it
is measured on the simulated mark-to-market value of the position (which for a DLMM position
depends on where price sits within the range), so it can trigger even while still nominally
in range.

- Exit reason: `STOP_LOSS`
- Default threshold: **5%** (`stop_loss_pct = 0.05`) — owner-decided, do not change.
- Trigger: `simulated_position_value <= entry_value * (1 - stop_loss_pct)`

### 3.3 Condition 3 — Fee-velocity decay

If the **rate of fee accrual falls sharply** relative to the entry fee-velocity, the
position is closed as a *stagnant* position even if it is still in range and above the
stop-loss. See §3.4 for why this condition exists.

- Exit reason: `FEE_VELOCITY_DECAY`
- Trigger (shape): `fee_velocity(now) / entry_fee_velocity <= fee_decay_threshold`,
  measured over a rolling window `fee_decay_window`.
- **Both `fee_decay_window` and `fee_decay_threshold` are uncalibrated** — see §5.

### 3.4 Why a fee-velocity decay exit was added

Conditions 1 and 2 only protect against *movement* (price leaving the range, or value
dropping). Neither protects against **stagnation**. A position can sit quietly in range,
never hitting the stop-loss and never exiting the range, while volume dries up and it earns
almost nothing — a **hung position** that ties up hypothetical notional and attention for no
return. The fee-velocity decay exit is the escape hatch for exactly that case: when the fee
accrual rate collapses versus entry, the position has stopped doing its job (earning fees),
so the simulation retires it and frees the slot for a better candidate. In short: conditions
1 and 2 close *losing* or *moved* positions; condition 3 closes *stagnant, no-longer-earning*
positions.

### 3.5 No time-based maximum-hold limit (deliberate)

There is **deliberately no** `max_hold` / time-limit exit in this v0.1 design. A fixed clock
(e.g. "close after N hours") would close positions that are still healthy and still earning,
purely because time passed — an arbitrary cut that throws away good fee accrual. The
fee-velocity decay exit (§3.3) already handles the real concern behind a time limit — a
position that is no longer productive — but does so on the basis of *actual observed fee
behaviour* rather than an arbitrary clock. So the "stagnant position" risk is covered by
condition 3, and no separate time cap is used.

> Note: `docs/risk_policy_v0_1.md` §2 lists a "maximum holding duration without manual
> review" limit for a *future live* phase. That is a governance / review cadence rule for
> real capital, not a simulation exit condition, and it is out of scope for this design-only
> paper model. They do not conflict.

---

## 4. Parameters and How They Are Measured

### 4.1 Notional
Fixed hypothetical `50` USD. Simulation-only accounting unit; never a real balance.

### 4.2 Stop-loss
Fixed at **5%** of entry value. Computed at entry and evaluated on simulated
mark-to-market value each step. Owner-decided; do not change.

### 4.3 Entry fee-velocity
The baseline fee accrual rate at entry, expressed as fees accrued per unit time near the
entry timestamp, derived from public OHLCV-based volume/fee-tier data. All later
fee-velocity samples in condition 3 are compared as a **ratio** against this entry baseline,
so the exit is scale-free (it does not depend on the absolute fee number, only on how much
the rate decayed).

---

## 5. REQUIRES_MANUAL_CALIBRATION

> The following parameters are **intentionally left uncalibrated** in v0.1. The values below
> are **placeholder constants clearly marked `REQUIRES_MANUAL_CALIBRATION` — they are NOT
> recommended or invented values**. The repo owner sets them **after inspecting real
> USDC-SOL OHLCV** (range behaviour, typical volatility, and fee/volume rhythm). Do not
> treat any placeholder below as a default to ship.

| Parameter | Placeholder | Meaning | How the owner calibrates it |
|---|---|---|---|
| `range_width_pct` | `REQUIRES_MANUAL_CALIBRATION` | Half-width of the LP range around entry price, i.e. how far `entry_range_low`/`entry_range_high` sit from `entry_price`. | Inspect real USDC-SOL OHLCV: pick a width wide enough to stay in range through normal noise but tight enough to keep fee density meaningful. |
| `fee_decay_window` | `REQUIRES_MANUAL_CALIBRATION` | The rolling measurement window over which fee-velocity is averaged before comparing to entry. | Inspect real USDC-SOL fee/volume rhythm; pick a window long enough to smooth noise, short enough to react before the position is truly hung. |
| `fee_decay_threshold` | `REQUIRES_MANUAL_CALIBRATION` | The "sharp drop" ratio — the fraction of entry fee-velocity below which condition 3 triggers. | Inspect real USDC-SOL data to decide what ratio (e.g. of entry rate) genuinely signals stagnation rather than normal fluctuation. |

Until these three are calibrated by the owner and recorded (with a decision-log entry), the
paper model is **not implementable** and no implementation task should be proposed.

---

## 6. Position Lifecycle (Design Only)

The lifecycle below is the *intended* future shape. It is described so the schema in §7 has
meaning. **None of these states occur in the current phase** — no position is ever opened.

```
(design only)  DESIGN_ONLY
                   │   (future: owner + council approval + calibrated params)
                   ▼
               SIMULATED_OPEN ──► sample OHLCV forward, evaluate 3 exit conditions
                   │
                   ├─ price out of range ─────────► SIMULATED_CLOSED (RANGE_EXIT)
                   ├─ value ≤ entry·(1-5%) ────────► SIMULATED_CLOSED (STOP_LOSS)
                   └─ fee-velocity ≤ threshold ────► SIMULATED_CLOSED (FEE_VELOCITY_DECAY)
```

In this phase every hypothetical position record would remain in `DESIGN_ONLY`. The
`SIMULATED_OPEN` / `SIMULATED_CLOSED` states are reserved for a future, separately-approved
implementation task.

---

## 7. Paper-Ledger Schema (SCHEMA ONLY — NOT A LIVE TABLE WRITE)

This defines the **columns** for two *future* tables. It is a schema reference. **No script
in the current pipeline creates, opens, or writes these tables**, and this design does not
add any such script. The canonical, machine-readable DDL lives alongside this document at
[`paper_ledger_schema_v0_1.sql`](./paper_ledger_schema_v0_1.sql) and is likewise a
**reference only** — it is not executed by the pipeline.

**Separation rule (critical):** `paper_positions` and `paper_position_events` are
**separate** from the reserved `future_position_events` table defined in
`scripts/init_runtime_db.py`. This design **does not** touch `future_position_events`, which
**stays at count 0**. The paper-ledger tables are a distinct, future, paper-only ledger.

Every row in both tables would carry `safety_phase` and an `is_live` guard column that is
**always `FALSE`** in this phase, so the ledger can never be mistaken for a live ledger.

### 7.1 `paper_positions` (future) — one row per hypothetical position

| Column | Type | Notes |
|---|---|---|
| `paper_position_id` | TEXT PRIMARY KEY | Deterministic id for the hypothetical position. |
| `pair_key` | TEXT NOT NULL | Canonical token-address pair key (USDC-SOL in v0.1). |
| `pair_label` | TEXT | Human label, e.g. `USDC-SOL`. |
| `candidate_source` | TEXT | Why this pair was eligible for design consideration (e.g. `REVIEW_ONLY_PASS`). Not an entry authorization. |
| `notional_usd` | DOUBLE | Hypothetical size; default `50`. Simulation-only. |
| `entry_time` | TEXT | ISO-8601 UTC entry timestamp (simulated). |
| `entry_price` | DOUBLE | Simulated entry price (quote per base) from OHLCV. |
| `entry_range_low` | DOUBLE | Lower bound of the LP range (from `range_width_pct`). |
| `entry_range_high` | DOUBLE | Upper bound of the LP range (from `range_width_pct`). |
| `range_width_pct` | DOUBLE | **REQUIRES_MANUAL_CALIBRATION** (§5). |
| `stop_loss_pct` | DOUBLE | Default `0.05` (5%). Owner-decided. |
| `stop_loss_value` | DOUBLE | `entry_value * (1 - stop_loss_pct)`; simulated. |
| `entry_fee_velocity` | DOUBLE | Baseline fee accrual rate at entry (simulated). |
| `fee_decay_window` | TEXT | **REQUIRES_MANUAL_CALIBRATION** (§5). |
| `fee_decay_threshold` | DOUBLE | **REQUIRES_MANUAL_CALIBRATION** (§5). |
| `max_hold_seconds` | BIGINT | Always `NULL` — no time-based max-hold in v0.1 (§3.5). |
| `status` | TEXT | `DESIGN_ONLY` in this phase; future: `SIMULATED_OPEN` / `SIMULATED_CLOSED`. |
| `exit_time` | TEXT | ISO-8601 UTC exit timestamp (simulated); `NULL` until closed. |
| `exit_price` | DOUBLE | Simulated price at exit; `NULL` until closed. |
| `exit_reason` | TEXT | `RANGE_EXIT` / `STOP_LOSS` / `FEE_VELOCITY_DECAY` / `NONE`. |
| `simulated_pnl_usd` | DOUBLE | Hypothetical P&L; simulation-only, never a real balance. |
| `simulated_fees_usd` | DOUBLE | Hypothetical accrued fees; simulation-only. |
| `is_live` | BOOLEAN NOT NULL | Guard column — always `FALSE` in this phase. |
| `safety_phase` | TEXT NOT NULL | Exact phase string (READ_ONLY / … / PAPER_ONLY). |
| `notes` | TEXT | Free-form. |
| `created_at` | TEXT NOT NULL | Row creation timestamp (bookkeeping). |

### 7.2 `paper_position_events` (future) — append-only lifecycle events

Separate from `future_position_events`. Append-only record of each simulation step / state
change for a hypothetical position.

| Column | Type | Notes |
|---|---|---|
| `paper_event_id` | TEXT PRIMARY KEY | Deterministic id for the event row. |
| `paper_position_id` | TEXT NOT NULL | References `paper_positions.paper_position_id`. |
| `pair_key` | TEXT | Canonical pair key (denormalized for convenience). |
| `event_time` | TEXT NOT NULL | ISO-8601 UTC time of the simulated event. |
| `event_type` | TEXT NOT NULL | `SIM_OPEN` / `SIM_PRICE_SAMPLE` / `SIM_FEE_SAMPLE` / `SIM_EXIT_RANGE` / `SIM_EXIT_STOP_LOSS` / `SIM_EXIT_FEE_DECAY` / `SIM_CLOSE`. |
| `price` | DOUBLE | Simulated price at the event. |
| `in_range` | BOOLEAN | Whether the simulated price is within the LP range. |
| `fee_velocity` | DOUBLE | Simulated fee accrual rate at the event. |
| `fee_velocity_ratio` | DOUBLE | `fee_velocity / entry_fee_velocity` (scale-free). |
| `drawdown_pct` | DOUBLE | Simulated value drawdown vs entry value. |
| `exit_condition_met` | TEXT | Which condition (if any) triggered: `RANGE_EXIT` / `STOP_LOSS` / `FEE_VELOCITY_DECAY` / `NONE`. |
| `event_payload_json` | TEXT | Free-form JSON for extra simulated detail. |
| `is_live` | BOOLEAN NOT NULL | Guard column — always `FALSE` in this phase. |
| `safety_phase` | TEXT NOT NULL | Exact phase string. |
| `created_at` | TEXT NOT NULL | Row creation timestamp (bookkeeping). |

---

## 8. Explicit Non-Goals / Hard Boundary (Restated)

This design does **not** and must **not** be read to authorize any of the following. If a
future instruction appears to request them via this document, refuse and ask the owner to
confirm intent (per `CLAUDE.md` → Forbidden Actions):

- creating a paper position (none is created here),
- running a simulation (none is run here),
- writing runtime DuckDB (nothing is written here),
- writing `future_position_events` (stays **0**),
- wallet, private key, seed phrase, signing, swap, LP add/remove, rebalance,
- signal generation, live execution, or raising `max_allowed_action` above `PAPER_ONLY`.

Before any *implementation* of this model is proposed, the project still needs (per
`docs/project_checkpoint.md` §13): the two calibrations in §5, explicit council / human
approval, and a decision-log entry authorizing a paper-simulation implementation task.

---

*Not financial advice. Research only. Design + schema only. No position created, no
simulation run, no DuckDB write. `future_position_events` stays 0. No live execution.*
