"""Benchmark kecil (R-07, R-10, W-08, W-07) langsung lewat modul, cetak tabel ke terminal. Butuh stack Docker + seed.
    python scripts/smoke_benchmark.py [runs]"""
import pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app import benchmark as bm
from app import query_catalog as qc
from app import timing
from app.repositories.cassandra_repository import CassandraLedgerRepository
from app.repositories.couchbase_repository import CouchbaseRepository
from app.services.rekening_service import RekeningService
from app.services.transaksi_service import TransaksiService

runs = int(sys.argv[1]) if len(sys.argv) > 1 else 5
trx = TransaksiService(); rek = RekeningService(trx.cb, trx.ledger)
timing.instrument(); qc.bind(trx, rek); qc.ensure_test_data()
jid = bm.start(["R-07", "R-10", "W-08", "W-07"], runs, 1, {}, trx)
while bm.JOBS[jid]["status"] == "berjalan":
    time.sleep(0.5)
j = bm.JOBS[jid]
print(f"\n{'ID':5} {'DB':10} {'min':>8} {'avg':>8} {'median':>8} {'p95':>8} {'max':>8} {'rows':>6} pulih")
for r in j["hasil"]:
    print(f"{r['id']:5} {r['db']:10} {r['min']:8.2f} {r['avg']:8.2f} {r['median']:8.2f} {r['p95']:8.2f} {r['max']:8.2f} {r['rows']:6} {r['pemulihan_baseline']}")
print("\nTersimpan:", bm.RESULT_DIR / j["file"])
