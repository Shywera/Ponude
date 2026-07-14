"""Autentikacija i autorizacija — čiste funkcije (bez DB/route ovisnosti).

- Lozinke: bcrypt (nikad plain/SHA).
- Dozvole: granularne, po korisniku (CSV ključeva u `User.dozvole`). `admin` = sve.
- `required_perm(path)` mapira URL na potrebnu dozvolu (koristi middleware).
- Pregled arhive (popis, proizvod, kalkulacija bez raspisa marži) ima svaki
  prijavljeni korisnik; raspis marži u kalkulaciji vidi samo tko ima "ponude".
"""
from __future__ import annotations

import re

# ── Katalog dozvola (ključ -> opis za UI) ───────────────────────────────────────
PERMISSIONS: dict[str, str] = {
    "uvoz":       "Uvoz kalkulacija i uređivanje kupaca",
    "ponude":     "Upiti i ponude (marže, raspis, PDF)",
    "statistika": "Statistika (zarada, marže po kupcima)",
    "admin":      "Administracija (korisnici + log + backup)",
}

# URL prefiks -> potrebna dozvola. Sve ostalo = dovoljna prijava (pregled arhive).
_PERM_MAP: list[tuple[str, str]] = [
    ("/arhiva/uvoz",  "uvoz"),
    ("/arhiva/kupci", "uvoz"),
    ("/upiti",        "ponude"),
    ("/ponude",       "ponude"),
    ("/ai-ponuda",    "ponude"),
    ("/statistika",   "statistika"),
    ("/admin",        "admin"),
    ("/backup",       "admin"),
]

# Putanje dostupne BEZ prijave.
PUBLIC_PATHS = {"/login", "/logout", "/api-docs", "/openapi.json", "/favicon.ico"}


def perms_set(dozvole: str | None) -> set[str]:
    return {p for p in (dozvole or "").split(",") if p}


def has_perm(dozvole: str | None, perm: str) -> bool:
    p = perms_set(dozvole)
    return "admin" in p or perm in p


def required_perm(path: str) -> str | None:
    """Koja je dozvola potrebna za danu putanju (ili None = dovoljna prijava)."""
    for prefix, perm in _PERM_MAP:
        if path == prefix or path.startswith(prefix + "/"):
            return perm
    return None


def should_audit(method: str, path: str, status: int) -> bool:
    return method in ("POST", "PUT", "DELETE", "PATCH") and status < 400


# ── Lozinke (bcrypt) ────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    import bcrypt
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    import bcrypt
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── Audit oznake ────────────────────────────────────────────────────────────────

_AKCIJE: list[tuple[str, str]] = [
    (r"^/login$",                              "Prijava"),
    (r"^/logout$",                             "Odjava"),
    (r"^/arhiva/uvoz$",                        "Uvoz kalkulacija"),
    (r"^/arhiva/kupci/\d+/uredi$",             "Uređivanje kupca"),
    (r"^/arhiva/kalkulacija/\d+/ai$",          "AI objašnjenje razlike"),
    (r"^/upiti/novi$",                         "Novi upit"),
    (r"^/upiti/\d+/stavka$",                   "Dodana stavka u upit"),
    (r"^/upiti/\d+/stavka/\d+/uredi$",         "Promjena marže/količine stavke"),
    (r"^/upiti/\d+/stavka/\d+/obrisi$",        "Brisanje stavke upita"),
    (r"^/upiti/\d+/obrisi$",                   "Brisanje upita"),
    (r"^/upiti/\d+/ponuda$",                   "Generirana ponuda"),
    (r"^/ponude/\d+/tekst$",                   "Uređivanje teksta ponude"),
    (r"^/admin/korisnici$",                    "Kreiranje korisnika"),
    (r"^/admin/korisnici/\d+/uredi$",          "Uređivanje korisnika"),
    (r"^/admin/korisnici/\d+/lozinka$",        "Promjena lozinke"),
    (r"^/admin/korisnici/\d+/obrisi$",         "Brisanje korisnika"),
]


def akcija_label(method: str, path: str) -> str:
    for pat, lbl in _AKCIJE:
        if re.match(pat, path):
            return lbl
    return f"{method} {path}"
