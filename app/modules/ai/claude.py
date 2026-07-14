"""AI objašnjenja razlika u cijeni — Claude API + demo (rule-based) način.

Claude NIKAD ne računa: dobiva gotove brojke iz `service.usporedi()` i samo ih
pretvara u čitljivo objašnjenje za direktora. Uz AI_DEMO=1 (ili kad API nije
dostupan) objašnjenje slaže kod po pravilima, označeno kao [DEMO].
"""
import json

from pydantic import BaseModel

from app.core.config import settings


class ObjasnjenjeRazlike(BaseModel):
    sazetak: str          # 1-2 rečenice za popis/karticu
    razlozi: list[str]    # bullet objašnjenja, poredana po važnosti
    razina: str           # info | paznja | kriticno


SYSTEM = """Ti si analitičar cijena u tiskari etiketa (offset tisak, rezanje, štancanje).
Dobivaš usporedbu dviju kalkulacija ISTOG proizvoda (stara vs nova) kao JSON s već
izračunatim brojkama. Tvoj posao je objasniti direktoru ZAŠTO se cijena promijenila,
na hrvatskom, kratko i konkretno.

Pravila:
- Ne izmišljaj brojke — koristi isključivo one iz JSON-a.
- Poredaj razloge po veličini utjecaja (najveći prvi).
- Manja serija = viši trošak po jedinici (fiksni troškovi pripreme na manje komada) — prepoznaj to.
- razina: "info" (<5% ili normalno objašnjivo), "paznja" (5-15% ili strukturna promjena),
  "kriticno" (>=15% ili nešto sumnjivo).
- sazetak: max 2 rečenice, direktan, bez fraza."""


def _demo_objasnjenje(diff: dict, razina: str) -> ObjasnjenjeRazlike:
    """Rule-based objašnjenje bez API-ja (AI_DEMO ili API nedostupan)."""
    razlozi: list[str] = []

    ck = diff.get("ck_po_jedinici") or {}
    delta = ck.get("delta_pct")

    ser = diff.get("serija") or {}
    if ser.get("staro") and ser.get("novo") and ser["staro"] != ser["novo"]:
        smjer = "manja" if ser["novo"] < ser["staro"] else "veća"
        razlozi.append(
            f"Serija je {smjer}: {ser['staro']:.0f} → {ser['novo']:.0f} — fiksni troškovi "
            f"pripreme raspoređuju se na {'manju' if smjer == 'manja' else 'veću'} količinu.")

    mat = (diff.get("materijali") or {})
    for p in sorted(mat.get("promjene_cijena", []),
                    key=lambda x: abs(x.get("delta_pct") or 0), reverse=True)[:3]:
        razlozi.append(f"Nabavna cijena '{(p.get('naziv') or p.get('sifra'))[:40]}' "
                       f"promijenjena {p.get('delta_pct'):+.1f}% "
                       f"({p.get('staro'):.4f} → {p.get('novo'):.4f} EUR).")
    if mat.get("dodani"):
        razlozi.append("Dodani materijali: " +
                       ", ".join((x.get("naziv") or x.get("sifra") or "?")[:30]
                                 for x in mat["dodani"][:3]) + ".")
    if mat.get("uklonjeni"):
        razlozi.append("Uklonjeni materijali: " +
                       ", ".join((x.get("naziv") or x.get("sifra") or "?")[:30]
                                 for x in mat["uklonjeni"][:3]) + ".")

    str_ = diff.get("strojevi") or {}
    if str_.get("dodani"):
        razlozi.append("Dodane operacije na strojevima: " + ", ".join(str_["dodani"]) + ".")
    if str_.get("uklonjeni"):
        razlozi.append("Više se ne koriste strojevi: " + ", ".join(str_["uklonjeni"]) + ".")

    tm = diff.get("trosak_materijal") or {}
    tr = diff.get("trosak_rad") or {}
    if tm.get("delta_pct") is not None and tr.get("delta_pct") is not None:
        razlozi.append(f"Materijal {tm['delta_pct']:+.1f}%, rad {tr['delta_pct']:+.1f}% "
                       f"prema prošloj kalkulaciji.")

    if delta is not None:
        smjer = "viša" if delta > 0 else "niža"
        sazetak = f"[DEMO] Cijena koštanja po jedinici {smjer} {abs(delta):.1f}% od prethodne kalkulacije."
    else:
        sazetak = "[DEMO] Nema usporedive cijene po jedinici prema prethodnoj kalkulaciji."
    if razlozi:
        sazetak += f" Glavni razlog: {razlozi[0]}"

    return ObjasnjenjeRazlike(sazetak=sazetak, razlozi=razlozi, razina=razina)


