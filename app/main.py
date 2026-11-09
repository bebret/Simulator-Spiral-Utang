"""Titik masuk FastAPI: endpoint JSON, halaman HTML, dan akun opsional."""

from contextlib import asynccontextmanager
from datetime import timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import auth, config, services
from .db import ensure_schema, get_db
from .models import Account, Player
from .schemas import AdvanceDaysRequest, BetRequest, LoanRequest, PlayerCreate, RepaymentRequest

BASE_DIR = Path(__file__).parent
WIB = timezone(timedelta(hours=7))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Membuat tabel yang belum ada dan melengkapi kolom baru pada tabel lama.
    ensure_schema()
    yield


app = FastAPI(title="Simulator Spiral Utang", lifespan=lifespan)
# Cookie session ditandatangani dengan SECRET_KEY (lihat .env).
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, same_site="lax")
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


def net_result(value) -> str:
    """Hasil taruhan bersih: positif = rugi, negatif = masih untung."""
    value = int(value)
    if value > 0:
        return "Rugi " + rupiah(value)
    if value < 0:
        return "Untung " + rupiah(-value)
    return "Rp0"


templates.env.filters["net_result"] = net_result


def wib_time(value) -> str:
    """Timestamp database (UTC) ditampilkan dalam WIB agar mudah dibaca."""
    return value.astimezone(WIB).strftime("%d/%m %H:%M")


templates.env.filters["wib_time"] = wib_time


# --- Akses simulasi ---------------------------------------------------------
def _is_allowed(request: Request, player: Player) -> bool:
    """Pemain tanpa akun boleh diakses siapa pun yang punya link.

    Pemain yang terikat akun hanya boleh diakses pemiliknya.
    """
    if player.account_id is None:
        return True
    return request.session.get("account_id") == player.account_id


def _require_access(request: Request, player: Player) -> None:
    if not _is_allowed(request, player):
        raise HTTPException(status_code=404, detail="Pemain tidak ditemukan")


def _page_access_redirect(request: Request, player: Player) -> RedirectResponse | None:
    if _is_allowed(request, player):
        return None
    return RedirectResponse(f"/login?next={request.url.path}", status_code=303)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    """Dipakai healthcheck / bukti bahwa aplikasi bisa bicara ke database."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="Database tidak terjangkau")
    return {"status": "ok", "database": "ok"}


# --- Akun (opsional) --------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/my", db: Session = Depends(get_db)):
    if auth.current_account(db, request) is not None:
        return RedirectResponse("/my", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="auth.html",
        context={"mode": "login", "next": auth.safe_next(next), "username": ""},
    )


@app.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/my"),
    db: Session = Depends(get_db),
):
    username = auth.normalize_username(username)
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None or not auth.verify_password(password, account.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="auth.html",
            context={
                "mode": "login",
                "error": "Username atau password salah.",
                "username": username,
                "next": auth.safe_next(next),
            },
            status_code=400,
        )

    request.session["account_id"] = account.id
    request.session["username"] = account.username
    return RedirectResponse(auth.safe_next(next), status_code=303)


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    if auth.current_account(db, request) is not None:
        return RedirectResponse("/my", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="auth.html",
        context={"mode": "register", "next": "/my", "username": ""},
    )


@app.post("/register")
def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    db: Session = Depends(get_db),
):
    username = auth.normalize_username(username)
    error = auth.validate_credentials(username, password)
    if error is None and password != password2:
        error = "Konfirmasi password tidak sama."
    if error is None and db.scalar(select(Account).where(Account.username == username)):
        error = "Username sudah dipakai."

    if error is not None:
        return templates.TemplateResponse(
            request=request,
            name="auth.html",
            context={"mode": "register", "error": error, "username": username, "next": "/my"},
            status_code=400,
        )

    account = Account(username=username, password_hash=auth.hash_password(password))
    db.add(account)
    db.commit()
    db.refresh(account)

    request.session["account_id"] = account.id
    request.session["username"] = account.username
    return RedirectResponse("/my", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/my", response_class=HTMLResponse)
def my_page(request: Request, db: Session = Depends(get_db)):
    account = auth.current_account(db, request)
    if account is None:
        return RedirectResponse("/login?next=/my", status_code=303)

    players = db.scalars(
        select(Player).where(Player.account_id == account.id).order_by(Player.id.desc())
    ).all()
    rows = []
    for player in players:
        cash, debt = services.account_totals(db, player.id)
        rows.append({"player": player, "cash": cash, "debt": debt})

    return templates.TemplateResponse(
        request=request,
        name="my.html",
        context={"account": account, "rows": rows},
    )


# --- Pemain -----------------------------------------------------------------
@app.post("/players", status_code=201)
def create_player(payload: PlayerCreate, request: Request, db: Session = Depends(get_db)):
    account = auth.current_account(db, request)
    player = services.create_player(db, payload.nickname, account_id=account.id if account else None)
    cash, debt = services.account_totals(db, player.id)
    return {
        "id": player.id,
        "nickname": player.nickname,
        "cash": cash,
        "debt": debt,
        "net_worth": cash - debt,
    }


@app.get("/players/{player_id}")
def read_player(player_id: int, request: Request, db: Session = Depends(get_db)):
    player = services.get_player(db, player_id)
    _require_access(request, player)
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
def delete_player(player_id: int, request: Request, db: Session = Depends(get_db)):
    player = services.get_player(db, player_id)
    _require_access(request, player)
    services.reset_player(db, player)
    return Response(status_code=204)


# --- Transaksi --------------------------------------------------------------
@app.post("/players/{player_id}/loans", status_code=201)
def create_loan(
    player_id: int, payload: LoanRequest, request: Request, db: Session = Depends(get_db)
):
    player = services.get_player(db, player_id)
    _require_access(request, player)
    return services.take_loan(db, player, payload.amount)


@app.post("/players/{player_id}/bets", status_code=201)
def create_bet(player_id: int, payload: BetRequest, request: Request, db: Session = Depends(get_db)):
    player = services.get_player(db, player_id)
    _require_access(request, player)
    return services.place_bet(db, player, payload.amount)


@app.post("/players/{player_id}/repayments", status_code=201)
def create_repayment(
    player_id: int, payload: RepaymentRequest, request: Request, db: Session = Depends(get_db)
):
    player = services.get_player(db, player_id)
    _require_access(request, player)
    return services.repay(db, player, payload.amount)


@app.post("/players/{player_id}/advance-days", status_code=201)
def advance_days(
    player_id: int, payload: AdvanceDaysRequest, request: Request, db: Session = Depends(get_db)
):
    player = services.get_player(db, player_id)
    _require_access(request, player)
    return services.advance_days(db, player, payload.days)


# --- Riwayat dan ringkasan --------------------------------------------------
@app.get("/players/{player_id}/ledger")
def read_ledger(player_id: int, request: Request, db: Session = Depends(get_db)):
    player = services.get_player(db, player_id)
    _require_access(request, player)
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
def read_summary(player_id: int, request: Request, db: Session = Depends(get_db)):
    player = services.get_player(db, player_id)
    _require_access(request, player)
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
def index(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "account": auth.current_account(db, request),
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

    redirect = _page_access_redirect(request, player)
    if redirect is not None:
        return redirect

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

    redirect = _page_access_redirect(request, player)
    if redirect is not None:
        return redirect

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
