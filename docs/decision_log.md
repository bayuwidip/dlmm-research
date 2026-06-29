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

## DEC-20260629-006 — Strategy Classification v0.2 Accepted as Local Pipeline Layer

**Date:** 2026-06-29
**Decision:** Strategy Classification v0.2 is accepted as a **local pipeline layer** built
on top of the pair-level view. It is implemented as a standalone script
(`scripts/classify_strategy.py`) that reads `data/pair_watchlist.csv` and
`data/ohlcv_top_pairs.csv` and writes `data/strategy_classification_v2.csv` plus
`reports/strategy_classification_v2.md`. It introduces the `strategy_class_v2` enum
`{CORE, TACTICAL, REJECT, NOT_EVALUATED}` with companion columns
(`pair_score_v2_core`, `pair_score_v2_tactical`, `pair_status_v2`, `risk_flag_count`,
`risk_flags`, `test_lane`, `live_eligibility`, `minimum_observation_days`,
`required_capability`, `v2_classification_reason`). Acceptance is at the **local layer
only** — it is not yet verified by a GitHub Actions artifact, and GitHub Actions is
deliberately not updated in this step.

**Rationale:** v0.2 extends, rather than replaces, the v0.1 pair-level scoring
(DEC-20260629-001). It encodes four binding rules drawn from the project's current phase:
1. **OHLCV unavailable → `NOT_EVALUATED`, never `REJECT`.** Missing volatility data is a
   gap, not a verdict — consistent with the no-guess principle and DEC-20260629-005.
2. **Extreme volatility is not an automatic `REJECT`.** A volatile pair becomes `TACTICAL`
   when liquidity, volume, fee quality, and data quality are acceptable; it is `REJECT`
   only when extreme/high volatility is *combined* with a severe issue (blacklist, no
   eligible fee pool, unacceptable liquidity/volume, or severe data issue such as
   `data_completeness_pct` below the floor). This realises ASM-20260629-003.
3. **`TACTICAL` is reporting/watchlist only.** It maps to `pair_status_v2 = WATCHLIST`,
   `live_eligibility = OBSERVE_ONLY`, `required_capability = OBSERVE`. No paper entry,
   no execution, no LP, no rebalance, no wallet pathway is implied or permitted.
4. **No live eligibility in this phase.** `live_eligibility` can never take any
   `LIVE_ELIGIBLE_*` value; this is enforced in the classifier and re-checked by the
   validator. PAPER_ONLY is preserved end-to-end (validation_gate remains red).

A successful local OHLCV diagnostic run on 2026-06-29 (20/20 `OK`, see ASM-20260629-006)
exercised the classifier on real volatility data, producing:
`CORE = 8`, `TACTICAL = 10`, `REJECT = 2`, `NOT_EVALUATED = 193`. The two `REJECT` rows
were extreme volatility *combined with* `LOW_DATA_COMPLETENESS` — confirming rule 2 fires
on combination, not on volatility alone.

**Impact:**
- `validate_watchlist.py` was extended **additively** with `validate_strategy_v2_csv()`
  (enum checks; `live_eligibility` may never be `LIVE_ELIGIBLE_*`; `pair_status_v2` may not
  contain `LIVE`; `required_capability` may not be an execution/wallet capability; `REJECT`
  must carry at least one severe flag; forbidden-column scan). Unit tests
  (`tests/test_classify_strategy.py`) cover the CORE/TACTICAL/REJECT/NOT_EVALUATED branches
  and the no-LIVE guarantee, stdlib-only.
- The four working scripts (`fetch_meteora_pools.py`, `build_watchlist.py`,
  `fetch_ohlcv_top_pairs.py`, and the existing body of `validate_watchlist.py`) were not
  refactored. Pool-level scoring remains legacy audit trail only (DEC-20260629-001).
- Acceptance is **local-only**. Promotion of these CORE/TACTICAL/REJECT results to
  authoritative status, and any GitHub Actions wiring, is gated on CI artifact
  confirmation (DEC-20260629-005, ASM-20260629-006).
