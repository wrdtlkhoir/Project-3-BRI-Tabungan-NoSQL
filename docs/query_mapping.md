# Pemetaan Query Project 2 → Project 3 (Couchbase + Cassandra Event Ledger)

Prinsip pembagian (menjawab catatan reviewer): **Couchbase = main database** (data operasional dan saldo),
**Cassandra = Event Ledger** (append-only, hanya riwayat/event transaksi). Couchbase **tidak** menyimpan transaksi;
Couchbase hanya menyimpan outbox sementara (antrian event yang belum terbit) agar event tidak hilang.

| Query | Deskripsi (Project 2) | Database | Implementasi Project 3 |
|---|---|---|---|
| R-01 | Riwayat transaksi suatu rekening | **Cassandra** | `GET /rekening/{no}/histori` → `ledger_by_rekening` (partisi no_rekening+bulan) |
| R-02 | Nasabah dengan >1 rekening | Couchbase | `GET /laporan/R-02` (N1QL, UNNEST pemegang_rekening) |
| R-03 | Laporan jumlah & nominal per bulan per kanal | **Cassandra** | `GET /laporan/R-03` → `ledger_by_kanal_bulan` (agregasi di aplikasi) |
| R-04 | Rekening tak bertransaksi >90 hari | Couchbase | `GET /laporan/R-04` (field `last_transaction_at` di dokumen rekening, diisi dari transaksi BERHASIL) |
| R-05 | Nasabah tanpa rekening | Couchbase | `GET /laporan/R-05` |
| R-06 | Rekap saldo per unit kerja | Couchbase | `GET /laporan/R-06` |
| R-07 | Riwayat posting bunga rekening | Couchbase | `GET /laporan/R-07?no_rekening=` |
| R-08 | Instruksi terjadwal aktif | Couchbase | `GET /laporan/R-08` |
| R-09 | Kartu debit kadaluarsa ≤30 hari | Couchbase | `GET /laporan/R-09` |
| R-10 | Distribusi rekening & saldo per produk | Couchbase | `GET /laporan/R-10` |
| W-01 | Daftar nasabah baru | Couchbase | N1QL `infra/couchbase/write_queries.n1ql` (dokumen `nik::` menjaga keunikan NIK) |
| W-02 | Buka rekening baru | Couchbase | N1QL `write_queries.n1ql` |
| W-03 | Catat pemegang rekening | Couchbase | N1QL `write_queries.n1ql` (embed dua arah) |
| W-04 | Daftar kartu debit | Couchbase | N1QL `write_queries.n1ql` |
| W-05 | Blokir rekening | Couchbase **+ ledger** | `POST /rekening/{no}/blokir` (transaksi ACID + event `STATUS_BLOKIR`) |
| W-06 | Blokir sementara kartu | Couchbase | N1QL `write_queries.n1ql` (via GSI `idx_kartu_rekening`) |
| W-07 | Setoran/penarikan/transfer + update saldo | **Couchbase + Cassandra** | `POST /transaksi/setoran|penarikan|transfer` (transaksi ACID + transactional outbox + ledger) |
| W-08 | Posting bunga bulanan | Couchbase | N1QL `write_queries.n1ql` (kunci komposit `posting::no::periode` = idempoten) |
| W-09 | Instruksi terjadwal baru | Couchbase | N1QL `write_queries.n1ql` |
| W-10 | Tutup rekening | Couchbase **+ ledger** | `POST /rekening/{no}/tutup` (hanya jika AKTIF dan saldo 0; event `STATUS_TUTUP`) |

## Query SQL yang tidak dapat diterjemahkan langsung
* **JOIN** (R-01 ke `kanal_layanan`, R-03, R-09): Cassandra tidak punya JOIN → `nama_kanal` didenormalisasi ke event ledger.
  Couchbase memakai `JOIN ... ON KEYS` / `UNNEST` terhadap dokumen yang di-embed.
* **`NOT EXISTS` atas tabel transaksi** (R-04): Couchbase tidak menyimpan transaksi → dipindah ke atribut turunan
  `last_transaction_at` yang diperbarui aplikasi di dalam transaksi yang sama dengan perubahan saldo.
* **Agregasi lintas partisi** (R-03): Cassandra tidak efisien untuk agregasi ad-hoc → tabel `ledger_by_kanal_bulan`
  (partisi per kanal+bulan) dan agregasi di aplikasi; untuk analitik berat disarankan Spark/OLAP.
* **FK & CHECK constraint**: tidak ada di NoSQL → validasi (status AKTIF, saldo cukup, nominal > 0) dilakukan service layer.
