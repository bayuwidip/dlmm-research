# Risk Policy v0.1 — DRAFT

> ## ⛔ STATUS: DRAFT — NOT YET ACTIVE
>
> This document is a **design specification** for the live phase, which has not begun.
>
> **No live execution code should be written based on this document.**
>
> This policy becomes active only when ALL of the following are simultaneously true:
> 1. `validation_gate = green` (at least one complete paper test cycle recorded).
> 2. Owner scope gate = green (already green as of 2026-06-29).
> 3. A decision log entry (`docs/decision_log.md`) explicitly authorizes live phase start.
> 4. The risk policy module has been built, tested, and reviewed as a separate code unit.
>
> Until then: `max_allowed_action = PAPER_ONLY` on all rows, in all CSVs, always.
>
> See DEC-20260629-003: execution code comes after the risk policy module, not before.

---

## 1. Risk Appetite

This project is **capital-preservation-first**. The primary goal is to learn how Meteora
DLMM works in practice. Any fee income is secondary. No strategy is worth breaking the
constraints below.

- Total capital at risk: **USD 500, hard cap, no exceptions, no top-up ever**.
- Source of funds: **disposable only**. Nothing needed for living expenses, savings goals,
  emergency fund, or wedding budget may be allocated.
- Acceptable outcome: modest fee income that beats a simple hold benchmark over the
  observation period. Matching stablecoin yield is a success. Losing the full USD 500
  is painful but not catastrophic — it was disposable to begin with.
- Unacceptable outcome: any top-up, any use of non-disposable funds, any emotional or
  occupational impact that lasts more than one week.

---

## 2. Risk Limits (Hard — Non-Negotiable)

These are binary constraints. A future risk policy module must enforce them mechanically.
They are not advisory.

| Limit | Value | Notes |
|---|---|---|
| Maximum total capital deployed | USD 500 | Includes all positions, ever. Not per position. |
| Maximum simultaneous open positions | 1 | No exceptions. Close before opening another. |
| Maximum size per position | USD 50 | Enforced at entry. Cannot be increased mid-position. |
| Minimum size per position | USD 25 | Below this, gas and fees consume a disproportionate fraction. |
| Maximum project drawdown — warning threshold | 15% of starting capital | Triggers mandatory pause. |
| Maximum project drawdown — halt threshold | 25% of starting capital | Triggers full project stop. |
| Minimum paper test duration before live entry | 3 days of recorded observations | Gate check, not waivable. |
| Maximum holding duration without manual review | 7 days | If no review occurs within 7 days, position is closed. |

---

## 3. Risk Tolerance (Soft — Guidance for Judgment Calls)

These are not hard rules but they frame the decision space. Violating them requires a
written note in the journal entry for that week.

- **IL tolerance:** Accept impermanent loss up to the point where simulated fee income
  covers it over the paper test horizon. If paper test fee income does not cover simulated IL
  over 3 days → pair goes to WATCHLIST, not to live.
- **Volatility tolerance:** First live position must be in a low-volatility pair (STABLE or
  BLUECHIP class). High-volatility pairs (TACTICAL class) are only considered after
  discipline is proven in at least one completed low-volatility live cycle.
- **Monitoring tolerance:** Only enter positions that can be checked once per day without
  disrupting work, sleep, or commitments. If checking feels urgent or intrusive → wrong pair.
- **Complexity tolerance:** Only enter a pool whose fee and return mechanics can be explained
  in two sentences, clearly and without qualification. Any uncertainty fails Protocol §6
  question 14.

---

## 4. No-Entry Conditions

A live position **must not** be opened if any of the following apply, regardless of the
pair's score or how attractive it appears:

1. The paper test observation window for this pair has not reached 3 full days.
2. Any question in Protocol §6 manual checklist cannot be answered clearly and in writing.
3. Emotional state at entry time is not neutral — FOMO, urgency, desire to recover a loss,
   or feeling "hot" → mandatory 24-hour cooling period, decision is cancelled and must be
   re-evaluated from scratch.
4. `validation_gate` is not green.
5. A position is already open (maximum 1 simultaneous position).
6. The pair's `max_allowed_action` in `pair_watchlist.csv` is not `LIVE_SMALL` or higher
   (when such a status exists in a future phase).
7. Exit conditions for this specific position have not been written down before entry.
8. This risk policy document is still in DRAFT status.

---

## 5. Emergency Exit Conditions

Exit an active position **immediately**, without waiting for the next scheduled review,
if any of the following occur:

1. Pool liquidity (active TVL) drops more than 50% in a single day with no identifiable
   benign cause (e.g. market-wide event vs. pool-specific exit).
2. Either token's holder count drops more than 20% in a rolling 7-day window.
3. A security incident, exploit, or credible rug report is published for either token
   or for the pool's smart contract.
4. Price has been continuously out-of-range for more than 48 hours with no return in sight
   and no rebalance option available.
5. A personal life event (work crisis, medical emergency, pre-wedding obligations) makes
   monitoring impossible for more than 3 consecutive days.

Emergency exit does not require journal approval first — exit first, record second.
The journal entry for that week must document the exit, the trigger, and the outcome.

---

## 6. Kill Switch Conditions

### Pause (close position, stop all new entries until the condition is resolved)

- Project drawdown reaches 15% of starting capital (USD 75 loss from a USD 500 start).
- Any entry is made without a completed journal entry documenting the rationale.
- Monitoring is interfering with work performance, sleep, or other commitments on 2 or
  more consecutive days.
- An emotional rule violation occurred: entry during FOMO, averaging down on a losing
  position, or any action taken to "make back" a loss.

Resolution: the pause continues until the triggering condition is resolved and a journal
entry is written acknowledging what happened and what will be done differently.

### Full Stop (project ends — no restart, no substitution)

- Project drawdown reaches 25% of starting capital (USD 125 loss from a USD 500 start).
- A top-up occurs using non-disposable funds.
- After completing a full observation window, the net result does not beat the hold benchmark.
- An ethics concern arises that is not fully resolved within 1 week.
- Inability to follow the rules in this document for 2 or more consecutive weeks.

Per Charter §17: if the project reaches a full stop, it is **not replaced** by another
trading or DeFi project as a substitute outlet. The stop is final for this iteration.

---

## 7. Implementation Note — No Live Execution Code Yet

No transaction-signing or execution code exists in this repository. This document is a
policy design specification only.

When the live phase is eventually authorized (after `validation_gate = green` and a
decision log entry confirms it), the implementation sequence is:

1. Write and review the risk policy module (`scripts/risk_policy.py` or similar) that
   reads `config/risk_policy.yaml` and exposes enforcement functions.
2. Write and review a state management layer that tracks open positions, drawdown, and
   position history.
3. Only after both are tested: write execution code.
4. All three components require separate review before any real transaction is signed.

This order is mandated by DEC-20260629-003 and is not optional.

---

*Risk Policy v0.1 — DRAFT. Not yet active.*
*Tunduk pada DLMM Trading Charter v0.1 dan DLMM Pool Screening Protocol v0.1.*
*Not financial advice.*
