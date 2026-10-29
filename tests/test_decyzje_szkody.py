"""Kontrola cytatow i ustalanie decyzji dla szkody (agent/decyzje_szkody.py) - czyste funkcje."""

from __future__ import annotations

import pytest

from agent.decyzje_szkody import klucz_cytatu, kontroluj_cytaty, podsumowanie_szkody, ustal_decyzje_szkody

FRAGMENTY = [
    {"id": "p4u1", "paragraf": 4, "ustep": 1, "tytul": "Zakres ubezpieczenia", "tresc": "§ 4. Zakres ubezpieczenia\nust. 1. Pożar."},
    {"id": "p6u4", "paragraf": 6, "ustep": 4, "tytul": "Wyłączenia odpowiedzialności", "tresc": "§ 6. Wyłączenia\nust. 4. Dach."},
]


def _cytat(paragraf, ustep):
    return {"paragraf": paragraf, "ustep": ustep, "uzasadnienie": "test"}


def _ocena(decyzja, cytaty=(), brakujace=()):
    return {"decyzja": decyzja, "cytaty": list(cytaty), "brakujace_dokumenty": list(brakujace), "dodatkowe_zapytanie": None}


def _stan(**zmiany):
    stan = {
        "typ_dokumentu": "SZKODA",
        "pola": {"nr_polisy": "PL/MSP/2026/0001"},
        "wynik_polisy": {"kody": [], "braki": []},
        "fragmenty_owu": FRAGMENTY,
        "ocena_pokrycia": _ocena("POKRYTA", [_cytat("§ 4", "1")]),
    }
    stan.update(zmiany)
    return stan


def test_klucz_cytatu_rozne_formaty():
    assert klucz_cytatu(_cytat("§ 6", "4")) == (6, 4)
    assert klucz_cytatu(_cytat("6", "ust. 4")) == (6, 4)
    assert klucz_cytatu(_cytat("§ 6 ust. 4", "")) == (6, 4)
    assert klucz_cytatu(_cytat("§6", "4.")) == (6, 4)
    assert klucz_cytatu(_cytat("§ 6", "")) is None
    assert klucz_cytatu(_cytat("", "4")) is None
    assert klucz_cytatu({"paragraf": None, "ustep": None}) is None


def test_kontrola_poprawny_cytat_przechodzi():
    assert kontroluj_cytaty(_ocena("ODMOWA", [_cytat("6", "ust. 4")]), FRAGMENTY) == {
        "ok": True, "powod": None, "odrzucone": []
    }


def test_kontrola_cytat_spoza_kontekstu():
    wynik = kontroluj_cytaty(_ocena("ODMOWA", [_cytat("§ 6", "4"), _cytat("§ 6", "7")]), FRAGMENTY)
    assert wynik["ok"] is False
    assert wynik["powod"] == "cytat_spoza_kontekstu"
    assert wynik["odrzucone"] == [_cytat("§ 6", "7")]


@pytest.mark.parametrize("decyzja", ["POKRYTA", "ODMOWA"])
def test_kontrola_pokryta_i_odmowa_bez_cytatu(decyzja):
    assert kontroluj_cytaty(_ocena(decyzja), FRAGMENTY)["powod"] == "brak_cytatu"


@pytest.mark.parametrize("decyzja", ["UZUPELNIENIE", "SKIEROWANIE"])
def test_kontrola_uzupelnienie_i_skierowanie_bez_cytatu_ok(decyzja):
    assert kontroluj_cytaty(_ocena(decyzja), FRAGMENTY)["ok"] is True


def test_kontrola_bez_oceny():
    assert kontroluj_cytaty(None, FRAGMENTY)["powod"] == "brak_oceny"


@pytest.mark.parametrize(
    ("zmiany", "oczekiwane"),
    [
        ({}, ("POKRYTA", ["ocena_llm"])),
        ({"blad": "Blad wezla"}, ("SKIEROWANIE", ["blad_agenta"])),
        ({"podejrzane_instrukcje": True}, ("SKIEROWANIE", ["podejrzane_instrukcje"])),
        ({"wynik_polisy": {"kody": ["S01"], "braki": []}, "ocena_pokrycia": None}, ("SKIEROWANIE", ["S01"])),
        ({"wynik_polisy": {"kody": ["S02"], "braki": []}, "ocena_pokrycia": None}, ("ODMOWA", ["S02"])),
        ({"ocena_pokrycia": None}, ("SKIEROWANIE", ["brak_oceny"])),
        ({"ocena_pokrycia": _ocena("ODMOWA", [_cytat("§ 13", "3")])}, ("SKIEROWANIE", ["cytat_spoza_kontekstu"])),
        ({"ocena_pokrycia": _ocena("ODMOWA")}, ("SKIEROWANIE", ["brak_cytatu"])),
        ({"wynik_polisy": {"kody": ["S03"], "braki": []}}, ("SKIEROWANIE", ["S03"])),
        ({"wynik_polisy": {"kody": ["S04"], "braki": []}}, ("POKRYTA", ["ocena_llm"])),
        ({"ocena_pokrycia": _ocena("ODMOWA", [_cytat("§ 6", "4")])}, ("ODMOWA", ["ocena_llm"])),
        ({"ocena_pokrycia": _ocena("UZUPELNIENIE", brakujace=["faktury"])}, ("UZUPELNIENIE", ["ocena_llm"])),
    ],
)
def test_ustal_decyzje_szkody_priorytety(zmiany, oczekiwane):
    assert ustal_decyzje_szkody(_stan(**zmiany)) == oczekiwane


