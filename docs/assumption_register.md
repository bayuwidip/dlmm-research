# Assumption Register

Active assumptions the project depends on. Each assumption should be reviewed at every
weekly journal entry. A violated or invalidated assumption requires a new decision log
entry before any code change is made in response.

Format per entry:
- **Date** — when the assumption was first recorded
- **Assumption** — the claim the project relies on, stated precisely
- **Basis** — evidence or reasoning that supports it
- **Risk if wrong** — what breaks and how severely
- **Review trigger** — the event or signal that should prompt re-examination
- **Mitigation plan** — what to do if the assumption turns out to be false

---

## ASM-20260629-001 — Meteora Datapi `/pools` Endpoint Remains Accessible

**Date:** 2026-06-29
**Assumption:** `https://dlmm.datapi.meteora.ag/pools` is a publicly accessible,
no-credential GET endpoint with a stable response schema:
`{ "data": [ { pool fields... } ] }`, paginated via `?page=N&page_size=100`.

**Basis:** Confirmed via successful fetch of 300 pools on 2026-06-29T08:15:45 UTC.
Rate limit documented as 30 RPS. Pipeline uses 0.5s inter-page delay. Schema verified
against the `fee_tvl_ratio` field unit (API value treated as percent; factor confirmed = 1.0
against raw data).

**Risk if wrong:** Entire pipeline fails at Step 1. `fetch_meteora_pools.py` exits non-zero.
No CSV is produced. GitHub Actions workflow fails. No candidates for paper test consideration.

**Review trigger:** Any CI run where `fetch_meteora_pools.py` exits non-zero, or where
`pool_count = 0` in the raw snapshot. Also review if Meteora announces API deprecation,
moves to an authenticated model, or changes the response schema.

**Mitigation plan:** No offline fallback by design (online-only). If schema changes,
update `map_pool()` in `build_watchlist.py` to match. If the endpoint is discontinued,
pause the project and identify an alternative source (e.g. Meteora's on-chain program
accounts, a different aggregator API) before resuming.

---

## ASM-20260629-002 — OHLCV Metrics Are Useful for Range-Risk Assessment

**Date:** 2026-06-29
**Assumption:** Hourly OHLCV data from `https://dlmm.datapi.meteora.ag/pools/{address}/ohlcv`
provides realized volatility, high-low range, and trend direction signals that are
meaningfully predictive of when a DLMM position will go out-of-range over a 1–7 day horizon.

**Basis:** Theoretical grounding: realized volatility (log-return standard deviation) is a
standard proxy for price dispersion. High-low range percentage is a natural proxy for the
width a position must have to stay in-range. Not yet empirically validated — the OHLCV
endpoint is currently returning `API_ERROR` in local runs (see ASM-20260629-006 and
DEC-20260629-005 for why this does not yet constitute a verdict on the endpoint).

**Risk if wrong:** `volatility_bucket` and `range_risk_bucket` columns would not correctly
predict out-of-range events. The volatility veto (capping high-volatility pairs at WATCHLIST)
would be based on noise rather than signal. Paper test records would be needed to validate
or refute this.

**Review trigger:** Once OHLCV data is flowing (confirmed via CI artifact), compare
`realized_volatility_pct` and `range_risk_bucket` values against actual observed out-of-range
events recorded during paper test. If predictive accuracy is poor, reassess the metric choice.

**Mitigation plan:** If OHLCV from datapi proves consistently unavailable or structurally
inappropriate, evaluate alternatives: Jupiter price API OHLCV, a CEX OHLCV feed for
correlated assets, or on-chain price oracle tick history.

---

## ASM-20260629-003 — High-Volatility Pairs Can Be Suitable for a TACTICAL Strategy Class

**Date:** 2026-06-29
**Assumption:** Not all high-volatility pairs should be permanently excluded. A future
`TACTICAL` strategy class — defined by short time-horizon positions, narrow bin steps,
and active monitoring — can make high-volatility pairs viable without violating the
project's low-maintenance intent for the other strategy classes.

