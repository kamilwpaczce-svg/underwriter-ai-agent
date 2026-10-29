# SPEC Demo 7 — RAG po OWU na LlamaIndex obok obecnego, porównanie na tym samym zestawie

> **Dla wykonawcy:** worktree `projekty\underwriter_demo7`, gałąź `demo7` odbita od `main` @ `a2f8777`.
> **Commit po każdym zadaniu** (tylko wskazane pliki, `git add <plik>`; **zero `git add -A` / `.` / `commit -a`**,
> zero push). Wznowienie od ostatniego commita. TDD: najpierw test offline, potem kod.
> Termin: **30.10.2026**, pół dnia (obok Etapu 20). Dane fikcyjne. **Bez Azure, bez `az`, bez `terraform`.**
> **Nic nie instaluj do `underwriter_agent_demo\.venv`** — LlamaIndex tylko w osobnym `.venv-llamaindex`.

**Cel:** ten sam RAG po OWU (te same fragmenty, te same zapytania, to samo `k = 5`) zbudowany na
**LlamaIndex** (`TextNode`, `BM25Retriever`, opcjonalnie `VectorStoreIndex`) i porównany z obecną
wyszukiwarką na zamrożonym zestawie: recall@1/3/5, MRR@5, przedział Wilsona, test McNemara na parach
(A28, `ewaluacja/statystyka.py`). Wynik piszemy także wtedy, gdy LlamaIndex wypada gorzej. Cel: pokazać
LlamaIndex obok LangGraph/LangChain na tych samych danych.

## Źródła (stan repo 28.10, `main` @ `a2f8777`; Demo 1 na `demo1` @ `7192bb1`)

**Uczciwe nazwanie punktu odniesienia.** W repo **nie ma retrievera LangChain**. Wyszukiwanie po OWU to
własny kod (BM25 w pamięci, Azure AI Search, Qdrant) za Protocolem `Wyszukiwarka`; LangChain/LangGraph
odpowiada za graf i wywołania LLM (`agent/model_azure.py:2`, `with_structured_output` w `agent/model.py:114`).
Demo porównuje więc **retrieval LlamaIndex z obecnym retrievalem stosu LangGraph/LangChain**, nie „retriever
LangChain vs retriever LlamaIndex”. Tak to opisujemy w docs.

- Fragmentacja: `rag/fragmenty.py:33-60` — 1 ustęp = 1 fragment, `id = "p{§}u{ust}"`, treść zaczyna się od
  `§ N. Tytuł\nust. M.`; 66 fragmentów (`podziel_owu()`, policzone 28.10). Plik OWU: `owu/owu_mienie_msp_v1.md` (111 linii).
- Obecna wyszukiwarka (baseline): `rag/wyszukiwarka.py` — `TOP_K = 5` (:19), Protocol `Wyszukiwarka`
  (:26-29, `szukaj(zapytanie, k) -> list[Fragment]`), `tokenizuj` (:32-34: małe litery, polskie znaki → ASCII,
  słowa ≥3 znaków obcięte do 5 — „stemming” pod fleksję), `WyszukiwarkaLokalna` BM25 k1=1.5, b=0.75 (:37-74),
  **fragmenty z wynikiem 0 nie są zwracane** (:74).
- Zestaw Z (main): `ewaluacja/porownaj_wyszukiwarki.py:53-66` `zloty_zbior()` — zapytania z pól Z01–Z12
  przez produkcyjne `agent.wezly_szkody.zbuduj_zapytanie_owu` (`agent/wezly_szkody.py:36-39`), oczekiwane
  ustępy z `paragrafy_oczekiwane`; zostaje **9 zapytań**. Miary: `ocen_wyszukiwarke` (:77-108) — recall@1/3/5,
  MRR@5, p50/p95; **zwraca tylko agregaty, bez trafień per zapytanie** (McNemar ich potrzebuje).
- Wynik Etapu 12 na zestawie Z (`SPEC_ETAP12.md:79-86`): `lokalna` recall@5 = **9/9 (100%)**, recall@1 67%,
  MRR 0,806; Azure hybryda i Qdrant też 100% @5. **Sufit**: na Z przy k=5 nie da się wygrać, da się tylko przegrać.
- Zestaw C (Demo 1, gałąź `demo1`, **niescalony do main**): `underwriter_demo1/dane/czat/pytania.json` —
  12 pytań zamrożonych 28.10 (M01–M08, N01–N02 nawiązujące, P01–P02 poza OWU), 10 z oczekiwanymi ustępami
  (M04 akceptuje § 9 ust. 3 lub 4). Zapytanie dla nawiązujących = pytanie + poprzednie pytanie użytkownika
  (`underwriter_demo1/czat/instrukcje.py:47-51`). Recall: `underwriter_demo1/ewaluacja/czat.py:147-166`.
  Wynik offline BM25: **recall@5 = 9/10**, chybione **M06** („samochody osobowe” vs „pojazdy mechaniczne”,
  luka leksykalna) — `underwriter_demo1/SPEC_DEMO1_CZAT_OWU.md:297`; decyzja właściciela: M06 zostaje, nie stroić (:299).
