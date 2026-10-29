# Ewaluacja modulu szkodowego - model: gpt-5-mini

Wyszukiwarka: lokalna, top_k: 5, wersja OWU: dce3071a929f
Przypadki: 12, decyzje zgodne: 11, w pelni zgodne: 11
cytat_trafiony: 0.89, recall_wyszukiwania@5: 0.89
Tokeny: wejscie 56451, wyjscie 16243

```
ID | Decyzja | Cytat | Recall@5 | Kontrola | DodZapytanie | Czas[ms]
Z01 | OK | OK | OK | OK | - | 19843
Z02 | OK | OK | OK | OK | - | 16945
Z03 | BLAD(SKIEROWANIE!=POKRYTA) | BLAD | BLAD | OK | - | 12853
Z04 | OK | OK | OK | OK | - | 16464
Z05 | OK | OK | OK | OK | - | 14733
Z06 | OK | OK | OK | OK | - | 13846
Z07 | OK | OK | OK | OK | - | 17624
Z08 | OK | OK | OK | OK | - | 16198
Z09 | OK | - | - | OK | - | 11689
Z10 | OK | OK | OK | OK | - | 17471
Z11 | OK | - | - | OK | - | 8862
Z12 | OK | - | - | OK | - | 8442
```

## Pomylki
- Z03: decyzja oczekiwana=POKRYTA, otrzymana=SKIEROWANIE ['brak_oceny']; cytat_trafiony=False