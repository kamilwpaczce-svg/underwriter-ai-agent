"""Etap 23, zadanie 4: ewaluacja vision (`python -m ewaluacja.zdjecia`) na atrapie - zero sieci.

Testy sprawdzaja oba stany: zdrowy (atrapa = 12/12, 5/5, 0 falszywych alarmow) i chory (model, ktory
sie myli albo rzuca - metryki musza to pokazac, a nie wyjsc "zielone" z samej konstrukcji).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.model import MetadaneWywolania
from agent.schematy import OcenaZdjecia
from agent.zdjecia import POKREWNE, kategoria_przyczyny
from ewaluacja import uruchom, zdjecia
from ewaluacja.atrapa import ModelAtrapa
from ewaluacja.szkody import wczytaj_oczekiwany_szkody, wszystkie_id_szkod
from ewaluacja.zdjecia_przypadki import PARY_NIEZGODNE, pozycje_ewaluacji

ROOT = Path(__file__).resolve().parent.parent
OCZEKIWANE_DIR = ROOT / "dane" / "oczekiwane"


def _atrapa() -> ModelAtrapa:
    return ModelAtrapa(OCZEKIWANE_DIR)


def _bieg(model, limit_tokenow: int = 10_000_000):
    pozycje = pozycje_ewaluacji(wszystkie_id_szkod())
    return zdjecia.uruchom_bieg(model, pozycje, limit_tokenow)


class _ModelStaly:
    """Chory model: zawsze to samo, niezaleznie od zdjecia."""

    nazwa_modelu = "staly"

    def __init__(self, rodzaj: str, dlugotrwalosc: str = "NAGLE", pewnosc: float = 0.9, tokeny=(100, 20)):
        self._ocena = OcenaZdjecia(
            czy_widac_szkode=True, rodzaj_zdarzenia=rodzaj, widoczne_mienie=[], dlugotrwalosc=dlugotrwalosc,
            oznaki=[], pewnosc=pewnosc, tekst_na_zdjeciu=False,
        )
        self._tokeny = tokeny
        self.wywolania = 0

    def analizuj_zdjecie(self, obraz: bytes, mime_type: str):
        self.wywolania += 1
        return self._ocena, MetadaneWywolania(tokeny_we=self._tokeny[0], tokeny_wy=self._tokeny[1])


class _ModelRzucajacy:
    nazwa_modelu = "rzucajacy"

    def __init__(self, wyjatek: Exception):
        self._wyjatek = wyjatek
        self.wywolania = 0

    def analizuj_zdjecie(self, obraz: bytes, mime_type: str):
        self.wywolania += 1
        raise self._wyjatek


# --- lista pozycji -------------------------------------------------------------------------------


def test_osiemnascie_pozycji_dwanascie_zgodnych_i_szesc_par():
    pozycje = pozycje_ewaluacji(wszystkie_id_szkod())
    assert len(pozycje) == 18
    assert [p.id for p in pozycje[:12]] == [f"Z{i:02d}" for i in range(1, 13)]
    assert [p.id for p in pozycje[12:]] == ["N1", "N2", "N3", "N4", "N5", "N6"]
    assert len({p.id for p in pozycje}) == 18
    for p in pozycje[:12]:
        assert p.zdjecie == p.zgloszenie == p.id


def test_pary_niezgodne_wg_spec():
    assert [(p.id, p.zdjecie, p.zgloszenie) for p in PARY_NIEZGODNE] == [
        ("N1", "Z02", "Z01"), ("N2", "Z12", "Z09"), ("N3", "Z07", "Z08"),
        ("N4", "Z11", "Z10"), ("N5", "Z05", "Z02"), ("N6", "Z06", "Z03"),
    ]


def test_pary_n1_n4_to_rozne_niepokrewne_kategorie_a_n5_n6_pokrewne():
    """Dane pary musza byc takie, jak opisuje SPEC: N1-N4 sa NIEZGODNE z definicji, N5/N6 pokrewne."""
    kat = {}
    for p in PARY_NIEZGODNE:
        rodzaj_zdjecia = wczytaj_oczekiwany_szkody(p.zdjecie)["zdjecie"]["rodzaj_zdarzenia"]
        kat[p.id] = (rodzaj_zdjecia, kategoria_przyczyny(wczytaj_oczekiwany_szkody(p.zgloszenie)["pola"]["przyczyna"]))
    for id_pary in ("N1", "N2", "N3", "N4"):
        a, b = kat[id_pary]
        assert a != b and frozenset({a, b}) not in POKREWNE, id_pary
    for id_pary in ("N5", "N6"):
        assert frozenset(kat[id_pary]) in POKREWNE, id_pary


# --- stan zdrowy: atrapa -------------------------------------------------------------------------


def test_atrapa_12_z_12_rodzajow_5_z_5_wykryc_zero_falszywych_alarmow():
    wiersze, przerwano = _bieg(_atrapa())
    assert not przerwano
    m = zdjecia.metryki_zdjec(wiersze)
    assert m["trafnosc_rodzaju"] == 12
    assert m["trafnosc_z_pokrewnymi"] == 12
    assert m["dlugotrwalosc_ok"] == 12
    assert m["wykrycie_niezgodnosci"] == 5
    assert m["falszywe_alarmy"] == 0
    assert m["bledy"] == 0
    assert m["n6_wynik"] == 0.0  # N6 (Z06 pod Z03): kategorie pokrewne -> NIEUSTALONA, nie wykryta
    # N6 + N5 sa pokrewne -> NIEUSTALONA (2 szt.), reszta ZGODNE albo NIEZGODNE
    assert m["nieustalone"] == 2


def test_wiersz_ma_pola_ze_spec_i_unikalne_id():
    wiersze, _ = _bieg(_atrapa())
    wymagane = {
        "id", "zdjecie", "zgloszenie", "rodzaj_oczekiwany", "rodzaj_otrzymany", "rodzaj_ok", "rodzaj_ok_pokrewne",
        "dlugotrwalosc_ok", "zgodnosc_rodzaju", "sygnal_dlugotrwalosci", "wykryto", "falszywy_alarm", "pewnosc",
        "tokeny_we", "tokeny_wy", "czas_ms",
    }
    for w in wiersze:
        assert wymagane <= set(w), (w["id"], wymagane - set(w))
        for pole in ("rodzaj_ok", "rodzaj_ok_pokrewne", "dlugotrwalosc_ok", "wykryto", "falszywy_alarm",
                     "sygnal_dlugotrwalosci"):
            assert isinstance(w[pole], bool), (w["id"], pole)
    assert len({w["id"] for w in wiersze}) == 18


def test_n5_wykryta_przez_sygnal_dlugotrwalosci_a_n1_przez_niezgodnosc():
    wiersze, _ = _bieg(_atrapa())
    po_id = {w["id"]: w for w in wiersze}
    assert po_id["N1"]["zgodnosc_rodzaju"] == "NIEZGODNE" and po_id["N1"]["wykryto"] is True
    assert po_id["N5"]["zgodnosc_rodzaju"] == "NIEUSTALONA"
    assert po_id["N5"]["sygnal_dlugotrwalosci"] is True and po_id["N5"]["wykryto"] is True
    assert po_id["N6"]["wykryto"] is False
    assert all(po_id[f"Z{i:02d}"]["zgodnosc_rodzaju"] == "ZGODNE" for i in range(1, 13))
    assert all(w["falszywy_alarm"] is False for w in wiersze)


def test_bieg_wola_tylko_analizuj_zdjecie_osiemnascie_razy():
    model = _ModelStaly("pozar")
    _bieg(model)
    assert model.wywolania == 18


# --- stan chory: model sie myli / rzuca ---------------------------------------------------------


def test_model_mylacy_sie_obniza_metryki_i_daje_falszywe_alarmy():
    """Model, ktory na kazde zdjecie mowi 'pozar': trafia tylko w zdjecia pozarow (Z01, Z08, Z12),
    a na pozostalych zgodnych pozycjach daje falszywy alarm (NIEZGODNE ze zgloszona przyczyna)."""
    wiersze, _ = _bieg(_ModelStaly("pozar"))
    m = zdjecia.metryki_zdjec(wiersze)
    oczekiwane_pozary = [
        i for i in wszystkie_id_szkod() if wczytaj_oczekiwany_szkody(i)["zdjecie"]["rodzaj_zdarzenia"] == "pozar"
    ]
    assert m["trafnosc_rodzaju"] == len(oczekiwane_pozary) < 12
    assert m["falszywe_alarmy"] > 0
    zgodne_ids = {w["id"] for w in wiersze if w["id"].startswith("Z") and w["falszywy_alarm"]}
    assert zgodne_ids.isdisjoint(oczekiwane_pozary)


def test_model_rzucajacy_daje_wiersze_z_bledem_nie_wyjatek():
    model = _ModelRzucajacy(ValueError("nieznane zdjecie"))
    wiersze, przerwano = _bieg(model)
    assert not przerwano and len(wiersze) == 18
    assert all(w["blad"] == "ValueError" for w in wiersze)  # tylko nazwa typu, bez tresci wyjatku
    assert all(w["rodzaj_ok"] is False and w["wykryto"] is False and w["rodzaj_otrzymany"] is None for w in wiersze)
    m = zdjecia.metryki_zdjec(wiersze)
    assert m["bledy"] == 18 and m["trafnosc_rodzaju"] == 0 and m["wykrycie_niezgodnosci"] == 0


def test_rate_limit_przerywa_bieg():
    class RateLimitError(Exception):
        pass

    model = _ModelRzucajacy(RateLimitError("429"))
    wiersze, przerwano = _bieg(model)
    assert przerwano == "rate_limit"
    assert model.wywolania == 1 and len(wiersze) == 1


def test_bezpiecznik_tokenow_przerywa_i_zachowuje_wyniki_czesciowe():
    model = _ModelStaly("pozar", tokeny=(400, 100))  # 500 tokenow na zdjecie
    wiersze, przerwano = _bieg(model, limit_tokenow=1200)
    assert przerwano == "limit_tokenow"
    assert len(wiersze) == 3 and model.wywolania == 3  # po 3. zdjeciu 1500 > 1200


# --- metryki -------------------------------------------------------------------------------------


def test_metryki_tokeny_koszt_i_percentyle():
    wiersze, _ = _bieg(_ModelStaly("pozar", tokeny=(400, 100)))
    for i, w in enumerate(wiersze, start=1):
        w["czas_ms"] = float(i * 10)  # 10..180
    m = zdjecia.metryki_zdjec(wiersze, cena_we_usd_na_milion=0.25, cena_wy_usd_na_milion=2.0)
    assert m["tokeny_we_na_zdjecie"] == 400 and m["tokeny_wy_na_zdjecie"] == 100
    assert m["koszt_usd_na_zdjecie"] == pytest.approx((400 * 0.25 + 100 * 2.0) / 1_000_000)
    assert m["czas_p50_ms"] == 90.0     # nearest-rank: ceil(0,5*18)=9 -> 90
    assert m["czas_p95_ms"] == 180.0    # ceil(0,95*18)=18 -> 180
    assert m["przypadki_lacznie"] == 18


def test_metryki_bez_cennika_nie_maja_kosztu():
    wiersze, _ = _bieg(_atrapa())
    assert "koszt_usd_na_zdjecie" not in zdjecia.metryki_zdjec(wiersze)


def test_percentyl_nearest_rank():
    assert zdjecia.percentyl([5.0, 1.0, 3.0], 50) == 3.0
    assert zdjecia.percentyl([1.0, 2.0, 3.0, 4.0], 50) == 2.0
    assert zdjecia.percentyl([1.0, 2.0, 3.0, 4.0], 95) == 4.0
    assert zdjecia.percentyl([], 50) == 0.0


# --- CLI ----------------------------------------------------------------------------------------


def test_main_atrapa_zapisuje_json_i_md_w_formacie_dla_statystyki(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(zdjecia, "WYNIKI_DIR", tmp_path)
    assert zdjecia.main(["--atrapa"]) == 0
    (plik_json,) = tmp_path.glob("*_zdjecia_atrapa.json")
    (plik_md,) = tmp_path.glob("*_zdjecia_atrapa.md")
    wynik = json.loads(plik_json.read_text(encoding="utf-8"))
    assert wynik["modul"] == "zdjecia" and wynik["model"] == "atrapa"
    assert len(wynik["przypadki"]) == 18
    assert len({w["id"] for w in wynik["przypadki"]}) == 18
    assert wynik["metadane"]["prog_pewnosci"] == 0.6
    assert wynik["metadane"]["wywolania_llm_laczne"] == 18
    tresc_md = plik_md.read_text(encoding="utf-8")
    assert "trafnosc_rodzaju" in tresc_md and "wykrycie_niezgodnosci" in tresc_md
    wyjscie = capsys.readouterr().out
    assert "12/12" in wyjscie and "5/5" in wyjscie


def test_main_biegi_zapisuje_osobny_plik_na_bieg_i_zbiorczy_raport(monkeypatch, tmp_path):
    monkeypatch.setattr(zdjecia, "WYNIKI_DIR", tmp_path)
    assert zdjecia.main(["--atrapa", "--biegi", "2"]) == 0
    assert len(list(tmp_path.glob("*_zdjecia_atrapa_bieg*.json"))) == 2
    (zbiorczy,) = tmp_path.glob("*_zdjecia_atrapa_zbiorczo.md")
    tresc = zbiorczy.read_text(encoding="utf-8")
    assert "min" in tresc and "max" in tresc and "wykrycie_niezgodnosci" in tresc


def test_main_nieznany_detail_odrzucany_przez_argparse():
    with pytest.raises(SystemExit):
        zdjecia.main(["--atrapa", "--detail", "ultra"])


def test_main_bezpiecznik_tokenow_konczy_kodem_3_i_zapisuje_czesciowe(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(zdjecia, "WYNIKI_DIR", tmp_path)
    monkeypatch.setattr(zdjecia, "_zbuduj_model", lambda *a, **k: _ModelStaly("pozar", tokeny=(400, 100)))
    assert zdjecia.main(["--atrapa", "--limit-tokenow", "1200"]) == 3
    assert "bezpiecznik" in capsys.readouterr().err
    (plik,) = tmp_path.glob("*_zdjecia_staly.json")
    wynik = json.loads(plik.read_text(encoding="utf-8"))
    assert wynik["metadane"]["czesciowy"] is True and len(wynik["przypadki"]) == 3


def test_main_rate_limit_konczy_kodem_4_bez_zapisu(monkeypatch, tmp_path, capsys):
    class RateLimitError(Exception):
        pass

    monkeypatch.setattr(zdjecia, "WYNIKI_DIR", tmp_path)
    monkeypatch.setattr(zdjecia, "_zbuduj_model", lambda *a, **k: _ModelRzucajacy(RateLimitError("429")))
    assert zdjecia.main(["--atrapa"]) == 4
    assert not list(tmp_path.iterdir())


def test_main_mlflow_taguje_modul_zdjecia_i_loguje_parametry(monkeypatch, tmp_path):
    monkeypatch.setattr(zdjecia, "WYNIKI_DIR", tmp_path)
    przechwycone = []

    def falszywe_logowanie(**kwargs):
        przechwycone.append(kwargs)
        return "run-123"

    monkeypatch.setattr(zdjecia, "zaloguj_przebieg", falszywe_logowanie)
    assert zdjecia.main(["--atrapa", "--mlflow"]) == 0
    (wywolanie,) = przechwycone
    assert wywolanie["tagi_dodatkowe"]["modul"] == "zdjecia"
    assert wywolanie["parametry"]["prog_pewnosci"] == 0.6
    assert wywolanie["parametry"]["model"] == "atrapa"
    assert "detail" in wywolanie["parametry"]
    assert wywolanie["metryki"]["trafnosc_rodzaju"] == 12.0
    assert all(isinstance(v, float) for v in wywolanie["metryki"].values())
    assert wywolanie["zrodlo"] == "zdjecia"
    assert wywolanie["czesciowy"] is False


def test_main_blad_mlflow_konczy_kodem_5(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(zdjecia, "WYNIKI_DIR", tmp_path)

    def zepsute(**kwargs):
        raise RuntimeError("brak polaczenia")

    monkeypatch.setattr(zdjecia, "zaloguj_przebieg", zepsute)
    assert zdjecia.main(["--atrapa", "--mlflow"]) == 5
    assert "MLflow" in capsys.readouterr().err
    assert list(tmp_path.glob("*.json"))  # pliki zostaja mimo bledu MLflow


# --- uruchom.py --modul szkody --zdjecia ---------------------------------------------------------


def _wynik_szkod(monkeypatch, tmp_path, argumenty: list[str]) -> dict:
    katalog = tmp_path / ("z_flaga_" + "_".join(argumenty).replace("-", "") if argumenty else "bez_flagi")
    katalog.mkdir()
    monkeypatch.setattr(uruchom, "WYNIKI_DIR", katalog)
    assert uruchom.main(["--atrapa", "--modul", "szkody", *argumenty]) == 0
    (plik,) = katalog.glob("*_szkody_atrapa.json")
    return json.loads(plik.read_text(encoding="utf-8"))


def test_uruchom_zdjecia_na_atrapie_decyzje_identyczne_a_panel_ok_dla_11_z_12(monkeypatch, tmp_path):
    bez = _wynik_szkod(monkeypatch, tmp_path, [])
    ze = _wynik_szkod(monkeypatch, tmp_path, ["--zdjecia"])
    pominiete = {"_czas_ms", "zdjecie_status"}
    for w_bez, w_ze in zip(bez["przypadki"], ze["przypadki"], strict=True):
        assert {k: v for k, v in w_bez.items() if k not in pominiete} == {
            k: v for k, v in w_ze.items() if k not in pominiete
        }, w_bez["id"]
    assert all("zdjecie_status" not in w for w in bez["przypadki"])
    # Z12 to przypadek z wstrzyknieciem polecen (podejrzane=true): wezel zdjecia jest pomijany
    # (SPEC zadanie 3: BRAK_ZDJECIA z powodem `pominiete`), wiec status OK jest dla 11 z 12, nie 12/12.
    assert [w["zdjecie_status"] for w in ze["przypadki"]] == ["OK"] * 11 + ["BRAK_ZDJECIA"]
    assert ze["przypadki"][11]["id"] == "Z12"
    # zdjecie nie dolicza wywolan LLM do budzetu (osobny budzet, SPEC decyzja 6)
    assert ze["metadane"]["wywolania_llm_laczne"] == bez["metadane"]["wywolania_llm_laczne"]


def test_uruchom_zdjecia_dla_modulu_wnioski_odmawia(capsys):
    assert uruchom.main(["--atrapa", "--zdjecia"]) == 2
    assert "--zdjecia" in capsys.readouterr().err