- Statystyka A28: `ewaluacja/statystyka.py` (sam stdlib) — `przedzial_wilsona` (:26), `mcnemar_dokladny` (:37),
  `porownaj(a, b)` (:81, słowniki `id -> bool`, zwraca b, c, p, listy rozjazdów).
- Cache embeddingów (Etap 12): format `rag/cache_embeddingow.py:8-10` (`sha256("<model>:<tekst>") -> wektor`),
  plik **tylko w** `projekty\underwriter_agent_demo_qdrant\.cache_embeddingow\text-embedding-3-small.json`
  (75 wpisów = 66 fragmentów OWU + 9 zapytań Z; sprawdzone 28.10). Zapytań zestawu C w cache **nie ma** (0/12).
- Zależności i środowiska: `requirements.txt` pinuje `openai==3.28.0` (:37), `pydantic==2.14.0` (:12),
  `numpy==2.5.4` (:57); wzór osobnego venv: `requirements-ewaluacja.txt:1-12`, `.gitignore:31,44`
  (`.venv-ewaluacja/`, `.venv-mlops/`). `.venv` = Python 3.14.4. Testy na `main`: **967 collected** (28.10).
- Markery pytest: `pytest.ini` (`integracja`, `azure`) — brak markera dla LlamaIndex; izolujemy `importorskip`.

### Wersje LlamaIndex (PyPI JSON, 28.10.2026; nic nie instalowano)

| Pakiet | Wersja | Python | Uwagi |
|---|---|---|---|
| `llama-index-core` | 0.14.25 (21.09) | `>=3.10,<4` | wheel `py3-none-any`; brak klasyfikatora 3.14; zależy m.in. od `nltk`, `tiktoken`, `sqlalchemy[asyncio]`, `llama-index-workflows`, `pydantic>=2.8`; **nie** zależy od `openai` |
| `llama-index-retrievers-bm25` | 0.8.0 (31.08) | `>=3.10,<4` | `bm25s>=0.2.7.post1`, **`pystemmer>=2.2.0.1,<3`**; `import Stemmer` na poziomie modułu (`base.py`), domyślnie stemmer angielski i stopwords `"en"` |
| `bm25s` | 0.3.15 | `>=3.8` | czysty Python + numpy |
| `PyStemmer` | 2.2.0.3 / 3.1.0 | — | **2.x: tylko sdist** (kompilacja C na Windows = MSVC); **3.1.0 ma wheel `cp314-win_amd64`** |
| `llama-index-llms-azure-openai` / `-embeddings-azure-openai` | 0.6.1 / 0.6.1 | `>=3.10,<4` | przez `llama-index-llms-openai 0.8.x` wymagają **`openai<3`** — konflikt z `openai==3.28.0` |
| `greenlet` (dla `sqlalchemy[asyncio]`) | 3.5.6 | `>=3.10` | wheel `cp314-win_amd64` jest |

**Zgodność z Py 3.14: NIESPRAWDZONE** (wszystko poza PyStemmer to `py3-none-any`, więc instalacja powinna
przejść, ale nikt tego nie uruchomił; klasyfikatora 3.14 brak). Dwa twarde ustalenia: (1) pin `pystemmer<3`
w `llama-index-retrievers-bm25` wymusza sdist → obejście w Zadaniu 0; (2) integracje Azure OpenAI LlamaIndex
nie wejdą obok `openai==3.28.0` → **nie używamy ich** (decyzja D4).

## Decyzje

- **D1. Baza porównania = `main` + zestaw pytań z Demo 1 przeniesiony jako plik danych.** Gałąź `demo7` od `main`
  (tam są `rag/`, `porownaj_wyszukiwarki.py`, `statystyka.py`, zestaw Z). Z `demo1` bierzemy **tylko**
  `dane/czat/pytania.json` (`git checkout demo1 -- dane/czat/pytania.json`, plik identyczny bajtowo → scalenie
  obu gałęzi bez konfliktu). Kodu `czat/` nie przenosimy; regułę zapytania nawiązującego odtwarzamy w 2 liniach
  z testem równoważności (Zadanie 1). Uzasadnienie: zestaw Z ma sufit 9/9 @5, więc sam nie odróżni wariantów;
  zestaw C ma znany trudny przypadek (M06) i pytania w języku naturalnym, czyli to, co LlamaIndex obiecuje
  robić lepiej. Raport podaje **oba zestawy osobno i łącznie (n = 19)**.
- **D2. Ten sam korpus, ten sam `k`.** Węzły LlamaIndex budujemy z `podziel_owu()` (66 fragmentów, `id_ = fragment.id`),
  bez `SentenceSplitter` — inne cięcie zmieniałoby dwie rzeczy naraz. `k = TOP_K = 5` dla wszystkich wariantów.
  Trafienie = dowolny oczekiwany ustęp w top-k (definicja jak `porownaj_wyszukiwarki.py:91-95`).
