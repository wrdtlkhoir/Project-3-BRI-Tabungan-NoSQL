"""Katalog 20 query (R-01..R-10, W-01..W-10) untuk UI + benchmark.

Aturan:
* Logika bisnis lama TIDAK diubah: R-01/R-03 memakai RekeningService/CassandraLedgerRepository, R-02..R-10 memakai teks
  N1QL di `app/repositories/read_queries.py` (hanya dibuat varian berparameter / tanpa LIMIT), W-07/W-05/W-10 memakai
  TransaksiService. Hanya W-01..W-04, W-06, W-08, W-09 yang runner-nya baru di sini (sebelumnya hanya berupa N1QL
  di `infra/couchbase/write_queries.n1ql`).
* Query tulis HANYA menyentuh data uji (prefix 002999 / NSB99 / 52299 / INSW99) kecuali pengguna memilih data lain.
"""
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Optional

from couchbase.exceptions import DocumentExistsException, DocumentNotFoundException, TransactionFailed
from couchbase.n1ql import QueryScanConsistency
from couchbase.options import QueryOptions

from app import timing
from app.repositories import read_queries as rq
from app.repositories.couchbase_repository import now_iso, sen_to_rupiah
from app.services.rekening_service import _months
from app.services.transaksi_service import BusinessError, to_sen

# --------------------------------------------------------------------------- data uji
TEST_PREFIX = "002999"
TEST_NASABAH = "NSB999000001"
TEST_ACC = {1: "002999000000001", 2: "002999000000002", 3: "002999000000003", 4: "002999000000004", 5: "002999000000005"}
TEST_CARD = "5229990000000001"
TEST_SALDO_SEN = 100_000_000          # Rp1.000.000,00
_B = {"svc": None, "rek": None}


def bind(trx, rek):
    _B["svc"], _B["rek"] = trx, rek


def svc():
    return _B["svc"]


def cb():
    return _B["svc"].cb


def ledger():
    return _B["svc"].ledger


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _rek_doc(no, saldo_sen):
    return {"_type": "rekening", "no_rekening": no, "id_produk": "PRD01", "mata_uang": "IDR", "tanggal_buka": _today(),
            "tanggal_tutup": None, "status_rekening": "AKTIF", "saldo_efektif": sen_to_rupiah(saldo_sen),
            "saldo_tersedia": sen_to_rupiah(saldo_sen), "saldo_efektif_sen": saldo_sen, "saldo_tersedia_sen": saldo_sen,
            "id_unit_kerja": "UK0005", "last_transaction_at": None, "tx_count": 0,
            "pemegang_rekening": [{"id_nasabah": TEST_NASABAH, "peran": "PEMEGANG_UTAMA", "penanda_utama": "Y", "tanggal_mulai": _today()}],
            "data_uji": True}


def ensure_test_data(reset: bool = False) -> dict:
    """Pastikan data uji ada. reset=True: hapus semua data uji (dan jejaknya di outbox + ledger) lalu buat ulang baseline."""
    c = cb()
    if reset:
        purge_test_data()
    made = []
    nas = {"_type": "nasabah", "id_nasabah": TEST_NASABAH, "nik": "9999000000000001", "nama_lengkap": "Nasabah Uji Coba",
           "jenis_nasabah": "INDIVIDU", "segmen_nasabah": "RITEL", "status_kyc": "TERVERIFIKASI",
           "tanggal_registrasi": _today(), "data_uji": True,
           "rekening_refs": [{"no_rekening": n, "peran": "PEMEGANG_UTAMA", "penanda_utama": "Y"} for n in TEST_ACC.values()]}
    try:
        c.nasabah.insert(f"nasabah::{TEST_NASABAH}", nas); made.append("nasabah")
    except DocumentExistsException:
        pass
    for i, no in TEST_ACC.items():
        try:
            c.rekening.insert(f"rekening::{no}", _rek_doc(no, 0 if i == 5 else TEST_SALDO_SEN)); made.append(no)
        except DocumentExistsException:
            pass
    try:
        kartu = c.cluster.bucket("bri_tabungan").scope("operasional").collection("kartu_debit")
        kartu.insert(f"kartu_debit::{TEST_CARD}", {"_type": "kartu_debit", "no_kartu": TEST_CARD, "no_rekening": TEST_ACC[1],
                       "bentuk_kartu": "FISIK", "jaringan_kartu": "VISA", "status_kartu": "AKTIF", "tanggal_terbit": _today(),
                       "tanggal_kadaluarsa": (datetime.now(timezone.utc) + timedelta(days=1825)).strftime("%Y-%m-%d"), "data_uji": True})
        made.append("kartu")
    except DocumentExistsException:
        pass
    return {"dibuat": made}


