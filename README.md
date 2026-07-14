# Ponude — arhiva kalkulacija i AI generiranje ponuda

Web aplikacija koja digitalizira arhivu proizvodnih kalkulacija (Excel) i iz njih
generira profesionalne ponude (PDF) na 4 jezika, uz AI usporedbu cijena s
prijašnjim ponudama istog kupca.

## Mogućnosti

- **Arhiva kalkulacija** — masovni uvoz starih Excel kalkulacija (parsiranje po
  strukturi radne knjige), pretraga po kupcu/proizvodu, povijest cijena
- **Šifrarnik kupaca** — adresa, OIB, kontakt, PDV status za zaglavlja ponuda
- **Radna tablica** — uvoz upita kupca, automatsko spajanje stavki s arhivom,
  logistika i DAP izračun
- **Generiranje ponude (PDF)** — profesionalni predložak na HR/EN/DE/IT;
  podaci tvrtke konfigurabilni kroz `.env`
- **AI usporedba cijena (Claude API)** — upozorenja na odstupanja u odnosu na
  prijašnje ponude istog kupca, s objašnjenjima
- **Excel izvoz**, prijava korisnika, audit log, automatski backup

## Tehnologije

FastAPI · SQLAlchemy · SQLite · Jinja2 · HTMX · reportlab · openpyxl · Anthropic (Claude) API

## Brzi start (Windows)

1. Instalirajte [Python 3](https://python.org)
2. Pokrenite **`run.bat`** — izgradi okruženje; kreirajte `.env` (vidi dolje)
3. Otvorite **http://127.0.0.1:8010**

## Konfiguracija (`.env`)

| Varijabla | Opis |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API ključ (za AI usporedbe); bez njega radi `AI_DEMO=1` način |
| `FIRMA_BRAND`, `FIRMA_NAZIV`, `FIRMA_ADRESA`, `FIRMA_TEL`, `FIRMA_WEB`, `FIRMA_REGISTRI` | podaci tvrtke za PDF zaglavlje (zadano demo) |
| `SECRET_KEY`, `ADMIN_PASSWORD` | sesija i početni admin |

## Povezani projekti

[ERP/MES/WMS](https://github.com/Shywera/erp) · [WMS](https://github.com/Shywera/wms) ·
[Reklamacije/QMS](https://github.com/Shywera/reklamacije) · [Alati](https://github.com/Shywera/tools)
