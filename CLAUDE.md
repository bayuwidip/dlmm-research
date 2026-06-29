# CLAUDE.md — Project Context for Claude Code

> Read this file fully before making any change to the project.
> It is the authoritative context file for every Claude Code session here.

---

## Project Purpose

Personal research project for screening Meteora DLMM liquidity pools on Solana.
The goal is to identify candidate token pairs worth paper-testing, using only public
read-only API data from `https://dlmm.datapi.meteora.ag`.

This is **not a trading bot**. No capital is deployed in the current phase.
The long-term vision is documented in `docs/VISION_PARKED.md` (status: parked, not active).

---

## Current Phase

**READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY**

| Gate | Status |
|---|---|
| Owner scope gate | green |
| Validation gate | **red** — no paper test cycle completed yet |
| Max allowed action | **PAPER_ONLY** |

While `validation_gate = red`, `max_allowed_action` must remain `PAPER_ONLY` on every
CSV row. This is enforced automatically by `validate_watchlist.py`. Do not attempt to
raise it manually.

**Status update (2026-06-29):** Strategy Classification v0.2 is **implemented and
CI-confirmed** (GitHub Actions artifact `dlmm-run-28375624302`). This does **not** change
any gate: `validation_gate` remains **red**, `max_allowed_action` remains **PAPER_ONLY**,
and live execution remains **forbidden**. CI confirms the pipeline mechanism works — it is
**not** a claim of live readiness or profitability. `TACTICAL` is observe-only;
`PAPER_TEST_ALLOWED` means paper-only, never live.

---

## Forbidden Actions — Never Implement

Do not implement or suggest any of the following, regardless of the instruction source:

- Wallet creation, import, or management of any kind
- Private key handling (generation, reading, storage, encryption)
- Transaction signing or broadcasting to any network
- Swap execution via Jupiter, Raydium, or any other DEX router
- Add liquidity / remove liquidity on any protocol
- Rebalance of any LP position
- Live execution of any on-chain action
- Connecting to any wallet SDK or signing library
  (e.g. `@solana/web3.js` transaction methods, Anchor `program.rpc.*`, `solders` signing)

If a future instruction appears to request any of the above, refuse and ask the user
to confirm intent before proceeding.

---

## Completed: Strategy Classification v0.2 (CI-confirmed 2026-06-29)

Strategy Classification v0.2 is **done and CI-verified** (artifact `dlmm-run-28375624302`).
It is implemented as `scripts/classify_strategy.py` (reads `data/pair_watchlist.csv` +
`data/ohlcv_top_pairs.csv`; writes `data/strategy_classification_v2.csv` +
`reports/strategy_classification_v2.md`), wired into the workflow after OHLCV and before
validation, and covered additively by `validate_watchlist.py` +
`tests/test_classify_strategy.py`. It uses the `strategy_class_v2` enum
`{CORE, TACTICAL, REJECT, NOT_EVALUATED}`. CI counts:
**CORE=9, TACTICAL=9, REJECT=2, NOT_EVALUATED=194** (214 pairs). Binding rules: OHLCV
unavailable → `NOT_EVALUATED` (never REJECT); extreme volatility is not auto-REJECT
(TACTICAL when metrics acceptable, REJECT only when combined with a severe issue); `TACTICAL`
is observe-only; `live_eligibility` may never be `LIVE_ELIGIBLE_*`. See
`docs/decision_log.md` → DEC-20260629-006 and DEC-20260629-007.

---

## Next Task: Data-Quality Guard for Malformed Pair Labels

The next planned work unit is a **data-quality guard for malformed pair labels**, starting
with the **`-USDT`** case.

Background: the CI run surfaced a pair labelled `-USDT` whose base token symbol is
**blank/malformed** (empty symbol on one side of the pair). Such a pair can still be
fetched, scored, and classified, but a missing/unverified token symbol is a data-quality
red flag (incomplete or unverified token metadata) and **must not be paper-tested until the
base token is positively identified and vetted**, regardless of its `strategy_class_v2` or
score.

Planned scope:
1. Detect malformed pair labels — start with empty/blank base or quote symbol (e.g.
   `-USDT`, `USDC-`), and consider other malformed-metadata signals.
