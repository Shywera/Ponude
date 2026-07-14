"""Rute upita i ponuda: unos upita, stavke s maržama, generiranje ponude + PDF."""
from datetime import date

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.arhiva import models as am
from app.modules.ponude import models as pm
from app.modules.ponude import pdf as pdfgen

router = APIRouter(tags=["ponude"])
from app.core.templating import templates  # zajednicka Jinja okolina


def _zadnja_kalkulacija(p: am.Proizvod) -> am.Kalkulacija | None:
    if not p.kalkulacije:
        return None
    return max(p.kalkulacije, key=lambda k: (k.datum or date.min, k.id))


# ------------------------------------------------------------------- UPITI

@router.get("/upiti")
def upiti(request: Request, db: Session = Depends(get_db)):
    lista = db.scalars(select(pm.Upit).order_by(pm.Upit.id.desc())).all()
    kupci = db.scalars(select(am.Kupac).order_by(am.Kupac.naziv)).all()
    return templates.TemplateResponse(request, "ponude/upiti.html",
                                      {"upiti": lista, "kupci": kupci})


@router.post("/upiti/novi")
def novi_upit(kupac_id: int = Form(...), naslov: str = Form(...),
              db: Session = Depends(get_db)):
    u = pm.Upit(kupac_id=kupac_id, naslov=naslov.strip() or "Upit")
    db.add(u)
    db.commit()
    return RedirectResponse(f"/upiti/{u.id}", status_code=303)


def _upit_ctx(request: Request, db: Session, u: pm.Upit) -> dict:
    from app.modules.arhiva.routes import raspon_marzi
    from app.modules.ponude import radna

    vec_u_upitu = {s.proizvod_id for s in u.stavke}
    proizvodi = [p for p in db.scalars(
        select(am.Proizvod).where(am.Proizvod.kupac_id == u.kupac_id)).all()
        if p.id not in vec_u_upitu and p.kalkulacije]
    proizvodi.sort(key=lambda p: p.naziv)
    od, do, korak = raspon_marzi(request)
    return {
        "u": u, "proizvodi": proizvodi,
        "ukupno_ck": sum(s.ck_total for s in u.stavke),
        "ukupno_prodajna": sum(s.prodajna_ukupno for s in u.stavke),
        "marza_opcije": list(range(od, do + 1, korak)),
        "od": od, "do": do, "korak": korak,
        "log": radna.logistika(u),
        "ima_logistike": any(s.kom_kutija for s in u.stavke) or bool(u.prijevoz_ukupno),
    }


@router.get("/upiti/{uid}")
def upit(uid: int, request: Request, db: Session = Depends(get_db)):
    u = db.get(pm.Upit, uid)
    if u is None:
        return RedirectResponse("/upiti", status_code=303)
    return templates.TemplateResponse(request, "ponude/upit.html",
                                      _upit_ctx(request, db, u))


@router.post("/upiti/{uid}/radna")
async def uvoz_radne(uid: int, request: Request, datoteka: UploadFile,
                     db: Session = Depends(get_db)):
    """Uvezi stavke iz radne tablice (format kupca) u upit."""
    import os
    import tempfile

    from app.modules.ponude import radna

    u = db.get(pm.Upit, uid)
    if u is None:
        return RedirectResponse("/upiti", status_code=303)
    try:
        sadrzaj = await datoteka.read()
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(sadrzaj)
            put = tmp.name
        try:
            redovi = radna.parsiraj_radnu(put)
            rezultat = radna.uvezi_u_upit(db, u, redovi)
        finally:
            os.unlink(put)
    except Exception as e:
        db.rollback()
        rezultat = [{"oznaka": datoteka.filename or "?", "status": "greska",
                     "poruka": str(e)}]
    ctx = _upit_ctx(request, db, u)
    ctx["radna_rezultat"] = rezultat
    return templates.TemplateResponse(request, "ponude/upit.html", ctx)