def _n1ql(q, **named):
    return list(cb().cluster.query(q, QueryOptions(named_parameters=named, scan_consistency=QueryScanConsistency.REQUEST_PLUS)).rows())


def purge_ledger_events(event_ids: list[str]):
    """Hapus jejak event uji di Cassandra (3 tabel) dan outbox Couchbase. Hanya untuk data uji."""
    s = ledger().s
    for eid in event_ids:
        r = s.execute("SELECT no_rekening, waktu_transaksi, jenis_transaksi, status_transaksi FROM transaksi_by_id WHERE id_transaksi=%s", [eid]).one()
        if r:
            row = s.execute("SELECT id_kanal FROM transaksi_by_rekening WHERE no_rekening=%s AND waktu_transaksi=%s AND id_transaksi=%s",
                            [r.no_rekening, r.waktu_transaksi, eid]).one()
            kanal = (row.id_kanal if row else None) or "NA"
            periode = r.waktu_transaksi.strftime("%Y%m")
            s.execute("DELETE FROM transaksi_by_rekening WHERE no_rekening=%s AND waktu_transaksi=%s AND id_transaksi=%s",
                      [r.no_rekening, r.waktu_transaksi, eid])
            s.execute("DELETE FROM transaksi_by_kanal_periode WHERE id_kanal=%s AND periode=%s AND status_transaksi=%s AND jenis_transaksi=%s AND waktu_transaksi=%s AND id_transaksi=%s",
                      [kanal, periode, r.status_transaksi, r.jenis_transaksi, r.waktu_transaksi, eid])
            s.execute("DELETE FROM transaksi_by_id WHERE id_transaksi=%s", [eid])
        try:
            cb().outbox.remove(f"outbox::{eid}")
        except DocumentNotFoundException:
            pass


def purge_test_data():
    """Hapus seluruh data uji + event ledger/outbox-nya."""
    q = lambda stmt: _n1ql(stmt)
    ks = "`bri_tabungan`.`operasional`"
    ev = [r["id"] for r in q(f"SELECT o.event_id AS id FROM {ks}.`outbox` o WHERE o.event.no_rekening LIKE '{TEST_PREFIX}%'")]
    purge_ledger_events(ev)
    for coll, pat in [("rekening", f"rekening::{TEST_PREFIX}%"), ("nasabah", "nasabah::NSB99%"), ("nasabah", "nik::9999%"),
                      ("kartu_debit", "kartu_debit::52299%"), ("instruksi_terjadwal", "instruksi::INSW99%"),
                      ("posting_bunga", f"posting::{TEST_PREFIX}%")]:
        q(f"DELETE FROM {ks}.`{coll}` d WHERE META(d).id LIKE '{pat}'")


# --------------------------------------------------------------------------- util query
def _strip_limit(q: str) -> str:
    return re.sub(r"\s+LIMIT\s+\d+\s*$", "", q.strip())


def cb_query(q: str, **named) -> list[dict]:
    """Jalankan N1QL, konsumsi SEMUA hasil, catat executionTime sisi server."""
    with timing.timed("cb"):
        res = cb().cluster.query(q, QueryOptions(named_parameters=named, scan_consistency=QueryScanConsistency.NOT_BOUNDED, metrics=True))
        rows = list(res.rows())
        try:
            timing.set_server_exec(res.metadata().metrics().execution_time().total_seconds() * 1000)
        except Exception:
            pass
    return rows


def _rand(n):
    return "".join(random.choice("0123456789") for _ in range(n))


@dataclass
class Param:
    name: str
    label: str
    type: str = "text"            # text | number | date | select
    default: object = ""
    options: Optional[list] = None
    hint: str = ""


@dataclass
class Q:
    id: str
    kind: str                      # R | W
    title: str
    desc: str
    db: str                        # Couchbase | Cassandra | Keduanya
    params: list
    statement: str
    run: Callable
    note: str = ""


CAT: dict[str, Q] = {}


def reg(q: Q):
    CAT[q.id] = q


# =========================================================================== READ
def r01(p):
    rs = _B["rek"]
    d1 = datetime.fromisoformat(p["tanggal_awal"]).replace(tzinfo=timezone.utc)
    d2 = datetime.fromisoformat(p["tanggal_akhir"]).replace(tzinfo=timezone.utc) + timedelta(days=1)
    rows = rs.histori(p["no_rekening"], d1, d2, 5000)
    timing.set_rows(len(rows))
    return {"rows": rows}