- No wallet, execution, LP, rebalance, swap, or private-key logic exists or is introduced.

---

## DEC-20260629-007 — GitHub Actions Confirms Strategy Classification v0.2 Pipeline

**Date:** 2026-06-29
**Decision:** The `collect_and_validate` GitHub Actions workflow — now including the
Strategy Classification v0.2 step wired after OHLCV and before validation — is confirmed
working end-to-end in the CI environment. Artifact **`dlmm-run-28375624302`** completed the
full sequence (fetch → build → OHLCV → strategy classification v0.2 → validate → upload
artifacts) and uploaded both v0.2 outputs (`data/strategy_classification_v2.csv`,
`reports/strategy_classification_v2.md`). This closes the CI-confirmation gate left open by
DEC-20260629-006 and ASM-20260629-006: v0.2 is no longer "local-only" — it is a
CI-verified pipeline layer.

**Rationale:** DEC-20260629-006 accepted v0.2 only at the local layer, explicitly gating
promotion on a verified GitHub Actions artifact (per DEC-20260629-005, CI is authoritative,
not local). Artifact `dlmm-run-28375624302` supplies that confirmation: OHLCV returned
**20/20 `OK`** in CI, and the classifier and validator both ran without failing the
workflow. Endpoint reachability, the `extract_candles()` parser, workflow integration, the
classifier, and the validator are therefore all confirmed functional in GitHub Actions.

**CI results (artifact `dlmm-run-28375624302`, run timestamp 2026-06-29T13:29 UTC):**
- OHLCV: 20/20 `OK` (0 `API_ERROR`, 0 `MALFORMED_RESPONSE`).
- `strategy_class_v2` counts: **CORE = 9, TACTICAL = 9, REJECT = 2, NOT_EVALUATED = 194**
  (214 rows total).
- `live_eligibility`: 0 rows with any `LIVE_ELIGIBLE_*` value — the no-live guarantee held
  in CI. PAPER_TEST_ALLOWED and OBSERVE_ONLY appear only on paper/observe terms.
- Pair count changed from **213 (local) to 214 (CI)** because the CI run fetched a fresh
  live Meteora snapshot; pair membership and per-pair metrics differ run-to-run by design
  (online-only, no fixed input). Small count drift between runs is expected, not a defect.

**Scope limits (what this decision does NOT assert):**
- This confirms the **pipeline mechanism works**, not that any strategy is profitable or
  live-ready. No edge has been demonstrated.
- Live execution remains **forbidden**. `validation_gate` stays **red**; max allowed action
  stays **PAPER_ONLY**.
- `TACTICAL` remains **observe-only** (`OBSERVE_ONLY`, watchlist) — no paper entry.
- `PAPER_TEST_ALLOWED` (CORE) means **paper test only** — it is not live eligibility and
  confers no wallet, signing, swap, LP, rebalance, or execution capability.

**Data-quality follow-up (must be resolved before any paper test of that pair):**
- The pair labelled **`-USDT`** has a **malformed / blank base token symbol** (empty symbol
  on one side of the pair). It appears in the OHLCV Top-20 and is classified by v0.2, but
  the blank symbol is a data-quality red flag (missing/unverified token metadata, possible
  unverified or malformed token). It must be **reviewed as a data-quality issue and not
  paper-tested until the base token is positively identified and vetted**, regardless of its
  `strategy_class_v2` or score. This does not require a code change now; it is a manual
  review gate recorded here so it is not overlooked.

**Impact:**
- ASM-20260629-006 status advanced to **VALIDATED IN CI** (artifact `dlmm-run-28375624302`),
  with a standing caveat that future runs may differ due to live market/API conditions.
- v0.2 is treated as a confirmed pipeline layer for reporting/screening purposes only;
  all phase gates (PAPER_ONLY, no live execution, TACTICAL observe-only) remain in force.
- `CLAUDE.md` OHLCV status (currently describing local `API_ERROR`) is now out of date and
  may be updated in a separate, explicitly-scoped step.

---

*This log is append-only. Do not edit or delete past entries.*
*New decisions are added at the bottom.*
