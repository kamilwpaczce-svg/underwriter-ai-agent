# Ewaluacja modulu szkodowego - model: gpt-5-mini

Wyszukiwarka: lokalna, top_k: 5, wersja OWU: dce3071a929f
Przypadki: 12, decyzje zgodne: 10, w pelni zgodne: 10
cytat_trafiony: 0.78, recall_wyszukiwania@5: 0.78
Tokeny: wejscie 55065, wyjscie 15795

```
ID | Decyzja | Cytat | Recall@5 | Kontrola | DodZapytanie | Czas[ms]
Z01 | OK | OK | OK | OK | - | 18370
Z02 | BLAD(SKIEROWANIE!=POKRYTA) | BLAD | BLAD | OK | - | 20778
Z03 | BLAD(SKIEROWANIE!=POKRYTA) | BLAD | BLAD | OK | - | 19590
Z04 | OK | OK | OK | OK | - | 15881
Z05 | OK | OK | OK | OK | - | 14867
Z06 | OK | OK | OK | OK | - | 15334
Z07 | OK | OK | OK | OK | - | 18750
Z08 | OK | OK | OK | OK | - | 14154
Z09 | OK | - | - | OK | - | 11562
Z10 | OK | OK | OK | OK | - | 16468
Z11 | OK | - | - | OK | - | 9537
Z12 | OK | - | - | OK | - | 10517
```

## Pomylki
- Z02: decyzja oczekiwana=POKRYTA, otrzymana=SKIEROWANIE ['brak_oceny']; cytat_trafiony=False
- Z03: decyzja oczekiwana=POKRYTA, otrzymana=SKIEROWANIE ['brak_oceny']; cytat_trafiony=False