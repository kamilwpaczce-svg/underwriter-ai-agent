# Ewaluacja vision (zdjecia szkod) - model: gpt-5-mini

detail: low, prog pewnosci: 0.6 (ustalony z gory, nie strojony), wywolania vision: 18
Rodzaje: 11/12 (z pokrewnymi 11/12), wykrycia N1-N5: 3/5, N6: niewykryta, falszywe alarmy: 2/12, bledy: 0.

## Metryki
- przypadki_lacznie: 18
- trafnosc_rodzaju: 11
- trafnosc_z_pokrewnymi: 11
- dlugotrwalosc_ok: 9
- wykrycie_niezgodnosci: 3
- n6_wynik: 0
- falszywe_alarmy: 2
- nieustalone: 4
- bledy: 0
- tokeny_we_na_zdjecie: 1582
- tokeny_wy_na_zdjecie: 354.3
- czas_p50_ms: 4879
- czas_p95_ms: 6551
- koszt_usd_na_zdjecie: 0.001104

```
ID | Zdjecie | Zgloszenie | Rodzaj(ocz->otrz) | Zgodnosc | Dlugotrw. | Wykryto | Pewn. | Czas[ms]
Z01 | Z01 | Z01 | pozar->pozar | ZGODNE | - | - | 0.90 | 5492
Z02 | Z02 | Z02 | zalanie->zalanie | ZGODNE | TAK | TAK | 0.90 | 4905
Z03 | Z03 | Z03 | przepiecie->przepiecie | ZGODNE | - | - | 0.90 | 4327
Z04 | Z04 | Z04 | kradziez_wlamanie->inne (!) | NIEUSTALONA | - | - | 0.90 | 4569
Z05 | Z05 | Z05 | korozja_zawilgocenie->korozja_zawilgocenie | ZGODNE | - | - | 0.90 | 4314
Z06 | Z06 | Z06 | awaria_wewnetrzna->awaria_wewnetrzna | ZGODNE | - | - | 0.90 | 6551
Z07 | Z07 | Z07 | kradziez_wlamanie->kradziez_wlamanie | ZGODNE | - | - | 0.80 | 5495
Z08 | Z08 | Z08 | pozar->pozar | ZGODNE | - | - | 0.90 | 4941
Z09 | Z09 | Z09 | zalanie->zalanie | ZGODNE | TAK | TAK | 0.85 | 4767
Z10 | Z10 | Z10 | zalanie->zalanie | ZGODNE | - | - | 0.90 | 4220
Z11 | Z11 | Z11 | huragan_wiatr->huragan_wiatr | ZGODNE | - | - | 0.80 | 5261
Z12 | Z12 | Z12 | pozar->pozar | ZGODNE | - | - | 0.90 | 4713
N1 | Z02 | Z01 | zalanie->zalanie | NIEZGODNE | TAK | TAK | 0.90 | 4879
N2 | Z12 | Z09 | pozar->pozar | NIEZGODNE | - | TAK | 0.90 | 4410
N3 | Z07 | Z08 | kradziez_wlamanie->inne (!) | NIEUSTALONA | - | - | 0.60 | 5077
N4 | Z11 | Z10 | huragan_wiatr->zalanie (!) | ZGODNE | - | - | 0.70 | 5226
N5 | Z05 | Z02 | korozja_zawilgocenie->korozja_zawilgocenie | NIEUSTALONA | TAK | TAK | 0.90 | 5089
N6 | Z06 | Z03 | awaria_wewnetrzna->awaria_wewnetrzna | NIEUSTALONA | - | - | 0.90 | 3993
```

## Pomylki
- Z02 (zdjecie Z02 pod zgloszenie Z02): rodzaj oczekiwany=zalanie, otrzymany=zalanie, zgodnosc=ZGODNE, wykryto=True
- Z04 (zdjecie Z04 pod zgloszenie Z04): rodzaj oczekiwany=kradziez_wlamanie, otrzymany=inne, zgodnosc=NIEUSTALONA, wykryto=False
- Z09 (zdjecie Z09 pod zgloszenie Z09): rodzaj oczekiwany=zalanie, otrzymany=zalanie, zgodnosc=ZGODNE, wykryto=True
- N3 (zdjecie Z07 pod zgloszenie Z08): rodzaj oczekiwany=kradziez_wlamanie, otrzymany=inne, zgodnosc=NIEUSTALONA, wykryto=False
- N4 (zdjecie Z11 pod zgloszenie Z10): rodzaj oczekiwany=huragan_wiatr, otrzymany=zalanie, zgodnosc=ZGODNE, wykryto=False