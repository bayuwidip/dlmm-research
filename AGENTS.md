# Agent Instructions

Before making any change in this repository, read CLAUDE.md in full and
follow it exactly. CLAUDE.md is the single source of truth for project
context, phase, forbidden actions, and file modification rules.

This file exists only so that Codex CLI auto-loads project context. Do not
duplicate or contradict CLAUDE.md here.

## Hard boundary (redundant safety copy, CLAUDE.md is authoritative)
No wallet. No private key. No seed phrase. No signing. No swap. No LP
add/remove. No rebalance. No live execution. No signal generation. No paper
position creation. No future_position_events writes. No threshold, risk
policy, or candidate status changes without explicit human instruction. Do
not modify existing scripts/*.py without targeted instruction. Never merge
or push to main -- stop at a branch + PR.
