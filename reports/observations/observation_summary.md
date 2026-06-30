# Paper Observation Readiness v0.1

Status: RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY

This report tracks classification stability across recorded runs.

Observation readiness means: stable enough to consider for future paper simulation.

It does **not** mean paper trade ready, live ready, LP ready, or execution allowed.

Forbidden actions remain: wallet, private key, signing, swap, LP add/remove, rebalance, live execution.

## Summary

- Total observed pairs: 213
- Observation ready: 0
- Core observing: 7
- Tactical observe-only: 10
- Blocked: 1

## Readiness Rules

- CORE requires 7 consecutive clean recorded runs.
- TACTICAL requires longer observation and remains observe-only in this phase.
- MALFORMED_PAIR_LABEL or blacklist observed historically creates a hard block.
- Chronic NOT_EVALUATED creates a block.

## Top Observation Rows

| Pair | Class | Status | Ready | Core Streak | Tactical Streak | Records | Flags | Reason |
|---|---|---|---:|---:|---:|---:|---|---|
| -USDT | REJECT | BLOCKED | False | 0 | 0 | 1 | MALFORMED_PAIR_LABEL | Hard block flag observed historically. |
| HYPE-SOL | CORE | CORE_OBSERVING | False | 1 | 0 | 1 | none | CORE clean streak=1; needs 7. |
| HYPE-USDC | CORE | CORE_OBSERVING | False | 1 | 0 | 1 | none | CORE clean streak=1; needs 7. |
| JLP-USDC | CORE | CORE_OBSERVING | False | 1 | 0 | 1 | none | CORE clean streak=1; needs 7. |
| JUP-SOL | CORE | CORE_OBSERVING | False | 1 | 0 | 1 | none | CORE clean streak=1; needs 7. |
| TRUMP-USDC | CORE | CORE_OBSERVING | False | 1 | 0 | 1 | none | CORE clean streak=1; needs 7. |
| USDC-SOL | CORE | CORE_OBSERVING | False | 1 | 0 | 1 | none | CORE clean streak=1; needs 7. |
| USDC-cbBTC | CORE | CORE_OBSERVING | False | 1 | 0 | 1 | none | CORE clean streak=1; needs 7. |
| AAVE-USDC | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_VOLUME|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| ALON-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| ALON-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|LOW_VOLUME|NO_ELIGIBLE_FEE_POOL|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| ANSEM-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|NO_ELIGIBLE_FEE_POOL|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| ANSEM-USDT | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|LOW_VOLUME|NO_ELIGIBLE_FEE_POOL|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| ANSEM-UwU | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| ANTE-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|LOW_VOLUME|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| ARX-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| ARX-USDC | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|LOW_VOLUME|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| ASTEROID-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| AVA-USDC | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|LOW_VOLUME|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| AgenC-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| BABYTROLL-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|LOW_VOLUME|NO_ELIGIBLE_FEE_POOL|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| BLEND-USDC | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|LOW_VOLUME|NO_ELIGIBLE_FEE_POOL|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| BNB-USDC | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_VOLUME|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| BP-USDC | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| BULL-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|LOW_VOLUME|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| BULLWIF-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|LOW_VOLUME|NO_ELIGIBLE_FEE_POOL|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| BURNIE-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| BURNIE-USDC | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|LOW_VOLUME|NO_ELIGIBLE_FEE_POOL|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| Bepe-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| Bonk-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| Bullshit-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|LOW_VOLUME|NO_ELIGIBLE_FEE_POOL|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| Buttcoin-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| Buttcoin-USDC | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| CARDS-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| CATWIF-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| CLIVE-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|NO_ELIGIBLE_FEE_POOL|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| CLOUD-USDC | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_VOLUME|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| CS-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|LOW_VOLUME|NO_ELIGIBLE_FEE_POOL|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| CTM-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| CUPSEY-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|NO_ELIGIBLE_FEE_POOL|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| Chameleon-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| Clude-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| DEUS-USDC | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|LOW_VOLUME|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| Daemon-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|LOW_VOLUME|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| ENA-USDC | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| ETH-MM | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|LOW_VOLUME|NO_ELIGIBLE_FEE_POOL|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| ETH-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| FINNBAGS-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | LOW_LIQUIDITY|LOW_VOLUME|NO_ELIGIBLE_FEE_POOL|OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| FRAG-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |
| Fartcoin-SOL | NOT_EVALUATED | NOT_EVALUATED | False | 0 | 0 | 1 | OHLCV_UNAVAILABLE | Latest classification is NOT_EVALUATED. |

---
No wallet · No private key · No signing · No swap · No LP · No rebalance · No live execution.
Observation only; PAPER_ONLY.
