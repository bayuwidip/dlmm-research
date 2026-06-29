# DLMM Pool Screening Protocol v0.1

> **Status proyek:** research-first · capital-limited (max USD 500) · no-top-up · edge BELUM terbukti.
> Dokumen ini adalah turunan dari **DLMM Trading Charter v0.1** dan tunduk penuh padanya. Jika ada konflik, Charter menang.

---

## ⛔ GERBANG PRA-AKTIVASI (baca sebelum apa pun)

Protokol ini **tidak boleh** dipakai untuk live test — fase manapun, nominal berapapun — sampai **dua** gerbang berikut hijau:

1. **Gerbang Etik.** Verifikasi terhadap **dokumen tertulis** (kode etik pegawai, kebijakan benturan kepentingan, aturan aktivitas/investasi pegawai BPD Bali, ketentuan OJK terkait). Bukan terhadap pemahaman umum. Selama belum dicek → status proyek = **PAPER-ONLY**.
2. **Gerbang Validasi.** Minimal satu siklus paper test selesai dan tercatat (lihat §7).

Selama salah satu gerbang merah: protokol ini hanya alat **screening + paper test**. Modal riil = nol.

### Status Gate Saat Ini

Berdasarkan pengecekan user terhadap peraturan tertulis perusahaan, **Gerbang Etik = GREEN**.

Namun **Gerbang Validasi = RED** sampai minimal satu siklus paper test selesai dan tercatat. Selama Gerbang Validasi masih merah, `max_allowed_action` tetap **PAPER_ONLY** meskipun skor pool tinggi.


---

## 1. Tujuan Protocol

Protokol ini **menyaring kandidat pool**, bukan menghasilkan sinyal entry.

Hal yang dilakukan protokol ini:
- Membuang pool yang jelas tidak layak (hard filter).
- Memberi skor relatif antar-kandidat untuk konsistensi penilaian.
- Memaksa pencatatan sebelum keputusan apapun.

Hal yang **TIDAK** dilakukan protokol ini:
- Tidak mengklaim edge. Lolos screening ≠ profitable. Filter hanya membuang yang buruk, tidak menemukan yang menang.
- Tidak memerintahkan entry. Skor 100 sekalipun tidak mewajibkan masuk.
- Tidak menggantikan paper test, benchmark, dan review manual.

Empat kemungkinan hasil akhir untuk tiap pool: **REJECT · WATCHLIST · PAPER TEST · SMALL LIVE TEST**.

> **⚠️ Catatan kritis #1 — kontradiksi yang harus kamu sadari.**
> Filter di protokol ini (JupShield, Organic Score, MCAP, holders) adalah filter yang dirancang untuk *memilih memecoin Solana yang kurang berbahaya* — bukan menyaringnya keluar. Charter §7 melarang "token tidak jelas, meme ekstrem, aset didorong hype" dan "token baru tanpa riwayat memadai." **Konsekuensi:** protokol ini secara default mengarahkanmu ke aset volatil, sedangkan Charter §10 mengarahkanmu ke low-maintenance. Untuk fase awal yang benar-benar patuh Charter, pertimbangkan menjalankan protokol ini **terlebih dulu pada pasangan stabil/blue-chip** (mis. SOL-USDC, stablecoin-stablecoin) dan menunda kategori memecoin sampai disiplin & edge terbukti. Lihat §4 dan §5 untuk bagaimana ini memengaruhi scoring.

---

## 2. Kategori Keputusan

| Status | Arti | Tindakan |
|---|---|---|
| **TOOL TEST** | Status di **luar** tangga strategi. Hanya untuk menguji apakah kolom data bisa diisi dari Meteora. | Isi 1 pool stabil. Bukan kandidat strategi. Nol modal. Tidak menyiratkan apa pun soal kualitas pool. |
| **REJECT** | Kena ≥1 hard filter, atau skor < 50 | Buang. Catat alasan. Tidak di-watchlist. |
| **WATCHLIST** | Lolos hard filter, skor 50–69 | Amati pasif. Tidak ada paper test. Re-evaluasi mingguan. |
| **PAPER TEST** | Lolos hard filter, skor 70–84 | Masuk paper test 3–7 hari (§7). Tanpa modal riil. |
| **SMALL LIVE TEST** | Skor 85–100 **DAN** paper test lolos **DAN** dua gerbang hijau | Kandidat live test USD 25–50 (§8). Tetap butuh review manual. |