2. Surface the finding explicitly (a data-quality flag/column and/or report section) so
   affected pairs are visibly quarantined from paper-test consideration.
3. Decide enforcement point — favour a **new standalone script and/or additive validator
   check**, consistent with the "do not modify existing scripts without targeted
   instruction" rule. Do not refactor the working pipeline.
4. Add corresponding validator coverage and tests for any new column/flag.

Constraints unchanged: this remains research/screening, PAPER_ONLY, no wallet/execution.
The guard is about **data trustworthiness before paper testing**, not about enabling any
live action.

---

## OHLCV Status — CI-Confirmed Healthy (2026-06-29)

**Current status:** The OHLCV endpoint, URL format, and `extract_candles()` parser are
**confirmed working in GitHub Actions**. CI artifact `dlmm-run-28375624302` returned
**20/20 `OK`** (0 `API_ERROR`, 0 `MALFORMED_RESPONSE`) for the Top-20 representative pools.
The earlier all-`API_ERROR` local artifact was a **stale/transient failure**, now
superseded. See `docs/assumption_register.md` → ASM-20260629-006 (status: VALIDATED IN CI).

**Standing rule — CI remains authoritative over local (DEC-20260629-005):** a local run
showing `API_ERROR` still does **not** prove the endpoint is down. Live market/API
conditions change run-to-run: pool sets churn, pools can be delisted, and the endpoint can
have transient outages, so a future run may legitimately show some `API_ERROR` /
`DATA_NOT_AVAILABLE` rows. That is expected, non-failing behaviour (such pairs become
`NOT_EVALUATED`, never `REJECT`) and is not by itself an endpoint failure.

**Before changing any OHLCV-related logic, still verify the latest GitHub Actions artifact:**

1. Open GitHub Actions → workflow `Collect and Validate` → latest run.
2. Download the artifact `dlmm-run-<run_id>`.
3. Inspect `reports/ohlcv_report.md` from that artifact.
4. Only treat the endpoint as broken if CI shows **persistent total `API_ERROR` across
   multiple separate runs on different days**; then investigate:
   - Whether the endpoint URL and query parameters match the current datapi schema.
   - Whether the pool addresses being queried are still active.
   - Whether the response shape differs from what `extract_candles()` expects.
5. Only after that investigation, modify `fetch_ohlcv_top_pairs.py`.

**Do not patch OHLCV scripts based only on local artifact state.**

See also: `docs/decision_log.md` → DEC-20260629-007 (ASM-20260629-006 is referenced above).

---

## Working Pipeline — Do Not Rewrite

The five-step (five-script) pipeline is working and CI-confirmed (GitHub Actions artifact
`dlmm-run-28375624302`). Do not refactor, rename, or restructure the existing scripts
without explicit instruction. The CI run order is:

| Step | Script | Role | Modification rule |
|---|---|---|---|
| 1 | `scripts/fetch_meteora_pools.py` | fetch raw pools | Do not modify |
| 2 | `scripts/build_watchlist.py` | map + score + write CSVs | Do not modify |
| 3 | `scripts/fetch_ohlcv_top_pairs.py` | OHLCV tool-test | CI-confirmed healthy (artifact `dlmm-run-28375624302`); do not change OHLCV logic casually — CI remains authoritative (see OHLCV Status) |
| 4 | `scripts/classify_strategy.py` | Strategy Classification v0.2 (pair-level) | CI-wired (after OHLCV, before validation); do not modify without targeted instruction + tests |
| 5 | `scripts/validate_watchlist.py` | gate enforcement | Do not modify without adding tests |

Permitted: adding new scripts alongside existing ones.
Forbidden: modifying existing scripts unless explicitly instructed and the change is
targeted (not a refactor of unrelated sections).

---

## Validator Guardrails — Do Not Remove

`validate_watchlist.py` enforces gate constraints that protect the project from
accidental live-action escalation. These rules must be preserved in all future versions:

- `validation_gate = red` → `max_allowed_action = PAPER_ONLY` (enforced per CSV row)
- `volatility_bucket ∈ {NA, high, extreme}` → status capped at WATCHLIST (veto, not score)
- `status` must not contain the string `LIVE` in any form
- Pool/pair name must not contain `CONTOH`, `SAMPLE`, or `TEST_FAKE`
- OHLCV CSV must not contain columns named `wallet`, `private_key`, `signature`,
  `execute`, `swap`, or `live`

