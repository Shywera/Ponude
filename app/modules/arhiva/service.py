"""Spremanje parsiranih kalkulacija u bazu + usporedba s prethodnom."""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.arhiva import models as m
from app.modules.arhiva import parser


def _nadji_ili_kreiraj_proizvod(db: Session, k: parser.Kalkulacija) -> m.Proizvod:
    kupac = db.scalar(select(m.Kupac).where(m.Kupac.naziv == k.kupac))
    if kupac is None:
        kupac = m.Kupac(naziv=k.kupac)
        db.add(kupac)
        db.flush()

    sifra = parser.izvuci_sifru_artikla(k.naziv_proizvoda)
    kljuc = sifra or parser.normaliziraj_naziv(k.naziv_proizvoda)
    proizvod = db.scalar(select(m.Proizvod).where(
        m.Proizvod.kupac_id == kupac.id, m.Proizvod.kljuc == kljuc))
    if proizvod is None:
        proizvod = m.Proizvod(kupac_id=kupac.id, naziv=k.naziv_proizvoda,
                              sifra_artikla=sifra, kljuc=kljuc)
        db.add(proizvod)
        db.flush()
    return proizvod


def spremi_kalkulaciju(db: Session, k: parser.Kalkulacija) -> tuple[m.Kalkulacija, bool]:
    """Spremi parsiranu kalkulaciju. Vraća (zapis, je_li_nova).
    Ako broj kalkulacije već postoji, postojeći zapis se NE dira."""
    postojeca = db.scalar(select(m.Kalkulacija).where(m.Kalkulacija.broj == k.broj))
    if postojeca is not None:
        return postojeca, False

    proizvod = _nadji_ili_kreiraj_proizvod(db, k)

    zapis = m.Kalkulacija(
        proizvod_id=proizvod.id,
        broj=k.broj, normativ_br=k.normativ_br, datum=k.datum,
        kupac_naziv=k.kupac, naziv_proizvoda=k.naziv_proizvoda,
        serija=k.serija, serija_jedinica=k.serija_jedinica,
        glavni_stroj=k.glavni_stroj,
        trosak_materijal=k.trosak_materijal, trosak_rad=k.trosak_rad,
        vanjska_usluga=k.vanjska_usluga, ck_total=k.ck_total,
        ck_po_jedinici=k.ck_po_jedinici,
        datoteka=k.datoteka,
        napomena_uvoza="; ".join(k.upozorenja) or None,
    )
    db.add(zapis)
    db.flush()

    for a in k.artikli:
        db.add(m.KalkulacijaArtikl(
            kalkulacija_id=zapis.id, rb=a.rb, naziv=a.naziv,
            sirina_mm=a.sirina_mm, visina_mm=a.visina_mm,
            broj_boja=a.broj_boja, broj_prolaza=a.broj_prolaza,
            lak=a.lak, dorada=a.dorada, tip_papira=a.tip_papira,
            gramatura=a.gramatura, nabavna_cijena=a.nabavna_cijena,
            udio=a.udio, kolicina=a.kolicina, ck_total=a.ck_total,
        ))
    for mat in k.materijali:
        db.add(m.KalkulacijaMaterijal(
            kalkulacija_id=zapis.id, sifra=mat.sifra, naziv=mat.naziv,
            jedinica=mat.jedinica, kolicina=mat.kolicina,
            jed_cijena=mat.jed_cijena, vrijednost=mat.vrijednost,
        ))
    for op in k.operacije:
        db.add(m.KalkulacijaOperacija(
            kalkulacija_id=zapis.id, stroj=op.stroj, operacija=op.operacija,
            proces=op.proces, vrijeme_min=op.vrijeme_min,
            cijena_h=op.cijena_h, iznos=op.iznos,
        ))
    return zapis, True


# ---------------------------------------------------------------- usporedba