SYSTEM_PONUDA = """Ti pišeš kratke poslovne tekstove ponuda za tiskaru etiketa.
Dobivaš podatke ponude (kupac, stavke s nazivima i količinama) kao JSON.
Napiši samo UVODNI PARAGRAF ponude: pristojan, poslovan, na hrvatskom,
2-4 rečenice. Bez naslova, bez potpisa, bez nabrajanja cijena (one su u tablici).
Ako je kupac strana tvrtka (GmbH, SA, Ltd...), piši na engleskom."""


def _demo_tekst_ponude(podaci: dict) -> str:
    kupac = podaci.get("kupac", "")
    n = len(podaci.get("stavke", []))
    strana = any(t in kupac.upper() for t in ("GMBH", " SA", "LTD", "S.A", "AG"))
    if strana:
        return (f"Thank you for your inquiry. We are pleased to submit our offer for "
                f"{n} label product(s) as specified below. All prices are quoted in EUR, "
                f"EXW, excluding VAT. We remain at your disposal for any questions.")
    return (f"Zahvaljujemo na Vašem upitu. U nastavku dostavljamo ponudu za {n} "
            f"proizvod(a) prema specifikaciji u tablici. Sve cijene su izražene u EUR, "
            f"EXW, bez PDV-a. Stojimo Vam na raspolaganju za sva dodatna pitanja.")


def tekst_ponude(podaci: dict) -> str:
    """Uvodni paragraf ponude. Demo/fallback bez API-ja."""
    if settings.ai_demo or not settings.anthropic_api_key:
        return _demo_tekst_ponude(podaci)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=settings.claude_model,
            max_tokens=1024,
            system=[{"type": "text", "text": SYSTEM_PONUDA,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content":
                       "Podaci ponude (JSON):\n" +
                       json.dumps(podaci, ensure_ascii=False, indent=1)}],
        )
        tekst = next((b.text for b in resp.content if b.type == "text"), "").strip()
        return tekst or _demo_tekst_ponude(podaci)
    except Exception:
        return _demo_tekst_ponude(podaci)


def objasni_razliku(diff: dict, fallback_razina: str) -> ObjasnjenjeRazlike:
    """Generiraj objašnjenje razlike. Redoslijed: demo ako je uključen; inače
    Claude API; ako API ne uspije (npr. nema kredita) — demo kao rezerva."""
    if settings.ai_demo or not settings.anthropic_api_key:
        return _demo_objasnjenje(diff, fallback_razina)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.parse(
            model=settings.claude_model,
            max_tokens=2048,
            system=[{"type": "text", "text": SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content":
                       "Usporedba kalkulacija (JSON):\n" +
                       json.dumps(diff, ensure_ascii=False, indent=1)}],
            output_format=ObjasnjenjeRazlike,
        )
        rezultat = resp.parsed_output
        if rezultat is None:
            return _demo_objasnjenje(diff, fallback_razina)
        if rezultat.razina not in ("info", "paznja", "kriticno"):
            rezultat.razina = fallback_razina
        return rezultat
    except Exception:
        d = _demo_objasnjenje(diff, fallback_razina)
        d.sazetak = d.sazetak.replace("[DEMO]", "[DEMO — API nedostupan]")
        return d


# ── Prijedlog marže (uči iz direktorovih potvrda/korekcija) ────────────────────

class PrijedlogMarze(BaseModel):
    marza_pct: float
    obrazlozenje: str


SYSTEM_MARZA = """Ti si iskusni komercijalist tiskare etiketa. Predlažeš STOPU MARŽE (%)
za stavku ponude. Dobivaš JSON s: trenutnom situacijom (serija, trošak ukupno i po 1000 kom,
promjena troška prema prošloj kalkulaciji) te POVIJEŠĆU ODLUKA — svaka prošla marža dolazi
S KONTEKSTOM u kojem je donesena (koja serija, koji trošak/1000, kada, je li direktor
prihvatio ili ispravio AI prijedlog i zašto).

KLJUČNO: marža NIJE statičan broj koji se prepisuje. Uči OBRAZAC iz odluka:
- kako direktor mijenja maržu s VELIČINOM SERIJE (manja serija u pravilu podnosi višu maržu)
- kako reagira na RAST TROŠKA materijala (dio poskupljenja ide na maržu ili se amortizira)
- novije odluke vrijede više od starijih; komentari direktora su izravna uputa
- odluke za ISTI proizvod > odluke za istog kupca > opća praksa
Prilagodi prijedlog RAZLICI između tadašnjeg i sadašnjeg konteksta — nikad slijepo kopiraj.

marza_pct: broj 20-70. obrazlozenje: 1-2 rečenice na hrvatskom koje POKAZUJU usporedbu
konteksta (npr. "kod serije 6.000 dana je 50 %; sada je serija upola manja i papir +8 % → 54 %")."""


