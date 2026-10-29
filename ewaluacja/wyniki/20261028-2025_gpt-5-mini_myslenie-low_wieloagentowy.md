# Ewaluacja agenta underwritera - model: gpt-5-mini_myslenie-low

Data: 20261028-2025
Liczba przypadkow: 14, w pelni zgodnych: 13
Czas calkowity: 222380 ms
Laczna liczba wywolan LLM: 40
Wariant grafu: wieloagentowy, trasa zgodna: 14/14
Tokeny lacznie: wejscie 71496, wyjscie 20541
OCR: 0 stron, 0 wywolan sieciowych, 23 trafien cache.
Koszt LLM (szacunkowy, cennik do weryfikacji): 0.0590 USD

```
ID | Typ | Pola | DecyzjaLLM | RegulyLLM | SilnikNaPolachLLM | Podejrzane | Czas[ms]
W01 | OK | 18/18 | OK | OK | OK | OK | 25531
W02 | OK | 18/18 | OK | OK | OK | OK | 15703
W03 | OK | 18/18 | OK | OK | OK | OK | 16159
W04 | OK | 18/18 | OK | OK | OK | OK | 15490
W05 | OK | 18/18 | OK | OK | OK | OK | 15410
W06 | OK | 18/18 | OK | OK | OK | OK | 13644
W07 | OK | 18/18 | OK | OK | OK | OK | 15822
W08 | OK | 18/18 | OK | OK | OK | OK | 14122
W09 | OK | 18/18 | OK | OK | OK | OK | 13777
W10 | OK | 18/18 | OK | OK | OK | OK | 15172
W11 | OK | 18/18 | OK | OK | OK | OK | 21640
W12 | OK | 17/18 | OK | OK | OK | OK | 19077
W13 | OK | 18/18 | OK | OK | OK | OK | 18656
W14 | OK | 0/0 | OK | OK | OK | OK | 2164
```

## Pomylki
- W12: decyzja oczekiwana=UZUPELNIENIE, otrzymana=UZUPELNIENIE; reguly oczekiwane=['R02', 'R09'], otrzymane=['R02', 'R09']; pola 17/18; silnik-na-polach-llm=UZUPELNIENIE