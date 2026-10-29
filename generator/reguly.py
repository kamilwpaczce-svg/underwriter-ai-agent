"""Referencyjny silnik regul underwritingowych (deterministyczny).

Wczytuje wytyczne z YAML i na podstawie faktow przypadku (`pola`) wylicza
decyzje oraz liste zadzialanych regul. Zero zgadywania: regula, ktorej pole
jest puste (None), nie dziala - z wyjatkiem R02, ktora wlasnie brak pol
wykrywa.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nip import nip_poprawny  # noqa: E402

PRIORYTET_SKUTKOW = {
    "ODMOWA": 3,
    "UZUPELNIENIE": 2,
    "SKIEROWANIE": 1,
}


def wczytaj_wytyczne(sciezka: str | Path) -> dict[str, Any]:
    with open(sciezka, "r", encoding="utf-8") as plik:
        return yaml.safe_load(plik)


def _parametry(wytyczne: dict[str, Any], regula_id: str) -> dict[str, Any]:
    for regula in wytyczne["reguly"]:
        if regula["id"] == regula_id:
            return regula.get("parametry") or {}
    raise KeyError(f"Brak reguly {regula_id} w wytycznych")


def _suma_ubezpieczenia_laczna(pola: dict[str, Any]) -> int:
    return (pola.get("su_budynki") or 0) + (pola.get("su_maszyny") or 0) + (pola.get("su_zapasy") or 0)


def _r01_pkd_wylaczone(pola: dict[str, Any], parametry: dict[str, Any]) -> bool:
    pkd = pola.get("pkd")
    if not pkd:
        return False
    return any(pkd.startswith(prefiks) for prefiks in parametry["prefiksy_pkd_wylaczone"])


def _r02_brak_pol_wymaganych(pola: dict[str, Any]) -> bool:
    if not pola.get("nip"):
        return True
    if not pola.get("adres"):
        return True
    if not pola.get("pkd"):
        return True
    if not pola.get("rodzaj_konstrukcji"):
        return True
    if pola.get("szkody_3_lata") is None:
        return True
    if _suma_ubezpieczenia_laczna(pola) <= 0:
        return True
    return False


def _r03_nip_bledny(pola: dict[str, Any]) -> bool:
    nip = pola.get("nip")
    if not nip:
        return False
    return not nip_poprawny(nip)


def _r04_su_laczna_powyzej_progu(pola: dict[str, Any], parametry: dict[str, Any]) -> bool:
    return _suma_ubezpieczenia_laczna(pola) > parametry["prog_laczna_su_pln"]


def _konstrukcja_palna(pola: dict[str, Any], parametry: dict[str, Any]) -> bool:
    konstrukcja = pola.get("rodzaj_konstrukcji")
    if not konstrukcja:
        return False
    return konstrukcja in parametry["konstrukcje_palne"]


def _r05_palna_bez_zabezpieczen(pola: dict[str, Any], parametry: dict[str, Any]) -> bool:
    if not _konstrukcja_palna(pola, parametry):
        return False
    if _suma_ubezpieczenia_laczna(pola) <= parametry["prog_laczna_su_pln"]:
        return False
    if pola.get("tryskacze"):
        return False
    if pola.get("ssp"):
        return False
    return True


def _r06_palna_stary_budynek(pola: dict[str, Any], parametry: dict[str, Any]) -> bool:
    if not _konstrukcja_palna(pola, parametry):
        return False
    rok_budowy = pola.get("rok_budowy")
    if rok_budowy is None:
        return False
    return rok_budowy < parametry["rok_budowy_graniczny"]


def _r07_szkodowosc(pola: dict[str, Any], parametry: dict[str, Any]) -> bool:
    szkody = pola.get("szkody_3_lata")
    if not szkody:
        return False
    if len(szkody) > parametry["maks_liczba_szkod"]:
        return True
    return any((szkoda.get("kwota") or 0) > parametry["prog_pojedynczej_szkody_pln"] for szkoda in szkody)


def _r08_strefa_powodziowa(pola: dict[str, Any], parametry: dict[str, Any]) -> bool:
    if not pola.get("strefa_powodziowa"):
        return False
    su_zapasy = pola.get("su_zapasy")
    if su_zapasy is None:
        return False
    return su_zapasy > parametry["prog_su_zapasy_pln"]


def _r09_ochrona_wsteczna(pola: dict[str, Any]) -> bool:
    okres_od = pola.get("okres_od")
    data_wniosku = pola.get("data_wniosku")
    if not okres_od or not data_wniosku:
        return False
    return okres_od < data_wniosku


def _sprawdz_regule(regula_id: str, pola: dict[str, Any], wytyczne: dict[str, Any]) -> bool:
    parametry = _parametry(wytyczne, regula_id)
    if regula_id == "R01":
        return _r01_pkd_wylaczone(pola, parametry)
    if regula_id == "R02":
        return _r02_brak_pol_wymaganych(pola)
    if regula_id == "R03":
        return _r03_nip_bledny(pola)
    if regula_id == "R04":
        return _r04_su_laczna_powyzej_progu(pola, parametry)
    if regula_id == "R05":
        return _r05_palna_bez_zabezpieczen(pola, parametry)
    if regula_id == "R06":
        return _r06_palna_stary_budynek(pola, parametry)
    if regula_id == "R07":
        return _r07_szkodowosc(pola, parametry)
    if regula_id == "R08":
        return _r08_strefa_powodziowa(pola, parametry)
    if regula_id == "R09":
        return _r09_ochrona_wsteczna(pola)
    raise KeyError(f"Nieznana regula {regula_id}")


def oblicz_decyzje(pola: dict[str, Any], wytyczne: dict[str, Any]) -> dict[str, Any]:
    """Zwraca {"decyzja": ..., "reguly": [...]} dla faktow przypadku `pola`.

    `reguly` to PELNA, posortowana po id lista wszystkich zadzialanych regul
    (nie tylko tych odpowiadajacych finalnej decyzji).
    """
    zadzialane: list[str] = []
    for regula in wytyczne["reguly"]:
        regula_id = regula["id"]
        if _sprawdz_regule(regula_id, pola, wytyczne):
            zadzialane.append(regula_id)
    zadzialane.sort()

    if not zadzialane:
        return {"decyzja": "AKCEPTACJA", "reguly": []}

    skutek_wg_id = {regula["id"]: regula["skutek"] for regula in wytyczne["reguly"]}
    najwyzszy_priorytet_skutek = max(
        (skutek_wg_id[regula_id] for regula_id in zadzialane),
        key=lambda skutek: PRIORYTET_SKUTKOW[skutek],
    )
    return {"decyzja": najwyzszy_priorytet_skutek, "reguly": zadzialane}
