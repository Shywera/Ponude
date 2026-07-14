from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # SQLite lokalno; za Postgres postavi DATABASE_URL u .env.
    database_url: str = "sqlite:///./ponude.db"

    # Claude API — objašnjenja razlika u cijeni + tekst ponude (faza 4).
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-4-8"
    # AI_DEMO=1 -> objašnjenja generira kod (pravila), bez API poziva.
    # Za pravi Claude: makni AI_DEMO iz .env (treba kredite na računu).
    ai_demo: bool = False

    # Potpisivanje session cookieja (prijava). Postavljeno u .env.
    secret_key: str = "dev-ponude-promijeni-me-u-env"

    # Lozinka početnog admina (koristi se samo kad je baza bez korisnika).
    admin_password: str = "admin"

    # ── Podaci tvrtke za dokumente (PDF/Excel/UI) — prave podatke postavi u .env ──
    firma_brand: str = "DEMOTISAK"
    firma_podnaslov: str = "TISKARA"
    firma_naziv: str = "Demo Tisak d.o.o."
    firma_adresa: str = "A  Ulica primjera 1, 10000 Zagreb, Croatia"
    firma_tel: str = "T  +385 1 000 0000"
    firma_fax: str = "F  +385 1 000 0001"
    firma_web: str = "W  www.example.com"
    firma_registri: str = "MB 00000000,  OIB 00000000000"
    firma_mjesto: str = "Zagreb"


settings = Settings()
