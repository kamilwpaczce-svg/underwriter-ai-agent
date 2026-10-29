# Ewaluacja modulu szkodowego - model: gpt-5-mini

Wyszukiwarka: lokalna, top_k: 5, wersja OWU: dce3071a929f
Przypadki: 12, decyzje zgodne: 10, w pelni zgodne: 10
cytat_trafiony: 0.78, recall_wyszukiwania@5: 0.78
Tokeny: wejscie 55101, wyjscie 15127

```
ID | Decyzja | Cytat | Recall@5 | Kontrola | DodZapytanie | Czas[ms]
Z01 | OK | OK | OK | OK | - | 16136
Z02 | OK | OK | OK | OK | - | 15064
Z03 | BLAD(SKIEROWANIE!=POKRYTA) | BLAD | BLAD | OK | - | 8515
Z04 | OK | OK | OK | OK | - | 17391
Z05 | OK | OK | OK | OK | - | 15726
Z06 | OK | OK | OK | OK | - | 21788
Z07 | BLAD(SKIEROWANIE!=UZUPELNIENIE) | BLAD | BLAD | OK | - | 10520
Z08 | OK | OK | OK | OK | - | 17568
Z09 | OK | - | - | OK | - | 10517
Z10 | OK | OK | OK | OK | - | 15104
Z11 | OK | - | - | OK | - | 9831
Z12 | OK | - | - | OK | - | 9588
```

## Pomylki
- Z03: decyzja oczekiwana=POKRYTA, otrzymana=SKIEROWANIE ['brak_oceny']; cytat_trafiony=False
- Z07: decyzja oczekiwana=UZUPELNIENIE, otrzymana=SKIEROWANIE ['brak_oceny']; cytat_trafiony=False