@router.post("/upiti/{uid}/prijevoz")
def spremi_prijevoz(uid: int, prijevoz_ukupno: str = Form(""),
                    db: Session = Depends(get_db)):
    u = db.get(pm.Upit, uid)
    if u is not None:
        try:
            u.prijevoz_ukupno = float(prijevoz_ukupno.replace(",", ".")) or None
        except ValueError:
            u.prijevoz_ukupno = None
        db.commit()
    return RedirectResponse(f"/upiti/{uid}", status_code=303)


@router.post("/upiti/{uid}/stavka/{sid}/logistika")
def uredi_logistiku(uid: int, sid: int, kom_kutija: str = Form(""),
                    kutija_paleta: str = Form(""), alat_cijena: str = Form(""),
                    db: Session = Depends(get_db)):
    s = db.get(pm.UpitStavka, sid)
    if s is not None and s.upit_id == uid:
        def _f(x):
            try:
                return float(x.replace(",", ".")) or None
            except ValueError:
                return None
        s.kom_kutija = _f(kom_kutija)
        s.kutija_paleta = _f(kutija_paleta)
        s.alat_cijena = _f(alat_cijena)
        db.commit()
    return RedirectResponse(f"/upiti/{uid}", status_code=303)


@router.post("/upiti/{uid}/stavka")
def dodaj_stavku(uid: int, proizvod_id: int = Form(...),
                 db: Session = Depends(get_db)):
    u = db.get(pm.Upit, uid)
    p = db.get(am.Proizvod, proizvod_id)
    if u is None or p is None:
        return RedirectResponse(f"/upiti/{uid}", status_code=303)
    k = _zadnja_kalkulacija(p)
    if k is None:
        return RedirectResponse(f"/upiti/{uid}", status_code=303)
    db.add(pm.UpitStavka(upit_id=u.id, proizvod_id=p.id, kalkulacija_id=k.id,
                         kolicina=k.serija, marza_pct=30.0))
    db.commit()
    return RedirectResponse(f"/upiti/{uid}", status_code=303)


@router.post("/upiti/{uid}/stavka/{sid}/uredi")
def uredi_stavku(uid: int, sid: int, request: Request,
                 marza_pct: float = Form(...),
                 kolicina: float | None = Form(None),
                 db: Session = Depends(get_db)):
    s = db.get(pm.UpitStavka, sid)
    if s is not None and s.upit_id == uid:
        nova = max(0.0, marza_pct)
        # direktor postavio drugačije od AI prijedloga -> zapamti kao korekciju
        if s.ai_marza_pct is not None and abs(nova - s.ai_marza_pct) > 0.01:
            import json as _json
            _fb(db, request, tip="marza",
                kupac_naziv=s.upit.kupac.naziv if s.upit and s.upit.kupac else None,
                proizvod_naziv=s.proizvod.naziv if s.proizvod else None,
                prijedlog=f"{s.ai_marza_pct:g} % — {s.ai_obrazlozenje or ''}",
                kontekst=_json.dumps(_stavka_kontekst(s, _ck_delta(db, s)), ensure_ascii=False),
                ocjena="korigirano", korekcija=f"{nova:g}", komentar=None)
        s.marza_pct = nova
        if kolicina:
            s.kolicina = kolicina
        db.commit()
    return RedirectResponse(f"/upiti/{uid}", status_code=303)


@router.post("/upiti/{uid}/stavka/{sid}/obrisi")
def obrisi_stavku(uid: int, sid: int, db: Session = Depends(get_db)):
    s = db.get(pm.UpitStavka, sid)
    if s is not None and s.upit_id == uid:
        db.delete(s)
        db.commit()
    return RedirectResponse(f"/upiti/{uid}", status_code=303)


@router.post("/upiti/{uid}/obrisi")
def obrisi_upit(uid: int, db: Session = Depends(get_db)):
    u = db.get(pm.Upit, uid)
    if u is not None and not u.ponude:
        db.delete(u)
        db.commit()
    return RedirectResponse("/upiti", status_code=303)


# ─── AI prijedlog marže + učenje iz direktorovih odluka ──────────────────────

