"""Repository Event Ledger (Cassandra). Semua penulisan bersifat idempoten:
primary key ditentukan deterministik oleh event (no_rekening, waktu_transaksi, id_transaksi),
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
    # Kolom Cassandra memakai nama laporan (id_transaksi, waktu_transaksi, ...); alias CQL menjaga nama
    # field event pada API/outbox (event_id, waktu_event, ...) tetap sama.
    _ALIAS = ("no_rekening, waktu_transaksi AS waktu_event, id_transaksi AS event_id, jenis_transaksi AS jenis_event, "
              "arah, nominal, mata_uang, id_kanal, nama_kanal, no_kartu, status_transaksi AS status_event, "
              "saldo_setelah, counterparty, sumber")

    def __init__(self, session=None):
        self.s = session or get_session()
        self._ins_main = self.s.prepare("""
            INSERT INTO transaksi_by_rekening (no_rekening, waktu_transaksi, id_transaksi, jenis_transaksi, arah,
                nominal, mata_uang, id_kanal, nama_kanal, no_kartu, status_transaksi, saldo_setelah, counterparty, sumber)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""")
        self._ins_id = self.s.prepare("""
            INSERT INTO transaksi_by_id (id_transaksi, no_rekening, waktu_transaksi, jenis_transaksi, nominal,
                status_transaksi, saldo_setelah, sumber) VALUES (?,?,?,?,?,?,?,?)""")
        self._ins_kanal = self.s.prepare("""
            INSERT INTO transaksi_by_kanal_periode (id_kanal, periode, status_transaksi, jenis_transaksi,
                waktu_transaksi, id_transaksi, nama_kanal, nominal) VALUES (?,?,?,?,?,?,?,?)""")

    # ------------------------------------------------------------------ tulis
    def append_event(self, ev: dict) -> None:
        """Tulis satu event ke ledger (logged batch ke 3 tabel). Idempoten: primary key deterministik."""
        waktu = ev["waktu_event"]
        periode = bulan_of(waktu)
        nominal = sen_to_decimal(ev["nominal_sen"])
        saldo = sen_to_decimal(ev["saldo_setelah_sen"]) if ev.get("saldo_setelah_sen") is not None else None
        b = BatchStatement(batch_type=BatchType.LOGGED)
        b.add(self._ins_main, (ev["no_rekening"], waktu, ev["event_id"], ev["jenis_event"], ev["arah"],
                               nominal, ev.get("mata_uang", "IDR"), ev.get("id_kanal"), ev.get("nama_kanal"),
                               ev.get("no_kartu"), ev["status_event"], saldo, ev.get("counterparty"),
                               ev.get("sumber", "API")))
        b.add(self._ins_id, (ev["event_id"], ev["no_rekening"], waktu, ev["jenis_event"], nominal,
                             ev["status_event"], saldo, ev.get("sumber", "API")))
        b.add(self._ins_kanal, (ev.get("id_kanal") or "NA", periode, ev["status_event"], ev["jenis_event"], waktu,
                                ev["event_id"], ev.get("nama_kanal"), nominal))
        self.s.execute(b)

    # ------------------------------------------------------------------ baca
    def history(self, no_rekening: str, bulan_list: Iterable[str] = (), dari: datetime | None = None,
                sampai: datetime | None = None, limit: int = 100) -> list[dict]:
        """R-01: satu partisi (no_rekening), sudah terurut waktu_transaksi DESC."""
        cql = f"SELECT {self._ALIAS} FROM transaksi_by_rekening WHERE no_rekening=%s"
        params: list = [no_rekening]
        if dari:
            cql += " AND waktu_transaksi >= %s"; params.append(dari)
        if sampai:
            cql += " AND waktu_transaksi < %s"; params.append(sampai)
        cql += " ORDER BY waktu_transaksi DESC LIMIT %s"; params.append(limit)
        return [r._asdict() for r in self.s.execute(SimpleStatement(cql), params)]

    def get_event(self, event_id: str) -> dict | None:
        r = self.s.execute("SELECT id_transaksi AS event_id, no_rekening, waktu_transaksi AS waktu_event, "
                           "jenis_transaksi AS jenis_event, nominal, status_transaksi AS status_event, saldo_setelah, sumber "
                           "FROM transaksi_by_id WHERE id_transaksi=%s", [event_id]).one()
        return r._asdict() if r else None

    def count_rekening(self, no_rekening: str) -> int:
        return self.s.execute("SELECT COUNT(*) FROM transaksi_by_rekening WHERE no_rekening=%s", [no_rekening]).one()[0]

    def report_kanal(self, id_kanal: str, bulan_list: Iterable[str]) -> list[dict]:
        """R-03: COUNT/SUM/AVG per periode dan jenis dikerjakan server (GROUP BY pada primary key), status BERHASIL."""
        out = []
        periods = sorted(set(bulan_list))
        if not periods:
            return out
        marks = ",".join(["%s"] * len(periods))
        cql = ("SELECT periode AS bulan, nama_kanal, jenis_transaksi, COUNT(*) AS jumlah_transaksi, "
               "SUM(nominal) AS total_nominal, AVG(nominal) AS rata_rata_nominal FROM transaksi_by_kanal_periode "
               f"WHERE id_kanal=%s AND periode IN ({marks}) AND status_transaksi='BERHASIL' "
               "GROUP BY id_kanal, periode, status_transaksi, jenis_transaksi")
        for r in self.s.execute(SimpleStatement(cql), [id_kanal, *periods]):
            out.append({"bulan": r.bulan, "id_kanal": id_kanal, "jenis_transaksi": r.jenis_transaksi,
                        "jumlah_transaksi": r.jumlah_transaksi, "total_nominal": str(r.total_nominal),
                        "rata_rata_nominal": str(Decimal(r.rata_rata_nominal).quantize(MONEY_Q))})
        out.sort(key=lambda d: (d["bulan"], d["jenis_transaksi"]))
        return out

    def ping(self) -> bool:
        return self.s.execute("SELECT release_version FROM system.local").one() is not None
