"""PDF ispis ponude: kupac gore lijevo, blok tvrtke desno,
mjesto i datum, PONUDA BR., numerirane stavke (format / količina / cijena),
PDV ovisno o kupcu (HR: obračun; inozemstvo: reverse charge), paritet, potpis.

Interni podaci (marža, CK) NIKAD ne idu u PDF.
"""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from app.modules.ponude.models import Ponuda

# Logo tvrtke (iz Resources/logo za ponude.pdf, pretvoren u PNG @600dpi) —
# sadrži kompletan blok: brand + adresa + T/F + email/web + OIB.
from pathlib import Path
_LOGO = str(Path(__file__).parent / "logo.png")
_LOGO_W, _LOGO_H = 152.961, 171.285  # originalne dimenzije u pt (iz izvornog PDF-a)

# ── Font (hrvatski znakovi) — isti pristup kao WMS/reklamacije ────────────────
try:
    pdfmetrics.registerFont(TTFont("F", "C:/Windows/Fonts/arial.ttf"))
    pdfmetrics.registerFont(TTFont("FB", "C:/Windows/Fonts/arialbd.ttf"))
    pdfmetrics.registerFontFamily("F", normal="F", bold="FB", italic="F", boldItalic="FB")
    _FONT, _FONTB = "F", "FB"
except Exception:
    _FONT, _FONTB = "Helvetica", "Helvetica-Bold"

_TAMNO = colors.HexColor("#1F2937")
_SIVA = colors.HexColor("#6B7280")
_CRVENA = colors.HexColor("#D42B1E")  # brand crvena

# Podaci tvrtke — iz konfiguracije (.env: FIRMA_*); zadano demo vrijednosti.
from app.core.config import settings as _cfg

TVRTKA = {
    "brand": _cfg.firma_brand,
    "podnaslov": _cfg.firma_podnaslov,
    "adresa": _cfg.firma_adresa,
    "tel": _cfg.firma_tel,
    "fax": _cfg.firma_fax,
    "web": _cfg.firma_web,
    "registri": _cfg.firma_registri,
    "mjesto": _cfg.firma_mjesto,
}


# ── Jezici ponude ───────────────────────────────────────────────────────────────
# Pozdravi su rodno neutralni u sva 4 jezika (kao hrvatsko "Poštovani").
INTRO = {
    "hr": "Poštovani,\ndostavljamo Vam ponudu za izradu materijala prema Vašem upitu:",
    "en": "Thank you for your inquiry. Please find below our offer for the "
          "production of the requested materials:",
    "de": "Guten Tag,\nvielen Dank für Ihre Anfrage. Nachfolgend übermitteln wir "
          "Ihnen unser Angebot für die Herstellung der angefragten Materialien:",
    "it": "Spettabile Ditta,\nfacendo seguito alla Vostra richiesta, Vi trasmettiamo "
          "la nostra offerta per la produzione dei materiali richiesti:",
}

# Stari standardni uvodi — da promjena jezika i dalje auto-prevede ponude
# generirane prije ove izmjene.
INTRO_SVI = set(INTRO.values()) | {
    "Dear Sirs,\nfurther to your inquiry, please find below our offer for the "
    "production of the requested materials:",
    "Sehr geehrte Damen und Herren,\nbezugnehmend auf Ihre Anfrage übermitteln "
    "wir Ihnen unser Angebot für die Herstellung der angefragten Materialien:",
}

