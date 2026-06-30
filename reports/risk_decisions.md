# Risk Decisions Report

- Generated (UTC): 2026-06-30T06:02:34.678788+00:00
- Input: `/home/ubuntu/projects/dlmm-research/data/strategy_classification_v2.csv`
- Output: `/home/ubuntu/projects/dlmm-research/data/risk_decisions.csv`
- Total rows: 213

## Safety banner

```
READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY
No wallet
No private key
No signing
No swap
No LP
No rebalance
No live execution
No LIVE_ELIGIBLE_*
```

> The Risk Engine has VETO authority but NO execution authority. It can stop and shrink; it can never place, sign, or send anything.

## Counts by risk_decision

- BLOCKED: 44
- OBSERVE_ONLY: 10
- PAPER_REVIEW_CANDIDATE: 7
- NOT_EVALUATED: 149
- REJECTED: 3

## Counts by risk_action

- NO_ACTION: 149
- CONTINUE_OBSERVATION: 10
- REVIEW_FOR_FUTURE_PAPER_SIMULATION: 7
- FIX_DATA_OR_CLASSIFICATION: 0
- REJECT: 47

## Top blockers

- NO_ELIGIBLE_FEE_POOL: 44
- CLASSIFIED_REJECT: 3
- TEST_LANE_QUARANTINE: 3
- NOT_LIVE_ELIGIBLE: 3
- MALFORMED_PAIR_LABEL: 1

## Top warnings

- LOW_LIQUIDITY: 98
- LOW_VOLUME: 89
- EXTREME_VOLATILITY: 7
- LOW_DATA_COMPLETENESS: 2

## Paper review candidates

> FUTURE paper-simulation REVIEW only. NOT a paper entry, NOT a paper trade, NOT live readiness.

| Pair | Pair key | Class | Decision | Action | Max allowed | Next step |
|---|---|---|---|---|---|---|
| USDC-SOL | EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v|So11111111111111111111111111111111111111112 | CORE | PAPER_REVIEW_CANDIDATE | REVIEW_FOR_FUTURE_PAPER_SIMULATION | FUTURE_PAPER_SIMULATION_REVIEW | Eligible for FUTURE paper-simulation REVIEW only. This is NOT a paper entry, NOT a paper trade, and NOT live readiness. No position is created and no order is placed. |
| HYPE-USDC | 98sMhvDwXj1RQi5c5Mndm3vPe9cBqPrbLaufMXFNMh5g|EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v | CORE | PAPER_REVIEW_CANDIDATE | REVIEW_FOR_FUTURE_PAPER_SIMULATION | FUTURE_PAPER_SIMULATION_REVIEW | Eligible for FUTURE paper-simulation REVIEW only. This is NOT a paper entry, NOT a paper trade, and NOT live readiness. No position is created and no order is placed. |
| USDC-cbBTC | EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v|cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij | CORE | PAPER_REVIEW_CANDIDATE | REVIEW_FOR_FUTURE_PAPER_SIMULATION | FUTURE_PAPER_SIMULATION_REVIEW | Eligible for FUTURE paper-simulation REVIEW only. This is NOT a paper entry, NOT a paper trade, and NOT live readiness. No position is created and no order is placed. |
| TRUMP-USDC | 6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN|EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v | CORE | PAPER_REVIEW_CANDIDATE | REVIEW_FOR_FUTURE_PAPER_SIMULATION | FUTURE_PAPER_SIMULATION_REVIEW | Eligible for FUTURE paper-simulation REVIEW only. This is NOT a paper entry, NOT a paper trade, and NOT live readiness. No position is created and no order is placed. |
| HYPE-SOL | 98sMhvDwXj1RQi5c5Mndm3vPe9cBqPrbLaufMXFNMh5g|So11111111111111111111111111111111111111112 | CORE | PAPER_REVIEW_CANDIDATE | REVIEW_FOR_FUTURE_PAPER_SIMULATION | FUTURE_PAPER_SIMULATION_REVIEW | Eligible for FUTURE paper-simulation REVIEW only. This is NOT a paper entry, NOT a paper trade, and NOT live readiness. No position is created and no order is placed. |
| JUP-SOL | JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN|So11111111111111111111111111111111111111112 | CORE | PAPER_REVIEW_CANDIDATE | REVIEW_FOR_FUTURE_PAPER_SIMULATION | FUTURE_PAPER_SIMULATION_REVIEW | Eligible for FUTURE paper-simulation REVIEW only. This is NOT a paper entry, NOT a paper trade, and NOT live readiness. No position is created and no order is placed. |
| JLP-USDC | 27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4|EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v | CORE | PAPER_REVIEW_CANDIDATE | REVIEW_FOR_FUTURE_PAPER_SIMULATION | FUTURE_PAPER_SIMULATION_REVIEW | Eligible for FUTURE paper-simulation REVIEW only. This is NOT a paper entry, NOT a paper trade, and NOT live readiness. No position is created and no order is placed. |

