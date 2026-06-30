# DLMM Target Architecture

> Long-term target architecture and role boundaries for the Personal DLMM Automation Project.
> This document is descriptive and planning-only. It authorizes no execution.

---

## 1. Purpose

This document defines the **long-term target architecture** and the **role boundaries** for
the Personal DLMM Automation Project. It describes where the system is today, what the next
layer is, and what every future layer would have to look like *if and only if* governance
explicitly authorizes it.

This document **complements** `docs/project_checkpoint.md`. The checkpoint is the short,
always-read-first status note; this file is the longer architectural map behind it. Where
the two ever disagree, the checkpoint plus the governance docs (`docs/decision_log.md`,
`docs/assumption_register.md`, `docs/risk_policy_v0_1.md`) take precedence, and this file is
updated to match.

This document **does not** authorize, enable, or imply approval for any of the following:

- execution of on-chain actions
- wallet integration
- live trading
- LP add / remove / rebalance
- automation beyond the current gate

It is an architecture reference. It is not a change of phase, gate, or constraint.

---

## 2. Current Phase

**READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY**

**Current active architecture:**

```
Data → Screening → Classification → Validation → Observation
```

**Next planned architecture layer:**

```
Read-only Runtime Orchestrator
```

The project is **not yet** in any of the following, and this document does not move it into
them:

- paper trading
- position simulation
- Telegram control room
- tiny live
- live execution
- full automation

The Observation layer being in place means *stable enough for future paper-simulation
consideration only* — it is not paper-trade readiness and not live readiness (see
`docs/project_checkpoint.md` §10).

---

## 3. Hard Safety Boundary

The project remains:

**READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY**

Forbidden in every layer, present and future:

- No wallet
- No private key
- No signing
- No swap
- No LP add/remove
- No rebalance
- No live execution
- No `LIVE_ELIGIBLE_*`

**Every future layer must preserve this boundary until governance explicitly changes it.**
"Governance explicitly changes it" means a `docs/decision_log.md` entry, a green
`validation_gate`, and a reviewed risk policy module — not an inference, not a tool's
suggestion, not a convenience during implementation.

---

## 4. Target Layered Architecture

The target system is a strict layered stack. Lower-numbered layers know nothing about
higher-numbered layers; higher layers depend on the contracts of lower layers. No layer may
assume a capability that the safety boundary (§3) forbids.

Status legend:

- **IMPLEMENTED** — built, in the pipeline, CI-confirmed
- **PARTIAL** — built but not yet complete or not fully wired
- **NEXT** — the immediately next planned layer
- **FUTURE** — planned, not started, gated behind earlier layers
- **PARKED** — deliberately deferred; must not be built without explicit governance approval

### 1. Data Collector — IMPLEMENTED

- **Role:** Fetch raw, read-only public pool data from `https://dlmm.datapi.meteora.ag`.
- **Allowed:** HTTP GET against public endpoints; write raw snapshots to `data/raw/`;
  exit non-zero on fetch failure.
- **Forbidden:** No authentication, no wallet, no write-back to any external service, no
  data fabrication, no synthetic fallback.
- **Status:** IMPLEMENTED — `scripts/fetch_meteora_pools.py`,
  `scripts/fetch_ohlcv_top_pairs.py`.

### 2. Screening Builder — IMPLEMENTED

- **Role:** Map, score, and aggregate pools into pool-level and pair-level watchlists.
- **Allowed:** Deterministic scoring; pair aggregation via `group_by_pair()`; write
  `data/pair_watchlist.csv` and `data/pools_watchlist.csv`.
- **Forbidden:** No execution semantics; no merging of pair-level and pool-level views; no
  fabricated values (use `DATA_NOT_AVAILABLE`).
- **Status:** IMPLEMENTED — `scripts/build_watchlist.py`.

### 3. Data Validator — IMPLEMENTED

- **Role:** Enforce gate constraints and guardrails on every CSV output.
- **Allowed:** Fail the run when a guardrail is violated; check
  `validation_gate = red → max_allowed_action = PAPER_ONLY`; veto on volatility bucket;
  forbid `LIVE` strings and forbidden columns; enforce the malformed-pair-label guard.
- **Forbidden:** No mutation of pipeline data; no relaxation of guardrails without added
  tests; cannot itself authorize any action.
