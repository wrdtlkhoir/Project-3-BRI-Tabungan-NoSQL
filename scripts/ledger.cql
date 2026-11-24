-- Event Ledger (append-only) — Cassandra
-- Prinsip: query-driven, partisi dibatasi per (rekening, bulan) agar tidak tumbuh tanpa batas.
CREATE KEYSPACE IF NOT EXISTS bri_ledger
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};
USE bri_ledger;

-- R-01: histori transaksi per rekening, terbaru dulu, bulan = format YYYYMM
CREATE TABLE IF NOT EXISTS ledger_by_rekening (
  no_rekening     text,
  bulan           text,
  waktu_event     timestamp,
  event_id        text,
  jenis_event     text,      -- SETORAN | PENARIKAN | TRANSFER_KELUAR | TRANSFER_MASUK | PEMBAYARAN | BIAYA | REVERSAL
  arah            text,      -- KREDIT | DEBIT
  nominal         decimal,
  mata_uang       text,
  id_kanal        text,
  nama_kanal      text,
  no_kartu        text,
  status_event    text,      -- BERHASIL | GAGAL | PENDING | REVERSED
  saldo_setelah   decimal,
  counterparty    text,      -- rekening lawan (transfer)
  sumber          text,      -- SEED | API
  PRIMARY KEY ((no_rekening, bulan), waktu_event, event_id)
) WITH CLUSTERING ORDER BY (waktu_event DESC, event_id ASC);

-- lookup/audit per event_id (idempotensi & jejak audit)
CREATE TABLE IF NOT EXISTS ledger_event_by_id (
  event_id      text PRIMARY KEY,
  no_rekening   text,
  bulan         text,
  waktu_event   timestamp,
  jenis_event   text,
  nominal       decimal,
  status_event  text,
  saldo_setelah decimal,
  sumber        text
);

-- R-03: laporan jumlah dan nominal per bulan per kanal
CREATE TABLE IF NOT EXISTS ledger_by_kanal_bulan (
  id_kanal      text,
  bulan         text,
  waktu_event   timestamp,
  event_id      text,
  nama_kanal    text,
  jenis_event   text,
  nominal       decimal,
  status_event  text,
  PRIMARY KEY ((id_kanal, bulan), waktu_event, event_id)
);
