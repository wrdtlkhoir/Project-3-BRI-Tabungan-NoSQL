"""Skenario demo end-to-end lewat API (dipakai untuk presentasi + screenshot).
Menyimpan seluruh langkah ke docs/demo_log.json."""
import json, pathlib, sys, time, uuid
import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8765"
A, B = "002101000000001", "002101000000004"
c = httpx.Client(base_url=BASE, timeout=60)
log = []
tag = uuid.uuid4().hex[:6]


def step(judul, method, url, **kw):
    t = time.perf_counter()
    r = c.request(method, url, **kw)
    ms = (time.perf_counter() - t) * 1000
    try:
        body = r.json()
    except Exception:
        body = r.text
    log.append({"judul": judul, "method": method, "url": url, "request": kw.get("json"), "status": r.status_code,
                "ms": round(ms, 1), "response": body})
    print(f"[{r.status_code}] {judul} ({ms:.0f} ms)")
    return body


def saldo(no):
    return step(f"Saldo {no} (Couchbase)", "GET", f"/rekening/{no}")


step("Health check kedua database", "GET", "/health")
sa0, sb0 = saldo(A), saldo(B)

# 1. setoran
k1 = f"demo-{tag}-setoran"
step("Setoran Rp500.000", "POST", "/transaksi/setoran", json={"no_rekening": A, "nominal": "500000.00", "idempotency_key": k1})
saldo(A)
step("Histori ledger (Cassandra) 3 event terbaru", "GET", f"/rekening/{A}/histori?limit=3")
# 2. retry idempoten
step("RETRY setoran dengan idempotency_key sama", "POST", "/transaksi/setoran", json={"no_rekening": A, "nominal": "500000.00", "idempotency_key": k1})
saldo(A)
# 3. penarikan
step("Penarikan Rp100.000", "POST", "/transaksi/penarikan", json={"no_rekening": A, "nominal": "100000.00", "idempotency_key": f"demo-{tag}-tarik"})
step("Penarikan melebihi saldo -> ditolak", "POST", "/transaksi/penarikan", json={"no_rekening": A, "nominal": "99999999999.00", "idempotency_key": f"demo-{tag}-tarik2"})
# 4. transfer
step("Saldo sebelum transfer: rekening B", "GET", f"/rekening/{B}")
step("Transfer A -> B Rp250.000 (1 transaksi ACID, 2 event)", "POST", "/transaksi/transfer",
     json={"rekening_sumber": A, "rekening_tujuan": B, "nominal": "250000.00", "idempotency_key": f"demo-{tag}-tf"})
saldo(A); saldo(B)
step("Histori A", "GET", f"/rekening/{A}/histori?limit=4")
step("Histori B", "GET", f"/rekening/{B}/histori?limit=2")
step("Transfer gagal (saldo kurang) -> kedua saldo tidak berubah", "POST", "/transaksi/transfer",
     json={"rekening_sumber": A, "rekening_tujuan": B, "nominal": "99999999999.00", "idempotency_key": f"demo-{tag}-tf2"})
saldo(A); saldo(B)
# 5. chaos: Cassandra down
step("SIMULASI: Cassandra mati", "POST", "/admin/chaos/ledger?down=true")
step("Setoran saat Cassandra mati (saldo tetap naik, event PENDING)", "POST", "/transaksi/setoran",
     json={"no_rekening": A, "nominal": "75000.00", "idempotency_key": f"demo-{tag}-chaos"})
saldo(A)
step("Outbox: event menunggu", "GET", "/admin/outbox")
step("Histori A tanpa event baru (ledger belum terbit)", "GET", f"/rekening/{A}/histori?limit=2")
step("SIMULASI: Cassandra pulih", "POST", "/admin/chaos/ledger?down=false")
step("Relay outbox -> Cassandra", "POST", "/admin/outbox/relay")
step("Histori A: event muncul tepat 1 kali", "GET", f"/rekening/{A}/histori?limit=3")
step("Outbox setelah relay", "GET", "/admin/outbox")
# 6. laporan
step("R-03 laporan per kanal (Cassandra)", "GET", "/laporan/R-03?id_kanal=KNL01&dari_bulan=202607&sampai_bulan=202610")
step("R-10 distribusi per produk (Couchbase)", "GET", "/laporan/R-10")
step("R-02 nasabah >1 rekening (Couchbase)", "GET", "/laporan/R-02")

out = pathlib.Path(__file__).resolve().parents[1] / "docs" / "demo_log.json"
json.dump(log, open(out, "w", encoding="utf8"), indent=1, default=str, ensure_ascii=False)
print("tersimpan", out)