reg(Q("R-01", "R", "Riwayat transaksi rekening", "Riwayat transaksi satu rekening dalam periode (terbaru dulu).", "Cassandra",
      [Param("no_rekening", "No. rekening", "text", "002101000000001"), Param("tanggal_awal", "Tanggal awal", "date", "2025-11-01"),
       Param("tanggal_akhir", "Tanggal akhir", "date", "2026-12-31")],
      "SELECT id_transaksi, waktu_transaksi, jenis_transaksi, arah, nominal, mata_uang,\n       status_transaksi, saldo_setelah, nama_kanal, no_kartu\n  FROM bri_tabungan.transaksi_by_rekening\n WHERE no_rekening = ?\n   AND waktu_transaksi >= ? AND waktu_transaksi < ?\n ORDER BY waktu_transaksi DESC;",
      r01))


def _cbq(qid, title, desc, params, text, builder, note=""):
    def run(p):
        stmt, named = builder(p)
        rows = cb_query(stmt, **named)
        timing.set_rows(len(rows))
        return {"rows": rows, "statement_dijalankan": stmt}
    reg(Q(qid, "R", title, desc, "Couchbase", params, text, run, note))


_cbq("R-02", "Nasabah dengan >1 rekening aktif", "Nasabah yang memiliki lebih dari satu rekening berstatus AKTIF.", [],
     _strip_limit(rq.R02), lambda p: (_strip_limit(rq.R02), {}))
_cbq("R-04", "Rekening idle (tanpa transaksi > N hari)", "Rekening AKTIF tanpa transaksi BERHASIL dalam N hari terakhir (last_transaction_at hanya diisi dari transaksi BERHASIL).",
     [Param("hari", "Hari", "number", 90)], _strip_limit(rq.R04).replace("(90 * 86400000)", "($hari * 86400000)"),
     lambda p: (_strip_limit(rq.R04).replace("(90 * 86400000)", "($hari * 86400000)"), {"hari": int(p["hari"])}))
_cbq("R-05", "Nasabah tanpa rekening", "Nasabah yang belum memiliki rekening.", [], _strip_limit(rq.R05), lambda p: (_strip_limit(rq.R05), {}))


def _r06(p):
    base = _strip_limit(rq.R06)
    if p.get("id_unit"):
        return base.replace("GROUP BY", "WHERE u.id_unit_kerja = $id_unit\nGROUP BY", 1), {"id_unit": p["id_unit"]}
    return base, {}


_cbq("R-06", "Rekap rekening per unit kerja", "Jumlah rekening AKTIF dan total saldo per unit kerja (opsional satu unit).",
     [Param("id_unit", "ID unit (opsional)", "text", "", hint="kosongkan = semua unit")], _strip_limit(rq.R06), _r06)
_cbq("R-07", "Riwayat posting bunga rekening", "Posting bunga dan pajak PPh final per periode. (Implementasi repo: Couchbase, koleksi posting_bunga.)",
     [Param("no_rekening", "No. rekening", "text", "002101000000001")], rq.R07, lambda p: (rq.R07, {"no_rekening": p["no_rekening"]}),
     note="Katalog awal menyebut Cassandra; implementasi repo menyimpan posting_bunga di Couchbase.")
_cbq("R-08", "Instruksi terjadwal aktif", "Instruksi AFT/autodebet yang masih aktif.", [], _strip_limit(rq.R08), lambda p: (_strip_limit(rq.R08), {}))
_cbq("R-09", "Kartu debit kedaluwarsa dalam N hari", "Kartu AKTIF yang kedaluwarsa dalam N hari ke depan beserta nama pemilik utama.",
     [Param("hari", "Hari", "number", 30)], _strip_limit(rq.R09).replace("30, 'day'", "$hari, 'day'"),
     lambda p: (_strip_limit(rq.R09).replace("30, 'day'", "$hari, 'day'"), {"hari": int(p["hari"])}))
_cbq("R-10", "Distribusi rekening per produk", "Jumlah rekening dan total saldo per produk tabungan.", [], rq.R10, lambda p: (rq.R10, {}))


def r03(p):
    thn = int(p["tahun"])
    bl = [f"{thn}{m:02d}" for m in range(1, 13)]
    rows = ledger().report_kanal(p["id_kanal"], bl)
    timing.set_rows(len(rows))
    return {"rows": rows}


# R-03 diselipkan agar urutan katalog R-01, R-02, R-03, ...
_tmp = CAT.pop("R-02")
reg(_tmp)
reg(Q("R-03", "R", "Laporan transaksi bulanan per kanal", "Jumlah dan nominal transaksi BERHASIL per bulan dan jenis pada satu kanal (GROUP BY dikerjakan server dari tabel transaksi_by_kanal_periode).",
      "Cassandra", [Param("id_kanal", "ID kanal", "select", "KNL01", [f"KNL0{i}" for i in range(1, 8)]), Param("tahun", "Tahun", "number", 2026)],
      "SELECT periode AS bulan, nama_kanal, jenis_transaksi,\n       COUNT(*) AS jumlah_transaksi, SUM(nominal) AS total_nominal, AVG(nominal) AS rata_rata_nominal\n  FROM bri_tabungan.transaksi_by_kanal_periode\n WHERE id_kanal = ? AND periode IN (?, ...)\n   AND status_transaksi = 'BERHASIL'\n GROUP BY id_kanal, periode, status_transaksi, jenis_transaksi;", r03))


