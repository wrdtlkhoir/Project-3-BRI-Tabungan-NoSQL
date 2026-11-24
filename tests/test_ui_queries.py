"""Integrasi: 20 query dari katalog UI (butuh docker compose + seed). Hasil angka dipakai sebagai sanity check, bukan hard assertion."""
import warnings

import pytest
from fastapi.testclient import TestClient

from app import query_catalog as qc
from app.main import app, state

TIMING_KEYS = {"total_ms", "couchbase_ms", "cassandra_ms", "app_ms", "rows_returned"}
SANITY = {"R-05": 1000, "R-08": 1274}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        qc.ensure_test_data(reset=True)
        yield c
        state["trx"].ledger_down = False


@pytest.mark.parametrize("qid", [f"R-{i:02d}" for i in range(1, 11)])
def test_query_read_berjalan_dan_punya_timing(client, qid):
    r = client.post(f"/api/queries/{qid}/run", json={"params": {}})
    assert r.status_code == 200, r.text
    d = r.json()
    tm = d["meta"]["timing"]
    assert TIMING_KEYS <= set(tm) and "Server-Timing" in r.headers
    assert tm["total_ms"] >= tm["couchbase_ms"] + tm["cassandra_ms"] - 1
    assert d["data"]["total_baris"] >= len(d["data"]["baris"]) and len(d["data"]["baris"]) <= 100
    if qid in SANITY and d["data"]["total_baris"] != SANITY[qid]:
        warnings.warn(f"{qid}: {d['data']['total_baris']} baris, acuan seed {SANITY[qid]} (data mungkin sudah berubah)")


def test_read_couchbase_mengisi_server_exec(client):
    tm = client.post("/api/queries/R-10/run", json={"params": {}}).json()["meta"]["timing"]
    assert tm.get("server_exec_ms") is not None and tm["server_exec_ms"] <= tm["couchbase_ms"] + 1


def test_write_butuh_konfirmasi(client):
    r = client.post("/api/queries/W-01/run", json={"params": {}, "confirm": False})
    assert r.status_code == 422 and r.json()["error"]["code"] == "KONFIRMASI_DIPERLUKAN"


def _snapshot(client):
    return {n: (lambda d: (d["saldo_efektif_sen"], d["tx_count"], d["status_rekening"], len(d["pemegang_rekening"])))(
        client.get(f"/rekening/{no}").json()) for n, no in qc.TEST_ACC.items()}


@pytest.mark.parametrize("qid", [f"W-{i:02d}" for i in range(1, 11)])
def test_query_write_jalan_dan_baseline_pulih(client, qid):
    before = _snapshot(client)
    r = qc.run_query(qid, {}, confirm=True, undo=True)
    assert r["restored"] is True and TIMING_KEYS <= set(r["timing"])
    assert _snapshot(client) == before


def test_w07_dua_database(client):
    r = qc.run_query("W-07", {}, confirm=True, undo=True)
    tm = r["timing"]
    assert tm["couchbase_ms"] > 0 and tm["cassandra_ms"] > 0 and tm["ledger_visible_lag_ms"] == 0


def test_benchmark_kecil_statistik(client):
    from app import benchmark as bm
    jid = bm.start(["R-07", "W-08"], 3, 1, {}, qc.svc())
    import time
    for _ in range(60):
        if bm.JOBS[jid]["status"] != "berjalan":
            break
        time.sleep(1)
    j = bm.JOBS[jid]
    assert j["status"] == "selesai"
    for row in j["hasil"]:
        assert len(row["runs_ms"]) == 3 and row["min"] <= row["median"] <= row["max"]
    assert next(r for r in j["hasil"] if r["id"] == "W-08")["pemulihan_baseline"] is True
