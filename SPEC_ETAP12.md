# Etap 12 — Qdrant jako trzecia wyszukiwarka RAG po OWU

Cel: dodać Qdrant obok Azure AI Search i lokalnego BM25 jako trzeci backend `Wyszukiwarka`
(ten sam interfejs, `WYSZUKIWARKA=qdrant`) i policzyć trafność wyszukiwania (nie decyzji LLM —
same retrieval) na złotym zbiorze zgłoszeń szkód Z01–Z12, żeby mieć uczciwe porównanie silników,
nie embeddingów.

Praca wykonana w osobnym worktree `underwriter_agent_demo_qdrant`, branch `etap12-qdrant`,
żeby nie ruszać głównego katalogu (branch `etap11-vllm` w trakcie ewaluacji). Żadnego `git push`.

## Decyzje

1. **Wektor gęsty = ten sam embedding co Azure Search** (`text-embedding-3-small`, Azure OpenAI,
   Entra ID). Celowo — porównujemy silniki wyszukiwania (Qdrant vs Azure AI Search vs lokalny
   BM25), nie modele embeddingów. `rag/qdrant_search.py` importuje `zbuduj_embedder()` wprost
   z `rag.azure_search`.
2. **Wektor rzadki = własny hash-based BM25-lite, nie fastembed `Qdrant/bm25`.** Sprawdzone
   empirycznie: `fastembed.sparse.bm25.supported_languages` nie zawiera `"polish"`
   (`SparseTextEmbedding('Qdrant/bm25', language='polish')` rzuca `ValueError`), a wymuszenie
   `language="english"` źle stemuje polskie słowa. Zamiast tego: ten sam `tokenizuj()` z
   `rag/wyszukiwarka.py` (już używany przez `WyszukiwarkaLokalna`), zliczenie częstości tokenów,
   indeks wymiaru = `sha1(token) mod (2**31 - 1)` (żeby nie trzeba było trzymać wspólnego słownika
   między indeksowaniem a zapytaniem), `SparseVectorParams(modifier=Modifier.IDF)` — Qdrant liczy
   IDF w locie z zaindeksowanego TF. **To przybliżenie, nie klasyczne BM25**: brakuje normalizacji
   po długości dokumentu (parametr `b`) i `k1` — przy bardzo krótkich/długich fragmentach wynik
   może się różnić od `WyszukiwarkaLokalna` (klasyczny BM25 k1=1.5, b=0.75). Opisane w nagłówku
   `rag/qdrant_search.py`. `fastembed` celowo NIE trafił do `requirements.txt` — niewykorzystany
   w ostatecznym kodzie (był tylko do eksploracji/odrzucenia opcji).
3. **Fuzja hybrydowa: Query API, `prefetch` + `FusionQuery(fusion=Fusion.RRF)`**, limit prefetch
   = `TOP_K * 4` na gałąź (stała `MNOZNIK_PREFETCH`), dobrana bez pomiaru — zapas, żeby RRF miał
   z czego wybierać; nie testowano wrażliwości wyniku na tę stałą.
4. **ID punktów:** Qdrant wymaga int/UUID, `Fragment.id` to string (`"p4u1"`) → deterministyczny
   `uuid.uuid5(NAMESPACE_STALY, fragment_id)`, więc ten sam fragment zawsze dostaje ten sam punkt
   (idempotentny upsert) bez trzymania osobnej mapy id→UUID.
5. **Indeksowanie: osobny skrypt `rag/indeksuj_owu_qdrant.py`, nie rozszerzenie
   `rag/indeksuj_owu.py`.** `indeksuj_owu.py` jest mocno Azure-specyficzny (`SearchIndexClient`,
   `_czekaj_na_indeksacje()` na eventual consistency, definicja indeksu w formacie Azure) —
   doklejanie gałęzi Qdrant do tej samej funkcji wymagałoby rozgałęzień `if klient Azure / if
   klient Qdrant` w środku wspólnej logiki. Osobny plik jest mniej inwazyjny: zero zmian
   w działającym kodzie Azure, powtórzona tylko logika obliczania fragmentów i wersji OWU
   (`rag.fragmenty`), reszta (budowa klienta Qdrant, kolekcja, upsert, usuwanie nieaktualnych
   punktów przez `scroll`) jest nowa i niezależna. Interpretacja punktu zadania „mniej
   inwazyjne” — własna decyzja, nie konsultowana.
