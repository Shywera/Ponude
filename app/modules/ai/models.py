"""Povratne informacije direktora na AI prijedloge — baza iz koje AI uči.

Svaki AI prijedlog (objašnjenje razlike, prijedlog marže, tekst) direktor
ocijeni kvačicom (dobro / loše) ili implicitno ispravi (postavi drugu maržu).
Zapisi se koriste kao primjeri u budućim AI prijedlozima za istog kupca /
proizvod — tako sustav "uči" bez ponovnog treniranja modela.
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AIFeedback(Base):
    __tablename__ = "ai_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    username: Mapped[str | None] = mapped_column(String(60))

    tip: Mapped[str] = mapped_column(String(30), index=True)   # objasnjenje | marza | tekst
    kupac_naziv: Mapped[str | None] = mapped_column(String, index=True)
    proizvod_naziv: Mapped[str | None] = mapped_column(String, index=True)

    prijedlog: Mapped[str | None] = mapped_column(Text)        # što je AI predložio (tekst/JSON)
    kontekst: Mapped[str | None] = mapped_column(Text)          # JSON konteksta odluke (serija, trošak, delta...)
    ocjena: Mapped[str] = mapped_column(String(20))            # dobro | lose | korigirano
    korekcija: Mapped[str | None] = mapped_column(Text)        # direktorova vrijednost (npr. marža)
    komentar: Mapped[str | None] = mapped_column(Text)         # direktorov razlog


class AINapomena(Base):
    """AI-jev nalaz problema na kalkulaciji — direktor potvrđuje ili odbacuje.
    Odluka se dodatno bilježi u AIFeedback (tip='napomena') radi učenja."""
    __tablename__ = "ai_napomena"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kalkulacija_id: Mapped[int] = mapped_column(Integer, index=True)
    created: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    tekst: Mapped[str] = mapped_column(Text)
    razina: Mapped[str] = mapped_column(String(20), default="paznja")  # info | paznja | kriticno
    status: Mapped[str] = mapped_column(String(20), default="nova")    # nova | potvrdjena | odbacena
    komentar: Mapped[str | None] = mapped_column(Text)                 # direktorov razlog kod odbacivanja
    odlucio: Mapped[str | None] = mapped_column(String(60))            # username
