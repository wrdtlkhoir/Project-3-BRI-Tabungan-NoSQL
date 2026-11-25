"""Endpoint /api/* dan halaman /ui (UI Query Explorer + Benchmark). Ditambahkan tanpa mengubah endpoint lama."""
import pathlib
import platform
import time
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import benchmark as bm
from app import query_catalog as qc
from app import timing
from app.services.transaksi_service import BusinessError

router = APIRouter()
STATIC = pathlib.Path(__file__).resolve().parent / "static" / "ui"
_cache: dict = {}


def bind(trx, rek):
    timing.instrument()
    qc.bind(trx, rek)
    try:
        qc.ensure_test_data()
    except Exception:
        pass


def mount_ui(app):
    app.mount("/ui/static", StaticFiles(directory=STATIC), name="ui-static")


def safe(obj):
    return jsonable_encoder(obj, custom_encoder={Decimal: str})


@router.get("/ui", include_in_schema=False)
def ui_page():
    return FileResponse(STATIC / "index.html")


@router.get("/api/status", tags=["ui"])
def status(refresh: bool = False):
    trx = qc.svc()
    out = {"python": platform.python_version()}
    t = time.perf_counter()
    try:
        ok = trx.cb.ping(); out["couchbase"] = {"ok": bool(ok), "ping_ms": round((time.perf_counter() - t) * 1000, 2)}
        try:
            out["couchbase"]["versi"] = next(iter(trx.cb.cluster.query("SELECT version() AS v").rows()))["v"]
        except Exception:
            pass
    except Exception as e:
        out["couchbase"] = {"ok": False, "error": str(e)[:150]}
    t = time.perf_counter()
    try:
        ok = trx.ledger.ping(); out["cassandra"] = {"ok": bool(ok), "ping_ms": round((time.perf_counter() - t) * 1000, 2),
                                                    "versi": trx.ledger.s.execute("SELECT release_version FROM system.local").one()[0]}
    except Exception as e:
        out["cassandra"] = {"ok": False, "error": str(e)[:150]}
    if refresh or "counts" not in _cache or time.time() - _cache["counts"][0] > 60:
        ks = "`bri_tabungan`.`operasional`"
        c = {}
        try:
            for coll, notlike in [("nasabah", "nasabah::NSB%"), ("rekening", "rekening::%"), ("kartu_debit", "kartu_debit::%")]:
                n_all = next(iter(trx.cb.cluster.query(f"SELECT COUNT(*) n FROM {ks}.`{coll}` d WHERE META(d).id LIKE '{notlike}'").rows()))["n"]
                pref = {"nasabah": "nasabah::NSB99%", "rekening": "rekening::002999%", "kartu_debit": "kartu_debit::52299%"}[coll]
                n_uji = next(iter(trx.cb.cluster.query(f"SELECT COUNT(*) n FROM {ks}.`{coll}` d WHERE META(d).id LIKE '{pref}'").rows()))["n"]
                c[coll] = {"seed": n_all - n_uji, "uji": n_uji}
            c["outbox"] = trx.cb.outbox_counts()
        except Exception as e:
            c["error"] = str(e)[:150]
        try:
            tot = 0
            for kanal in [f"KNL0{i}" for i in range(1, 8)]:
                for b in [f"2025{m:02d}" for m in (11, 12)] + [f"2026{m:02d}" for m in range(1, 13)]:
                    tot += trx.ledger.s.execute("SELECT COUNT(*) FROM transaksi_by_kanal_periode WHERE id_kanal=%s AND periode=%s", [kanal, b]).one()[0]
            c["ledger_events"] = tot
            c["ledger_api"] = trx.ledger.s.execute("SELECT COUNT(*) FROM transaksi_by_id").one()[0]
        except Exception as e:
            c["ledger_error"] = str(e)[:150]
        _cache["counts"] = (time.time(), c)
    out["jumlah"] = _cache["counts"][1]
    out["simulasi_cassandra_mati"] = trx.ledger_down
    return out


