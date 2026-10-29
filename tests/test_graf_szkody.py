"""Galaz SZKODA w grafie LangGraph na atrapie modelu i lokalnym BM25 - zero sieci."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.graf import zbuduj_graf
from agent.model import MetadaneWywolania
from agent.schematy import Cytat, EkstrakcjaSzkody, Klasyfikacja, OcenaPokrycia, PolaSzkody
from agent.wezly_szkody import ZAPYTANIE_DOMYSLNE, zbuduj_zapytanie_owu
from rag.wyszukiwarka import WyszukiwarkaLokalna

ROOT = Path(__file__).resolve().parent.parent
# Plik tylko do wezla `wczytaj` - tresc ignoruje atrapa.
PLIK = ROOT / "dane" / "wnioski" / "W01.pdf"
_METADANE = MetadaneWywolania(tokeny_we=10, tokeny_wy=5)

POLA_Z01 = {
    "nr_polisy": "PL/MSP/2026/0001",
    "data_zdarzenia": "2026-09-03",
    "data_zgloszenia": "2026-09-05",
    "przyczyna": "Pożar hali produkcyjnej piekarni wywołany zwarciem instalacji elektrycznej przy piecu",
    "rodzaj_mienia": "budynek",
    "szacowana_kwota": 380000,
    "okolicznosci": "Ogień objął dach i ściany hali, akcję gaśniczą prowadziła straż pożarna.",
    "zalaczniki": ["zaświadczenie straży pożarnej", "zdjęcia hali"],  # Etap 15: cecha liczba_zalacznikow
}


class AtrapaSzkody:
    """Test double ModelAgenta dla szkody: kolejne odpowiedzi z list albo wyjatki."""

    def __init__(self, ekstrakcja, oceny=(), typ="SZKODA"):
        self._typ = typ
        self._ekstrakcja = ekstrakcja
        self._oceny = list(oceny)
        self.wywolania_oceny: list[tuple] = []

    def klasyfikuj(self, czesci):
        return Klasyfikacja(typ_dokumentu=self._typ, uzasadnienie="test"), _METADANE

    def ekstrahuj_szkode(self, czesci):
        return self._ekstrakcja, _METADANE

    def ocen_pokrycie(self, pola, wynik_polisy, fragmenty, dodatkowe=None):
        self.wywolania_oceny.append(([f.id for f in fragmenty], None if dodatkowe is None else [f.id for f in dodatkowe]))
        element = self._oceny.pop(0)
        if isinstance(element, Exception):
            raise element
        return element, _METADANE


class LiczacaWyszukiwarka:
    nazwa = "liczaca"

    def __init__(self, blad: Exception | None = None):
        self._lokalna = WyszukiwarkaLokalna()
        self._blad = blad
        self.zapytania: list[tuple[str, int]] = []

    def szukaj(self, zapytanie, k=5):
        self.zapytania.append((zapytanie, k))
        if self._blad:
            raise self._blad
        return self._lokalna.szukaj(zapytanie, k)


def _ekstrakcja(podejrzane=False, **pola):
    return EkstrakcjaSzkody(pola=PolaSzkody(**{**POLA_Z01, **pola}), podejrzane_instrukcje=podejrzane)


def _uruchom(model, wyszukiwarka=None, model_ryzyka=None):
    graf = zbuduj_graf(model, InMemorySaver(), wyszukiwarka=wyszukiwarka, model_ryzyka=model_ryzyka)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    wynik = graf.invoke({"plik": str(PLIK), "wywolania_llm": 0, "log": []}, config)
    return graf, config, wynik


def _podsumowanie(wynik):
    assert "__interrupt__" in wynik
    return wynik["__interrupt__"][0].value


def test_zbuduj_zapytanie_owu():
    assert zbuduj_zapytanie_owu({"przyczyna": "Pożar", "rodzaj_mienia": "budynek", "okolicznosci": None}) == "Pożar budynek"
    assert zbuduj_zapytanie_owu({}) == ZAPYTANIE_DOMYSLNE


def test_szkoda_dochodzi_do_zatwierdzenia_z_cytatami_i_wznawia():
    ocena = OcenaPokrycia(decyzja="POKRYTA", cytaty=[Cytat(paragraf="§ 4", ustep="1", uzasadnienie="pożar")])
    model = AtrapaSzkody(_ekstrakcja(), [ocena])
    graf, config, wynik = _uruchom(model)
    podsumowanie = _podsumowanie(wynik)
    assert podsumowanie["typ_dokumentu"] == "SZKODA"
    assert podsumowanie["decyzja"] == "POKRYTA"
    assert podsumowanie["kontrola_cytatow"]["ok"] is True
    assert podsumowanie["cytaty"][0]["fragment_id"] == "p4u1"
    assert podsumowanie["cytaty"][0]["tresc"].startswith("§ 4. Zakres ubezpieczenia\nust. 1.")
    assert "p4u1" in podsumowanie["fragmenty_owu_id"]
    assert [w["wezel"] for w in wynik["log"]] == [
        "wczytaj", "klasyfikuj", "ekstrahuj_szkode", "analizuj_zdjecie", "sprawdz_polise", "ocen_ryzyko_szkody",
        "szukaj_owu", "ocen_pokrycie", "kontrola_cytatow",
    ]
    assert wynik["czesci"] is None

    koniec = graf.invoke(Command(resume={"decyzja": "POKRYTA", "kto": "likwidator"}), config)
    assert koniec["decyzja_koncowa"] == "POKRYTA"
    assert koniec["zatwierdzil"] == "likwidator"


def test_puste_pola_konczy_sie_s01_bez_oceny():
    pusta = EkstrakcjaSzkody(pola=PolaSzkody(), podejrzane_instrukcje=False)
    model = AtrapaSzkody(pusta)
    wyszukiwarka = LiczacaWyszukiwarka()
    _, _, wynik = _uruchom(model, wyszukiwarka)
    podsumowanie = _podsumowanie(wynik)
    assert podsumowanie["decyzja"] == "SKIEROWANIE"
    assert podsumowanie["powody_decyzji"] == ["S01"]
    assert model.wywolania_oceny == []
    assert wyszukiwarka.zapytania == []


def test_s02_odmowa_bez_llm_i_bez_wyszukiwania():
    model = AtrapaSzkody(_ekstrakcja(nr_polisy="PL/MSP/2025/0009", data_zdarzenia="2026-05-12", data_zgloszenia="2026-05-14"))
    wyszukiwarka = LiczacaWyszukiwarka()
    _, _, wynik = _uruchom(model, wyszukiwarka)
    podsumowanie = _podsumowanie(wynik)
    assert (podsumowanie["decyzja"], podsumowanie["powody_decyzji"]) == ("ODMOWA", ["S02"])
    assert podsumowanie["cytaty"] == []
    assert model.wywolania_oceny == [] and wyszukiwarka.zapytania == []


def test_podejrzane_instrukcje_ida_prosto_do_zatwierdzenia():
    model = AtrapaSzkody(_ekstrakcja(podejrzane=True))
    _, _, wynik = _uruchom(model)
    podsumowanie = _podsumowanie(wynik)
    assert (podsumowanie["decyzja"], podsumowanie["powody_decyzji"]) == ("SKIEROWANIE", ["podejrzane_instrukcje"])
    assert podsumowanie["wynik_polisy"] is None


def test_dodatkowe_zapytanie_maksymalnie_raz():
    pierwsza = OcenaPokrycia(decyzja="SKIEROWANIE", dodatkowe_zapytanie="dokumenty po kradzieży z włamaniem")
    druga = OcenaPokrycia(
        decyzja="POKRYTA",
        cytaty=[Cytat(paragraf="§ 4", ustep="1", uzasadnienie="pożar")],
        dodatkowe_zapytanie="jeszcze jedno zapytanie",
    )
    model = AtrapaSzkody(_ekstrakcja(), [pierwsza, druga])
    wyszukiwarka = LiczacaWyszukiwarka()
    _, _, wynik = _uruchom(model, wyszukiwarka)
    podsumowanie = _podsumowanie(wynik)
    assert len(model.wywolania_oceny) == 2
    assert [k for _, k in wyszukiwarka.zapytania] == [5, 3]
    assert wyszukiwarka.zapytania[1][0] == "dokumenty po kradzieży z włamaniem"
    assert model.wywolania_oceny[0][1] is None
    assert model.wywolania_oceny[1][1] is not None
    assert not set(model.wywolania_oceny[1][1]) & set(model.wywolania_oceny[1][0])
    assert podsumowanie["dodatkowe_zapytanie"] == "dokumenty po kradzieży z włamaniem"
    assert podsumowanie["decyzja"] == "POKRYTA"
    assert len(podsumowanie["fragmenty_owu_id"]) == len(set(podsumowanie["fragmenty_owu_id"]))
    assert [w["wezel"] for w in wynik["log"]].count("ocen_pokrycie_2") == 1
    assert wynik["wywolania_llm"] == 4


def test_cytat_spoza_kontekstu_daje_skierowanie():
    ocena = OcenaPokrycia(decyzja="ODMOWA", cytaty=[Cytat(paragraf="§ 13", ustep="3", uzasadnienie="zmyslony")])
    _, _, wynik = _uruchom(AtrapaSzkody(_ekstrakcja(), [ocena]))
    podsumowanie = _podsumowanie(wynik)
    assert (podsumowanie["decyzja"], podsumowanie["powody_decyzji"]) == ("SKIEROWANIE", ["cytat_spoza_kontekstu"])
    assert podsumowanie["decyzja_llm"] == "ODMOWA"


def test_kwota_ponad_su_pokryta_zmienia_sie_na_skierowanie():
    ocena = OcenaPokrycia(decyzja="POKRYTA", cytaty=[Cytat(paragraf="§ 4", ustep="1", uzasadnienie="pożar")])
    _, _, wynik = _uruchom(AtrapaSzkody(_ekstrakcja(szacowana_kwota=2_500_000), [ocena]))
    podsumowanie = _podsumowanie(wynik)
    assert (podsumowanie["decyzja"], podsumowanie["powody_decyzji"]) == ("SKIEROWANIE", ["S03"])
    assert podsumowanie["wynik_polisy"]["kody"] == ["S03"]


def test_blad_wyszukiwarki_daje_skierowanie_bez_oceny():
    model = AtrapaSzkody(_ekstrakcja())
    _, _, wynik = _uruchom(model, LiczacaWyszukiwarka(blad=ConnectionError("brak sieci")))
    podsumowanie = _podsumowanie(wynik)
    assert (podsumowanie["decyzja"], podsumowanie["powody_decyzji"]) == ("SKIEROWANIE", ["blad_agenta"])
    assert "ConnectionError" in podsumowanie["blad"]
    assert "brak sieci" in podsumowanie["blad"]  # tresc bledu, nie tylko klasa (403 vs 404)
    assert model.wywolania_oceny == []


def test_blad_llm_w_ocenie_po_2_probach_daje_skierowanie():
    model = AtrapaSzkody(_ekstrakcja(), [RuntimeError("x"), RuntimeError("y")])
    _, _, wynik = _uruchom(model)
    podsumowanie = _podsumowanie(wynik)
    assert (podsumowanie["decyzja"], podsumowanie["powody_decyzji"]) == ("SKIEROWANIE", ["blad_agenta"])
    assert "ocen_pokrycie" in podsumowanie["blad"]


@pytest.mark.parametrize("typ", ["WNIOSEK", "INNY"])
def test_routing_po_klasyfikacji_dla_innych_typow_bez_zmian(typ):
    from agent.wezly import po_klasyfikacji

    assert po_klasyfikacji({"typ_dokumentu": typ}) == ("ekstrahuj" if typ == "WNIOSEK" else "zakoncz_inny")
    assert po_klasyfikacji({"typ_dokumentu": "SZKODA"}) == "ekstrahuj_szkode"


# ---------------------------------------------------------------------------
# Etap 15: wezel ocen_ryzyko_szkody (sygnal ryzyka - nigdy nie zmienia decyzji ani trasy)
# ---------------------------------------------------------------------------

class AtrapaModeluRyzyka:
    wersja = "v-test"

    def __init__(self, wynik=0.73, glowne=("udzial_kwoty", "szkody_3_lata"), blad: Exception | None = None):
        self._wynik, self._glowne, self._blad = wynik, list(glowne), blad
        self.wywolania: list[dict] = []

    def ocen(self, cechy):
        self.wywolania.append(cechy)
        if self._blad:
            raise self._blad
        return {"wynik": self._wynik, "glowne_cechy": list(self._glowne)}


def _pokryta():
    return OcenaPokrycia(decyzja="POKRYTA", cytaty=[Cytat(paragraf="§ 4", ustep="1", uzasadnienie="pożar")])


def _kolejnosc_wezlow(wynik):
    return [w["wezel"] for w in wynik["log"]]


def _stan_do_ryzyka(**dodatki):
    return {
        "pola": {**POLA_Z01, "zalaczniki": ["a", "b"]},
        "wynik_polisy": {
            "polisa": {"okres_od": "2026-01-01", "szkody_3_lata": 1},
            "suma_ubezpieczenia": 2_000_000,
            "dni_do_zgloszenia": 2,
            "kody": [],
        },
        "log": [{"wezel": "x"}],
        **dodatki,
    }


def test_ryzyko_s01_brak_danych_a_trasa_bez_zmian():
    pusta = EkstrakcjaSzkody(pola=PolaSzkody(), podejrzane_instrukcje=False)
    model_ryzyka = AtrapaModeluRyzyka()
    _, _, wynik = _uruchom(AtrapaSzkody(pusta), LiczacaWyszukiwarka(), model_ryzyka)
    podsumowanie = _podsumowanie(wynik)
    assert podsumowanie["ryzyko"]["status"] == "BRAK_DANYCH"
    assert podsumowanie["ryzyko"]["wynik"] is None
    assert (podsumowanie["decyzja"], podsumowanie["powody_decyzji"]) == ("SKIEROWANIE", ["S01"])
    assert _kolejnosc_wezlow(wynik) == [
        "wczytaj", "klasyfikuj", "ekstrahuj_szkode", "analizuj_zdjecie", "sprawdz_polise", "ocen_ryzyko_szkody",
    ]
    assert model_ryzyka.wywolania == []  # bez cech model nie jest pytany


def test_ryzyko_brak_modelu_to_model_niedostepny_a_dalej_normalnie():
    _, _, wynik = _uruchom(AtrapaSzkody(_ekstrakcja(), [_pokryta()]))
    podsumowanie = _podsumowanie(wynik)
    assert podsumowanie["ryzyko"]["status"] == "MODEL_NIEDOSTEPNY"
    assert podsumowanie["ryzyko"]["wynik"] is None and podsumowanie["ryzyko"]["glowne_cechy"] == []
    assert podsumowanie["decyzja"] == "POKRYTA"


def test_ryzyko_ok_w_panelu_bez_cech_a_cechy_w_stanie():
    model_ryzyka = AtrapaModeluRyzyka()
    _, _, wynik = _uruchom(AtrapaSzkody(_ekstrakcja(), [_pokryta()]), model_ryzyka=model_ryzyka)
    ryzyko = _podsumowanie(wynik)["ryzyko"]
    assert ryzyko == {
        "status": "OK", "wynik": 0.73, "wersja": "v-test", "glowne_cechy": ["udzial_kwoty", "szkody_3_lata"],
    }
    assert "cechy" not in ryzyko
    cechy = wynik["ryzyko_szkody"]["cechy"]  # w stanie sa - potrzebne do zapisu wejsc modelu
    assert cechy == model_ryzyka.wywolania[0] and len(cechy) == 7
    assert cechy["udzial_kwoty"] == pytest.approx(380000 / 2_000_000)


def test_ryzyko_model_rzucajacy_to_model_niedostepny_i_nie_psuje_wniosku():
    model_ryzyka = AtrapaModeluRyzyka(blad=RuntimeError("zepsuty model"))
    _, _, wynik = _uruchom(AtrapaSzkody(_ekstrakcja(), [_pokryta()]), model_ryzyka=model_ryzyka)
    podsumowanie = _podsumowanie(wynik)
    assert podsumowanie["ryzyko"] == {
        "status": "MODEL_NIEDOSTEPNY", "wynik": None, "wersja": "v-test", "glowne_cechy": [],
    }
    assert podsumowanie["decyzja"] == "POKRYTA"


def test_ryzyko_wynik_nan_to_model_niedostepny():
    _, _, wynik = _uruchom(
        AtrapaSzkody(_ekstrakcja(), [_pokryta()]), model_ryzyka=AtrapaModeluRyzyka(wynik=float("nan"))
    )
    assert _podsumowanie(wynik)["ryzyko"]["status"] == "MODEL_NIEDOSTEPNY"


def test_podejrzane_instrukcje_omijaja_wezel_ryzyka_a_panel_ma_brak_danych():
    _, _, wynik = _uruchom(AtrapaSzkody(_ekstrakcja(podejrzane=True)), model_ryzyka=AtrapaModeluRyzyka())
    assert "ocen_ryzyko_szkody" not in _kolejnosc_wezlow(wynik)
    assert _podsumowanie(wynik)["ryzyko"] == {"status": "BRAK_DANYCH"}


def test_wezel_zmienia_tylko_ryzyko_i_log():
    import copy

    from agent.wezly_szkody import wezel_ocen_ryzyko_szkody

    stan = _stan_do_ryzyka()
    kopia = copy.deepcopy(stan)
    aktualizacja = wezel_ocen_ryzyko_szkody(stan, AtrapaModeluRyzyka())
    assert set(aktualizacja) == {"ryzyko_szkody", "log"}
    assert [w["wezel"] for w in aktualizacja["log"]] == ["x", "ocen_ryzyko_szkody"]
    assert stan == kopia  # wejscie nietkniete


def test_wezel_nigdy_nie_rzuca_na_dziwnym_stanie():
    from agent.wezly_szkody import wezel_ocen_ryzyko_szkody

    aktualizacja = wezel_ocen_ryzyko_szkody({"pola": "nie slownik", "wynik_polisy": 5}, AtrapaModeluRyzyka())
    assert aktualizacja["ryzyko_szkody"]["status"] == "BRAK_DANYCH"


def test_span_wezla_ryzyka_ma_tylko_status_wersje_i_wynik():
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from agent.wezly_szkody import wezel_ocen_ryzyko_szkody

    eksporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(eksporter))
    with provider.get_tracer("test").start_as_current_span("wezel.ocen_ryzyko_szkody"):
        wezel_ocen_ryzyko_szkody(_stan_do_ryzyka(), AtrapaModeluRyzyka())
    atrybuty = dict(eksporter.get_finished_spans()[0].attributes)
    assert atrybuty == {"uw.ryzyko.status": "OK", "uw.ryzyko.wersja": "v-test", "uw.ryzyko.wynik": 0.73}


def _przypadki_istniejacych_testow():
    """(id, fabryka modelu, fabryka wyszukiwarki) - po jednym na kazdy scenariusz galezi SZKODA."""
    pusta = EkstrakcjaSzkody(pola=PolaSzkody(), podejrzane_instrukcje=False)
    dodatkowe = [
        OcenaPokrycia(decyzja="SKIEROWANIE", dodatkowe_zapytanie="dokumenty po kradzieży z włamaniem"),
        OcenaPokrycia(decyzja="POKRYTA", cytaty=[Cytat(paragraf="§ 4", ustep="1", uzasadnienie="pożar")]),
    ]
    zmyslony = OcenaPokrycia(decyzja="ODMOWA", cytaty=[Cytat(paragraf="§ 13", ustep="3", uzasadnienie="zmyslony")])
    s02 = _ekstrakcja(nr_polisy="PL/MSP/2025/0009", data_zdarzenia="2026-05-12", data_zgloszenia="2026-05-14")
    return [
        ("pokryta", lambda: AtrapaSzkody(_ekstrakcja(), [_pokryta()]), LiczacaWyszukiwarka),
        ("s01", lambda: AtrapaSzkody(pusta), LiczacaWyszukiwarka),
        ("s02", lambda: AtrapaSzkody(s02), LiczacaWyszukiwarka),
        ("podejrzane", lambda: AtrapaSzkody(_ekstrakcja(podejrzane=True)), LiczacaWyszukiwarka),
        ("dodatkowe_zapytanie", lambda: AtrapaSzkody(_ekstrakcja(), list(dodatkowe)), LiczacaWyszukiwarka),
        ("cytat_spoza_kontekstu", lambda: AtrapaSzkody(_ekstrakcja(), [zmyslony]), LiczacaWyszukiwarka),
        ("kwota_ponad_su", lambda: AtrapaSzkody(_ekstrakcja(szacowana_kwota=2_500_000), [_pokryta()]), LiczacaWyszukiwarka),
        ("blad_wyszukiwarki", lambda: AtrapaSzkody(_ekstrakcja()), lambda: LiczacaWyszukiwarka(blad=ConnectionError("x"))),
        ("blad_llm", lambda: AtrapaSzkody(_ekstrakcja(), [RuntimeError("x"), RuntimeError("y")]), LiczacaWyszukiwarka),
    ]


def _odcisk(wynik):
    podsumowanie = _podsumowanie(wynik)
    return {
        "decyzja": podsumowanie["decyzja"],
        "powody": podsumowanie["powody_decyzji"],
        "cytaty": podsumowanie["cytaty"],
        "blad": podsumowanie["blad"],
        "fragmenty": podsumowanie["fragmenty_owu_id"],
        "wezly": [w for w in _kolejnosc_wezlow(wynik) if w not in ("ocen_ryzyko_szkody", "analizuj_zdjecie")],
        "wywolania_llm": wynik["wywolania_llm"],
    }


@pytest.mark.parametrize("przypadek", _przypadki_istniejacych_testow(), ids=lambda p: p[0])
@pytest.mark.parametrize("wariant", ["ok", "rzuca"])
def test_decyzja_i_trasa_identyczne_z_modelem_ryzyka_i_bez(przypadek, wariant):
    _, fabryka_modelu, fabryka_wyszukiwarki = przypadek
    model_ryzyka = AtrapaModeluRyzyka() if wariant == "ok" else AtrapaModeluRyzyka(blad=RuntimeError("x"))
    _, _, bez = _uruchom(fabryka_modelu(), fabryka_wyszukiwarki())
    _, _, z = _uruchom(fabryka_modelu(), fabryka_wyszukiwarki(), model_ryzyka)
    assert _odcisk(z) == _odcisk(bez)
    # test nie jest pusty: model faktycznie byl odpytany tam, gdzie sa cechy
    bez_cech = przypadek[0] in ("s01", "podejrzane")
    oczekiwany = "BRAK_DANYCH" if bez_cech else ("OK" if wariant == "ok" else "MODEL_NIEDOSTEPNY")
    assert _podsumowanie(z)["ryzyko"]["status"] == oczekiwany


# ---------------------------------------------------------------------------
# Etap 23, zadanie 3: wezel analizuj_zdjecie (sygnal dla likwidatora - nigdy nie zmienia decyzji ani trasy)
# ---------------------------------------------------------------------------

from agent.schematy import OcenaZdjecia  # noqa: E402

TRASA_ZE_ZDJECIEM = [
    "wczytaj", "klasyfikuj", "ekstrahuj_szkode", "analizuj_zdjecie", "sprawdz_polise", "ocen_ryzyko_szkody",
    "szukaj_owu", "ocen_pokrycie", "kontrola_cytatow",
]


def _ocena_zdjecia(rodzaj="pozar", dlugotrwalosc="NAGLE", pewnosc=0.9, **reszta) -> OcenaZdjecia:
    dane = {
        "czy_widac_szkode": True,
        "rodzaj_zdarzenia": rodzaj,
        "widoczne_mienie": ["hala"],
        "dlugotrwalosc": dlugotrwalosc,
        "oznaki": ["sadza"],
        "pewnosc": pewnosc,
        "tekst_na_zdjeciu": False,
    }
    dane.update(reszta)
    return OcenaZdjecia(**dane)


class AtrapaZeZdjeciem(AtrapaSzkody):
    """AtrapaSzkody z analizuj_zdjecie: kolejne wyniki z listy albo wyjatki; zlicza wywolania."""

    def __init__(self, ekstrakcja, oceny=(), wyniki_zdjecia=()):
        super().__init__(ekstrakcja, oceny)
        self._wyniki_zdjecia = list(wyniki_zdjecia)
        self.wywolania_zdjecia: list[tuple[int, str]] = []

    def analizuj_zdjecie(self, obraz, mime_type):
        self.wywolania_zdjecia.append((len(obraz), mime_type))
        element = self._wyniki_zdjecia.pop(0)
        if isinstance(element, Exception):
            raise element
        return element, MetadaneWywolania(tokeny_we=423, tokeny_wy=90)


def _plik_zdjecia(tmp_path, nazwa="zdjecie.jpg", bajty=b"\xff\xd8\xff-test"):
    sciezka = tmp_path / nazwa
    sciezka.write_bytes(bajty)
    return str(sciezka)


def _uruchom_ze_zdjeciem(model, zdjecia, wyszukiwarka=None, model_ryzyka=None):
    graf = zbuduj_graf(model, InMemorySaver(), wyszukiwarka=wyszukiwarka, model_ryzyka=model_ryzyka)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    wejscie = {"plik": str(PLIK), "wywolania_llm": 0, "log": []}
    if zdjecia is not None:
        wejscie["zdjecia"] = zdjecia
    return graf, config, graf.invoke(wejscie, config)


def test_zdjecie_ok_zgodne_trasa_i_panel(tmp_path):
    model = AtrapaZeZdjeciem(_ekstrakcja(), [_pokryta()], [_ocena_zdjecia()])
    _, _, wynik = _uruchom_ze_zdjeciem(model, [_plik_zdjecia(tmp_path)])
    podsumowanie = _podsumowanie(wynik)
    assert _kolejnosc_wezlow(wynik) == TRASA_ZE_ZDJECIEM
    assert model.wywolania_zdjecia == [(len(b"\xff\xd8\xff-test"), "image/jpeg")]
    zdjecie = podsumowanie["zdjecie"]
    assert zdjecie["status"] == "OK"
    assert zdjecie["kategoria_zgloszona"] == "pozar"
    assert zdjecie["zgodnosc_rodzaju"] == "ZGODNE"
    assert zdjecie["sygnal_dlugotrwalosci"] is False
    assert zdjecie["powody"] == []
    assert zdjecie["ocena"]["rodzaj_zdarzenia"] == "pozar"
    assert podsumowanie["decyzja"] == "POKRYTA"
    wpis = next(w for w in wynik["log"] if w["wezel"] == "analizuj_zdjecie")
    assert (wpis["tokeny_we"], wpis["tokeny_wy"]) == (423, 90)
    assert wynik["wywolania_llm"] == 3  # klasyfikuj, ekstrahuj_szkode, ocen_pokrycie - vision poza budzetem


def test_zdjecie_niezgodne_nie_zmienia_decyzji(tmp_path):
    model = AtrapaZeZdjeciem(_ekstrakcja(), [_pokryta()], [_ocena_zdjecia(rodzaj="zalanie")])
    _, _, wynik = _uruchom_ze_zdjeciem(model, [_plik_zdjecia(tmp_path)])
    _, _, bez = _uruchom_ze_zdjeciem(AtrapaSzkody(_ekstrakcja(), [_pokryta()]), None)
    podsumowanie = _podsumowanie(wynik)
    assert podsumowanie["zdjecie"]["zgodnosc_rodzaju"] == "NIEZGODNE"
    assert podsumowanie["decyzja"] == "POKRYTA"
    assert (podsumowanie["decyzja"], podsumowanie["powody_decyzji"]) == (
        _podsumowanie(bez)["decyzja"], _podsumowanie(bez)["powody_decyzji"],
    )


@pytest.mark.parametrize("zdjecia", [None, []])
def test_bez_zdjec_brak_zdjecia_i_zero_wywolan_vision(zdjecia):
    model = AtrapaZeZdjeciem(_ekstrakcja(), [_pokryta()])
    _, _, wynik = _uruchom_ze_zdjeciem(model, zdjecia)
    zdjecie = _podsumowanie(wynik)["zdjecie"]
    assert zdjecie["status"] == "BRAK_ZDJECIA" and zdjecie["ocena"] is None
    assert zdjecie["powody"] == []
    assert _kolejnosc_wezlow(wynik) == TRASA_ZE_ZDJECIEM
    assert model.wywolania_zdjecia == []


def test_plik_nie_istnieje_to_blad_odczytu(tmp_path):
    model = AtrapaZeZdjeciem(_ekstrakcja(), [_pokryta()])
    _, _, wynik = _uruchom_ze_zdjeciem(model, [str(tmp_path / "nie_ma.jpg")])
    podsumowanie = _podsumowanie(wynik)
    assert podsumowanie["zdjecie"]["status"] == "BLAD_ODCZYTU"
    assert podsumowanie["zdjecie"]["powody"] == ["plik_nie_istnieje"]
    assert podsumowanie["decyzja"] == "POKRYTA"
    assert model.wywolania_zdjecia == []
    assert str(tmp_path) not in str(podsumowanie["zdjecie"])  # sciezka nie wycieka do panelu


def test_zdjecie_za_duze_to_blad_odczytu(tmp_path):
    from agent.zdjecia import MAKS_ROZMIAR_BAJTOW

    model = AtrapaZeZdjeciem(_ekstrakcja(), [_pokryta()])
    plik = _plik_zdjecia(tmp_path, "duze.jpg", b"x" * (MAKS_ROZMIAR_BAJTOW + 1))
    _, _, wynik = _uruchom_ze_zdjeciem(model, [plik])
    zdjecie = _podsumowanie(wynik)["zdjecie"]
    assert (zdjecie["status"], zdjecie["powody"]) == ("BLAD_ODCZYTU", ["plik_za_duzy"])
    assert model.wywolania_zdjecia == []


def test_gif_to_blad_odczytu(tmp_path):
    model = AtrapaZeZdjeciem(_ekstrakcja(), [_pokryta()])
    _, _, wynik = _uruchom_ze_zdjeciem(model, [_plik_zdjecia(tmp_path, "a.gif", b"GIF89a")])
    zdjecie = _podsumowanie(wynik)["zdjecie"]
    assert (zdjecie["status"], zdjecie["powody"]) == ("BLAD_ODCZYTU", ["nieobslugiwany_typ"])
    assert model.wywolania_zdjecia == []


def test_niezgodny_naglowek_to_blad_odczytu_i_model_nie_dostaje_pliku(tmp_path):
    """PNG podszyty pod .jpg (rozszerzenie != magic bytes) -> BLAD_ODCZYTU, model nie jest wolany."""
    model = AtrapaZeZdjeciem(_ekstrakcja(), [_pokryta()])
    plik = _plik_zdjecia(tmp_path, "udaje.jpg", b"\x89PNG\r\n\x1a\n-dane")
    _, _, wynik = _uruchom_ze_zdjeciem(model, [plik])
    zdjecie = _podsumowanie(wynik)["zdjecie"]
    assert (zdjecie["status"], zdjecie["powody"]) == ("BLAD_ODCZYTU", ["niezgodny_naglowek"])
    assert model.wywolania_zdjecia == []


def test_model_rzuca_dwa_razy_to_model_niedostepny_bez_zmiany_budzetu_llm(tmp_path):
    model = AtrapaZeZdjeciem(
        _ekstrakcja(), [_pokryta()], [RuntimeError("tajna tresc bledu"), TimeoutError("x")]
    )
    _, _, wynik = _uruchom_ze_zdjeciem(model, [_plik_zdjecia(tmp_path)])
    podsumowanie = _podsumowanie(wynik)
    assert len(model.wywolania_zdjecia) == 2
    assert podsumowanie["zdjecie"]["status"] == "MODEL_NIEDOSTEPNY"
    assert podsumowanie["zdjecie"]["ocena"] is None
    assert podsumowanie["decyzja"] == "POKRYTA" and podsumowanie["blad"] is None
    assert wynik["wywolania_llm"] == 3  # identycznie jak bez zdjecia
    nazwy = [n for n in _kolejnosc_wezlow(wynik) if n.startswith("analizuj_zdjecie")]
    assert nazwy == ["analizuj_zdjecie_proba1_blad", "analizuj_zdjecie_proba2_blad", "analizuj_zdjecie"]
    assert "tajna tresc bledu" not in str(wynik["log"])  # w logu tylko nazwa klasy, nie tresc


def test_blad_vision_nie_zuzywa_limitu_a_ocen_pokrycie_dziala_z_dodatkowym_zapytaniem(tmp_path):
    """Najgorszy przypadek budzetu: ocen_pokrycie x2 (wywolania_llm=4) i vision pada 2x - decyzja ta sama."""
    pierwsza = OcenaPokrycia(decyzja="SKIEROWANIE", dodatkowe_zapytanie="dokumenty po kradzieży z włamaniem")
    model = AtrapaZeZdjeciem(_ekstrakcja(), [pierwsza, _pokryta()], [RuntimeError("a"), RuntimeError("b")])
    _, _, wynik = _uruchom_ze_zdjeciem(model, [_plik_zdjecia(tmp_path)])
    assert _podsumowanie(wynik)["decyzja"] == "POKRYTA"
    assert wynik["wywolania_llm"] == 4


def test_not_implemented_to_model_niedostepny_po_jednej_probie(tmp_path):
    model = AtrapaZeZdjeciem(_ekstrakcja(), [_pokryta()], [NotImplementedError("vllm")])
    _, _, wynik = _uruchom_ze_zdjeciem(model, [_plik_zdjecia(tmp_path)])
    assert len(model.wywolania_zdjecia) == 1
    assert _podsumowanie(wynik)["zdjecie"]["status"] == "MODEL_NIEDOSTEPNY"
    nazwy = [n for n in _kolejnosc_wezlow(wynik) if n.startswith("analizuj_zdjecie")]
    assert nazwy == ["analizuj_zdjecie_proba1_blad", "analizuj_zdjecie"]


def test_model_bez_metody_analizuj_zdjecie_to_model_niedostepny(tmp_path):
    """Zwykla AtrapaSzkody (bez analizuj_zdjecie) - AttributeError nie moze zepsuc grafu."""
    _, _, wynik = _uruchom_ze_zdjeciem(AtrapaSzkody(_ekstrakcja(), [_pokryta()]), [_plik_zdjecia(tmp_path)])
    assert _podsumowanie(wynik)["zdjecie"]["status"] == "MODEL_NIEDOSTEPNY"
    assert _podsumowanie(wynik)["decyzja"] == "POKRYTA"


def test_pierwsze_zdjecie_tylko_kolejne_pominiete(tmp_path):
    model = AtrapaZeZdjeciem(_ekstrakcja(), [_pokryta()], [_ocena_zdjecia()])
    pliki = [_plik_zdjecia(tmp_path, "a.jpg"), _plik_zdjecia(tmp_path, "b.png", b"\x89PNG\r\n\x1a\n-test")]
    _, _, wynik = _uruchom_ze_zdjeciem(model, pliki)
    zdjecie = _podsumowanie(wynik)["zdjecie"]
    assert len(model.wywolania_zdjecia) == 1 and model.wywolania_zdjecia[0][1] == "image/jpeg"
    assert zdjecie["status"] == "OK" and zdjecie["powody"] == ["pominieto_kolejne_zdjecia"]


def test_podejrzane_instrukcje_pomijaja_wezel_zdjecia(tmp_path):
    model = AtrapaZeZdjeciem(_ekstrakcja(podejrzane=True), wyniki_zdjecia=[_ocena_zdjecia()])
    _, _, wynik = _uruchom_ze_zdjeciem(model, [_plik_zdjecia(tmp_path)])
    assert "analizuj_zdjecie" not in _kolejnosc_wezlow(wynik)
    assert model.wywolania_zdjecia == []
    assert _podsumowanie(wynik)["zdjecie"] == {"status": "BRAK_ZDJECIA", "powody": ["pominiete"]}


def test_blad_ekstrakcji_pomija_wezel_zdjecia(tmp_path):
    class ModelZBledemEkstrakcji(AtrapaZeZdjeciem):
        def ekstrahuj_szkode(self, czesci):
            raise RuntimeError("x")

    model = ModelZBledemEkstrakcji(_ekstrakcja(), wyniki_zdjecia=[_ocena_zdjecia()])
    _, _, wynik = _uruchom_ze_zdjeciem(model, [_plik_zdjecia(tmp_path)])
    podsumowanie = _podsumowanie(wynik)
    assert podsumowanie["blad"] is not None
    assert "analizuj_zdjecie" not in _kolejnosc_wezlow(wynik) and model.wywolania_zdjecia == []
    assert podsumowanie["zdjecie"] == {"status": "BRAK_ZDJECIA", "powody": ["pominiete"]}


def test_panel_bez_sygnalu_w_stanie_to_brak_zdjecia():
    from agent.decyzje_szkody import podsumowanie_szkody

    assert podsumowanie_szkody({})["zdjecie"] == {"status": "BRAK_ZDJECIA", "powody": ["pominiete"]}


def test_wezel_zdjecia_zmienia_tylko_sygnal_i_log(tmp_path):
    import copy

    from agent.wezly_szkody import wezel_analizuj_zdjecie

    stan = _stan_do_ryzyka(zdjecia=[_plik_zdjecia(tmp_path)], wywolania_llm=2)
    kopia = copy.deepcopy(stan)
    model = AtrapaZeZdjeciem(_ekstrakcja(), wyniki_zdjecia=[_ocena_zdjecia()])
    aktualizacja = wezel_analizuj_zdjecie(stan, model)
    assert set(aktualizacja) == {"sygnal_zdjecia", "log"}
    assert [w["wezel"] for w in aktualizacja["log"]] == ["x", "analizuj_zdjecie"]
    assert stan == kopia  # wejscie nietkniete (w tym wywolania_llm)


@pytest.mark.parametrize(
    "stan",
    [
        {"pola": "nie slownik", "zdjecia": 5},
        {"pola": 5, "zdjecia": [None]},
        {"zdjecia": "sciezka_zamiast_listy.jpg"},
        {"pola": {"przyczyna": 12}, "zdjecia": ["/nie/ma/takiego.jpg"]},
    ],
)
def test_wezel_zdjecia_nigdy_nie_rzuca_na_dziwnym_stanie(stan):
    from agent.wezly_szkody import wezel_analizuj_zdjecie

    aktualizacja = wezel_analizuj_zdjecie(stan, AtrapaZeZdjeciem(_ekstrakcja(), wyniki_zdjecia=[_ocena_zdjecia()]))
    assert aktualizacja["sygnal_zdjecia"]["status"] in {"BRAK_ZDJECIA", "BLAD_ODCZYTU"}


def test_pole_zdjecia_nie_bedace_lista_to_blad_odczytu():
    from agent.wezly_szkody import wezel_analizuj_zdjecie

    sygnal = wezel_analizuj_zdjecie({"zdjecia": "a.jpg"}, AtrapaZeZdjeciem(_ekstrakcja()))["sygnal_zdjecia"]
    assert (sygnal["status"], sygnal["powody"]) == ("BLAD_ODCZYTU", ["nieprawidlowe_pole_zdjecia"])


def test_wezel_zdjecia_nie_rzuca_gdy_model_zwraca_smieci(tmp_path):
    from agent.wezly_szkody import wezel_analizuj_zdjecie

    class ModelZeSmieciami:
        def analizuj_zdjecie(self, obraz, mime_type):
            return "to nie jest OcenaZdjecia", MetadaneWywolania(tokeny_we=1, tokeny_wy=1)

    aktualizacja = wezel_analizuj_zdjecie(_stan_do_ryzyka(zdjecia=[_plik_zdjecia(tmp_path)]), ModelZeSmieciami())
    assert aktualizacja["sygnal_zdjecia"]["status"] == "MODEL_NIEDOSTEPNY"


def test_ustal_decyzje_szkody_nie_czyta_sygnalu_zdjecia():
    from agent.decyzje_szkody import ustal_decyzje_szkody

    class StanZPulapka(dict):
        def get(self, klucz, domyslnie=None):
            assert klucz != "sygnal_zdjecia", "decyzja nie moze czytac sygnalu zdjecia"
            return super().get(klucz, domyslnie)

        def __getitem__(self, klucz):
            assert klucz != "sygnal_zdjecia", "decyzja nie moze czytac sygnalu zdjecia"
            return super().__getitem__(klucz)

    stan = _stan_do_ryzyka(
        sygnal_zdjecia={"status": "OK", "zgodnosc_rodzaju": "NIEZGODNE", "sygnal_dlugotrwalosci": True},
        ocena_pokrycia={"decyzja": "POKRYTA", "cytaty": [], "brakujace_dokumenty": []},
        fragmenty_owu=[],
    )
    bez = {k: v for k, v in stan.items() if k != "sygnal_zdjecia"}
    assert ustal_decyzje_szkody(StanZPulapka(stan)) == ustal_decyzje_szkody(bez)


def test_span_wezla_zdjecia_ma_tylko_dozwolone_atrybuty(tmp_path):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from agent.wezly_szkody import wezel_analizuj_zdjecie

    def atrybuty_spanu(model, zdjecia):
        eksporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(eksporter))
        with provider.get_tracer("test").start_as_current_span("wezel.analizuj_zdjecie"):
            wezel_analizuj_zdjecie(_stan_do_ryzyka(zdjecia=zdjecia), model)
        return dict(eksporter.get_finished_spans()[0].attributes)

    ocena = _ocena_zdjecia(oznaki=["SZYLD_FIRMY_XYZ"], widoczne_mienie=["SZYLD_FIRMY_XYZ"])
    ok = atrybuty_spanu(
        AtrapaZeZdjeciem(_ekstrakcja(), wyniki_zdjecia=[ocena]), [_plik_zdjecia(tmp_path, "tajna_nazwa.jpg")]
    )
    assert ok == {
        "uw.zdjecie.status": "OK",
        "uw.zdjecie.rodzaj": "pozar",
        "uw.zdjecie.zgodnosc": "ZGODNE",
        "uw.zdjecie.dlugotrwalosc_sygnal": False,
        "uw.zdjecie.pewnosc": 0.9,
    }
    assert atrybuty_spanu(AtrapaZeZdjeciem(_ekstrakcja()), None) == {"uw.zdjecie.status": "BRAK_ZDJECIA"}
    assert atrybuty_spanu(AtrapaZeZdjeciem(_ekstrakcja()), ["/nie/ma/tajna_nazwa.jpg"]) == {
        "uw.zdjecie.status": "BLAD_ODCZYTU"
    }


# --- Test parametryczny: zdjecie nie zmienia decyzji ani trasy (Z01-Z12 x {bez, wlasne, para N}) ---

KATALOG_ZDJEC = ROOT / "dane" / "zdjecia_szkod"
IDS_SZKOD = [f"Z{n:02d}" for n in range(1, 13)]
# zgloszenie -> zdjecie z pary niezgodnej (SPEC decyzja 9): N1 Z02 pod Z01, N2 Z12 pod Z09, N3 Z07 pod Z08,
# N4 Z11 pod Z10, N5 Z05 pod Z02, N6 Z06 pod Z03.
PARY_N = {"Z01": "Z02", "Z09": "Z12", "Z08": "Z07", "Z10": "Z11", "Z02": "Z05", "Z03": "Z06"}
WARIANTY_ZDJEC = [(i, "bez") for i in IDS_SZKOD] + [(i, "wlasne") for i in IDS_SZKOD] + [(i, "para") for i in PARY_N]


def _przebieg_atrapy(id_przypadku, zdjecia):
    from ewaluacja.atrapa import ModelAtrapa

    model = ModelAtrapa(ROOT / "dane" / "oczekiwane")
    model.ustaw_przypadek(id_przypadku)
    graf = zbuduj_graf(model, InMemorySaver(), wyszukiwarka=WyszukiwarkaLokalna())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    wejscie = {"plik": str(ROOT / "dane" / "szkody" / f"{id_przypadku}.pdf"), "wywolania_llm": 0, "log": []}
    if zdjecia is not None:
        wejscie["zdjecia"] = zdjecia
    return graf.invoke(wejscie, config)


def _odcisk_trasy_i_decyzji(wynik):
    podsumowanie = _podsumowanie(wynik)
    return {
        "decyzja": podsumowanie["decyzja"],
        "powody": podsumowanie["powody_decyzji"],
        "decyzja_llm": podsumowanie["decyzja_llm"],
        "cytaty": podsumowanie["cytaty"],
        "blad": podsumowanie["blad"],
        "fragmenty": podsumowanie["fragmenty_owu_id"],
        "wezly": [w for w in _kolejnosc_wezlow(wynik) if not w.startswith("analizuj_zdjecie")],
        "wywolania_llm": wynik["wywolania_llm"],
    }


@pytest.mark.parametrize("id_przypadku, wariant", WARIANTY_ZDJEC, ids=lambda v: str(v))
def test_decyzja_i_trasa_identyczne_ze_zdjeciem_i_bez(id_przypadku, wariant):
    sciezka = {
        "bez": None,
        "wlasne": [str(KATALOG_ZDJEC / f"{id_przypadku}.jpg")],
        "para": [str(KATALOG_ZDJEC / f"{PARY_N.get(id_przypadku, id_przypadku)}.jpg")],
    }[wariant]
    bez = _przebieg_atrapy(id_przypadku, None)
    ze = _przebieg_atrapy(id_przypadku, sciezka)
    assert _odcisk_trasy_i_decyzji(ze) == _odcisk_trasy_i_decyzji(bez)

    zdjecie = _podsumowanie(ze)["zdjecie"]
    if wariant == "bez":
        assert zdjecie["status"] == "BRAK_ZDJECIA"
    elif _podsumowanie(bez)["podejrzane_instrukcje"]:
        assert zdjecie == {"status": "BRAK_ZDJECIA", "powody": ["pominiete"]}
    else:
        # test nie jest pusty: sygnal faktycznie policzony, a pary N1-N5 daja sygnal wprost
        assert zdjecie["status"] == "OK"
        assert "analizuj_zdjecie" in _kolejnosc_wezlow(ze)
        if wariant == "para" and id_przypadku in ("Z01", "Z09", "Z08", "Z10"):
            assert zdjecie["zgodnosc_rodzaju"] == "NIEZGODNE"
        if wariant == "para" and id_przypadku == "Z02":
            assert zdjecie["sygnal_dlugotrwalosci"] is True
