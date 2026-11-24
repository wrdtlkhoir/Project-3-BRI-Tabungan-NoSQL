"""Repository Couchbase (main database): data operasional + outbox.

Uang disimpan sebagai INTEGER dalam satuan sen (field *_sen) agar tidak ada sisa desimal
floating point (catatan reviewer). Field desimal lama (saldo_efektif, saldo_tersedia)
tetap diperbarui sebagai tampilan agar kompatibel dengan query Project 2 / laporan."""
from datetime import datetime, timezone
from decimal import Decimal

from couchbase.exceptions import DocumentExistsException, DocumentNotFoundException
from couchbase.n1ql import QueryScanConsistency
from couchbase.options import QueryOptions, ReplaceOptions

from app.database.couchbase_db import get_cluster, get_collection, get_scope
from app.config import get_settings


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sen_to_rupiah(sen: int) -> float:
    return float((Decimal(sen) / Decimal(100)).quantize(Decimal("0.01")))


class CouchbaseRepository:
    def __init__(self):
        self.rekening = get_collection("rekening")
        self.nasabah = get_collection("nasabah")
        self.kanal = get_collection("kanal")
        self.outbox = get_collection("outbox")
        self.cluster = get_cluster()
        self.keyspace = f"`{get_settings().couchbase_bucket}`.`{get_settings().couchbase_scope}`"

    # ------------------------------------------------------------- KV
    def get_rekening(self, no_rekening: str) -> dict | None:
        try:
            return self.rekening.get(f"rekening::{no_rekening}").content_as[dict]
        except DocumentNotFoundException:
            return None

    def get_nasabah(self, id_nasabah: str) -> dict | None:
        try:
            return self.nasabah.get(f"nasabah::{id_nasabah}").content_as[dict]
        except DocumentNotFoundException:
            return None

    def get_kanal_nama(self, id_kanal: str) -> str | None:
        try:
            return self.kanal.get(f"kanal::{id_kanal}").content_as[dict]["nama_kanal"]
        except DocumentNotFoundException:
            return None

    def get_outbox(self, event_id: str) -> dict | None:
        try:
            return self.outbox.get(f"outbox::{event_id}").content_as[dict]
        except DocumentNotFoundException:
            return None

    # ------------------------------------------------------------- Outbox
    def mark_outbox(self, event_id: str, status: str, error: str | None = None) -> None:
        key = f"outbox::{event_id}"
        for _ in range(5):                      # retry CAS
            r = self.outbox.get(key)
            doc = r.content_as[dict]
            doc["status"] = status
            doc["attempts"] = doc.get("attempts", 0) + (0 if status == "PUBLISHED" else 1)
            doc["last_error"] = error
            doc["updated_at"] = now_iso()
            if status == "PUBLISHED":
                doc["published_at"] = now_iso()
            try:
                self.outbox.replace(key, doc, ReplaceOptions(cas=r.cas))
                return
            except Exception:
                continue

    def pending_outbox(self, limit: int = 100) -> list[dict]:
        q = (f"SELECT o.* FROM {self.keyspace}.`outbox` o WHERE o.status = 'PENDING' "
             f"ORDER BY o.created_at LIMIT {int(limit)}")
        return list(self.cluster.query(q, QueryOptions(scan_consistency=QueryScanConsistency.REQUEST_PLUS)).rows())

    def outbox_counts(self) -> dict:
        q = f"SELECT o.status AS status, COUNT(*) AS n FROM {self.keyspace}.`outbox` o GROUP BY o.status"
        return {r["status"]: r["n"] for r in self.cluster.query(
            q, QueryOptions(scan_consistency=QueryScanConsistency.REQUEST_PLUS)).rows()}

    # ------------------------------------------------------------- Query Read (Project 2) -> N1QL
    def query(self, statement: str, **named):
        res = self.cluster.query(statement, QueryOptions(named_parameters=named,
                                 scan_consistency=QueryScanConsistency.NOT_BOUNDED))
        return list(res.rows())

    def ping(self) -> bool:
        from couchbase.options import PingOptions
        from couchbase.diagnostics import ServiceType
        r = self.cluster.ping(PingOptions(service_types=[ServiceType.KeyValue, ServiceType.Query]))
        return all(e.state.name == "OK" for eps in r.endpoints.values() for e in eps)