def _fb(db: Session, request: Request, **kw):
    """Zapiši direktorovu odluku o AI prijedlogu (baza za buduće prijedloge)."""
    from app.modules.ai.models import AIFeedback
    u = getattr(request.state, "user", None)
    db.add(AIFeedback(username=u.username if u else None, **kw))


def _stavka_kontekst(s: pm.UpitStavka, ck_delta_pct=None) -> dict:
    """Kontekst u kojem je odluka o marži donesena — sprema se uz svaki feedback
    da AI kasnije može usporediti tadašnju i sadašnju situaciju (serija, trošak...)."""
    kol = s.kolicina or (s.kalkulacija.serija if s.kalkulacija else None)
    return {"serija_tisuca": kol,
            "ck_total": s.ck_total,
            "ck_po_1000": round(s.ck_total / kol, 4) if kol else None,
            "ck_delta_pct": ck_delta_pct,
            "datum_kalkulacije": str(s.kalkulacija.datum) if s.kalkulacija else None}


def _ck_delta(db: Session, s: pm.UpitStavka):
    from app.modules.arhiva import service as arh_service
    if not s.kalkulacija:
        return None
    pret = arh_service.prethodna_kalkulacija(db, s.kalkulacija)
    if pret is None:
        return None
    return (arh_service.usporedi(s.kalkulacija, pret).get("ck_total") or {}).get("delta_pct")


def _marza_ctx(db: Session, s: pm.UpitStavka):
    """Sve što AI treba za prijedlog: trenutna situacija + povijest S KONTEKSTOM.
    Marža nije statična — ista etiketa na 2.000 i na 10.000 tisuća nema istu maržu,
    pa svaka povijesna odluka nosi serију i trošak/1000 iz svog vremena."""
    import json as _json

    from app.modules.ai.models import AIFeedback

    naziv = s.proizvod.naziv if s.proizvod else "?"
    kupac = s.upit.kupac.naziv if s.upit and s.upit.kupac else "?"
    delta = _ck_delta(db, s)
    kol = s.kolicina or (s.kalkulacija.serija if s.kalkulacija else None)

    # korištene marže iz svih ponuda tog kupca — s kontekstom (serija, trošak/1000)
    povijest = []
    for ps in db.scalars(
            select(pm.PonudaStavka).join(pm.Ponuda)
            .where(pm.Ponuda.kupac_naziv == kupac,
                   pm.PonudaStavka.marza_pct.is_not(None))
            .order_by(pm.Ponuda.datum.desc(), pm.PonudaStavka.id.desc())
            .limit(15)).all():
        povijest.append({
            "datum": str(ps.ponuda.datum) if ps.ponuda else None,
            "proizvod": ps.naziv, "isti_proizvod": ps.naziv == naziv,
            "marza": ps.marza_pct, "serija_tisuca": ps.kolicina,
            "ck_po_1000": round((ps.ck_total or 0) / ps.kolicina, 4)
                          if (ps.ck_total and ps.kolicina) else None,
            "ishod_ponude": ps.ponuda.status if ps.ponuda else None})

    # direktorove odluke o AI prijedlozima — s kontekstom iz trenutka odluke
    odluke = []
    for fb in db.scalars(
            select(AIFeedback)
            .where(AIFeedback.tip == "marza",
                   (AIFeedback.proizvod_naziv == naziv) | (AIFeedback.kupac_naziv == kupac))
            .order_by(AIFeedback.id.desc()).limit(15)).all():
        marza = None
        if fb.ocjena == "korigirano" and fb.korekcija:
            try:
                marza = float(fb.korekcija)
            except ValueError:
                pass
        elif fb.ocjena == "dobro" and fb.prijedlog:
            try:
                marza = float(fb.prijedlog.split("%")[0].strip().replace(",", "."))
            except ValueError:
                pass
        odluke.append({
            "datum": fb.created.strftime("%d.%m.%Y."),
            "proizvod": fb.proizvod_naziv, "isti_proizvod": fb.proizvod_naziv == naziv,
            "ai_prijedlog": fb.prijedlog, "ocjena": fb.ocjena,
            "direktor_marza": marza, "komentar": fb.komentar,
            "kontekst": _json.loads(fb.kontekst) if fb.kontekst else {}})

    ctx = {"kupac": kupac, "proizvod": naziv,
           "trenutno": {"serija_tisuca": kol, "ck_total": s.ck_total,
                        "ck_po_1000": round(s.ck_total / kol, 4) if kol else None,
                        "ck_delta_pct": delta},
           "povijest_prodaja": povijest,
           "odluke": odluke}
    return ctx, odluke


