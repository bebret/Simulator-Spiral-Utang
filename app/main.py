"""Titik masuk FastAPI: endpoint JSON dan halaman HTML."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import config, services
from .db import Base, engine, get_db
from .schemas import AdvanceDaysRequest, BetRequest, LoanRequest, PlayerCreate, RepaymentRequest


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tabel dibuat saat startup: cukup untuk proyek sekecil ini.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Simulator Spiral Utang", lifespan=lifespan)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    """Dipakai healthcheck / bukti bahwa aplikasi bisa bicara ke database."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="Database tidak terjangkau")
    return {"status": "ok", "database": "ok"}


# --- Pemain -----------------------------------------------------------------
@app.post("/players", status_code=201)
def create_player(payload: PlayerCreate, db: Session = Depends(get_db)):
    player = services.create_player(db, payload.nickname)
    cash, debt = services.account_totals(db, player.id)
    return {
        "id": player.id,
        "nickname": player.nickname,
        "cash": cash,
        "debt": debt,
        "net_worth": cash - debt,
    }


@app.get("/players/{player_id}")
def read_player(player_id: int, db: Session = Depends(get_db)):
    player = services.get_player(db, player_id)
    cash, debt = services.account_totals(db, player_id)
    return {
        "id": player.id,
        "nickname": player.nickname,
        "created_at": player.created_at,
        "cash": cash,
        "debt": debt,
        "net_worth": cash - debt,
    }


@app.delete("/players/{player_id}", status_code=204)
def delete_player(player_id: int, db: Session = Depends(get_db)):
    player = services.get_player(db, player_id)
    services.reset_player(db, player)
    return Response(status_code=204)


# --- Transaksi --------------------------------------------------------------
@app.post("/players/{player_id}/loans", status_code=201)
def create_loan(player_id: int, payload: LoanRequest, db: Session = Depends(get_db)):
    player = services.get_player(db, player_id)
    return services.take_loan(db, player, payload.amount)


@app.post("/players/{player_id}/bets", status_code=201)
def create_bet(player_id: int, payload: BetRequest, db: Session = Depends(get_db)):
    player = services.get_player(db, player_id)
    return services.place_bet(db, player, payload.amount)


@app.post("/players/{player_id}/repayments", status_code=201)
def create_repayment(player_id: int, payload: RepaymentRequest, db: Session = Depends(get_db)):
    player = services.get_player(db, player_id)
    return services.repay(db, player, payload.amount)


@app.post("/players/{player_id}/advance-days", status_code=201)
def advance_days(player_id: int, payload: AdvanceDaysRequest, db: Session = Depends(get_db)):
    player = services.get_player(db, player_id)
    return services.advance_days(db, player, payload.days)


# --- Riwayat dan ringkasan --------------------------------------------------
@app.get("/players/{player_id}/ledger")
def read_ledger(player_id: int, db: Session = Depends(get_db)):
    services.get_player(db, player_id)
    entries = services.get_entries(db, player_id)
    return {
        "entries": [
            {
                "id": entry.id,
                "type": entry.type,
                "cash_delta": entry.cash_delta,
                "debt_delta": entry.debt_delta,
                "note": entry.note,
                "created_at": entry.created_at,
            }
            for entry in entries
        ]
    }


@app.get("/players/{player_id}/summary")
def read_summary(player_id: int, db: Session = Depends(get_db)):
    player = services.get_player(db, player_id)
    return services.summary(db, player)
