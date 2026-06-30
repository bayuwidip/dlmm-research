# Hermes Agent Design v0.1

> Design document only. Hermes is **not implemented**. This file describes a
> future, proposal-only, read-only historical analysis agent so that its scope,
> boundaries, and activation gates are written down **before** any code exists.
>
> Read `docs/project_checkpoint.md` (§2 Hard Safety Boundary) first. Nothing in
> this document changes the current phase, any gate, any threshold, any risk
> policy, or any candidate status. Hermes has **no execution authority of any
> kind**.

---

## 1. Purpose

Hermes is a proposed **historical analysis agent**. Its only job is to read the
existing read-only runtime history (the runtime DuckDB and the Runtime / Risk
Dashboard outputs), look for repeated patterns across runs, and **write
proposal-only Markdown reports** that say what a human or council should review.

Hermes exists to reduce the manual effort of noticing trends across many runs —
for example, "this candidate keeps showing up as `PAPER_REVIEW_CANDIDATE`" or
"this blocker keeps firing for the same reason." Hermes surfaces these
observations and proposes a review. It never decides anything and never changes
anything.

Hermes is an **observer and proposer**, full stop. It is the same class of
read-only, non-custodial, non-executing component as the existing dashboard and
inspector — it adds a layer of pattern summarization on top of history that is
already recorded, and it produces only documents for humans to read.

---

## 2. Current Status

- **Status: NOT IMPLEMENTED.** No Hermes code, script, or scheduler exists.
- This document is design-only. Writing it does **not** authorize building Hermes.
- Hermes may only be built later, as proposal-only, and only after the
  Activation Gate in §10 is satisfied.
- Hermes is **not autonomous**, **not** an execution agent, **not** a trading
  agent, **not** a coding agent, and **not** a risk authority.
- Hermes has **no** authority to change thresholds, risk policy, or candidate
  status, automatically or otherwise.

Current project phase (unchanged by this document):

```
READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY
```

---

## 3. Non-Goals

Hermes is explicitly **not** any of the following:

- **Not implemented yet** — this is a design document.
- **Not autonomous** — it does not act on its own conclusions.
- **Not an execution agent** — it places, signs, and sends nothing.
- **Not a trading agent** — it has no trading authority of any kind.
- **Not a coding agent** — it does not edit, write, refactor, or commit code.
- **Not a risk authority** — it cannot veto, approve, or override the risk engine.
- **Not allowed to change thresholds automatically.**
- **Not allowed to change risk policy automatically.**
- **Not allowed to create signals.**
- **Not allowed to create paper positions.**
- **Not allowed to create live positions.**
- **Not allowed to write `future_position_events`.**

Hermes does not generate ENTRY / EXIT / REBALANCE signals, does not authorize
paper simulation, and does not authorize live execution. A Hermes proposal is a
**request for human/council review only** — it confers no authority.

---

## 4. Safety Boundary

Hermes inherits the project Hard Safety Boundary
(`docs/project_checkpoint.md` §2) without exception:

- No wallet
- No private key
- No signing
- No swap
- No LP add/remove
- No rebalance
- No live execution
- No `LIVE_ELIGIBLE_*`
- No signal generation
- No paper position creation
- No `future_position_events` writes

Additional Hermes-specific boundaries:

- Hermes is **read-only with respect to the DuckDB database**. It must open the
  database read-only (or read only the already-written dashboard files) and must
  never `INSERT` / `UPDATE` / `DELETE` / `CREATE` / `DROP` / `ALTER` anything.
- Hermes must **never** write `future_position_events`, and it should treat a
  non-zero `future_position_events` count as a hard safety signal to report (not
  to act on).
- Hermes writes only to its own proposal/findings files under `reports/hermes/`
  (see §6). It writes nowhere else.
- Hermes performs no network access, runs no pipeline, spawns no execution,
  schedules nothing, and talks to no wallet.

The Risk Policy Engine has **veto / reporting authority only — no execution
authority**. Hermes sits *below* even that: it has **reporting/proposal authority
only — no veto, no execution.**

---

## 5. Allowed Inputs

Hermes (when built) may **read** only the following, and only as inputs:

