"""Serwowanie modelu ryzyka szkody w API (Etap 15, SPEC decyzje 5 i 6).

Model (`champion.skops`), `referencja.json` i `metadane.json` leza w kontenerze Blob
`modele` pod prefiksem `ryzyko_szkody/` (zapisuje je `pipeline_ml/eksportuj_championa`,
a lokalnie `zapisz_do_katalogu`). API ladowanie robi RAZ przy starcie przez
`ModelRyzyka.z_bloba(magazyn)`: dowolny blad (brak bloba, uszkodzony plik, nieznany typ
w skops, brak uprawnien) daje `None` i ostrzezenie w logu - API musi wstac bez modelu.

Format `skops` zamiast pickle: ladowanie dopuszcza tylko typy z `ZAUFANE_TYPY`; nieznany
typ w pliku konczy sie bledem, a nie wykonaniem kodu. sklearn i pandas sa importowane
leniwie (wewnatrz funkcji), zeby sam import modulu nic nie kosztowal.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ryzyko.cechy import CECHY, CECHY_LICZBOWE

logger = logging.getLogger(__name__)

KONTENER_DOMYSLNY = "modele"
PREFIKS_DOMYSLNY = "ryzyko_szkody/"
PLIK_MODELU = "champion.skops"
PLIK_REFERENCJI = "referencja.json"
PLIK_METADANYCH = "metadane.json"
# Jedyny typ spoza sklearn-owej listy domyslnej, potrzebny do Pipeline(ColumnTransformer+HGB)
# (zmierzone w DSZ0). Nic wiecej - nieznany typ ma konczyc sie bledem.
ZAUFANE_TYPY = ["sklearn.ensemble._hist_gradient_boosting.predictor.TreePredictor"]
MAX_GLOWNYCH_CECH = 3
_PROG_SPADKU = 1e-9  # spadek wyniku mniejszy niz to nie jest "glowna cecha"


def mediany_z_referencji(referencja: dict[str, Any]) -> dict[str, float]:
    """Mediany cech liczbowych z `referencja` (klucz `mediana`); cechy bez niej pomijane."""
    mediany: dict[str, float] = {}
    for cecha in CECHY_LICZBOWE:
        opis = referencja.get(cecha) or {}
        if isinstance(opis.get("mediana"), (int, float)):
            mediany[cecha] = float(opis["mediana"])
    return mediany


def pliki_modelu(
    model: Any, wersja: str, referencja: dict[str, Any], metryki: dict[str, float] | None = None
) -> dict[str, bytes]:
    """Etap 15: trzy pliki serwowania (nazwa -> bajty); wspolne dla katalogu i Blob."""
    from skops.io import dumps

    metadane = {"wersja": wersja, "data": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if metryki:
        metadane["metryki"] = metryki
    return {
        PLIK_MODELU: dumps(model),
        PLIK_REFERENCJI: json.dumps(referencja, ensure_ascii=False, indent=2).encode("utf-8"),
        PLIK_METADANYCH: json.dumps(metadane, ensure_ascii=False, indent=2).encode("utf-8"),
    }


def zapisz_do_katalogu(
    model: Any,
    wersja: str,
    referencja: dict[str, Any],
    katalog: str | Path,
    metryki: dict[str, float] | None = None,
) -> None:
    """Etap 15: `champion.skops`, `referencja.json`, `metadane.json` (wersja, data, metryki) w `katalog`."""
    cel = Path(katalog)
    cel.mkdir(parents=True, exist_ok=True)
    for nazwa, dane in pliki_modelu(model, wersja, referencja, metryki).items():
        (cel / nazwa).write_bytes(dane)


@dataclass
class ModelRyzyka:
    """Etap 15: wytrenowany Pipeline + wersja + mediany referencyjne do `glowne_cechy`.

    Wynik to SYGNAL DLA CZLOWIEKA (likwidatora), nigdy decyzja - patrz SPEC decyzja 6.
    """

    model: Any
    wersja: str
    mediany: dict[str, float] = field(default_factory=dict)

    def ocen(self, cechy: dict[str, Any]) -> dict[str, Any]:
        """Etap 15: `{"wynik": P(klasa 1) zaokraglone do 3 miejsc, "glowne_cechy": [2-3 nazwy]}`.

        `glowne_cechy` to PRZYBLIZENIE DLA CZLOWIEKA, a nie wyjasnienie modelu (to nie SHAP
        ani waznosc permutacyjna): dla kazdej cechy liczbowej podmieniamy jej wartosc na
        mediane referencji i mierzymy, o ile spadl wynik; zwracamy do 3 cech o najwiekszym
        dodatnim spadku (posortowane malejaco, remis wg kolejnosci `CECHY`). Cechy, ktorych
        podmiana nie obniza wyniku, nie sa wymieniane - wiec dla bardzo niskiego wyniku lista
        moze byc krotsza albo pusta. Cechy kategorialnej (rodzaj mienia) nie ruszamy.
        Deterministyczne, jedno wywolanie `predict_proba` na 1 + N wierszach.
        """
        import pandas as pd

        brakujace = [c for c in CECHY if c not in cechy]
        if brakujace:
            raise KeyError(f"brak cech: {brakujace}")
        sprawdzane = [c for c in CECHY_LICZBOWE if c in self.mediany]
        wiersze = [{c: cechy[c] for c in CECHY}]
        for cecha in sprawdzane:
            wiersz = dict(wiersze[0])
            wiersz[cecha] = self.mediany[cecha]
            wiersze.append(wiersz)
        proby = self.model.predict_proba(pd.DataFrame(wiersze, columns=CECHY))[:, 1]
        bazowy = float(proby[0])
        spadki = [(bazowy - float(p), cecha) for cecha, p in zip(sprawdzane, proby[1:])]
        spadki = [s for s in spadki if s[0] > _PROG_SPADKU]
        spadki.sort(key=lambda s: -s[0])  # sort stabilny: remis zostaje w kolejnosci CECHY
        return {
            "wynik": round(bazowy, 3),
            "glowne_cechy": [cecha for _, cecha in spadki[:MAX_GLOWNYCH_CECH]],
        }

    @classmethod
    def _z_pobierania(cls, pobierz: Callable[[str], bytes]) -> "ModelRyzyka":
        from skops.io import loads

        model = loads(pobierz(PLIK_MODELU), trusted=ZAUFANE_TYPY)
        if not hasattr(model, "predict_proba"):
            raise TypeError(f"zaladowany obiekt ({type(model).__name__}) nie ma predict_proba")
        referencja = json.loads(pobierz(PLIK_REFERENCJI).decode("utf-8"))
        metadane = json.loads(pobierz(PLIK_METADANYCH).decode("utf-8"))
        wersja = metadane.get("wersja")
        if not isinstance(wersja, str) or not wersja:
            raise ValueError("metadane bez pola 'wersja'")
        return cls(model=model, wersja=wersja, mediany=mediany_z_referencji(referencja))

    @classmethod
    def z_katalogu(cls, katalog: str | Path) -> "ModelRyzyka":
        """Etap 15: odczyt z katalogu (testy, praca lokalna). Bledy propaguja sie - w
        odroznieniu od `z_bloba`, ktory zwraca None."""
        baza = Path(katalog)
        return cls._z_pobierania(lambda nazwa: (baza / nazwa).read_bytes())

    @classmethod
    def z_bloba(
        cls, magazyn: Any, kontener: str | None = None, prefiks: str = PREFIKS_DOMYSLNY
    ) -> "ModelRyzyka | None":
        """Etap 15: ladowanie przy starcie API przez `magazyn.pobierz_z_kontenera`.

        Kontener: argument, potem env `KONTENER_MODELI`, potem `modele`. KAZDY blad (brak
        bloba, uszkodzony plik, nieznany typ w skops, brak metody w magazynie) -> None +
        ostrzezenie; w logu tylko nazwa klasy wyjatku i sciezka bloba, nigdy tresc pliku.
        """
        kontener = kontener or os.environ.get("KONTENER_MODELI") or KONTENER_DOMYSLNY
        try:
            return cls._z_pobierania(lambda nazwa: magazyn.pobierz_z_kontenera(kontener, prefiks + nazwa))
        except Exception as e:
            logger.warning(
                "Model ryzyka niedostepny (%s/%s): %s - API startuje bez modelu.",
                kontener,
                prefiks,
                type(e).__name__,
            )
            return None
