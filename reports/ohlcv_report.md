# OHLCV Tool-Test Report

- Run timestamp (UTC): 2026-06-29T13:00:15.108426+00:00
- Candidate pairs selected: 20
- Timeframe: 1h | Lookback: 72h

## Rows by ohlcv_status
- OK: 20
- DATA_NOT_AVAILABLE: 0
- API_ERROR: 0
- MALFORMED_RESPONSE: 0

## Top 20 OHLCV Tool-Test

| Pair | Score | Pair Status | OHLCV Status | Pool | Candles | %Chg | HL Range% | RV% | Vol | Range | Trend |
|---|---:|---|---|---|---:|---:|---:|---:|---|---|---|
| USDC-SOL | 94.0 | PAPER TEST | OK | 5rCf1DM8… | 73 | 3.997 | 9.1532 | 5.3471 | MODERATE | MODERATE | UP |
| ANSEM-SOL | 91.0 | PAPER TEST | OK | 6e7V9eeg… | 32 | 47.0518 | 239.6609 | 77.4228 | EXTREME | EXTREME | UP_STRONG |
| HYPE-USDC | 91.0 | PAPER TEST | OK | 6F4rVnmV… | 73 | 0.0 | 7.8922 | 6.1537 | MODERATE | MODERATE | SIDEWAYS |
| SOL-PUMP | 89.0 | PAPER TEST | OK | EtPcWELe… | 73 | 7.2135 | 23.2392 | 13.3805 | HIGH | HIGH | UP_STRONG |
| MET-SOL | 86.5 | PAPER TEST | OK | AsSyvUnb… | 73 | 5.1219 | 17.8021 | 11.5202 | HIGH | HIGH | UP_STRONG |
| USDC-cbBTC | 83.5 | PAPER TEST | OK | 7ubS3Gcc… | 73 | -0.3593 | 3.9554 | 2.8556 | LOW | LOW | SIDEWAYS |
| USDC-MET | 83.5 | PAPER TEST | OK | 5hbf9JP8… | 73 | 9.6264 | 20.4199 | 12.8779 | HIGH | HIGH | UP_STRONG |
| ANSEM-USDC | 82.0 | PAPER TEST | OK | BetLT47e… | 31 | 54.275 | 171.5569 | 76.0585 | EXTREME | EXTREME | UP_STRONG |
| TRUMP-USDC | 81.0 | PAPER TEST | OK | 3C5YE97H… | 73 | -1.3896 | 8.8671 | 5.1924 | MODERATE | MODERATE | DOWN |
| SOL-KINS | 79.5 | PAPER TEST | OK | 3XrDjwbi… | 73 | 8.8487 | 59.8122 | 42.8802 | EXTREME | EXTREME | UP_STRONG |
| Jotchua-SOL | 78.5 | PAPER TEST | OK | EDeuGoVF… | 73 | -18.4936 | 74.8231 | 53.5688 | EXTREME | EXTREME | DOWN_STRONG |
| KLED-SOL | 77.5 | PAPER TEST | OK | Diy8bJcV… | 73 | 55.8761 | 176.6156 | 60.864 | EXTREME | EXTREME | UP_STRONG |
| CARDS-USDC | 76.5 | PAPER TEST | OK | 2N1KNuLS… | 73 | -13.3988 | 28.6272 | 18.1306 | EXTREME | HIGH | DOWN_STRONG |
| HYPE-SOL | 75.5 | PAPER TEST | OK | 6oQ9wVex… | 73 | 3.9554 | 6.4375 | 4.2 | MODERATE | MODERATE | UP |
| USDC-JUP | 74.5 | PAPER TEST | OK | HfgjZDme… | 73 | -1.9752 | 14.9873 | 9.5531 | HIGH | MODERATE | DOWN |
| JUP-SOL | 74.5 | PAPER TEST | OK | HdsFGjjY… | 73 | -5.3949 | 12.9087 | 6.864 | MODERATE | MODERATE | DOWN_STRONG |
| -USDT | 74.0 | PAPER TEST | OK | 9p3aRWnb… | 73 | 2.4193 | 5.7362 | 5.003 | MODERATE | MODERATE | UP |
| SOLANGELES-SOL | 73.0 | PAPER TEST | OK | 7t4QCjxN… | 73 | 69.4466 | 189.9927 | 81.8592 | EXTREME | EXTREME | UP_STRONG |
| USDC-PUMP | 72.5 | PAPER TEST | OK | 88LoXa6p… | 73 | 10.9141 | 24.9956 | 13.538 | HIGH | HIGH | UP_STRONG |
| JLP-USDC | 72.5 | PAPER TEST | OK | AnJacX3h… | 73 | 2.0191 | 4.9145 | 3.3054 | MODERATE | LOW | UP |

## Data quality notes

- 20 pool mengembalikan OHLCV valid. Metrik dihitung dari candle nyata.
- Expected candles per pool (1h × 72h): ~72. `data_completeness_pct` mengukur cakupan terhadap angka ini.
- Jika struktur response berbeda dari skema terdokumentasi, baris ditandai MALFORMED_RESPONSE — bukan ditebak.

---
**OHLCV report is not a live signal. It is a volatility and data-quality tool test only. No wallet, no execution, no trading action.**