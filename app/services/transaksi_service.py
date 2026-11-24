"""Business logic transaksi: Couchbase (saldo, ACID multi-dokumen) + Cassandra (event ledger).

Alur (Transactional Outbox)
  1. Validasi + ubah saldo + tulis dokumen outbox 'PENDING'  -> SATU transaksi Couchbase (atomik)
  2. Publish event ke Cassandra (idempoten)
  3. Tandai outbox 'PUBLISHED'
Jika langkah 2 gagal (Cassandra down), saldo tetap benar dan event tidak hilang: relay mengulang
dari outbox sampai berhasil. Event tidak ganda karena idempotency key + primary key deterministik."""
import hashlib
import threading
from datetime import datetime, timezone
from decimal import Decimal

from couchbase.exceptions import TransactionFailed

from app.config import get_settings
from app.repositories.cassandra_repository import CassandraLedgerRepository, sen_to_decimal
from app.repositories.couchbase_repository import CouchbaseRepository, now_iso, sen_to_rupiah


class BusinessError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def to_sen(nominal: Decimal) -> int:
    return int((nominal * 100).to_integral_value())


def event_base(idempotency_key: str) -> str:
    return "EVT-" + hashlib.sha1(idempotency_key.encode()).hexdigest()[:20].upper()


class TransaksiService:
    def __init__(self, cb: CouchbaseRepository | None = None, ledger: CassandraLedgerRepository | None = None):
        self.cb = cb or CouchbaseRepository()
        self.ledger = ledger or CassandraLedgerRepository()
        self.ledger_down = False          # saklar simulasi kegagalan Cassandra (demo / test)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ util
    def _event(self, event_id, jenis, arah, no_rekening, nominal_sen, saldo_setelah_sen, kanal, counterparty=None,
               idem=None, correlation=None):
        return {"event_id": event_id, "no_rekening": no_rekening, "jenis_event": jenis, "arah": arah,
                "nominal_sen": nominal_sen, "saldo_setelah_sen": saldo_setelah_sen, "mata_uang": "IDR",
                "id_kanal": kanal, "nama_kanal": self.cb.get_kanal_nama(kanal), "status_event": "BERHASIL",
                "counterparty": counterparty, "idempotency_key": idem, "correlation_id": correlation,
                "waktu_event": now_iso(), "sumber": "API"}

    @staticmethod
    def _apply(doc: dict, delta_sen: int, jenis: str, ts: str, check_funds: bool):
        if doc.get("status_rekening") != "AKTIF":
            raise BusinessError("REKENING_TIDAK_AKTIF", f"rekening {doc['no_rekening']} berstatus {doc.get('status_rekening')}")
        ef = doc["saldo_efektif_sen"]; tv = doc["saldo_tersedia_sen"]
        if check_funds and (tv + delta_sen < 0 or ef + delta_sen < 0):
            raise BusinessError("SALDO_TIDAK_CUKUP", f"saldo tersedia {sen_to_rupiah(tv):,.2f} tidak cukup")
        doc["saldo_efektif_sen"] = ef + delta_sen
        doc["saldo_tersedia_sen"] = tv + delta_sen
        doc["saldo_efektif"] = sen_to_rupiah(doc["saldo_efektif_sen"])      # tampilan kompatibel Project 2
        doc["saldo_tersedia"] = sen_to_rupiah(doc["saldo_tersedia_sen"])
        doc["last_transaction_at"] = ts                                     # hanya transaksi BERHASIL (R-04)
        doc["tx_count"] = doc.get("tx_count", 0) + 1
        return doc

    def _run_txn(self, fn):
        """Jalankan fn(ctx) sebagai transaksi ACID Couchbase."""
        try:
            self.cb.cluster.transactions.run(fn)
        except TransactionFailed as e:
            raise RuntimeError(f"transaksi Couchbase gagal: {e}") from e

    # ------------------------------------------------------------------ operasi
    def _existing(self, event_id: str):
        ob = self.cb.get_outbox(event_id)
        if ob:
            return self._response(ob, duplicate=True)
        return None

    def _response(self, ob: dict, duplicate=False) -> dict:
        ev = ob["event"]
        return {"event_id": ob["event_id"], "jenis": ob["jenis"], "status": ev["status_event"], "duplicate": duplicate,
                "saldo_setelah": sen_to_decimal(ev["saldo_setelah_sen"]), "ledger_status": ob["status"],
                "detail": {"no_rekening": ev["no_rekening"], "nominal": str(sen_to_decimal(ev["nominal_sen"])),
                           "counterparty": ev.get("counterparty"), "waktu_event": ev["waktu_event"]}}

    def _single(self, jenis, arah, no_rekening, nominal, idem, kanal, check_funds) -> dict:
        event_id = event_base(idem)
        if (dup := self._existing(event_id)):
            return dup
        sen = to_sen(nominal)
        delta = sen if arah == "KREDIT" else -sen
        ts = now_iso()
        out = {}

        def logic(ctx):
            key = f"rekening::{no_rekening}"
            r = ctx.get(self.cb.rekening, key)
            doc = r.content_as[dict]
            try:
                doc = self._apply(doc, delta, jenis, ts, check_funds)
            except BusinessError as e:
                out["err"] = e
                return                                              # tidak ada perubahan -> commit kosong
            ctx.replace(r, doc)
            ev = self._event(event_id, jenis, arah, no_rekening, sen, doc["saldo_efektif_sen"], kanal, idem=idem)
            ev["waktu_event"] = ts
            ctx.insert(self.cb.outbox, f"outbox::{event_id}", {
                "type": "outbox", "event_id": event_id, "jenis": jenis, "status": "PENDING", "attempts": 0,
                "created_at": ts, "event": ev})
            out["event_id"] = event_id

        if self.cb.get_rekening(no_rekening) is None:
            raise BusinessError("REKENING_TIDAK_DITEMUKAN", f"rekening {no_rekening} tidak ada")
        try:
            self._run_txn(logic)
        except RuntimeError:
            if (dup := self._existing(event_id)):                   # balapan dua request identik
                return dup
            raise
        if "err" in out:
            raise out["err"]
        self.publish(event_id)
        return self._response(self.cb.get_outbox(event_id))

    def setoran(self, no_rekening, nominal, idempotency_key, id_kanal="KNL01"):
        return self._single("SETORAN", "KREDIT", no_rekening, nominal, idempotency_key, id_kanal, False)

    def penarikan(self, no_rekening, nominal, idempotency_key, id_kanal="KNL01"):
        return self._single("PENARIKAN", "DEBIT", no_rekening, nominal, idempotency_key, id_kanal, True)

    def transfer(self, sumber, tujuan, nominal, idempotency_key, id_kanal="KNL01"):
        """Debit + kredit dalam SATU transaksi ACID Couchbase: kalau salah satu gagal, keduanya batal."""
        if sumber == tujuan:
            raise BusinessError("REKENING_SAMA", "rekening sumber dan tujuan tidak boleh sama")
        base = event_base(idempotency_key)
        ev_d, ev_k = base + "-D", base + "-K"
        if (dup := self._existing(ev_d)):
            return dup
        for n in (sumber, tujuan):
            if self.cb.get_rekening(n) is None:
                raise BusinessError("REKENING_TIDAK_DITEMUKAN", f"rekening {n} tidak ada")
        sen = to_sen(nominal)
        ts = now_iso()
        out = {}

        def logic(ctx):
            rs = ctx.get(self.cb.rekening, f"rekening::{sumber}")
            rt = ctx.get(self.cb.rekening, f"rekening::{tujuan}")
            ds, dt = rs.content_as[dict], rt.content_as[dict]
            try:
                ds = self._apply(ds, -sen, "TRANSFER_KELUAR", ts, True)
                dt = self._apply(dt, +sen, "TRANSFER_MASUK", ts, False)
            except BusinessError as e:
                out["err"] = e
                return
            ctx.replace(rs, ds)
            ctx.replace(rt, dt)
            e1 = self._event(ev_d, "TRANSFER_KELUAR", "DEBIT", sumber, sen, ds["saldo_efektif_sen"], id_kanal,
                             counterparty=tujuan, idem=idempotency_key, correlation=base)
            e2 = self._event(ev_k, "TRANSFER_MASUK", "KREDIT", tujuan, sen, dt["saldo_efektif_sen"], id_kanal,
                             counterparty=sumber, idem=idempotency_key, correlation=base)
            for e in (e1, e2):
                e["waktu_event"] = ts
                ctx.insert(self.cb.outbox, f"outbox::{e['event_id']}", {
                    "type": "outbox", "event_id": e["event_id"], "jenis": e["jenis_event"], "status": "PENDING",
                    "attempts": 0, "created_at": ts, "event": e})

        try:
            self._run_txn(logic)
        except RuntimeError:
            if (dup := self._existing(ev_d)):
                return dup
            raise
        if "err" in out:
            raise out["err"]
        self.publish(ev_d)
        self.publish(ev_k)
        res = self._response(self.cb.get_outbox(ev_d))
        k = self.cb.get_outbox(ev_k)
        res["detail"]["event_id_kredit"] = ev_k
        res["detail"]["ledger_status_kredit"] = k["status"]
        return res


    # ------------------------------------------------------------------ perubahan status rekening (W-05, W-10)
    def ubah_status(self, no_rekening: str, status_baru: str, idempotency_key: str):
        """Blokir (TERBLOKIR) atau tutup (DITUTUP) rekening. Status berubah di Couchbase dan event audit
        masuk ledger lewat outbox, dalam satu transaksi ACID."""
        assert status_baru in ("TERBLOKIR", "DITUTUP")
        event_id = event_base(idempotency_key)
        if (dup := self._existing(event_id)):
            return dup
        if self.cb.get_rekening(no_rekening) is None:
            raise BusinessError("REKENING_TIDAK_DITEMUKAN", f"rekening {no_rekening} tidak ada")
        ts = now_iso(); out = {}
        jenis = "STATUS_BLOKIR" if status_baru == "TERBLOKIR" else "STATUS_TUTUP"

        def logic(ctx):
            r = ctx.get(self.cb.rekening, f"rekening::{no_rekening}")
            doc = r.content_as[dict]
            if doc.get("status_rekening") != "AKTIF":                       # sama seperti IF status_rekening='AKTIF' (Project 2)
                out["err"] = BusinessError("REKENING_TIDAK_AKTIF", f"status saat ini {doc.get('status_rekening')}")
                return
            doc["status_rekening"] = status_baru
            if status_baru == "DITUTUP":
                if doc["saldo_efektif_sen"] != 0:
                    out["err"] = BusinessError("SALDO_MASIH_ADA", "rekening dengan saldo tidak boleh ditutup; tarik/transfer dulu")
                    return
                doc["tanggal_tutup"] = ts[:10]
            ctx.replace(r, doc)
            ev = self._event(event_id, jenis, "NA", no_rekening, 0, doc["saldo_efektif_sen"], None, idem=idempotency_key)
            ev["waktu_event"] = ts
            ev["status_event"] = "BERHASIL"
            ctx.insert(self.cb.outbox, f"outbox::{event_id}", {"type": "outbox", "event_id": event_id, "jenis": jenis,
                       "status": "PENDING", "attempts": 0, "created_at": ts, "event": ev})

        try:
            self._run_txn(logic)
        except RuntimeError:
            if (dup := self._existing(event_id)):
                return dup
            raise
        if "err" in out:
            raise out["err"]
        self.publish(event_id)
        return self._response(self.cb.get_outbox(event_id))

    # ------------------------------------------------------------------ outbox -> Cassandra
    def publish(self, event_id: str) -> str:
        """Publish satu event outbox ke Cassandra. Mengembalikan status outbox setelahnya."""
        ob = self.cb.get_outbox(event_id)
        if ob is None:
            raise KeyError(event_id)
        if ob["status"] == "PUBLISHED":
            return "PUBLISHED"
        try:
            if self.ledger_down:
                raise ConnectionError("Cassandra tidak dapat dijangkau (simulasi)")
            ev = dict(ob["event"])
            ev["waktu_event"] = datetime.strptime(ev["waktu_event"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            self.ledger.append_event(ev)
            self.cb.mark_outbox(event_id, "PUBLISHED")
            return "PUBLISHED"
        except Exception as e:                                       # noqa: BLE001 — outbox menjaga event tetap aman
            attempts = ob.get("attempts", 0) + 1
            status = "FAILED" if attempts >= get_settings().outbox_max_attempts else "PENDING"
            self.cb.mark_outbox(event_id, status, error=str(e)[:200])
            return status

    def relay_pending(self, limit: int = 200) -> dict:
        pend = self.cb.pending_outbox(limit)
        ok = 0
        for ob in pend:
            if self.publish(ob["event_id"]) == "PUBLISHED":
                ok += 1
        return {"diproses": len(pend), "berhasil": ok, "sisa": len(pend) - ok}
