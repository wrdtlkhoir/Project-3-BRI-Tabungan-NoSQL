"""A. Unit test: logika murni (tanpa database)."""
from decimal import Decimal

import pytest

from app.services.transaksi_service import BusinessError, TransaksiService, event_base, to_sen
from app.repositories.cassandra_repository import bulan_of, sen_to_decimal
from datetime import datetime, timezone


def test_to_sen_tanpa_floating_point():
    assert to_sen(Decimal("500000.00")) == 50_000_000
    assert to_sen(Decimal("0.10")) + to_sen(Decimal("0.20")) == to_sen(Decimal("0.30"))   # 0.1+0.2 aman


def test_sen_to_decimal_roundtrip():
    assert sen_to_decimal(15_126_350_916) == Decimal("151263509.16")


def test_event_base_deterministik():
    assert event_base("abc-12345678") == event_base("abc-12345678")
    assert event_base("abc-12345678") != event_base("abc-12345679")


def test_bulan_partisi():
    assert bulan_of(datetime(2026, 11, 24, 23, 59, tzinfo=timezone.utc)) == "202611"


def _doc(**kw):
    d = {"no_rekening": "X", "status_rekening": "AKTIF", "saldo_efektif_sen": 1_000_000, "saldo_tersedia_sen": 1_000_000}
    d.update(kw); return d


def test_apply_setoran():
    d = TransaksiService._apply(_doc(), 500_000, "SETORAN", "2026-11-24T00:00:00.000000Z", False)
    assert d["saldo_efektif_sen"] == 1_500_000 and d["saldo_efektif"] == 15000.0 and d["tx_count"] == 1


def test_apply_penarikan_saldo_kurang():
    with pytest.raises(BusinessError) as e:
        TransaksiService._apply(_doc(), -2_000_000, "PENARIKAN", "t", True)
    assert e.value.code == "SALDO_TIDAK_CUKUP"


def test_apply_rekening_tidak_aktif():
    with pytest.raises(BusinessError) as e:
        TransaksiService._apply(_doc(status_rekening="TERBLOKIR"), 100, "SETORAN", "t", False)
    assert e.value.code == "REKENING_TIDAK_AKTIF"