# =========================================================================== WRITE helpers
def _txn(fn):
    with timing.timed("cb"):
        try:
            cb().cluster.transactions.run(fn)
        except TransactionFailed as e:
            raise BusinessError("TRANSAKSI_GAGAL", f"transaksi Couchbase dibatalkan: {str(e)[:120]}")


def _need_rek(no):
    d = cb().get_rekening(no)
    if d is None:
        raise BusinessError("REKENING_TIDAK_DITEMUKAN", f"rekening {no} tidak ada")
    return d


def _get_doc(coll, key):
    with timing.timed("cb"):
        try:
            return coll.get(key).content_as[dict]
        except DocumentNotFoundException:
            return None


# --- W-01
def w01(p):
    nik = p.get("nik") or "9999" + _rand(12)
    nid = "NSB99" + _rand(7)
    c = cb()
    if _get_doc(c.nasabah, f"nik::{nik}"):
        raise BusinessError("NIK_SUDAH_TERDAFTAR", f"NIK {nik} sudah terdaftar")
    doc = {"_type": "nasabah", "id_nasabah": nid, "nik": nik, "nama_lengkap": p["nama_lengkap"], "jenis_nasabah": p["jenis_nasabah"],
           "segmen_nasabah": p["segmen_nasabah"], "status_kyc": "MENUNGGU_VERIFIKASI", "tanggal_registrasi": _today(),
           "rekening_refs": [], "data_uji": True}

    def logic(ctx):
        ctx.insert(c.nasabah, f"nik::{nik}", {"id_nasabah": nid})
        ctx.insert(c.nasabah, f"nasabah::{nid}", doc)
    _txn(logic)
    return {"rows": [doc], "message": f"nasabah {nid} terdaftar (NIK {nik})", "undo": [("del", c.nasabah, f"nasabah::{nid}"), ("del", c.nasabah, f"nik::{nik}")]}


reg(Q("W-01", "W", "Daftarkan nasabah baru", "Membuat dokumen nasabah + dokumen penjaga NIK (keunikan) dalam satu transaksi ACID.", "Couchbase",
      [Param("nik", "NIK (kosong = acak)", "text", ""), Param("nama_lengkap", "Nama lengkap", "text", "Nasabah Uji Baru"),
       Param("jenis_nasabah", "Jenis", "select", "INDIVIDU", ["INDIVIDU", "KORPORASI", "LEMBAGA"]),
       Param("segmen_nasabah", "Segmen", "select", "RITEL", ["MIKRO_UMI", "RITEL", "PRIORITAS", "PRIVATE", "KORPORASI"])],
      "INSERT INTO `bri_tabungan`.`operasional`.`nasabah` (KEY, VALUE) VALUES\n  ('nik::<nik>', {\"id_nasabah\": \"<id>\"}),\n  ('nasabah::<id>', {... \"status_kyc\": \"MENUNGGU_VERIFIKASI\", \"rekening_refs\": []});\n-- keduanya dalam 1 transaksi ACID (SDK transactions)", w01))


# --- W-02
def w02(p):
    c = cb()
    nas = _get_doc(c.nasabah, f"nasabah::{p['id_nasabah']}")
    if nas is None:
        raise BusinessError("NASABAH_TIDAK_DITEMUKAN", f"nasabah {p['id_nasabah']} tidak ada")
    if _get_doc(c.cluster.bucket("bri_tabungan").scope("operasional").collection("produk"), f"produk::{p['id_produk']}") is None:
        raise BusinessError("PRODUK_TIDAK_DITEMUKAN", f"produk {p['id_produk']} tidak ada")
    no = TEST_PREFIX + _rand(9)
    doc = _rek_doc(no, 0); doc["id_produk"] = p["id_produk"]; doc["id_unit_kerja"] = p["id_unit"]
    doc["pemegang_rekening"][0]["id_nasabah"] = p["id_nasabah"]
    snap = dict(nas)

    def logic(ctx):
        r = ctx.get(c.nasabah, f"nasabah::{p['id_nasabah']}")
        n = r.content_as[dict]
        n.setdefault("rekening_refs", []).append({"no_rekening": no, "peran": "PEMEGANG_UTAMA", "penanda_utama": "Y"})
        ctx.insert(c.rekening, f"rekening::{no}", doc)
        ctx.replace(r, n)
    _txn(logic)
    return {"rows": [doc], "message": f"rekening {no} dibuka untuk {p['id_nasabah']}",
            "undo": [("del", c.rekening, f"rekening::{no}"), ("put", c.nasabah, f"nasabah::{p['id_nasabah']}", snap)]}