def _demo_marza(ctx: dict) -> PrijedlogMarze:
    """Prijedlog bez API-ja: NAJBLIŽI KONTEKST + prilagodba za razlike.
    Ne prepisuje zadnju vrijednost — traži odluku s najsličnijom serijom
    (prednost istom proizvodu i novijim odlukama) pa korigira za razliku
    u količini i kretanje troška po 1000 kom."""
    import math
    from datetime import date as _date

    sada = ctx.get("trenutno") or {}
    serija = sada.get("serija_tisuca")
    ck1000 = sada.get("ck_po_1000")

    # kandidati: direktorove odluke (najjači signal) + korištene marže iz ponuda
    kandidati = []
    for o in ctx.get("odluke") or []:
        k = o.get("kontekst") or {}
        m = o.get("direktor_marza")
        if m is None:
            continue
        kandidati.append({"marza": m, "serija": k.get("serija_tisuca"),
                          "ck_1000": k.get("ck_po_1000"), "datum": o.get("datum"),
                          "isti": bool(o.get("isti_proizvod")), "tezina": 0.6,
                          "izvor": "direktorova odluka", "komentar": o.get("komentar")})
    for p in ctx.get("povijest_prodaja") or []:
        if p.get("marza") is None:
            continue
        kandidati.append({"marza": p["marza"], "serija": p.get("serija_tisuca"),
                          "ck_1000": p.get("ck_po_1000"), "datum": p.get("datum"),
                          "isti": bool(p.get("isti_proizvod")), "tezina": 1.0,
                          "izvor": "korištena marža", "komentar": None})
    if not kandidati:
        return PrijedlogMarze(marza_pct=30.0,
                              obrazlozenje="[DEMO] Nema povijesti za ovaj proizvod ni kupca — standardnih 30 %.")

    # najbliži kontekst: sličnost serije (log skala) + bonus isti proizvod + svježina
    def udaljenost(k):
        d = 0.0
        if serija and k.get("serija"):
            d += abs(math.log(max(serija, 1e-6) / max(k["serija"], 1e-6)))
        else:
            d += 1.0
        if not k["isti"]:
            d += 1.5
        d += k["tezina"] * 0.3
        return d

    best = min(kandidati, key=udaljenost)
    baza = float(best["marza"])
    razlozi = []
    opis_kad = f"({best['datum']})" if best.get("datum") else ""
    if best.get("serija"):
        razlozi.append(f"{best['izvor']} {opis_kad}: {baza:g} % kod serije "
                       f"{best['serija']:,.0f} tis.".replace(",", "."))
    else:
        razlozi.append(f"{best['izvor']} {opis_kad}: {baza:g} %")
    if best.get("komentar"):
        razlozi.append(f"direktor: \"{best['komentar']}\"")

    prilagodba = 0.0
    # 1) razlika u količini: manja serija -> viša marža (i obratno), ±1pp po prepolavljanju
    if serija and best.get("serija") and best["serija"] > 0:
        omjer = serija / best["serija"]
        if omjer < 0.95 or omjer > 1.05:
            korak = -math.log2(omjer)          # 0.5x serija -> +1; 2x -> -1
            kor = max(-4.0, min(4.0, round(korak * 1.5)))
            if kor:
                prilagodba += kor
                razlozi.append(f"serija je {'manja' if omjer < 1 else 'veća'} "
                               f"({omjer:.1f}×) → {kor:+g} pp")
    # 2) kretanje troška po 1000 od tada
    if ck1000 and best.get("ck_1000") and best["ck_1000"] > 0:
        d_ck = (ck1000 - best["ck_1000"]) / best["ck_1000"] * 100
        if abs(d_ck) >= 5:
            kor = 2.0 if d_ck > 0 else -1.0
            prilagodba += kor
            razlozi.append(f"trošak/1000 od tada {d_ck:+.0f} % → {kor:+g} pp")
    # 3) trend prema prošloj kalkulaciji (ako nema usporedbe troška iz povijesti)
    delta = sada.get("ck_delta_pct")
    if delta is not None and abs(delta) >= 10 and not any("trošak/1000" in r for r in razlozi):
        kor = 2.0 if delta > 0 else -2.0
        prilagodba += kor
        razlozi.append(f"trošak vs prošla kalkulacija {delta:+.1f} % → {kor:+g} pp")

    pct = max(20.0, min(70.0, round(baza + prilagodba)))
    return PrijedlogMarze(marza_pct=pct, obrazlozenje="[DEMO] " + "; ".join(razlozi) + f" → {pct:g} %.")


