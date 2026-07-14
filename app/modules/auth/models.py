from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    """Korisnik. `dozvole` = CSV ključeva iz `security.PERMISSIONS` (admin = sve)."""
    __tablename__ = "korisnik"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    ime: Mapped[str | None] = mapped_column(String(120))
    lozinka_hash: Mapped[str] = mapped_column(String(200))
    dozvole: Mapped[str] = mapped_column(Text, default="")   # CSV: "uvoz,ponude"
    aktivan: Mapped[bool] = mapped_column(Boolean, default=True)
    # datetime.now (Python, lokalno vrijeme) — NE func.now() jer SQLite tada piše UTC
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)


class AuditLog(Base):
    """Tko je što napravio — bilježi middleware za svaku mutaciju (POST/PUT/DELETE)."""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    username: Mapped[str | None] = mapped_column(String(60))
    metoda: Mapped[str | None] = mapped_column(String(10))
    putanja: Mapped[str | None] = mapped_column(String(300))
    akcija: Mapped[str | None] = mapped_column(String(200))
    detalji: Mapped[str | None] = mapped_column(Text)