> Status **bukan** otomatis. Skor mengusulkan; manusia memutuskan turun (bukan naik). Kamu boleh menurunkan status pool dari hasil skornya, tidak pernah menaikkannya.

---

## 3. Hard Filter (auto-REJECT)

Satu saja terpenuhi → **REJECT**, tanpa scoring lebih lanjut.

**Keamanan / kualitas token**
1. JupShield OFF.
2. High supply concentration (terdeteksi konsentrasi suplai tinggi).
3. Organic Score < 60.
4. Top-holder / wallet pembuat memegang porsi suplai yang dominan.

**Likuiditas & ukuran**
5. MCAP < USD 500K.
6. Active TVL < USD 10K.
7. Volume 24j < USD 10K.
8. Total LPs < 20.
9. Holders < 200.

**Kualitas data & sinyal palsu**
10. Token terlalu baru — riwayat data < 7 hari (tidak cukup untuk menilai konsistensi).
11. Fee/TVL tinggi tetapi hanya karena **spike sesaat** (satu lonjakan volume, lalu sepi).
12. Holders **menurun tajam** dalam periode pengamatan (indikasi distribusi/exit).
13. Volume tampak **non-organik** (pola wash-trading: volume tinggi, holder & LP stagnan).
14. Pool **tidak bisa dijelaskan secara rasional** — kamu tidak paham dari mana fee/return-nya datang.

> Jika ragu antara WATCHLIST dan REJECT → **REJECT**. Biaya melewatkan peluang = 0. Biaya masuk pool buruk = nyata.

---

## 4. Scoring System (0–100)

Skoring hanya dijalankan **setelah** pool lolos semua hard filter §3.

| Dimensi | Bobot | Apa yang dinilai |
|---|---|---|
| Safety / token quality | 25% | JupShield, Organic Score, distribusi suplai, kejelasan token |
| Liquidity quality | 20% | Active TVL, kedalaman, stabilitas TVL |
| Fee quality | 20% | Fees/Active TVL **DAN konsistensinya** 3–7 hari (bukan angka 1 hari) |
| Volatility suitability | 15% | Kecocokan dengan kapasitas monitoring — lihat catatan #2 |
| LP distribution / participation | 10% | Total LPs, tidak terkonsentrasi di 1–2 LP |
| Data consistency | 10% | Ketersediaan & kestabilan data historis |

Tiap dimensi diberi 0–100, lalu dikalikan bobot. Total = skor pool.

> **⚠️ Catatan kritis #2 — "Volatility suitability" dikoreksi dari spesifikasi awal.**
> Prompt awal menyebut "Volatility 2–4% cocok untuk low-maintenance." **Ini keliru secara mekanis.** Volatilitas lebih tinggi = harga lebih sering keluar range = lebih sering rebalance = **lebih** high-maintenance. Untuk kapasitas 3–5 jam/minggu (Charter §10), skor "volatility suitability" tertinggi diberikan pada volatilitas **rendah** dengan range lebar, bukan 2–4%. Skema yang dipakai di sini:
> - Volatilitas rendah (pasangan stabil/berkorelasi), range lebar → skor tinggi (cocok low-maintenance).
> - Volatilitas 2–4% → skor menengah, **hanya** boleh tinggi jika sudah terbukti bisa dimonitor tanpa ganggu kerja.
> - Volatilitas > 4% → skor rendah di fase awal, apapun fee-nya.

> **⚠️ Catatan kritis #3 — ilusi presisi.**
> Skor 85 tidak "lebih layak" dari 84 secara bermakna; selisih kecil adalah noise. Skor tinggi adalah **syarat perlu, bukan syarat cukup**. Ia tidak pernah memaksa entry dan tidak pernah membatalkan keraguan dari checklist manual §6. Jika skor tinggi tapi checklist §6 ada satu jawaban "tidak tahu" → pool turun ke WATCHLIST, bukan naik.

