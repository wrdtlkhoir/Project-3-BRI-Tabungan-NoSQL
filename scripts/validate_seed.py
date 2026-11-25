"""Validasi setelah seeding: jumlah dokumen Couchbase, jumlah event Cassandra, konsistensi identifier."""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import psycopg
from app.config import get_settings
from app.database.couchbase_db import get_cluster
from app.database.cassandra_db import get_session
from couchbase.options import QueryOptions
from couchbase.n1ql import QueryScanConsistency

s = get_settings(); ok = True
def check(label, a, b):
    global ok
    flag = "OK  " if a == b else "BEDA"
    ok &= (a == b)
    print(f"[{flag}] {label}: sumber PG={a:,}  target={b:,}")

with psycopg.connect(s.pg_dsn) as pg, pg.cursor() as cur:
    q = lambda sql: (cur.execute(sql), cur.fetchone()[0])[1]
    pgc = {"produk": q("select count(*) from produk_tabungan"), "unit_kerja": q("select count(*) from unit_kerja"),
           "kanal": q("select count(*) from kanal_layanan"), "nasabah": q("select count(*) from nasabah"),
           "rekening": q("select count(*) from rekening_tabungan"), "kartu_debit": q("select count(*) from kartu_debit"),
           "posting_bunga": q("select count(*) from posting_bunga"), "instruksi_terjadwal": q("select count(*) from instruksi_terjadwal")}
    pg_tx = q("select count(*) from transaksi_tabungan")
    pg_saldo = q("select coalesce(sum(saldo_efektif),0) from rekening_tabungan")

cl = get_cluster(); opt = QueryOptions(scan_consistency=QueryScanConsistency.REQUEST_PLUS)
for c, n in pgc.items():
    # data uji UI/benchmark (rekening 002999*, nasabah NSB99*, kartu 52299*, instruksi INSW99*, posting 002999*) dikecualikan
    excl = {"nasabah": "(d.id_nasabah LIKE 'NSB99%')", "rekening": "(d.no_rekening LIKE '002999%')", "kartu_debit": "(d.no_kartu LIKE '52299%')",
            "instruksi_terjadwal": "(d.id_instruksi LIKE 'INSW99%')", "posting_bunga": "(d.no_rekening LIKE '002999%')"}.get(c)
    where = f" WHERE NOT {excl}" if excl else ""
    got = list(cl.query(f"SELECT COUNT(*) AS n FROM `bri_tabungan`.`operasional`.`{c}` d{where}", opt).rows())[0]["n"]
    check(f"Couchbase {c}", n, got)
tot_sen = list(cl.query("SELECT SUM(r.saldo_efektif_sen) AS t FROM `bri_tabungan`.`operasional`.`rekening` r WHERE r.no_rekening NOT LIKE '002999%'", opt).rows())[0]["t"]

ses = get_session()
# rekonsiliasi saldo: total saldo Couchbase = total seed (PG) + net event API di ledger (setoran/transfer masuk - penarikan/transfer keluar)
net = 0
n_api_uji = 0
for r in ses.execute("SELECT jenis_transaksi, nominal, no_rekening FROM transaksi_by_id"):
    if r.no_rekening.startswith("002999"):          # event data uji tidak dihitung
        n_api_uji += 1
        continue
    sign = 1 if r.jenis_transaksi in ("SETORAN", "TRANSFER_MASUK") else (-1 if r.jenis_transaksi in ("PENARIKAN", "TRANSFER_KELUAR") else 0)
    net += sign * int(r.nominal * 100)
check("Rekonsiliasi total saldo Couchbase = seed PG + net event ledger (sen)", int(pg_saldo * 100) + net, int(tot_sen))
# Cassandra tidak punya COUNT(*) murah lintas partisi: hitung dari tabel kanal (7 kanal x 12 bulan) atau sampel
total = 0
for kanal in ["KNL01", "KNL02", "KNL03", "KNL04", "KNL05", "KNL06", "KNL07"]:
    for b in [f"2025{m:02d}" for m in (11, 12)] + [f"2026{m:02d}" for m in range(1, 12)]:
        total += ses.execute("SELECT COUNT(*) FROM transaksi_by_kanal_periode WHERE id_kanal=%s AND periode=%s", [kanal, b]).one()[0]
n_api = ses.execute("SELECT COUNT(*) FROM transaksi_by_id").one()[0]      # event yang dibuat API (bukan seed), termasuk data uji
check("Cassandra ledger (transaksi_by_kanal_periode, event SEED saja)", pg_tx, total - n_api)
print(f"       (event dari API setelah seed: {n_api})")

# konsistensi identifier: rekening uji ada di kedua DB dan jumlah event ledger = tx_count Couchbase
from app.repositories.couchbase_repository import CouchbaseRepository
cb = CouchbaseRepository()
for no in ("002101000000001", "002101000000004"):
    doc = cb.get_rekening(no)
    n_led = ses.execute("SELECT COUNT(*) FROM transaksi_by_rekening WHERE no_rekening=%s", [no]).one()[0]
    check(f"rekening {no}: tx_count Couchbase vs event ledger", doc["tx_count"], n_led)
print("HASIL VALIDASI:", "SEMUA OK" if ok else "ADA PERBEDAAN")
sys.exit(0 if ok else 1)
