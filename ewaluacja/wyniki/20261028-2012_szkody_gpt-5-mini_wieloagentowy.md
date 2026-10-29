# Ewaluacja modulu szkodowego - model: gpt-5-mini

Wyszukiwarka: lokalna, top_k: 5, wersja OWU: dce3071a929f
Przypadki: 12, decyzje zgodne: 10, w pelni zgodne: 10
cytat_trafiony: 0.78, recall_wyszukiwania@5: 0.78
Tokeny: wejscie 55067, wyjscie 15009

```
ID | Decyzja | Cytat | Recall@5 | Kontrola | DodZapytanie | Czas[ms]
Z01 | OK | OK | OK | OK | - | 17332
Z02 | OK | OK | OK | OK | - | 18734
Z03 | BLAD(SKIEROWANIE!=POKRYTA) | BLAD | BLAD | OK | - | 14562
Z04 | BLAD(SKIEROWANIE!=ODMOWA) | BLAD | BLAD | OK | - | 10975
Z05 | OK | OK | OK | OK | - | 14132
Z06 | OK | OK | OK | OK | - | 14934
Z07 | OK | OK | OK | OK | - | 16711
Z08 | OK | OK | OK | OK | - | 16429
Z09 | OK | - | - | OK | - | 11472
Z10 | OK | OK | OK | OK | - | 16026
Z11 | OK | - | - | OK | - | 10452
Z12 | OK | - | - | OK | - | 8789
```

## Pomylki
- Z03: decyzja oczekiwana=POKRYTA, otrzymana=SKIEROWANIE ['brak_oceny']; cytat_trafiony=False
- Z04: decyzja oczekiwana=ODMOWA, otrzymana=SKIEROWANIE ['brak_oceny']; cytat_trafiony=False