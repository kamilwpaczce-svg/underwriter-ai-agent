"""19c: pilnuje zgodnosci `obserwowalnosc/metryki_efektu.kql` z kodem.

KQL jest sprawdzany recznie w portalu, ale trzy rzeczy psuja sie cicho i da sie je
sprawdzic offline: (1) cennik zyje w dwoch miejscach (uruchom.py i .kql), (2) zapytanie
mogloby zniknac przy edycji, (3) nazwa atrybutu/spanu w KQL moglaby sie rozjechac z kodem
(literowka = metryka zawsze 0, bez bledu)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KQL = (ROOT / "obserwowalnosc" / "metryki_efektu.kql").read_text(encoding="utf-8")
URUCHOM = (ROOT / "ewaluacja" / "uruchom.py").read_text(encoding="utf-8")

# Pliki, w ktorych powstaja spany i atrybuty (telemetria.py: nazwa tracera, bez atrybutow uw.*).
ZRODLA_TELEMETRII = [
    ROOT / "api" / "agent_serwis.py",
    ROOT / "obserwowalnosc" / "model_sledzony.py",
    ROOT / "obserwowalnosc" / "wezly.py",
    ROOT / "obserwowalnosc" / "telemetria.py",
]
KOD = "\n".join(p.read_text(encoding="utf-8") for p in ZRODLA_TELEMETRII)

NAGLOWKI = [
    "Koszt LLM na wniosek",
    "Odsetek rekomendacji SKIEROWANIE",
    "Odsetek odejsc czlowieka od rekomendacji",
    "Odsetek wnioskow z bledem agenta",
    "Czas przebiegu agenta - p95",
    "Alert jakosci - odsetek odejsc",
]


def _liczba(tekst: str, wzorzec: str) -> float:
    dopasowanie = re.search(wzorzec, tekst, flags=re.MULTILINE)
    assert dopasowanie, f"brak dopasowania: {wzorzec}"
    return float(dopasowanie.group(1))


def test_cennik_w_kql_rowny_cennikowi_w_uruchom_py():
    we_kql = _liczba(KQL, r"let\s+cena_we_usd_na_milion\s*=\s*([0-9.]+)\s*;")
    wy_kql = _liczba(KQL, r"let\s+cena_wy_usd_na_milion\s*=\s*([0-9.]+)\s*;")
    we_py = _liczba(URUCHOM, r"^CENA_GPT5_MINI_WE_USD_NA_MILION\s*=\s*([0-9.]+)")
    wy_py = _liczba(URUCHOM, r"^CENA_GPT5_MINI_WY_USD_NA_MILION\s*=\s*([0-9.]+)")
    assert (we_kql, wy_kql) == (we_py, wy_py)


def test_cennik_w_kql_ma_komentarz_orientacyjny():
    for nazwa in ("cena_we_usd_na_milion", "cena_wy_usd_na_milion"):
        linia = next(l for l in KQL.splitlines() if re.match(rf"let\s+{nazwa}\b", l))
        assert "orientacyjny" in linia, linia


def test_kazde_z_szesciu_zapytan_jest_obecne_w_kolejnosci():
    naglowki = re.findall(r"^// === (\d+)\. (.+?) ===\s*$", KQL, flags=re.MULTILINE)
    assert [int(n) for n, _ in naglowki] == [1, 2, 3, 4, 5, 6]
    for (_, tytul), oczekiwany in zip(naglowki, NAGLOWKI):
        assert tytul.startswith(oczekiwany), (tytul, oczekiwany)


def test_kazde_zapytanie_ma_wlasne_okno_i_filtr_roli():
    """Zapytania kopiuje sie do portalu pojedynczo - kazde musi byc samodzielne i
    odfiltrowywac ruch testowy (role), inaczej metryki licza uw-test-alarmu."""
    bloki = re.split(r"(?m)^// === \d+\. .*$", KQL)[1:]
    assert len(bloki) == 6
    for numer, blok in enumerate(bloki, start=1):
        assert re.search(r"let\s+okno\s*=", blok), f"zapytanie {numer}: brak let okno"
        assert "AppRoleName in (role)" in blok, f"zapytanie {numer}: brak filtra roli"
        assert "AppDependencies" in blok, f"zapytanie {numer}: spany wewnetrzne leza w AppDependencies"
        assert "AppRequests" not in blok


def test_zapytanie_alertu_ma_prog_okno_i_minimum_ze_specyfikacji():
    alert = re.split(r"(?m)^// === 6\. .*$", KQL)[1]
    assert re.search(r"let\s+okno\s*=\s*24h\s*;", alert)
    assert re.search(r"let\s+min_decyzji\s*=\s*5\s*;", alert)
    assert re.search(r"let\s+prog_odejsc_pct\s*=\s*50\.0\s*;", alert)
    assert 'Name == "wniosek.wznow"' in alert


def test_klucze_properties_w_kql_istnieja_w_kodzie():
    klucze = set(re.findall(r'Properties\["([^"]+)"\]', KQL))
    assert klucze == {
        "uw.wniosek_id",
        "uw.decyzja",
        "uw.blad",
        "uw.odejscie_od_rekomendacji",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
    }
    for klucz in klucze:
        assert f'"{klucz}"' in KOD, f"atrybut {klucz} z KQL nie wystepuje w kodzie telemetrii"


def test_nazwy_spanow_w_kql_istnieja_w_kodzie():
    nazwy = set(re.findall(r'Name == "([^"]+)"', KQL))
    assert nazwy == {"wniosek.uruchom", "wniosek.wznow"}
    for nazwa in nazwy:
        assert f'"{nazwa}"' in KOD, f"span {nazwa} z KQL nie wystepuje w kodzie"
    # llm.* powstaje z f"llm.{operacja}" - prefiks z KQL (startswith "llm.") musi zgadzac sie z kodem.
    assert 'Name startswith "llm."' in KQL
    assert 'f"llm.{operacja}"' in KOD


def test_wartosci_atrybutow_w_kql_zgodne_z_kodem():
    """Kody decyzji uzywane w filtrach KQL musza istniec w kodzie API."""
    schematy = (ROOT / "api" / "schematy_api.py").read_text(encoding="utf-8")
    assert '"SKIEROWANIE"' in KQL and '"SKIEROWANIE"' in schematy
    assert '"NIE_DOTYCZY"' in KQL and '"NIE_DOTYCZY"' in (ROOT / "agent" / "wezly.py").read_text(encoding="utf-8")


def test_kql_bez_znakow_spoza_ascii():
    """Zero polskich znakow i emoji w plikach automatow (zasada repo)."""
    assert KQL.isascii()
