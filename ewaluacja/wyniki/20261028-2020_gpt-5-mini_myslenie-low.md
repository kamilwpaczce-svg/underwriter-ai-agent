# Ewaluacja agenta underwritera - model: gpt-5-mini_myslenie-low

Data: 20261028-2020
Liczba przypadkow: 14, w pelni zgodnych: 13
Czas calkowity: 200588 ms
Laczna liczba wywolan LLM: 40
Wariant grafu: jeden, trasa zgodna: 14/14
Tokeny lacznie: wejscie 66342, wyjscie 20440
OCR: 0 stron, 0 wywolan sieciowych, 23 trafien cache.
Koszt LLM (szacunkowy, cennik do weryfikacji): 0.0575 USD

```
ID | Typ | Pola | DecyzjaLLM | RegulyLLM | SilnikNaPolachLLM | Podejrzane | Czas[ms]
W01 | OK | 18/18 | OK | OK | OK | OK | 13423
W02 | OK | 18/18 | OK | OK | OK | OK | 14434
W03 | OK | 18/18 | OK | OK | OK | OK | 13637
W04 | OK | 18/18 | OK | OK | OK | OK | 18132
W05 | OK | 18/18 | OK | OK | OK | OK | 13382
W06 | OK | 18/18 | OK | OK | OK | OK | 11935
W07 | OK | 18/18 | BLAD(UZUPELNIENIE!=SKIEROWANIE) | BLAD | OK | OK | 16941
W08 | OK | 18/18 | OK | OK | OK | OK | 15444
W09 | OK | 18/18 | OK | OK | OK | OK | 13002
W10 | OK | 18/18 | OK | OK | OK | OK | 15482
W11 | OK | 18/18 | OK | OK | OK | OK | 15081
W12 | OK | 18/18 | OK | OK | OK | OK | 20797
W13 | OK | 18/18 | OK | OK | OK | OK | 17516
W14 | OK | 0/0 | OK | OK | OK | OK | 1363
```

## Pomylki
- W07: decyzja oczekiwana=SKIEROWANIE, otrzymana=UZUPELNIENIE; reguly oczekiwane=['R07'], otrzymane=['R03', 'R07']; pola 18/18; silnik-na-polach-llm=SKIEROWANIE