- **D3. Warianty (offline domyślnie):**
  - `lokalna` — baseline, `WyszukiwarkaLokalna` bez zmian;
  - `li-bm25-domyslny` — `BM25Retriever.from_defaults(nodes=..., similarity_top_k=5)` „jak z tutoriala”
    (stemmer angielski, stopwords `en`) — mierzy koszt naiwnej adopcji frameworka na polskim tekście;
  - `li-bm25-bez-stemmera` — `skip_stemming=True` i bez angielskich stopwords (wartość `language`
    sprawdzić w źródle: `bm25s.tokenize(stopwords=...)`, `bm25s/tokenization.py:569-573`; dopuszczalne `None`/`[]`);
    polskiego stemmera PyStemmer nie ma — tego nie obchodzimy własnym kodem;
  - `li-wektor` — **tylko jeśli właściciel zgodzi się w DO DECYZJI 2**: `VectorStoreIndex` (in-memory) z własną
    klasą `BaseEmbedding` czytającą wektory z kopii cache Etapu 12, **bez sieci** (brak wpisu → wyjątek, nie
    wywołanie Azure). Tylko na zestawie Z (cache pokrywa 9/9 zapytań i 66/66 fragmentów).
- **D4. Bez LLM w porównaniu.** Porównujemy retrieval (deterministyczny, zero kosztu, powtarzalny — jedno
  uruchomienie wystarcza, powtórzenia z A28 nie mają sensu). Generację pokazujemy **offline**: `CitationQueryEngine`
  (albo `RetrieverQueryEngine`) z `MockLLM` z `llama_index.core` — dowód, że potok LlamaIndex działa end-to-end
  i zwraca `source_nodes` mapowalne na „§ N ust. M”. Biegu gpt-5-mini przez LlamaIndex **nie robimy** (konflikt
  `openai<3`, a „ten sam model” wymagałby tego samego promptu i kontroli cytatów co Demo 1 — poza pół dnia).
- **D5. Izolacja:** `requirements-llamaindex.txt` instalowany **na wierzch** `requirements.txt` w nowym
  `.venv-llamaindex` (wzór `requirements-ewaluacja.txt`). Bez integracji `-llms-*`/`-embeddings-*`, więc `openai`
  zostaje 3.28.0. Testy LlamaIndex: `pytest.importorskip("llama_index.core")` na górze pliku → w `.venv` są
  **pomijane** (liczba passed bez zmian). Kod LlamaIndex tylko w nowych modułach, importowany leniwie;
  żaden istniejący moduł go nie importuje.
- **D6. Adapter, nie przepisywanie.** `WyszukiwarkaLlamaIndex` implementuje istniejący Protocol `Wyszukiwarka`
  (zwraca `list[Fragment]` po `node.id_`), więc liczy go ta sama funkcja miar co baseline i może być w przyszłości
  wpięty w graf bez zmian w `agent/`. W tym demie **nie wpinamy** go w graf ani w API.
- **D7. Statystyka:** per zapytanie `id -> trafione@5`; `statystyka.porownaj(lokalna, wariant)` → b, c, p McNemara;
  Wilson dla recall@5 każdego wariantu. Z góry zapisane w raporcie: przy n = 19 nawet różnica 4:0 daje p = 0,125
  — wynik to **kierunek**, nie dowód (ta sama uwaga co A28).

## Pliki

| Plik | Co |
|---|---|
| `requirements-llamaindex.txt` (nowy) | piny z Zadania 0 + komentarz o kolejności instalacji i obejściu `pystemmer` |
| `.gitignore` | dopisać `.venv-llamaindex/` i `.cache_embeddingow_demo7/` (jeśli D3 `li-wektor`) |
| `dane/czat/pytania.json` (z `demo1`, bez zmian) | zestaw C |
| `rag/llamaindex_owu.py` (nowy) | `wezly_owu(fragmenty) -> list[TextNode]`, `WyszukiwarkaLlamaIndex`, `zbuduj_bm25(wariant)`, opcjonalnie `EmbeddingZCache` + `zbuduj_wektorowa(plik)`, `zbuduj_silnik_cytatow(retriever, llm)` |
| `ewaluacja/porownaj_llamaindex.py` (nowy) | zestawy Z i C, trafienia per zapytanie, agregaty, Wilson, McNemar, zapis `ewaluacja/wyniki/<ts>_llamaindex.{json,md}` (gitignored, `.gitignore:5`) |
| `tests/test_llamaindex_owu.py` (nowy) | testy z `importorskip` |
| `tests/test_porownaj_llamaindex_zestawy.py` (nowy) | testy bez LlamaIndex (zestaw C, reguła zapytania, miary) — biegną w `.venv` |
| `docs/ROZWOJ.md` | sekcja „Demo 7 — LlamaIndex” z tabelą i wnioskiem |
| `README.md` | 2–3 linie: jak uruchomić porównanie, link do sekcji |

Nie ruszamy: `agent/`, `api/`, `rag/wyszukiwarka.py`, `rag/fragmenty.py`, `ewaluacja/porownaj_wyszukiwarki.py`,
`requirements.txt`, `infra/`, `deploy/`.

## Zadania

### Zadanie 0: środowisko i weryfikacja wersji (~30 min, notatka pod zadaniem w tym pliku)

- [x] `python -m venv .venv-llamaindex` (Python 3.14 jak `.venv`), `pip install -r requirements.txt`.
- [x] `pip install --dry-run llama-index-core==0.14.25 bm25s==0.3.15 pystemmer==3.1.0` → zapisz, co dochodzi i czy
      coś z `requirements.txt` zmienia wersję (szczególnie `pydantic`, `sqlalchemy`, `numpy`, `tenacity`, `openai`).
      Zmiana wersji pakietu z `requirements.txt` = **stop i notatka** (nie godzimy się po cichu).
