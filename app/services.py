"""Logika bisnis: pinjaman, taruhan, bunga, cicilan, dan ringkasan.

Semua uang adalah integer rupiah. Saldo (cash) dan utang (debt) selalu
dihitung ulang dari tabel ledger, tidak pernah disimpan sebagai kolom.
"""

import secrets

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .models import LedgerEntry, Player

# Simbol netral, tanpa merek atau karakter berhak cipta.
SYMBOLS = ["7", "★", "◆", "●", "▲"]


# --- Helper dasar -----------------------------------------------------------
def get_player(db: Session, player_id: int) -> Player:
    player = db.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Pemain tidak ditemukan")
    return player


def account_totals(db: Session, player_id: int) -> tuple[int, int]:
    cash, debt = db.execute(
        select(
            func.coalesce(func.sum(LedgerEntry.cash_delta), 0),
            func.coalesce(func.sum(LedgerEntry.debt_delta), 0),
        ).where(LedgerEntry.player_id == player_id)
    ).one()
    return int(cash), int(debt)


def add_entry(
    db: Session,
    player_id: int,
    entry_type: str,
    cash_delta: int = 0,
    debt_delta: int = 0,
    note: str | None = None,
) -> None:
    db.add(
        LedgerEntry(
            player_id=player_id,
            type=entry_type,
            cash_delta=cash_delta,
            debt_delta=debt_delta,
            note=note,
        )
    )


def get_entries(db: Session, player_id: int) -> list[LedgerEntry]:
    return list(
        db.scalars(
            select(LedgerEntry)
            .where(LedgerEntry.player_id == player_id)
            .order_by(LedgerEntry.id)
        ).all()
    )


def total_bet_loss(db: Session, player_id: int) -> int:
    """Total taruhan yang dipasang dikurangi total kemenangan."""
    net = db.scalar(
        select(func.coalesce(func.sum(LedgerEntry.cash_delta), 0)).where(
            LedgerEntry.player_id == player_id,
            LedgerEntry.type.in_(["BET", "WIN"]),
        )
    )
    return -int(net)


def loans_taken_while_in_debt(entries: list[LedgerEntry]) -> int:
    """Hitung pinjaman yang diambil saat utang berjalan masih > 0."""
    debt = 0
    count = 0
    for entry in entries:
        if entry.type == "LOAN" and debt > 0:
            count += 1
        debt += entry.debt_delta
    return count


# --- Aksi pemain ------------------------------------------------------------
def create_player(db: Session, nickname: str) -> Player:
    player = Player(nickname=nickname)
    db.add(player)
    db.commit()
    db.refresh(player)
    return player


def take_loan(db: Session, player: Player, amount: int) -> dict:
    if amount not in config.LOAN_OPTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Nominal harus salah satu dari: {config.LOAN_OPTIONS}",
        )

    cash, debt = account_totals(db, player.id)
    if debt + amount > config.MAX_TOTAL_DEBT:
        raise HTTPException(
            status_code=400,
            detail=f"Melebihi batas total utang Rp{config.MAX_TOTAL_DEBT:,}",
        )

    fee = int(round(amount * config.LOAN_ADMIN_FEE_PCT / 100))
    entries = get_entries(db, player.id)
    loans_while_in_debt = loans_taken_while_in_debt(entries) + (1 if debt > 0 else 0)

    # Pokok pinjaman: kas bertambah, utang bertambah.
    add_entry(db, player.id, "LOAN", cash_delta=amount, debt_delta=amount, note="Pinjaman dicairkan")
    # Biaya admin dipotong di depan: kas berkurang, utang tidak berubah.
    add_entry(
        db,
        player.id,
        "FEE",
        cash_delta=-fee,
        note=f"Biaya admin {config.LOAN_ADMIN_FEE_PCT:g}%",
    )
    db.commit()

    new_cash, new_debt = account_totals(db, player.id)
    return {
        "amount": amount,
        "admin_fee": fee,
        "cash_received": amount - fee,
        "cash": new_cash,
        "debt": new_debt,
        "loan_count": len([entry for entry in entries if entry.type == "LOAN"]) + 1,
        "loans_taken_while_in_debt": loans_while_in_debt,
    }


