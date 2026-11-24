"""Pengukuran execution time per query.

Prinsip: kode lama TIDAK diubah. `instrument()` membungkus (monkeypatch) metode repository/service yang
menyentuh database agar waktunya otomatis terakumulasi ke objek Timing yang sedang aktif (contextvar).
  couchbase_ms = waktu di sekitar pemanggilan driver Couchbase (KV, transaksi, N1QL; hasil dikonsumsi penuh)
  cassandra_ms = waktu di sekitar pemanggilan driver Cassandra
  server_exec_ms = executionTime bawaan Couchbase (metadata.metrics) -> waktu eksekusi murni di server DB
  app_ms = total - couchbase - cassandra (validasi, mapping, serialisasi)"""
import contextlib
import contextvars
import functools
import statistics
import time

_current: contextvars.ContextVar = contextvars.ContextVar("timing", default=None)
_depth: contextvars.ContextVar = contextvars.ContextVar("timing_depth", default=0)


class Timing:
    def __init__(self):
        self.t0 = time.perf_counter_ns()
        self.t1 = None
        self.cb_ns = 0
        self.cass_ns = 0
        self.server_exec_ms = None
        self.rows = 0
        self.extra: dict = {}

    def stop(self):
        self.t1 = self.t1 or time.perf_counter_ns()
        return self

    def as_dict(self) -> dict:
        end = self.t1 or time.perf_counter_ns()
        total = (end - self.t0) / 1e6
        cb, cass = self.cb_ns / 1e6, self.cass_ns / 1e6
        d = {"total_ms": round(total, 3), "couchbase_ms": round(cb, 3), "cassandra_ms": round(cass, 3),
             "app_ms": round(max(total - cb - cass, 0.0), 3), "rows_returned": self.rows}
        if self.server_exec_ms is not None:
            d["server_exec_ms"] = round(self.server_exec_ms, 3)
        d.update(self.extra)
        return d


@contextlib.contextmanager
def measure():
    t = Timing()
    token = _current.set(t)
    try:
        yield t
    finally:
        t.stop()
        _current.reset(token)


@contextlib.contextmanager
def timed(kind: str):
    """kind: 'cb' | 'cass'. Aman dipanggil bersarang (hanya lapisan terluar yang dihitung)."""
    t = _current.get()
    d = _depth.get()
    if t is None or d > 0:
        yield
        return
    token = _depth.set(d + 1)
    s = time.perf_counter_ns()
    try:
        yield
    finally:
        e = time.perf_counter_ns() - s
        if kind == "cb":
            t.cb_ns += e
        else:
            t.cass_ns += e
        _depth.reset(token)


def set_server_exec(ms: float):
    t = _current.get()
    if t is not None:
        t.server_exec_ms = (t.server_exec_ms or 0.0) + ms


def set_rows(n: int):
    t = _current.get()
    if t is not None:
        t.rows = n


def _wrap(cls, name, kind):
    orig = getattr(cls, name)
    if getattr(orig, "_timed", False):
        return

    @functools.wraps(orig)
    def inner(*a, **kw):
        with timed(kind):
            return orig(*a, **kw)
    inner._timed = True
    setattr(cls, name, inner)


def instrument():
    """Dipanggil sekali saat startup UI. Tidak mengubah perilaku, hanya menambah pencatatan waktu."""
    from app.repositories.cassandra_repository import CassandraLedgerRepository as CA
    from app.repositories.couchbase_repository import CouchbaseRepository as CB
    from app.services.transaksi_service import TransaksiService as TS
    for n in ("get_rekening", "get_nasabah", "get_outbox", "mark_outbox", "query"):
        _wrap(CB, n, "cb")
    for n in ("append_event", "history", "report_kanal", "months_with_data", "count_partition", "get_event"):
        _wrap(CA, n, "cass")
    _wrap(TS, "_run_txn", "cb")      # transaksi ACID Couchbase (validasi + update saldo + outbox)


def stats(values: list[float]) -> dict:
    """min/avg/median/p95/max dari daftar run (ms)."""
    if not values:
        return {}
    v = sorted(values)
    p95 = v[min(len(v) - 1, max(0, int(round(0.95 * (len(v) - 1)))))]
    return {"min": round(v[0], 3), "avg": round(statistics.mean(v), 3), "median": round(statistics.median(v), 3),
            "p95": round(p95, 3), "max": round(v[-1], 3)}