@router.post("/upiti/{uid}/ai-marze")
def ai_predlozi_marze(uid: int, request: Request, db: Session = Depends(get_db)):
    """AI predloži maržu za svaku stavku upita (direktor potvrđuje ili ispravlja)."""
    from app.modules.ai import claude as ai

    u = db.get(pm.Upit, uid)
    if u is None:
        return RedirectResponse("/upiti", status_code=303)
    for s in u.stavke:
        ctx, primjeri = _marza_ctx(db, s)
        p = ai.predlozi_marzu(ctx, primjeri)
        s.ai_marza_pct = p.marza_pct
        s.ai_obrazlozenje = p.obrazlozenje
    db.commit()
    return RedirectResponse(f"/upiti/{uid}", status_code=303)


@router.post("/upiti/{uid}/stavka/{sid}/ai-prihvati")
def ai_prihvati_marzu(uid: int, sid: int, request: Request,
                      db: Session = Depends(get_db)):
    """Kvačica: direktor prihvaća AI prijedlog — postavlja maržu i uči sustav."""
    s = db.get(pm.UpitStavka, sid)
    if s is not None and s.upit_id == uid and s.ai_marza_pct is not None:
        import json as _json
        s.marza_pct = s.ai_marza_pct
        _fb(db, request, tip="marza",
            kupac_naziv=s.upit.kupac.naziv if s.upit and s.upit.kupac else None,
            proizvod_naziv=s.proizvod.naziv if s.proizvod else None,
            prijedlog=f"{s.ai_marza_pct:g} % — {s.ai_obrazlozenje or ''}",
            kontekst=_json.dumps(_stavka_kontekst(s, _ck_delta(db, s)), ensure_ascii=False),
            ocjena="dobro", korekcija=None, komentar=None)
        db.commit()
    return RedirectResponse(f"/upiti/{uid}", status_code=303)


# ------------------------------------------------------------------ PONUDE

def _novi_broj_ponude(db: Session) -> str:
    """Broj u formatu NN-GGGG (kao "02-2026") — redni broj u godini."""
    god = date.today().year
    n = db.scalar(select(func.count(pm.Ponuda.id))
                  .where(pm.Ponuda.datum >= date(god, 1, 1))) or 0
    return f"{n + 1:02d}-{god}"


def _opis_stavke(k) -> str | None:
    """Format artikla za ponudu, npr. "format: 9,9 x 6,4 cm" (iz kalkulacije)."""
    if k is None or not k.artikli:
        return None
    dims = {(a.sirina_mm, a.visina_mm) for a in k.artikli
            if a.sirina_mm and a.visina_mm}
    if not dims:
        return None
    if len(dims) == 1:
        s, v = dims.pop()
        return f"format: {s / 10:g} x {v / 10:g} cm".replace(".", ",")
    return f"{len(dims)} formata"


@router.post("/upiti/{uid}/ponuda")
def generiraj_ponudu(uid: int, stil: str = Form("medvedgrad"),
                     db: Session = Depends(get_db)):
    """Zamrzni trenutne stavke upita u ponudu (snapshot); PDV prema kupcu."""
    u = db.get(pm.Upit, uid)
    if u is None or not u.stavke:
        return RedirectResponse(f"/upiti/{uid}", status_code=303)
    ponuda = _generiraj(db, u, stil)
    db.commit()
    return RedirectResponse(f"/ponude/{ponuda.id}", status_code=303)


