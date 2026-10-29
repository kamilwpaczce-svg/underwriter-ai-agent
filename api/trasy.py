"""APIRouter: wszystkie endpointy Etapu 3.

Uwierzytelnienie jest poza zakresem (Etap 6: Entra ID / Easy Auth). Naglowek
`X-Uzytkownik` to jawna zaslepka - tozsamosc deklarowana przez klienta, nie
weryfikowana.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Request, Response, UploadFile
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from agent.zdjecia import MAKS_ROZMIAR_BAJTOW
from api.agent_serwis import SerwisAgenta, zadanie_w_tle
from api.baza import Wniosek, ZdarzenieAudytu, dopisz_audyt
from api.magazyn import MagazynDokumentow
from api.schematy_api import (
    DECYZJE_SZKODY,
    DECYZJE_WNIOSKU,
    DecyzjaIn,
    UtworzWniosekOut,
    WniosekListaOut,
    WniosekSzczegolyOut,
    ZdarzenieAudytuOut,
    ZdrowieOut,
)

logger = logging.getLogger(__name__)
router = APIRouter()

ROZSZERZENIA_DOZWOLONE = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".eml": "message/rfc822",
}
MAX_ROZMIAR_B = 10 * 1024 * 1024
# Etap 23: opcjonalne zdjecie szkody - tylko JPEG/PNG, limit zgodny z agent.zdjecia (SPEC decyzja 5).
ROZSZERZENIA_ZDJEC = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
STATUSY_DOZWOLONE = {"PRZETWARZANIE", "CZEKA_NA_DECYZJE", "ZAKONCZONY", "INNY_DOKUMENT", "BLAD"}


def _teraz() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Zaleznosci (czytaja wspolny stan z app.state - patrz api/main.py)
# ---------------------------------------------------------------------------

def _sesja_db(request: Request) -> Generator[Session, None, None]:
    fabryka = request.app.state.fabryka_sesji
    sesja = fabryka()
    try:
        yield sesja
    finally:
        sesja.close()


def _magazyn(request: Request) -> MagazynDokumentow:
    return request.app.state.magazyn


def _serwis(request: Request) -> SerwisAgenta:
    return request.app.state.serwis


def _fabryka_sesji(request: Request):
    return request.app.state.fabryka_sesji


def _telemetria(request: Request) -> bool:
    return request.app.state.telemetria


def _model_ryzyka(request: Request) -> str | None:
    model = request.app.state.model_ryzyka
    return model.wersja if model is not None else None


def _pobierz_wniosek_lub_404(sesja: Session, wniosek_id: uuid.UUID) -> Wniosek:
    wpis = sesja.get(Wniosek, wniosek_id)
    if wpis is None:
        raise HTTPException(status_code=404, detail="Wniosek nie istnieje.")
    return wpis


# ---------------------------------------------------------------------------
# Endpointy
# ---------------------------------------------------------------------------

@router.post("/wnioski", response_model=UtworzWniosekOut, status_code=202)
async def utworz_wniosek(
    tlo: BackgroundTasks,
    plik: UploadFile = File(...),
    zdjecie: UploadFile | None = File(None),
    sesja: Session = Depends(_sesja_db),
    magazyn: MagazynDokumentow = Depends(_magazyn),
    serwis: SerwisAgenta = Depends(_serwis),
    fabryka_sesji=Depends(_fabryka_sesji),
):
    nazwa = plik.filename or "dokument"
    rozszerzenie = Path(nazwa).suffix.lower()
    if rozszerzenie not in ROZSZERZENIA_DOZWOLONE:
        raise HTTPException(
            status_code=415,
            detail=f"Nieobslugiwane rozszerzenie '{rozszerzenie}'. Dozwolone: .pdf, .jpg, .jpeg, .eml.",
        )

    dane = await plik.read()
    if len(dane) > MAX_ROZMIAR_B:
        raise HTTPException(status_code=413, detail=f"Plik przekracza limit {MAX_ROZMIAR_B} bajtow.")

    # Zdjecie walidowane PRZED zapisem czegokolwiek: odrzucone nie zostawia bloba dokumentu ani wniosku.
    dane_zdjecia: bytes | None = None
    rozszerzenie_zdjecia = ""
    if zdjecie is not None and zdjecie.filename:
        rozszerzenie_zdjecia = Path(zdjecie.filename).suffix.lower()
        if rozszerzenie_zdjecia not in ROZSZERZENIA_ZDJEC:
            raise HTTPException(
                status_code=415,
                detail=f"Nieobslugiwane rozszerzenie zdjecia '{rozszerzenie_zdjecia}'. Dozwolone: .jpg, .jpeg, .png.",
            )
        dane_zdjecia = await zdjecie.read()
        if len(dane_zdjecia) > MAKS_ROZMIAR_BAJTOW:
            raise HTTPException(status_code=413, detail=f"Zdjecie przekracza limit {MAKS_ROZMIAR_BAJTOW} bajtow.")

    wniosek_id = uuid.uuid4()
    blob_nazwa = f"{wniosek_id}{rozszerzenie}"
    typ_mime = ROZSZERZENIA_DOZWOLONE[rozszerzenie]

    magazyn.zapisz(blob_nazwa, dane, typ_mime)
    zdjecie_blob: str | None = None
    if dane_zdjecia is not None:
        zdjecie_blob = f"{wniosek_id}_zdjecie{rozszerzenie_zdjecia}"
        magazyn.zapisz(zdjecie_blob, dane_zdjecia, ROZSZERZENIA_ZDJEC[rozszerzenie_zdjecia])

    wpis = Wniosek(
        id=wniosek_id,
        nazwa_pliku=nazwa,
        typ_mime=typ_mime,
        rozmiar_b=len(dane),
        blob_nazwa=blob_nazwa,
        status="PRZETWARZANIE",
        thread_id=str(wniosek_id),
    )
    sesja.add(wpis)
    dopisz_audyt(sesja, wniosek_id, "PRZYJETO", kto=None, dane={"nazwa_pliku": nazwa, "rozmiar_b": len(dane)})
    sesja.commit()

    tlo.add_task(zadanie_w_tle, serwis, fabryka_sesji, wniosek_id, nazwa, blob_nazwa, zdjecie_blob)

    return UtworzWniosekOut(id=wniosek_id, status="PRZETWARZANIE")


@router.get("/wnioski", response_model=list[WniosekListaOut])
def lista_wnioskow(status: str | None = None, limit: int = 50, sesja: Session = Depends(_sesja_db)):
    if status is not None and status not in STATUSY_DOZWOLONE:
        raise HTTPException(status_code=422, detail=f"Niepoprawny status '{status}'.")
    limit = min(max(limit, 1), 200)

    zapytanie = select(Wniosek).order_by(Wniosek.utworzono.desc()).limit(limit)
    if status is not None:
        zapytanie = zapytanie.where(Wniosek.status == status)
    return sesja.scalars(zapytanie).all()


@router.get("/wnioski/{wniosek_id}", response_model=WniosekSzczegolyOut)
def szczegoly_wniosku(wniosek_id: uuid.UUID, sesja: Session = Depends(_sesja_db)):
    return _pobierz_wniosek_lub_404(sesja, wniosek_id)


@router.get("/wnioski/{wniosek_id}/dokument")
def dokument_wniosku(
    wniosek_id: uuid.UUID, sesja: Session = Depends(_sesja_db), magazyn: MagazynDokumentow = Depends(_magazyn)
):
    wpis = _pobierz_wniosek_lub_404(sesja, wniosek_id)
    dane = magazyn.pobierz(wpis.blob_nazwa)
    return Response(content=dane, media_type=wpis.typ_mime)


@router.post("/wnioski/{wniosek_id}/decyzja", response_model=WniosekSzczegolyOut)
def zloz_decyzje(
    wniosek_id: uuid.UUID,
    cialo: DecyzjaIn,
    sesja: Session = Depends(_sesja_db),
    serwis: SerwisAgenta = Depends(_serwis),
    x_uzytkownik: str | None = Header(default=None, alias="X-Uzytkownik"),
):
    if not x_uzytkownik or not x_uzytkownik.strip():
        raise HTTPException(status_code=422, detail="Naglowek 'X-Uzytkownik' jest wymagany.")

    wpis = _pobierz_wniosek_lub_404(sesja, wniosek_id)
    if wpis.status != "CZEKA_NA_DECYZJE":
        raise HTTPException(
            status_code=409,
            detail=f"Wniosek ma status '{wpis.status}', oczekiwano 'CZEKA_NA_DECYZJE'.",
        )

    podsumowanie = wpis.podsumowanie or {}
    szkoda = podsumowanie.get("typ_dokumentu") == "SZKODA"
    dozwolone = DECYZJE_SZKODY if szkoda else DECYZJE_WNIOSKU
    if cialo.decyzja not in dozwolone:
        raise HTTPException(
            status_code=422,
            detail=f"Decyzja '{cialo.decyzja}' niedozwolona dla tego dokumentu. Dozwolone: {', '.join(sorted(dozwolone))}.",
        )
    if szkoda:
        # Szkoda: rekomendacja agenta = decyzja po regulach (S01-S03, kontrola cytatow);
        # decyzja_llm to surowa ocena modelu - zapisywana w audycie, nie wymusza komentarza.
        rekomendacja_decyzja = podsumowanie.get("decyzja_llm")
        silnik_decyzja = podsumowanie.get("decyzja")
        odejscie_od_rekomendacji = cialo.decyzja != silnik_decyzja
    else:
        rekomendacja_decyzja = (podsumowanie.get("rekomendacja") or {}).get("decyzja")
        silnik_decyzja = (podsumowanie.get("decyzja_silnika") or {}).get("decyzja")
        odejscie_od_rekomendacji = cialo.decyzja != rekomendacja_decyzja or cialo.decyzja != silnik_decyzja

    if odejscie_od_rekomendacji and not (cialo.komentarz and cialo.komentarz.strip()):
        raise HTTPException(
            status_code=422,
            detail="Decyzja odbiega od rekomendacji LLM lub decyzji silnika regul - komentarz jest wymagany.",
        )

    try:
        wynik = serwis.wznow(wniosek_id, cialo.decyzja, x_uzytkownik, odejscie=odejscie_od_rekomendacji)
    except Exception as e:  # noqa: BLE001 - zaden wyjatek nie moze zniknac cicho
        logger.exception("Blad wznowienia grafu dla wniosku %s", wniosek_id)
        wpis.status = "BLAD"
        wpis.zakonczono = _teraz()
        dopisz_audyt(sesja, wniosek_id, "BLAD", kto=x_uzytkownik, dane={"blad": str(e)})
        sesja.commit()
        raise HTTPException(status_code=500, detail="Blad wznowienia przebiegu agenta.") from e

    wpis.status = "ZAKONCZONY"
    wpis.decyzja_koncowa = wynik.get("decyzja_koncowa")
    wpis.zatwierdzil = wynik.get("zatwierdzil")
    wpis.komentarz = cialo.komentarz
    wpis.zakonczono = _teraz()

    dopisz_audyt(
        sesja,
        wniosek_id,
        "DECYZJA",
        kto=x_uzytkownik,
        dane={
            "decyzja": cialo.decyzja,
            "komentarz": cialo.komentarz,
            "odejscie_od_rekomendacji": odejscie_od_rekomendacji,
            "rekomendacja_llm": rekomendacja_decyzja,
            "decyzja_silnika": silnik_decyzja,
        },
    )
    sesja.commit()
    sesja.refresh(wpis)
    return wpis


@router.get("/wnioski/{wniosek_id}/audyt", response_model=list[ZdarzenieAudytuOut])
def audyt_wniosku(wniosek_id: uuid.UUID, sesja: Session = Depends(_sesja_db)):
    _pobierz_wniosek_lub_404(sesja, wniosek_id)
    zapytanie = select(ZdarzenieAudytu).where(ZdarzenieAudytu.wniosek_id == wniosek_id).order_by(ZdarzenieAudytu.czas)
    return sesja.scalars(zapytanie).all()


@router.get("/zdrowie", response_model=ZdrowieOut)
def zdrowie(
    sesja: Session = Depends(_sesja_db),
    magazyn: MagazynDokumentow = Depends(_magazyn),
    telemetria: bool = Depends(_telemetria),
    model_ryzyka: str | None = Depends(_model_ryzyka),
):
    problemy: list[str] = []
    try:
        sesja.execute(text("SELECT 1"))
    except Exception as e:  # noqa: BLE001 - /zdrowie ma zglosic kazda przyczyne awarii
        problemy.append(f"postgres: {e}")
    try:
        magazyn.sprawdz_dostepnosc()
    except Exception as e:  # noqa: BLE001
        problemy.append(f"blob: {e}")

    if problemy:
        raise HTTPException(status_code=503, detail=problemy)
    return ZdrowieOut(status="ok", telemetria=telemetria, model_ryzyka=model_ryzyka)