def test_kontrola_ze_stanu_ma_pierwszenstwo():
    stan = _stan(kontrola_cytatow={"ok": False, "powod": "cytat_spoza_kontekstu", "odrzucone": []})
    assert ustal_decyzje_szkody(stan) == ("SKIEROWANIE", ["cytat_spoza_kontekstu"])


def test_pokryta_z_brakami_idzie_do_skierowania():
    stan = _stan(wynik_polisy={"kody": [], "braki": ["data_zdarzenia", "rodzaj_mienia"]})
    assert ustal_decyzje_szkody(stan) == (
        "SKIEROWANIE",
        ["brak_danych:data_zdarzenia", "brak_danych:rodzaj_mienia"],
    )
    odmowa = _stan(
        wynik_polisy={"kody": [], "braki": ["data_zdarzenia"]},
        ocena_pokrycia=_ocena("ODMOWA", [_cytat("§ 6", "4")]),
    )
    assert ustal_decyzje_szkody(odmowa) == ("ODMOWA", ["ocena_llm"])


def test_podsumowanie_ma_pelna_tresc_cytatu():
    stan = _stan(
        ocena_pokrycia=_ocena("POKRYTA", [_cytat("§ 4", "1"), _cytat("§ 9", "9")]),
        kontrola_cytatow={"ok": False, "powod": "cytat_spoza_kontekstu", "odrzucone": [_cytat("§ 9", "9")]},
        plik="Z01.pdf",
    )
    podsumowanie = podsumowanie_szkody(stan)
    assert podsumowanie["typ_dokumentu"] == "SZKODA"
    assert podsumowanie["decyzja"] == "SKIEROWANIE"
    assert podsumowanie["decyzja_llm"] == "POKRYTA"
    assert podsumowanie["cytaty"][0]["fragment_id"] == "p4u1"
    assert podsumowanie["cytaty"][0]["tresc"].startswith("§ 4. Zakres ubezpieczenia")
    assert podsumowanie["cytaty"][1]["fragment_id"] is None
    assert podsumowanie["fragmenty_owu_id"] == ["p4u1", "p6u4"]
    assert set(podsumowanie) >= {
        "plik", "pola", "wynik_polisy", "decyzja", "powody_decyzji", "cytaty",
        "brakujace_dokumenty", "kontrola_cytatow", "dodatkowe_zapytanie", "blad", "podejrzane_instrukcje",
    }


def test_podsumowanie_bez_oceny_nie_wywraca_sie():
    podsumowanie = podsumowanie_szkody({"typ_dokumentu": "SZKODA", "blad": "x"})
    assert podsumowanie["decyzja"] == "SKIEROWANIE"
    assert podsumowanie["cytaty"] == [] and podsumowanie["fragmenty_owu_id"] == []


@pytest.mark.parametrize("parsuj", ["json", "dict"])
def test_zepsuty_znak_paragrafu_z_gpt5_mini_nie_odrzuca_cytatu(parsuj):
    # Zaobserwowane 15.10 na gpt-5-mini: "\u0000a7 2" zamiast "§ 2". Bez czyszczenia
    # klucz_cytatu bral "7" z "a7" za paragraf -> 4/12 szkod SKIEROWANIE "cytat_spoza_kontekstu",
    # a NUL wywrocilby zapis do Postgresa.
    import json

    from agent.schematy import OcenaPokrycia

    surowy = json.dumps({
        "decyzja": "POKRYTA",
        "cytaty": [{"paragraf": "\x00a7 2", "ustep": "7", "uzasadnienie": "zalanie\x00"}],
        "brakujace_dokumenty": [],
        "dodatkowe_zapytanie": None,
    })
    ocena = OcenaPokrycia.model_validate_json(surowy) if parsuj == "json" else OcenaPokrycia.model_validate(json.loads(surowy))
    cytat = ocena.cytaty[0].model_dump()
    assert cytat["paragraf"] == "§ 2" and cytat["uzasadnienie"] == "zalanie"
    assert klucz_cytatu(cytat) == (2, 7)
    assert kontroluj_cytaty(ocena.model_dump(), [{"paragraf": 2, "ustep": 7}])["ok"] is True