def _generiraj(db: Session, u: pm.Upit, stil: str) -> pm.Ponuda:
    """Snapshot upita u ponudu. stil=medvedgrad (PDF) | excel (DAP/xlsx)."""
    from app.modules.ponude import radna

    u_hr = bool(u.kupac.u_hrvatskoj)
    stil = stil if stil in ("medvedgrad", "excel") else "medvedgrad"
    log = radna.logistika(u)
    ima_prijevoza = log["po_paleti"] is not None

    ponuda = pm.Ponuda(upit_id=u.id, broj=_novi_broj_ponude(db),
                       kupac_naziv=u.kupac.naziv,
                       pdv_obracun=u_hr, pdv_stopa=25.0, stil=stil,
                       paritet=("DAP" if (stil == "excel" and ima_prijevoza)
                                else ("EXW" if stil == "excel"
                                      else "FCO adresa Naručitelja")))
    db.add(ponuda)
    db.flush()

    for s in u.stavke:
        d = log["po_stavci"].get(s.id, {})
        dap = d.get("dap_1000")
        if stil == "excel":
            jed = dap if (ima_prijevoza and dap is not None) else s.exw_1000
        else:
            jed = s.prodajna_po_jedinici
        kol = s.kolicina or (s.kalkulacija.serija if s.kalkulacija else None)
        db.add(pm.PonudaStavka(
            ponuda_id=ponuda.id,
            kalkulacija_broj=s.kalkulacija.broj if s.kalkulacija else None,
            naziv=s.proizvod.naziv if s.proizvod else "?",
            opis=_opis_stavke(s.kalkulacija),
            kolicina=kol,
            jedinica=(s.kalkulacija.serija_jedinica if s.kalkulacija else None),
            jed_cijena=jed,
            iznos=round((kol or 0) * (jed or 0), 2) if stil == "excel"
                  else s.prodajna_ukupno,
            marza_pct=s.marza_pct,
            ck_total=s.ck_total,
            exw_1000=s.exw_1000,
            prijevoz_1000=d.get("prijevoz_1000"),
            dap_1000=dap,
            alat_cijena=s.alat_cijena,
            tehnika=s.tehnika,
        ))

    # Jezik ponude: iz šifrarnika kupca (auto-prepoznat iz VAT-a, uredivo),
    # rezerva: HR kupac -> hrvatski, strani -> engleski.
    ponuda.jezik = (u.kupac.jezik if u.kupac.jezik in pdfgen.INTRO
                    else ("hr" if u_hr else "en"))
    ponuda.uvodni_tekst = pdfgen.INTRO[ponuda.jezik]
    u.status = "ponuda"
    return ponuda


@router.get("/ponude")
def ponude(request: Request, db: Session = Depends(get_db)):
    lista = db.scalars(select(pm.Ponuda).order_by(pm.Ponuda.id.desc())).all()
    return templates.TemplateResponse(request, "ponude/ponude.html", {"ponude": lista})


@router.get("/ponude/{pid}")
def ponuda(pid: int, request: Request, db: Session = Depends(get_db)):
    p = db.get(pm.Ponuda, pid)
    if p is None:
        return RedirectResponse("/ponude", status_code=303)
    # rastavi paritet na incoterm + mjesto za formu
    par_sel, par_mjesto = "", p.paritet or ""
    for opt in pdfgen.PARITETI:
        if par_mjesto == opt or par_mjesto.startswith(opt + " "):
            par_sel, par_mjesto = opt, par_mjesto[len(opt):].strip()
            break
    return templates.TemplateResponse(request, "ponude/ponuda.html", {
        "p": p, "pariteti": pdfgen.PARITETI,
        "par_sel": par_sel, "par_mjesto": par_mjesto,
    })