@router.get("/api/queries", tags=["ui"])
def queries():
    return [{"id": q.id, "kind": q.kind, "title": q.title, "desc": q.desc, "db": q.db, "note": q.note, "statement": q.statement,
             "params": [p.__dict__ for p in q.params]} for q in qc.CAT.values()]


class RunBody(BaseModel):
    params: dict = {}
    confirm: bool = False


def _timing_header(tm: dict) -> dict:
    return {"Server-Timing": f"total;dur={tm['total_ms']}, couchbase;dur={tm['couchbase_ms']}, cassandra;dur={tm['cassandra_ms']}, app;dur={tm['app_ms']}"}


@router.post("/api/queries/{qid}/run", tags=["ui"])
def run(qid: str, body: RunBody):
    qid = qid.upper()
    if qid not in qc.CAT:
        raise HTTPException(404, f"query {qid} tidak dikenal")
    q = qc.CAT[qid]
    try:
        r = qc.run_query(qid, body.params, confirm=body.confirm)
    except BusinessError as e:
        return JSONResponse(status_code=422, content={"error": {"code": e.code, "message": e.message}})
    except Exception as e:                       # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": {"code": type(e).__name__, "message": str(e)[:300]}})
    rows = r["result"].pop("rows", None) or []
    stmt = r["result"].pop("statement_dijalankan", None)
    total = r["timing"]["rows_returned"]
    data = {"id": qid, "judul": q.title, "database": q.db, "statement": stmt or q.statement, "parameter": r["params_used"],
            "total_baris": total, "baris": rows[:100], "dipotong": len(rows) > 100, "hasil": r["result"]}
    return JSONResponse(content=safe({"data": data, "meta": {"timing": r["timing"]}}), headers=_timing_header(r["timing"]))


@router.post("/api/test-data/reset", tags=["ui"])
def reset_test():
    return {"data": qc.ensure_test_data(reset=True), "pesan": "data uji dikembalikan ke baseline"}


class BenchBody(BaseModel):
    ids: list[str] | None = None
    grup: str | None = None          # R | W | ALL
    runs: int = 5
    warmup: int = 1
    params: dict = {}
    confirm_write: bool = False


@router.post("/api/benchmark", tags=["ui"])
def bench_start(b: BenchBody):
    ids = b.ids or {"R": [i for i in qc.CAT if i.startswith("R")], "W": [i for i in qc.CAT if i.startswith("W")],
                    "ALL": list(qc.CAT)}.get((b.grup or "ALL").upper(), [])
    ids = [i.upper() for i in ids if i.upper() in qc.CAT]
    if not ids:
        raise HTTPException(422, "tidak ada query dipilih")
    if any(i.startswith("W") for i in ids) and not b.confirm_write:
        return JSONResponse(status_code=422, content={"error": {"code": "KONFIRMASI_DIPERLUKAN", "message": "benchmark query tulis mengubah data uji (dipulihkan setiap run); kirim confirm_write=true"}})
    if not (1 <= b.runs <= 50):
        raise HTTPException(422, "runs harus 1..50")
    return {"job_id": bm.start(ids, b.runs, max(0, b.warmup), b.params, qc.svc())}


@router.get("/api/benchmark/jobs/{job_id}", tags=["ui"])
def bench_job(job_id: str):
    j = bm.JOBS.get(job_id)
    if not j:
        raise HTTPException(404, "job tidak ditemukan")
    return safe({k: v for k, v in j.items() if k != "hasil" or j.get("status") == "selesai"})


@router.get("/api/benchmark/results", tags=["ui"])
def bench_results():
    return bm.list_results()


@router.get("/api/benchmark/results/{file}", tags=["ui"])
def bench_result(file: str, format: str = "json"):
    try:
        d = bm.load(file)
    except FileNotFoundError:
        raise HTTPException(404, "hasil tidak ditemukan")
    if format == "csv":
        return PlainTextResponse(bm.to_csv(d), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={file}.csv"})
    if format == "md":
        return PlainTextResponse(bm.to_md(d), media_type="text/markdown")
    return safe(d)