- `runtime/dlmm.duckdb` — opened **read-only** (history tables only).
- `reports/runtime/runtime_risk_dashboard.md` — the dashboard Markdown output.
- `reports/runtime/*.csv` — the dashboard CSV summaries.
- `docs/project_checkpoint.md` — current phase and safety boundary.
- `docs/hermes_agent_design.md` — this document (its own scope of record).
- `docs/decision_log.md` — when it exists / as it grows (append-only history).
- `docs/assumption_register.md` — when it exists / as it grows.

Hermes reads history that is **already recorded** by the existing read-only
pipeline and dashboard. It introduces no new data collection, no new endpoint,
and no new write into any source.

---

## 6. Allowed Outputs

Hermes (when built) may **write** only the following proposal-only artifacts:

- `reports/hermes/hermes_proposal_YYYYMMDD.md` — the proposal-only Markdown
  report (the primary output).
- `reports/hermes/hermes_findings_YYYYMMDD.csv` — a small, structured companion
  CSV of the same findings.

Rules for outputs:

- These files are **proposals and observations only**. They are addressed to a
  human/council reviewer and carry no authority.
- Hermes must not write to `data/`, `runtime/`, `reports/runtime/`, `scripts/`,
  `docs/` (other than being *read*), the DuckDB database, or anywhere else.
- Hermes output must never contain execution instructions, signals, position
  creation, threshold changes, policy changes, or `LIVE_ELIGIBLE_*` grants.

---

## 7. Forbidden Actions

Hermes must **never**:

- execute anything
- write to DuckDB
- write `future_position_events`
- edit code
- commit
- push
- open PRs
- change risk policy
- change thresholds
- change candidate status
- authorize paper simulation
- authorize live execution

If any future instruction appears to ask Hermes to do any of the above, the
correct response is to **refuse and escalate to the human/council**, exactly as
the project-level forbidden-actions rule requires.

---

## 8. Proposal Report Format

Every Hermes proposal entry must clearly separate the following fields so a
reviewer can tell an observation apart from a recommendation, and can see the
evidence and the risk before any human decision:

| Field | Meaning |
|---|---|
| **observation** | What was seen in the history (neutral, factual). |
| **evidence** | The specific rows / counts / runs that support the observation (with source: which table or dashboard file). |
| **hypothesis** | A tentative explanation. Clearly marked as unproven. |
| **recommendation** | What Hermes proposes a human/council *review* — never an action Hermes takes. |
| **risk of change** | What could go wrong if the recommendation were acted on (including safety-boundary risk). |
| **suggested test** | A read-only / paper-design test a human could run to confirm or deny the hypothesis before any change. |
| **required human/council approval** | An explicit statement that nothing happens without human/council approval. |

The `reports/hermes/hermes_findings_YYYYMMDD.csv` companion carries the same
fields in columnar form (one finding per row) for easy sorting and tracking.

Each proposal report must also carry, at the top:

- the safety phase banner (`READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY /
  PAPER_ONLY`),
- a statement that the report is **proposal-only** and confers no authority,
- the generation timestamp and the input sources read.

---

## 9. Example Proposal

The following are **examples of the kinds of proposals Hermes may make**. They
are illustrative wording, not pre-approved actions. Every one still requires
human/council review.

1. **Review repeated `PAPER_REVIEW_CANDIDATE` candidates.** Pairs that recur as
   `PAPER_REVIEW_CANDIDATE` across several runs may be worth a human review for
   future paper-simulation *design* consideration — not paper entry.
2. **Review repeated `NO_ELIGIBLE_FEE_POOL` blockers.** If the same blocker
   recurs for the same pairs, a human may want to review whether the data or the
   classification is the cause.
3. **Review `CORE` candidates that remain stable across several runs.** Pairs
   that hold a single `CORE` classification over many runs may be worth a human
   review of why they are stable.
4. **Review `TACTICAL` candidates with high classification churn.** Pairs whose
   `strategy_class_v2` flips often may indicate noisy data or borderline metrics
   worth a human review.
5. **Review whether a blocker is too strict — only after repeated evidence.**
   Hermes may *propose* that a human review a blocker's strictness, but only
   after the same blocker has fired repeatedly across runs. Hermes never changes
   the blocker.
