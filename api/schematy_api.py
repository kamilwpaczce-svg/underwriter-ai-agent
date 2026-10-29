"""Pydantic: odpowiedzi i zadania API. Modele wyjsciowe czytaja wprost z obiektow
SQLAlchemy przez `from_attributes=True`."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Decyzja = Literal["AKCEPTACJA", "POKRYTA", "ODMOWA", "UZUPELNIENIE", "SKIEROWANIE"]
# Etap 10: zestaw dozwolonych decyzji zalezy od typu dokumentu (api/trasy.py::zloz_decyzje).
DECYZJE_WNIOSKU = frozenset({"AKCEPTACJA", "ODMOWA", "UZUPELNIENIE", "SKIEROWANIE"})
DECYZJE_SZKODY = frozenset({"POKRYTA", "ODMOWA", "UZUPELNIENIE", "SKIEROWANIE"})
Status = Literal["PRZETWARZANIE", "CZEKA_NA_DECYZJE", "ZAKONCZONY", "INNY_DOKUMENT", "BLAD"]


class UtworzWniosekOut(BaseModel):
    id: uuid.UUID
    status: Status


class WniosekListaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nazwa_pliku: str
    status: str
    typ_dokumentu: str | None = None
    decyzja_koncowa: str | None
    utworzono: datetime
    zakonczono: datetime | None


class WniosekSzczegolyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nazwa_pliku: str
    typ_mime: str
    rozmiar_b: int
    status: str
    thread_id: str
    podsumowanie: dict | None
    log_wezlow: list | None
    wywolania_llm: int | None
    tokeny_we: int | None
    tokeny_wy: int | None
    decyzja_koncowa: str | None
    zatwierdzil: str | None
    komentarz: str | None
    utworzono: datetime
    zakonczono: datetime | None


class DecyzjaIn(BaseModel):
    decyzja: Decyzja
    komentarz: str | None = None


class ZdarzenieAudytuOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    czas: datetime
    zdarzenie: str
    kto: str | None
    dane: dict | None


class ZdrowieOut(BaseModel):
    status: Literal["ok"]
    telemetria: bool
    # Etap 15: wersja zaladowanego modelu ryzyka albo None (API dziala tez bez modelu)
    model_ryzyka: str | None = None