- [x] Instalacja: `llama-index-core`, `bm25s`, `pystemmer==3.1.0`, potem `pip install --no-deps llama-index-retrievers-bm25==0.8.0`
      (obejście pinu `pystemmer<3`). `pip check` pokaże ten jeden rozjazd — zapisać go dosłownie w notatce i
      w komentarzu `requirements-llamaindex.txt`. Jeśli kompilator nie jest potrzebny, a `pystemmer 2.2.0.3`
      jednak instaluje się z sdist bez błędu — wybierz zgodny pin i opisz.
- [x] Dymny test: `python -c "import llama_index.core, bm25s, Stemmer; from llama_index.retrievers.bm25 import BM25Retriever"`
      + zbudowanie retrievera na 3 węzłach i jedno `retrieve`. Pada na 3.14 → **stop**, notatka, raport do właściciela
      (plan B: `py -3.13` jeśli zainstalowany — sprawdź `py -0`; nie instaluj nowego Pythona bez zgody).
- [x] `.venv\Scripts\python -c "import llama_index"` → `ModuleNotFoundError` (dowód izolacji, wklej do notatki).
- [x] Zapisz piny do `requirements-llamaindex.txt`, dopisz `.gitignore`. Commit.

> **Notatka z wykonania Zadania 0 (28.10.2026, Python 3.14.4, Windows, `.venv-llamaindex`):**
> - `pip install -r requirements.txt` w nowym venv: przeszło bez błędu.
> - Dry-run `llama-index-core==0.14.25 bm25s==0.3.15 pystemmer==3.1.0`: **34 nowe pakiety, zero zmian/odinstalowań** pakietów z `requirements.txt`
>   (`pydantic 2.14.0`, `sqlalchemy 2.1.4`, `numpy 2.5.4`, `tenacity 9.1.4`, `openai 3.28.0` bez zmian; `greenlet 3.5.6` już był). Porównanie `pip freeze` przed/po instalacji:
>   140 -> 175 pozycji, żadna dotychczasowa nie zmieniła wersji. Dochodzą m.in. `llama-index-workflows 2.26.1`, `nltk 3.10.4`, `aiohttp 3.14.5`, `networkx 3.7`, `fsspec 2026.9.0`, `PyStemmer 3.1.0` (wheel).
> - Instalacja: wg planu (`--no-deps` dla `llama-index-retrievers-bm25==0.8.0`). Wariant `pystemmer 2.2.0.3` z sdist **nie był próbowany** (3.1.0 działa, wybrano go bez kompilatora).
> - `pip check` — jedyny rozjazd, dosłownie:
>   `llama-index-retrievers-bm25 0.8.0 has requirement pystemmer<3,>=2.2.0.1, but you have pystemmer 3.1.0.`
> - Dymny test na Py 3.14.4: import `llama_index.core, bm25s, Stemmer, BM25Retriever` OK; `BM25Retriever.from_defaults(nodes=3x TextNode, similarity_top_k=2)` + `retrieve` zwraca właściwy węzeł na 1. miejscu (`n2`, score 1.4745); `Stemmer.Stemmer("english").stemWord("running") == "run"` (API 3.x działa).
> - Izolacja: `.venv\Scripts\python -c "import llama_index"` -> `ModuleNotFoundError: No module named 'llama_index'`.
> - Piny: `requirements-llamaindex.txt` (z komentarzem o rozjeździe); `.gitignore` +`.venv-llamaindex/`.
> - Nie sprawdzano w kodzie, że domyślny stemmer/stopwords `BM25Retriever` są angielskie (to ustalenie ze spec, wiersz tabeli wersji) — do weryfikacji w Zadaniu 2 (warianty `domyslny` / `bez-stemmera`).

### Zadanie 1: zestawy i miary bez LlamaIndex (TDD, `.venv`, ~45 min)

- [x] `git checkout demo1 -- dane/czat/pytania.json` (bez zmian treści; test sprawdza `zamrozono == "2026-10-28"`).
- [x] `ewaluacja/porownaj_llamaindex.py`: `zestaw_z()` (opakowuje `zloty_zbior()`), `zestaw_c(sciezka)` — pomija
      pytania bez `oczekiwane` (P01, P02), zapytanie nawiązującego = `f"{pytanie} {poprzednie_pytanie}"`;
      każdy wiersz `{"id", "zestaw", "zapytanie", "oczekiwane": set[(§, ust)]}`.
- [x] Testy: zestaw C ma 10 wierszy; zapytanie N01 == `"A kogo muszę o tym zawiadomić? Czy kradzież z włamaniem jest objęta ubezpieczeniem?"`
      (równoważność z `underwriter_demo1/czat/instrukcje.py:47-51`); M04 ma 2 oczekiwane; każdy oczekiwany ustęp
      istnieje w `podziel_owu()`; zestaw Z ma 9 wierszy.
