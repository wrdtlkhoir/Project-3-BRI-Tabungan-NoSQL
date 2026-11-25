# BRI Tabungan NoSQL — Couchbase (main) + Cassandra (Event Ledger), versi lokal

Project 3 Manajemen Data (IF5101). Sistem tabungan BRI dari Project 2 diimplementasikan pada dua database NoSQL yang
saling terhubung lewat backend Python (FastAPI).

| Komponen | Peran |
|---|---|
| **Couchbase CE 7.6.1** | Main database: nasabah, rekening (saldo integer sen), kartu, produk, unit kerja, kanal, posting bunga, instruksi, **outbox** |
| **Cassandra 5.0** | **Event Ledger** append-only: `transaksi_by_rekening`, `transaksi_by_kanal_periode`, `transaksi_by_id` (keyspace `bri_tabungan`) |
| **PostgreSQL 16** | Hanya sumber seed (dump Project 2). Dipakai sekali untuk memuat kedua DBMS |
| **FastAPI** | Validasi, transaksi ACID Couchbase, transactional outbox, relay ke Cassandra |

Dokumentasi: [docs/arsitektur.md](docs/arsitektur.md), [docs/query_mapping.md](docs/query_mapping.md).
Presentasi + screenshot: `docs/Project3_Presentasi_BRI_Tabungan_NoSQL.pptx`, `docs/screenshots/`.

## Prasyarat
* Docker Desktop (disarankan RAM untuk WSL ≥ 6 GB; matikan container lain yang berat)
* Python 3.11–3.13

## Menjalankan (Windows PowerShell / Git Bash)
```bash
cd bri-tabungan-nosql
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt   # sekali saja
cp .env.example .env                                                              # sekali saja

docker compose up -d                       # PostgreSQL, Cassandra, Couchbase (+ init & restore dump). Tunggu ±2 menit
docker compose ps -a                       # bri-couchbase-init & bri-pg-restore harus "Exited (0)"

.venv/Scripts/python scripts/load_all.py   # muat seed: Couchbase (±1 menit) + ledger Cassandra (±10 menit)
.venv/Scripts/python scripts/build_indexes.py
.venv/Scripts/python scripts/validate_seed.py        # harus "SEMUA OK"

.venv/Scripts/python -m uvicorn app.main:app --port 8765   # Swagger: http://127.0.0.1:8765/docs
.venv/Scripts/python scripts/demo.py http://127.0.0.1:8765  # skenario demo end-to-end
.venv/Scripts/python -m pytest tests -v                      # unit + integrasi (15 tes)
.venv/Scripts/python tests/stress_test.py --n 300 --workers 8
.venv/Scripts/python scripts/make_screenshots.py http://127.0.0.1:8765 && .venv/Scripts/python scripts/build_pptx.py
```
Web UI Couchbase: http://127.0.0.1:8091 (Administrator / password).
Cassandra: `docker exec -it bri-cassandra cqlsh`.

## Catatan teknis penting (hasil debugging)
* **Port API 8765, bukan 8000**: di Windows port 8000 bisa masuk rentang cadangan Hyper-V/WSL (WinError 10013).
* **Gunakan `couchbase://127.0.0.1`**, bukan `localhost` (relay port WSL kadang menolak `localhost`).
* **Publikasikan port 8092** pada container Couchbase; tanpa itu `wait_until_ready`/`ping` SDK menunggu ±75 detik. Backend juga membatasi cek ke layanan KV + Query.
* File shell di `infra/` harus berakhiran baris **LF** (bukan CRLF) agar jalan di container Linux.
* `upsert_multi` Couchbase tidak melempar error untuk kegagalan parsial → loader memeriksa hasil per dokumen dan me-retry.
* Kuota RAM Couchbase diperkecil (cluster 1,5 GB, bucket 768 MB) agar muat di laptop 16 GB.

## Endpoint utama
| Method | Path | Keterangan |
|---|---|---|
| POST | `/transaksi/setoran` `/penarikan` `/transfer` | transaksi ACID Couchbase + outbox → ledger. Wajib `idempotency_key` |
| POST | `/rekening/{no}/blokir` `/tutup` | W-05 / W-10 + event audit |
| GET | `/rekening/{no}` | dokumen rekening (Couchbase) |
| GET | `/rekening/{no}/histori` | R-01 (Cassandra) |
| GET | `/laporan/R-02 … R-10` | query Read Project 2 (R-03 = Cassandra, lainnya Couchbase) |
| GET/POST | `/admin/outbox`, `/admin/outbox/relay`, `/admin/chaos/ledger?down=true` | status outbox, paksa relay, simulasi Cassandra mati |

---

## UI + Execution Time per Query

Halaman UI dilayani backend yang sama (tanpa build step, tanpa CDN): **http://127.0.0.1:8765/ui**