reg(Q("W-02", "W", "Buka rekening tabungan baru", "Membuat rekening baru (saldo 0) dan menautkannya ke nasabah (rekening_refs) dalam satu transaksi ACID.", "Couchbase",
      [Param("id_nasabah", "ID nasabah", "text", TEST_NASABAH), Param("id_produk", "ID produk", "text", "PRD01"), Param("id_unit", "ID unit kerja", "text", "UK0005")],
      "INSERT INTO `...`.`rekening` (KEY, VALUE) VALUES ('rekening::<no>', {... \"saldo_efektif_sen\": 0, \"status_rekening\": \"AKTIF\"});\nUPDATE `...`.`nasabah` USE KEYS 'nasabah::<id>' SET rekening_refs = ARRAY_APPEND(rekening_refs, {...});\n-- 1 transaksi ACID", w02,
      note="Event status tidak dicatat ke ledger; ledger hanya menerima transaksi uang dan perubahan status (W-05, W-10)."))


# --- W-03
def w03(p):
    c = cb()
    r_snap = _need_rek(p["no_rekening"])
    n_snap = _get_doc(c.nasabah, f"nasabah::{p['id_nasabah']}")
    if n_snap is None:
        raise BusinessError("NASABAH_TIDAK_DITEMUKAN", f"nasabah {p['id_nasabah']} tidak ada")
    if any(h["id_nasabah"] == p["id_nasabah"] for h in r_snap.get("pemegang_rekening", [])):
        raise BusinessError("SUDAH_PEMEGANG", "nasabah sudah tercatat sebagai pemegang rekening ini")

    def logic(ctx):
        rr = ctx.get(c.rekening, f"rekening::{p['no_rekening']}"); rn = ctx.get(c.nasabah, f"nasabah::{p['id_nasabah']}")
        d1, d2 = rr.content_as[dict], rn.content_as[dict]
        d1.setdefault("pemegang_rekening", []).append({"id_nasabah": p["id_nasabah"], "peran": p["peran"], "penanda_utama": "N", "tanggal_mulai": _today()})
        d2.setdefault("rekening_refs", []).append({"no_rekening": p["no_rekening"], "peran": p["peran"], "penanda_utama": "N"})
        ctx.replace(rr, d1); ctx.replace(rn, d2)
    _txn(logic)
    return {"rows": [{"no_rekening": p["no_rekening"], "id_nasabah": p["id_nasabah"], "peran": p["peran"]}], "message": "pemegang rekening dicatat dua arah (atomik)",
            "undo": [("put", c.rekening, f"rekening::{p['no_rekening']}", r_snap), ("put", c.nasabah, f"nasabah::{p['id_nasabah']}", n_snap)]}


reg(Q("W-03", "W", "Catat pemegang rekening", "Menambah pemegang/peran pada rekening dan menautkan balik ke nasabah, atomik dalam satu transaksi ACID (dua dokumen).", "Couchbase",
      [Param("no_rekening", "No. rekening", "text", TEST_ACC[1]), Param("id_nasabah", "ID nasabah", "text", "NSB000000001"),
       Param("peran", "Peran", "select", "PESERTA", ["PEMEGANG_UTAMA", "PESERTA", "PEMBERI_KUASA"])],
      "UPDATE `...`.`rekening` USE KEYS 'rekening::<no>' SET pemegang_rekening = ARRAY_APPEND(pemegang_rekening, {...});\nUPDATE `...`.`nasabah` USE KEYS 'nasabah::<id>' SET rekening_refs = ARRAY_APPEND(rekening_refs, {...});\n-- 1 transaksi ACID (jawaban catatan reviewer: dua UPDATE tidak boleh terpisah)", w03))


# --- W-04
def w04(p):
    c = cb()
    _need_rek(p["no_rekening"])
    kartu_col = cb().cluster.bucket("bri_tabungan").scope("operasional").collection("kartu_debit")
    no = p.get("no_kartu") or "52299" + _rand(11)
    doc = {"_type": "kartu_debit", "no_kartu": no, "no_rekening": p["no_rekening"], "bentuk_kartu": p["bentuk_kartu"], "jaringan_kartu": p["jaringan_kartu"],
           "status_kartu": "AKTIF", "tanggal_terbit": _today(), "tanggal_kadaluarsa": (datetime.now(timezone.utc) + timedelta(days=1825)).strftime("%Y-%m-%d"), "data_uji": True}
    with timing.timed("cb"):
        try:
            kartu_col.insert(f"kartu_debit::{no}", doc)
        except DocumentExistsException:
            raise BusinessError("KARTU_SUDAH_ADA", f"kartu {no} sudah ada")
    return {"rows": [doc], "message": f"kartu {no} didaftarkan", "undo": [("del", kartu_col, f"kartu_debit::{no}")]}


