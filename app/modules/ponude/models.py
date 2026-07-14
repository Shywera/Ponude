"""Modeli upita i ponuda.

Upit = kupčev zahtjev s popisom etiketa (stavki). Svaka stavka referencira
kalkulaciju iz arhive i nosi maržu. Ponuda = SNAPSHOT upita u trenutku
generiranja (cijene se zamrzavaju), s brojem P-GGGG-NNN i PDF ispisom.
"""
from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Integer,
                        String, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.modules.arhiva import models as _arhiva  # noqa: F401 — razrješava
# string-reference ("Kupac", "Proizvod", "Kalkulacija") i kad se ovaj modul
# učita samostalno (skripte, testovi)


class Upit(Base):
    __tablename__ = "upit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kupac_id: Mapped[int] = mapped_column(ForeignKey("kupac.id"), index=True)
    naslov: Mapped[str] = mapped_column(String)
    datum: Mapped[date] = mapped_column(Date, default=date.today)
    status: Mapped[str] = mapped_column(String, default="otvoren")  # otvoren | ponuda
    napomena: Mapped[str | None] = mapped_column(Text, nullable=True)
    kreiran: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # Excel/DAP ponude: ukupna cijena prijevoza (kamion) za cijeli upit, EUR.
    prijevoz_ukupno: Mapped[float | None] = mapped_column(Float, nullable=True)

    kupac = relationship("Kupac")
    stavke: Mapped[list["UpitStavka"]] = relationship(
        back_populates="upit", cascade="all, delete-orphan",
        order_by="UpitStavka.id")
    ponude: Mapped[list["Ponuda"]] = relationship(back_populates="upit")


class UpitStavka(Base):
    __tablename__ = "upit_stavka"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upit_id: Mapped[int] = mapped_column(ForeignKey("upit.id"), index=True)
    proizvod_id: Mapped[int] = mapped_column(ForeignKey("proizvod.id"))
    kalkulacija_id: Mapped[int] = mapped_column(ForeignKey("kalkulacija.id"))

    kolicina: Mapped[float | None] = mapped_column(Float, nullable=True)  # default = serija kalkulacije
    marza_pct: Mapped[float] = mapped_column(Float, default=30.0)

    # logistika (iz radne tablice) — za DAP izračun i excel ponudu
    kom_kutija: Mapped[float | None] = mapped_column(Float, nullable=True)    # etiketa po kutiji
    kutija_paleta: Mapped[float | None] = mapped_column(Float, nullable=True)  # kutija po paleti
    alat_cijena: Mapped[float | None] = mapped_column(Float, nullable=True)   # one-time tools EUR
    tehnika: Mapped[str | None] = mapped_column(Text, nullable=True)          # JSON tehničkih podataka

    # AI prijedlog marže (direktor potvrđuje kvačicom ili ispravlja)
    ai_marza_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_obrazlozenje: Mapped[str | None] = mapped_column(Text, nullable=True)

    upit: Mapped["Upit"] = relationship(back_populates="stavke")
    proizvod = relationship("Proizvod")
    kalkulacija = relationship("Kalkulacija")

    # --- izračuni (uvijek iz kalkulacije, nikad iz keša) -------------------
    @property
    def ck_total(self) -> float:
        return self.kalkulacija.ck_total if self.kalkulacija else 0.0

    @property
    def prodajna_ukupno(self) -> float:
        """PRODAJNA VRIJEDNOST = (marža/100 + 1) × CK — ista formula kao u Excelu."""
        return round((self.marza_pct / 100.0 + 1.0) * self.ck_total, 2)

    @property
    def prodajna_po_jedinici(self) -> float | None:
        q = self.kolicina or (self.kalkulacija.serija if self.kalkulacija else None)
        if not q:
            return None
        return round(self.prodajna_ukupno / q, 4)

    @property
    def marza_iznos(self) -> float:
        return round(self.prodajna_ukupno - self.ck_total, 2)

    # --- logistika / DAP ----------------------------------------------------
    @property
    def kolicina_kom(self) -> float | None:
        """Količina u komadima (jedinica kalkulacije je 'tisuća')."""
        q = self.kolicina or (self.kalkulacija.serija if self.kalkulacija else None)
        return q * 1000.0 if q else None

    @property
    def et_po_paleti(self) -> float | None:
        if self.kom_kutija and self.kutija_paleta:
            return self.kom_kutija * self.kutija_paleta
        return None

    @property
    def palete(self) -> int | None:
        """Broj paleta za narudžbu = ceil(količina kom / etiketa po paleti)."""
        import math
        if self.kolicina_kom and self.et_po_paleti:
            return math.ceil(self.kolicina_kom / self.et_po_paleti)
        return None

    @property
    def exw_1000(self) -> float | None:
        """EXW EUR/1000 kom = prodajna po jedinici (jedinica = tisuća)."""
        return self.prodajna_po_jedinici


