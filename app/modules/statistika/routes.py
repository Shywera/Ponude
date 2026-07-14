"""Statistika za direktora — sve izračunato iz arhive i ponuda, bez JS librarya.

Sekcije:
  * KPI kartice (proizvodi, kalkulacije, ponude, prosječna marža)
  * Promjene nabavnih cijena materijala (prva vs zadnja cijena po šifri)
  * Kretanje CK po jedinici za proizvode s više kalkulacija (sparkline)
  * Struktura troška po kupcu (materijal vs rad)
  * Marže i zarada po kupcu (iz izdanih ponuda)
"""
from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.arhiva import models as am
from app.modules.ponude import models as pm

router = APIRouter(tags=["statistika"])
from app.core.templating import templates  # zajednicka Jinja okolina


def _sparkline(vrijednosti: list[float], w: int = 130, h: int = 30) -> dict | None:
    """Točke za SVG polyline (2px linija, marker na zadnjoj točki)."""
    if len(vrijednosti) < 2:
        return None
    mn, mx = min(vrijednosti), max(vrijednosti)
    rasp = (mx - mn) or 1.0
    pad = 4
    tocke = []
    for i, v in enumerate(vrijednosti):
        x = pad + i * (w - 2 * pad) / (len(vrijednosti) - 1)
        y = h - pad - (v - mn) * (h - 2 * pad) / rasp
        tocke.append((round(x, 1), round(y, 1)))
    return {"w": w, "h": h,
            "points": " ".join(f"{x},{y}" for x, y in tocke),
            "zadnja": tocke[-1]}


@router.get("/statistika")
def statistika(request: Request, db: Session = Depends(get_db)):
    kalkulacije = db.scalars(select(am.Kalkulacija)).all()
    proizvodi = db.scalars(select(am.Proizvod)).all()
    ponude = db.scalars(select(pm.Ponuda)).all()

    # ---- KPI ---------------------------------------------------------------
    god = date.today().year
    ponude_god = [p for p in ponude if p.datum and p.datum.year == god]
    sve_stavke = [s for p in ponude for s in p.stavke]
    marze_pct = [s.marza_pct for s in sve_stavke if s.marza_pct is not None]
    kpi = {
        "proizvoda": len(proizvodi),
        "kalkulacija": len(kalkulacije),
        "kupaca_aktivnih": len({p.kupac_id for p in proizvodi}),
        "ponuda_god": len(ponude_god),
        "vrijednost_ponuda_god": sum(p.ukupno for p in ponude_god),
        "zarada_ponuda_god": sum((s.iznos - (s.ck_total or 0)) for p in ponude_god
                                 for s in p.stavke),
        "prosj_marza": (sum(marze_pct) / len(marze_pct)) if marze_pct else None,
    }

    # ---- promjene cijena materijala (prva vs zadnja po šifri) ---------------
    po_sifri: dict[str, list] = {}
    for k in kalkulacije:
        kad = (k.datum or k.uvezeno.date(), k.id)
        for mt in k.materijali:
            if mt.sifra and mt.jed_cijena:
                po_sifri.setdefault(mt.sifra, []).append((kad, mt.jed_cijena, mt.naziv))
    materijali = []
    for sifra, zapisi in po_sifri.items():
        zapisi.sort(key=lambda z: z[0])
        prva, zadnja = zapisi[0][1], zapisi[-1][1]
        if len(zapisi) >= 2 and abs(zadnja - prva) > 1e-9:
            materijali.append({
                "sifra": sifra, "naziv": zapisi[-1][2] or sifra,
                "prva": prva, "zadnja": zadnja,
                "delta_pct": (zadnja - prva) / prva * 100,
                "n": len(zapisi),
            })
    materijali.sort(key=lambda m: abs(m["delta_pct"]), reverse=True)
    materijali = materijali[:12]
    max_delta = max((abs(m["delta_pct"]) for m in materijali), default=1.0)
    for m in materijali:
        m["sirina"] = round(abs(m["delta_pct"]) / max_delta * 100, 1)

    # ---- proizvodi s lancem: CK/jedinici kroz vrijeme (sparkline) ------------
    lanci = []
    for p in proizvodi:
        ks = sorted(p.kalkulacije, key=lambda k: (k.datum or k.uvezeno.date(), k.id))
        vr = [k.ck_po_jedinici for k in ks if k.ck_po_jedinici]
        if len(vr) >= 2:
            lanci.append({
                "p": p, "n": len(vr),
                "prva": vr[0], "zadnja": vr[-1],
                "delta_pct": (vr[-1] - vr[0]) / vr[0] * 100 if vr[0] else None,
                "spark": _sparkline(vr),
                "od": ks[0].datum, "do": ks[-1].datum,
            })
    lanci.sort(key=lambda r: r["n"], reverse=True)

    # ---- struktura troška po kupcu (materijal vs rad) ------------------------
    po_kupcu: dict[str, dict] = {}
    for k in kalkulacije:
        d = po_kupcu.setdefault(k.kupac_naziv, {"mat": 0.0, "rad": 0.0, "n": 0})
        d["mat"] += k.trosak_materijal
        d["rad"] += k.trosak_rad
        d["n"] += 1
    struktura = []
    for naziv, d in po_kupcu.items():
        uk = d["mat"] + d["rad"]
        if uk > 0:
            struktura.append({"kupac": naziv, "mat": d["mat"], "rad": d["rad"],
                              "ukupno": uk, "n": d["n"],
                              "mat_pct": d["mat"] / uk * 100,
                              "rad_pct": d["rad"] / uk * 100})
    struktura.sort(key=lambda s: s["ukupno"], reverse=True)

    # ---- marže po kupcu (iz ponuda) -------------------------------------------
    marze_kupci: dict[str, dict] = {}
    for p in ponude:
        d = marze_kupci.setdefault(p.kupac_naziv, {"marze": [], "zarada": 0.0,
                                                   "vrijednost": 0.0, "n": 0})
        d["n"] += 1
        for s in p.stavke:
            if s.marza_pct is not None:
                d["marze"].append(s.marza_pct)
            d["zarada"] += s.iznos - (s.ck_total or 0)
            d["vrijednost"] += s.iznos
    marze = []
    for naziv, d in marze_kupci.items():
        if d["marze"]:
            marze.append({"kupac": naziv, "n": d["n"],
                          "prosj": sum(d["marze"]) / len(d["marze"]),
                          "zarada": d["zarada"], "vrijednost": d["vrijednost"]})
    marze.sort(key=lambda m: m["zarada"], reverse=True)
    max_zarada = max((m["zarada"] for m in marze), default=1.0) or 1.0
    for m in marze:
        m["sirina"] = round(max(m["zarada"], 0) / max_zarada * 100, 1)

    return templates.TemplateResponse(request, "statistika/pregled.html", {
        "kpi": kpi, "materijali": materijali, "lanci": lanci,
        "struktura": struktura, "marze": marze, "god": god,
    })
