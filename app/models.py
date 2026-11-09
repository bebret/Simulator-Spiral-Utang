"""Model SQLAlchemy: satu tabel pemain, satu tabel ledger append-only."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Account(Base):
    """Akun opsional. Pemain tanpa akun tetap bisa bermain lewat link."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    players: Mapped[list["Player"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", passive_deletes=True
    )


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nickname: Mapped[str] = mapped_column(String(30), nullable=False)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    account: Mapped["Account | None"] = relationship(back_populates="players")

    entries: Mapped[list["LedgerEntry"]] = relationship(
        back_populates="player", cascade="all, delete-orphan", passive_deletes=True
    )


class LedgerEntry(Base):
    """Satu baris = satu kejadian. Tidak pernah di-UPDATE.

    Saldo dan utang TIDAK disimpan di tabel players; keduanya adalah jumlah
    dari cash_delta dan debt_delta di tabel ini.
    """

    __tablename__ = "ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    cash_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    debt_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    player: Mapped["Player"] = relationship(back_populates="entries")