- [x] `trafienia(wyszukiwarka, zestaw, k=5) -> dict[id, {"ranga", "ids"}]` i `agreguj(...)` → recall@1/3/5, MRR@5.
      **Test spójności:** dla `WyszukiwarkaLokalna` na zestawie Z agregaty == `ocen_wyszukiwarke(...)` z
      `porownaj_wyszukiwarki.py` (te same liczby, poza czasem). Test na zestawie C: `lokalna` recall@5 == 9/10, chybione `["M06"]`
      (odtworzenie wyniku Demo 1; inna liczba = stop i notatka, nie poprawiać testu).
- [x] Pełne `pytest` w `.venv`: 967 + nowe, zero regresji. Commit.

> **Notatka z wykonania Zadania 1 (28.10.2026, `.venv`, Python 3.14.4):**
> - `dane/czat/pytania.json`: `git checkout demo1 -- ...`; blob git identyczny z `demo1` (`a17b1b9f769804837dd10342b97f137656a4311c`).
>   Hash SHA-256 pliku w katalogu roboczym różni się od `git show`, bo `core.autocrlf=true` (CRLF w working tree); po `tr -d '\r'` oba dają `d93b5542...`.
> - Nowe pliki: `ewaluacja/porownaj_llamaindex.py` (`zestaw_z`, `zestaw_c`, `trafienia`, `agreguj`; zero LlamaIndex),
>   `tests/test_porownaj_llamaindex_zestawy.py` (15 testów). TDD: test czerwony (`ModuleNotFoundError`), potem kod; testy z liczbami znanymi
>   z Etapu 12 i Demo 1 przeszły za pierwszym razem, bez poprawiania oczekiwań.
> - `lokalna` (baseline), top-5: **Z** n=9: recall@1 0,667 (6/9), @3 0,889 (8/9), @5 1,000 (9/9), MRR@5 0,806 (rangi: Z04=2, Z07=4, Z10=2, reszta 1).
>   **C** n=10: @1 0,600 (6/10), @3 0,800 (8/10), @5 0,900 (9/10), MRR@5 0,703; chybione tylko **M06**; M01 ranga 3, M02 ranga 5 (ledwo w top-5).
>   **Z+C** n=19: @1 12/19, @3 16/19, @5 18/19 (0,947), MRR@5 0,752. Wszystkie id unikalne między zestawami.
> - Agregaty `lokalna` na Z == `ocen_wyszukiwarke` (test spójności: recall@1/3/5, MRR@5, n).
> - **Odstępstwo 1:** regres z Zadania 0 — `tests/test_dane.py::test_brak_cyrylicy_w_plikach_tekstowych` padał (stan przed Zadaniem 1: 957 passed, **1 failed**),
>   bo skanował `.venv-llamaindex` (`bm25s/stopwords.py` ma słowa rosyjskie). Dodano `".venv-llamaindex"` do zbioru wykluczeń (jak `.venv-ewaluacja`, `.venv-mlops`),
>   osobny commit `6a41d5f` (łatwy do cofnięcia). `test_dane.py` nie jest na liście „Nie ruszamy”, ale też nie na liście „Pliki” — do potwierdzenia.
> - **Odstępstwo 2:** spec podaje „967 collected”; w tym worktree było 968 (957 passed + 1 failed + 7 skipped + 3 deselected) przed zmianami. Różnica 1 niewyjaśniona
>   (nie sprawdzano, czy to inny stan `main` niż w specyfikacji, czy błąd zliczenia). Po: 983 collected = 973 passed + 7 skipped + 3 deselected.
> - Ścieżka w specyfikacji `underwriter_demo1/czat/instrukcje.py:47-51` w gałęzi `demo1` to po prostu `czat/instrukcje.py` (funkcja `zapytanie_wyszukiwania`); reguła zgodna z testem N01.
> - Obsługa wyjątku z `szukaj` w `trafienia` jeszcze NIE istnieje (wyjątek się propaguje) — wymaga Zadanie 3 („wariant z wyjątkiem liczy się jako nietrafienie i jest wypisany”).

### Zadanie 2: LlamaIndex — węzły, adapter, warianty BM25 (TDD, `.venv-llamaindex`, ~1,5 h)

- [x] `tests/test_llamaindex_owu.py` zaczyna się od `pytest.importorskip("llama_index.core")` i `importorskip("llama_index.retrievers.bm25")`.
- [x] `wezly_owu(podziel_owu())`: 66 `TextNode`, `id_ == fragment.id`, `text == fragment.tresc`, metadata
      `paragraf`, `ustep`, `tytul` (wyłączone z tekstu do embeddingu/LLM: `excluded_embed_metadata_keys`,
      `excluded_llm_metadata_keys`). Test: liczba, unikalność id, zgodność treści.
- [x] `WyszukiwarkaLlamaIndex(retriever, nazwa)`: `szukaj(zapytanie, k)` ustawia `similarity_top_k = k`, woła
      `retrieve`, mapuje `node.id_ -> Fragment`; nieznane id → wyjątek (nie ciche pominięcie). Test na atrapie
      retrievera (bez BM25). **Węzły z wynikiem 0:** zapisać w notatce, czy `BM25Retriever` je zwraca (baseline nie,
      `rag/wyszukiwarka.py:74`); dla recall@k to bez znaczenia, ale trzeba to nazwać.