## Observe-only

> Reporting/watchlist only — continue observation, no paper entry.

| Pair | Pair key | Class | Decision | Action | Max allowed | Next step |
|---|---|---|---|---|---|---|
| SOL-PUMP | So11111111111111111111111111111111111111112|pumpCmXqMfrsAkQ5r49WcJnRayYRqmXz6ae8H7H9Dfn | TACTICAL | OBSERVE_ONLY | CONTINUE_OBSERVATION | OBSERVE_ONLY | Continue observation only. No paper entry, no execution. Re-review after the observation window; do not escalate from this layer. |
| MET-SOL | METvsvVRapdj9cFLzq4Tr43xK4tAjQfwX76z3n6mWQL|So11111111111111111111111111111111111111112 | TACTICAL | OBSERVE_ONLY | CONTINUE_OBSERVATION | OBSERVE_ONLY | Continue observation only. No paper entry, no execution. Re-review after the observation window; do not escalate from this layer. |
| USDC-MET | EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v|METvsvVRapdj9cFLzq4Tr43xK4tAjQfwX76z3n6mWQL | TACTICAL | OBSERVE_ONLY | CONTINUE_OBSERVATION | OBSERVE_ONLY | Continue observation only. No paper entry, no execution. Re-review after the observation window; do not escalate from this layer. |
| SOL-KINS | So11111111111111111111111111111111111111112|Tqj8yFmagrg7oorpQkVGYR52r96RFTamvWfth9bpump | TACTICAL | OBSERVE_ONLY | CONTINUE_OBSERVATION | OBSERVE_ONLY | Continue observation only. No paper entry, no execution. Re-review after the observation window; do not escalate from this layer. |
| Jotchua-SOL | BcHEaaTCvycPwwsJ9yQTXdHP9X2gCLkznDbZ8VySpump|So11111111111111111111111111111111111111112 | TACTICAL | OBSERVE_ONLY | CONTINUE_OBSERVATION | OBSERVE_ONLY | Continue observation only. No paper entry, no execution. Re-review after the observation window; do not escalate from this layer. |
| KLED-SOL | 1zJX5gRnjLgmTpq5sVwkq69mNDQkCemqoasyjaPW6jm|So11111111111111111111111111111111111111112 | TACTICAL | OBSERVE_ONLY | CONTINUE_OBSERVATION | OBSERVE_ONLY | Continue observation only. No paper entry, no execution. Re-review after the observation window; do not escalate from this layer. |
| CARDS-USDC | CARDSccUMFKoPRZxt5vt3ksUbxEFEcnZ3H2pd3dKxYjp|EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v | TACTICAL | OBSERVE_ONLY | CONTINUE_OBSERVATION | OBSERVE_ONLY | Continue observation only. No paper entry, no execution. Re-review after the observation window; do not escalate from this layer. |
| USDC-JUP | EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v|JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN | TACTICAL | OBSERVE_ONLY | CONTINUE_OBSERVATION | OBSERVE_ONLY | Continue observation only. No paper entry, no execution. Re-review after the observation window; do not escalate from this layer. |
| SOLANGELES-SOL | 8wxkvAfEns76yBzu4MnbV7VnXWjg3iDPA9uwAQ6cpump|So11111111111111111111111111111111111111112 | TACTICAL | OBSERVE_ONLY | CONTINUE_OBSERVATION | OBSERVE_ONLY | Continue observation only. No paper entry, no execution. Re-review after the observation window; do not escalate from this layer. |
| USDC-PUMP | EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v|pumpCmXqMfrsAkQ5r49WcJnRayYRqmXz6ae8H7H9Dfn | TACTICAL | OBSERVE_ONLY | CONTINUE_OBSERVATION | OBSERVE_ONLY | Continue observation only. No paper entry, no execution. Re-review after the observation window; do not escalate from this layer. |

