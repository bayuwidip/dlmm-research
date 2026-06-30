# DLMM Project Checkpoint

> Single short checkpoint for humans, Claude Code, and future AI sessions.
> Read this first so we do not repeat context or accidentally jump to live execution.

---

## 1. Current Phase

**READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY**

---

## 2. Current Hard Safety Boundary

- No wallet
- No private key
- No signing
- No swap
- No LP add/remove
- No rebalance
- No live execution
- No `LIVE_ELIGIBLE_*`

---

## 3. Latest Merged Milestones

- Strategy Classification v0.2
- Paper Observation Readiness v0.1
- GitHub Actions now runs the observation pipeline
- Pull request checks are enabled through the `pull_request` trigger
- Observation artifacts are uploaded in CI

---

## 4. Current Pipeline

```
fetch_meteora_pools.py
  → build_watchlist.py
  → fetch_ohlcv_top_pairs.py
  → classify_strategy.py
  → observe_strategy.py
  → validate_watchlist.py
```

---

## 5. Important Scripts

- `scripts/fetch_meteora_pools.py`
- `scripts/build_watchlist.py`
- `scripts/fetch_ohlcv_top_pairs.py`
- `scripts/classify_strategy.py`
- `scripts/observe_strategy.py`
- `scripts/validate_watchlist.py`

---

## 6. Important Data / Report Outputs

**Data:**
- `data/pools_watchlist.csv`
- `data/pair_watchlist.csv`
- `data/ohlcv_top_pairs.csv`
- `data/strategy_classification_v2.csv`
- `data/observations/strategy_observations.jsonl`

**Reports:**
- `reports/latest_pool_report.md`
- `reports/ohlcv_report.md`
- `reports/strategy_classification_v2.md`
- `reports/observations/observation_summary.md`
- `reports/observations/observation_summary.csv`

---

## 7. Validation Commands

```bash
python3 -m unittest tests/test_observe_strategy.py
python3 -m unittest tests/test_classify_strategy.py
python3 scripts/validate_watchlist.py
```

---

## 8. VPS Status

- Tencent Lighthouse 2C2G
- Swap 2GB enabled
- Claude Code installed
- RTK installed and active
- GitHub CLI installed and authenticated
- Tailscale installed on VPS, but laptop-side access/hardening is **not complete yet**
- **Do not close public SSH** until Tailscale SSH from laptop has been proven

---

## 9. Git Workflow

- Work on feature branches
- Use PRs
- Let GitHub Actions checks pass before merge
- Use squash merge
- Do not commit generated runtime history automatically yet unless explicitly approved

---

## 10. Current Observation Meaning

Observation readiness means **stable enough for future paper-simulation consideration only**.

- It does **not** mean paper-trade ready.
- It does **not** mean live ready.
- It does **not** authorize LP, swap, wallet, signing, or execution.

---

## 11. Next Planned Work

- Decide observation storage policy: artifact-only vs commit-back vs DuckDB
- Set up a VPS scheduled runner later — not GitHub Actions as runtime
- Add Telegram notification/control room later, read-only first
- Complete Tailscale laptop setup before closing public SSH

---

## 12. Operating Rule for Coding Agents

Before coding, agents must:

1. Read this checkpoint
2. Check `git status`
3. Confirm the current branch
4. Preserve the safety boundary

---

*Not financial advice. Research only. No live execution in this phase.*