- [x] `zbuduj_bm25("domyslny" | "bez-stemmera")` wg D3. Test dymny: zapytanie „pożar budynku” zwraca ≤5 fragmentów,
      wszystkie z OWU. **Nie stroimy** parametrów pod wynik (jedna konfiguracja na wariant, ustalona przed pomiarem).
- [x] (zgoda właściciela 28.10, DO DECYZJI 2) `EmbeddingZCache(BaseEmbedding)`: `_get_query_embedding`/`_get_text_embedding`
      czytają kopię cache (`.cache_embeddingow_demo7/text-embedding-3-small.json`, skopiowaną z worktree qdrant),
      klucz jak `rag/cache_embeddingow.py:21-22`; brak wpisu → `KeyError` z tekstem. `VectorStoreIndex(nodes, embed_model=...)`.
      Test: 66/66 fragmentów i 9/9 zapytań Z w cache; Azure nie jest wołany (brak importu `openai` w ścieżce).
- [x] Commit.

> **Notatka z wykonania Zadania 2 (28.10.2026, `.venv-llamaindex`, Python 3.14.4, llama-index-core 0.14.25):**
> - Nowe: `rag/llamaindex_owu.py` (`wezly_owu`, `WyszukiwarkaLlamaIndex(retriever, nazwa, fragmenty=None)`, `zbuduj_bm25`, `EmbeddingZCache`, `zbuduj_wektorowa`),
>   `tests/test_llamaindex_owu.py` (21 testów; w `.venv` 1 skipped przez `importorskip`). `.gitignore` +`.cache_embeddingow_demo7/`. TDD: czerwony = `ModuleNotFoundError: rag.llamaindex_owu`.
> - **Sprawdzone w kodzie `BM25Retriever` 0.8.0:** domyślnie stemmer `english` i stopwords `"en"` (test: `stemWord("running") == "run"`, `"to"` brak w słowniku indeksu, bo jest na liście angielskiej).
>   **Asymetria biblioteki:** stopwords (`language`) działa tylko przy budowie indeksu; zapytanie przechodzi przez `bm25s.tokenize(...)` z domyślnym `stopwords="english"` także przy `language=None`.
>   Z OWU tylko token `to` jest na liście angielskiej. Nie obchodzimy tego własnym kodem. `bez-stemmera` = `skip_stemming=True, language=None` (`bm25s`: `stopwords=None` -> `[]`).
> - Indeks BM25 budowany z `get_content(MetadataMode.EMBED)`, więc metadane węzłów muszą być w `excluded_embed_metadata_keys` (są; test).
> - **Węzły z wynikiem 0:** `BM25Retriever` ZWRACA zawsze k węzłów, uzupełniając wynikami `0.0` (baseline `lokalna` ich nie zwraca). Np. „pożar budynku”: 1 węzeł z wynikiem 1,90, reszta 0,0.
>   **ROZSTRZYGNIĘTE (Właściciel 28.10):** adapter `WyszukiwarkaLlamaIndex.szukaj` pomija węzły z `score == 0` (jak baseline);
>   `score=None` zostaje. Testy `test_adapter_pomija_wezly_z_wynikiem_zero_jak_baseline`, `test_adapter_zostawia_wezly_bez_wyniku`.
>   (Poprawka z Zadania 3: poprzednie zdanie „Adapter ich NIE filtruje" było nieaktualne po `7e6fdc8` - filtruje.) Diagnostyka na zestawach Z+C (19 zapytań, oba warianty): **0 zapytań ma węzły o wyniku 0 w top-5**, więc przy tych zestawach nie wpływa to na recall; ale zero-węzły mogą dać przypadkowe trafienie na innym zestawie.
> - Test dymny „pożar budynku” (k=5): `lokalna` p9u3,p4u1,p2u5,p2u4,p8u1; `li-bm25-domyslny` i `li-bm25-bez-stemmera` oba p2u5,p14u3,p14u2,p14u1,p13u2 (tylko p2u5 ma wynik > 0). Obie warianty ≤5 fragmentów, wszystkie z OWU.
> - `li-wektor`: kopia cache (2,3 MB, 75 wpisów, wektory 1536) skopiowana z `underwriter_agent_demo_qdrant\.cache_embeddingow\` (zero wywołań API); pokrycie 66/66 fragmentów i 9/9 zapytań Z (test). Brak pliku -> `FileNotFoundError` (nie tworzymy), brak wpisu -> `KeyError`.
>   Test ścieżki wektorowej w osobnym procesie: po zbudowaniu indeksu i jednym `szukaj` w `sys.modules` nie ma `openai` ani `azure*`. Testy wektorowe skipują się, gdy brak kopii cache (jest gitignored).
> - Pełne `pytest` w `.venv`: 973 passed, 11 skipped (10 przed zadaniem + 1 nowy plik), zero regresji. `pip check` w `.venv-llamaindex`: tylko opisany rozjazd `pystemmer`.

### Zadanie 3: porównanie, potok z cytatami offline, dokumentacja (~1,5 h)

- [x] `porownaj_llamaindex.main()`: warianty z D3 dostępne w środowisku (brak `llama_index` → tylko `lokalna` +
      komunikat na stderr, kod wyjścia ≠ 0, żeby bieg w złym venv nie udawał sukcesu). Dla każdego wariantu i
      zestawu (Z, C, Z+C): n, recall@1/3/5, MRR@5, Wilson 95% dla recall@5, McNemar vs `lokalna` (b, c, p,
      id rozjazdów), top-5 id per zapytanie w JSON.
- [x] Testy na atrapach wyszukiwarek (`.venv`): tabela MD ma wszystkie warianty, McNemar liczony na id wspólnych,
      wariant z wyjątkiem w `szukaj` liczy się jako nietrafienie i jest wypisany (wzór `porownaj_wyszukiwarki.py:84-89`).
- [x] `zbuduj_silnik_cytatow(retriever, llm)` → `CitationQueryEngine` (lub `RetrieverQueryEngine`, jeśli Citation
      przetnie węzły — wtedy notatka) z `MockLLM`; test: `response.source_nodes` ⊆ węzły z retrievera, każdy
      mapuje się na „§ N ust. M”. To dowód potoku, nie ocena jakości odpowiedzi.
- [x] Jeden bieg w `.venv-llamaindex`; wyniki do `ewaluacja/wyniki/` (gitignored), tabela i wniosek do
      `docs/ROZWOJ.md` („Demo 7 — LlamaIndex”): co wygrało/przegrało, które id się rozjechały i dlaczego
      (np. angielski stemmer na polskiej fleksji), ograniczenie n, czego nie mierzyliśmy (generacja, czas end-to-end).
- [x] README: polecenie uruchomienia. Pełne `pytest` w `.venv` (zero regresji) i `pytest tests/test_llamaindex_owu.py`
      w `.venv-llamaindex`. Commit. Liczby w raporcie końcowym.

> **Notatka z wykonania Zadania 3 (28.10.2026):**
> - Nowe/zmienione: `ewaluacja/porownaj_llamaindex.py` (`trafienia` łapie wyjątek z `szukaj` = nietrafienie + klucz `blad`; `zbuduj_wyniki`, `tabela_md`,
>   `zaladuj_warianty_li`, `zapisz_wyniki`, `main`), `rag/llamaindex_owu.py` (`zbuduj_silnik_cytatow`, `zrodla_cytatow`; poprawiony nieaktualny docstring adaptera),
>   `tests/test_porownaj_llamaindex_wyniki.py` (11 testów, `.venv`), `tests/test_llamaindex_owu.py` (+6 testów: silnik cytatów z `MockLLM` przy zablokowanej sieci, `main` w LlamaIndex).
> - Bieg: `.venv-llamaindex\Scripts\python -m ewaluacja.porownaj_llamaindex` -> `ewaluacja/wyniki/20261028-1933_llamaindex.{json,md}` (gitignored). Wynik: `lokalna` odtwarza
>   Z 9/9 i C 9/10 (chybione M06); oba warianty BM25 LlamaIndex Z 6/9, C 8/10, Z+C 14/19 (McNemar 4:0, p = 0,125); `li-wektor` Z 8/9 (1:0, p = 1,0). Wszystko nieistotne statystycznie.
>   Tabela i wniosek: `docs/ROZWOJ.md`, „Demo 7 - LlamaIndex".
> - `CitationQueryEngine`: nie ciął fragmentów OWU (1 fragment = 1 chunk przy 512 tokenach), więc nie było potrzeby `RetrieverQueryEngine`. Chunki dostają NOWE id (kod LlamaIndex
>   usuwa `id_`), mapowanie na „§ N ust. M” idzie po metadanych. Konstruktor `CitationQueryEngine(retriever=..., llm=...)`, nie `from_args` (to wymaga indeksu).
> - `main()`: brak LlamaIndex -> kod 2 + komunikat; brak pliku cache -> pomija tylko `li-wektor` (komunikat na stderr, kod 0).
> - Pełne `pytest` w `.venv`: 984 passed, 11 skipped (było 973/11). `.venv-llamaindex`: `test_llamaindex_owu.py` 29 passed; `pip check` tylko rozjazd `pystemmer`.

## Kryteria akceptacji

- `.venv` nietknięty: `import llama_index` → `ModuleNotFoundError`; pełny `pytest` w `.venv` = 967 dotychczasowych
  + nowe testy bez LlamaIndex zielone, testy LlamaIndex `skipped`.
- W `.venv-llamaindex` testy `tests/test_llamaindex_owu.py` zielone; `pip check` pokazuje co najwyżej opisany rozjazd `pystemmer`.
- `lokalna` odtwarza znane liczby: Z 9/9 @5 (`SPEC_ETAP12.md:81`), C 9/10 @5 z chybionym M06 (`SPEC_DEMO1_CZAT_OWU.md:297`).
- Tabela w `docs/ROZWOJ.md`: ≥2 warianty LlamaIndex vs `lokalna` na Z, C i Z+C, z Wilsonem i McNemarem, ten sam k = 5,
  ten sam korpus 66 fragmentów; wniosek napisany także przy wyniku gorszym od baseline.
- Zero wywołań sieciowych w biegu porównania (bez `az login`, bez kluczy).

## Ryzyka

| Ryzyko | Skutek | Co robić |
|---|---|---|
| `llama-index-core` nie działa na Py 3.14 (NIESPRAWDZONE) | brak dema | Zadanie 0 wykrywa w 15 min; plan B `py -3.13`, jeśli jest; inaczej stop i raport |
| `pystemmer<3` w retrievers-bm25 → sdist bez MSVC | brak `BM25Retriever` | `--no-deps` + `pystemmer 3.1.0` (wheel cp314); rozjazd opisany; API `Stemmer.Stemmer` w 3.x — sprawdzić dymnym testem |
| `llama-index-core` podnosi/obniża pakiet z `requirements.txt` | ciche rozjechanie `.venv-llamaindex` | `--dry-run` przed instalacją, stop przy zmianie |
| Sufit na zestawie Z (9/9) | „remis” bez informacji | dlatego zestaw C i raport osobno per zestaw |
| Kusi strojenie (polskie stopwords, własny tokenizer w LlamaIndex) po zobaczeniu wyniku | wynik niewiarygodny | jedna konfiguracja na wariant ustalona w D3 przed pomiarem; dodatkowe warianty tylko jako osobne, nazwane „po pomiarze” |
| Cache embeddingów z 17.10 nie pasuje do bieżącego OWU | `KeyError` | to zamierzone; test pokrycia w Zadaniu 2; bez cichego dociągania z Azure |
| Etap 20 (APIM) tego samego dnia zjada czas | demo niedokończone | Zadania 0–2 dają już wynik; Zadanie 3 można skrócić do tabeli bez potoku cytatów |

## Czego nie robić

- Nie instalować niczego do `.venv`; nie dopisywać LlamaIndex do `requirements.txt`, `Dockerfile`, obrazu API.
- Nie instalować `llama-index-llms-*` / `llama-index-embeddings-*` (wymagają `openai<3`).
- Nie wołać Azure (`az`, `terraform`, Azure OpenAI) — także nie „tylko 10 embeddingów” bez zgody właściciela.
- Nie wpinać LlamaIndex w graf, API ani Demo 1; nie zmieniać `rag/wyszukiwarka.py` ani `rag/fragmenty.py`.
- Nie zmieniać `dane/czat/pytania.json` ani oczekiwanych ustępów; nie usuwać M06.
- Nie stroić parametrów BM25/LlamaIndex pod wynik; nie raportować „LlamaIndex lepszy/gorszy” bez p z McNemara.
- Nie pisać „LangChain retriever” — w repo go nie ma (patrz Źródła).
- `git add -A` / `.` / `commit -a`, push — zakazane.

## DO DECYZJI (Właściciel, przed 30.10)

1. **Zestaw C z Demo 1 w demie 7?** Kopia `dane/czat/pytania.json` z gałęzi `demo1` (bez kodu czatu).
   **Rekomendacja: TAK.** Sam zestaw Z ma sufit 9/9 przy k = 5, więc nic nie odróżni; plik jest zamrożony
   i identyczny, scalenie `demo1` później nie da konfliktu.
2. **Wariant wektorowy `li-wektor` z cache embeddingów Etapu 12?** Zero kosztu i zero sieci, ale tylko zestaw Z
   (9 zapytań; dla C brakuje 10 wektorów zapytań — dociągnięcie to ok. 200 tokenów, poniżej 0,01 USD, ale wymaga
   `az login` i Azure OpenAI w dniu APIM). **Rekomendacja: TAK, tylko na Z i tylko z cache, bez Azure.** Pokazuje
   `VectorStoreIndex` i własny `BaseEmbedding`, czyli typowy wariant użycia LlamaIndex; wynik na C podany jako „nie mierzone”.
3. **Generacja odpowiedzi gpt-5-mini przez LlamaIndex (ten sam model co Demo 1)?** Wymaga osobnego venv z `openai<3`,
   tego samego promptu i kontroli cytatów co Demo 1 oraz kilku centów Azure. **Rekomendacja: NIE w demie 7** —
   tylko potok z `MockLLM` offline; bieg na żywo ewentualnie po scaleniu Demo 1 (01.11), jeśli zostanie bufor.

## ROZSTRZYGNIĘTE (Właściciel, 28.10)

1. Zestaw C z Demo 1: **TAK** (kopia `dane/czat/pytania.json` z gałęzi `demo1`).
2. Wariant `li-wektor`: **TAK — tylko zestaw Z, tylko z cache Etapu 12, bez Azure**; wynik na C = „nie mierzone”.
3. Generacja gpt-5-mini przez LlamaIndex: **NIE w demie 7** — tylko potok z `MockLLM` offline.
4. (po zad. 3) Wariant z polskim stemmerem dla sprawdzenia hipotezy o fleksji: **NIE teraz — backlog**
   (byłoby strojenie pod wynik; demo pokazuje już, co miało).
5. (po zad. 3) Brak pliku cache przy `li-wektor`: **błąd, nie cicha pomijka** — `main` liczy i zapisuje resztę,
   ale kończy kodem 3 (test `test_main_bez_pliku_cache_pomija_li_wektor_i_konczy_kodem_3`).

Uwaga do opisu: w repo nie ma retrievera LangChain — porównanie to LlamaIndex vs własne wyszukiwanie
(BM25 `rag/wyszukiwarka.py`), nie „vs LangChain”. Tak samo w całej dokumentacji.