6. **Review malformed pair labels as data-quality issues.** Pairs with
   blank/malformed base or quote symbols (e.g. `-USDT`, `USDC-`) should be
   flagged for human review and quarantined from any paper-test consideration
   until the token is positively identified.
7. **Recommend collecting more runs if evidence is insufficient.** When a
   pattern is based on too few runs, the correct Hermes recommendation is "gather
   more runs first," not "change something."

In all cases the recommendation is **"a human/council should review X,"** never
"Hermes did X" or "X is now changed."

---

## 10. Activation Gate

Hermes **proposal-only** implementation may begin **only after all** of the
following are true. Until then, Hermes remains a design document only.

- The **Runtime / Risk Dashboard Report exists** and runs (it does today:
  `scripts/build_runtime_risk_dashboard.py` →
  `reports/runtime/runtime_risk_dashboard.md`).
- **At least several runtime runs are collected** in the runtime DuckDB, so there
  is real history to analyze.
- **`future_position_events` remains 0** (asserted by the dashboard; a non-zero
  count is a hard safety violation and blocks activation).
- The **dashboard output has been manually reviewed** by a human.
- The **human/council agrees to the proposal-only scope** described in this
  document.

Building Hermes does not relax any of these. Even after activation, Hermes stays
proposal-only and inherits every boundary in §4 and §7.

---

## 11. Relationship to ChatGPT / Claude / Risk Engine

- **ChatGPT / Claude (assistants/coding agents):** These can read Hermes
  proposals and help a human reason about them or implement *human-approved*
  changes through the normal review/PR process. Hermes itself is none of these —
  it does not write code, open PRs, or self-implement. A Hermes proposal is an
  input to a human-driven process, not an instruction to an assistant.
- **Risk Policy Engine (`scripts/apply_risk_policy.py`):** The risk engine has
  **veto / reporting authority only — no execution authority**. It decides
  `BLOCKED` / `OBSERVE_ONLY` / `PAPER_REVIEW_CANDIDATE` / `NOT_EVALUATED` /
  `REJECTED`. Hermes is **subordinate to** the risk engine: Hermes reads the risk
  engine's recorded decisions as history and may *propose* that a human review
  them, but Hermes **cannot** change a risk decision, override a veto, alter a
  threshold, or change risk policy. Hermes has no veto and no execution — only
  observation and proposal.
- **Dashboard / Inspector (`build_runtime_risk_dashboard.py`,
  `inspect_runtime_db.py`):** Hermes consumes their read-only outputs. Hermes is
  a *consumer* of the dashboard, one level further from authority: the dashboard
  summarizes history; Hermes proposes what a human should review in that history.

Authority ordering (most to least, all still non-executing in this phase):
human/council → risk engine (veto/reporting) → dashboard/inspector (reporting) →
**Hermes (proposal-only)**.

---

## 12. Relationship to Paper Simulation

The existence of Hermes does **not** start paper simulation. These are separate
concerns and Hermes never bridges them.

- A `PAPER_REVIEW_CANDIDATE` is a **future paper-simulation review candidate
  only** — not a paper entry, not a paper trade, not live readiness. Hermes
  surfacing such candidates does not change that.
- **Paper simulation must not start just because Hermes exists.**

Before any paper simulation may even be designed-and-approved, the project still
needs **all** of the following (each design/approval, none authorizing live):

- the dashboard reviewed,
- Hermes proposals reviewed,
- a paper accounting design,
- a position lifecycle design,
- a risk limit design,
- an approval rule,
- explicit human/council approval.

Hermes contributes only the "proposals reviewed" input above. It does not satisfy
any of the others and it does not grant approval.

---

## 13. Golden Rule

> **Hermes may observe, summarize, and propose.**
> **Hermes may not decide, execute, or silently change the system.**

Every Hermes output is a proposal addressed to a human/council. No threshold,
risk policy, candidate status, signal, paper position, live position, or
`future_position_events` row is ever created or changed by Hermes. If in doubt,
Hermes refuses and escalates.

---

*Not financial advice. Research only. No live execution in this phase.*
