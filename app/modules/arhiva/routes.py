"""Rute arhive: popis etiketa, detalj proizvoda s razlikama, detalj kalkulacije, uvoz."""
import os
import tempfile
from datetime import date

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.arhiva import models as m
from app.modules.arhiva import parser, service

router = APIRouter(prefix="/arhiva", tags=["arhiva"])
from app.core.templating import templates  # zajednicka Jinja okolina


def _zadnja(p: m.Proizvod) -> m.Kalkulacija | None:
    if not p.kalkulacije:
        return None
    return max(p.kalkulacije, key=lambda k: (k.datum or date.min, k.id))


def raspon_marzi(request: Request) -> tuple[int, int, int]:
    """Raspon raspisa marži iz query parametara (?od=30&do=70&korak=2), s granicama."""
    def _int(ime: str, default: int) -> int:
        try:
            return int(request.query_params.get(ime, default))
        except (TypeError, ValueError):
            return default
    od = max(0, min(_int("od", 30), 300))
    do = max(od, min(_int("do", 70), 300))
    korak = max(1, min(_int("korak", 1), 50))
    if (do - od) // korak > 80:  # zaštita od predugih tablica
        do = od + 80 * korak
    return od, do, korak


@router.get("")
def popis(request: Request, db: Session = Depends(get_db), kupac: int | None = None, q: str = ""):
    """Popis svih etiketa (proizvoda) sa zadnjom cijenom i razlikom prema prethodnoj."""
    kupci = db.scalars(select(m.Kupac).order_by(m.Kupac.naziv)).all()
    proizvodi = db.scalars(select(m.Proizvod)).all()

    redovi = []
    for p in proizvodi:
        if kupac and p.kupac_id != kupac:
            continue
        if q and q.lower() not in p.naziv.lower():
            continue
        z = _zadnja(p)
        if z is None:
            continue
        red = {"p": p, "z": z, "delta": None, "razina": None, "broj_kalk": len(p.kalkulacije)}
        pret = service.prethodna_kalkulacija(db, z)
        if pret is not None:
            d = service.usporedi(z, pret)
            red["delta"] = (d.get("ck_po_jedinici") or {}).get("delta_pct")
            red["razina"] = service.razina_upozorenja(d)
        redovi.append(red)

    redovi.sort(key=lambda r: (r["p"].kupac.naziv, r["p"].naziv))
    return templates.TemplateResponse(request, "arhiva/popis.html", {
        "redovi": redovi, "kupci": kupci, "kupac_id": kupac, "q": q,
    })


@router.get("/proizvod/{pid}")
def proizvod(pid: int, request: Request, db: Session = Depends(get_db)):
    """Kronologija kalkulacija jednog proizvoda + detaljna razlika zadnje prema prethodnoj."""
    p = db.get(m.Proizvod, pid)
    if p is None:
        return RedirectResponse("/arhiva", status_code=303)

    kalk = sorted(p.kalkulacije, key=lambda k: (k.datum or date.min, k.id), reverse=True)
    usporedbe = {}  # kalk.id -> dict usporedbe s kronološki prethodnom
    for k in kalk:
        pret = service.prethodna_kalkulacija(db, k)
        if pret is not None:
            d = service.usporedi(k, pret)
            d["_razina"] = service.razina_upozorenja(d)
            usporedbe[k.id] = d

    return templates.TemplateResponse(request, "arhiva/proizvod.html", {
        "p": p, "kalkulacije": kalk, "usporedbe": usporedbe,
    })


@router.get("/kalkulacija/{kid}")
def kalkulacija(kid: int, request: Request, db: Session = Depends(get_db),
                stavka: int | None = None):
    k = db.get(m.Kalkulacija, kid)
    if k is None:
        return RedirectResponse("/arhiva", status_code=303)

    # Kontekst upita: ?stavka=<id> -> raspis marži postaje ODABIR marže za tu
    # stavku (kao kad direktor zaokruži maržu na isprintanoj kalkulaciji).
    stavka_obj = None
    if stavka is not None:
        from app.modules.ponude.models import UpitStavka
        stavka_obj = db.get(UpitStavka, stavka)
        if stavka_obj is not None and stavka_obj.kalkulacija_id != k.id:
            stavka_obj = None
    pret = service.prethodna_kalkulacija(db, k)
    usporedba = None
    if pret is not None:
        usporedba = service.usporedi(k, pret)
        usporedba["_razina"] = service.razina_upozorenja(usporedba)

    # Raspis po maržama — podesiv raspon i korak (npr. 30–70 po 2, 50–80 po 1).
    # PRODAJNA VRIJEDNOST = (marža/100 + 1) × CK; cijena radnog sata stroja =
    # financijska razlika / sati glavnog stroja (Excel: J/D22).
    od, do, korak = raspon_marzi(request)
    sati_stroja = sum((o.vrijeme_min or 0.0) for o in k.operacije
                      if o.stroj and k.glavni_stroj and o.stroj == k.glavni_stroj) / 60.0
    marze = []
    for pct in range(od, do + 1, korak):
        pv = (pct / 100.0 + 1.0) * k.ck_total
        fr = pv - k.ck_total
        marze.append({
            "pct": pct,
            "prodajna_vrijednost": pv,
            "razlika": fr,
            "po_jedinici": (pv / k.serija) if k.serija else None,
            "cijena_sata": (fr / sati_stroja) if sati_stroja else None,
        })

    from app.modules.ai.models import AINapomena
    napomene = db.scalars(select(AINapomena)
                          .where(AINapomena.kalkulacija_id == k.id)
                          .order_by(AINapomena.status, AINapomena.id)).all()

    return templates.TemplateResponse(request, "arhiva/kalkulacija.html", {
        "k": k, "pret": pret, "u": usporedba,
        "marze": marze, "sati_stroja": sati_stroja,
        "od": od, "do": do, "korak": korak,
        "stavka": stavka_obj, "napomene": napomene,
    })


