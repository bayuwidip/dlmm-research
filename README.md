# DLMM Research

Personal DeFi automation project. **Bukan bot trading.**

Long-term vision: autonomous DeFi strategy system (diparkir — lihat `docs/VISION_PARKED.md`).
Current phase: **online data collection, scoring, validation, reporting.**

## ⚠️ Batas fase ini

- Tidak ada wallet, private key, transaction signing, atau live execution.
- Tidak ada offline mode, tidak ada synthetic/sample data, tidak ada dummy report.
- Pipeline mengambil data dari **Meteora public API live**. Jika API gagal, pipeline gagal (exit non-zero). Tidak ada fallback ke data contoh.
- `DATA_NOT_AVAILABLE` dipakai **hanya** untuk field yang memang tidak tersedia dari API — bukan untuk menyembunyikan error fetch.

## Status gate

| Gate | Nilai |
|---|---|
| Ethics gate | green (berdasarkan pengecekan user terhadap peraturan tertulis) |
| Validation gate | red (belum ada siklus paper test selesai) |
| Max allowed action | PAPER_ONLY |

Selama `validation_gate=red`, `max_allowed_action` wajib `PAPER_ONLY` dan status tidak boleh `SMALL LIVE TEST` — ditegakkan otomatis oleh validator.

## Struktur

```
dlmm-research/
├── docs/
│   ├── DLMM_POOL_SCREENING_PROTOCOL.md
│   └── VISION_PARKED.md          # visi jangka panjang (PARKED, tidak dijalankan)
├── data/
│   ├── pools_watchlist.csv       # output build (header-only sampai run pertama)
│   └── raw/                      # snapshot mentah dari API (gitignored)
├── reports/
│   └── latest_pool_report.md     # output build (dari API live; gitignored)
├── scripts/
│   ├── fetch_meteora_pools.py    # collector online-only
│   ├── build_watchlist.py        # mapping + hard filter + scoring + veto
│   └── validate_watchlist.py     # validator gate enforcement
├── journals/
│   └── weekly_review_template.md
├── logs/                         # log runtime (gitignored)
├── .github/workflows/
│   └── collect_and_validate.yml  # fetch -> build -> validate -> upload artifact
├── README.md
└── .gitignore
```

## Menjalankan online pipeline

```bash
python scripts/fetch_meteora_pools.py
python scripts/build_watchlist.py
python scripts/validate_watchlist.py
```

`fetch` mengambil dari `https://dlmm.datapi.meteora.ag/pools` (no credential, read-only GET) dan menyimpan ke `data/raw/meteora_pools_raw_<timestamp>.json` + `meteora_pools_raw_latest.json`. `build` membaca `_latest.json`, memetakan field, dan menulis `data/pools_watchlist.csv` + `reports/latest_pool_report.md`. `validate` menegakkan aturan gate dan menolak data contoh.

## Catatan temuan (fase TOOL TEST)

Beberapa kriteria scoring di protokol tidak punya sumber di endpoint `/pools`: `total_lps` (tidak ada di skema), `organic_score` (konsep Jupiter), dan volatilitas (butuh OHLCV endpoint terpisah). Field-field ini ditandai `DATA_NOT_AVAILABLE`. Report menyorot gap ini agar protokol bisa disesuaikan ke data yang benar-benar tersedia — bukan dipaksa terisi.

## Keamanan

Tidak ada credential, wallet, atau private key di repo. `.gitignore` mengecualikan `.env`, `*.key`, `*.pem`. Tidak ada kode yang dapat mengeksekusi transaksi on-chain di fase ini.

---
*Bukan nasihat finansial. Not a live trading signal.*