def predlozi_marzu(ctx: dict, primjeri: list[dict]) -> PrijedlogMarze:
    """AI prijedlog marže. ctx = brojke iz koda; primjeri = direktorov feedback."""
    if settings.ai_demo or not settings.anthropic_api_key:
        return _demo_marza(ctx)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.parse(
            model=settings.claude_model,
            max_tokens=1024,
            system=[{"type": "text", "text": SYSTEM_MARZA,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content":
                       "Podaci (trenutna situacija + povijest odluka s kontekstom, JSON):\n" +
                       json.dumps(ctx, ensure_ascii=False)}],
            output_format=PrijedlogMarze,
        )
        r = resp.parsed_output
        if r is None:
            return _demo_marza(ctx)
        r.marza_pct = max(20.0, min(70.0, r.marza_pct))
        return r
    except Exception:
        d = _demo_marza(ctx)
        d.obrazlozenje = d.obrazlozenje.replace("[DEMO]", "[DEMO — API nedostupan]")
        return d


# ── AI pregled kalkulacije: pronalazak problema/anomalija ──────────────────────

class Napomena(BaseModel):
    tekst: str
    razina: str   # info | paznja | kriticno


class PregledKalkulacije(BaseModel):
    napomene: list[Napomena]


SYSTEM_PREGLED = """Ti si kontrolor kalkulacija u tiskari etiketa. Dobivaš JSON jedne
kalkulacije: materijale (s uobičajenom cijenom istog materijala iz drugih kalkulacija),
operacije rada, seriju te usporedbu s prethodnom kalkulacijom istog proizvoda.

Pronađi STVARNE PROBLEME (ne prepričavaj podatke):
- cijene materijala koje drastično odstupaju od uobičajenih (greške unosa!)
- stavke s cijenom ili količinom 0, operacije bez vremena ili cijene sata
- neobične skokove troška prema prošloj kalkulaciji koje treba provjeriti
- sve što bi direktora moglo skupo koštati ako prođe neprimijećeno

Za svaki problem: tekst (1 rečenica, konkretno, s brojkama) i razina
(kriticno = vjerojatno greška; paznja = provjeriti; info = dobro znati).
Ako problema NEMA, vrati praznu listu — ne izmišljaj."""


def _demo_pregled(ctx: dict) -> list[Napomena]:
    naps: list[Napomena] = []
    for m in ctx.get("materijali") or []:
        c, tip = m.get("jed_cijena"), m.get("tipicna_cijena")
        naziv = (m.get("naziv") or m.get("sifra") or "?")[:45]
        if c is not None and tip and tip > 0:
            d = (c - tip) / tip * 100
            if abs(d) >= 60:
                naps.append(Napomena(
                    tekst=f"'{naziv}': jedinična cijena {c:.4f} € odstupa {d:+.0f} % od "
                          f"uobičajene ({tip:.4f} € u ostalim kalkulacijama) — moguća greška unosa.",
                    razina="kriticno" if abs(d) >= 85 else "paznja"))
        if c == 0:
            naps.append(Napomena(tekst=f"'{naziv}': jedinična cijena je 0 € — trošak nije uračunat.",
                                 razina="kriticno"))
    for o in ctx.get("operacije") or []:
        stroj = (o.get("stroj") or "?")[:30]
        if o.get("cijena_h") == 0 or o.get("iznos") == 0:
            naps.append(Napomena(tekst=f"Operacija na '{stroj}' ima cijenu/iznos 0 € — rad nije uračunat.",
                                 razina="paznja"))
        if o.get("vrijeme_min") == 0:
            naps.append(Napomena(tekst=f"Operacija na '{stroj}' ima vrijeme 0 — provjeriti normativ.",
                                 razina="info"))
    delta = ctx.get("ck_delta_pct")
    if delta is not None and abs(delta) >= 25:
        naps.append(Napomena(
            tekst=f"Trošak po jedinici {delta:+.1f} % prema prošloj kalkulaciji — provjeriti prije ponude.",
            razina="kriticno" if abs(delta) >= 50 else "paznja"))
    if not ctx.get("serija"):
        naps.append(Napomena(tekst="Serija nije upisana — cijena po jedinici se ne može računati.",
                             razina="paznja"))
    for n in naps:
        n.tekst = "[DEMO] " + n.tekst
    return naps[:8]


def pregledaj_kalkulaciju(ctx: dict) -> list[Napomena]:
    """AI pregled kalkulacije — vraća listu problema (prazna = sve OK)."""
    if settings.ai_demo or not settings.anthropic_api_key:
        return _demo_pregled(ctx)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.parse(
            model=settings.claude_model,
            max_tokens=2048,
            system=[{"type": "text", "text": SYSTEM_PREGLED,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content":
                       "Kalkulacija (JSON):\n" + json.dumps(ctx, ensure_ascii=False)}],
            output_format=PregledKalkulacije,
        )
        r = resp.parsed_output
        if r is None:
            return _demo_pregled(ctx)
        for n in r.napomene:
            if n.razina not in ("info", "paznja", "kriticno"):
                n.razina = "paznja"
        return r.napomene[:10]
    except Exception:
        return _demo_pregled(ctx)
