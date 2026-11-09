"""Titik masuk FastAPI: endpoint JSON dan halaman HTML."""

from contextlib import asynccontextmanager
from datetime import timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import config, services
from .db import Base, engine, get_db
from .models import Player
from .schemas import AdvanceDaysRequest, BetRequest, LoanRequest, PlayerCreate, RepaymentRequest

BASE_DIR = Path(__file__).parent
WIB = timezone(timedelta(hours=7))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tabel dibuat saat startup: cukup untuk proyek sekecil ini.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Simulator Spiral Utang", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def rupiah(value) -> str:
    value = int(value)
    sign = "−" if value < 0 else ""
    return sign + "Rp" + f"{abs(value):,}".replace(",", ".")


def signed_rupiah(value) -> str:
    value = int(value)
    if value == 0:
        return "—"
    sign = "+" if value > 0 else "−"
    return sign + "Rp" + f"{abs(value):,}".replace(",", ".")


templates.env.filters["rupiah"] = rupiah
templates.env.filters["signed_rupiah"] = signed_rupiah
templates.env.filters["minus"] = lambda value: str(value).replace("-", "−")


def wib_time(value) -> str:
    """Timestamp database (UTC) ditampilkan dalam WIB agar mudah dibaca."""
    return value.astimezone(WIB).strftime("%d/%m %H:%M")


templates.env.filters["wib_time"] = wib_time


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


# --- Halaman HTML -----------------------------------------------------------
def _page_404(player_id: int) -> HTMLResponse:
    return HTMLResponse(
        content=(
            '<!DOCTYPE html><html lang="id"><head><meta charset="utf-8">'
            "<title>Simulasi tidak ditemukan</title>"
            '<link rel="stylesheet" href="/static/style.css"></head><body>'
            '<div class="edu-banner">SIMULASI EDUKASI — TIDAK ADA UANG ASLI.</div>'
            '<main class="narrow"><h1>Simulasi tidak ditemukan</h1>'
            f'<p class="muted">Pemain #{player_id} tidak ada. Mungkin simulasinya sudah direset.</p>'
            '<a class="btn btn-primary" href="/">Buat simulasi baru</a></main></body></html>'
        ),
        status_code=404,
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "admin_fee_pct": config.LOAN_ADMIN_FEE_PCT,
            "win_prob_pct": int(round(config.BET_WIN_PROB * 100)),
            "daily_interest_pct": config.DAILY_INTEREST_PCT,
        },
    )


@app.get("/play/{player_id}", response_class=HTMLResponse)
def play_page(player_id: int, request: Request, db: Session = Depends(get_db)):
    player = db.get(Player, player_id)
    if player is None:
        return _page_404(player_id)

    cash, debt = services.account_totals(db, player_id)
    entries = services.get_entries(db, player_id)
    return templates.TemplateResponse(
        request=request,
        name="play.html",
        context={
            "player": player,
            "cash": cash,
            "debt": debt,
            "bet_loss": services.total_bet_loss(db, player_id),
            "entries": list(reversed(entries))[:20],
            "loan_count": sum(1 for entry in entries if entry.type == "LOAN"),
            "loan_options": sorted(config.LOAN_OPTIONS),
            "bet_chips": [10_000, 50_000, 100_000],
            "symbols": services.SYMBOLS,
            "admin_fee_pct": config.LOAN_ADMIN_FEE_PCT,
            "daily_interest_pct": config.DAILY_INTEREST_PCT,
            "win_prob_pct": int(round(config.BET_WIN_PROB * 100)),
            "payout_mult": config.BET_PAYOUT_MULT,
            "max_advance_days": config.MAX_ADVANCE_DAYS,
            "max_total_debt": config.MAX_TOTAL_DEBT,
        },
    )


@app.get("/play/{player_id}/summary", response_class=HTMLResponse)
def summary_page(player_id: int, request: Request, db: Session = Depends(get_db)):
    player = db.get(Player, player_id)
    if player is None:
        return _page_404(player_id)

    return templates.TemplateResponse(
        request=request,
        name="summary.html",
        context={
            "summary": services.summary(db, player),
            "admin_fee_pct": config.LOAN_ADMIN_FEE_PCT,
            "daily_interest_pct": config.DAILY_INTEREST_PCT,
            "payout_mult": config.BET_PAYOUT_MULT,
        },
    )