| Tab | Isi |
|---|---|
| **Status** | ping Couchbase & Cassandra (versi, latensi), jumlah data seed vs data uji, jumlah event ledger, status outbox |
| **Query Explorer** | 20 kartu (R-01..R-10, W-01..W-10): form parameter berisi default dari data uji, statement SQL++/CQL (bisa disalin), tabel hasil (maks. 100 baris + total, bisa diurutkan, ekspor CSV), panel **Execution Time** |
| **Benchmark** | pilih query, `runs` (default 5) + `warm-up` (1), progress bar, tabel min/avg/median/p95/max/rows, grafik batang, riwayat, ekspor CSV/JSON/Markdown |
| **Transaksi** | setoran/penarikan/transfer (W-07) dengan idempotency key, tombol "Kirim ulang dengan key yang sama", riwayat rekening (R-01) |

### Execution time: apa yang diukur
| Field | Arti |
|---|---|
| `couchbase_ms` | waktu di sekitar pemanggilan driver Couchbase (KV, transaksi, N1QL; **semua hasil dikonsumsi**) |
| `cassandra_ms` | waktu di sekitar pemanggilan driver Cassandra |
| `server_exec_ms` | `executionTime` bawaan Couchbase (`metadata.metrics`) = waktu eksekusi murni di server DB |
| `app_ms` | `total − couchbase − cassandra` (validasi, mapping, serialisasi) |
| `total_ms`, `rows_returned` | dari awal sampai hasil siap, dan jumlah baris total |
| `ledger_visible_lag_ms` | khusus W-07: jeda sampai event terlihat di Cassandra (sinkron = 0) |

Pengukuran memakai `time.perf_counter_ns()` (`app/timing.py`). Modul ini **membungkus** (monkeypatch) metode repository/service saat startup,
sehingga kode lama tidak diubah. Setiap respons `/api/queries/{id}/run` memuat `meta.timing` dan header `Server-Timing`.

### Data uji & keamanan query tulis
* Query tulis hanya menyentuh **data uji**: rekening `002999000000001..005`, nasabah `NSB999000001` (+ `NSB99*`), kartu `5229990000000001` (+ `52299*`), instruksi `INSW99*`.
  Data uji dibuat otomatis saat startup; **Reset data uji** (tab Status atau `POST /api/test-data/reset`) mengembalikannya ke baseline.
* Query tulis wajib konfirmasi (`confirm=true` / dialog di UI). Benchmark WRITE butuh `confirm_write=true`.
* Benchmark WRITE: tiap run → jalankan → **pulihkan baseline** (pemulihan tidak diukur; status `pemulihan_baseline` dicatat). Event ledger dan outbox hasil run ikut dihapus.
* `scripts/validate_seed.py` mengecualikan data uji dari hitungan seed.

### Endpoint
| Method | Path | Keterangan |
|---|---|---|
| GET | `/ui` | halaman UI |
| GET | `/api/status` | status DB, versi, jumlah data |
| GET | `/api/queries` | katalog 20 query + parameter default + statement |
| POST | `/api/queries/{id}/run` | body `{"params": {...}, "confirm": false}` → `{"data": ..., "meta": {"timing": ...}}` |
| POST | `/api/benchmark` | body `{"ids":[...]|"grup":"R|W|ALL","runs":5,"warmup":1,"confirm_write":true}` → `job_id` |
| GET | `/api/benchmark/jobs/{job_id}` | progress + hasil |
| GET | `/api/benchmark/results[/{file}?format=json|csv|md]` | riwayat & ekspor |
| POST | `/api/test-data/reset` | pulihkan data uji |

### Menjalankan
```bash
docker compose up -d                                   # lihat bagian "Menjalankan" di atas
python -m uvicorn app.main:app --port 8765             # buka http://127.0.0.1:8765/ui
python scripts/smoke_benchmark.py 5                    # benchmark kecil, cetak tabel ke terminal
python -m pytest tests -q                              # 44 tes (unit + integrasi + UI/katalog)
```
Hasil benchmark tersimpan di `benchmark_results/<timestamp>_<id>.json` (contoh nyata sudah ada).

### Menambah query baru ke katalog
Di `app/query_catalog.py`: tulis fungsi `run(params)` (baca → `cb_query(...)`/`ledger()...`; tulis → kembalikan daftar `undo`), lalu `reg(Q(id, kind, title, desc, db, [Param(...)], statement, run))`
dan tambahkan id ke `ORDER`. UI dan benchmark otomatis ikut.

### Perbedaan katalog awal vs implementasi repo
* **R-07 dan W-08 (posting bunga)**: katalog awal menyebut Cassandra; implementasi repo menyimpan `posting_bunga` di **Couchbase**. Mengikuti implementasi repo.
* **W-01..W-04, W-06, W-08, W-09**: sebelumnya hanya berupa N1QL (`infra/couchbase/write_queries.n1ql`); runner-nya baru di katalog (W-02, W-03 memakai transaksi ACID dua dokumen).
* **W-05, W-10, W-07**: memakai `TransaksiService` yang sudah ada (event masuk ledger lewat outbox).
* **R-02 = 2.657** (bukan 2.656): nasabah uji `NSB999000001` memiliki 5 rekening aktif dan ikut terhitung.