def _spin_reels(won: bool) -> list[str]:
    """Menang: tiga simbol sama. Kalah: acak murni, tidak semuanya sama."""
    if won:
        symbol = secrets.choice(SYMBOLS)
        return [symbol, symbol, symbol]
    while True:
        reels = [secrets.choice(SYMBOLS) for _ in range(3)]
        if len(set(reels)) > 1:
            return reels


def place_bet(db: Session, player: Player, amount: int) -> dict:
    cash, _ = account_totals(db, player.id)
    if amount > cash:
        raise HTTPException(status_code=400, detail="Saldo kas tidak cukup")

    # Hasil ditentukan di server, tidak pernah di browser.
    won = secrets.randbelow(10_000) < int(config.BET_WIN_PROB * 10_000)
    reels = _spin_reels(won)

    add_entry(db, player.id, "BET", cash_delta=-amount, note="Taruhan simulasi")
    payout = 0
    if won:
        payout = int(amount * config.BET_PAYOUT_MULT)
        add_entry(db, player.id, "WIN", cash_delta=payout, note="Kemenangan simulasi")
    db.commit()

    new_cash, new_debt = account_totals(db, player.id)
    return {
        "won": won,
        "reels": reels,
        "amount": amount,
        "payout": payout,
        "net": payout - amount,
        "cash": new_cash,
        "debt": new_debt,
        "session_bet_loss": total_bet_loss(db, player.id),
    }


def repay(db: Session, player: Player, amount: int) -> dict:
    cash, debt = account_totals(db, player.id)
    limit = min(cash, debt)
    if amount > limit:
        raise HTTPException(
            status_code=400,
            detail=f"Nominal melebihi saldo atau utang (maksimal Rp{limit:,})",
        )

    add_entry(db, player.id, "REPAY", cash_delta=-amount, debt_delta=-amount, note="Bayar cicilan")
    db.commit()

    new_cash, new_debt = account_totals(db, player.id)
    return {"amount": amount, "cash": new_cash, "debt": new_debt}


def advance_days(db: Session, player: Player, days: int) -> dict:
    added_interest = 0
    for _ in range(days):
        _, debt = account_totals(db, player.id)
        if debt <= 0:
            break
        interest = int(round(debt * config.DAILY_INTEREST_PCT / 100))
        if interest <= 0:
            break
        add_entry(
            db,
            player.id,
            "INTEREST",
            debt_delta=interest,
            note=f"Bunga {config.DAILY_INTEREST_PCT:g}%/hari",
        )
        added_interest += interest
    db.commit()

    _, new_debt = account_totals(db, player.id)
    return {"days": days, "interest_added": added_interest, "debt": new_debt}


def summary(db: Session, player: Player) -> dict:
    entries = get_entries(db, player.id)
    cash, debt = account_totals(db, player.id)

    series = [{"t": 0, "cash": 0, "debt": 0, "label": "Awal"}]
    running_cash = 0
    running_debt = 0
    for index, entry in enumerate(entries, start=1):
        running_cash += entry.cash_delta
        running_debt += entry.debt_delta
        series.append(
            {"t": index, "cash": running_cash, "debt": running_debt, "label": entry.type}
        )

    total_fees = -sum(entry.cash_delta for entry in entries if entry.type == "FEE")
    total_interest = sum(entry.debt_delta for entry in entries if entry.type == "INTEREST")
    loan_count = sum(1 for entry in entries if entry.type == "LOAN")
    bet_loss = total_bet_loss(db, player.id)

    return {
        "player_id": player.id,
        "nickname": player.nickname,
        "cash": cash,
        "debt": debt,
        "net_worth": cash - debt,
        "total_fees": total_fees,
        "total_interest": total_interest,
        "total_bet_loss": bet_loss,
        "loan_count": loan_count,
        "loans_taken_while_in_debt": loans_taken_while_in_debt(entries),
        "win_probability": config.BET_WIN_PROB,
        "expected_value_per_bet": config.BET_WIN_PROB * config.BET_PAYOUT_MULT - 1,
        "series": series,
    }


def reset_player(db: Session, player: Player) -> None:
    db.delete(player)
    db.commit()
