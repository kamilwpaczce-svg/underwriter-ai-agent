# Ewaluacja agenta underwritera - model: gpt-5-mini_myslenie-low

Data: 20261028-1925
Liczba przypadkow: 14, w pelni zgodnych: 13
Czas calkowity: 235974 ms
Laczna liczba wywolan LLM: 40
Wariant grafu: wieloagentowy, trasa zgodna: 14/14
Tokeny lacznie: wejscie 71514, wyjscie 21133
OCR: 0 stron, 0 wywolan sieciowych, 23 trafien cache.
Koszt LLM (szacunkowy, cennik do weryfikacji): 0.0601 USD

```
ID | Typ | Pola | DecyzjaLLM | RegulyLLM | SilnikNaPolachLLM | Podejrzane | Czas[ms]
W01 | OK | 18/18 | OK | OK | OK | OK | 27002
W02 | OK | 18/18 | OK | OK | OK | OK | 18137
W03 | OK | 18/18 | OK | OK | OK | OK | 16609
W04 | OK | 18/18 | OK | OK | OK | OK | 15687
W05 | OK | 18/18 | OK | OK | OK | OK | 15422
W06 | OK | 18/18 | OK | OK | OK | OK | 12525
W07 | OK | 18/18 | OK | OK | OK | OK | 26221
W08 | OK | 18/18 | OK | OK | OK | OK | 15694
W09 | OK | 18/18 | OK | OK | OK | OK | 16124
W10 | OK | 18/18 | OK | OK | OK | OK | 17138
W11 | OK | 18/18 | OK | OK | OK | OK | 17614
W12 | OK | 17/18 | OK | OK | OK | OK | 18545
W13 | OK | 18/18 | OK | OK | OK | OK | 16348
W14 | OK | 0/0 | OK | OK | OK | OK | 2896
```

## Pomylki
- W12: decyzja oczekiwana=UZUPELNIENIE, otrzymana=UZUPELNIENIE; reguly oczekiwane=['R02', 'R09'], otrzymane=['R02', 'R09']; pola 17/18; silnik-na-polach-llm=UZUPELNIENIE