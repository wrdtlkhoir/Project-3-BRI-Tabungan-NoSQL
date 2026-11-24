from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class _Base(BaseModel):
    nominal: Decimal = Field(..., gt=0, description="Nominal rupiah, maksimal 2 desimal")
    idempotency_key: str = Field(..., min_length=8, max_length=64,
                                 description="Kunci unik dari client. Retry dengan kunci sama tidak menggandakan transaksi")
    id_kanal: str = Field("KNL01", description="KNL01 = BRImo")

    @field_validator("nominal")
    @classmethod
    def _dua_desimal(cls, v: Decimal) -> Decimal:
        if v != v.quantize(Decimal("0.01")):
            raise ValueError("nominal maksimal 2 angka desimal")
        return v


class SetoranRequest(_Base):
    no_rekening: str


class PenarikanRequest(_Base):
    no_rekening: str


class TransferRequest(_Base):
    rekening_sumber: str
    rekening_tujuan: str


class TransaksiResponse(BaseModel):
    event_id: str
    jenis: str
    status: str
    duplicate: bool = False
    saldo_setelah: Optional[Decimal] = None
    ledger_status: str          # PUBLISHED | PENDING
    detail: dict = {}