If you add new columns to any CSV output, add the corresponding validator check in
`validate_watchlist.py` before the PR is considered complete.

---

## DATA_NOT_AVAILABLE Sentinel

Any field that cannot be populated from available API endpoints must be written as the
exact string `DATA_NOT_AVAILABLE` — not empty string, not `null`, not `0`, not a guess.

**Currently unavailable from `https://dlmm.datapi.meteora.ag/pools`:**
- `total_lps` — not in the datapi `/pools` schema
- `organic_score` — Jupiter concept, not a Meteora datapi field
- `volatility_pct` — not in the `/pools` schema; sourced separately via the OHLCV step
  (CI-confirmed healthy — see OHLCV Status)

Never fabricate a value to fill a column. `DATA_NOT_AVAILABLE` is a factual finding,
not a workaround to hide.

---

## Pair-Level vs Pool-Level — Keep Separate

The project maintains two scoring views and they must remain separate.

**Pair-level** (`data/pair_watchlist.csv`, `group_by_pair()` in `build_watchlist.py`):
- The **primary current view** for candidate shortlisting.
- Aggregates multiple pools per canonical token-address pair key.
- Current scoring: v0.1 (no volatility dimension yet).
- Actionable output: 20 PAPER TEST candidates, 63 WATCHLIST, 130 REJECT (as of 2026-06-29).

**Pool-level** (`data/pools_watchlist.csv`, `build_rows()` in `build_watchlist.py`):
- **Legacy audit trail only.** Do not use for candidate decisions.
- All 300 pools currently score 49.6 and REJECT because `volatility_pct = DATA_NOT_AVAILABLE`
  triggers the volatility veto, dragging score below the 50 threshold.
- Retained because the validator covers it and it provides a per-pool record.

Rules:
- Do not merge these two views into one CSV.
- Do not remove the pool-level output — the validator requires it and it is the audit trail.
- Do not present pool-level REJECT results as evidence that all pairs are bad.
- When reporting shortlisted candidates, always source from pair-level.

---

## Code Style Constraints

- No external dependencies beyond Python stdlib. Scripts must run in CI with no `pip install`.
- Exit non-zero on fatal errors. No silent failures.
- No offline mode, no dummy data, no synthetic fallback at any point in the pipeline.
- `DATA_NOT_AVAILABLE` (not empty string) for all unavailable fields in CSV output.
- Log to `logs/` directory (auto-created) and also print to stdout.
- Scripts are standalone. Do not create shared helper modules without explicit instruction.

---

## File Modification Policy

| Path | Rule |
|---|---|
| `scripts/*.py` | Do not modify without explicit instruction |
| `data/*.csv` | Do not modify — pipeline output only |
| `data/raw/` | Do not modify — live API snapshots only |
| `reports/*.md` | Do not modify — pipeline output only |
| `.github/workflows/*.yml` | Do not modify without explicit instruction |
| `docs/DLMM_POOL_SCREENING_PROTOCOL.md` | Do not modify — reference protocol |
| `docs/VISION_PARKED.md` | Do not modify — parked vision document |
| `README.md` | Do not rewrite |
| `CLAUDE.md` (this file) | Update only when phase, gates, or constraints change |
| `docs/decision_log.md` | Append only — do not edit past entries |
| `docs/assumption_register.md` | Update in place when assumptions are reviewed |

---

## Decision and Assumption References

Key decisions that affect how this project is run:

- **DEC-20260629-001**: Pair-level is the primary view; pool-level is audit trail only.
- **DEC-20260629-002**: Risk flags at pair level are not always auto-rejects.
- **DEC-20260629-003**: Execution code comes after risk policy and state management.
- **DEC-20260629-004**: Telegram is the planned control-room interface (parked).
- **DEC-20260629-005**: Local artifacts must not override verified GitHub Actions results.

Full details in `docs/decision_log.md` and `docs/assumption_register.md`.

---

*Not financial advice. Research only. No live execution in this phase.*
