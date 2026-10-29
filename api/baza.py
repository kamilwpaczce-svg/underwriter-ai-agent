"""SQLAlchemy 2.0: modele `Wniosek`, `ZdarzenieAudytu`; fabryka silnika i sesji.

Typ JSON mapowany na JSONB w Postgresie przez `with_variant` - w SQLite (testy) trafia
jako zwykly JSON (serializacja/parsowanie przez sam SQLAlchemy, bez utraty danych).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Engine,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    create_engine,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

JSONTyp = JSON().with_variant(JSONB(), "postgresql")


def _teraz() -> datetime:
    return datetime.now(timezone.utc)


class Baza(DeclarativeBase):
    pass


class Wniosek(Baza):
    __tablename__ = "wnioski"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nazwa_pliku: Mapped[str] = mapped_column(String, nullable=False)
    typ_mime: Mapped[str] = mapped_column(String, nullable=False)
    rozmiar_b: Mapped[int] = mapped_column(Integer, nullable=False)
    blob_nazwa: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PRZETWARZANIE")
    thread_id: Mapped[str] = mapped_column(String, nullable=False)
    podsumowanie: Mapped[dict | None] = mapped_column(JSONTyp, nullable=True)
    log_wezlow: Mapped[list | None] = mapped_column(JSONTyp, nullable=True)
    wywolania_llm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokeny_we: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokeny_wy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decyzja_koncowa: Mapped[str | None] = mapped_column(String, nullable=True)
    zatwierdzil: Mapped[str | None] = mapped_column(String, nullable=True)
    komentarz: Mapped[str | None] = mapped_column(Text, nullable=True)
    utworzono: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_teraz, nullable=False)
    zakonczono: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def typ_dokumentu(self) -> str | None:
        """Etap 10: typ z podsumowania grafu (WNIOSEK/SZKODA), bez nowej kolumny i migracji.
        None dopoki graf nie dojdzie do zatwierdzenia (PRZETWARZANIE, BLAD, INNY_DOKUMENT)."""
        return (self.podsumowanie or {}).get("typ_dokumentu")

    zdarzenia: Mapped[list["ZdarzenieAudytu"]] = relationship(
        back_populates="wniosek", order_by="ZdarzenieAudytu.czas"
    )


class ZdarzenieAudytu(Baza):
    """Tylko INSERT z kodu aplikacji - nigdy UPDATE/DELETE. Slad audytowy pod AI Act."""

    __tablename__ = "audyt"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wniosek_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("wnioski.id"), nullable=False)
    czas: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_teraz, nullable=False)
    zdarzenie: Mapped[str] = mapped_column(String, nullable=False)
    kto: Mapped[str | None] = mapped_column(String, nullable=True)
    dane: Mapped[dict | None] = mapped_column(JSONTyp, nullable=True)

    wniosek: Mapped["Wniosek"] = relationship(back_populates="zdarzenia")


class WejscieModelu(Baza):
    """Etap 15 (SPEC decyzja 8): wejscia modelu ryzyka szkody - tylko liczby i kody, bez NIP,
    nazwisk i opisow. `zrodlo`: `api` (wniosek z API) albo `symulacja` (pipeline_ml/symuluj_ruch).
    Wiersze `symulacja` nie maja wniosku (`wniosek_id` NULL). Zapis tylko INSERT; czyta job dryfu."""

    __tablename__ = "wejscia_modelu"
    __table_args__ = (CheckConstraint("zrodlo IN ('api', 'symulacja')", name="ck_wejscia_modelu_zrodlo"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wniosek_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("wnioski.id"), nullable=True)
    wersja_modelu: Mapped[str] = mapped_column(String, nullable=False)
    cechy: Mapped[dict] = mapped_column(JSONTyp, nullable=False)
    wynik: Mapped[float] = mapped_column(Float, nullable=False)
    zrodlo: Mapped[str] = mapped_column(String, nullable=False)
    utworzono: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_teraz, server_default=func.now(), nullable=False
    )


def utworz_silnik(database_url: str) -> Engine:
    """SQLite w pamieci (testy) wymaga StaticPool + check_same_thread=False, zeby
    BackgroundTasks (inny watek) widzialy te sama baze co request. Postgres (prod) -
    zwykly silnik z pool_pre_ping."""
    if database_url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in database_url or database_url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        return create_engine(database_url, **kwargs)
    return create_engine(database_url, pool_pre_ping=True)


def utworz_fabryke_sesji(silnik: Engine) -> sessionmaker:
    return sessionmaker(bind=silnik, expire_on_commit=False)


def utworz_tabele(silnik: Engine) -> None:
    """Tworzy schemat `wnioski`/`audyt` bez Alembica - uzywane w testach (SQLite) i w
    demo na sqlite. Na Postgresie w produkcji schemat tworzy wylacznie `alembic upgrade head`."""
    Baza.metadata.create_all(silnik)


def dopisz_audyt(
    sesja: Session, wniosek_id: uuid.UUID, zdarzenie: str, *, kto: str | None = None, dane: dict | None = None
) -> None:
    sesja.add(ZdarzenieAudytu(wniosek_id=wniosek_id, zdarzenie=zdarzenie, kto=kto, dane=dane))


def napraw_wiszace_wnioski(fabryka_sesji: sessionmaker) -> int:
    """Wywolywane przy starcie API: wniosek w PRZETWARZANIE przezyl restart procesu,
    co oznacza, ze przebieg grafu zostal przerwany w locie (nie przez interrupt()).
    Nie wznawiamy automatycznie - wznowienie to kolejne platne wywolania LLM, decyzja
    nalezy do czlowieka. Oznaczamy BLAD i zostawiamy slad w audycie."""
    with fabryka_sesji() as sesja:
        wiszace = sesja.scalars(select(Wniosek).where(Wniosek.status == "PRZETWARZANIE")).all()
        for wpis in wiszace:
            wpis.status = "BLAD"
            wpis.zakonczono = _teraz()
            dopisz_audyt(sesja, wpis.id, "BLAD", kto=None, dane={"powod": "przerwany restartem"})
        if wiszace:
            sesja.commit()
        return len(wiszace)
