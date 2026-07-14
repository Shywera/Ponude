"""Backup SQLite baze — automatski (na svakom startu) + ručni (/backup download)."""
import shutil
from datetime import datetime
from pathlib import Path

from app.core.config import settings

ZADRZI = 20  # koliko zadnjih auto-backupa zadržati


def db_putanja() -> Path | None:
    """Putanja do SQLite datoteke (None ako nije SQLite)."""
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        return None
    return Path(url[len("sqlite:///"):])


def auto_backup() -> None:
    """Kopiraj postojeću bazu u `backup/<naziv>_YYYYMMDD_HHMMSS.db`; zadrži zadnjih ZADRZI."""
    p = db_putanja()
    if p is None or not p.exists():
        return
    bdir = p.parent / "backup"
    bdir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        shutil.copy2(p, bdir / f"{p.stem}_{stamp}{p.suffix}")
    except Exception:
        return
    stari = sorted(bdir.glob(f"{p.stem}_*{p.suffix}"))
    for f in stari[:-ZADRZI]:
        try:
            f.unlink()
        except Exception:
            pass
