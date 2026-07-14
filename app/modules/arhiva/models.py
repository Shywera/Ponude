"""Modeli arhive kalkulacija.

Proizvod (etiketa) je centralni entitet — usporedba cijena ide po proizvodu.
Kalkulacija = jedan uvezeni Excel "Prodajna cijena <broj>.xlsx"; troškovi se
RAČUNAJU PONOVNO iz sirovih stavki (materijal + rad), Excelov keš prodajne
cijene se ne koristi (poznati `==` bug u dijelu izvornih datoteka).
"""
from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Kupac(Base):
    __tablename__ = "kupac"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    naziv: Mapped[str] = mapped_column(String, unique=True, index=True)

    # podaci za zaglavlje ponude + PDV logika
    u_hrvatskoj: Mapped[bool] = mapped_column(Boolean, default=True)   # HR -> obračun PDV-a; inače reverse charge
    adresa: Mapped[str | None] = mapped_column(String, nullable=True)  # ulica, poštanski broj i grad
    oib: Mapped[str | None] = mapped_column(String, nullable=True)
    kontakt: Mapped[str | None] = mapped_column(String, nullable=True)  # tel/mob/email
    np_osoba: Mapped[str | None] = mapped_column(String, nullable=True)  # "n/p g. ..."
    jezik: Mapped[str | None] = mapped_column(String, nullable=True)     # hr|en|de|it — jezik ponuda

    proizvodi: Mapped[list["Proizvod"]] = relationship(back_populates="kupac")


class Proizvod(Base):
    """Etiketa/proizvod — ključ usporedbe. Šifra artikla se vadi iz naziva
    (npr. "Somersby Pear SRB leđna 40000546" -> 40000546); ako je nema,
    ključ je normalizirani naziv."""
    __tablename__ = "proizvod"
    __table_args__ = (UniqueConstraint("kupac_id", "kljuc", name="uq_proizvod_kupac_kljuc"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kupac_id: Mapped[int] = mapped_column(ForeignKey("kupac.id"), index=True)
    naziv: Mapped[str] = mapped_column(String)
    sifra_artikla: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    kljuc: Mapped[str] = mapped_column(String, index=True)  # sifra ili normalizirani naziv
    kreiran: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    kupac: Mapped["Kupac"] = relationship(back_populates="proizvodi")
    kalkulacije: Mapped[list["Kalkulacija"]] = relationship(
        back_populates="proizvod", order_by="Kalkulacija.datum")


class Kalkulacija(Base):
    __tablename__ = "kalkulacija"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proizvod_id: Mapped[int] = mapped_column(ForeignKey("proizvod.id"), index=True)

    broj: Mapped[str] = mapped_column(String, unique=True, index=True)   # KALKULACIJA BR
    normativ_br: Mapped[str | None] = mapped_column(String, nullable=True)
    datum: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    kupac_naziv: Mapped[str] = mapped_column(String)
    naziv_proizvoda: Mapped[str] = mapped_column(String)

    serija: Mapped[float | None] = mapped_column(Float, nullable=True)       # količina
    serija_jedinica: Mapped[str | None] = mapped_column(String, nullable=True)  # "tisuća"
    glavni_stroj: Mapped[str | None] = mapped_column(String, nullable=True)

    # PONOVNO IZRAČUNATI troškovi (EUR) — iz stavki, ne iz Excel keša
    trosak_materijal: Mapped[float] = mapped_column(Float, default=0.0)
    trosak_rad: Mapped[float] = mapped_column(Float, default=0.0)
    vanjska_usluga: Mapped[float] = mapped_column(Float, default=0.0)
    ck_total: Mapped[float] = mapped_column(Float, default=0.0)          # mat + rad + vanjska
    ck_po_jedinici: Mapped[float | None] = mapped_column(Float, nullable=True)  # ck_total / serija

    datoteka: Mapped[str | None] = mapped_column(String, nullable=True)
    uvezeno: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    napomena_uvoza: Mapped[str | None] = mapped_column(Text, nullable=True)  # npr. "izvor imao ==/#VALUE! greške"

    # AI analiza razlike prema prethodnoj kalkulaciji (faza 4; NULL dok se ne generira)
    ai_sazetak: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_razlozi: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON lista stringova
    ai_razina: Mapped[str | None] = mapped_column(String, nullable=True)  # info | paznja | kriticno

    proizvod: Mapped["Proizvod"] = relationship(back_populates="kalkulacije")
    artikli: Mapped[list["KalkulacijaArtikl"]] = relationship(
        back_populates="kalkulacija", cascade="all, delete-orphan")
    materijali: Mapped[list["KalkulacijaMaterijal"]] = relationship(
        back_populates="kalkulacija", cascade="all, delete-orphan")
    operacije: Mapped[list["KalkulacijaOperacija"]] = relationship(
        back_populates="kalkulacija", cascade="all, delete-orphan")


class KalkulacijaArtikl(Base):
    """Artikl/mutacija unutar kalkulacije (1, 2 ili 6 po datoteci)."""
    __tablename__ = "kalkulacija_artikl"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kalkulacija_id: Mapped[int] = mapped_column(ForeignKey("kalkulacija.id"), index=True)

    rb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    naziv: Mapped[str | None] = mapped_column(String, nullable=True)
    sirina_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    visina_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    broj_boja: Mapped[float | None] = mapped_column(Float, nullable=True)
    broj_prolaza: Mapped[float | None] = mapped_column(Float, nullable=True)
    lak: Mapped[str | None] = mapped_column(String, nullable=True)
    dorada: Mapped[str | None] = mapped_column(String, nullable=True)      # spojeno G-J
    tip_papira: Mapped[str | None] = mapped_column(String, nullable=True)
    gramatura: Mapped[str | None] = mapped_column(String, nullable=True)
    nabavna_cijena: Mapped[str | None] = mapped_column(String, nullable=True)

    udio: Mapped[float | None] = mapped_column(Float, nullable=True)
    kolicina: Mapped[float | None] = mapped_column(Float, nullable=True)
    ck_total: Mapped[float | None] = mapped_column(Float, nullable=True)   # udio * (mat+rad), izračunato

    kalkulacija: Mapped["Kalkulacija"] = relationship(back_populates="artikli")


class KalkulacijaMaterijal(Base):
    __tablename__ = "kalkulacija_materijal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kalkulacija_id: Mapped[int] = mapped_column(ForeignKey("kalkulacija.id"), index=True)

    sifra: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    naziv: Mapped[str | None] = mapped_column(String, nullable=True)
    jedinica: Mapped[str | None] = mapped_column(String, nullable=True)
    kolicina: Mapped[float | None] = mapped_column(Float, nullable=True)
    jed_cijena: Mapped[float | None] = mapped_column(Float, nullable=True)   # EUR
    vrijednost: Mapped[float | None] = mapped_column(Float, nullable=True)   # EUR

    kalkulacija: Mapped["Kalkulacija"] = relationship(back_populates="materijali")


class KalkulacijaOperacija(Base):
    __tablename__ = "kalkulacija_operacija"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kalkulacija_id: Mapped[int] = mapped_column(ForeignKey("kalkulacija.id"), index=True)

    stroj: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    operacija: Mapped[str | None] = mapped_column(String, nullable=True)
    proces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vrijeme_min: Mapped[float | None] = mapped_column(Float, nullable=True)  # minute
    cijena_h: Mapped[float | None] = mapped_column(Float, nullable=True)     # EUR/h
    iznos: Mapped[float | None] = mapped_column(Float, nullable=True)        # EUR

    kalkulacija: Mapped["Kalkulacija"] = relationship(back_populates="operacije")
