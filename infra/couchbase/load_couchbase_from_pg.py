"""
Muat data Tabungan BRI hasil pg_restore(tabungan_bri.dump) ke Couchbase.

Kenapa script ini, bukan seed_couchbase.py?
-------------------------------------------
seed_couchbase.py MENGENERASI ULANG data dengan Faker + tanggal relatif
('-1y', 'today'), jadi hasilnya bergantung pada hari eksekusi (itulah sebabnya
saldo rekening 002101000000001 bisa beda antar laptop). Untuk laporan, sumber
kebenarannya adalah dump PostgreSQL yang sama dipakai Part-2 dan Cassandra.

Script ini hanya MEMBACA PostgreSQL lalu menulis dokumen Couchbase dengan
bentuk yang sama persis seperti seed_couchbase.py (key, field, array embed).

Jalankan:
    python load_couchbase_from_pg.py

Prasyarat:
    - PostgreSQL tabungan_bri sudah di-restore dari tabungan_bri.dump di :5434
    - bucket/scope/collection sesuai couchbase_ddl.n1ql sudah dibuat
    - pip install "psycopg[binary]" "couchbase>=4.1"
"""
import os
import time
from datetime import date, datetime, timezone

import psycopg
from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.exceptions import DocumentNotFoundException
from couchbase.options import ClusterOptions

PG_DSN = os.getenv(
    "PG_DSN",
    "host=localhost port=5434 dbname=tabungan_bri user=postgres password=password",
)
CB_CONN_STR = os.getenv("CB_CONN_STR", "couchbase://localhost")
CB_USERNAME = os.getenv("CB_USERNAME", "Administrator")
CB_PASSWORD = os.getenv("CB_PASSWORD", "password")
CB_BUCKET = "bri_tabungan"
CB_SCOPE = "operasional"
BATCH = 1000


