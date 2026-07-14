# CLAUDE.md

Kontekst za Claude Code. Ovo je **jedini kontekst koji putuje između računala** kroz git —
Claudova lokalna memorija se NE sinkronizira. Na kraju sesije ažuriraj "Trenutno stanje" i
pokreni `spremi.bat`.

## Što je ovo
**Ponude / kalkulacije** web-aplikacija za tiskaru samoljepljivih etiketa:
- **Arhiva** starih Excel kalkulacija ("Prodajna cijena") — uvoz iz foldera, parsiranje,
  pretraga po kupcu/proizvodu.
- **Generiranje ponuda (PDF)** uz pomoć **Claude API-ja**; direktor vidi razlike u cijeni
  u odnosu na prijašnje ponude s upozorenjima.
- Prijava + korisnici + audit, statistika.
FastAPI + SQLAlchemy + SQLite + Jinja2 + reportlab (PDF) + openpyxl (xlsx) + anthropic SDK.

## Pokretanje i alati (Windows, .bat)
- `run.bat` / `dev-wifi.bat` — port **8010**; prvi put gradi `.venv` (+ treba `.env`, vidi dolje).
- `backup.bat` — backup baze. `update.bat` — `git pull` + deps. `spremi.bat` — add+commit+pull+push.
- Ručni test: `.venv\Scripts\python.exe` + FastAPI `TestClient`.

## Arhitektura
```
app/main.py                FastAPI: create_all, seed admin, auth/audit middleware, routeri
app/core/                  config (pydantic-settings, .env), database, backup, templating
app/modules/ai/            claude.py — Claude API pozivi (generiranje ponude); models
app/modules/arhiva/        import_folder, parser, service, routes — uvoz/čitanje starih kalkulacija
app/modules/ponude/        models, pdf (reportlab), xlsx (openpyxl), radna, routes, logo.png
app/modules/auth/          security (dozvole/bcrypt) + models (korisnik/audit) + routes
app/modules/statistika/    statistika/izvještaji
app/templates/             aiponuda/ + arhiva/ + auth/ + ...
```

## Konfiguracija (`.env`) — VAŽNO
Aplikacija čita ključeve iz `.env` preko `settings` (pydantic-settings), npr.:
- `ANTHROPIC_API_KEY` — **tajni** Claude API ključ. **NIKAD ne commitati.** Kod ga koristi
  preko `settings.anthropic_api_key` (`app/modules/ai/claude.py`), ne hardkodirati.
- `SECRET_KEY` — potpis session cookieja. `AI_DEMO` — demo/flag.
- `DATABASE_URL` — zadano `sqlite:///./ponude.db`.
> `.env`, `ponude.db`, `backup/`, `.venv`, `*.log` su u `.gitignore` i NE idu na GitHub.

## Konvencije i zamke
- **Model:** Claude 5 obitelj / Opus 4.8. ID-evi: Opus 4.8 `claude-opus-4-8`, Sonnet 5
  `claude-sonnet-5`, Haiku 4.5 `claude-haiku-4-5-20251001`. Koristi najnovije za nove značajke.
- **pydantic-settings:** `.env` varijabla radi samo ako postoji polje u `Settings`.
- **.bat MORA biti CRLF** (Write daje LF → cmd se zatvori): `awk '{sub(/\r$/,""); printf "%s\r\n",$0}'`.
- **Portovi:** ERP=8000, WMS-app=8600, Reklamacije-app=8601, **Ponude-app=8010**.
- Poznata zamka iz ranije: parser je na više mjesta koristio `==` umjesto dodjele/usporedbe
  (provjeri `app/modules/arhiva/parser.py` prije izmjena parsiranja).

## Sinkronizacija kuća/posao
Sinkronizira se **samo kod + CLAUDE.md**. Baza (`ponude.db`), `.env` i `backup/` su lokalni po
računalu. Na novom računalu: `git clone` → napravi `.env` s `ANTHROPIC_API_KEY` (ne dolazi s
GitHuba!) → `run.bat`. Tijek: `spremi.bat` na jednom → `update.bat` na drugom.

## Trenutno stanje (ažuriraj na kraju sesije)
- 2026-07: čisti upload na GitHub (`Shywera/Ponude`) nakon što je stari .gitignore bio pokvaren
  i uvukao `.env`/bazu (počišćeno; ključ nije bio gurnut). (dopuni po potrebi)
