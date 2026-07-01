# Agent Instructions

Before making any change in this repository, read CLAUDE.md in full and
follow it exactly. CLAUDE.md is the single source of truth for project
context, phase, forbidden actions, and file modification rules.

This file exists only so that Codex CLI auto-loads project context. Do not
duplicate or contradict CLAUDE.md here.

## Optional RTK usage

RTK may be used when available for exploration and token saving on noisy
outputs, such as large diffs, long logs, or broad search results. RTK is
optional only: do not make repository tasks, tests, validation, or agent
instructions depend on RTK being installed.

For final validation evidence, run and report the original project commands
directly (for example `python3 -m unittest discover tests` and
`python3 scripts/validate_watchlist.py`). RTK summaries can support
investigation, but they do not replace the canonical command output.

## Hard boundary (redundant safety copy, CLAUDE.md is authoritative)
No wallet. No private key. No seed phrase. No signing. No swap. No LP
add/remove. No rebalance. No live execution. No signal generation. No paper
position creation. No future_position_events writes. No threshold, risk
policy, or candidate status changes without explicit human instruction. Do
not modify existing scripts/*.py without targeted instruction. Never merge
or push to main -- stop at a branch + PR.