reg(Q("W-04", "W", "Daftarkan kartu debit", "Mendaftarkan kartu debit baru yang terhubung ke rekening.", "Couchbase",
      [Param("no_rekening", "No. rekening", "text", TEST_ACC[1]), Param("no_kartu", "No. kartu (kosong = acak)", "text", ""),
       Param("bentuk_kartu", "Bentuk", "select", "FISIK", ["FISIK", "VIRTUAL"]),
       Param("jaringan_kartu", "Jaringan", "select", "VISA", ["VISA", "MASTERCARD", "GPN_PRIVATE_LABEL"])],
      "INSERT INTO `...`.`kartu_debit` (KEY, VALUE) VALUES ('kartu_debit::<no>', {... \"status_kartu\": \"AKTIF\"});", w04))


# --- W-05 / W-10 (memakai TransaksiService.ubah_status yang sudah ada)
def _status_runner(status):
    def run(p):
        c = cb(); no = p["no_rekening"]
        snap = _need_rek(no)
        idem = "ui-" + uuid.uuid4().hex[:16]
        res = svc().ubah_status(no, status, idem)
        eid = res["event_id"]
        return {"rows": [res], "message": f"status rekening {no} menjadi {status}",
                "undo": [("put", c.rekening, f"rekening::{no}", snap), ("ledger", [eid])]}
    return run


reg(Q("W-05", "W", "Blokir rekening", "Mengubah status rekening AKTIF menjadi TERBLOKIR (transaksi ACID) + event audit STATUS_BLOKIR ke ledger Cassandra.", "Keduanya",
      [Param("no_rekening", "No. rekening", "text", TEST_ACC[2])],
      "UPDATE `...`.`rekening` USE KEYS 'rekening::<no>' SET status_rekening = 'TERBLOKIR' WHERE status_rekening = 'AKTIF';\n-- + dokumen outbox PENDING (1 transaksi ACID) -> event STATUS_BLOKIR di Cassandra", _status_runner("TERBLOKIR")))

reg(Q("W-10", "W", "Penutupan rekening", "Menutup rekening (hanya jika AKTIF dan saldo 0) + event audit STATUS_TUTUP ke ledger.", "Keduanya",
      [Param("no_rekening", "No. rekening", "text", TEST_ACC[5])],
      "UPDATE `...`.`rekening` USE KEYS 'rekening::<no>' SET status_rekening = 'DITUTUP', tanggal_tutup = <hari ini>\n WHERE status_rekening = 'AKTIF' AND saldo_efektif_sen = 0;\n-- + outbox -> event STATUS_TUTUP di Cassandra", _status_runner("DITUTUP")))


# --- W-06
def w06(p):
    c = cb()
    kartu_col = c.cluster.bucket("bri_tabungan").scope("operasional").collection("kartu_debit")
    snap = _get_doc(kartu_col, f"kartu_debit::{p['no_kartu']}")
    if snap is None:
        raise BusinessError("KARTU_TIDAK_DITEMUKAN", f"kartu {p['no_kartu']} tidak ada")

    def logic(ctx):
        r = ctx.get(kartu_col, f"kartu_debit::{p['no_kartu']}")
        d = r.content_as[dict]
        if d.get("status_kartu") != "AKTIF":
            raise BusinessError("KARTU_TIDAK_AKTIF", f"status kartu {d.get('status_kartu')}")
        d["status_kartu"] = "BLOKIR_SEMENTARA"
        ctx.replace(r, d)
    with timing.timed("cb"):
        if snap.get("status_kartu") != "AKTIF":
            raise BusinessError("KARTU_TIDAK_AKTIF", f"status kartu {snap.get('status_kartu')}")
        c.cluster.transactions.run(logic)
    return {"rows": [{"no_kartu": p["no_kartu"], "status_kartu": "BLOKIR_SEMENTARA"}], "message": "kartu diblokir sementara",
            "undo": [("put", kartu_col, f"kartu_debit::{p['no_kartu']}", snap)]}


