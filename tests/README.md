# tests/ — Test Suite (Reserved)

This directory is reserved for automated tests. **No tests exist yet.**

The project is in READ_ONLY / PAPER_ONLY phase. The pipeline's primary correctness
guarantee is the live API + validator cycle running in CI — not a mock-based test suite.
A formal test suite will be added incrementally as scoring logic grows complex enough
that a silent regression becomes a realistic risk.

---

## When to Add Tests

Add tests when:
- A new scoring function has non-trivial branching that a future change could break silently.
- The validator (`validate_watchlist.py`) adds a new rule that must be verified in isolation.
- A new data-transformation script is added alongside the existing pipeline.
- A live safety property (no wallet columns, no LIVE status under red gate) needs a
  mechanical check that runs on every commit.

Do not add tests as a reflexive practice for all scripts. The live API cycle already
exercises the fetch → build → validate path end-to-end, and the validator enforces
correctness constraints on CSV output. Unit tests for trivial wrappers around stdlib
calls add maintenance cost without adding safety.

---

## Planned Test Categories

### `tests/unit/`

**Purpose:** Verify pure functions in isolation — fixed inputs in, deterministic outputs
out, no file I/O, no network calls.

**Coverage targets:**

| Function | Location | What to verify |
|---|---|---|
| `score_liquidity_pair(total_tvl)` | `build_watchlist.py` | Breakpoints match protocol §4A; `NA` input → 10 |
| `score_volume_pair(total_vol)` | `build_watchlist.py` | Breakpoints; `NA` → 10 |
| `score_fee_pair(best_pct)` | `build_watchlist.py` | Threshold values; `NA` → 0 |
| `score_token_quality_pair(...)` | `build_watchlist.py` | `blacklisted=1 → 0`; MCAP/holder ladder |
| `score_pool_diversity_pair(pool_count, bin_step_count)` | `build_watchlist.py` | Single-pool → 40; multi-step → 100 |
| `score_data_quality_pair(sanity_flag)` | `build_watchlist.py` | All four flag values |
| `assign_pair_status(score, blacklisted, elig, sanity)` | `build_watchlist.py` | Blacklisted override; eligible=0 cap; score ladder |
| `bucket_from_pct(vpct)` | `build_watchlist.py` | NA passthrough; numeric boundaries |
| `hard_filter(m)` | `build_watchlist.py` | Each of the 4+ rejection conditions independently |
| `vol_bucket(rv)`, `range_bucket(hl)`, `trend_dir(pct)` | `fetch_ohlcv_top_pairs.py` | All boundaries including edge values |
| `extract_candles(raw)` | `fetch_ohlcv_top_pairs.py` | Dict with "data" key; list directly; unknown shape → (None, reason) |
| `compute_metrics(candles)` | `fetch_ohlcv_top_pairs.py` | Known-value fixture; < 2 candles → None |

**Framework:** Python `unittest` (stdlib only, no `pytest` dependency required). One
test file per source module:
- `tests/unit/test_build_watchlist.py`
- `tests/unit/test_fetch_ohlcv.py`

Tests must not import from scripts by modifying `sys.path` in unexpected ways — use
a standard `importlib` approach or restructure the function into a testable helper module
only when the test is actually being written.

---

### `tests/negative/`

**Purpose:** Verify that the pipeline and validator correctly detect and reject bad inputs —
malformed data, missing files, constraint violations, and adversarial column names.

**Coverage targets:**

| Scenario | Expected behavior |
|---|---|
| `fetch_meteora_pools.py` receives empty list from API | Exit non-zero |
| `build_watchlist.py` called without `_latest.json` | Exit non-zero, clear error message |
| Pool field is missing from API response | Written as `DATA_NOT_AVAILABLE`, not guessed |
| `validate_watchlist.py` — each of the 14 pool-level rules violated individually | Each produces a specific error, not a generic failure |
| `validate_watchlist.py` — `blacklisted > 0` but `pair_status ≠ REJECT` | Rule fires |
| `validate_watchlist.py` — `eligible = 0` and `pair_status = PAPER TEST` | Rule fires |
| OHLCV CSV with a column named `wallet` | Forbidden-column rule fires |
| OHLCV CSV with a column named `private_key` | Forbidden-column rule fires |
| `extract_candles()` receives a dict without known list keys | Returns `(None, reason)` not crash |
| `extract_candles()` receives a non-dict, non-list type | Returns `(None, reason)` not crash |
| `compute_metrics()` receives fewer than 2 valid candles | Returns `None` not crash |