## Rejected / blocked

> Vetoed by the risk engine — not eligible for review.

| Pair | Pair key | Class | Decision | Action | Max allowed | Next step |
|---|---|---|---|---|---|---|
| ANSEM-SOL | 9cRCn9rGT8V2imeM2BaKs13yhMEais3ruM3rPvTGpump|So11111111111111111111111111111111111111112 | REJECT | REJECTED | REJECT | NONE | No action. Pair was rejected by strategy classification. Do not observe-for-entry and do not consider for paper review. |
| ANSEM-USDC | 9cRCn9rGT8V2imeM2BaKs13yhMEais3ruM3rPvTGpump|EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v | REJECT | REJECTED | REJECT | NONE | No action. Pair was rejected by strategy classification. Do not observe-for-entry and do not consider for paper review. |
| -USDT | CWZ6BsdnjkDVTGkmL6bGbJXXig6ceef12KvyGQW14cMt|Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB | REJECT | REJECTED | REJECT | NONE | No action. Pair was rejected by strategy classification. Do not observe-for-entry and do not consider for paper review. |
| PYTHIA-SOL | CreiuhfwdWCN5mJbMJtA9bBpYQrQF2tCBuZwSPWfpump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| SOL-USD1 | So11111111111111111111111111111111111111112|USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| USWR-USDC | 4D8qUHm334fxqeTauPvF8gQ7fYgrD4Mpmb1Wy6ftUSWR|EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| CUPSEY-SOL | BwAU6gsimrFhJrRcZqKxQJayfnkyyan63WNCJRWYpump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| UЅⅮT-SOL | CuKMu1kgAiFU5oHRWXRv9pWHApr5QKsaoodb1WDuRP5v|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| 🐂🀄️-USDC | EPD8jj7bVhNh3o7Wx1XZ39aaacSki8p2ABaN61yhUnBh|EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| GOKHSHTEIN-SOL | 9ZkArkhhDMe19ToEUWnUiM75XWJxcTSF2vmKHM2Spump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| ANSEM-SOL | 6KDh3wLSZMg37nnU7prtKZr7Rut7WQGSf33Vp1G7pump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| SOL-FINNBAGS | So11111111111111111111111111111111111111112|xc5gN35tmTiCB5mEWJjwUTNc9dCzbxp5SH2ewV4BAGS | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| ANSEM-USDT | 9cRCn9rGT8V2imeM2BaKs13yhMEais3ruM3rPvTGpump|Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| 🐂🀄️-SOL | 2hci7YELD2n8JREvP3LXbPJSx1rJnDb9fBZyP6iUpump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| RTM-USDC | 3d1qHSAkQhoN7kN1C6tvpAArCkXWxwYdBng6taXCDM6u|EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| BURNIE-USDC | CGEDT9QZDvvH5GmVkWJH2BXiMJqMJySC9ihWyr7Spump|EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| CS-SOL | 9qwxahBxcgKyn5X7kZvkN7qxKZg6pkVD8Lo4URtopump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| CLIVE-SOL | HEU5mPDm5jCyn4AjQKjvWuvttACKvitgpAdwfmu2DoiA|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| SOL-FARM | So11111111111111111111111111111111111111112|yMJPZbnhoHib3ib8n8PfiVcp9yauk1vnaGKLx7epump | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| 🐂🀄-SOL | 7jrazSKnCU2vbyVPJ8dfEF2TMYLcUiDBsFaEGvqopump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| SOL-🐂🀄️ | So11111111111111111111111111111111111111112|dUaSdZm38CStjhp1VSJWGFQqSxf6DQB2hfjMXmVpump | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| MM-SOL | Ax8PSfCXxmxb8C8kYTzN5CPpTe6PyeZfFf8rrXNCjupx|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| MM-USDC | Ax8PSfCXxmxb8C8kYTzN5CPpTe6PyeZfFf8rrXNCjupx|EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| MANLET-SOL | FamUNkepHXkVxjWHeMSpJmD4xVhCSyNnUG9GVsdmR2xQ|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| WOC-SOL | 3WjLscH2JsXLEFJZRA9z8ti8yRGxWGKbqymPd7UicRth|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| ETH-MM | 7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs|Ax8PSfCXxmxb8C8kYTzN5CPpTe6PyeZfFf8rrXNCjupx | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| WCANIME-SOL | GDShNPDh22CpeUruKJ7uxnXEcxptU4dtjFymvorTpump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| VSK-SOL | 12z7AWnW5Q8mAS9qFtCWnnMdhNvqScZHe8w627EfEASY|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| BLEND-USDC | BWsnyEa1XtsNRdgPaDoA1WVUonF7BBGZTd2zc72NQsWT|EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| MM-JUP | Ax8PSfCXxmxb8C8kYTzN5CPpTe6PyeZfFf8rrXNCjupx|JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| BABYTROLL-SOL | 6qdzMx4c9rL2X3Ns3SwZ8uEo4zReDPjdXpAEmpo7pump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| USDC-Aliens | EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v|F5tfztTnE4sYsMhZT5KrFpWvHmYSfJZoRjCuxKPbpump | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| piss-SOL | DXXcq4tY5e4PbXybyBMnxZjHVmzv1GVrAXoW5TcC5kbu|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| SOL-mogsem | So11111111111111111111111111111111111111112|Z4S3sHmJmcY44oBNFA4sJtM5Ks2dfSnniGQwi4GaX5v | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| USDC-mogsem | EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v|Z4S3sHmJmcY44oBNFA4sJtM5Ks2dfSnniGQwi4GaX5v | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| TJR-SOL | D1BHW3Tz4ygwwfCGzje9tMAMHz5ScAWm1EZhSTmgpump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| Bullshit-SOL | 9qeN746oRit785W9xs69XR4Tzm2i4vjaxUikNYYFpump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| TURTLE-SOL | 2dJniDEAGCG7zWKseCkyrML3W23WLjDf1CGxpNv3pump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| INFERRA-SOL | 9ufM9TJd1UEmi9awnGfxCkCHAgQ3JZ5Sw6YxeSeEASY|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| SKULLY-SOL | FE9v2QJfNPmgNf5yGFu4MJvafVrPCtPCDRxeS5mipump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| SOL-honestSOL | So11111111111111111111111111111111111111112|sctmWXGT7L75psrUHV2xxyTQKndE7ZcCQRHy2z6D5ER | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| BULLWIF-SOL | 5npesGsnVhcQbh6oVcsLtn5UKqdgYeipgDKsGaappump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| FINNBAGS-SOL | Cgh2CWxXEoVLsutZahV1264YdaGNbB4nLrwQ97H1BAGS|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| liquititty-SOL | 9Cn7or8TVicZYjSUEmgRk4A9XdXFzkBS8vn1ebt6pump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| ALON-SOL | EhB1sbSiFVw8XYb8NJUcKEJocGsa4KGxxrS3LsvFpump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| 🐂🀄-SOL | DJ7YoBbUpTyL2gLHEBDVWpxpzSL3ANga25XrZM2Wpump|So11111111111111111111111111111111111111112 | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |
| USDC-honestSOL | EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v|sctmWXGT7L75psrUHV2xxyTQKndE7ZcCQRHy2z6D5ER | NOT_EVALUATED | BLOCKED | REJECT | NONE | Quarantine. Resolve the severe risk flag(s) ['NO_ELIGIBLE_FEE_POOL'] before the pair can re-enter screening. Not eligible for review. |

---

**This report does not authorize paper entries, live entries, LP actions, swaps, rebalances, wallet use, signing, or execution.**

_Phase: READ_ONLY / RESEARCH_ONLY / SCREENING_ONLY / PAPER_ONLY. Research only._