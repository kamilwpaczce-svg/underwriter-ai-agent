import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "generator"))

from nip import wygeneruj_poprawny_nip
from reguly import oblicz_decyzje, wczytaj_wytyczne

WYTYCZNE_SCIEZKA = Path(__file__).resolve().parent.parent / "wytyczne" / "wytyczne_mienie_v1.yaml"
WYTYCZNE = wczytaj_wytyczne(WYTYCZNE_SCIEZKA)

NIP_OK = wygeneruj_poprawny_nip("123456320")


def bazowe_pola(**nadpisania):
    pola = {
        "nazwa_firmy": "Firma Testowa Sp. z o.o.",
        "nip": NIP_OK,
        "adres": {"ulica": "ul. Testowa 1", "kod": "00-001", "miasto": "Warszawa"},
        "pkd": "46.49.Z",
        "branza": "handel hurtowy",
        "rodzaj_konstrukcji": "niepalna",
        "rok_budowy": 2000,
        "su_budynki": 1_000_000,
        "su_maszyny": 0,
        "su_zapasy": 0,
        "tryskacze": False,
        "ssp": False,
        "strefa_powodziowa": False,
        "szkody_3_lata": [],
        "okres_od": "2026-11-01",
        "okres_do": "2027-10-31",
        "data_wniosku": "2026-10-01",
        "broker": "Broker Testowy",
    }
    pola.update(nadpisania)
    return pola


def test_akceptacja_bez_regul():
    wynik = oblicz_decyzje(bazowe_pola(), WYTYCZNE)
    assert wynik == {"decyzja": "AKCEPTACJA", "reguly": []}


def test_r01_pkd_wylaczone_materialy_wybuchowe():
    wynik = oblicz_decyzje(bazowe_pola(pkd="20.51.Z"), WYTYCZNE)
    assert wynik["decyzja"] == "ODMOWA"
    assert "R01" in wynik["reguly"]


def test_r01_pkd_wylaczone_cala_sekcja_38():
    wynik = oblicz_decyzje(bazowe_pola(pkd="38.32.Z"), WYTYCZNE)
    assert "R01" in wynik["reguly"]


def test_r01_pkd_dozwolone_nie_dziala():
    wynik = oblicz_decyzje(bazowe_pola(pkd="46.49.Z"), WYTYCZNE)
    assert "R01" not in wynik["reguly"]


def test_r02_brak_nip():
    wynik = oblicz_decyzje(bazowe_pola(nip=None), WYTYCZNE)
    assert "R02" in wynik["reguly"]
    assert wynik["decyzja"] == "UZUPELNIENIE"


def test_r02_brak_deklaracji_szkodowosci():
    wynik = oblicz_decyzje(bazowe_pola(szkody_3_lata=None), WYTYCZNE)
    assert "R02" in wynik["reguly"]


def test_r02_brak_sumy_ubezpieczenia():
    wynik = oblicz_decyzje(bazowe_pola(su_budynki=0, su_maszyny=0, su_zapasy=0), WYTYCZNE)
    assert "R02" in wynik["reguly"]


def test_r02_pelne_dane_nie_dziala():
    wynik = oblicz_decyzje(bazowe_pola(), WYTYCZNE)
    assert "R02" not in wynik["reguly"]


def test_r03_nip_bledna_suma_kontrolna():
    zly_nip = NIP_OK[:9] + str((int(NIP_OK[9]) + 1) % 10)
    wynik = oblicz_decyzje(bazowe_pola(nip=zly_nip), WYTYCZNE)
    assert "R03" in wynik["reguly"]
    assert wynik["decyzja"] == "UZUPELNIENIE"


def test_r03_brak_nip_nie_uruchamia_r03():
    wynik = oblicz_decyzje(bazowe_pola(nip=None), WYTYCZNE)
    assert "R03" not in wynik["reguly"]


def test_r04_dokladnie_na_progu_nie_dziala():
    wynik = oblicz_decyzje(bazowe_pola(su_budynki=10_000_000, su_maszyny=0, su_zapasy=0), WYTYCZNE)
    assert "R04" not in wynik["reguly"]
    assert wynik["decyzja"] == "AKCEPTACJA"


def test_r04_jeden_pln_powyzej_progu_dziala():
    wynik = oblicz_decyzje(bazowe_pola(su_budynki=10_000_001, su_maszyny=0, su_zapasy=0), WYTYCZNE)
    assert "R04" in wynik["reguly"]
    assert wynik["decyzja"] == "SKIEROWANIE"


def test_r05_palna_powyzej_progu_bez_zabezpieczen():
    wynik = oblicz_decyzje(
        bazowe_pola(
            rodzaj_konstrukcji="drewniana",
            rok_budowy=2000,
            su_budynki=2_000_001,
            su_maszyny=0,
            su_zapasy=0,
            tryskacze=False,
            ssp=False,
        ),
        WYTYCZNE,
    )
    assert "R05" in wynik["reguly"]
    assert wynik["decyzja"] == "SKIEROWANIE"


def test_r05_dokladnie_na_progu_nie_dziala():
    wynik = oblicz_decyzje(
        bazowe_pola(rodzaj_konstrukcji="drewniana", rok_budowy=2000, su_budynki=2_000_000, tryskacze=False, ssp=False),
        WYTYCZNE,
    )
    assert "R05" not in wynik["reguly"]


