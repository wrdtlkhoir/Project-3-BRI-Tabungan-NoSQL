"""FastAPI backend: penghubung Couchbase (main) dan Cassandra (event ledger).

Jalankan:  uvicorn app.main:app --port 8000      (dokumentasi interaktif: http://localhost:8000/docs)"""
import asyncio
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import FastAPI, HTTPException, Query

from app.config import get_settings
from app.schemas.transaksi import PenarikanRequest, SetoranRequest, TransaksiResponse, TransferRequest
from app.services.rekening_service import RekeningService, _months
from app.services.transaksi_service import BusinessError, TransaksiService

state: dict = {}


def _relay_loop(stop: threading.Event):
    interval = get_settings().outbox_relay_interval
    while not stop.wait(interval):
        try:
            svc = state.get("trx")
            if svc is not None and not svc.ledger_down:
                svc.relay_pending(100)
        except Exception:      # relay tidak boleh mati
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # koneksi SDK bersifat blocking -> jalankan di thread agar event loop uvicorn tidak tertahan
    state["trx"] = await asyncio.to_thread(TransaksiService)
    state["rek"] = RekeningService(state["trx"].cb, state["trx"].ledger)
    stop = threading.Event()
    t = threading.Thread(target=_relay_loop, args=(stop,), daemon=True)
    t.start()
    yield
    stop.set()


app = FastAPI(title="BRI Tabungan NoSQL — Couchbase + Cassandra Event Ledger", version="1.0", lifespan=lifespan)


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except BusinessError as e:
        raise HTTPException(status_code=422, detail={"code": e.code, "message": e.message})


@app.get("/health", tags=["sistem"])
def health():
    trx: TransaksiService = state["trx"]
    return {"couchbase": trx.cb.ping(), "cassandra": trx.ledger.ping(), "ledger_down_simulasi": trx.ledger_down,
            "outbox": trx.cb.outbox_counts()}


@app.get("/rekening/{no_rekening}", tags=["rekening (Couchbase)"])
def get_rekening(no_rekening: str):
    r = state["rek"].get_rekening(no_rekening)
    if r is None:
        raise HTTPException(404, "rekening tidak ditemukan")
    return r


@app.get("/rekening/{no_rekening}/histori", tags=["ledger (Cassandra) — R-01"])
def histori(no_rekening: str, dari: datetime | None = None, sampai: datetime | None = None,
            limit: int = Query(20, ge=1, le=500)):
    if dari and dari.tzinfo is None:
        dari = dari.replace(tzinfo=timezone.utc)
    if sampai and sampai.tzinfo is None:
        sampai = sampai.replace(tzinfo=timezone.utc)
    return state["rek"].histori(no_rekening, dari, sampai, limit)


@app.post("/transaksi/setoran", response_model=TransaksiResponse, tags=["transaksi"])
def setoran(req: SetoranRequest):
    return _guard(state["trx"].setoran, req.no_rekening, req.nominal, req.idempotency_key, req.id_kanal)


@app.post("/transaksi/penarikan", response_model=TransaksiResponse, tags=["transaksi"])
def penarikan(req: PenarikanRequest):
    return _guard(state["trx"].penarikan, req.no_rekening, req.nominal, req.idempotency_key, req.id_kanal)


@app.post("/transaksi/transfer", response_model=TransaksiResponse, tags=["transaksi"])
def transfer(req: TransferRequest):
    return _guard(state["trx"].transfer, req.rekening_sumber, req.rekening_tujuan, req.nominal,
                  req.idempotency_key, req.id_kanal)


@app.get("/laporan/{kode}", tags=["laporan (query Project 2)"])
def laporan(kode: str, no_rekening: str | None = None, id_kanal: str = "KNL01",
            dari_bulan: str = "202601", sampai_bulan: str = "202611"):
    """R-02, R-04..R-10 -> Couchbase (N1QL). R-03 -> Cassandra. R-01 lihat /rekening/{no}/histori."""
    kode = kode.upper()
    if kode == "R-03":
        y1, m1 = int(dari_bulan[:4]), int(dari_bulan[4:]); y2, m2 = int(sampai_bulan[:4]), int(sampai_bulan[4:])
        bl = _months(datetime(y1, m1, 1, tzinfo=timezone.utc), datetime(y2, m2, 1, tzinfo=timezone.utc))
        return state["rek"].laporan("R-03", id_kanal=id_kanal, bulan_list=bl)
    from app.repositories.read_queries import COUCHBASE_READS
    if kode not in COUCHBASE_READS:
        raise HTTPException(404, f"{kode} tidak dikenal")
    if kode == "R-07" and not no_rekening:
        raise HTTPException(422, "R-07 membutuhkan no_rekening")
    return state["rek"].laporan(kode, no_rekening=no_rekening)


@app.post("/rekening/{no_rekening}/blokir", response_model=TransaksiResponse, tags=["transaksi"])
def blokir(no_rekening: str, idempotency_key: str):
    """W-05 Memblokir rekening (IF status AKTIF) + event audit di ledger."""
    return _guard(state["trx"].ubah_status, no_rekening, "TERBLOKIR", idempotency_key)


@app.post("/rekening/{no_rekening}/tutup", response_model=TransaksiResponse, tags=["transaksi"])
def tutup(no_rekening: str, idempotency_key: str):
    """W-10 Menutup rekening (hanya jika AKTIF dan saldo 0) + event audit di ledger."""
    return _guard(state["trx"].ubah_status, no_rekening, "DITUTUP", idempotency_key)


# ---------------------------------------------------------------- outbox & simulasi kegagalan
@app.get("/admin/outbox", tags=["admin"])
def outbox_status():
    trx: TransaksiService = state["trx"]
    return {"ringkasan": trx.cb.outbox_counts(), "pending": [
        {"event_id": o["event_id"], "jenis": o["jenis"], "attempts": o.get("attempts"), "last_error": o.get("last_error")}
        for o in trx.cb.pending_outbox(20)]}


@app.post("/admin/outbox/relay", tags=["admin"])
def outbox_relay():
    return state["trx"].relay_pending(500)


@app.post("/admin/chaos/ledger", tags=["admin"])
def chaos(down: bool):
    """Simulasi Cassandra mati: saldo di Couchbase tetap berubah, event menunggu di outbox (PENDING)."""
    state["trx"].ledger_down = down
    return {"ledger_down_simulasi": down}
