"""Atrapa ModelAgenta do testu calego toru ewaluacji bez sieci.

Nie wykonuje zadnych wywolan sieciowych - zwraca dane wprost z
`dane/oczekiwane/<ID>.json` dla aktualnie ustawionego przypadku. Uzywana przez
`ewaluacja/uruchom.py --atrapa`, zeby sprawdzic graf, interrupt, porownanie i
zapis wynikow bez klucza API i bez kontaktu z Gemini.

Etap 10: przypadki `Z..` (zgloszenia szkod) czyta z `dane/szkody/oczekiwane/<ID>.json`.
`ocen_pokrycie` odtwarza zachowanie modelu z narzedziem: gdy przypadek ma
`zapytanie_dodatkowe`, pierwsze wywolanie (bez `dodatkowe`) prosi o dodatkowe
wyszukiwanie, drugie zwraca decyzje.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from agent.model import MetadaneWywolania
from agent.schematy import (
    Cytat,
    DecyzjaSupervisora,
    Ekstrakcja,
    EkstrakcjaSzkody,
    Klasyfikacja,
    Ocena,
    OcenaPokrycia,
    OcenaZdjecia,
    Pola,
    PolaSzkody,
    UzasadnienieReguly,
)
from agent.wczytywanie import CzesciDokumentu
from rag.fragmenty import Fragment, parsuj_odwolanie

_METADANE_ATRAPY = MetadaneWywolania(tokeny_we=0, tokeny_wy=0)


class ModelAtrapa:
    """Przed kazdym przypadkiem wywolaj `ustaw_przypadek(id)`."""

    def __init__(self, katalog_oczekiwane: str | Path, katalog_szkody: str | Path | None = None):
        self._katalog = Path(katalog_oczekiwane)
        # Domyslnie dane/szkody/oczekiwane obok dane/oczekiwane.
        self._katalog_szkody = (
            Path(katalog_szkody) if katalog_szkody is not None else self._katalog.parent / "szkody" / "oczekiwane"
        )
        self._biezacy: dict | None = None
        self.nazwa_modelu = "atrapa"
        # Etap 23: zdjecia szkod obok dane/oczekiwane (dane/zdjecia_szkod); mapa hashy liczona leniwie.
        self._katalog_zdjec = self._katalog.parent / "zdjecia_szkod"
        self._id_wg_hasha: dict[str, str] | None = None

    def ustaw_przypadek(self, id_przypadku: str) -> None:
        katalog = self._katalog_szkody if id_przypadku.startswith("Z") else self._katalog
        sciezka = katalog / f"{id_przypadku}.json"
        with open(sciezka, "r", encoding="utf-8") as plik:
            dane = json.load(plik)
        dane.setdefault("id", id_przypadku)
        self._biezacy = dane

    def _mapa_zdjec(self) -> dict[str, str]:
        """SHA-256 bajtow `Z??.jpg` -> id przypadku. Pliki `*_flux_rdza.jpg` (odrzucone zdjecia
        ze starszych przebiegow) nie pasuja do wzorca i nie wchodza do mapy."""
        if self._id_wg_hasha is None:
            mapa: dict[str, str] = {}
            if self._katalog_zdjec.is_dir():
                for plik in sorted(self._katalog_zdjec.glob("Z*.jpg")):
                    if re.fullmatch(r"Z\d\d\.jpg", plik.name):
                        mapa[hashlib.sha256(plik.read_bytes()).hexdigest()] = plik.stem
            self._id_wg_hasha = mapa
        return self._id_wg_hasha

    def _wymagaj_przypadku(self) -> dict:
        if self._biezacy is None:
            raise RuntimeError("ModelAtrapa: nie ustawiono przypadku - wywolaj ustaw_przypadek(id) przed uzyciem.")
        return self._biezacy

    def klasyfikuj(self, czesci: CzesciDokumentu) -> tuple[Klasyfikacja, MetadaneWywolania]:
        dane = self._wymagaj_przypadku()
        wynik = Klasyfikacja(typ_dokumentu=dane["typ_dokumentu"], uzasadnienie="atrapa: z dane/oczekiwane")
        return wynik, _METADANE_ATRAPY

    def ekstrahuj(self, czesci: CzesciDokumentu) -> tuple[Ekstrakcja, MetadaneWywolania]:
        dane = self._wymagaj_przypadku()
        pola = Pola(**(dane.get("pola") or {}))
        podejrzane = dane.get("id") == "W13"
        wynik = Ekstrakcja(pola=pola, podejrzane_instrukcje=podejrzane)
        return wynik, _METADANE_ATRAPY

    def ocen(
        self, instrukcje: str, pola_json: str, problemy_walidacji: list[str]
    ) -> tuple[Ocena, MetadaneWywolania]:
        dane = self._wymagaj_przypadku()
        reguly = dane.get("reguly") or []
        if reguly:
            uzasadnienia = [
                UzasadnienieReguly(regula=r, tekst=f"Atrapa: regula {r} zadzialala (dane/oczekiwane).")
                for r in reguly
            ]
        else:
            uzasadnienia = [UzasadnienieReguly(regula="OGOLNE", tekst="Atrapa: brak zadzialanych regul - AKCEPTACJA.")]
        wynik = Ocena(decyzja=dane["decyzja"], reguly=reguly, uzasadnienia=uzasadnienia)
        return wynik, _METADANE_ATRAPY

    def ekstrahuj_szkode(self, czesci: CzesciDokumentu) -> tuple[EkstrakcjaSzkody, MetadaneWywolania]:
        dane = self._wymagaj_przypadku()
        wynik = EkstrakcjaSzkody(
            pola=PolaSzkody(**(dane.get("pola") or {})),
            podejrzane_instrukcje=bool(dane.get("podejrzane")),
        )
        return wynik, _METADANE_ATRAPY

    def analizuj_zdjecie(self, obraz: bytes, mime_type: str) -> tuple[OcenaZdjecia, MetadaneWywolania]:
        """Rozpoznaje zdjecie po hashu bajtow (nie po `ustaw_przypadek`) - zdjecie z pary N1-N6 ma
        miec ocene swojego zdjecia, nie biezacego przypadku. Nieznane bajty -> ValueError."""
        id_przypadku = self._mapa_zdjec().get(hashlib.sha256(obraz).hexdigest())
        if id_przypadku is None:
            raise ValueError("ModelAtrapa: nieznane zdjecie (brak w dane/zdjecia_szkod/Z??.jpg).")
        with open(self._katalog_szkody / f"{id_przypadku}.json", "r", encoding="utf-8") as plik:
            oczekiwane = json.load(plik)["zdjecie"]
        wynik = OcenaZdjecia(
            czy_widac_szkode=True,
            rodzaj_zdarzenia=oczekiwane["rodzaj_zdarzenia"],
            widoczne_mienie=[],
            dlugotrwalosc=oczekiwane["dlugotrwalosc"],
            oznaki=[],
            pewnosc=0.9,
            tekst_na_zdjeciu=False,
        )
        return wynik, _METADANE_ATRAPY

    def decyduj_supervisor(
        self, czesci: CzesciDokumentu | None, podsumowanie: dict | None
    ) -> tuple[DecyzjaSupervisora, MetadaneWywolania]:
        """Etap 24. Krok 1 (`czesci` != None): `typ_dokumentu` z oczekiwanych, WNIOSEK -> agent_underwritingu,
        SZKODA -> agent_szkod, INNY -> zakoncz. Krok 2: lustro `po_sprawdzeniu_polisy` na kodach polisy z
        podsumowania - `zakoncz` przy S01/S02, w pozostalych przypadkach (takze Z12) `agent_owu`
        (DO DECYZJI 1, 27.10)."""
        dane = self._wymagaj_przypadku()
        if czesci is not None:
            typ = dane["typ_dokumentu"]
            nastepny = {"WNIOSEK": "agent_underwritingu", "SZKODA": "agent_szkod", "INNY": "zakoncz"}[typ]
            wynik = DecyzjaSupervisora(typ_dokumentu=typ, nastepny=nastepny, uzasadnienie="atrapa: z dane/oczekiwane")
            return wynik, _METADANE_ATRAPY
        kody = (podsumowanie or {}).get("kody_polisy") or []
        nastepny = "zakoncz" if ("S01" in kody or "S02" in kody) else "agent_owu"
        wynik = DecyzjaSupervisora(nastepny=nastepny, uzasadnienie="atrapa: lustro po_sprawdzeniu_polisy")
        return wynik, _METADANE_ATRAPY

    def ocen_pokrycie(
        self,
        pola: dict,
        wynik_polisy: dict,
        fragmenty: list[Fragment],
        dodatkowe: list[Fragment] | None = None,
    ) -> tuple[OcenaPokrycia, MetadaneWywolania]:
        dane = self._wymagaj_przypadku()
        if dane.get("zapytanie_dodatkowe") and dodatkowe is None:
            wynik = OcenaPokrycia(decyzja="SKIEROWANIE", dodatkowe_zapytanie=dane["zapytanie_dodatkowe"])
            return wynik, _METADANE_ATRAPY

        oczekiwane = [o for o in (parsuj_odwolanie(tekst) for tekst in dane.get("paragrafy_oczekiwane") or []) if o]
        widoczne = {(f.paragraf, f.ustep) for f in [*fragmenty, *(dodatkowe or [])]}
        # Atrapa cytuje pierwszy oczekiwany ustep, ktory faktycznie dostala; gdy zaden
        # nie zostal pobrany - pierwszy oczekiwany (kontrola cytatow go odrzuci, tak jak
        # odrzucilaby halucynacje prawdziwego modelu).
        wybrany = next((o for o in oczekiwane if o in widoczne), oczekiwane[0] if oczekiwane else None)
        cytaty = []
        if wybrany is not None:
            cytaty.append(
                Cytat(
                    paragraf=f"§ {wybrany[0]}",
                    ustep=str(wybrany[1]),
                    uzasadnienie="Atrapa: ustep z dane/szkody/oczekiwane.",
                )
            )
        wynik = OcenaPokrycia(
            decyzja=dane.get("decyzja_llm") or "SKIEROWANIE",
            cytaty=cytaty,
            brakujace_dokumenty=list(dane.get("brakujace_dokumenty") or []),
        )
        return wynik, _METADANE_ATRAPY