@router.get("/kupci")
def kupci(request: Request, db: Session = Depends(get_db), q: str = ""):
    """Šifrarnik kupaca: adresa/OIB/kontakt za zaglavlje ponude + PDV status."""
    lista = db.scalars(select(m.Kupac).order_by(m.Kupac.naziv)).all()
    ukupno = len(lista)
    if q:
        ql = q.lower()
        lista = [k for k in lista if ql in k.naziv.lower()
                 or (k.oib and ql in k.oib.lower())]
    else:
        # kupci s proizvodima u arhivi (najkorišteniji) na vrh
        lista.sort(key=lambda k: (not k.proizvodi, k.naziv))
    return templates.TemplateResponse(request, "arhiva/kupci.html", {
        "kupci": lista, "q": q, "ukupno": ukupno,
    })


@router.post("/kupci/{kid}/uredi")
def kupac_uredi(kid: int, request: Request, db: Session = Depends(get_db),
                adresa: str = Form(""), oib: str = Form(""), kontakt: str = Form(""),
                np_osoba: str = Form(""), u_hrvatskoj: str = Form(""),
                jezik: str = Form("")):
    k = db.get(m.Kupac, kid)
    if k is not None:
        k.adresa = adresa.strip() or None
        k.oib = oib.strip() or None
        k.kontakt = kontakt.strip() or None
        k.np_osoba = np_osoba.strip() or None
        k.u_hrvatskoj = u_hrvatskoj == "1"
        if jezik in ("hr", "en", "de", "it"):
            k.jezik = jezik
        db.commit()
    return RedirectResponse("/arhiva/kupci", status_code=303)


@router.post("/kalkulacija/{kid}/ai")
def generiraj_ai(kid: int, db: Session = Depends(get_db)):
    """Generiraj (ili regeneriraj) AI objašnjenje razlike prema prethodnoj kalkulaciji."""
    import json as _json

    from app.modules.ai import claude as ai

    k = db.get(m.Kalkulacija, kid)
    if k is None:
        return RedirectResponse("/arhiva", status_code=303)
    pret = service.prethodna_kalkulacija(db, k)
    if pret is None:
        return RedirectResponse(f"/arhiva/proizvod/{k.proizvod_id}", status_code=303)

    d = service.usporedi(k, pret)
    obj = ai.objasni_razliku(d, service.razina_upozorenja(d))
    k.ai_sazetak = obj.sazetak
    k.ai_razlozi = _json.dumps(obj.razlozi, ensure_ascii=False)
    k.ai_razina = obj.razina
    db.commit()
    return RedirectResponse(f"/arhiva/proizvod/{k.proizvod_id}", status_code=303)


@router.post("/kalkulacija/{kid}/ai-ocjena")
def ai_ocjena(kid: int, request: Request, ocjena: str = Form(""),
              komentar: str = Form(""), db: Session = Depends(get_db)):
    """Direktorova kvačica na AI objašnjenje (dobro/loše) — sustav uči."""
    from app.modules.ai.models import AIFeedback

    k = db.get(m.Kalkulacija, kid)
    if k is not None and ocjena in ("dobro", "lose"):
        u = getattr(request.state, "user", None)
        db.add(AIFeedback(
            username=u.username if u else None, tip="objasnjenje",
            kupac_naziv=k.kupac_naziv, proizvod_naziv=k.naziv_proizvoda,
            prijedlog=k.ai_sazetak, ocjena=ocjena,
            komentar=komentar.strip() or None))
        db.commit()
    return RedirectResponse(f"/arhiva/proizvod/{k.proizvod_id if k else ''}", status_code=303)


