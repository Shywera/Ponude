"""Ponude-app — arhiva kalkulacija, usporedba cijena i izrada ponuda.

Prijava + granularne dozvole + audit log (isti pristup kao WMS-app):
  * SessionMiddleware (potpisani httpOnly cookie) drži `user_id`.
  * `auth_audit` middleware: traži prijavu, provjerava dozvolu po putanji, te
    bilježi svaku mutaciju (POST/PUT/DELETE) u `audit_log`.

Pokretanje:  .venv\\Scripts\\uvicorn app.main:app --reload   (ili run.bat / dev-wifi.bat)
"""
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import (FileResponse, PlainTextResponse,
                               RedirectResponse, Response)
from sqlalchemy import func, select
from starlette.middleware.sessions import SessionMiddleware

from app.core.backup import auto_backup, db_putanja
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.modules.arhiva import models  # noqa: F401 — registrira tablice
from app.modules.arhiva.routes import router as arhiva_router
from app.modules.ai import models as ai_models  # noqa: F401 — ai_feedback tablica
from app.modules.auth import models as auth_models  # noqa: F401 — korisnik/audit_log
from app.modules.auth import security as sec
from app.modules.auth.models import AuditLog, User
from app.modules.auth.routes import router as auth_router
from app.modules.auth.routes import templates as auth_templates
from app.modules.ponude import models as ponude_models  # noqa: F401 — registrira tablice
from app.modules.ponude.routes import router as ponude_router
from app.modules.statistika.routes import router as statistika_router

auto_backup()  # backup postojeće baze prije starta
Base.metadata.create_all(bind=engine)

# Dodaj nove stupce na postojeću bazu ako fale (create_all ne mijenja postojeće tablice).
from sqlalchemy import inspect as sa_inspect, text  # noqa: E402


def _dodaj_stupce(tablica: str, stupci: dict[str, str]) -> None:
    postojeci = {c["name"] for c in sa_inspect(engine).get_columns(tablica)}
    with engine.begin() as conn:
        for ime, definicija in stupci.items():
            if ime not in postojeci:
                conn.execute(text(f"ALTER TABLE {tablica} ADD COLUMN {ime} {definicija}"))


_dodaj_stupce("kupac", {
    "u_hrvatskoj": "BOOLEAN DEFAULT 1",
    "adresa": "TEXT", "oib": "TEXT", "kontakt": "TEXT", "np_osoba": "TEXT",
    "jezik": "TEXT",
})
_dodaj_stupce("ponuda", {
    "pdv_obracun": "BOOLEAN DEFAULT 1",
    "pdv_stopa": "FLOAT DEFAULT 25.0",
    "paritet": "TEXT", "potpisnik": "TEXT",
    "jezik": "TEXT", "stil": "TEXT", "status": "TEXT",
})
_dodaj_stupce("ponuda_stavka", {"opis": "TEXT", "exw_1000": "FLOAT",
                                "prijevoz_1000": "FLOAT", "dap_1000": "FLOAT",
                                "alat_cijena": "FLOAT", "tehnika": "TEXT"})
_dodaj_stupce("upit", {"prijevoz_ukupno": "FLOAT"})
_dodaj_stupce("upit_stavka", {"ai_marza_pct": "FLOAT", "ai_obrazlozenje": "TEXT"})
_dodaj_stupce("ai_feedback", {"kontekst": "TEXT"})
_dodaj_stupce("upit_stavka", {"kom_kutija": "FLOAT", "kutija_paleta": "FLOAT",
                              "alat_cijena": "FLOAT", "tehnika": "TEXT"})

