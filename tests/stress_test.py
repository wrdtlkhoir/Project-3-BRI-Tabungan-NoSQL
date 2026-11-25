"""C. Stress test: Couchbase saja, Cassandra saja, dan integrasi. Ukur avg/P95/P99/throughput/error-rate.
Catatan: semua berjalan di satu laptop (tanpa jaringan antar node), jadi angka = batas bawah latensi."""
import argparse, json, pathlib, statistics, sys, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import psycopg
from app.config import get_settings
from app.services.transaksi_service import TransaksiService
from app.repositories.cassandra_repository import CassandraLedgerRepository


def accounts(n):
    with psycopg.connect(get_settings().pg_dsn) as c, c.cursor() as cur:
        cur.execute("select no_rekening from rekening_tabungan where status_rekening='AKTIF' and saldo_efektif>50000000 "
                    "order by no_rekening limit %s", [n])
        return [r[0] for r in cur.fetchall()]


def pct(v, p): 
    v = sorted(v); return v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))]


def run(name, fn, total, workers):
    lat, err = [], [0]
    lock = threading.Lock()
    def one(i):
        t = time.perf_counter()
        try:
            fn(i); ok = True
        except Exception:
            ok = False
        d = (time.perf_counter() - t) * 1000
        with lock:
            lat.append(d)
            if not ok: err[0] += 1
    t0 = time.perf_counter()
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, range(total)))
    el = time.perf_counter() - t0
    r = {"skenario": name, "request": total, "workers": workers, "avg_ms": round(statistics.mean(lat), 2),
         "p50_ms": round(pct(lat, 50), 2), "p95_ms": round(pct(lat, 95), 2), "p99_ms": round(pct(lat, 99), 2),
         "throughput_rps": round(total / el, 1), "error_rate_pct": round(100 * err[0] / total, 2)}
    print(r, flush=True)
    return r


def purge_synthetic(led, prefix):
    """Hapus event sintetis stress test (hanya ditulis ke Cassandra, tidak mengubah saldo Couchbase)."""
    s = led.s
    for r in list(s.execute("SELECT id_transaksi, no_rekening, waktu_transaksi, jenis_transaksi, status_transaksi FROM transaksi_by_id WHERE sumber='STRESS' ALLOW FILTERING")):
        if not r.id_transaksi.startswith(prefix.split("-")[0] + "-"):
            continue
        s.execute("DELETE FROM transaksi_by_rekening WHERE no_rekening=%s AND waktu_transaksi=%s AND id_transaksi=%s", [r.no_rekening, r.waktu_transaksi, r.id_transaksi])
        s.execute("DELETE FROM transaksi_by_kanal_periode WHERE id_kanal=%s AND periode=%s AND status_transaksi=%s AND jenis_transaksi=%s AND waktu_transaksi=%s AND id_transaksi=%s",
                  ["KNL01", r.waktu_transaksi.strftime("%Y%m"), r.status_transaksi, r.jenis_transaksi, r.waktu_transaksi, r.id_transaksi])
        s.execute("DELETE FROM transaksi_by_id WHERE id_transaksi=%s", [r.id_transaksi])


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=400); ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    svc = TransaksiService(); led = svc.ledger; cb = svc.cb
    accs = accounts(40); res = []
    run_id = uuid.uuid4().hex[:8]

    # 1. Couchbase saja
    res.append(run("Couchbase READ (KV get rekening)", lambda i: cb.get_rekening(accs[i % len(accs)]), a.n * 2, a.workers))
    def cb_write(i):
        no = accs[i % len(accs)]
        def logic(ctx):
            r = ctx.get(cb.rekening, f"rekening::{no}"); d = r.content_as[dict]; d["tx_count"] = d.get("tx_count", 0) + 0
            ctx.replace(r, d)
        cb.cluster.transactions.run(logic)
    res.append(run("Couchbase WRITE (transaksi ACID, 1 dokumen)", cb_write, a.n, a.workers))

    # 2. Cassandra saja
    def cas_write(i):
        led.append_event({"event_id": f"STRESS-{run_id}-{i}", "no_rekening": accs[i % len(accs)], "jenis_event": "SETORAN",
                          "arah": "KREDIT", "nominal_sen": 100_00, "saldo_setelah_sen": 100_00, "status_event": "BERHASIL",
                          "id_kanal": "KNL01", "nama_kanal": "BRImo Super App", "waktu_event": datetime.now(timezone.utc),
                          "sumber": "STRESS"})
    res.append(run("Cassandra WRITE (append event, 3 tabel)", cas_write, a.n, a.workers))
    now = datetime.now(timezone.utc); bl = [f"2026{m:02d}" for m in range(11, 12)] + ["202610", "202609"]
    res.append(run("Cassandra READ (histori R-01)", lambda i: led.history(accs[i % len(accs)], bl, limit=20), a.n * 2, a.workers))

    # 3. Integrasi: setoran end-to-end (Couchbase txn + outbox + Cassandra), rekening berbeda -> konflik minimal
    res.append(run("INTEGRASI setoran (CB txn + outbox + Cassandra)",
                   lambda i: svc.setoran(accs[i % len(accs)], Decimal("10000.00"), f"st-{run_id}-{i:06d}"), a.n, a.workers))

    # 4. Konsistensi: 100 setoran serentak ke SATU rekening (hot account)
    hot = accs[0]; s0 = cb.get_rekening(hot)["saldo_efektif_sen"]; N = 100
    r = run("INTEGRASI hot account (100 setoran serentak, 1 rekening)",
            lambda i: svc.setoran(hot, Decimal("1000.00"), f"hot-{run_id}-{i:05d}"), N, a.workers)
    s1 = cb.get_rekening(hot)["saldo_efektif_sen"]
    sukses = round(N * (1 - r["error_rate_pct"] / 100))
    r["konsistensi"] = {"saldo_awal_sen": s0, "saldo_akhir_sen": s1, "selisih_sen": s1 - s0,
                        "diharapkan_sen": sukses * 100_000, "konsisten": (s1 - s0) == sukses * 100_000, "sukses": sukses}
    print("KONSISTENSI:", r["konsistensi"])
    res.append(r)

    purge_synthetic(led, f"STRESS-{run_id}-")            # event sintetis (tanpa perubahan saldo) dibersihkan agar ledger tetap konsisten
    out = pathlib.Path(__file__).resolve().parents[1] / "docs" / "stress_result.json"
    json.dump({"waktu": datetime.now(timezone.utc).isoformat(), "hasil": res}, open(out, "w"), indent=1)
    print("tersimpan", out)


if __name__ == "__main__":
    main()