def _ai_pregled(db: Session, k: m.Kalkulacija) -> int:
    """Pokreni AI pregled kalkulacije: nađi probleme, spremi kao napomene.
    Postojeće neodlučene ('nova') napomene se zamjenjuju; odlučene ostaju."""
    import statistics

    from sqlalchemy import delete as _delete

    from app.modules.ai import claude as ai
    from app.modules.ai.models import AINapomena

    # tipična cijena svakog materijala = medijan iz OSTALIH kalkulacija
    materijali = []
    for mt in k.materijali:
        tipicna = None
        if mt.sifra:
            ostale = [x.jed_cijena for x in db.scalars(
                select(m.KalkulacijaMaterijal)
                .where(m.KalkulacijaMaterijal.sifra == mt.sifra,
                       m.KalkulacijaMaterijal.kalkulacija_id != k.id,
                       m.KalkulacijaMaterijal.jed_cijena.is_not(None))).all()]
            if ostale:
                tipicna = statistics.median(ostale)
        materijali.append({"sifra": mt.sifra, "naziv": mt.naziv,
                           "kolicina": mt.kolicina, "jed_cijena": mt.jed_cijena,
                           "tipicna_cijena": tipicna})

    pret = service.prethodna_kalkulacija(db, k)
    delta = None
    usporedba = None
    if pret is not None:
        usporedba = service.usporedi(k, pret)
        delta = (usporedba.get("ck_po_jedinici") or {}).get("delta_pct")

    ctx = {"kalkulacija": k.broj, "proizvod": k.naziv_proizvoda,
           "serija": k.serija, "ck_total": k.ck_total,
           "ck_delta_pct": delta,
           "materijali": materijali,
           "operacije": [{"stroj": o.stroj, "operacija": o.operacija,
                          "vrijeme_min": o.vrijeme_min, "cijena_h": o.cijena_h,
                          "iznos": o.iznos} for o in k.operacije],
           "usporedba_s_prethodnom": usporedba}

    napomene = ai.pregledaj_kalkulaciju(ctx)
    db.execute(_delete(AINapomena).where(AINapomena.kalkulacija_id == k.id,
                                         AINapomena.status == "nova"))
    for n in napomene:
        db.add(AINapomena(kalkulacija_id=k.id, tekst=n.tekst, razina=n.razina))
    db.commit()
    return len(napomene)


@router.post("/kalkulacija/{kid}/ai-pregled")
def ai_pregled_rucno(kid: int, db: Session = Depends(get_db)):
    """Gumb: (ponovno) pokreni AI pregled problema na kalkulaciji."""
    k = db.get(m.Kalkulacija, kid)
    if k is None:
        return RedirectResponse("/arhiva", status_code=303)
    _ai_pregled(db, k)
    return RedirectResponse(f"/arhiva/kalkulacija/{kid}", status_code=303)


@router.post("/napomena/{nid}/odluka")
def napomena_odluka(nid: int, request: Request, odluka: str = Form(""),
                    komentar: str = Form(""), db: Session = Depends(get_db)):
    """Direktorova kvačica na AI napomenu: ✓ točno / ✗ nije problem — sustav uči."""
    from app.modules.ai.models import AIFeedback, AINapomena

    n = db.get(AINapomena, nid)
    if n is not None and odluka in ("potvrdjena", "odbacena"):
        u = getattr(request.state, "user", None)
        n.status = odluka
        n.komentar = komentar.strip() or None
        n.odlucio = u.username if u else None
        k = db.get(m.Kalkulacija, n.kalkulacija_id)
        db.add(AIFeedback(
            username=n.odlucio, tip="napomena",
            kupac_naziv=k.kupac_naziv if k else None,
            proizvod_naziv=k.naziv_proizvoda if k else None,
            prijedlog=n.tekst, ocjena="dobro" if odluka == "potvrdjena" else "lose",
            komentar=n.komentar))
        db.commit()
        return RedirectResponse(f"/arhiva/kalkulacija/{n.kalkulacija_id}", status_code=303)
    return RedirectResponse("/arhiva", status_code=303)


@router.get("/uvoz")
def uvoz_forma(request: Request):
    return templates.TemplateResponse(request, "arhiva/uvoz.html", {"rezultati": None})


@router.post("/uvoz")
async def uvoz(request: Request, datoteke: list[UploadFile], db: Session = Depends(get_db)):
    """Upload jedne ili više .xlsx kalkulacija; parsiraj i spremi."""
    rezultati = []
    for dat in datoteke:
        ime = dat.filename or "bez-imena.xlsx"
        try:
            sadrzaj = await dat.read()
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(sadrzaj)
                put = tmp.name
            try:
                k = parser.parsiraj(put)
                k.datoteka = ime
                zapis, novo = service.spremi_kalkulaciju(db, k)
                if novo:
                    db.commit()
                    try:
                        _ai_pregled(db, zapis)  # automatski AI pregled problema
                    except Exception:
                        pass
                    rezultati.append({"ime": ime, "status": "ok",
                                      "poruka": f"Uvezeno: {k.broj} — {k.naziv_proizvoda} "
                                                f"(CK {k.ck_total:.2f} EUR)",
                                      "upozorenja": k.upozorenja, "kid": zapis.id})
                else:
                    rezultati.append({"ime": ime, "status": "preskoceno",
                                      "poruka": f"Kalkulacija {k.broj} već postoji u arhivi.",
                                      "upozorenja": [], "kid": zapis.id})
            finally:
                os.unlink(put)
        except Exception as e:
            db.rollback()
            rezultati.append({"ime": ime, "status": "greska", "poruka": str(e),
                              "upozorenja": [], "kid": None})
    return templates.TemplateResponse(request, "arhiva/uvoz.html", {"rezultati": rezultati})