class Ponuda(Base):
    __tablename__ = "ponuda"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upit_id: Mapped[int] = mapped_column(ForeignKey("upit.id"), index=True)
    broj: Mapped[str] = mapped_column(String, unique=True, index=True)  # P-2026-001
    datum: Mapped[date] = mapped_column(Date, default=date.today)
    kupac_naziv: Mapped[str] = mapped_column(String)
    uvodni_tekst: Mapped[str | None] = mapped_column(Text, nullable=True)
    napomene: Mapped[str | None] = mapped_column(Text, nullable=True)
    vrijedi_dana: Mapped[int] = mapped_column(Integer, default=30)
    kreirana: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # PDV i uvjeti (snapshot u trenutku generiranja)
    pdv_obracun: Mapped[bool] = mapped_column(Boolean, default=True)   # HR kupac -> True
    pdv_stopa: Mapped[float] = mapped_column(Float, default=25.0)
    paritet: Mapped[str | None] = mapped_column(String, nullable=True,
                                                default="FCO adresa Naručitelja")
    potpisnik: Mapped[str | None] = mapped_column(String, nullable=True)
    jezik: Mapped[str] = mapped_column(String, default="hr")        # hr | en | de | it
    stil: Mapped[str] = mapped_column(String, default="medvedgrad")  # medvedgrad | excel
    # tok: nacrt -> (ai_nacrt: obavezan pregled AI odluka) -> za_slanje -> poslana -> prihvacena|odbijena
    status: Mapped[str] = mapped_column(String, default="nacrt")

    @property
    def pdv_iznos(self) -> float:
        return round(self.ukupno * self.pdv_stopa / 100.0, 2) if self.pdv_obracun else 0.0

    @property
    def ukupno_s_pdv(self) -> float:
        return round(self.ukupno + self.pdv_iznos, 2)

    upit: Mapped["Upit"] = relationship(back_populates="ponude")
    stavke: Mapped[list["PonudaStavka"]] = relationship(
        back_populates="ponuda", cascade="all, delete-orphan",
        order_by="PonudaStavka.id")

    @property
    def ukupno(self) -> float:
        return round(sum(s.iznos for s in self.stavke), 2)


class PonudaStavka(Base):
    """Zamrznuta stavka ponude — kopija vrijednosti u trenutku generiranja."""
    __tablename__ = "ponuda_stavka"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ponuda_id: Mapped[int] = mapped_column(ForeignKey("ponuda.id"), index=True)
    kalkulacija_broj: Mapped[str | None] = mapped_column(String, nullable=True)

    naziv: Mapped[str] = mapped_column(String)
    opis: Mapped[str | None] = mapped_column(String, nullable=True)  # npr. "format: 9,9x6,4 cm"
    kolicina: Mapped[float | None] = mapped_column(Float, nullable=True)
    jedinica: Mapped[str | None] = mapped_column(String, nullable=True)
    jed_cijena: Mapped[float | None] = mapped_column(Float, nullable=True)  # EUR po jedinici
    iznos: Mapped[float] = mapped_column(Float, default=0.0)                # EUR ukupno
    marza_pct: Mapped[float | None] = mapped_column(Float, nullable=True)   # interno (ne ide u PDF)
    ck_total: Mapped[float | None] = mapped_column(Float, nullable=True)    # interno

    # excel/DAP stil — zamrznuto pri generiranju
    exw_1000: Mapped[float | None] = mapped_column(Float, nullable=True)      # EUR/1000
    prijevoz_1000: Mapped[float | None] = mapped_column(Float, nullable=True)  # EUR/1000
    dap_1000: Mapped[float | None] = mapped_column(Float, nullable=True)      # EUR/1000
    alat_cijena: Mapped[float | None] = mapped_column(Float, nullable=True)   # one-time EUR
    tehnika: Mapped[str | None] = mapped_column(Text, nullable=True)          # JSON

    ponuda: Mapped["Ponuda"] = relationship(back_populates="stavke")
