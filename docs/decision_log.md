# Decision Log

Records decisions that affect project structure, architecture, rules, or workflow.
Each entry is permanent — past entries are never edited. Revisions are recorded as
new entries that reference the original.

Format per entry:
- **Date** — when the decision was made
- **Decision** — what was decided, stated precisely
- **Rationale** — why, including tradeoffs considered
- **Impact** — what this changes or constrains going forward

---

## DEC-20260629-001 — Pair-Level Scoring Before Pool-Level

**Date:** 2026-06-29
**Decision:** Pair-level aggregation (`pair_watchlist.csv`, produced by `group_by_pair()`
in `build_watchlist.py`) is the **primary shortlisting view**. Pool-level scoring
(`pools_watchlist.csv`, produced by `build_rows()`) is retained as **legacy audit trail only**
and must not be used as the source for candidate decisions.

**Rationale:** A single token pair (e.g. USDC-SOL) can have up to 9 pools with different
bin steps. Evaluating pools individually inflates the candidate list, fragments signal across
bin steps, and makes fee-eligibility comparisons noisy. Grouping by canonical token-address
pair key first produces a cleaner shortlist, surfaces multi-pool diversity as a positive
signal, and isolates the fee-ratio distortion problem (small-TVL pools inflating the ratio)
through the `eligible_fee_pool` filter.

**Impact:**
- `build_watchlist.py` runs `group_by_pair()` after `build_rows()`. Both are written to disk.
- Reports and recommendations source from `pair_watchlist.csv`.
- Pool-level CSV is still written, validated, and preserved for auditability.
- Future scoring improvements (v0.2+) target the pair-level view first.

---

## DEC-20260629-002 — Risk Flags at Pair Level Are Not Always Auto-Rejects

**Date:** 2026-06-29
**Decision:** At pair level, risk signals such as fee-ratio distortion and low eligible-pool
count are encoded as `fee_ratio_sanity_flag` values and affect `score_data_quality`, but do
**not** automatically REJECT a pair unless `blacklisted_pool_count > 0` or
`eligible_fee_pool_count = 0`.

**Rationale:** A pair like ANSEM-SOL has a severe raw fee-ratio distortion (329M% raw vs
18.6% eligible best) caused by micro-TVL pools. However, it still has 4 eligible pools with
meaningful TVL and volume. Blanket auto-reject on any distortion flag would discard valid
candidates. The `eligible_fee_pool` filter already corrects for the distortion in the usable
metric (`best_eligible_fee_tvl_pct_24h`). The sanity flag's role is to signal to the analyst
that manual inspection is required before a paper test decision — not to replace that judgment.

**Impact:**
- `score_data_quality_pair()` maps `low_tvl_distortion → 70` (not 0).
- `assign_pair_status()` only forces REJECT when `blacklisted > 0` or `eligible = 0`.
- Analyst must inspect `fee_ratio_sanity_flag` manually as part of the Protocol §6 checklist
  before committing to any paper test for a distorted pair.

---

## DEC-20260629-003 — Execution Logic Comes After Risk Policy and State Management

**Date:** 2026-06-29
**Decision:** Any future live-execution capability (currently parked — see `docs/VISION_PARKED.md`)
must be built **only after** a config-driven risk policy module and a state management layer
are in place and reviewed. Execution code cannot be the first component built in a live phase.

**Rationale:** An execution module without a risk gate is unconstrained. A system that can
place orders but cannot enforce position limits, drawdown thresholds, or kill-switch
conditions is more dangerous than no system at all. Hardcoded risk logic inside an execution
function is also insufficient — it cannot be reviewed, configured, or updated without
touching execution code, which creates audit and regression risk. The risk policy must exist
as a separate, config-driven, independently-testable module before any transaction-signing
code is written.

**Impact:**
- Future development order for live phase: risk_policy module → state manager → execution layer.
  Never the reverse.
- `docs/risk_policy_v0_1.md` (DRAFT) documents the intended policy; it is not active.
- `config/risk_policy.yaml` is reserved for the machine-readable form of the policy.
- Live execution remains forbidden until `validation_gate = green` **and** the risk module
  has been built, tested, and explicitly reviewed.

---

## DEC-20260629-004 — Telegram as Initial Control Room Interface

**Date:** 2026-06-29
**Decision:** When a notification and control layer is eventually built (currently parked),
**Telegram Bot API** is the designated initial interface for pipeline alerts and manual
override commands.

**Rationale:** Solo operator, capital-limited project. Telegram bot in polling mode requires
no server infrastructure, no domain, no TLS configuration. Setup cost is minimal. Supports
message formatting and inline keyboard buttons for acknowledgment and basic commands.
A web dashboard would be over-engineering at this scale before edge is proven. The decision
is recorded here to prevent this choice from being relitigated without cause in a future session.

**Impact:**
- `config/telegram_events.yaml` is reserved for event-to-message-template mapping.
- No Telegram code is to be written in the current phase (PAPER_ONLY).
- Bot token must always be loaded from environment variables — never hardcoded or committed.
- If Telegram proves insufficient when the live phase is authorized, a new decision log entry
  must document the change and the reason.

---

## DEC-20260629-005 — Local Artifacts Must Not Override Verified GitHub Actions Results

**Date:** 2026-06-29
**Decision:** Local pipeline output files (`data/ohlcv_top_pairs.csv`,
`reports/ohlcv_report.md`, etc.) must **not** be treated as ground truth for API
reachability, endpoint behavior, or data availability. The GitHub Actions artifact from the
`collect_and_validate` workflow is the authoritative source for pipeline status.

**Rationale:** Local runs may fail due to conditions that do not affect CI: local network
restrictions, proxy interference, stale pool addresses in a local cache, or a transient
API outage at the time of the local run. A local `API_ERROR` on all 20 OHLCV polls is a
single data point, not evidence that the endpoint is permanently unavailable or that the
script logic is wrong. Treating local failures as permanent causes premature restructuring
of working pipeline code — the wrong fix for the wrong diagnosis.

**Impact:**
- Before any OHLCV-related code change: download the latest CI artifact and inspect
  `reports/ohlcv_report.md` from that run.
- If CI also shows all `API_ERROR`: investigate endpoint URL, query parameters, and
  response schema before modifying any script.
- This rule applies to all pipeline artifacts, not only OHLCV.
- See `CLAUDE.md` → OHLCV section and `docs/assumption_register.md` → ASM-20260629-006.

---

*This log is append-only. Do not edit or delete past entries.*
*New decisions are added at the bottom.*