**Basis:** Current protocol (§5 Catatan Kritis #6) imposes a hard veto capping
high-volatility pairs at WATCHLIST status. This veto is explicitly a **phase-1 constraint**
pending proven discipline, not a permanent architectural rule. The Charter's §10 concern
about monitoring burden applies to positions intended to run unattended — it does not
preclude a deliberately short-duration, actively monitored position type.

**Risk if wrong:** A TACTICAL class built too early (before discipline is proven) could
absorb disproportionate monitoring time and IL losses, undermining the low-maintenance
intent of the project and violating Charter §10.

**Review trigger:** After the first full paper test cycle completes. Assess whether
monitoring burden at high-volatility pairs during paper test stayed within acceptable bounds.
Do not introduce the TACTICAL class until this review occurs.

**Mitigation plan:** Keep the volatility veto active for STABLE and BLUECHIP classes
regardless of what happens with TACTICAL. TACTICAL classification must be gated by a
separate, explicit protocol section written in v0.2 or later — not assumed from this entry.

---

## ASM-20260629-004 — A Tiny Live Position Can Validate Execution Without Material Financial Risk

**Date:** 2026-06-29
**Assumption:** A USD 25–50 live position (per Charter §8) is small enough that execution
failures (wrong range entry, failed transaction, UI error, or minor misjudgment) produce
only learning value rather than meaningful financial harm, while still being large enough
to confirm that the full execution workflow functions correctly end-to-end.

**Basis:** Charter §8 explicitly sets this size range. Consistent with the project's total
capital cap of USD 500 and the no-top-up constraint. A $25–50 position represents 5–10%
of total capital — painful to lose entirely but not catastrophic.

**Risk if wrong:** Even a $25–50 position can be lost entirely to a rug, a smart contract
exploit, extreme IL, or a position that stays out-of-range indefinitely. The risk floor
is never zero. If the first live position is also the one that experiences a worst-case
event, the loss is real even if small in absolute terms.

**Review trigger:** This assumption is only active when `validation_gate = green`.
Until then it is parked. Review when at least one full paper test cycle is completed
and the live phase is under consideration.

**Mitigation plan:** Hard position-size cap enforced in the risk policy module (not yet
built — see `docs/risk_policy_v0_1.md`). Maximum 1 active position at any time per
Charter §9. Exit conditions must be written before entry. Enforce via decision checklist,
not only by code.

---

## ASM-20260629-005 — Telegram Bot API Is Sufficient as the Initial Control Room

**Date:** 2026-06-29
**Assumption:** A Telegram bot in polling mode (no webhook, no server) provides sufficient
real-time alerting and basic command handling for a solo operator managing at most 1
active LP position at a time.

**Basis:** Decision DEC-20260629-004. Telegram Bot API is free, well-documented, and
requires no infrastructure beyond a network connection. Supports rich text, inline
keyboards, and per-chat message history. Polling interval of 1–5 seconds is adequate
for a project where the monitoring cadence is once per day, not sub-minute.

**Risk if wrong:** Telegram has message delivery delays under load and occasional
API downtime. A polling bot cannot guarantee sub-second alert delivery. If the project
eventually requires near-real-time kill-switch triggers (e.g. price oracle breach alerts),
polling Telegram may be too slow.

**Review trigger:** When Telegram integration is being actively designed (currently parked).
At that point, evaluate the actual monitoring latency requirement against Telegram's
observed delivery latency under normal conditions.

**Mitigation plan:** If Telegram latency proves insufficient for a critical alert type,
supplement with a secondary channel (e.g. email via SMTP, SMS via a messaging API).
This is a future concern — no Telegram code is written in the current phase.

---

## ASM-20260629-006 — Local OHLCV API_ERROR Artifacts May Be Stale

**Date:** 2026-06-29
**Assumption:** The local `data/ohlcv_top_pairs.csv` and `reports/ohlcv_report.md`
showing `API_ERROR` for all 20 top pairs reflect a **transient or environment-specific
failure**, not a permanent unavailability of the OHLCV endpoint.

**Basis:** The endpoint URL pattern (`/pools/{address}/ohlcv?timeframe=...&start_time=...
&end_time=...`) is consistent with the documented datapi schema. The raw snapshot file
`data/raw/ohlcv_top_pairs_raw_latest.json` shows `"raw_by_pool": {}` (empty), confirming
that zero successful responses were received in that local run. However, a single local
run result is not sufficient to conclude that the endpoint is broken for all environments
or across all time. Network conditions, local proxy settings, or a transient API outage at
the time of the run could each produce this outcome.

**Risk if wrong:** If the endpoint is genuinely unavailable or has permanently changed its
response schema, then OHLCV-dependent features (volatility scoring, range-risk classification)
cannot be built from this source and an alternative must be identified.

**Review trigger:**
1. Download the latest GitHub Actions artifact for the `collect_and_validate` workflow.
2. Inspect `reports/ohlcv_report.md` from that artifact.
3. If the CI artifact also shows all `API_ERROR` across multiple separate runs on different
   days, escalate to investigating the endpoint directly.

**Mitigation plan:** If CI artifacts confirm persistent failure:
- Test the endpoint URL manually with `curl` or a browser to inspect the raw response.
- Compare response shape against what `extract_candles()` in `fetch_ohlcv_top_pairs.py`
  expects.
- If schema has changed, update `extract_candles()` to handle the new shape.
- If the endpoint is discontinued, identify an alternative (see ASM-20260629-002).

See also: DEC-20260629-005 (local artifacts must not override CI results).

---

*Assumptions are reviewed at each weekly journal entry (`journals/weekly_review_template.md`).*
*A violated assumption requires a decision log entry before any code change is made.*