@router.post("/ponude/{pid}/tekst")
def uredi_tekst(pid: int, uvodni_tekst: str = Form(""), napomene: str = Form(""),
                paritet: str = Form(""), paritet_mjesto: str = Form(""),
                potpisnik: str = Form(""), pdv_obracun: str = Form(""),
                jezik: str = Form("hr"), db: Session = Depends(get_db)):
    p = db.get(pm.Ponuda, pid)
    if p is not None:
        novi_uvod = uvodni_tekst.strip() or None
        if jezik in pdfgen.INTRO and jezik != p.jezik:
            p.jezik = jezik
            # ako je uvodni tekst standardan (nije ručno mijenjan), prevedi ga
            if novi_uvod in pdfgen.INTRO_SVI or novi_uvod is None:
                novi_uvod = pdfgen.INTRO[jezik]
        p.uvodni_tekst = novi_uvod
        p.napomene = napomene.strip() or None
        p.paritet = f"{paritet.strip()} {paritet_mjesto.strip()}".strip() or None
        p.potpisnik = potpisnik.strip() or None
        p.pdv_obracun = pdv_obracun == "1"
        db.commit()
    return RedirectResponse(f"/ponude/{pid}", status_code=303)


@router.post("/ponude/{pid}/status")
def ponuda_status(pid: int, status: str = Form(""), db: Session = Depends(get_db)):
    """Ishod ponude — signal iz kojeg AI uči koje marže prolaze kod kupca."""
    p = db.get(pm.Ponuda, pid)
    if p is not None and status in ("nacrt", "za_slanje", "poslana",
                                    "prihvacena", "odbijena"):
        p.status = status
        db.commit()
    return RedirectResponse(f"/ponude/{pid}", status_code=303)


@router.get("/ponude/{pid}/xlsx")
def ponuda_xlsx(pid: int, db: Session = Depends(get_db)):
    from app.modules.ponude import xlsx as xlsxgen
    p = db.get(pm.Ponuda, pid)
    if p is None:
        return RedirectResponse("/ponude", status_code=303)
    buf = xlsxgen.xlsx_ponuda(p)
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="Offer_{p.broj}.xlsx"'})