reg(Q("W-06", "W", "Blokir sementara kartu debit", "Mengubah status kartu AKTIF menjadi BLOKIR_SEMENTARA.", "Couchbase",
      [Param("no_kartu", "No. kartu", "text", TEST_CARD)],
      "UPDATE `...`.`kartu_debit` USE KEYS 'kartu_debit::<no>' SET status_kartu = 'BLOKIR_SEMENTARA' WHERE status_kartu = 'AKTIF';", w06))


# --- W-07
def w07(p):
    s = svc(); c = cb(); jenis = p["jenis"]
    idem = p.get("idempotency_key") or "ui-" + uuid.uuid4().hex[:16]
    nominal = Decimal(str(p["nominal"]))
    accs = [p["no_rekening"]] + ([p["no_rekening_tujuan"]] if jenis == "transfer" else [])
    snaps = {a: _need_rek(a) for a in accs}
    if jenis == "setoran":
        res = s.setoran(p["no_rekening"], nominal, idem)
    elif jenis == "penarikan":
        res = s.penarikan(p["no_rekening"], nominal, idem)
    else:
        res = s.transfer(p["no_rekening"], p["no_rekening_tujuan"], nominal, idem)
    eids = [res["event_id"]] + ([res["detail"]["event_id_kredit"]] if jenis == "transfer" else [])
    undo = [("put", c.rekening, f"rekening::{a}", snaps[a]) for a in accs] + [("ledger", eids)]
    after = {a: cb().get_rekening(a)["saldo_efektif"] for a in accs}
    return {"rows": [res], "message": f"{jenis} berhasil, ledger {res['ledger_status']}", "saldo_sebelum": {a: snaps[a]["saldo_efektif"] for a in accs},
            "saldo_sesudah": after, "ledger_visible_lag_ms": 0 if res["ledger_status"] == "PUBLISHED" else None, "undo": undo}


reg(Q("W-07", "W", "Transaksi (setoran / penarikan / transfer)", "Update saldo di Couchbase (transaksi ACID + idempotency + outbox) lalu event terbit ke ledger Cassandra.", "Keduanya",
      [Param("jenis", "Jenis", "select", "setoran", ["setoran", "penarikan", "transfer"]), Param("no_rekening", "No. rekening (sumber)", "text", TEST_ACC[3]),
       Param("no_rekening_tujuan", "Rekening tujuan (transfer)", "text", TEST_ACC[4]), Param("nominal", "Nominal (Rp)", "number", 100000),
       Param("idempotency_key", "Idempotency key (kosong = baru)", "text", "", hint="isi key yang sama untuk mendemokan retry")],
      "-- Couchbase (1 transaksi ACID)\nUPDATE rekening SET saldo_efektif_sen = saldo_efektif_sen + <sen>, tx_count = tx_count + 1, last_transaction_at = NOW_STR();\nINSERT INTO outbox (KEY,VALUE) VALUES ('outbox::<event>', {status:'PENDING', event:{...}});\n-- Cassandra (logged batch, idempoten)\nINSERT INTO bri_ledger.ledger_by_rekening (...) VALUES (...);\nINSERT INTO bri_ledger.ledger_event_by_id (...) VALUES (...);\nINSERT INTO bri_ledger.ledger_by_kanal_bulan (...) VALUES (...);", w07))


# --- W-08
def w08(p):
    c = cb(); _need_rek(p["no_rekening"])
    col = c.cluster.bucket("bri_tabungan").scope("operasional").collection("posting_bunga")
    kotor = Decimal(str(p["bunga_kotor"])); pajak = (kotor * Decimal("0.20")).quantize(Decimal("0.01"))
    doc = {"_type": "posting_bunga", "no_rekening": p["no_rekening"], "periode": p["periode"], "hari_berjalan": int(p["hari_berjalan"]),
           "tarif_bunga": float(p["tarif_bunga"]), "bunga_kotor": float(kotor), "pajak_pph_final": float(pajak), "bunga_bersih": float(kotor - pajak),
           "tanggal_posting": now_iso(), "data_uji": True}
    key = f"posting::{p['no_rekening']}::{p['periode']}"
    with timing.timed("cb"):
        try:
            col.insert(key, doc)
        except DocumentExistsException:
            raise BusinessError("SUDAH_DIPOSTING", f"periode {p['periode']} sudah diposting untuk rekening ini (kunci komposit = idempoten)")
    return {"rows": [doc], "message": f"bunga periode {p['periode']} diposting", "undo": [("del", col, key)]}


