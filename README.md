# BRI Tabungan NoSQL — Couchbase (main) + Cassandra (Event Ledger), versi lokal

Project 3 Manajemen Data (IF5101). Sistem tabungan BRI dari Project 2 diimplementasikan pada dua database NoSQL yang
saling terhubung lewat backend Python (FastAPI).

| Komponen | Peran |
|---|---|
| **Couchbase CE 7.6.1** | Main database: nasabah, rekening (saldo integer sen), kartu, produk, unit kerja, kanal, posting bunga, instruksi, **outbox** |
| **Cassandra 5.0** | **Event Ledger** append-only: `ledger_by_rekening`, `ledger_event_by_id`, `ledger_by_kanal_bulan` (keyspace `bri_ledger`) |
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