TEKST = {
    "hr": dict(ponuda_br="PONUDA BR.", datum="Datum:", kontakt_osoba="Kontakt osoba:",
               format_="format:", kolicina="količina:", cijena="cijena:", iznos="iznos:",
               kom="kom", tisuca="tisuća",
               osnovica="Osnovica:", pdv="PDV {s} %:", ukupno_s_pdv="UKUPNO s PDV-om:",
               ukupno="UKUPNO:", pdv_recenica="Na navedene cijene obračunavamo PDV.",
               reverse="PDV nije obračunat — prijenos porezne obveze (reverse charge).",
               paritet="Paritet:",
               odstupanje="Svako odstupanje od navedenih tehničkih parametara posebno "
                          "se obračunava i fakturira.",
               hvala="Zahvaljujemo na upitu i srdačno Vas pozdravljamo.",
               za=f"Za {_cfg.firma_naziv}",
               vrijedi="Ponuda vrijedi {n} dana od datuma izdavanja."),
    "en": dict(ponuda_br="OFFER NO.", datum="Date:", kontakt_osoba="Contact person:",
               format_="format:", kolicina="quantity:", cijena="price:", iznos="amount:",
               kom="pcs", tisuca="thousand",
               osnovica="Net amount:", pdv="VAT {s} %:", ukupno_s_pdv="TOTAL incl. VAT:",
               ukupno="TOTAL:", pdv_recenica="VAT will be added to the above prices.",
               reverse="VAT not charged — reverse charge mechanism applies.",
               paritet="Terms of delivery:",
               odstupanje="Any deviation from the specified technical parameters will "
                          "be calculated and invoiced separately.",
               hvala="Thank you for your inquiry. Kind regards,",
               za=f"For {_cfg.firma_naziv}",
               vrijedi="This offer is valid for {n} days from the date of issue."),
    "de": dict(ponuda_br="ANGEBOT NR.", datum="Datum:", kontakt_osoba="Ansprechpartner:",
               format_="Format:", kolicina="Menge:", cijena="Preis:", iznos="Betrag:",
               kom="Stk", tisuca="Tausend",
               osnovica="Nettobetrag:", pdv="MwSt. {s} %:", ukupno_s_pdv="GESAMT inkl. MwSt.:",
               ukupno="GESAMT:", pdv_recenica="Die genannten Preise verstehen sich zzgl. MwSt.",
               reverse="Keine MwSt. berechnet — Steuerschuldnerschaft des "
                       "Leistungsempfängers (Reverse-Charge).",
               paritet="Lieferbedingung:",
               odstupanje="Jede Abweichung von den angegebenen technischen Parametern "
                          "wird gesondert berechnet und fakturiert.",
               hvala="Wir danken für Ihre Anfrage und verbleiben mit freundlichen Grüßen,",
               za=f"Für {_cfg.firma_naziv}",
               vrijedi="Dieses Angebot ist {n} Tage ab Ausstellungsdatum gültig."),
    "it": dict(ponuda_br="OFFERTA N.", datum="Data:", kontakt_osoba="Persona di contatto:",
               format_="formato:", kolicina="quantità:", cijena="prezzo:", iznos="importo:",
               kom="pz", tisuca="mille",
               osnovica="Imponibile:", pdv="IVA {s} %:", ukupno_s_pdv="TOTALE IVA inclusa:",
               ukupno="TOTALE:", pdv_recenica="Ai prezzi indicati verrà applicata l'IVA.",
               reverse="IVA non applicata — inversione contabile (reverse charge).",
               paritet="Resa:",
               odstupanje="Ogni variazione rispetto ai parametri tecnici indicati sarà "
                          "calcolata e fatturata separatamente.",
               hvala="Vi ringraziamo per la richiesta e porgiamo cordiali saluti,",
               za=f"Per {_cfg.firma_naziv}",
               vrijedi="La presente offerta è valida {n} giorni dalla data di emissione."),
}

# Incoterms za odabir pariteta u UI-u.
PARITETI = ["EXW", "FCA", "FOB", "CFR", "CIF", "CIP", "CPT", "DAP", "DAT", "DDP",
            "FCO adresa Naručitelja"]


