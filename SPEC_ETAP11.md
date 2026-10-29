# Etap 11 — trzeci dostawca LLM: vLLM (model open-source na wynajetym GPU)

Cel: trzeci dostawca obok Gemini i Azure OpenAI — model open-source (np. Bielik 11B,
Qwen3-8B) serwowany przez **vLLM** (API zgodne z OpenAI) na wynajetym GPU (RunPod),
za tym samym `ModelAgenta` (`agent/model.py`), bez zmiany grafu. Cel porownania: ta sama
ewaluacja co dla Azure — 14 wnioskow (`--modul wnioski`) + 12 zgloszen szkod
(`--modul szkody`) — zestawiona z `gpt-5-mini`: **wynik** (zgodnosc), **koszt**
(token vs. czas najmu GPU), **opoznienie** i **przepustowosc**.

## Zakres

1. **`agent/model_vllm.py`** — `ModelVLLM(ModelAzure)`. Dziedziczenie, nie kompozycja:
   OCR mediow (Document Intelligence, `agent/ocr_azure.py`) i wszystkie metody
   `ModelAgenta` sa identyczne jak w `ModelAzure` — jedyna roznica to budowa `self._llm`
   (`langchain_openai.ChatOpenAI` na `base_url` serwera vLLM) i zrodlo konfiguracji.
   Ten etap wymienia **tylko** dostawce LLM, nie dostawce OCR.
   - `ChatOpenAI(base_url=..., api_key=..., model=..., temperature=0, max_retries=1,
     timeout=180, extra_body=...)`.
   - Metoda structured output konfigurowalna (`VLLM_STRUCTURED_METHOD`, domyslnie
     `json_schema`; `function_calling`/`json_mode` dozwolone) przez cienki wrapper
     wokol `ChatOpenAI.with_structured_output` — `agent/model.py::_wywolaj_structured_llm`
     (wspolne dla kazdego dostawcy) **nie jest zmieniane**.
   - Domyslnie wylaczony tryb "myslenia" modeli typu Qwen3
     (`extra_body={"chat_template_kwargs": {"enable_thinking": False}}`),
     wylaczalne przez `VLLM_MYSLENIE=1`.
   - `self.myslenie = None` zawsze (brak odpowiednika `reasoning_effort` Azure) —
     `ewaluacja/uruchom.py` dokleja `myslenie` do nazwy modelu w wynikach tylko gdy
     wartosc jest "truthy", wiec `None` nic nie dokleja.
2. **`ewaluacja/uruchom.py`** — `--dostawca vllm`, galaz w `_zbuduj_model`. Raport:
   dostawca, nazwa modelu, metoda structured output. OCR (strony/wywolania/cache)
   nadal liczony (ten sam Document Intelligence). **Koszt USD liczony tylko dla Azure**
   (cennik $/token) — GPU wynajety rozlicza sie czasem najmu, nie tokenami; brak stawki
   $/h w repo, wiec koszt vLLM zostaje otwarty (patrz "Otwarte").
3. **`ewaluacja/szkody.py`**, **`api/`** — sprawdzone: `ewaluacja/szkody.py` nie ma
   wlasnego wyboru dostawcy (bierze gotowy `model`), zmiana nie byla potrzebna.
   `api/agent_serwis.py` **nie ruszany** — API produkcyjne demo zostaje na Azure OpenAI.

## Konfiguracja (zmienne srodowiskowe)

| zmienna | znaczenie |
|---|---|
| `VLLM_BASE_URL` | np. `https://<pod>-8000.proxy.runpod.net/v1` |
| `VLLM_MODEL` | nazwa modelu serwowanego przez vLLM |
| `VLLM_API_KEY` / `VLLM_API_KEY_FILE` | klucz API vLLM (wartosc / plik ze sciezka) |
| `VLLM_BEZ_KLUCZA=1` | jawna zgoda na brak klucza (serwer bez `--api-key`) |
| `VLLM_STRUCTURED_METHOD` | `json_schema` (domyslnie) / `function_calling` / `json_mode` |
| `VLLM_MYSLENIE=1` | nie wysylaj `enable_thinking: False` (domyslnie wysylane) |
| `VLLM_MAX_TOKENS` | limit dlugosci odpowiedzi, domyslnie 2048 (patrz Pulapki) |

## Czego NIE robimy

- API produkcyjne demo (`api/agent_serwis.py`) **zostaje na Azure OpenAI** — vLLM tylko
  w ewaluacji offline/porownawczej.
- GPU jest **wynajete** (RunPod), nie on-premise — zero wlasnej infrastruktury GPU.
- Nie zmieniamy dostawcy OCR (Document Intelligence zostaje dla wszystkich trzech
  dostawcow LLM).

