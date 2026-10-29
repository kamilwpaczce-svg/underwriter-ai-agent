# Ewaluacja modulu szkodowego - model: gpt-5-mini

Wyszukiwarka: lokalna, top_k: 5, wersja OWU: dce3071a929f
Przypadki: 12, decyzje zgodne: 9, w pelni zgodne: 9
cytat_trafiony: 0.67, recall_wyszukiwania@5: 0.67
Tokeny: wejscie 53719, wyjscie 14815

```
ID | Decyzja | Cytat | Recall@5 | Kontrola | DodZapytanie | Czas[ms]
Z01 | OK | OK | OK | OK | - | 19336
Z02 | OK | OK | OK | OK | - | 16588
Z03 | BLAD(SKIEROWANIE!=POKRYTA) | BLAD | BLAD | OK | - | 10774
Z04 | OK | OK | OK | OK | - | 18416
Z05 | BLAD(SKIEROWANIE!=ODMOWA) | BLAD | BLAD | OK | - | 11379
Z06 | OK | OK | OK | OK | - | 15399
Z07 | BLAD(SKIEROWANIE!=UZUPELNIENIE) | BLAD | BLAD | OK | - | 10481
Z08 | OK | OK | OK | OK | - | 14587
Z09 | OK | - | - | OK | - | 11516
Z10 | OK | OK | OK | OK | - | 18347
Z11 | OK | - | - | OK | - | 9191
Z12 | OK | - | - | OK | - | 9634
```

## Pomylki
- Z03: decyzja oczekiwana=POKRYTA, otrzymana=SKIEROWANIE ['brak_oceny']; cytat_trafiony=False
- Z05: decyzja oczekiwana=ODMOWA, otrzymana=SKIEROWANIE ['brak_oceny']; cytat_trafiony=False
- Z07: decyzja oczekiwana=UZUPELNIENIE, otrzymana=SKIEROWANIE ['brak_oceny']; cytat_trafiony=False