# ---------------------------------------------------------------------------
# Konversi tipe PostgreSQL -> JSON Couchbase
# ---------------------------------------------------------------------------
def iso(value):
    """date/datetime -> string ISO; TIMESTAMPTZ dibuang offset-nya supaya
    sama dengan datetime naive yang dipakai seed_bri.py / seed_couchbase.py."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def num(value):
    """Decimal -> float (json.dumps tidak bisa menyerialkan Decimal)."""
    return float(value) if value is not None else None


def sen(value):
    """Decimal rupiah -> integer sen (tidak ada floating point; catatan reviewer)."""
    from decimal import Decimal
    return int((Decimal(value) * 100).to_integral_value()) if value is not None else None


def clean(value):
    """CHAR(n) PostgreSQL bisa membawa spadding trailing."""
    return value.strip() if isinstance(value, str) else value


# ---------------------------------------------------------------------------
# Bangun semua dokumen di memori dari PostgreSQL
# ---------------------------------------------------------------------------
def build_documents(conn):
    docs = {
        "produk": {},
        "unit_kerja": {},
        "kanal": {},
        "nasabah": {},
        "rekening": {},
        "kartu_debit": {},
        "posting_bunga": {},
        "instruksi_terjadwal": {},
    }

    with conn.cursor() as cur:
        # ---- produk ------------------------------------------------------
        cur.execute("""
            SELECT id_produk, nama_produk, keluarga_produk, segmen_tujuan,
                   mata_uang, saldo_minimum, skema_bunga, biaya_admin, status_produk
            FROM produk_tabungan
        """)
        for r in cur:
            docs["produk"][f"produk::{r[0]}"] = {
                "_type": "produk", "id_produk": r[0], "nama_produk": r[1],
                "keluarga_produk": r[2], "segmen_tujuan": r[3],
                "mata_uang": clean(r[4]), "saldo_minimum": num(r[5]),
                "skema_bunga": r[6], "biaya_admin": num(r[7]), "status_produk": r[8],
            }

        # ---- unit_kerja --------------------------------------------------
        cur.execute("""
            SELECT id_unit_kerja, nama_unit_kerja, jenis_unit_kerja,
                   alamat_lokasi, id_unit_induk
            FROM unit_kerja
        """)
        for r in cur:
            docs["unit_kerja"][f"unit_kerja::{r[0]}"] = {
                "_type": "unit_kerja", "id_unit_kerja": r[0],
                "nama_unit_kerja": r[1], "jenis_unit_kerja": r[2],
                "alamat_lokasi": r[3], "id_unit_induk": r[4],
            }

        # ---- kanal -------------------------------------------------------
        cur.execute("SELECT id_kanal, nama_kanal, tipe_kanal, status_operasional FROM kanal_layanan")
        for r in cur:
            docs["kanal"][f"kanal::{r[0]}"] = {
                "_type": "kanal", "id_kanal": r[0], "nama_kanal": r[1],
                "tipe_kanal": r[2], "status_operasional": r[3],
            }

        # ---- nasabah -----------------------------------------------------
        cur.execute("""
            SELECT id_nasabah, nik, nama_lengkap, jenis_nasabah, segmen_nasabah,
                   status_kyc, tanggal_registrasi
            FROM nasabah
        """)
        for r in cur:
            docs["nasabah"][f"nasabah::{r[0]}"] = {
                "_type": "nasabah", "id_nasabah": r[0], "nik": r[1],
                "nama_lengkap": r[2], "jenis_nasabah": r[3], "segmen_nasabah": r[4],
                "status_kyc": r[5], "tanggal_registrasi": iso(r[6]),
                "rekening_refs": [],   # diisi dari pemegang_rekening
            }

        # ---- rekening ----------------------------------------------------
        cur.execute("""
            SELECT no_rekening, id_produk, mata_uang, tanggal_buka, tanggal_tutup,
                   status_rekening, saldo_efektif, saldo_tersedia, id_unit_kerja
            FROM rekening_tabungan
        """)
        for r in cur:
            docs["rekening"][f"rekening::{r[0]}"] = {
                "_type": "rekening", "no_rekening": r[0], "id_produk": r[1],
                "mata_uang": clean(r[2]), "tanggal_buka": iso(r[3]),
                "tanggal_tutup": iso(r[4]), "status_rekening": r[5],
                "saldo_efektif": num(r[6]), "saldo_tersedia": num(r[7]),
                "saldo_efektif_sen": sen(r[6]), "saldo_tersedia_sen": sen(r[7]),
                "id_unit_kerja": r[8],
                "pemegang_rekening": [],   # diisi dari pemegang_rekening
                "last_transaction_at": None, "tx_count": 0,  # diisi dari ledger
            }

        # ---- pemegang_rekening -> embed ke dua arah ----------------------
        cur.execute("""
            SELECT no_rekening, id_nasabah, peran, penanda_utama, tanggal_mulai
            FROM pemegang_rekening
            ORDER BY no_rekening, peran, id_nasabah
        """)
        for norek, nid, peran, utama, mulai in cur:
            rekening_doc = docs["rekening"].get(f"rekening::{norek}")
            nasabah_doc = docs["nasabah"].get(f"nasabah::{nid}")
            if rekening_doc is not None:
                rekening_doc["pemegang_rekening"].append({
                    "id_nasabah": nid, "peran": peran,
                    "penanda_utama": clean(utama), "tanggal_mulai": iso(mulai),
                })
            if nasabah_doc is not None:
                nasabah_doc["rekening_refs"].append({
                    "no_rekening": norek, "peran": peran, "penanda_utama": clean(utama),
                })

        # ---- field turunan dari ledger (sama seperti seed_couchbase.py) --
        cur.execute("""
            SELECT no_rekening,
                   MAX(waktu_transaksi) FILTER (WHERE status_transaksi = 'BERHASIL') AS last_tx,
                   COUNT(*) AS n
            FROM transaksi_tabungan
            GROUP BY no_rekening
        """)
        for norek, last_tx, n in cur:
            doc = docs["rekening"].get(f"rekening::{norek}")
            if doc is not None:
                doc["last_transaction_at"] = iso(last_tx)
                doc["tx_count"] = n

        # ---- kartu_debit -------------------------------------------------
        cur.execute("""
            SELECT no_kartu, no_rekening, bentuk_kartu, jaringan_kartu,
                   status_kartu, tanggal_terbit, tanggal_kadaluarsa
            FROM kartu_debit
        """)
        for r in cur:
            docs["kartu_debit"][f"kartu_debit::{r[0]}"] = {
                "_type": "kartu_debit", "no_kartu": r[0], "no_rekening": r[1],
                "bentuk_kartu": r[2], "jaringan_kartu": r[3], "status_kartu": r[4],
                "tanggal_terbit": iso(r[5]), "tanggal_kadaluarsa": iso(r[6]),
            }

        # ---- posting_bunga ----------------------------------------------
        cur.execute("""
            SELECT no_rekening, periode, hari_berjalan, tarif_bunga, bunga_kotor,
                   pajak_pph_final, bunga_bersih, tanggal_posting
            FROM posting_bunga
        """)
        for r in cur:
            periode = clean(r[1])
            docs["posting_bunga"][f"posting::{r[0]}::{periode}"] = {
                "_type": "posting_bunga", "no_rekening": r[0], "periode": periode,
                "hari_berjalan": r[2], "tarif_bunga": num(r[3]),
                "bunga_kotor": num(r[4]), "pajak_pph_final": num(r[5]),
                "bunga_bersih": num(r[6]), "tanggal_posting": iso(r[7]),
            }

        # ---- instruksi_terjadwal ----------------------------------------
        cur.execute("""
            SELECT id_instruksi, jenis_instruksi, no_rekening_sumber,
                   no_rekening_tujuan, frekuensi, hari_eksekusi, nominal_target,
                   status_instruksi, tanggal_mulai, tanggal_selesai
            FROM instruksi_terjadwal
        """)
        for r in cur:
            docs["instruksi_terjadwal"][f"instruksi::{r[0]}"] = {
                "_type": "instruksi_terjadwal", "id_instruksi": r[0],
                "jenis_instruksi": r[1], "no_rekening_sumber": r[2],
                "no_rekening_tujuan": r[3], "frekuensi": r[4],
                "hari_eksekusi": r[5], "nominal_target": num(r[6]),
                "status_instruksi": r[7], "tanggal_mulai": iso(r[8]),
                "tanggal_selesai": iso(r[9]),
            }

    return docs


# ---------------------------------------------------------------------------
# Tulis ke Couchbase
# ---------------------------------------------------------------------------
def upsert_all(collection, documents, label):
    """Upsert batch dan PERIKSA hasil per dokumen. upsert_multi tidak melempar error untuk kegagalan
    parsial (hanya dikembalikan di result.exceptions), jadi dokumen bisa hilang diam-diam; di sini
    dokumen yang gagal di-retry satu per satu dan kalau tetap gagal proses dihentikan."""
    items = list(documents.items())
    t0 = time.time()
    for i in range(0, len(items), BATCH):
        batch = dict(items[i:i + BATCH])
        res = collection.upsert_multi(batch)
        failed = list((getattr(res, "exceptions", None) or {}).keys())
        for attempt in range(1, 6):
            if not failed:
                break
            time.sleep(0.5 * attempt)
            still = []
            for k in failed:
                try:
                    collection.upsert(k, batch[k])
                except Exception:
                    still.append(k)
            failed = still
        if failed:
            raise SystemExit(f"{label}: {len(failed)} dokumen gagal ditulis (contoh {failed[:3]})")
        print(f"  ... {label}: {min(i + BATCH, len(items))}/{len(items)}", flush=True)
    print(f"selesai {label}: {len(items)} dokumen ({time.time() - t0:.1f}s)", flush=True)


def main():
    t0 = time.time()
    with psycopg.connect(PG_DSN) as conn:
        docs = build_documents(conn)
    print(f"selesai baca PostgreSQL ({time.time() - t0:.1f}s)", flush=True)

    cluster = Cluster(
        CB_CONN_STR,
        ClusterOptions(PasswordAuthenticator(CB_USERNAME, CB_PASSWORD)),
    )
    scope = cluster.bucket(CB_BUCKET).scope(CB_SCOPE)

    # Guard tanpa N1QL: collection nasabah sengaja TANPA primary index, jadi
    # SELECT COUNT(*) akan gagal. Cek satu document key lewat KV saja.
    # CB_ALLOW_RELOAD=1 (dipakai docker-compose) melewati guard ini; upsert di
    # bawah tetap idempoten karena sumbernya selalu dump yang sama.
    if os.getenv("CB_ALLOW_RELOAD") == "1":
        print("CB_ALLOW_RELOAD=1 -> melewati guard, dokumen akan di-upsert ulang.")
    else:
        try:
            scope.collection("nasabah").get("nasabah::NSB000000001")
            raise SystemExit("sudah pernah dimuat (nasabah::NSB000000001 sudah ada). "
                             "Kosongkan collection dulu jika ingin mengulang.")
        except DocumentNotFoundException:
            pass

    only = {x.strip() for x in os.getenv("CB_ONLY", "").split(",") if x.strip()}   # opsional: muat sebagian koleksi
    for name, documents in docs.items():
        if only and name not in only:
            continue
        upsert_all(scope.collection(name), documents, name)

    cluster.close()
    total = sum(len(d) for d in docs.values())
    print(f"SELESAI — {total:,} dokumen Couchbase dari dump PostgreSQL "
          f"({time.time() - t0:.1f}s)")
    print("Jangan lupa BUILD INDEX (lihat SETUP_LOKAL.md langkah 6).")


if __name__ == "__main__":
    main()