def test_r05_z_tryskaczami_nie_dziala():
    wynik = oblicz_decyzje(
        bazowe_pola(rodzaj_konstrukcji="drewniana", rok_budowy=2000, su_budynki=2_000_001, tryskacze=True, ssp=False),
        WYTYCZNE,
    )
    assert "R05" not in wynik["reguly"]


def test_r05_z_ssp_nie_dziala():
    wynik = oblicz_decyzje(
        bazowe_pola(rodzaj_konstrukcji="plyta_warstwowa_eps", rok_budowy=2000, su_budynki=2_000_001, tryskacze=False, ssp=True),
        WYTYCZNE,
    )
    assert "R05" not in wynik["reguly"]


def test_r06_palna_przed_rokiem_granicznym():
    wynik = oblicz_decyzje(bazowe_pola(rodzaj_konstrukcji="drewniana", rok_budowy=1959), WYTYCZNE)
    assert "R06" in wynik["reguly"]
    assert wynik["decyzja"] == "ODMOWA"


def test_r06_dokladnie_rok_graniczny_nie_dziala():
    wynik = oblicz_decyzje(bazowe_pola(rodzaj_konstrukcji="drewniana", rok_budowy=1960), WYTYCZNE)
    assert "R06" not in wynik["reguly"]


def test_r06_niepalna_nie_dziala_mimo_starego_budynku():
    wynik = oblicz_decyzje(bazowe_pola(rodzaj_konstrukcji="niepalna", rok_budowy=1900), WYTYCZNE)
    assert "R06" not in wynik["reguly"]


def test_r07_trzy_szkody_dziala():
    szkody = [{"rok": 2024, "przyczyna": "zalanie", "kwota": 1000}] * 3
    wynik = oblicz_decyzje(bazowe_pola(szkody_3_lata=szkody), WYTYCZNE)
    assert "R07" in wynik["reguly"]
    assert wynik["decyzja"] == "SKIEROWANIE"


def test_r07_dwie_szkody_nie_dziala():
    szkody = [{"rok": 2024, "przyczyna": "zalanie", "kwota": 1000}] * 2
    wynik = oblicz_decyzje(bazowe_pola(szkody_3_lata=szkody), WYTYCZNE)
    assert "R07" not in wynik["reguly"]


def test_r07_pojedyncza_szkoda_dokladnie_na_progu_nie_dziala():
    szkody = [{"rok": 2024, "przyczyna": "pozar", "kwota": 500_000}]
    wynik = oblicz_decyzje(bazowe_pola(szkody_3_lata=szkody), WYTYCZNE)
    assert "R07" not in wynik["reguly"]


def test_r07_pojedyncza_szkoda_powyzej_progu_dziala():
    szkody = [{"rok": 2024, "przyczyna": "pozar", "kwota": 500_001}]
    wynik = oblicz_decyzje(bazowe_pola(szkody_3_lata=szkody), WYTYCZNE)
    assert "R07" in wynik["reguly"]


def test_r08_strefa_powodziowa_powyzej_progu():
    wynik = oblicz_decyzje(bazowe_pola(strefa_powodziowa=True, su_zapasy=1_000_001, su_budynki=1_000_000), WYTYCZNE)
    assert "R08" in wynik["reguly"]
    assert wynik["decyzja"] == "SKIEROWANIE"


def test_r08_dokladnie_na_progu_nie_dziala():
    wynik = oblicz_decyzje(bazowe_pola(strefa_powodziowa=True, su_zapasy=1_000_000, su_budynki=1_000_000), WYTYCZNE)
    assert "R08" not in wynik["reguly"]


def test_r08_bez_strefy_nie_dziala():
    wynik = oblicz_decyzje(bazowe_pola(strefa_powodziowa=False, su_zapasy=2_000_000, su_budynki=1_000_000), WYTYCZNE)
    assert "R08" not in wynik["reguly"]


def test_r09_okres_od_przed_data_wniosku():
    wynik = oblicz_decyzje(bazowe_pola(okres_od="2026-09-01", data_wniosku="2026-10-01"), WYTYCZNE)
    assert "R09" in wynik["reguly"]
    assert wynik["decyzja"] == "SKIEROWANIE"


def test_r09_okres_od_tego_samego_dnia_nie_dziala():
    wynik = oblicz_decyzje(bazowe_pola(okres_od="2026-10-01", data_wniosku="2026-10-01"), WYTYCZNE)
    assert "R09" not in wynik["reguly"]


def test_priorytet_odmowa_wygrywa_z_uzupelnieniem():
    wynik = oblicz_decyzje(
        bazowe_pola(nip=None, rodzaj_konstrukcji="drewniana", rok_budowy=1900),
        WYTYCZNE,
    )
    assert set(wynik["reguly"]) >= {"R02", "R06"}
    assert wynik["decyzja"] == "ODMOWA"


def test_priorytet_uzupelnienie_wygrywa_ze_skierowaniem():
    wynik = oblicz_decyzje(
        bazowe_pola(rodzaj_konstrukcji=None, szkody_3_lata=None, okres_od="2026-09-01", data_wniosku="2026-10-01"),
        WYTYCZNE,
    )
    assert set(wynik["reguly"]) >= {"R02", "R09"}
    assert wynik["decyzja"] == "UZUPELNIENIE"


def test_reguly_posortowane_po_id():
    wynik = oblicz_decyzje(
        bazowe_pola(nip=None, rodzaj_konstrukcji="drewniana", rok_budowy=1900),
        WYTYCZNE,
    )
    assert wynik["reguly"] == sorted(wynik["reguly"])