- **Status:** IMPLEMENTED — `scripts/validate_watchlist.py`.

### 4. Strategy Classifier — IMPLEMENTED

- **Role:** Assign `strategy_class_v2 ∈ {CORE, TACTICAL, REJECT, NOT_EVALUATED}` and
  companion columns at the pair level.
- **Allowed:** Classify; emit risk flags; route malformed/severe cases to REJECT/QUARANTINE;
  mark `OBSERVE_ONLY` / `PAPER_TEST_ALLOWED` (paper-only) / `NOT_EVALUATED`.
- **Forbidden:** `live_eligibility` may never be any `LIVE_ELIGIBLE_*` value; OHLCV
  unavailable → `NOT_EVALUATED`, never REJECT; no execution capability implied.
- **Status:** IMPLEMENTED (v0.2, CI-confirmed) — `scripts/classify_strategy.py`.

### 5. Observation Layer — IMPLEMENTED

- **Role:** Record strategy observations over time for future paper-simulation consideration.
- **Allowed:** Append observation records; produce observation summaries.
- **Forbidden:** Observation is **not** paper-trade authorization, not live authorization, not
  position creation.
- **Status:** IMPLEMENTED (Observation Readiness v0.1) — `scripts/observe_strategy.py`.

### 6. Runtime Orchestrator — NEXT

- **Role:** Run the read-only pipeline steps in sequence on the VPS, with logging, summaries,
  and a lock file.
- **Allowed:** Sequential step execution; logging; run summaries; overlap prevention; exit-code
  recording. Remains non-custodial and non-executing.
- **Forbidden:** No entry/exit decisions, no risk approval, no position creation, no Telegram
  command handling, no wallet/signing/swap/LP/rebalance/live execution.
- **Status:** NEXT — `scripts/run_readonly_pipeline.py` (see §6).

### 7. SSOT / Storage Layer — FUTURE

- **Role:** Durable single source of truth for run history and derived records.
- **Allowed:** Store pipeline runs, observations, classifications, risk flags, and (later)
  paper positions, state transitions, and Telegram events.
- **Forbidden:** No automatic commit-back to GitHub of runtime history without explicit
  approval; no storage of secrets, keys, or wallet material.
- **Status:** FUTURE — likely DuckDB on VPS (see §7).

### 8. Risk Engine — FUTURE

- **Role:** Apply risk appetite, limits, and tolerance; veto entries; cap exposure.
- **Allowed:** Veto entry; cap position size, active pool count, CORE and TACTICAL exposure;
  trigger freeze recommendation; recommend emergency exit.
- **Forbidden:** No direct signing, no direct execution, no bypassing the validator or the
  position manager.
- **Status:** FUTURE — has **veto authority but no execution authority** (see §8).

### 9. Signal Engine — FUTURE

- **Role:** Emit candidate signals only.
- **Allowed:** Output `ENTRY_CANDIDATE`, `EXIT_CANDIDATE`, `REBALANCE_CANDIDATE`, `NO_ACTION`.
- **Forbidden:** No direct transaction, no wallet access, no bypassing validator, risk engine,
  or position manager.
- **Status:** FUTURE (see §9).

### 10. Position Manager — FUTURE

- **Role:** Track position records and state when the phase allows.
- **Allowed:** Create/track position records; record entry/exit reasons; track near-range and
  out-of-range states; expose state to Telegram.
- **Forbidden:** No independent scoring, no bypassing risk policy, no private-key management,
  no direct execution.
- **Status:** FUTURE (see §10).

### 11. Paper Accounting — FUTURE

- **Role:** Simulate position economics on paper before any live consideration.
- **Allowed:** Record simulated paper positions with explicit assumptions and limitations.
- **Forbidden:** No real funds, no execution, no claim of precision beyond stated assumptions.
- **Status:** FUTURE — must come **before** live (see §11).

### 12. Telegram Control Room — FUTURE

- **Role:** Operator interface; read-only observer first.
- **Allowed (early):** Pipeline success/failure, daily summary, CORE/TACTICAL candidates, risk
  flags, and (later) paper position updates.
- **Forbidden:** Never direct wallet access or transaction signing; state-changing commands
  require governance approval, risk gates, logging, and confirmation rules.
- **Status:** FUTURE (see §12).

### 13. Execution Engine — PARKED