6. **Tryb klienta:** `QDRANT_URL` ma pierwszeństwo nad `QDRANT_PATH`; brak obu → domyślnie
   `QDRANT_PATH=.qdrant_lokalny/` (tryb embedded na dysku, bez serwera). Użyty we wszystkich
   przebiegach w tej sesji był `:memory:` (testy) i `.qdrant_lokalny/`/`:memory:` (porównanie) —
   **serwer przez `docker-compose.qdrant.yml` NIE był uruchamiany ani testowany** (Docker Desktop
   był wyłączony na tej maszynie i zgodnie z poleceniem nie został włączony). Obraz
   `qdrant/qdrant:v1.19.2` — tag sprawdzony na Docker Hub 17.10.2026 (nie z pamięci modelu),
   dobrany pod wersję zainstalowanego `qdrant-client==1.19.1`.
7. **Domyślny `QDRANT_TRYB=hybryda`** (dense+sparse+RRF) — wybór własny, bo to tryb najbliższy
   temu, co robi `WyszukiwarkaAzure` (hybrydowa). `gesty`/`rzadki` istnieją do diagnostyki
   i do porównania w `ewaluacja/porownaj_wyszukiwarki.py`.
8. **Cache embeddingów na dysku** (`rag/cache_embeddingow.py`, `.cache_embeddingow/`, klucz
   `sha256(f"{model}:{tekst}")`) — żeby porównanie wielu wariantów (lokalna/azure/azure+semantyczna/
   qdrant/qdrant-gesty/qdrant-rzadki) w jednym przebiegu nie płaciło za ten sam embedding
   wielokrotnie. Skutek uboczny opisany w sekcji Wyniki (zastrzeżenie o czasie).
