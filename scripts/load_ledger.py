"""Muat riwayat transaksi Project 2 (PostgreSQL, hasil restore dump) ke Event Ledger Cassandra.

Sumber SAMA dengan loader Couchbase (dump tabungan_bri.dump) -> data kedua DBMS identik
(catatan reviewer: seed sekali, isi kedua DBMS dari dump yang sama).
event_id = id_transaksi Project 2 (identifier konsisten dengan sumber)."""
import pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import psycopg
from cassandra.concurrent import execute_concurrent_with_args
from app.config import get_settings
from app.database.cassandra_db import get_session

s = get_settings()
session = get_session()
ins_main = session.prepare("""INSERT INTO ledger_by_rekening (no_rekening, bulan, waktu_event, event_id, jenis_event, arah,
    nominal, mata_uang, id_kanal, nama_kanal, no_kartu, status_event, saldo_setelah, counterparty, sumber)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""")
ins_kanal = session.prepare("""INSERT INTO ledger_by_kanal_bulan (id_kanal, bulan, waktu_event, event_id, nama_kanal,
    jenis_event, nominal, status_event) VALUES (?,?,?,?,?,?,?,?)""")

t0 = time.time(); n = 0
SQL = """SELECT t.no_rekening, t.waktu_transaksi, t.id_transaksi, t.jenis_transaksi, t.arah, t.nominal, t.mata_uang,
                t.id_kanal, k.nama_kanal, t.no_kartu, t.status_transaksi, t.saldo_setelah
         FROM transaksi_tabungan t JOIN kanal_layanan k USING (id_kanal)"""
with psycopg.connect(s.pg_dsn) as conn, conn.cursor(name="c") as cur:
    cur.itersize = 20000
    cur.execute(SQL)
    main, kan = [], []
    def flush():
        global n
        for stmt, rows in ((ins_main, main), (ins_kanal, kan)):
            results = execute_concurrent_with_args(session, stmt, rows, concurrency=40, raise_on_first_error=False)
            for (ok, res), params in zip(results, rows):
                if ok:
                    continue
                for attempt in range(8):                     # retry (penulisan idempoten: aman diulang)
                    try:
                        time.sleep(0.5 * (attempt + 1))
                        session.execute(stmt, params)
                        break
                    except Exception:
                        if attempt == 7:
                            raise
        n += len(main); main.clear(); kan.clear()
        print(f"  ... {n:,} baris ({time.time()-t0:.0f}s)", flush=True)
    for r in cur:
        no, w, eid, jenis, arah, nom, cur_, kanal, knama, kartu, st, saldo = r
        bulan = w.strftime("%Y%m")
        main.append((no, bulan, w, eid, jenis, arah, nom, (cur_ or "IDR").strip(), kanal, knama, kartu, st, saldo, None, "SEED"))
        kan.append((kanal, bulan, w, eid, knama, jenis, nom, st))
        if len(main) >= 10000:
            flush()
    if main:
        flush()
print(f"SELESAI: {n:,} event dimuat ke Cassandra ({time.time()-t0:.0f}s)")
