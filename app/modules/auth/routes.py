from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth import security as sec
from app.modules.auth.models import AuditLog, User

router = APIRouter(tags=["auth"])
from app.core.templating import templates  # zajednicka Jinja okolina


def _zapisi(db: Session, user: User | None, akcija: str, detalji: str | None = None,
            metoda: str = "POST", putanja: str = ""):
    db.add(AuditLog(
        user_id=user.id if user else None, username=user.username if user else None,
        metoda=metoda, putanja=putanja, akcija=akcija, detalji=detalji,
    ))


def _aktivnih_admina(db: Session, osim_id: int | None = None) -> int:
    q = select(User).where(User.aktivan.is_(True))
    return sum(1 for u in db.scalars(q).all()
               if "admin" in sec.perms_set(u.dozvole) and u.id != osim_id)


# ─── Prijava / odjava ─────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/arhiva", status_code=303)
    return templates.TemplateResponse(request, "auth/login.html", {"greska": None})


@router.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(""), lozinka: str = Form(""),
          db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == username.strip()))
    if user is None or not user.aktivan or not sec.verify_password(lozinka, user.lozinka_hash):
        return templates.TemplateResponse(
            request, "auth/login.html",
            {"greska": "Pogrešno korisničko ime ili lozinka (ili je račun isključen)."},
            status_code=401,
        )
    request.session["user_id"] = user.id
    user.last_login = datetime.now()
    _zapisi(db, user, "Prijava", metoda="POST", putanja="/login")
    db.commit()
    return RedirectResponse("/arhiva", status_code=303)


@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    uid = request.session.get("user_id")
    if uid:
        u = db.get(User, uid)
        _zapisi(db, u, "Odjava", metoda="GET", putanja="/logout")
        db.commit()
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ─── Admin: korisnici ─────────────────────────────────────────────────────────

@router.get("/admin", response_class=HTMLResponse)
def admin_home():
    return RedirectResponse("/admin/korisnici", status_code=303)


@router.get("/admin/korisnici", response_class=HTMLResponse)
def korisnici(request: Request, db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.username)).all()
    return templates.TemplateResponse(request, "auth/korisnici.html", {
        "users": users, "permissions": sec.PERMISSIONS, "perms_set": sec.perms_set,
    })


@router.post("/admin/korisnici", response_class=RedirectResponse)
def korisnik_novi(request: Request, username: str = Form(""), ime: str = Form(""),
                  lozinka: str = Form(""), dozvole: list[str] = Form(default=[]),
                  db: Session = Depends(get_db)):
    username = username.strip()
    if not username or not lozinka:
        return RedirectResponse("/admin/korisnici?greska=Ime+i+lozinka+su+obavezni", status_code=303)
    if db.scalar(select(User).where(User.username == username)):
        return RedirectResponse("/admin/korisnici?greska=Korisnik+vec+postoji", status_code=303)
    valjane = [d for d in dozvole if d in sec.PERMISSIONS]
    db.add(User(username=username, ime=ime.strip() or None,
                lozinka_hash=sec.hash_password(lozinka),
                dozvole=",".join(valjane), aktivan=True))
    db.commit()
    return RedirectResponse("/admin/korisnici", status_code=303)


@router.post("/admin/korisnici/{uid}/uredi", response_class=RedirectResponse)
def korisnik_uredi(request: Request, uid: int, ime: str = Form(""),
                   dozvole: list[str] = Form(default=[]), aktivan: str = Form(""),
                   db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if u is None:
        return RedirectResponse("/admin/korisnici", status_code=303)
    valjane = [d for d in dozvole if d in sec.PERMISSIONS]
    bit_ce_aktivan = aktivan == "on"
    gubi_admin = "admin" not in valjane or not bit_ce_aktivan
    if gubi_admin and "admin" in sec.perms_set(u.dozvole) and u.aktivan \
            and _aktivnih_admina(db, osim_id=u.id) == 0:
        return RedirectResponse(
            "/admin/korisnici?greska=Mora+postojati+barem+jedan+aktivan+admin", status_code=303)
    u.ime = ime.strip() or None
    u.dozvole = ",".join(valjane)
    u.aktivan = bit_ce_aktivan
    db.commit()
    return RedirectResponse("/admin/korisnici", status_code=303)


@router.post("/admin/korisnici/{uid}/lozinka", response_class=RedirectResponse)
def korisnik_lozinka(uid: int, lozinka: str = Form(""), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if u and lozinka.strip():
        u.lozinka_hash = sec.hash_password(lozinka)
        db.commit()
    return RedirectResponse("/admin/korisnici", status_code=303)


@router.post("/admin/korisnici/{uid}/obrisi", response_class=RedirectResponse)
def korisnik_obrisi(request: Request, uid: int, db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if u is None:
        return RedirectResponse("/admin/korisnici", status_code=303)
    ja = request.state.user
    if ja and ja.id == u.id:
        return RedirectResponse("/admin/korisnici?greska=Ne+mozes+obrisati+sebe", status_code=303)
    if "admin" in sec.perms_set(u.dozvole) and u.aktivan and _aktivnih_admina(db, osim_id=u.id) == 0:
        return RedirectResponse(
            "/admin/korisnici?greska=Mora+postojati+barem+jedan+aktivan+admin", status_code=303)
    db.delete(u)
    db.commit()
    return RedirectResponse("/admin/korisnici", status_code=303)


# ─── Admin: audit log ─────────────────────────────────────────────────────────

@router.get("/admin/log", response_class=HTMLResponse)
def audit_log(request: Request, stranica: int = 1, db: Session = Depends(get_db)):
    po_str = 50
    stranica = max(1, stranica)
    ukupno = db.scalar(select(func.count(AuditLog.id))) or 0
    redovi = db.scalars(
        select(AuditLog).order_by(AuditLog.timestamp.desc())
        .offset((stranica - 1) * po_str).limit(po_str)
    ).all()
    return templates.TemplateResponse(request, "auth/log.html", {
        "redovi": redovi, "stranica": stranica, "ukupno": ukupno,
        "ima_jos": stranica * po_str < ukupno,
    })
