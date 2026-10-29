# Ewaluacja agenta underwritera - model: gpt-5-mini_myslenie-low

Data: 20261028-1958
Liczba przypadkow: 14, w pelni zgodnych: 13
Czas calkowity: 192906 ms
Laczna liczba wywolan LLM: 40
Wariant grafu: jeden, trasa zgodna: 14/14
Tokeny lacznie: wejscie 66328, wyjscie 20613
OCR: 0 stron, 0 wywolan sieciowych, 23 trafien cache.
Koszt LLM (szacunkowy, cennik do weryfikacji): 0.0578 USD

```
ID | Typ | Pola | DecyzjaLLM | RegulyLLM | SilnikNaPolachLLM | Podejrzane | Czas[ms]
W01 | OK | 18/18 | OK | OK | OK | OK | 16434
W02 | OK | 18/18 | OK | OK | OK | OK | 14268
W03 | OK | 18/18 | OK | OK | OK | OK | 14947
W04 | OK | 18/18 | OK | OK | OK | OK | 14370
W05 | OK | 18/18 | OK | OK | OK | OK | 13096
W06 | OK | 18/18 | OK | OK | OK | OK | 13189
W07 | OK | 18/18 | BLAD(UZUPELNIENIE!=SKIEROWANIE) | BLAD | OK | OK | 16326
W08 | OK | 18/18 | OK | OK | OK | OK | 14043
W09 | OK | 18/18 | OK | OK | OK | OK | 12976
W10 | OK | 18/18 | OK | OK | OK | OK | 16944
W11 | OK | 18/18 | OK | OK | OK | OK | 14053
W12 | OK | 18/18 | OK | OK | OK | OK | 16290
W13 | OK | 18/18 | OK | OK | OK | OK | 14003
W14 | OK | 0/0 | OK | OK | OK | OK | 1952
```

## Pomylki
- W07: decyzja oczekiwana=SKIEROWANIE, otrzymana=UZUPELNIENIE; reguly oczekiwane=['R07'], otrzymane=['R03', 'R07']; pola 18/18; silnik-na-polach-llm=SKIEROWANIE