# config/ — Configuration Files (Reserved)

This directory is reserved for machine-readable configuration that future pipeline
stages will consume. **No config files exist yet.**

Files will be created here only when the feature they configure is actively being built
and authorized. Do not create config files preemptively — premature config introduces
a divergence risk between the config values and the hardcoded constants that the
scripts and validators currently rely on.

---

## Planned Config Files

### `classification.yaml`

**Purpose:** Define strategy classification rules for pair candidates.
**Used by:** Future `scripts/classify_pairs.py` (not yet written).
**When to create:** When Strategy Classification v0.2 is actively being implemented,
after OHLCV data is confirmed flowing via CI artifact.

**Contents will include:**
```yaml
version: "0.2"
strategy_classes:
  STABLE:
    description: "Low-volatility pairs suitable for low-maintenance LP"
    min_pair_score: 70
    max_volatility_bucket: "LOW"
    min_fee_tvl_pct: 0.05
  BLUECHIP:
    description: "High-TVL established pairs, moderate volatility acceptable"
    min_pair_score: 70
    max_volatility_bucket: "MODERATE"
    min_total_tvl_usd: 1000000
  TACTICAL:
    description: "Short-duration, actively monitored high-volatility positions"
    min_pair_score: 75
    max_volatility_bucket: "HIGH"
    requires_paper_test_days: 5
    enabled: false   # not active until volatility tracking is validated
```

**Constraint:** Classification rules must be consistent with the protocol veto rules
in `docs/DLMM_POOL_SCREENING_PROTOCOL.md` §5. If they conflict, the protocol wins.

---

### `risk_policy.yaml`

**Purpose:** Machine-readable version of `docs/risk_policy_v0_1.md`.
**Used by:** Future risk policy module (not yet written — see DEC-20260629-003).
**When to create:** Only after `docs/risk_policy_v0_1.md` exits DRAFT status,
`validation_gate = green`, and a decision log entry authorizes live phase start.

**Contents will include:**
```yaml
version: "0.1"
status: "DRAFT"   # must be "ACTIVE" before any execution code uses this file
hard_limits:
  max_total_capital_usd: 500
  max_simultaneous_positions: 1
  max_position_size_usd: 50
  min_position_size_usd: 25
  drawdown_pause_pct: 15
  drawdown_halt_pct: 25
  min_paper_test_days: 3
  max_holding_days_without_review: 7
```

**Security note:** This file must never contain wallet addresses, private keys, or
API credentials. Those are loaded from environment variables only.

---

### `scoring_thresholds.yaml`

**Purpose:** Externalize scoring rubric thresholds currently hardcoded in `build_watchlist.py`.
**Used by:** A future refactored scoring engine (not yet written).
**When to create:** Only if the scoring engine is explicitly decoupled from
`build_watchlist.py` as a separate module. Do not create this file simply to
"clean up" the script — the hardcoded constants are currently the authoritative
reference for the validator and are easier to audit in-place.

**Contents will include:**
```yaml
version: "0.1"
hard_filter:
  min_mcap_usd: 500000
  min_tvl_usd: 10000
  min_volume_24h_usd: 10000
  min_holders: 200
pair_scoring_weights:
  liquidity: 0.30
  volume: 0.20
  fee: 0.20
  token_quality: 0.15
  pool_diversity: 0.10
  data_quality: 0.05
status_thresholds:
  reject_below: 50
  watchlist_below: 70
  paper_test_below: 85
fee_eligibility:
  min_tvl_usd: 10000
  min_volume_24h_usd: 10000
volatility_buckets:
  low_below_pct: 3.0
  moderate_below_pct: 8.0
  high_below_pct: 15.0
```

**Constraint:** Any change to values here must be mirrored in `validate_watchlist.py`
if those values are currently part of validator logic.

---

### `runtime.yaml`

**Purpose:** Control pipeline runtime parameters that may need to differ between
local runs and CI, or that an operator may want to tune without touching script code.
**Used by:** All pipeline scripts, loaded at startup.
**When to create:** When the pipeline requires environment-specific configuration.
Currently, constants are hardcoded per-script and are consistent across environments,
so this file is not yet needed.

**Contents will include:**
```yaml
version: "0.1"
api:
  base_url: "https://dlmm.datapi.meteora.ag"
  timeout_seconds: 30
  rate_limit_delay_seconds: 0.5
  user_agent: "dlmm-research-collector/0.2 (read-only; research; online-only)"
fetch_pools:
  page_size: 100
  max_pages: 3
ohlcv:
  timeframe: "1h"
  lookback_hours: 72
  top_n_candidates: 20
  per_pool_delay_seconds: 0.4
logging:
  level: "INFO"
  dir: "logs"
```

---

### `telegram_events.yaml`

**Purpose:** Define which pipeline events trigger Telegram notifications and the
message template for each event type.
**Used by:** Future Telegram alert module (parked — see DEC-20260629-004).
**When to create:** When Telegram integration is authorized. Not in current phase.

**Contents will include:**
```yaml
version: "0.1"
# Bot token must be loaded from environment variable TELEGRAM_BOT_TOKEN.
# Never hardcode a token here.
chat_id_env_var: "TELEGRAM_CHAT_ID"

events:
  OHLCV_ALL_OK:
    severity: "info"
    template: "OHLCV: all {count} pairs returned OK. Top vol: {top_pair} ({rv_pct}% RV)."
  OHLCV_ALL_ERROR:
    severity: "warning"
    template: "OHLCV: all {count} pairs returned API_ERROR. Check CI artifact."
  PAIR_SCORE_HIGH:
    severity: "info"
    template: "Pair {pair} scored {score} — eligible for paper test consideration."
  VALIDATION_FAILED:
    severity: "error"
    template: "Validator FAILED. {error_count} errors. Check artifact for details."
  KILL_SWITCH_TRIGGERED:
    severity: "critical"
    template: "KILL SWITCH: {reason}. Drawdown {drawdown_pct}%. Check immediately."
  PAPER_TEST_DAY_LOG:
    severity: "info"
    template: "Paper test day {day}: {pair} fee est {fee_est} | price in-range: {in_range}"
```

**Security constraint:** `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are always
environment variables. Never commit tokens to the repository.

---

## Notes for All Config Files

- All config files use YAML format.
- Config values **never override validator gate constraints**. Gate enforcement lives
  in `validate_watchlist.py` and is not configurable via YAML.
- A `version:` field is required in every config file. Version must match the
  corresponding policy document version when applicable.
- Credentials (Telegram token, any future wallet address, any API key) are always
  loaded from environment variables — never from config files committed to the repository.