def _x(v) -> str:
    if v is None or v == "":
        return ""
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _eur(v: float | None, dec: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _kol(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f}".replace(",", ".")


def pdf_ponuda(p: Ponuda) -> io.BytesIO:
    kupac = p.upit.kupac if p.upit else None
    t = TEKST.get(p.jezik or "hr", TEKST["hr"])

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=22 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"Ponuda {p.broj}")

    st = ParagraphStyle("n", fontName=_FONT, fontSize=10, textColor=_TAMNO, leading=14)
    st_b = ParagraphStyle("b", fontName=_FONTB, fontSize=10, textColor=_TAMNO, leading=14)
    st_kupac = ParagraphStyle("k", fontName=_FONTB, fontSize=12.5, textColor=_TAMNO, leading=16)
    st_mali = ParagraphStyle("m", fontName=_FONT, fontSize=8.5, textColor=_SIVA, leading=11.5)
    st_brand = ParagraphStyle("br", fontName=_FONTB, fontSize=19, textColor=_TAMNO, leading=20)
    st_naslov = ParagraphStyle("na", fontName=_FONTB, fontSize=13.5, textColor=_TAMNO,
                               leading=16, alignment=2)  # desno
    st_desno = ParagraphStyle("de", fontName=_FONT, fontSize=10, textColor=_TAMNO,
                              leading=14, alignment=2)

    el = []

    # ── zaglavlje: kupac lijevo, tvrtka desno ──────────────────────────────
    lijevo = [Paragraph(_x(p.kupac_naziv), st_kupac)]
    if kupac and kupac.adresa:
        for red in kupac.adresa.split(","):
            lijevo.append(Paragraph(_x(red.strip()), st))
    if kupac and kupac.oib:
        lijevo.append(Paragraph(f"OIB: {_x(kupac.oib)}", st))
    if kupac and kupac.kontakt:
        for red in kupac.kontakt.split("·"):
            lijevo.append(Paragraph(_x(red.strip()), st))
    if kupac and kupac.np_osoba:
        lijevo.append(Spacer(1, 2 * mm))
        lijevo.append(Paragraph(f"{t['kontakt_osoba']} {_x(kupac.np_osoba)}", st_b))

    logo = Image(_LOGO, width=_LOGO_W, height=_LOGO_H)  # originalna veličina (~54×60 mm)
    logo.hAlign = "RIGHT"
    desno = [logo]

    zag = Table([[lijevo, desno]], colWidths=[96 * mm, 72 * mm])
    zag.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    el.append(zag)
    el.append(Spacer(1, 8 * mm))

    # ── mjesto/datum + broj ponude (desno) ─────────────────────────────────
    el.append(Paragraph(f"{TVRTKA['mjesto']}, {p.datum.strftime('%d.%m.%Y.')}", st_desno))
    el.append(Spacer(1, 4 * mm))
    el.append(Paragraph(f"{t['ponuda_br']} {_x(p.broj)}", st_naslov))
    el.append(Spacer(1, 8 * mm))

    # ── uvodni tekst ─────────────────────────────────────────────────────────
    if p.uvodni_tekst:
        el.append(Paragraph(_x(p.uvodni_tekst).replace("\n", "<br/>"), st))
        el.append(Spacer(1, 5 * mm))

    # ── stavke: numerirano, kao u stvarnoj ponudi ───────────────────────────
    st_stavka = ParagraphStyle("sn", fontName=_FONTB, fontSize=10.5,
                               textColor=_TAMNO, leading=14)
    for i, s in enumerate(p.stavke, start=1):
        el.append(Paragraph(f"{i}.  {_x(s.naziv)}", st_stavka))
        el.append(Spacer(1, 1.5 * mm))
        redovi = []
        if s.opis:
            opis = s.opis
            if opis.startswith("format:"):
                opis = t["format_"] + opis[len("format:"):]
            redovi.append(("", _x(opis)))
        jed = t["tisuca"] if s.jedinica == "tisuća" else (_x(s.jedinica) or t["kom"])
        kol_txt = f"{_kol(s.kolicina)} {jed}"
        if s.jedinica == "tisuća" and s.kolicina:
            kol_txt += f" ({_kol(s.kolicina * 1000)} {t['kom']})"
        redovi.append((t["kolicina"], kol_txt))
        if s.jed_cijena is not None:
            cij = f"{_eur(s.jed_cijena, 4)} EUR/{jed}"
            if s.jedinica == "tisuća":
                cij += f"  ({_eur(s.jed_cijena / 1000, 4)} EUR/{t['kom']})"
            redovi.append((t["cijena"], cij))
        redovi.append((t["iznos"], f"{_eur(s.iznos, 2)} EUR"))
        tbl = Table([[Paragraph(f"<b>{lab}</b>" if lab else "", st),
                      Paragraph(txt, st)] for lab, txt in redovi],
                    colWidths=[28 * mm, 130 * mm])
        tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (0, -1), 10 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        el.append(tbl)
        el.append(Spacer(1, 4 * mm))

    # ── PDV raspis ────────────────────────────────────────────────────────────
    el.append(Spacer(1, 2 * mm))
    if p.pdv_obracun:
        pdv_redovi = [
            [t["osnovica"], f"{_eur(p.ukupno)} EUR"],
            [t["pdv"].format(s=f"{p.pdv_stopa:g}"), f"{_eur(p.pdv_iznos)} EUR"],
            [t["ukupno_s_pdv"], f"{_eur(p.ukupno_s_pdv)} EUR"],
        ]
        tbl = Table([[Paragraph(f"<b>{lab}</b>", st), Paragraph(f"<b>{val}</b>" if lab == t["ukupno_s_pdv"] else val, st)]
                     for lab, val in pdv_redovi], colWidths=[44 * mm, 60 * mm])
        tbl.setStyle(TableStyle([
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("LINEABOVE", (0, 2), (-1, 2), 0.7, _TAMNO),
        ]))
        el.append(tbl)
        el.append(Spacer(1, 2 * mm))
        el.append(Paragraph(t["pdv_recenica"], st))
    else:
        el.append(Paragraph(f"<b>{t['ukupno']} {_eur(p.ukupno)} EUR</b>", st))
        el.append(Spacer(1, 2 * mm))
        el.append(Paragraph(t["reverse"], st))
    el.append(Spacer(1, 4 * mm))

    # ── paritet + standardne napomene ───────────────────────────────────────
    if p.paritet:
        tbl = Table([[Paragraph(f"<b>{t['paritet']}</b>", st), Paragraph(_x(p.paritet), st)]],
                    colWidths=[40 * mm, 118 * mm])
        tbl.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
        el.append(tbl)
        el.append(Spacer(1, 4 * mm))

    if p.napomene:
        el.append(Paragraph(_x(p.napomene).replace("\n", "<br/>"), st))
        el.append(Spacer(1, 3 * mm))

    el.append(Paragraph(t["odstupanje"], st))
    el.append(Paragraph(t["hvala"], st))
    el.append(Spacer(1, 6 * mm))
    el.append(Paragraph(t["za"], st))
    if p.potpisnik:
        el.append(Spacer(1, 2 * mm))
        el.append(Paragraph(_x(p.potpisnik), st))
    el.append(Spacer(1, 4 * mm))
    el.append(Paragraph(t["vrijedi"].format(n=p.vrijedi_dana), st_mali))

    doc.build(el)
    buf.seek(0)
    return buf
