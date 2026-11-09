"""Akun opsional: hashing password, validasi, dan bantuan session."""

import hashlib
import hmac
import re
import secrets

from sqlalchemy.orm import Session
from starlette.requests import Request

from .models import Account

# Parameter scrypt (murah untuk demo, tetap jauh lebih baik daripada plaintext).
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LENGTH = 32

USERNAME_PATTERN = re.compile(r"^[a-z0-9_]{3,30}$")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=KEY_LENGTH,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, digest_hex = stored.split("$")
        if algo != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(digest, expected)


def normalize_username(value: str) -> str:
    return value.strip().lower()


def validate_credentials(username: str, password: str) -> str | None:
    """Mengembalikan pesan error, atau None bila valid."""
    if not USERNAME_PATTERN.match(username):
        return "Username 3-30 karakter: huruf kecil, angka, dan garis bawah."
    if len(password) < 8:
        return "Password minimal 8 karakter."
    if len(password) > 128:
        return "Password maksimal 128 karakter."
    return None


def current_account(db: Session, request: Request) -> Account | None:
    account_id = request.session.get("account_id")
    if not isinstance(account_id, int):
        return None
    return db.get(Account, account_id)


def safe_next(value: str | None) -> str:
    """Hanya izinkan redirect ke path lokal, bukan URL luar."""
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/my"