def prethodna_kalkulacija(db: Session, kalk: m.Kalkulacija) -> m.Kalkulacija | None:
    """Kronološki prethodna kalkulacija istog proizvoda (po datumu pa id-u)."""
    kandidati = [x for x in kalk.proizvod.kalkulacije if x.id != kalk.id]
    ranije = [x for x in kandidati
              if (x.datum or x.uvezeno.date(), x.id) < (kalk.datum or kalk.uvezeno.date(), kalk.id)]
    if not ranije:
        return None
    return max(ranije, key=lambda x: (x.datum or x.uvezeno.date(), x.id))


def usporedi(nova: m.Kalkulacija, stara: m.Kalkulacija) -> dict:
    """Deterministička usporedba dviju kalkulacija istog proizvoda.
    Vraća čiste brojke/činjenice — ovo je ulaz i za UI i za Claude."""
    d: dict = {"stara_broj": stara.broj, "stara_datum": str(stara.datum),
               "nova_broj": nova.broj, "nova_datum": str(nova.datum)}

    def pct(novo, staro):
        if staro and novo is not None:
            return round((novo - staro) / staro * 100, 1)
        return None

    d["ck_po_jedinici"] = {"staro": stara.ck_po_jedinici, "novo": nova.ck_po_jedinici,
                           "delta_pct": pct(nova.ck_po_jedinici, stara.ck_po_jedinici)}
    d["ck_total"] = {"staro": stara.ck_total, "novo": nova.ck_total,
                     "delta_pct": pct(nova.ck_total, stara.ck_total)}
    d["serija"] = {"staro": stara.serija, "novo": nova.serija}
    d["trosak_materijal"] = {"staro": stara.trosak_materijal, "novo": nova.trosak_materijal,
                             "delta_pct": pct(nova.trosak_materijal, stara.trosak_materijal)}
    d["trosak_rad"] = {"staro": stara.trosak_rad, "novo": nova.trosak_rad,
                       "delta_pct": pct(nova.trosak_rad, stara.trosak_rad)}

    # materijali po šifri: promjena nabavne cijene, dodani, uklonjeni
    stari_mat = {x.sifra: x for x in stara.materijali if x.sifra}
    novi_mat = {x.sifra: x for x in nova.materijali if x.sifra}
    promjene, dodani, uklonjeni = [], [], []
    for sifra, nm in novi_mat.items():
        sm = stari_mat.get(sifra)
        if sm is None:
            dodani.append({"sifra": sifra, "naziv": nm.naziv, "vrijednost": nm.vrijednost})
        elif sm.jed_cijena and nm.jed_cijena and abs(nm.jed_cijena - sm.jed_cijena) > 1e-9:
            promjene.append({"sifra": sifra, "naziv": nm.naziv,
                             "staro": sm.jed_cijena, "novo": nm.jed_cijena,
                             "delta_pct": pct(nm.jed_cijena, sm.jed_cijena)})
    for sifra, sm in stari_mat.items():
        if sifra not in novi_mat:
            uklonjeni.append({"sifra": sifra, "naziv": sm.naziv, "vrijednost": sm.vrijednost})
    d["materijali"] = {"promjene_cijena": promjene, "dodani": dodani, "uklonjeni": uklonjeni}

    # operacije po stroju
    stari_str = {x.stroj for x in stara.operacije if x.stroj}
    novi_str = {x.stroj for x in nova.operacije if x.stroj}
    d["strojevi"] = {"dodani": sorted(novi_str - stari_str),
                     "uklonjeni": sorted(stari_str - novi_str)}
    return d


def razina_upozorenja(d: dict) -> str:
    """info | paznja | kriticno — prag na Δ cijene po jedinici."""
    delta = (d.get("ck_po_jedinici") or {}).get("delta_pct")
    if delta is None:
        delta = (d.get("ck_total") or {}).get("delta_pct") or 0
    a = abs(delta)
    if a >= 15:
        return "kriticno"
    if a >= 5:
        return "paznja"
    return "info"


def usporedba_json(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, indent=1)