- **Role:** (Future-only) translate approved decisions into on-chain actions.
- **Allowed:** Nothing in the current or next phases — parked.
- **Forbidden:** Everything in §3 remains forbidden; this layer does not exist and is not to be
  built next.
- **Status:** PARKED — the **last** layer, not the next (see §13).

### 14. Kill Switch / Safety Controller — FUTURE

- **Role:** Highest-authority safety override.
- **Allowed:** Freeze new entries, disable TACTICAL mode, stop live mode, trigger emergency
  exit mode, mark system `KILLED`.
- **Forbidden:** Cannot itself be bypassed by lower engines; cannot be disabled silently.
- **Status:** FUTURE — overrides all lower-level engines (see §14).

### 15. Council / Governance Layer — PARTIAL

- **Role:** Human-and-docs authority over rules, gates, and risk.
- **Allowed:** Propose (AI) and approve (user/council); record major changes in the decision
  log; review risk policy changes.
- **Forbidden:** No automatic governance changes; no agent may silently revise live/risk rules.
- **Status:** PARTIAL — exists today as the governance docs and the user; not yet a tool
  (see §15).

### 16. Hermes / Learning Agent — FUTURE

- **Role:** Future learning/proposal agent over observation and paper history.
- **Allowed:** Analyze observation history and paper results; detect recurring failure modes;
  propose rule/threshold/strategy changes.
- **Forbidden:** No direct code change without review, no direct risk/live-rule change, no
  execution authority, no bypassing council/governance.
- **Status:** FUTURE — Hermes proposes; council/user decides (see §16).

---

## 5. Current Implemented Layers

The following layers are currently implemented or merged and CI-confirmed (see
`docs/decision_log.md` DEC-20260629-006/007/008 and `docs/project_checkpoint.md`):

- **Data Collector** — `scripts/fetch_meteora_pools.py`, `scripts/fetch_ohlcv_top_pairs.py`
- **Screening Builder** — `scripts/build_watchlist.py`
- **Data Validator** — `scripts/validate_watchlist.py`
- **Strategy Classification v0.2** — `scripts/classify_strategy.py`
- **Observation Readiness v0.1** — `scripts/observe_strategy.py`
- **GitHub Actions CI artifact pipeline** — `collect_and_validate` workflow, artifact-based
- **Project checkpoint** — `docs/project_checkpoint.md`

Current pipeline order:

```
fetch_meteora_pools.py
  → build_watchlist.py
  → fetch_ohlcv_top_pairs.py
  → classify_strategy.py
  → observe_strategy.py
  → validate_watchlist.py
```

---

## 6. Next Layer: Read-only Runtime Orchestrator

The next planned coding layer is a **read-only runtime orchestrator** to run the existing
pipeline on the VPS as a scheduled runner — not as new analytical logic.

**Target script:** `scripts/run_readonly_pipeline.py`

**Allowed responsibilities:**

- run the read-only pipeline steps sequentially
- create logs
- create run summaries
- prevent overlapping runs using a lock file
- record exit codes
- remain non-custodial
- remain non-executing

**Forbidden responsibilities:**

- no entry decision
- no exit decision
- no risk approval
- no position creation
- no Telegram command handling
- no wallet
- no signing
- no swap
- no LP
- no rebalance
- no live execution

**Runtime Orchestrator is NOT:**

- Risk Engine
- Signal Engine
- Position Manager
- Telegram Control Room
- Execution Engine

It is a scheduler and bookkeeper around the already-working read-only pipeline. It calls the
existing scripts; it does not modify them and does not add decision logic.

---

## 7. Future SSOT / Storage Layer

**Likely direction:** DuckDB on the VPS as a lightweight single source of truth (SSOT).

**Current rule:**

- GitHub Actions remains **artifact-only**.
- **No automatic commit-back** of runtime history to the repository unless explicitly
  approved (consistent with `docs/project_checkpoint.md` §9 and §11).

**The storage layer should eventually store:**

- pipeline runs
- observations
- classifications
- risk flags
- future paper positions
- future state transitions
- future Telegram events

The storage layer holds history only. It never holds wallet material, private keys, or any
secret, and it confers no execution capability.

---

## 8. Future Risk Engine

**Allowed responsibilities:**

