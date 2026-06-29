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

## Next Task: Strategy Classification v0.2

The next planned work unit is **Strategy Classification v0.2**.

Planned scope:
1. Diagnose and resolve the OHLCV API_ERROR — see the OHLCV section below before touching anything.
2. Integrate OHLCV-derived volatility as a scoring dimension at pair level (currently absent in v0.1).
3. Add a `strategy_type` classification output: `STABLE / BLUECHIP / TACTICAL`.
4. Extend `validate_watchlist.py` to cover any new columns introduced by v0.2.

**Do not begin v0.2 implementation until OHLCV status is confirmed from a verified
GitHub Actions artifact** (see OHLCV section below).

---

## OHLCV Status — Local Artifacts May Be Stale

**Warning:** Local files `data/ohlcv_top_pairs.csv` and `reports/ohlcv_report.md` may
reflect a transient failure, not the current API state. A local run showing `API_ERROR`
for all 20 pairs does not prove the endpoint is permanently unavailable.

**Before changing any OHLCV-related logic, verify the latest GitHub Actions artifact:**

1. Open GitHub Actions → workflow `Collect and Validate` → latest run.
2. Download the artifact `dlmm-run-<run_id>`.
3. Inspect `reports/ohlcv_report.md` from that artifact.
4. If the artifact also shows all `API_ERROR`, then investigate:
   - Whether the endpoint URL and query parameters match the current datapi schema.
   - Whether the pool addresses being queried are still active.
   - Whether the response shape differs from what `extract_candles()` expects.
5. Only after this investigation, modify `fetch_ohlcv_top_pairs.py`.

**Do not patch OHLCV scripts based only on local artifact state.**

See also: `docs/assumption_register.md` → ASM-20260629-006.

---

## Working Pipeline — Do Not Rewrite

The four-script pipeline is working and CI-tested. Do not refactor, rename, or
restructure the existing scripts without explicit instruction.

| Script | Role | Modification rule |
|---|---|---|
| `scripts/fetch_meteora_pools.py` | Step 1: fetch raw pools | Do not modify |
| `scripts/build_watchlist.py` | Step 2: map + score + write CSVs | Do not modify |
| `scripts/fetch_ohlcv_top_pairs.py` | Step 3: OHLCV tool-test | Do not modify until CI verified |
| `scripts/validate_watchlist.py` | Step 4: gate enforcement | Do not modify without adding tests |

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
- `volatility_pct` — requires OHLCV endpoint (separate, currently failing locally)

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