reg(Q("W-08", "W", "Posting bunga bulanan", "Mencatat hasil posting bunga satu periode. Kunci komposit posting::rekening::periode membuat posting ganda otomatis ditolak.", "Couchbase",
      [Param("no_rekening", "No. rekening", "text", TEST_ACC[3]), Param("periode", "Periode (YYYYMM)", "text", "202611"),
       Param("hari_berjalan", "Hari berjalan", "number", 30), Param("tarif_bunga", "Tarif bunga", "number", 0.015), Param("bunga_kotor", "Bunga kotor (Rp)", "number", 12500)],
      "INSERT INTO `...`.`posting_bunga` (KEY, VALUE) VALUES ('posting::<no>::<periode>', {bunga_kotor, pajak_pph_final: 20%, bunga_bersih, ...});\n-- INSERT gagal jika kunci sudah ada (idempoten)", w08,
      note="Katalog awal menyebut Cassandra; implementasi repo menyimpan posting_bunga di Couchbase."))


# --- W-09
def w09(p):
    c = cb(); _need_rek(p["no_rekening_sumber"]); _need_rek(p["no_rekening_tujuan"])
    if p["no_rekening_sumber"] == p["no_rekening_tujuan"]:
        raise BusinessError("REKENING_SAMA", "rekening sumber dan tujuan tidak boleh sama")
    col = c.cluster.bucket("bri_tabungan").scope("operasional").collection("instruksi_terjadwal")
    iid = "INSW99" + _rand(9)
    doc = {"_type": "instruksi_terjadwal", "id_instruksi": iid, "jenis_instruksi": "AFT", "no_rekening_sumber": p["no_rekening_sumber"],
           "no_rekening_tujuan": p["no_rekening_tujuan"], "frekuensi": p["frekuensi"], "hari_eksekusi": int(p["hari_eksekusi"]),
           "nominal_target": float(p["nominal_target"]), "status_instruksi": "AKTIF", "tanggal_mulai": _today(), "tanggal_selesai": None, "data_uji": True}
    with timing.timed("cb"):
        col.insert(f"instruksi::{iid}", doc)
    return {"rows": [doc], "message": f"instruksi {iid} dibuat", "undo": [("del", col, f"instruksi::{iid}")]}


reg(Q("W-09", "W", "Instruksi terjadwal baru (AFT)", "Mendaftarkan instruksi transfer otomatis (AFT).", "Couchbase",
      [Param("no_rekening_sumber", "Rekening sumber", "text", TEST_ACC[3]), Param("no_rekening_tujuan", "Rekening tujuan", "text", TEST_ACC[4]),
       Param("nominal_target", "Nominal (Rp)", "number", 1000000), Param("frekuensi", "Frekuensi", "select", "BULANAN", ["HARIAN", "MINGGUAN", "BULANAN"]),
       Param("hari_eksekusi", "Hari eksekusi", "number", 25)],
      "INSERT INTO `...`.`instruksi_terjadwal` (KEY, VALUE) VALUES ('instruksi::<id>', {jenis_instruksi:'AFT', ..., status_instruksi:'AKTIF'});", w09))


# --- urutan katalog R-01..R-10, W-01..W-10
ORDER = [f"R-{i:02d}" for i in range(1, 11)] + [f"W-{i:02d}" for i in range(1, 11)]
CAT = {k: CAT[k] for k in ORDER}


# =========================================================================== eksekusi
def normalize(q: Q, params: dict) -> dict:
    out = {}
    for pr in q.params:
        v = (params or {}).get(pr.name, None)
        out[pr.name] = pr.default if v is None or v == "" else v
        if pr.type == "number" and not isinstance(out[pr.name], (int, float)):
            out[pr.name] = float(out[pr.name]) if "." in str(out[pr.name]) else int(out[pr.name])
    return out


def apply_undo(undo: list):
    ok = True
    for step in undo or []:
        try:
            if step[0] == "del":
                try:
                    step[1].remove(step[2])
                except DocumentNotFoundException:
                    pass
            elif step[0] == "put":
                step[1].upsert(step[2], step[3])
            elif step[0] == "ledger":
                purge_ledger_events(step[1])
        except Exception:
            ok = False
    return ok


def run_query(qid: str, params: dict, confirm: bool = False, undo: bool = False) -> dict:
    q = CAT[qid]
    if q.kind == "W" and not confirm:
        raise BusinessError("KONFIRMASI_DIPERLUKAN", "query tulis mengubah data uji; kirim confirm=true setelah memahami dampaknya")
    p = normalize(q, params)
    with timing.measure() as t:
        out = q.run(p)
        if q.kind == "W" and out.get("rows") is not None:
            timing.set_rows(len(out["rows"]))
    undo_steps = out.pop("undo", None)
    restored = None
    if undo:
        restored = apply_undo(undo_steps)
    tm = t.as_dict()
    if "ledger_visible_lag_ms" in out:
        tm["ledger_visible_lag_ms"] = out.pop("ledger_visible_lag_ms")
    return {"id": q.id, "params_used": p, "timing": tm, "result": out, "restored": restored}