- apply risk appetite
- apply risk limits
- apply risk tolerance
- veto entry
- cap position size
- cap active pool count
- cap CORE exposure
- cap TACTICAL exposure
- trigger freeze recommendation
- recommend emergency exit

**Forbidden:**

- no direct signing
- no direct execution
- no bypassing the validator
- no bypassing the position manager

**The Risk Engine has veto authority but no execution authority.** It can stop things and
shrink things; it can never place, sign, or send anything. This realises DEC-20260629-003
(risk policy module before any execution code) and draws its limits from
`docs/risk_policy_v0_1.md`.

---

## 9. Future Signal Engine

**Allowed output (candidate signals only):**

- `ENTRY_CANDIDATE`
- `EXIT_CANDIDATE`
- `REBALANCE_CANDIDATE`
- `NO_ACTION`

**Forbidden:**

- no direct transaction
- no wallet access
- no bypassing the validator
- no bypassing the risk engine
- no bypassing the position manager

A signal is a suggestion for downstream layers, never an instruction to an external network.

---

## 10. Future Position Manager

**Allowed responsibilities:**

- create position records when the phase allows
- track position state
- record entry reason
- record exit reason
- track near-range and out-of-range states
- expose state to Telegram

**Forbidden:**

- no independent scoring
- no bypassing risk policy
- no private-key management
- no direct execution

The Position Manager is the system of record for positions. It does not decide whether to
enter — it records and tracks what the risk-gated process has decided.

---

## 11. Future Paper Accounting

**Paper accounting must come before live.** No live position may be considered until paper
accounting works and a paper test cycle is recorded (this is what `validation_gate = green`
ultimately depends on).

A future paper position should record at least:

- `position_id`
- `strategy_class`
- `pair`
- `pool_address`
- `entry_time`
- `entry_price`
- `range_lower` / `range_upper`
- entry reason
- risk flags
- initial capital
- estimated fees
- adverse movement
- range status
- exit time
- exit reason
- estimated net result
- limitations

**Paper accounting does not need to be perfect on day one, but its assumptions and limitations
must be explicit.** A simulated number with a stated assumption is acceptable; a simulated
number presented as precise truth is not.

---

## 12. Future Telegram Control Room

**Initial Telegram role:** read-only observer.

**Allowed early events:**

- pipeline success/failure
- daily summary
- CORE candidates
- TACTICAL candidates
- risk flags
- paper position updates (later)

**Final Telegram may support commands later**, such as:

- `/status`
- `/positions`
- `/core`
- `/tactical`
- `/risk`
- `/freeze`
- `/kill`

**Constraints:**

- Telegram must **never** directly access a wallet or sign transactions.
- State-changing Telegram commands require **governance approval, risk gates, logging, and
  confirmation rules**.
- The bot token is always loaded from environment variables — never hardcoded or committed
  (DEC-20260629-004).

---

## 13. Future Execution Engine

**Status: PARKED.**

The Execution Engine is **future-only** and may only be considered after **all** of the
following exist and are reviewed:

- risk policy exists
- position state model exists
- paper accounting works
- Telegram critical alerts work
- kill switch exists
- security model exists
- tiny live governance approval exists

**Execution is the last layer, not the next layer.** Until every item above is true and a
decision log entry authorizes the live phase, no execution code is written, and the §3
boundary stands.

---

## 14. Kill Switch / Safety Controller

The Kill Switch is the **highest authority** in the runtime.

**Future allowed responsibilities:**

- freeze new entries
- disable TACTICAL mode
- stop live mode
- trigger emergency exit mode
- mark system as `KILLED`

**The Kill Switch overrides lower-level engines.** A freeze or kill from this layer cannot be
overridden by the Signal Engine, Risk Engine, Position Manager, or Execution Engine. Its
conditions are drawn from `docs/risk_policy_v0_1.md` §6 (Pause / Full Stop).

---

## 15. Council / Governance Layer

- **AI may propose.**
- **User / council approves.**
- Major rule changes require a `docs/decision_log.md` entry.
- Risk policy changes require review.
- No automatic governance changes.
- No agent may silently revise live/risk rules.

The governance layer is what makes every "FUTURE" and "PARKED" status above binding rather
than advisory. A status changes only by going through this layer.

---

## 16. Hermes / Learning Agent

Hermes is a **future learning/proposal agent**.

**Allowed:**

