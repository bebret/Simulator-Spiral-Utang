"""Konfigurasi aplikasi, seluruhnya dibaca dari environment variable.

Nilai default di sini sama dengan isi .env.example supaya aplikasi tetap
bisa dijalankan walau ada variabel yang lupa diisi.
"""

import os
from urllib.parse import quote_plus


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


# --- Koneksi database -------------------------------------------------------
POSTGRES_USER = os.getenv("POSTGRES_USER", "appuser")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "change_me")
POSTGRES_DB = os.getenv("POSTGRES_DB", "debtsim")
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = _int("DB_PORT", 5432)

# Host "db" adalah nama service di docker-compose, bukan localhost/IP.
DATABASE_URL = os.getenv("DATABASE_URL") or (
    f"postgresql+psycopg://{quote_plus(POSTGRES_USER)}:{quote_plus(POSTGRES_PASSWORD)}"
    f"@{DB_HOST}:{DB_PORT}/{POSTGRES_DB}"
)

# --- Aturan simulasi (bagian 6 spesifikasi) ---------------------------------
LOAN_ADMIN_FEE_PCT = _float("LOAN_ADMIN_FEE_PCT", 20.0)
DAILY_INTEREST_PCT = _float("DAILY_INTEREST_PCT", 1.0)
MAX_TOTAL_DEBT = _int("MAX_TOTAL_DEBT", 5_000_000)
LOAN_OPTIONS = [
    int(item) for item in os.getenv("LOAN_OPTIONS", "500000,1000000,2000000").split(",") if item.strip()
]
BET_WIN_PROB = _float("BET_WIN_PROB", 0.40)
BET_PAYOUT_MULT = _float("BET_PAYOUT_MULT", 2.0)
MAX_ADVANCE_DAYS = _int("MAX_ADVANCE_DAYS", 30)

# Kunci penandatangan cookie session. Ganti dengan nilai acak di .env.
SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-secret-change-me")
