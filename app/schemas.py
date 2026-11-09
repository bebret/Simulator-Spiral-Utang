"""Skema Pydantic untuk validasi request (error otomatis 422)."""

from pydantic import BaseModel, Field, field_validator

from . import config


class PlayerCreate(BaseModel):
    nickname: str = Field(min_length=1, max_length=30)

    @field_validator("nickname")
    @classmethod
    def tanpa_spasi_berlebih(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Nickname tidak boleh kosong")
        return value


class LoanRequest(BaseModel):
    amount: int = Field(gt=0)


class BetRequest(BaseModel):
    amount: int = Field(gt=0)


class RepaymentRequest(BaseModel):
    amount: int = Field(gt=0)


class AdvanceDaysRequest(BaseModel):
    days: int = Field(gt=0, le=config.MAX_ADVANCE_DAYS)
