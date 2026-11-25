"""B. Integration test: Couchbase <-> Cassandra lewat backend (butuh docker compose + seed)."""
import uuid
from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app, state


def _pick_accounts(n):
    """Pilih rekening AKTIF dengan saldo besar dari dump (sumber yang sama dengan seed)."""
    with psycopg.connect(get_settings().pg_dsn) as c, c.cursor() as cur:
        cur.execute("""select no_rekening from rekening_tabungan where status_rekening='AKTIF' and saldo_efektif > 50000000
                       order by no_rekening desc limit %s""", [n])
        return [r[0] for r in cur.fetchall()]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c
        state["trx"].ledger_down = False


@pytest.fixture(scope="module")
def accs():
    return _pick_accounts(6)


def key(): return "it-" + uuid.uuid4().hex[:16]


def saldo(client, no): return client.get(f"/rekening/{no}").json()["saldo_efektif_sen"]


def n_event(no, jenis=None):
    rows = state["rek"].ledger.s.execute(
        "SELECT jenis_transaksi FROM transaksi_by_rekening WHERE no_rekening=%s", [no]).all()
    return len([r for r in rows if jenis is None or r.jenis_transaksi == jenis])


def test_setoran_ubah_saldo_dan_catat_event(client, accs):
    no = accs[0]; s0 = saldo(client, no); e0 = n_event(no, "SETORAN")
    r = client.post("/transaksi/setoran", json={"no_rekening": no, "nominal": "500000.00", "idempotency_key": key()})
    assert r.status_code == 200 and r.json()["ledger_status"] == "PUBLISHED"
    assert saldo(client, no) == s0 + 50_000_000
    assert n_event(no, "SETORAN") == e0 + 1
    h = client.get(f"/rekening/{no}/histori?limit=1").json()[0]
    assert h["jenis_event"] == "SETORAN" and Decimal(h["nominal"]) == Decimal("500000.00")


def test_idempotensi_retry_tidak_ganda(client, accs):
    no = accs[1]; k = key(); s0 = saldo(client, no); e0 = n_event(no, "SETORAN")
    a = client.post("/transaksi/setoran", json={"no_rekening": no, "nominal": "100000", "idempotency_key": k}).json()
    b = client.post("/transaksi/setoran", json={"no_rekening": no, "nominal": "100000", "idempotency_key": k}).json()
    assert a["event_id"] == b["event_id"] and b["duplicate"] is True
    assert saldo(client, no) == s0 + 10_000_000          # hanya sekali
    assert n_event(no, "SETORAN") == e0 + 1


def test_penarikan_saldo_tidak_cukup_tidak_menulis_apa_apa(client, accs):
    no = accs[2]; s0 = saldo(client, no); e0 = n_event(no)
    r = client.post("/transaksi/penarikan", json={"no_rekening": no, "nominal": "99999999999.00", "idempotency_key": key()})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "SALDO_TIDAK_CUKUP"
    assert saldo(client, no) == s0 and n_event(no) == e0


def test_transfer_atomik_dua_event(client, accs):
    a, b = accs[3], accs[4]; sa, sb = saldo(client, a), saldo(client, b)
    r = client.post("/transaksi/transfer", json={"rekening_sumber": a, "rekening_tujuan": b, "nominal": "250000.00",
                                                  "idempotency_key": key()})
    assert r.status_code == 200
    assert saldo(client, a) == sa - 25_000_000 and saldo(client, b) == sb + 25_000_000
    assert n_event(a, "TRANSFER_KELUAR") >= 1 and n_event(b, "TRANSFER_MASUK") >= 1


def test_transfer_gagal_tidak_mengubah_kedua_saldo(client, accs):
    a, b = accs[3], accs[4]; sa, sb = saldo(client, a), saldo(client, b)
    r = client.post("/transaksi/transfer", json={"rekening_sumber": a, "rekening_tujuan": b, "nominal": "99999999999.00",
                                                  "idempotency_key": key()})
    assert r.status_code == 422
    assert saldo(client, a) == sa and saldo(client, b) == sb          # tidak ada debit tanpa kredit


def test_cassandra_down_event_aman_di_outbox_lalu_pulih(client, accs):
    no = accs[5]; s0 = saldo(client, no); e0 = n_event(no, "SETORAN")
    client.post("/admin/chaos/ledger?down=true")
    r = client.post("/transaksi/setoran", json={"no_rekening": no, "nominal": "75000.00", "idempotency_key": key()}).json()
    assert r["ledger_status"] == "PENDING"                            # saldo berubah, event menunggu
    assert saldo(client, no) == s0 + 7_500_000 and n_event(no, "SETORAN") == e0
    client.post("/admin/chaos/ledger?down=false")
    res = client.post("/admin/outbox/relay").json()
    assert res["berhasil"] >= 1
    assert n_event(no, "SETORAN") == e0 + 1                           # tepat satu event
    client.post("/admin/outbox/relay")                                # relay ulang tidak menggandakan
    assert n_event(no, "SETORAN") == e0 + 1


def test_histori_terurut_terbaru_dulu(client, accs):
    h = client.get(f"/rekening/{accs[0]}/histori?limit=10").json()
    ts = [x["waktu_event"] for x in h]
    assert ts == sorted(ts, reverse=True) and len(h) == 10


def test_partisi_per_rekening_terbatas(client, accs):
    assert state["rek"].ledger.count_rekening(accs[0]) < 5000