9. **Punkt opcjonalny z zadania (lokalne polskie embeddingi, np. `sdadas/mmlw-retrieval-roberta-base`,
   osobna kolekcja) — POMINIĘTY.** Decyzja własna: already dostarczone 3 warianty (hybryda/gęsty/
   rzadki) na Qdrant plus Azure plus lokalny BM25 dają 6-pozycyjną tabelę porównawczą, co
   realizuje sedno zadania („porównanie trafności"); dorzucenie czwartego silnika embeddingów
   (pobranie modelu ~500MB+, osobna kolekcja, osobny prefiks zapytania wymagany przez ten model)
   poszerzyłoby zakres bez decyzji, która by się dzięki temu zmieniła — zgodnie z zasadą projektu
   „przed budową pytaj, jaka decyzja się zmieni". Nie jest to ocena, że wariant jest bez wartości,
   tylko że wykracza poza czas i zakres tej sesji.

## Wyniki porównania

Złoty zbiór: 9 z 12 zgłoszeń szkód (Z01–Z12) ma niepusty `paragrafy_oczekiwane`
(S01/S02-podobne bez paragrafu są pomijane — ta sama konwencja co `ewaluacja/szkody.py`).
Zapytania budowane dokładnie tą samą funkcją co produkcja: `agent.wezly_szkody.zbuduj_zapytanie_owu`.
Dane realne: Azure OpenAI + Azure AI Search przez `az login` (konto z limitem wydatków, read-only
na Search — indeks nie był modyfikowany, żadne nowe zasoby Azure nie zostały utworzone).

Przebieg `python ewaluacja/porownaj_wyszukiwarki.py`, zapisany w
`ewaluacja/wyniki/20261017-1455_wyszukiwarki.{json,md}` (gitignored jak reszta `ewaluacja/wyniki/`,
zgodnie z istniejącą regułą `.gitignore:5` w tym repo — niezmienioną w tym etapie):

| Wyszukiwarka | N | Recall@1 | Recall@3 | Recall@5 | MRR@5 | p50 [ms] | p95 [ms] | Błędy |
|---|---|---|---|---|---|---|---|---|
| lokalna | 9 | 67% | 89% | 100% | 0.806 | 0.2 | 0.2 | 0 |
| azure | 9 | 44% | 89% | 100% | 0.689 | 46.4 | 1257.2 | 0 |
| azure+semantyczna | 9 | 67% | 100% | 100% | 0.833 | 82.6 | 96.3 | 0 |
| qdrant (hybryda) | 9 | 44% | 89% | 100% | 0.676 | 5.0 | 6.8 | 0 |
| qdrant-gesty | 9 | 33% | 78% | 89% | 0.565 | 1.1 | 2.3 | 0 |
| qdrant-rzadki | 9 | 56% | 89% | 100% | 0.750 | 1.1 | 1.2 | 0 |

**Zastrzeżenie o próbce:** 9 zapytań — różnica o 1 trafienie to kilkanaście punktów procentowych
recall. Kierunek, nie precyzyjny pomiar.

**Zastrzeżenie o czasie:** wszystkie warianty dzielą jeden cache embeddingów na dysku — ten sam
tekst zapytania płaci za embedding Azure OpenAI tylko raz w całym przebiegu. Wariant uruchomiony
jako pierwszy (`lokalna` nie płaci wcale, `azure` płaci naprawdę) ponosi prawdziwy koszt sieciowy
embeddingu; warianty Qdrant uruchomione po Azure dostają ten embedding z cache za darmo.
p50/p95 powyżej **nie są więc uczciwym porównaniem end-to-end** (zapytanie użytkownika → wynik).
Qdrant mierzy tu w dużej części sam czas wyszukiwania w lokalnej, embedded bazie bez sieci —
różnica rząd-wielkości względem Azure wynika częściowo z architektury (baza lokalna vs HTTP do
Azure), częściowo z efektu cache. Żeby zmierzyć uczciwie end-to-end, trzeba by uruchamiać każdy
wariant w osobnym procesie z pustym cache embeddingów — nie zrobione w tej sesji.

**Odczyt trafności (recall/MRR, niezależny od efektu cache):** na tym małym zbiorze `lokalna`
i `qdrant-rzadki` (oba oparte o BM25-podobne dopasowanie leksykalne) wypadają najlepiej spośród
wariantów jednosilnikowych; `azure+semantyczna` (jedyny wariant z rerankerem) ma najwyższy
recall@3/MRR ogółem; `qdrant-gesty` (czysty wektor, bez komponentu leksykalnego) wypada najsłabiej —
spójne z tym, że krótkie, terminologicznie gęste fragmenty OWU faworyzują dopasowanie słów
kluczowych nad czystym podobieństwem semantycznym. Hybryda Qdrant (RRF dense+sparse) nie pobiła
tu ani samego `qdrant-rzadki`, ani `azure+semantyczna` — możliwe przyczyny (nieprzebadane):
przybliżenie IDF zamiast pełnego BM25 w gałęzi sparse, dobór mnożnika prefetch, mała próbka.

## Testy

`pytest -q -m "not azure"` w worktree: **363 passed, 5 skipped, 2 deselected, 1 warning in 32.49s**
(baseline na `main` przed zmianami: wszystko zielone — nic nie zepsute). Nowe testy offline, bez
sieci: Qdrant w trybie `:memory:` + atrapa embeddera o stałym wektorze
(`tests/test_wyszukiwarka_qdrant.py` — 16 testów, `tests/test_indeksuj_owu_qdrant.py` — 3 testy,
`tests/test_cache_embeddingow.py` — 4 testy).

## Otwarte / niezrobione

- `docker-compose.qdrant.yml` (serwer, port 6333/6334) — napisany, **nie uruchomiony i nie
  przetestowany** na tej maszynie (Docker Desktop wyłączony, celowo nie włączony). Oznaczone
  komentarzem na górze pliku.
- Wariant z lokalnymi polskimi embeddingami (pkt. 5 zadania) — pominięty, patrz Decyzje pkt. 9.
- Pomiar end-to-end latency bez efektu współdzielonego cache embeddingów — niezrobiony (patrz
  zastrzeżenie o czasie wyżej).
- Wrażliwość wyniku hybrydy na `MNOZNIK_PREFETCH` (obecnie `TOP_K * 4`, niedobrane pomiarowo) —
  nieprzebadana.
- `README.md` i `.env.example` dostały opis `WYSZUKIWARKA=qdrant`, ale żaden nowy routing
  produkcyjny (API/graf) nie przełącza się automatycznie na Qdrant — zmiana ograniczona do
  warstwy `rag/`, zgodnie z zakresem zadania (porównanie wyszukiwarek, nie zmiana domyślnego
  backendu w produkcji).
