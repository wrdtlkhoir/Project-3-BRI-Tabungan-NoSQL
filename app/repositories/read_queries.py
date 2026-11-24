"""Catatan: agregasi saldo memakai kolom integer saldo_efektif_sen (dibagi 100) agar tidak ada sisa
desimal floating point (mis. 280839026180.20013).

Query Read Project 2 (R-02 .. R-10) diterjemahkan ke N1QL pada Couchbase.
Teks query berasal dari laporan Part-3 (bagian Couchbase) — tidak dikarang ulang.
R-01 (riwayat transaksi) dan R-03 (laporan per kanal) dilayani Cassandra (Event Ledger)."""

KS = "`bri_tabungan`.`operasional`"

R02 = f"""SELECT h.id_nasabah, n.nama_lengkap, COUNT(DISTINCT r.no_rekening) AS jumlah_rekening_aktif,
       ROUND(SUM(r.saldo_efektif_sen) / 100, 2) AS total_saldo_efektif
FROM {KS}.`rekening` r UNNEST r.pemegang_rekening h
JOIN {KS}.`nasabah` n ON KEYS 'nasabah::' || h.id_nasabah
WHERE r.status_rekening = 'AKTIF' AND h.id_nasabah IS NOT NULL
GROUP BY h.id_nasabah, n.nama_lengkap
HAVING COUNT(DISTINCT r.no_rekening) > 1
ORDER BY total_saldo_efektif DESC LIMIT 20"""

# R-04: pada Project 2 hanya transaksi BERHASIL yang dihitung. last_transaction_at diisi aplikasi
# dari event BERHASIL saja (lihat TransaksiService), sehingga cukup membaca dokumen rekening.
R04 = f"""SELECT r.no_rekening, r.saldo_efektif, r.saldo_tersedia, r.tanggal_buka
FROM {KS}.`rekening` r
WHERE r.status_rekening = 'AKTIF'
  AND (r.last_transaction_at IS MISSING OR r.last_transaction_at IS NULL
       OR STR_TO_MILLIS(r.last_transaction_at) < STR_TO_MILLIS(NOW_STR()) - (90 * 86400000))
ORDER BY r.saldo_efektif DESC LIMIT 20"""

R05 = f"""SELECT n.id_nasabah, n.nik, n.nama_lengkap, n.status_kyc, n.tanggal_registrasi
FROM {KS}.`nasabah` n
WHERE ARRAY_LENGTH(n.rekening_refs) = 0 OR n.rekening_refs IS MISSING
ORDER BY n.tanggal_registrasi DESC LIMIT 20"""

R06 = f"""SELECT u.id_unit_kerja, u.nama_unit_kerja, u.jenis_unit_kerja, COUNT(r.no_rekening) AS total_rekening,
       ROUND(IFMISSINGORNULL(SUM(r.saldo_efektif_sen), 0) / 100, 2) AS total_saldo_efektif
FROM {KS}.`unit_kerja` u LEFT JOIN {KS}.`rekening` r
  ON r.id_unit_kerja = u.id_unit_kerja AND r.status_rekening = 'AKTIF'
GROUP BY u.id_unit_kerja, u.nama_unit_kerja, u.jenis_unit_kerja
ORDER BY total_saldo_efektif DESC LIMIT 20"""

R07 = f"""SELECT p.periode, p.hari_berjalan, p.tarif_bunga, p.bunga_kotor, p.pajak_pph_final, p.bunga_bersih, p.tanggal_posting
FROM {KS}.`posting_bunga` p WHERE p.no_rekening = $no_rekening ORDER BY p.periode DESC"""

R08 = f"""SELECT i.id_instruksi, i.jenis_instruksi, i.no_rekening_sumber, i.no_rekening_tujuan, i.frekuensi,
       i.hari_eksekusi, i.nominal_target, i.tanggal_mulai, i.tanggal_selesai
FROM {KS}.`instruksi_terjadwal` i
WHERE i.status_instruksi = 'AKTIF'
  AND (i.tanggal_selesai IS NULL OR i.tanggal_selesai IS MISSING OR i.tanggal_selesai >= SUBSTR(NOW_STR(), 0, 10))
ORDER BY i.tanggal_mulai ASC LIMIT 20"""

R09 = f"""SELECT kd.no_kartu, kd.no_rekening, kd.bentuk_kartu, kd.jaringan_kartu, kd.status_kartu, kd.tanggal_kadaluarsa,
       n.nama_lengkap AS nama_pemilik
FROM {KS}.`kartu_debit` kd
JOIN {KS}.`rekening` r ON KEYS 'rekening::' || kd.no_rekening
UNNEST r.pemegang_rekening h
JOIN {KS}.`nasabah` n ON KEYS 'nasabah::' || h.id_nasabah
WHERE kd.status_kartu = 'AKTIF' AND h.penanda_utama = 'Y'
  AND kd.tanggal_kadaluarsa >= SUBSTR(NOW_STR(), 0, 10)
  AND kd.tanggal_kadaluarsa <= DATE_ADD_STR(NOW_STR(), 30, 'day')
ORDER BY kd.tanggal_kadaluarsa ASC LIMIT 20"""

R10 = f"""SELECT p.id_produk, p.nama_produk, p.keluarga_produk, COUNT(r.no_rekening) AS jumlah_rekening,
       ROUND(IFMISSINGORNULL(SUM(r.saldo_efektif_sen), 0) / 100, 2) AS total_saldo
FROM {KS}.`produk` p LEFT JOIN {KS}.`rekening` r ON r.id_produk = p.id_produk
GROUP BY p.id_produk, p.nama_produk, p.keluarga_produk ORDER BY jumlah_rekening DESC"""

COUCHBASE_READS = {"R-02": R02, "R-04": R04, "R-05": R05, "R-06": R06, "R-07": R07, "R-08": R08, "R-09": R09, "R-10": R10}