---

## 4A. Scoring Rubric Detail

Tiap dimensi memetakan ke **satu nilai diskret tetap**, bukan rentang. Tujuannya: input yang sama selalu menghasilkan skor yang sama → auditable, tidak bisa digeser saat sedang tertarik pada satu pool.

> **⚠️ Catatan kritis #4 — kenapa nilai tetap, bukan rentang.**
> Rubric versi rentang (mis. "90–100") masih menyisakan bias: saat tertarik kamu pilih 100, saat netral 90. Lubangnya mengecil tapi tidak tertutup. Nilai diskret menutupnya. Pilih baris yang paling cocok; ambil angkanya apa adanya.

> **⚠️ Catatan kritis #5 — rubric diselaraskan dengan hard filter.**
> Pool yang sudah kena hard filter §3 (TVL < 10K, LP < 20, holders < 200, dst.) **tidak pernah sampai ke scoring**. Karena itu lantai tiap rubric di bawah dimulai tepat di atas ambang hard filter. Tidak ada baris "skor sangat rendah karena TVL anjlok" — kondisi itu sudah di-REJECT sebelum scoring, dan tidak boleh memberi ilusi bahwa pool berbahaya "masih bisa diselamatkan dimensi lain."

### Safety / Token Quality — 25%
| Kondisi | Skor |
|---|---:|
| JupShield ON, Organic Score > 80, no supply concentration, token/pair jelas | 95 |
| JupShield ON, Organic Score 70–80, distribusi cukup sehat | 80 |
| JupShield ON, Organic Score 60–70, ada keraguan minor | 67 |
| Lolos hard filter tapi token sulit dijelaskan / narasi terlalu hype | 45 |

### Liquidity Quality — 20%
| Kondisi | Skor |
|---|---:|
| Active TVL > 100K dan stabil 3–7 hari | 95 |
| Active TVL 50K–100K dan relatif stabil | 80 |
| Active TVL 25K–50K | 67 |
| Active TVL 10K–25K (tepat di atas hard filter) | 50 |

### Fee Quality — 20%
| Kondisi | Skor |
|---|---:|
| Fees/Active TVL > 0,2% konsisten 3–7 hari, bukan spike | 95 |
| Fee cukup tinggi tapi hanya konsisten 2–3 hari | 80 |
| Fee sedang dan stabil | 67 |
| Fee tinggi tapi volatil/spike (hati-hati: sinyal palsu) | 45 |

### Volatility Suitability — 15%
| Kondisi | Skor |
|---|---:|
| Volatilitas rendah, range lebar, cocok low-maintenance | 95 |
| Volatilitas moderat, masih bisa dimonitor 1–2x/hari | 78 |
| Volatilitas 2–4%, perlu monitoring lebih aktif | 55 |
| Volatilitas > 4%, rawan keluar range | 30 |

> **Gate volatilitas (veto, bukan pengurang nilai).** Lihat Catatan Kritis #6 di §5.

### LP Distribution / Participation — 10%
| Kondisi | Skor |
|---|---:|
| Total LPs > 100 dan tidak terkonsentrasi | 95 |
| Total LPs 50–100 | 80 |
| Total LPs 20–50 (tepat di atas hard filter) | 65 |

### Data Consistency — 10%
| Kondisi | Skor |
|---|---:|
| Data tersedia dan stabil minimal 7 hari | 95 |
| Data tersedia 3–7 hari | 78 |
| Data terbatas tapi masih bisa diamati | 55 |
| Data tidak cukup | → **REJECT** (jangan skor; tulis "data tidak cukup") |

**Cara hitung:** (Safety×0,25)+(Liquidity×0,20)+(Fee×0,20)+(Volatility×0,15)+(LP×0,10)+(Data×0,10) = skor total.

---

## 5. Interpretasi Skor

| Skor | Status default |
|---|---|
| < 50 | REJECT |
| 50–69 | WATCHLIST |
| 70–84 | PAPER TEST |
| 85–100 | Kandidat SMALL LIVE TEST — **wajib** review manual §6 + paper test §7 + dua gerbang hijau |

