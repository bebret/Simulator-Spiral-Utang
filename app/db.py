"""Engine dan session SQLAlchemy."""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def ensure_schema() -> None:
    """Buat tabel yang belum ada, lalu lengkapi kolom baru pada tabel lama.

    `create_all` hanya membuat tabel baru; ia tidak menambah kolom ke tabel
    yang sudah ada. Karena itu kolom `account_id` ditambahkan dengan ALTER
    yang idempoten, agar database yang sudah berisi data tidak perlu dihapus.
    """
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE players "
                "ADD COLUMN IF NOT EXISTS account_id INTEGER "
                "REFERENCES accounts(id) ON DELETE CASCADE"
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_players_account_id ON players (account_id)")
        )


def get_db():
    """Dependency FastAPI: satu session per request, selalu ditutup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
