from datetime import datetime, timezone, timedelta
from decimal import Decimal

from app.repositories.cassandra_repository import CassandraLedgerRepository
from app.repositories.couchbase_repository import CouchbaseRepository
from app.repositories import read_queries as rq


def _months(dari: datetime, sampai: datetime) -> list[str]:
    out, cur = [], datetime(dari.year, dari.month, 1, tzinfo=timezone.utc)
    while cur <= sampai:
        out.append(cur.strftime("%Y%m"))
        cur = datetime(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1, tzinfo=timezone.utc)
    return out


class RekeningService:
    def __init__(self, cb: CouchbaseRepository | None = None, ledger: CassandraLedgerRepository | None = None):
        self.cb = cb or CouchbaseRepository()
        self.ledger = ledger or CassandraLedgerRepository()

    def get_rekening(self, no_rekening: str):
        doc = self.cb.get_rekening(no_rekening)
        if doc is None:
            return None
        return {k: doc.get(k) for k in ("no_rekening", "id_produk", "status_rekening", "saldo_efektif", "saldo_tersedia",
                                        "saldo_efektif_sen", "id_unit_kerja", "last_transaction_at", "tx_count",
                                        "pemegang_rekening")}

    def histori(self, no_rekening: str, dari: datetime | None, sampai: datetime | None, limit: int = 50):
        """R-01 -> Cassandra. Default: 12 bulan terakhir; satu partisi per rekening, sudah terurut waktu menurun."""
        sampai = sampai or datetime.now(timezone.utc) + timedelta(days=1)
        dari = dari or sampai - timedelta(days=365)
        rows = self.ledger.history(no_rekening, _months(dari, sampai), dari, sampai, limit)
        for r in rows:
            r["nominal"] = str(r["nominal"]); r["saldo_setelah"] = str(r["saldo_setelah"]) if r["saldo_setelah"] is not None else None
            r["waktu_event"] = r["waktu_event"].isoformat()
        return rows

    def laporan(self, kode: str, **params):
        if kode == "R-03":
            return self.ledger.report_kanal(params.get("id_kanal", "KNL01"), params["bulan_list"])
        q = rq.COUCHBASE_READS[kode]
        return self.cb.query(q, **({"no_rekening": params["no_rekening"]} if kode == "R-07" else {}))
