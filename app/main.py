"""Titik masuk FastAPI."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import Base, engine, get_db


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