- analyze observation history
- analyze paper results
- detect recurring failure modes
- propose rule changes
- propose threshold changes
- propose strategy improvements

**Forbidden:**

- no direct code change without review
- no direct risk limit change
- no direct live rule change
- no execution authority
- no bypassing council/governance

**Hermes proposes. Council/user decides.** Hermes is a source of suggestions for the
governance layer, never an authority that can act on its own conclusions.

---

## 17. AI Role Split Is Functional, Not Vendor-Specific

This section is important.

The current workflow may use:

- **ChatGPT** as PM / Architect / Reviewer / Risk Gatekeeper / prompt writer
- **Claude Code** as the implementation agent

**This is not a permanent vendor dependency.** The tools above are a current convenience, not
a structural requirement.

The **durable roles** are:

- **PM / Architect / Reviewer / Risk Gatekeeper**
- **Implementation Agent**
- **Validator / CI**
- **Governance Docs**
- **User / Council**

**If paid ChatGPT or Claude subscriptions are unavailable, the roles still exist.** Only the
tool filling a role changes; the role boundary does not.

Possible replacements:

- the user manually acts as PM / reviewer / council
- repo docs become the primary memory
- GitHub Actions becomes the mandatory validator
- smaller scoped tasks replace large AI-assisted tasks
- free or limited AI tools may assist
- local AI may assist later
- another coding agent may replace Claude Code

**The role boundary remains unchanged even if the tool changes.**

---

## 18. Subscription Exit Plan

The user may stop the paid Claude / ChatGPT subscription in **around 20 days** (i.e. roughly
mid-July 2026 from today, 2026-06-30).

Therefore, **before subscription exit**, the project should prioritize **durable assets** that
live in the repository and survive without premium AI:

1. `docs/project_checkpoint.md`
2. `docs/target_architecture.md`
3. clear handoff prompts
4. GitHub Actions validation
5. unit tests
6. validator coverage
7. VPS read-only runner
8. runtime log / summary structure
9. storage policy decision
10. DuckDB schema skeleton if time allows

**The project must not depend on AI memory. The repository must become the memory.**

**Premium AI should accelerate the project, not become a hidden dependency.** Anything that
would stop working the day the subscription lapses is a liability and must be captured in the
repo before then.

---

## 19. Phase Gates

| Gate | Name | Status |
|---|---|---|
| Gate 1 | Research Pipeline | PASSED / MOSTLY PASSED |
| Gate 2 | Strategy Classification | PASSED |
| Gate 3 | Observation Readiness | PASSED |
| Gate 4 | Read-only VPS Runtime | NEXT |
| Gate 5 | SSOT / DuckDB Storage | FUTURE |
| Gate 6 | Risk Policy Engine | FUTURE |
| Gate 7 | Paper Position Engine | FUTURE |
| Gate 8 | Telegram Read-only Observer | FUTURE |
| Gate 9 | Tiny Live CORE | FUTURE |
| Gate 10 | Tactical Paper Automation | FUTURE |
| Gate 11 | Tactical Tiny Live | FUTURE |
| Gate 12 | Full 24/7 Automation | FUTURE |

Gates 1–3 are passed (research pipeline, strategy classification, observation readiness).
Gate 4 (read-only VPS runtime) is the next gate. Gates 5–12 are future and remain blocked by
the §3 safety boundary and the governance layer. No live gate (9+) opens while
`validation_gate = red` and `max_allowed_action = PAPER_ONLY`.

---

## 20. Coding Agent Rules

**Before coding, any coding agent must:**

- read `docs/project_checkpoint.md`
- read `docs/target_architecture.md`
- check `git status`
- confirm the current branch
- preserve the safety boundary
- modify only scoped files
- run relevant tests
- run the validator when pipeline behavior changes
- show changed files
- show the git diff summary
- not commit until reviewed, unless explicitly instructed

**Coding agents must not:**

- redesign architecture without approval
- introduce execution capability
- introduce wallet / signing / private-key handling
- silently change risk / governance rules
- bypass the validator
- bypass tests
- convert observation into paper / live authorization

---

## 21. Architecture Summary

Understand first.
Classify second.
Observe third.
Orchestrate safely fourth.
Store history fifth.
Simulate sixth.
Control risk seventh.
Automate last.
Scale only after evidence.

---

*Not financial advice. Research only. No live execution in this phase.*
