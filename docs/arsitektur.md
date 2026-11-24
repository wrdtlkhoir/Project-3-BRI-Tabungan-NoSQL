# Arsitektur (Local) — Couchbase + Cassandra Event Ledger

```
Client ──HTTP──▶ FastAPI backend (Python)
                    │  validasi, business logic, idempotensi, relay outbox
         ┌──────────┴───────────┐
         ▼                      ▼
   Couchbase CE 7.6.1       Cassandra 5.0
   (main database)          (Event Ledger, append-only)
   rekening, nasabah, ...   ledger_by_rekening ((no_rekening, bulan), waktu DESC)
   saldo (integer sen)      ledger_event_by_id
   outbox (PENDING→PUBLISHED) ledger_by_kanal_bulan
```

## Alur setoran (Transactional Outbox)
1. Client kirim `POST /transaksi/setoran` dengan `idempotency_key`.
2. **Satu transaksi ACID Couchbase**: baca rekening → validasi → update saldo (`saldo_efektif_sen`) →
   tulis dokumen `outbox::<event_id>` berstatus `PENDING`.
3. Backend menulis event ke Cassandra (logged batch ke 3 tabel; idempoten karena primary key deterministik).
4. Outbox ditandai `PUBLISHED`. Respons ke client memuat `ledger_status`.
5. Jika Cassandra gagal di langkah 3, saldo tetap benar, event aman di outbox, **relay** (background tiap 2 detik atau
   `POST /admin/outbox/relay`) mengulang sampai berhasil. Retry client dengan kunci yang sama → `duplicate: true`, tidak ganda.

## Trade-off
* Tidak ada distributed transaction Couchbase↔Cassandra → konsistensi akhir (eventual) untuk ledger; saldo selalu konsisten (ACID di Couchbase).
* Delivery event = *at-least-once* + penulisan idempoten = efek *exactly-once* pada ledger.
* Alternatif ditolak: dual-write langsung (event bisa hilang), Saga penuh (kompleks untuk 2 database), LWT Cassandra per event
  (4 fase Paxos per tulis → lebih lambat; lihat Part-3 laporan).

## Konfigurasi
Semua koneksi dari `.env` (`.env.example` memuat contoh local dan cloud). Backend tidak berubah antara cloud dan local.