Override hanya berlaku satu arah: **boleh menurunkan** status (lebih konservatif), **tidak boleh menaikkan** dari hasil skor.

> **⚠️ Catatan kritis #6 — gate volatilitas (veto keras, di atas skor total).**
> Bobot volatilitas hanya 15% — terlalu kecil untuk memveto. Tanpa gate, memecoin volatil bisa tembus skor ≥85 lewat fee+TVL+LP tinggi, lalu memicu SMALL LIVE TEST — persis yang Charter §7 larang di fase awal. Maka di fase awal proyek (sebelum disiplin & edge terbukti):
> - Volatilitas **> 4%** → status maksimal = **WATCHLIST**, apa pun skor totalnya. Tidak boleh PAPER TEST, tidak boleh LIVE.
> - Volatilitas **2–4%** → status maksimal = **PAPER TEST**. Tidak boleh langsung LIVE.
> - Hanya volatilitas **rendah** (pasangan stabil/berkorelasi) yang boleh jadi kandidat SMALL LIVE TEST.
>
> Ini veto, bukan pengurang nilai. Skor 90 dengan volatilitas tinggi tetap mentok di WATCHLIST. Gate ini dicabut hanya setelah review eksplisit bahwa volatilitas tertentu terbukti bisa dimonitor tanpa mengganggu pekerjaan (Charter §10).

---

## 6. Checklist Manual Sebelum Entry (paper test maupun live)

Pool **tidak boleh** lanjut jika ada satu pun pertanyaan yang tidak bisa dijawab dengan jelas dan tertulis. "Tidak tahu" = pool turun status.

1. Kenapa pool ini menarik? (alasan spesifik, bukan "lagi rame")
2. Dari mana fee-nya berasal? (volume jenis apa, dari trader siapa)
3. Apakah Fees/Active TVL konsisten 3–7 hari, atau cuma spike?
4. Apakah volume organik atau lonjakan sesaat / wash?
5. Apakah jumlah & distribusi LP sehat (tidak 1–2 LP dominan)?
6. Apakah harga sedang trending kuat satu arah? (jika ya → risiko IL/keluar-range naik)
7. Apa skenario rugi terbesar, dan berapa besar nominalnya?
8. Apa benchmark pembandingnya (§Charter 6)? Hold? Stablecoin? Diam saja?
9. Kapan dan pada kondisi apa harus exit? (ditulis **sebelum** masuk)
10. Apakah saya benar-benar paham kedua token di pair ini?

> Tambahan wajib dari Charter §8: **kondisi emosi saat ini ditulis.** Jika FOMO/marah/ingin balas rugi/merasa "panas" → cooling-down 24 jam, keputusan batal.

---

## 7. Aturan Paper Test (3–7 hari, tanpa modal riil)

Tujuan: mengumpulkan data nyata pool tanpa risiko, dan menguji apakah thesis bertahan.

Catat di awal dan tiap hari:
1. Harga awal kedua token + tanggal/jam mulai.
2. Range/bin simulasi yang *akan* dipakai (tetapkan di awal, jangan ubah).
3. Fee estimasi harian (berdasarkan Fees/Active TVL × ukuran posisi simulasi).
4. Perubahan Active TVL harian.
5. Perubahan volume harian.
6. Perubahan jumlah holder harian.
7. Apakah harga **keluar range** simulasi — kapan, berapa lama.
8. **Pembanding wajib:** nilai posisi LP simulasi vs sekadar hold kedua token (benchmark §Charter 6).

Kriteria lulus paper test (semua harus ya):
- Fee simulasi **menutupi** estimasi IL + biaya (bukan hanya terlihat besar).
- Posisi tidak keluar range sepanjang waktu (atau keluar singkat & terkelola).
- Hasil simulasi **mengalahkan benchmark hold**.
- Data cukup stabil untuk dipercaya (bukan 1 hari beruntung).

Jika tidak lulus → kembali ke WATCHLIST atau REJECT. **Bukan** "coba pakai uang sungguhan saja siapa tahu beda."

---

## 8. Aturan Small Live Test