# Heuristika za postojeće kupce: strani sufiks -> nije u HR (reverse charge).
_STRANI = ("GMBH", "S.R.O", " SA", "S.A.", " LTD", " AG", " KFT", " SRL")
with engine.begin() as _conn:
    for _id, _naziv, _uhr in _conn.execute(text("SELECT id, naziv, u_hrvatskoj FROM kupac")):
        if _uhr in (None, 1, True) and any(t in _naziv.upper() for t in _STRANI):
            _conn.execute(text("UPDATE kupac SET u_hrvatskoj = 0 WHERE id = :i"), {"i": _id})
    # Postojeće ponude (jednokratno — marker je paritet IS NULL): PDV prema kupcu.
    _conn.execute(text("""
        UPDATE ponuda
           SET pdv_obracun = COALESCE((SELECT k.u_hrvatskoj FROM kupac k
                                       WHERE k.naziv = ponuda.kupac_naziv), 1),
               pdv_stopa   = COALESCE(pdv_stopa, 25.0),
               paritet     = 'FCO adresa Naručitelja'
         WHERE paritet IS NULL"""))
    # jezik/stil za postojeće ponude (jednokratno — samo NULL)
    _conn.execute(text("""UPDATE ponuda SET jezik = CASE WHEN pdv_obracun = 1
                          THEN 'hr' ELSE 'en' END WHERE jezik IS NULL"""))
    _conn.execute(text("UPDATE ponuda SET stil = 'medvedgrad' WHERE stil IS NULL"))
    _conn.execute(text("UPDATE ponuda SET status = 'nacrt' WHERE status IS NULL"))
    # jezik ponuda po kupcu (jednokratno — samo NULL): VAT prefiks pa sufiks tvrtke
    for _id, _naziv, _oib, _uhr, _jez in _conn.execute(text(
            "SELECT id, naziv, oib, u_hrvatskoj, jezik FROM kupac")):
        if _jez:
            continue
        o = (str(_oib or "")).upper().replace(" ", "").replace("-", "").replace(".", "")
        n = (_naziv or "").upper()
        if o.startswith("HR") or (o.isdigit() and len(o) == 11) or _uhr:
            j = "hr"
        elif o.startswith(("ATU", "DE")) or "GMBH" in n or n.endswith(" AG"):
            j = "de"
        elif o.startswith("IT") or n.endswith((" SRL", " SPA", " S.R.L.", " S.P.A.")):
            j = "it"
        else:
            j = "en"
        _conn.execute(text("UPDATE kupac SET jezik = :j WHERE id = :i"),
                      {"j": j, "i": _id})


def _seed_admin() -> None:
    """Ako nema nijednog korisnika, kreiraj početnog admina (lozinka iz ADMIN_PASSWORD)."""
    db = SessionLocal()
    try:
        if (db.scalar(select(func.count(User.id))) or 0) == 0:
            pw = settings.admin_password
            db.add(User(username="admin", ime="Administrator",
                        lozinka_hash=sec.hash_password(pw), dozvole="admin", aktivan=True))
            db.commit()
            print(f"[PONUDE] Kreiran pocetni admin -> korisnik: admin  lozinka: {pw}  "
                  f"(PROMIJENI nakon prve prijave!)")
    finally:
        db.close()


_seed_admin()

app = FastAPI(title="Ponude", docs_url="/api-docs", redoc_url=None)


@app.middleware("http")
async def auth_audit(request: Request, call_next):
    path = request.url.path
    if path in sec.PUBLIC_PATHS or path.startswith("/api-docs"):
        return await call_next(request)

    db = SessionLocal()
    try:
        uid = request.session.get("user_id")
        user = db.get(User, uid) if uid else None
        if user is not None and not user.aktivan:
            user = None
        request.state.user = user

        if user is None:
            if request.headers.get("HX-Request"):
                r = Response(status_code=401)
                r.headers["HX-Redirect"] = "/login"
                return r
            return RedirectResponse("/login", status_code=303)

        needed = sec.required_perm(path)
        if needed and not sec.has_perm(user.dozvole, needed):
            return auth_templates.TemplateResponse(
                request, "auth/403.html",
                {"perm": needed, "opis": sec.PERMISSIONS.get(needed, needed)},
                status_code=403)

        response = await call_next(request)

        if sec.should_audit(request.method, path, response.status_code):
            db.add(AuditLog(user_id=user.id, username=user.username, metoda=request.method,
                            putanja=path, akcija=sec.akcija_label(request.method, path)))
            db.commit()
        return response
    finally:
        db.close()


# SessionMiddleware se dodaje ZADNJI -> vanjski sloj -> postavi request.session
# prije nego auth_audit pokuša čitati prijavu.
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key,
                   same_site="lax", https_only=False)

app.include_router(auth_router)
app.include_router(arhiva_router)
app.include_router(ponude_router)
app.include_router(statistika_router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/arhiva")


@app.get("/backup", include_in_schema=False)
def backup(request: Request):
    """Preuzmi kopiju trenutne baze (dozvola: admin — provjerava middleware)."""
    p = db_putanja()
    if p is None or not p.exists():
        return PlainTextResponse("Baza ne postoji.", status_code=404)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return FileResponse(p, filename=f"{p.stem}_{stamp}{p.suffix}",
                        media_type="application/octet-stream")
