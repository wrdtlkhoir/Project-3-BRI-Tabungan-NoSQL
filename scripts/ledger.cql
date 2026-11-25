-- Event Ledger (append-only), Cassandra.
-- Prinsip: query-driven. Tiga tabel, masing-masing melayani satu pola akses.
CREATE KEYSPACE IF NOT EXISTS bri_tabungan
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};
USE bri_tabungan;

-- R-01: riwayat transaksi per rekening, terbaru dulu
CREATE TABLE IF NOT EXISTS transaksi_by_rekening (
  no_rekening       text,
  waktu_transaksi   timestamp,
  id_transaksi      text,
  jenis_transaksi   text,      -- SETORAN | PENARIKAN | TRANSFER_KELUAR | TRANSFER_MASUK | PEMBAYARAN | BIAYA | REVERSAL | STATUS_*
  arah              text,      -- KREDIT | DEBIT
  nominal           decimal,
  mata_uang         text,
  id_kanal          text,
  nama_kanal        text,
  no_kartu          text,
  status_transaksi  text,      -- BERHASIL | GAGAL | PENDING | REVERSED
  saldo_setelah     decimal,
  counterparty      text,      -- rekening lawan (transfer)
  sumber            text,      -- SEED | API
  PRIMARY KEY ((no_rekening), waktu_transaksi, id_transaksi)
) WITH CLUSTERING ORDER BY (waktu_transaksi DESC, id_transaksi ASC);

-- R-03: laporan jumlah dan nominal per bulan per kanal (GROUP BY dikerjakan server)
CREATE TABLE IF NOT EXISTS transaksi_by_kanal_periode (
  id_kanal          text,
  periode           text,      -- YYYYMM
  status_transaksi  text,
  jenis_transaksi   text,
  waktu_transaksi   timestamp,
  id_transaksi      text,
  nama_kanal        text,
  nominal           decimal,
  PRIMARY KEY ((id_kanal, periode), status_transaksi, jenis_transaksi, waktu_transaksi, id_transaksi)
);

-- lookup per id_transaksi (idempotensi W-07 dan jejak audit)
CREATE TABLE IF NOT EXISTS transaksi_by_id (
  id_transaksi      text PRIMARY KEY,
  no_rekening       text,
  waktu_transaksi   timestamp,
  jenis_transaksi   text,
  nominal           decimal,
  status_transaksi  text,
  saldo_setelah     decimal,
  sumber            text
);