## Testy

- `tests/test_model_vllm.py` — zero sieci: brak konfiguracji → `BrakKonfiguracjiVLLM`
  (i pominiecie tej walidacji przy wstrzynietym `llm`, jak w `ModelAzure`); klucz z pliku
  i z env; `VLLM_BEZ_KLUCZA`; wrapper wstrzykuje `method`; `extra_body` domyslny i pusty
  przy `VLLM_MYSLENIE=1`; OCR mediow przez wstrzykniety klient (tekst do LLM, bajty nie);
  `_zbuduj_model("vllm")`.

## Wyniki na zywo (2026-10-17)

Serwer: RunPod, 1x RTX PRO 4500 Blackwell (32 GB), EU-RO-1, 0,72 $/h, obraz
`vllm/vllm-openai:v0.31.0`, `--max-model-len 16384`, `json_schema` (xgrammar). Pod usuniety
po pomiarach; ~48 min najmu = ~0,58 $ (oba modele, z dwoma startami serwera).

| model | wnioski: decyzja LLM | wnioski: silnik regul na polach LLM | szkody | czas wnioskow |
|---|---|---|---|---|
| gpt-5-mini (Azure, low) | 14/14 | — | 11/12 (2026-10-15) | 232 s |
| Bielik-11B-v3.0-Instruct-FP8-Dynamic | 2/14 | 13/14 | 9/12, recall@5 0,89 | 1152 s* |
| Qwen3-8B (bf16, bez myslenia) | 2/14 | 14/14 | 8/12, recall@5 1,00 | 196 s |

\* Bielik bez `VLLM_MAX_TOKENS`: W08 (260 s) i W11 (744 s, ekstrakcja padla) to
zapetlenie generacji; bez nich ~150 s na 12 wnioskow. Jedyny blad silnika (W11) wynika z tego
zapetlenia, nie z jakosci pol.

Wniosek: oba modele open-source dobrze **ekstrahuja** pola, ale zle **decyduja** (Qwen
systematycznie ODMOWA - 11/14; Bielik myli sie w obie strony i dopisuje R04). Hybryda
"maly model on-prem do ekstrakcji + deterministyczny silnik regul do decyzji" daje 13-14/14,
tyle co gpt-5-mini, bez wysylania danych poza wlasne GPU - i z decyzja powtarzalna i
audytowalna. Ocena pokrycia szkody (rozumowanie na tekscie OWU) zostaje slabym punktem malych
modeli (8-9/12); trudne sa decyzje UZUPELNIENIE (Z07, Z08). Z10 myla wszystkie trzy modele
lacznie z gpt-5-mini - do sprawdzenia, czy to nie problem samego przypadku.

Zastrzezenie: 14 + 12 przypadkow, po jednym przebiegu na model, przypadki i oczekiwane
odpowiedzi ulozone przez nas - argument do demo, nie benchmark.

Wyniki: `ewaluacja/wyniki/20261017-*` (lokalnie, gitignored) + MLflow (`.venv-ewaluacja`).

## Pulapki (sprawdzone na zywo)

- **Zapetlenie przy `json_schema`**: Bielik bez limitu generowal ~7 tys. tokenow (~2 min GPU)
  do timeoutu klienta, wezel grafu ponawial. Poprawny JSON ma najwyzej kilkaset tokenow ->
  `VLLM_MAX_TOKENS` (domyslnie 2048) zamienia zapetlenie w szybki blad parsowania.
- **Cloudflare przed proxy RunPod zwraca 403 dla domyslnego User-Agenta `urllib`** -
  wlasna sonda musi ustawic UA; klient `openai` dziala bez zmian. 502 = serwer jeszcze nie
  nasluchuje (start ~5 min: pobranie wag, torch.compile, CUDA graphs).
- **Wariant obrazu `-cu129` crashowal** (`libnvrtc.so.13`) na hoscie CUDA 13.0 - dzialal
  obraz bazowy `v0.31.0`.
- MLflow jest tylko w `.venv-ewaluacja` - przebieg z `--mlflow` z `.venv` konczy sie
  `No module named 'mlflow'` po zapisaniu wynikow.

## Otwarte

- Bielik ponownie z `VLLM_MAX_TOKENS` (czysty pomiar W08/W11) - nie zrobione, nie zmieni
  wniosku.
- Przeliczenie kosztu: najem 0,72 $/h vs cennik $/token gpt-5-mini przy realnym wolumenie.
- Hybryda w samym grafie (decyzja z silnika, gdy dostawca = vLLM) - dzis tylko w ewaluacji.
