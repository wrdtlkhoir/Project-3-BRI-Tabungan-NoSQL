"""Repository Event Ledger (Cassandra). Semua penulisan bersifat idempoten:
primary key ditentukan deterministik oleh event (no_rekening, bulan, waktu_event, event_id),
sehingga retry menulis baris yang sama (upsert) dan tidak menggandakan event."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

from cassandra.query import BatchStatement, BatchType, SimpleStatement

from app.database.cassandra_db import get_session

MONEY_Q = Decimal("0.01")


def bulan_of(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y%m")


def sen_to_decimal(sen: int) -> Decimal:
    return (Decimal(sen) / Decimal(100)).quantize(MONEY_Q)


class CassandraLedgerRepository:
    def __init__(self, session=None):
        self.s = session or get_session()
        self._ins_main = self.s.prepare("""
            INSERT INTO ledger_by_rekening (no_rekening, bulan, waktu_event, event_id, jenis_event, arah,
                nominal, mata_uang, id_kanal, nama_kanal, no_kartu, status_event, saldo_setelah, counterparty, sumber)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""")
        self._ins_id = self.s.prepare("""
            INSERT INTO ledger_event_by_id (event_id, no_rekening, bulan, waktu_event, jenis_event, nominal,
                status_event, saldo_setelah, sumber) VALUES (?,?,?,?,?,?,?,?,?)""")
        self._ins_kanal = self.s.prepare("""
            INSERT INTO ledger_by_kanal_bulan (id_kanal, bulan, waktu_event, event_id, nama_kanal, jenis_event,
                nominal, status_event) VALUES (?,?,?,?,?,?,?,?)""")

    # ------------------------------------------------------------------ tulis
    def append_event(self, ev: dict) -> None:
        """Tulis satu event ke ledger (logged batch ke 3 tabel). Idempoten."""
        waktu = ev["waktu_event"]
        bulan = bulan_of(waktu)
        nominal = sen_to_decimal(ev["nominal_sen"])
        saldo = sen_to_decimal(ev["saldo_setelah_sen"]) if ev.get("saldo_setelah_sen") is not None else None
        b = BatchStatement(batch_type=BatchType.LOGGED)
        b.add(self._ins_main, (ev["no_rekening"], bulan, waktu, ev["event_id"], ev["jenis_event"], ev["arah"],
                               nominal, ev.get("mata_uang", "IDR"), ev.get("id_kanal"), ev.get("nama_kanal"),
                               ev.get("no_kartu"), ev["status_event"], saldo, ev.get("counterparty"),
                               ev.get("sumber", "API")))
        b.add(self._ins_id, (ev["event_id"], ev["no_rekening"], bulan, waktu, ev["jenis_event"], nominal,
                             ev["status_event"], saldo, ev.get("sumber", "API")))
        b.add(self._ins_kanal, (ev.get("id_kanal") or "NA", bulan, waktu, ev["event_id"], ev.get("nama_kanal"),
                                ev["jenis_event"], nominal, ev["status_event"]))
        self.s.execute(b)

    # ------------------------------------------------------------------ baca
    def history(self, no_rekening: str, bulan_list: Iterable[str], dari: datetime | None = None,
                sampai: datetime | None = None, limit: int = 100) -> list[dict]:
        """R-01. Baca per partisi (rekening, bulan) lalu gabungkan, terbaru dulu."""
        rows: list[dict] = []
        for bulan in sorted(set(bulan_list), reverse=True):
            cql = ("SELECT * FROM ledger_by_rekening WHERE no_rekening=%s AND bulan=%s")
            params = [no_rekening, bulan]
            if dari:
                cql += " AND waktu_event >= %s"; params.append(dari)
            if sampai:
                cql += " AND waktu_event < %s"; params.append(sampai)
            cql += " LIMIT %s"; params.append(limit)
            for r in self.s.execute(SimpleStatement(cql), params):
                rows.append(r._asdict())
            if len(rows) >= limit:
                break
        rows.sort(key=lambda r: r["waktu_event"], reverse=True)
        return rows[:limit]

    def months_with_data(self, no_rekening: str, candidates: Iterable[str]) -> list[str]:
        out = []
        for b in candidates:
            r = self.s.execute("SELECT event_id FROM ledger_by_rekening WHERE no_rekening=%s AND bulan=%s LIMIT 1",
                               [no_rekening, b]).one()
            if r:
                out.append(b)
        return out

    def get_event(self, event_id: str) -> dict | None:
        r = self.s.execute("SELECT * FROM ledger_event_by_id WHERE event_id=%s", [event_id]).one()
        return r._asdict() if r else None

    def count_partition(self, no_rekening: str, bulan: str) -> int:
        return self.s.execute("SELECT COUNT(*) FROM ledger_by_rekening WHERE no_rekening=%s AND bulan=%s",
                              [no_rekening, bulan]).one()[0]

    def report_kanal(self, id_kanal: str, bulan_list: Iterable[str]) -> list[dict]:
        """R-03: agregasi per bulan dari partisi (id_kanal, bulan); hanya status BERHASIL."""
        out = []
        for b in sorted(bulan_list):
            n, total = 0, Decimal(0)
            by_jenis: dict[str, list] = {}
            for r in self.s.execute("SELECT jenis_event, nominal, status_event, nama_kanal FROM ledger_by_kanal_bulan "
                                    "WHERE id_kanal=%s AND bulan=%s", [id_kanal, b]):
                if r.status_event != "BERHASIL":
                    continue
                d = by_jenis.setdefault(r.jenis_event, [0, Decimal(0)])
                d[0] += 1; d[1] += r.nominal
            for jenis, (n, total) in by_jenis.items():
                out.append({"bulan": b, "id_kanal": id_kanal, "jenis_transaksi": jenis, "jumlah_transaksi": n,
                            "total_nominal": str(total), "rata_rata_nominal": str((total / n).quantize(MONEY_Q))})
        return out

    def ping(self) -> bool:
        return self.s.execute("SELECT release_version FROM system.local").one() is not None