**Approach:** Prepare minimal fixture CSV files and JSON blobs in `tests/fixtures/`.
No live API calls in negative tests. Each test case uses the smallest input that triggers
the specific condition.

---

### `tests/scenarios/`

**Purpose:** Simulate realistic end-to-end data transformations using fixture data.
Verify that the pipeline produces the expected output shape and business logic from
controlled inputs.

**Coverage targets:**

| Scenario | What to assert |
|---|---|
| 5 pools from 3 token pairs | `group_by_pair()` produces exactly 3 groups |
| 1 pair has `blacklisted_pool_count > 0` | Pair gets `REJECT` regardless of score |
| 1 pool in a pair has fee ratio 1000× higher than others | `low_tvl_distortion` sanity flag fires |
| All rows have `validation_gate = red` | All rows have `max_allowed_action = PAPER_ONLY` |
| OHLCV fixture with 72 candles of known values | Computed `pct_change`, `realized_volatility_pct`, `max_drawdown_pct` match hand-calculated expected values within tolerance |
| A pair where `eligible_fee_pool_count = 0` and base score would be PAPER TEST | Status capped at WATCHLIST |
| A pair with score 49 | Gets REJECT |
| A pair with score 70 | Gets PAPER TEST (not WATCHLIST) |

**Approach:** Fixture JSON files in `tests/fixtures/raw/` that mimic the datapi response
schema. Tests call `build_rows()`, `group_by_pair()`, `compute_metrics()` directly with
fixture data and assert on the output dict/list structure.

**Fixture naming convention:**
- `tests/fixtures/raw/fixture_5pools_3pairs.json`
- `tests/fixtures/raw/fixture_ohlcv_72candles.json`
- Fixture files must use clearly fake pool addresses (e.g. `FIXTURE_POOL_ADDR_001`)
  and must NOT contain real token prices or fee data.

---

### `tests/live_safety/`

**Purpose:** Enforce non-negotiable project safety constraints at the code level.
These tests scan the repository itself — not fixture data — and must always pass.
A failure here means a forbidden pattern was introduced into the codebase.

**Coverage targets:**

| Check | What triggers a failure |
|---|---|
| Forbidden imports in `scripts/*.py` | `solana`, `solders`, `anchorpy`, `web3` (Ethereum), any signing library |
| Forbidden string literals in `scripts/*.py` | `private_key`, `sign_transaction`, `send_transaction`, `execute_swap`, `add_liquidity`, `remove_liquidity` |
| Forbidden column names in `data/*.csv` | Any header containing `wallet`, `private_key`, `signature`, `execute`, `swap` |
| `validation_gate = red` rows in `data/pair_watchlist.csv` | Any row where `max_allowed_action ≠ PAPER_ONLY` |
| GitHub Actions workflow | Any env var named `PRIVATE_KEY`, `WALLET_SECRET`, `SEED_PHRASE`, or similar |
| `config/*.yaml` (when they exist) | Any literal token or key value (not a `${...}` env var reference) |

**When to run:** On every commit via a CI step added to `collect_and_validate.yml`.
These tests must run before the validate step, not after, so a failure blocks the artifact upload.

**Approach:** Use Python `unittest` with file-scanning logic (read files as text,
`assert pattern not in content`). No mocking required — these tests operate on the
actual repository files.

---

## Fixture Policy

- All fixtures live in `tests/fixtures/`.
- Fixture pool addresses must be clearly fake: use the pattern `FIXTURE_POOL_ADDR_NNN`.
- Fixture token addresses must be clearly fake: use `FIXTURE_TOKEN_ADDR_NNN`.
- Fixture files must not contain real token prices, real fee data, or any value that
  could be mistaken for a live trading signal.
- Add a `"_fixture_note": "NOT PRODUCTION DATA"` field to all fixture JSON files.

---

## Running Tests (Future)

```bash
# All categories
python -m pytest tests/

# By category
python -m pytest tests/unit/
python -m pytest tests/negative/
python -m pytest tests/scenarios/
python -m pytest tests/live_safety/

# Without pytest (stdlib only)
python -m unittest discover -s tests/unit/
python -m unittest discover -s tests/live_safety/
```

**Dependency constraint:** No test dependencies beyond Python stdlib and `pytest`.
If `pytest` is not installed, all tests must also be runnable via `python -m unittest discover`.
This keeps CI consistent with the project's no-external-dependency policy.