Hanya boleh dijalankan jika **SEMUA** terpenuhi:
1. Dua gerbang pra-aktivasi hijau (etik tertulis + paper test selesai).
2. Skor pool ≥ 85.
3. Paper test §7 **lulus**.
4. Tidak ada red flag tersisa.
5. Alasan entry tertulis (§6).
6. Exit rule tertulis sebelum masuk (§11 Charter).
7. Ukuran posisi **maksimal USD 25–50** di fase awal.
8. **Tidak** men-deploy seluruh USD 500. Maksimal 1 posisi aktif (Charter §9).
9. Kondisi emosi tercatat netral.

Penambahan ukuran posisi di masa depan **hanya** karena kepatuhan aturan terbukti di review mingguan — **bukan** karena posisi sebelumnya profit (Charter §9).

---

## 9. Kill-Switch

**Hentikan sementara** (tutup posisi, stop entry baru) jika salah satu:
1. Ada entry tanpa jurnal.
2. Rugi yang terjadi karena melanggar aturan (bukan rugi yang sudah diantisipasi).
3. Muncul keinginan top-up di luar USD 500.
4. Pool berubah jadi red flag (likuiditas anjlok, holder kabur, token event tak dipahami).
5. Monitoring mulai mengganggu pekerjaan / tidur / persiapan nikah.
6. Drawdown proyek mencapai **15%** dari modal.
7. Hasil bersih tidak mengalahkan benchmark setelah periode pengamatan.

**Hentikan penuh** (proyek selesai) jika salah satu:
1. Drawdown mencapai **25%**.
2. Ada top-up impulsif / dana non-disposable terpakai.
3. Pelanggaran etik atau area abu-abu yang belum tuntas.
4. Setelah periode validasi, hasil bersih tidak mengalahkan benchmark.
5. Aku tidak mampu mematuhi aturan yang kutulis sendiri.

> Charter §17: jika gagal, proyek dihentikan dan **tidak diganti** proyek trading lain sebagai pelarian.

---

## 10. Template Jurnal Kandidat Pool

Kolom mengikuti `pools_watchlist.csv` (29 kolom). Yang krusial dan baru:
- **`volatility_pct`** = angka terukur (audit trail). **`volatility_bucket`** = kategori untuk scoring (low/moderate/high). Pisahkan: angka adalah fakta, bucket adalah interpretasi.
- **`ethics_gate` / `validation_gate` / `max_allowed_action`** = kunci perilaku yang melekat di tiap baris. Selama salah satu gate `red`, `max_allowed_action` = `PAPER_ONLY`, **apa pun `score_total`-nya**. Ini mencegah skor tinggi diam-diam menggeser keputusan.

Kolom inti yang dicatat per pool: tanggal · pool · pair · mcap · holders · volume 24j · active TVL · fees/active TVL · volatility_pct · volatility_bucket · total LPs · organic score · supply concentration · enam skor dimensi · score_total · vol_gate_applied · ethics_gate · validation_gate · max_allowed_action · status · alasan · risiko utama · keputusan · review date.

> Pool tanpa baris jurnal = tidak boleh lanjut, meski terlihat menarik (Charter §13).
> Jika sebuah kolom **tidak tersedia** di Meteora, tulis `data tidak cukup` — jangan dikarang. Ketidaktersediaan kolom adalah temuan validasi alat, bukan masalah yang harus dipaksakan terisi.

---

## 11. Prinsip Penutup

- Filter membuang yang buruk; ia **tidak** menemukan yang menang. Edge dibuktikan oleh data, bukan oleh lolos screening.
- Skor tinggi = syarat perlu, bukan cukup. Keraguan manual mengalahkan skor.
- Volatilitas tinggi = maintenance tinggi. Untuk waktu terbatas, pilih tenang, bukan ramai.
- Live test = nol sampai gerbang etik tertulis hijau.
- Jika data tidak cukup, tulis **"data tidak cukup"** — jangan mengarang, jangan mengira-ngira.
- Tidak ada pool yang layak jika hanya bisa dikelola oleh versi diriku yang sedang sangat disiplin, sangat sempat, dan sangat tenang.

---
*v0.1 — dokumen riset, bukan nasihat finansial. Tunduk pada DLMM Trading Charter v0.1.*
