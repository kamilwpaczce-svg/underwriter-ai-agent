# Ewaluacja vision (zdjecia szkod) - model: gpt-5-mini

detail: low, prog pewnosci: 0.6 (ustalony z gory, nie strojony), wywolania vision: 18
Rodzaje: 10/12 (z pokrewnymi 10/12), wykrycia N1-N5: 4/5, N6: niewykryta, falszywe alarmy: 2/12, bledy: 0.

## Metryki
- przypadki_lacznie: 18
- trafnosc_rodzaju: 10
- trafnosc_z_pokrewnymi: 10
- dlugotrwalosc_ok: 9
- wykrycie_niezgodnosci: 4
- n6_wynik: 0
- falszywe_alarmy: 2
- nieustalone: 4
- bledy: 0
- tokeny_we_na_zdjecie: 1582
- tokeny_wy_na_zdjecie: 369.2
- czas_p50_ms: 4698
- czas_p95_ms: 5791
- koszt_usd_na_zdjecie: 0.001134

```
ID | Zdjecie | Zgloszenie | Rodzaj(ocz->otrz) | Zgodnosc | Dlugotrw. | Wykryto | Pewn. | Czas[ms]
Z01 | Z01 | Z01 | pozar->pozar | ZGODNE | - | - | 0.90 | 5166
Z02 | Z02 | Z02 | zalanie->zalanie | ZGODNE | - | - | 0.85 | 4910
Z03 | Z03 | Z03 | przepiecie->przepiecie | ZGODNE | - | - | 0.85 | 4045
Z04 | Z04 | Z04 | kradziez_wlamanie->inne (!) | NIEUSTALONA | - | - | 0.90 | 5300
Z05 | Z05 | Z05 | korozja_zawilgocenie->korozja_zawilgocenie | ZGODNE | - | - | 0.90 | 4790
Z06 | Z06 | Z06 | awaria_wewnetrzna->awaria_wewnetrzna | ZGODNE | - | - | 0.90 | 5221
Z07 | Z07 | Z07 | kradziez_wlamanie->korozja_zawilgocenie (!) | NIEZGODNE | TAK | TAK | 0.60 | 5791
Z08 | Z08 | Z08 | pozar->pozar | ZGODNE | - | - | 0.90 | 4293
Z09 | Z09 | Z09 | zalanie->zalanie | ZGODNE | TAK | TAK | 0.80 | 5066
Z10 | Z10 | Z10 | zalanie->zalanie | ZGODNE | - | - | 0.90 | 4165
Z11 | Z11 | Z11 | huragan_wiatr->huragan_wiatr | ZGODNE | - | - | 0.80 | 4647
Z12 | Z12 | Z12 | pozar->pozar | ZGODNE | - | - | 0.90 | 4898
N1 | Z02 | Z01 | zalanie->zalanie | NIEZGODNE | TAK | TAK | 0.85 | 4698
N2 | Z12 | Z09 | pozar->pozar | NIEZGODNE | - | TAK | 0.90 | 4516
N3 | Z07 | Z08 | kradziez_wlamanie->inne (!) | NIEUSTALONA | - | - | 0.60 | 4954
N4 | Z11 | Z10 | huragan_wiatr->huragan_wiatr | NIEZGODNE | - | TAK | 0.80 | 4654
N5 | Z05 | Z02 | korozja_zawilgocenie->korozja_zawilgocenie | NIEUSTALONA | TAK | TAK | 0.90 | 4587
N6 | Z06 | Z03 | awaria_wewnetrzna->awaria_wewnetrzna | NIEUSTALONA | - | - | 0.90 | 4373
```

## Pomylki
- Z04 (zdjecie Z04 pod zgloszenie Z04): rodzaj oczekiwany=kradziez_wlamanie, otrzymany=inne, zgodnosc=NIEUSTALONA, wykryto=False
- Z07 (zdjecie Z07 pod zgloszenie Z07): rodzaj oczekiwany=kradziez_wlamanie, otrzymany=korozja_zawilgocenie, zgodnosc=NIEZGODNE, wykryto=True
- Z09 (zdjecie Z09 pod zgloszenie Z09): rodzaj oczekiwany=zalanie, otrzymany=zalanie, zgodnosc=ZGODNE, wykryto=True
- N3 (zdjecie Z07 pod zgloszenie Z08): rodzaj oczekiwany=kradziez_wlamanie, otrzymany=inne, zgodnosc=NIEUSTALONA, wykryto=False