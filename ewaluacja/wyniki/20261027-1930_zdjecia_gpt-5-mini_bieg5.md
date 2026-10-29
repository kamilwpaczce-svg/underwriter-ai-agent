# Ewaluacja vision (zdjecia szkod) - model: gpt-5-mini

detail: low, prog pewnosci: 0.6 (ustalony z gory, nie strojony), wywolania vision: 18
Rodzaje: 11/12 (z pokrewnymi 11/12), wykrycia N1-N5: 4/5, N6: niewykryta, falszywe alarmy: 1/12, bledy: 0.

## Metryki
- przypadki_lacznie: 18
- trafnosc_rodzaju: 11
- trafnosc_z_pokrewnymi: 11
- dlugotrwalosc_ok: 10
- wykrycie_niezgodnosci: 4
- n6_wynik: 0
- falszywe_alarmy: 1
- nieustalone: 3
- bledy: 0
- tokeny_we_na_zdjecie: 1582
- tokeny_wy_na_zdjecie: 363.2
- czas_p50_ms: 4475
- czas_p95_ms: 5450
- koszt_usd_na_zdjecie: 0.001122

```
ID | Zdjecie | Zgloszenie | Rodzaj(ocz->otrz) | Zgodnosc | Dlugotrw. | Wykryto | Pewn. | Czas[ms]
Z01 | Z01 | Z01 | pozar->pozar | ZGODNE | - | - | 0.90 | 4017
Z02 | Z02 | Z02 | zalanie->zalanie | ZGODNE | - | - | 0.90 | 4733
Z03 | Z03 | Z03 | przepiecie->przepiecie | ZGODNE | - | - | 0.85 | 4054
Z04 | Z04 | Z04 | kradziez_wlamanie->inne (!) | NIEUSTALONA | - | - | 0.90 | 4311
Z05 | Z05 | Z05 | korozja_zawilgocenie->korozja_zawilgocenie | ZGODNE | - | - | 0.90 | 4047
Z06 | Z06 | Z06 | awaria_wewnetrzna->awaria_wewnetrzna | ZGODNE | - | - | 0.90 | 4530
Z07 | Z07 | Z07 | kradziez_wlamanie->kradziez_wlamanie | ZGODNE | - | - | 0.70 | 4540
Z08 | Z08 | Z08 | pozar->pozar | ZGODNE | - | - | 0.90 | 4084
Z09 | Z09 | Z09 | zalanie->zalanie | ZGODNE | TAK | TAK | 0.90 | 4475
Z10 | Z10 | Z10 | zalanie->zalanie | ZGODNE | - | - | 0.90 | 4148
Z11 | Z11 | Z11 | huragan_wiatr->huragan_wiatr | ZGODNE | - | - | 0.80 | 4931
Z12 | Z12 | Z12 | pozar->pozar | ZGODNE | - | - | 0.90 | 4276
N1 | Z02 | Z01 | zalanie->zalanie | NIEZGODNE | TAK | TAK | 0.90 | 5450
N2 | Z12 | Z09 | pozar->pozar | NIEZGODNE | - | TAK | 0.90 | 4502
N3 | Z07 | Z08 | kradziez_wlamanie->korozja_zawilgocenie (!) | NIEZGODNE | TAK | TAK | 0.60 | 5347
N4 | Z11 | Z10 | huragan_wiatr->zalanie (!) | ZGODNE | - | - | 0.80 | 4525
N5 | Z05 | Z02 | korozja_zawilgocenie->korozja_zawilgocenie | NIEUSTALONA | TAK | TAK | 0.90 | 4215
N6 | Z06 | Z03 | awaria_wewnetrzna->awaria_wewnetrzna | NIEUSTALONA | - | - | 0.90 | 4500
```

## Pomylki
- Z04 (zdjecie Z04 pod zgloszenie Z04): rodzaj oczekiwany=kradziez_wlamanie, otrzymany=inne, zgodnosc=NIEUSTALONA, wykryto=False
- Z09 (zdjecie Z09 pod zgloszenie Z09): rodzaj oczekiwany=zalanie, otrzymany=zalanie, zgodnosc=ZGODNE, wykryto=True
- N4 (zdjecie Z11 pod zgloszenie Z10): rodzaj oczekiwany=huragan_wiatr, otrzymany=zalanie, zgodnosc=ZGODNE, wykryto=False