@router.get("/ponude/{pid}/pdf")
def ponuda_pdf(pid: int, db: Session = Depends(get_db)):
    p = db.get(pm.Ponuda, pid)
    if p is None:
        return RedirectResponse("/ponude", status_code=303)
    buf = pdfgen.pdf_ponuda(p)
    return StreamingResponse(buf, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="Ponuda_{p.broj}.pdf"'})


# ═══ AI PONUDA (testna stranica): upišeš upit — AI napravi SVE, direktor
#     OBAVEZNO pregleda svaku odluku (prihvati/odbij + napomena) ═══════════════

@router.get("/ai-ponuda")
def ai_ponuda_forma(request: Request, db: Session = Depends(get_db)):
    kupci = db.scalars(select(am.Kupac).order_by(am.Kupac.naziv)).all()
    proizvodi = []
    for p in db.scalars(select(am.Proizvod)).all():
        if p.kalkulacije:
            k = _zadnja_kalkulacija(p)
            proizvodi.append({"id": p.id, "kupac_id": p.kupac_id,
                              "naziv": p.naziv, "serija": k.serija if k else None})
    return templates.TemplateResponse(request, "aiponuda/forma.html", {
        "kupci": kupci, "proizvodi": proizvodi,
    })


@router.post("/ai-ponuda")
async def ai_ponuda_kreiraj(request: Request, db: Session = Depends(get_db)):
    """AI napravi SVE: upit, stavke, marže (s obrazloženjima), pregled problema,
    tekst, ponudu — pa OBAVEZAN direktorov pregled prije slanja."""
    from app.modules.ai import claude as ai
    from app.modules.ai.models import AINapomena
    from app.modules.arhiva.routes import _ai_pregled

    form = await request.form()
    try:
        kupac_id = int(form.get("kupac_id") or 0)
    except ValueError:
        kupac_id = 0
    kupac = db.get(am.Kupac, kupac_id)
    ids = form.getlist("proizvod_id")
    if kupac is None or not ids:
        return RedirectResponse("/ai-ponuda", status_code=303)

    naslov = (form.get("naslov") or "").strip() or \
        f"AI ponuda {date.today().strftime('%d.%m.%Y.')}"
    stil = form.get("stil") if form.get("stil") in ("medvedgrad", "excel") else "medvedgrad"

    u = pm.Upit(kupac_id=kupac.id, naslov=naslov)
    db.add(u)
    db.flush()
    for pid in ids:
        try:
            p = db.get(am.Proizvod, int(pid))
        except ValueError:
            continue
        if p is None:
            continue
        k = _zadnja_kalkulacija(p)
        if k is None:
            continue
        kol = None
        try:
            kol = float(str(form.get(f"kolicina_{pid}") or "").replace(",", ".")) or None
        except ValueError:
            pass
        db.add(pm.UpitStavka(upit_id=u.id, proizvod_id=p.id, kalkulacija_id=k.id,
                             kolicina=kol or k.serija, marza_pct=30.0))
    db.flush()
    db.refresh(u)
    if not u.stavke:
        db.rollback()
        return RedirectResponse("/ai-ponuda", status_code=303)

    # 1) AI marže — predloži I primijeni (direktor će svaku potvrditi/ispraviti)
    for s in u.stavke:
        ctx, _ = _marza_ctx(db, s)
        pr = ai.predlozi_marzu(ctx, [])
        s.ai_marza_pct = pr.marza_pct
        s.ai_obrazlozenje = pr.obrazlozenje
        s.marza_pct = pr.marza_pct

    # 2) AI pregled problema na kalkulacijama (ako već nije napravljen)
    for s in u.stavke:
        if not db.scalars(select(AINapomena).where(
                AINapomena.kalkulacija_id == s.kalkulacija_id)).first():
            _ai_pregled(db, s.kalkulacija)

    # 3) ponuda (uvodni tekst po jeziku ide u _generiraj)
    ponuda = _generiraj(db, u, stil)
    ponuda.status = "ai_nacrt"   # obavezan pregled prije slanja
    db.commit()
    return RedirectResponse(f"/ai-ponuda/{ponuda.id}/pregled", status_code=303)


def _ai_pregled_ctx(db: Session, p: pm.Ponuda) -> dict:
    from app.modules.ai.models import AINapomena
    u = p.upit
    parovi = list(zip(p.stavke, u.stavke)) if u else []
    kalk_ids = [s.kalkulacija_id for s in (u.stavke if u else [])]
    problemi = db.scalars(select(AINapomena).where(
        AINapomena.kalkulacija_id.in_(kalk_ids),
        AINapomena.status == "nova")).all() if kalk_ids else []
    return {"p": p, "u": u, "parovi": parovi, "problemi": problemi}


@router.get("/ai-ponuda/{pid}/pregled")
def ai_ponuda_pregled(pid: int, request: Request, db: Session = Depends(get_db),
                      greska: str = ""):
    p = db.get(pm.Ponuda, pid)
    if p is None:
        return RedirectResponse("/ai-ponuda", status_code=303)
    ctx = _ai_pregled_ctx(db, p)
    ctx["greska"] = greska
    return templates.TemplateResponse(request, "aiponuda/pregled.html", ctx)


@router.post("/ai-ponuda/{pid}/potvrdi")
async def ai_ponuda_potvrdi(pid: int, request: Request, db: Session = Depends(get_db)):
    """Obrada obaveznog pregleda: svaka AI odluka mora biti prihvaćena ili
    odbijena (uz opcionalnu napomenu) — sve se sprema u bazu učenja."""
    import json as _json

    from app.modules.ai.models import AIFeedback, AINapomena

    p = db.get(pm.Ponuda, pid)
    if p is None or p.upit is None:
        return RedirectResponse("/ai-ponuda", status_code=303)
    form = await request.form()
    u = p.upit
    ja = getattr(request.state, "user", None)

    def _kom(prefix):
        if form.get(f"{prefix}_nap") == "da":
            return (form.get(f"{prefix}_komentar") or "").strip() or None
        return None

    # validacija: SVE odluke moraju postojati (obavezan pregled)
    for s in u.stavke:
        if form.get(f"st_{s.id}_odluka") not in ("prihvati", "odbij"):
            return RedirectResponse(f"/ai-ponuda/{pid}/pregled?greska=stavke",
                                    status_code=303)
        if form.get(f"st_{s.id}_odluka") == "odbij" and not form.get(f"st_{s.id}_marza"):
            return RedirectResponse(f"/ai-ponuda/{pid}/pregled?greska=marza",
                                    status_code=303)
    if form.get("tekst_odluka") not in ("prihvati", "odbij"):
        return RedirectResponse(f"/ai-ponuda/{pid}/pregled?greska=tekst",
                                status_code=303)

    # stavke: marže (prihvat ili korekcija — oboje ide u učenje, s kontekstom)
    for ps, s in zip(p.stavke, u.stavke):
        od = form.get(f"st_{s.id}_odluka")
        kom = _kom(f"st_{s.id}")
        kontekst = _json.dumps(_stavka_kontekst(s, _ck_delta(db, s)), ensure_ascii=False)
        if od == "prihvati":
            _fb(db, request, tip="marza", kupac_naziv=p.kupac_naziv,
                proizvod_naziv=s.proizvod.naziv if s.proizvod else None,
                prijedlog=f"{s.ai_marza_pct:g} % — {s.ai_obrazlozenje or ''}",
                kontekst=kontekst, ocjena="dobro", korekcija=None, komentar=kom)
        else:
            try:
                nova = float(str(form.get(f"st_{s.id}_marza")).replace(",", "."))
            except ValueError:
                return RedirectResponse(f"/ai-ponuda/{pid}/pregled?greska=marza",
                                        status_code=303)
            _fb(db, request, tip="marza", kupac_naziv=p.kupac_naziv,
                proizvod_naziv=s.proizvod.naziv if s.proizvod else None,
                prijedlog=f"{s.ai_marza_pct:g} % — {s.ai_obrazlozenje or ''}",
                kontekst=kontekst, ocjena="korigirano",
                korekcija=f"{nova:g}", komentar=kom)
            s.marza_pct = nova
            # preračun zamrznute stavke ponude na direktorovu maržu
            kol = ps.kolicina
            prodajna = round((nova / 100.0 + 1.0) * (ps.ck_total or 0), 2)
            ps.marza_pct = nova
            if p.stil == "excel" and kol:
                exw = round(prodajna / kol, 4)
                ps.exw_1000 = exw
                ps.dap_1000 = round(exw + ps.prijevoz_1000, 4) \
                    if ps.prijevoz_1000 is not None else None
                jed = ps.dap_1000 if ((p.paritet or "").upper().startswith("DAP")
                                      and ps.dap_1000 is not None) else exw
                ps.jed_cijena = jed
                ps.iznos = round(kol * jed, 2)
            else:
                ps.jed_cijena = round(prodajna / kol, 4) if kol else None
                ps.iznos = prodajna

    # uvodni tekst ponude
    kom = _kom("tekst")
    if form.get("tekst_odluka") == "prihvati":
        db.add(AIFeedback(username=ja.username if ja else None, tip="tekst",
                          kupac_naziv=p.kupac_naziv, prijedlog=p.uvodni_tekst,
                          ocjena="dobro", komentar=kom))
    else:
        novi = (form.get("tekst_novi") or "").strip()
        db.add(AIFeedback(username=ja.username if ja else None, tip="tekst",
                          kupac_naziv=p.kupac_naziv, prijedlog=p.uvodni_tekst,
                          ocjena="korigirano", korekcija=novi or None, komentar=kom))
        if novi:
            p.uvodni_tekst = novi

    # AI napomene o problemima kalkulacija
    for n in db.scalars(select(AINapomena).where(
            AINapomena.kalkulacija_id.in_([s.kalkulacija_id for s in u.stavke]),
            AINapomena.status == "nova")).all():
        od = form.get(f"prob_{n.id}_odluka")
        if od in ("potvrdjena", "odbacena"):
            n.status = od
            n.komentar = _kom(f"prob_{n.id}")
            n.odlucio = ja.username if ja else None
            db.add(AIFeedback(username=n.odlucio, tip="napomena",
                              kupac_naziv=p.kupac_naziv, prijedlog=n.tekst,
                              ocjena="dobro" if od == "potvrdjena" else "lose",
                              komentar=n.komentar))

    p.status = "za_slanje"
    db.commit()
    return RedirectResponse(f"/ponude/{pid}", status_code=303)
