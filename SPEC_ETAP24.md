# SPEC Etap 24 — wariant wieloagentowy: supervisor LangGraph + agenci wyspecjalizowani

> **Dla wykonawcy:** gałąź `etap24` odbita od `main` **po scaleniu `etap19` i `etap23`** (worktree, jeśli
> w repo pracuje druga sesja; **zero `git commit -a`**). **Commit po każdym zadaniu** — wznowienie od
> ostatniego commita. TDD: najpierw test offline, potem kod. Jedno wywołanie agenta = 1–2 zadania.
> Termin: **29.10.2026** (1 dzień). Dane fikcyjne. Bez nowych zasobów Azure, bez `terraform`, bez wdrożenia.

**Cel:** drugi, równoległy wariant orkiestracji tego samego agenta: **supervisor** (węzeł LLM w LangGraph)
przekazuje sterowanie trzem wyspecjalizowanym agentom — **agentowi underwritingu**, **agentowi szkód** i
**agentowi OWU (RAG)** — i porównanie go z obecnym grafem na W01–W14 i Z01–Z12: trafność (Wilson,
McNemar z Etapu 19a), tokeny, koszt, opóźnienie, zgodność trasy. **Stary graf zostaje i jest domyślny**;
wariant wybiera przełącznik w konfiguracji. Wniosek piszemy także wtedy, gdy wariant wieloagentowy
wypada gorzej. Cel: pokazać system wieloagentowy.

## Źródła (stan repo 27.10, `main` @ `0952d54`)

- Obecny graf `agent/graf.py::zbuduj_graf(model, checkpointer, sciezka_wytycznych, wyszukiwarka, sciezka_polis, model_ryzyka)`:
  ```
  wczytaj → klasyfikuj ─WNIOSEK→ ekstrahuj → waliduj → ocen → kontrola → zatwierdzenie
                       ─INNY───→ zakoncz_inny
                       ─SZKODA─→ ekstrahuj_szkode → [analizuj_zdjecie, Etap 23] → sprawdz_polise
                                 → ocen_ryzyko_szkody ─S01/S02→ zatwierdzenie
                                                      ─inaczej→ szukaj_owu → ocen_pokrycie → kontrola_cytatow → zatwierdzenie
  ```
  Każdy węzeł owinięty `sledz_wezel` (span `wezel.<nazwa>`), błąd → router kieruje do `zatwierdzenie`.
- Stan `agent/wezly.py:27` (`StanGrafu`, TypedDict, `total=False`); `LIMIT_WYWOLAN_LLM = 6`, `_wywolaj_model` (2 próby).
- Węzły i routery: `agent/wezly.py` (wniosek), `agent/wezly_szkody.py` (szkoda). Deterministyczne
  zabezpieczenia: `wezel_kontrola` (silnik reguł), `sprawdz_polise` (S01–S04), `kontrola_cytatow`,
  `ustal_decyzje_szkody` (`agent/decyzje_szkody.py`). Punkt nadzoru człowieka: `wezel_zatwierdzenie` (`interrupt`).
- Model: Protocol `ModelAgenta` (`agent/model.py`), structured output przez `_wywolaj_structured_llm` —
  **projekt świadomie nie używa natywnego function calling** (SPEC_ETAP10: „działa tak samo u każdego
  dostawcy i w atrapie”). Atrapa: `ewaluacja/atrapa.py`. Owijka spanów: `obserwowalnosc/model_sledzony.py`.
- API: `api/agent_serwis.py::SerwisAgenta._zbuduj_graf` woła `zbuduj_graf(...)`; konfiguracja `api/ustawienia.py`.
- Ewaluacja: `ewaluacja/uruchom.py` (`--modul wnioski|szkody`, `--dostawca`, `--reasoning`, `--mlflow`),
  pole trafności wniosków `decyzja_llm_ok` (`ewaluacja/porownanie.py:124`), szkód `decyzja_ok` (`ewaluacja/szkody.py`).
- Statystyka 19a: `ewaluacja/statystyka.py` (CLI `stabilnosc` / `porownaj`, Wilson, dokładny McNemar,
  wynik większościowy na przypadek) — **dziś tylko na gałęzi `etap19`** (worktree `underwriter_etap19`,
  commit `1bd537d`), scalenie do `main` zaplanowane na 28.10 wieczór. Wyniki bazowe 26.10:
  `gpt-5-mini` `low` — wnioski 14/14 (wynik większościowy; W07 niestabilny 4/5), szkody 12/12; bieg 14
  wniosków ≈ 3–4 min.
- Pakiety: `langgraph==1.2.14` (`Command`, `Send` dostępne), `langgraph-supervisor` **nie jest zainstalowany**.

## Decyzje

1. **LangGraph, supervisor napisany ręcznie (węzeł + `Command(goto=…)`), nie `langgraph-supervisor` /
   `create_react_agent`.** Powody: (a) prebudowany supervisor przekazuje sterowanie przez natywne tool calling
   i stan oparty na liście `messages` — kłóci się z typowanym `StanGrafu`, structured output i atrapą;
   (b) zostają checkpointer Postgres, `interrupt` w `zatwierdzenie`, spany per węzeł i deterministyczne
   kontrole — porównanie mierzy **tylko orkiestrację**, przy tym samym modelu, promptach, danych i kontrolach;
   (c) brak nowej zależności w obrazie API. **CrewAI i PydanticAI — poza zakresem** (wzmianka w README):
   CrewAI ma własny model ról/zadań i pamięci, trudno w nim zachować `interrupt` z checkpointerem Postgres
   i deterministyczne bramki jako osobne kroki; PydanticAI daje dobre typowane wyjścia, ale orkiestracja
   (`pydantic-graph`) oznaczałaby przepisanie grafu, czyli porównanie dwóch implementacji naraz zamiast
   dwóch orkiestracji. Ewentualne demo w CrewAI/PydanticAI dopiero po 9.11.
2. **Agenci = podgrafy** (`StateGraph(StanGrafu)` skompilowany bez checkpointera, dodany do rodzica jako węzeł —
   dziedziczy checkpointer rodzica), złożone z **istniejących funkcji węzłów** (bez kopiowania logiki):
   - `agent_underwritingu`: `ekstrahuj → waliduj → ocen → kontrola` (błąd → koniec podgrafu),
   - `agent_szkod`: `ekstrahuj_szkode → [analizuj_zdjecie] → sprawdz_polise → ocen_ryzyko_szkody`,
   - `agent_owu`: `szukaj_owu → ocen_pokrycie → kontrola_cytatow`.
   Te same prompty co dziś — specjalizacja = zakres narzędzi i danych, nie nowe prompty (inaczej porównanie
   miesza dwie zmienne). Wspólny `StanGrafu`; agent zwraca tylko swoje pola + `log`.
3. **Supervisor** (`agent/supervisor.py`, węzeł `supervisor`) dostaje sterowanie na starcie i po każdym agencie.
   **LLM jest wołany tylko tam, gdzie jest wybór**:
   - krok 1 (po `wczytaj`): LLM widzi dokument (jak `klasyfikuj`) i zwraca `DecyzjaSupervisora`
     — **zastępuje węzeł `klasyfikuj`** (ustawia `typ_dokumentu`);
   - po `agent_szkod`: LLM widzi zwięzłe podsumowanie stanu (kody polisy, braki, status ryzyka, rodzaj mienia —
     bez treści dokumentu) i wybiera `agent_owu` albo `zakoncz`;
   - po `agent_underwritingu` i `agent_owu`: przejście deterministyczne do `zatwierdzenie` (bez LLM),
     zapisane w `log` jako `supervisor_deterministyczny`.
   Uczciwy opis do README: w tym procesie supervisor przejmuje klasyfikację i jedno rozwidlenie; reszta
   przepływu jest liniowa. Wieloagentowość tu to podział odpowiedzialności, nie autonomia.
4. **Schemat** (`agent/schematy.py`):
   ```python
   AgentDocelowy = Literal["agent_underwritingu", "agent_szkod", "agent_owu", "zakoncz"]
   class DecyzjaSupervisora(_OczyszczonyTekstModelu):
       typ_dokumentu: TypDokumentu | None   # wymagany w kroku 1, w kolejnych ignorowany
       nastepny: AgentDocelowy
       uzasadnienie: str                    # max ~300 zn., do logu i panelu, nie do spanu
   ```
   Protocol: `ModelAgenta.decyduj_supervisor(czesci: CzesciDokumentu | None, podsumowanie: dict)
   -> tuple[DecyzjaSupervisora, MetadaneWywolania]`. Implementacje: `ModelAzure` (krok 1: tekst + OCR jak
   `klasyfikuj`; krok 2: tylko JSON podsumowania), `ModelGemini` (wspólna funkcja `_wywolaj_supervisor`),
   `ModelVLLM` (ta sama wspólna funkcja, jeśli nie wymaga zmian; inaczej `NotImplementedError` → `SKIEROWANIE`),
   `ModelSledzony`, `ModelAtrapa` (krok 1: `typ_dokumentu` z oczekiwanych; krok 2: `agent_owu`, gdy przypadek
   ma `decyzja_llm` ≠ `None`, inaczej `zakoncz`). Prompt: `agent/instrukcje_supervisor.py`.
5. **Bramki deterministyczne na wybór supervisora** (`dozwolone_ruchy(stan) -> set[AgentDocelowy]`):
   - krok 1: `typ_dokumentu` wygrywa nad `nastepny` (WNIOSEK→`agent_underwritingu`, SZKODA→`agent_szkod`,
     INNY→`zakoncz_inny`); niespójność → korekta;
   - `agent_owu` tylko dla SZKODY po `agent_szkod`; ten sam agent drugi raz → zabronione;
   - ruch zabroniony → wybór z deterministycznego routera obecnego grafu, `korekty_supervisora += 1`,
     wpis `supervisor_korekta` w `log` i atrybut spanu;
   - wybór **dozwolony, ale inny niż w obecnym grafie** (np. `zakoncz` dla zwykłej szkody → brak oceny pokrycia
     → `SKIEROWANIE`, albo `agent_owu` przy S01) **nie jest korygowany** — właśnie to mierzymy (`trasa_zgodna`).
     Decyzja końcowa nadal przechodzi przez `ustal_decyzje_szkody` / silnik reguł, więc błąd supervisora
     kończy się `SKIEROWANIE` do człowieka, nie cichą akceptacją.
6. **Limity:** osobny licznik `wywolania_supervisora` (max `MAKS_KROKOW_SUPERVISORA = 3`, każde wywołanie
   z 1 ponowieniem) — **nie** zużywa `LIMIT_WYWOLAN_LLM` agentów (ścieżka szkody zużywa dziś do 4 z 6;
   wspólny licznik zmieniałby decyzje przez sam limit, a nie przez orkiestrację). Przekroczenie albo błąd
   LLM supervisora 2× → `blad` w stanie → `zatwierdzenie` z `SKIEROWANIE` (ten sam wzorzec co dziś).
7. **Przełącznik:** `GRAF_WARIANT=jeden|wieloagentowy` (domyślnie `jeden`); `agent/graf.py::wybierz_graf(wariant, **kw)`
   zwraca `zbuduj_graf` albo `zbuduj_graf_wieloagentowy` (ta sama sygnatura). `api/ustawienia.py` czyta
   zmienną, `SerwisAgenta._zbuduj_graf` używa `wybierz_graf`. Nieznana wartość → błąd przy starcie (nie cichy fallback).
   Env Container App bez zmian (domyślnie `jeden`) — wdrożenie nie jest częścią etapu.
8. **Telemetria:** span `wezel.supervisor` z atrybutami `uw.supervisor.krok`, `uw.supervisor.wybor`,
   `uw.supervisor.korekta` (bool), `uw.supervisor.llm` (bool); span `agent.<nazwa>` wokół podgrafu.
   Bez `uzasadnienie` i treści dokumentu w atrybutach. Rozszerzyć istniejący test RODO atrybutów.
9. **Panel:** podsumowania (wniosek i szkoda) dostają klucz `orkiestracja`:
   `{"wariant": "wieloagentowy", "trasa_agentow": [...], "korekty": n, "uzasadnienia": [...]}`; w wariancie
   `jeden` klucza brak (stare testy panelu bez zmian). Frontend — **poza zakresem** (JSON widoczny w API).
10. **Ewaluacja i statystyka:**
    - `uruchom.py --wariant jeden|wieloagentowy` (domyślnie `jeden`), w wynikach `metadane.wariant` i na przypadek:
      `trasa` (lista węzłów z `log`, bez sufiksów prób), `trasa_zgodna` (trasa agentów zgodna z trasą obecnego
      grafu dla tego przypadku — wzorce tras zapisane w `ewaluacja/trasy_oczekiwane.py` z biegu atrapy wariantu
      `jeden`), `wywolania_supervisora`, `korekty_supervisora`, `_czas_ms`, tokeny we/wy.
    - **Min. 5 biegów na wariant i moduł**, biegi **przeplatane** (J, W, J, W, …), ten sam dzień, ta sama
      konfiguracja (`--dostawca azure --reasoning low`) — świeży baseline zamiast porównania z biegami z 26.10
      (inny dzień = inne obciążenie i możliwe zmiany wdrożenia). Razem 20 biegów (2 warianty × 2 moduły × 5).
    - `python -m ewaluacja.statystyka stabilnosc` per wariant (`--pole decyzja_llm_ok` dla wniosków,
      `--pole decyzja_ok` dla szkód) i `porownaj` (McNemar na wyniku większościowym) jeden vs wieloagentowy.
    - **Efekt sufitu nazwany wprost:** baseline ma 14/14 i 12/12 — trafność może tu wykazać tylko pogorszenie;
      brak istotnej różnicy (n = 14 / 12) nie dowodzi równoważności. Główne porównanie to koszt, opóźnienie,
      zgodność trasy i stabilność.
    - Tablica w `docs/ROZWOJ.md`: wariant × moduł → trafność (większościowa + Wilson), rozrzut min–max z 5 biegów,
      tokeny we/wy na dokument, koszt USD na dokument (cennik z `uruchom.py`), opóźnienie p50/p95 na dokument,
      wywołania LLM na dokument, `trasa_zgodna`, korekty supervisora, p McNemara. Pod tablicą **jeden akapit
      wniosku**, pisany także gdy wieloagentowy jest gorszy (spodziewane: drożej i wolniej o krok supervisora,
      trafność bez zmian albo gorsza).
    - MLflow: tag `wariant`, ten sam eksperyment.

## Pliki

| plik | rola |
|---|---|
| `agent/schematy.py` | `AgentDocelowy`, `DecyzjaSupervisora` |
| `agent/instrukcje_supervisor.py` | prompt supervisora + `podsumowanie_dla_supervisora(stan) -> dict` |
| `agent/model.py`, `agent/model_azure.py`, `agent/model_vllm.py` | metoda `decyduj_supervisor` |
| `obserwowalnosc/model_sledzony.py`, `ewaluacja/atrapa.py` | owijka, atrapa |
| `agent/agenci.py` | `zbuduj_agenta_underwritingu/_szkod/_owu(...)` — podgrafy z istniejących węzłów |
| `agent/supervisor.py` | węzeł `supervisor`, `dozwolone_ruchy`, `router_deterministyczny`, liczniki |
| `agent/graf_wieloagentowy.py` | `zbuduj_graf_wieloagentowy(...)` (sygnatura jak `zbuduj_graf`) |
| `agent/graf.py` | `wybierz_graf(wariant, **kw)` |
| `agent/wezly.py`, `agent/decyzje_szkody.py` | pola stanu `wywolania_supervisora`, `korekty_supervisora`, `trasa_agentow`; klucz `orkiestracja` |
| `api/ustawienia.py`, `api/agent_serwis.py` | `GRAF_WARIANT` |
| `ewaluacja/uruchom.py`, `ewaluacja/trasy_oczekiwane.py` | `--wariant`, trasa, `trasa_zgodna` |
| `tests/test_supervisor.py`, `tests/test_graf_wieloagentowy.py`, `tests/test_agenci.py`, `tests/test_ewaluacja_wariant.py` | testy offline |
| `README.md`, `docs/ROZWOJ.md` | architektura, decyzja o frameworku, tablica, wniosek |

## Zadania

### Zadanie 0: rozpoznanie (bez kodu produkcyjnego, notatka w tym pliku pod zadaniem)
- [ ] Czy `ewaluacja/statystyka.py` i `tests/test_statystyka.py` są na `main`. **Nie ma → STOP**, raport do
      sesji głównej (nie kopiować pliku z `etap19` ani nie scalać samemu).
- [ ] Czy `etap23` jest scalony (węzeł `analizuj_zdjecie`); nie jest → agent szkód bez tego węzła, adnotacja.
- [ ] Spike w scratchpadzie (nie w repo): podgraf jako węzeł + `Command(goto=…)` z rodzica + `interrupt` w rodzicu
      + `MemorySaver` — wznowienie `Command(resume=…)` działa i nie powtarza podgrafów. Zapisać wzorzec.
- [ ] Policzyć z wyników 26.10 (`underwriter_etap19/ewaluacja/wyniki/` albo `main` po scaleniu) tokeny i czas
      na dokument dla `low` — punkt odniesienia do sprawdzenia, czy świeży baseline nie odbiega.

#### Notatka z rozpoznania (27.10.2026, ok. 19:35, gałąź `etap24` odbita od `main` @ `68905db`)

**Wynik bramki: STOP.** Etap nie rusza z zadaniem 1, dopóki sesja główna nie scali `etap19`.

1. **`statystyka.py` na `main`: NIE MA.** `ls ewaluacja/statystyka.py tests/test_statystyka.py` w worktree
   `etap24` (= `main` @ `68905db`) zwraca „No such file or directory”. `git merge-base --is-ancestor etap19 main`
   jest fałszywe (gałąź `etap19` @ `0470983`, niescalona). Zgodnie ze SPEC: STOP, raport do sesji głównej,
   pliku nie kopiowano. Zadanie 0 dokończone mimo to (wyłącznie odczyt i spike w scratchpadzie), żeby po
   scaleniu zadanie 1 mogło ruszyć od razu.
   Uwaga: SPEC zakłada odbicie `etap24` **po** scaleniu `etap19` i `etap23`, więc po scaleniu trzeba odbić
   gałąź na nowo albo zrobić `git rebase main` (na `etap24` jest tylko ten commit z notatką).
2. **`etap23` (`analizuj_zdjecie`): NIESCALONY.** `merge-base --is-ancestor etap23 main` jest fałszywe (gałąź `etap23` @ `acb5e43`),
   `grep analizuj_zdjecie agent/*.py` na `main` nic nie zwraca, `agent/graf.py:73-94` nie ma tego węzła.
   Jeśli zostanie tak do startu zadania 2, `agent_szkod` = `ekstrahuj_szkode → sprawdz_polise → ocen_ryzyko_szkody`
   (adnotacja w README i `docs/ROZWOJ.md`). Scalenie `etap23` przed startem: węzeł wchodzi do podgrafu bez zmian w SPEC.
3. **Spike (podgraf + `Command(goto)` + `interrupt` w rodzicu + `MemorySaver`): DZIAŁA**, `langgraph==1.2.14`
   (`requirements.txt:9`, w `.venv` ta sama wersja). Skrypt: scratchpad sesji, `spike24/spike.py` (poza repo),
   bieg 27.10 19:33, exit 0. Wynik:
   - ścieżka zdrowa: `supervisor` 3×, każdy węzeł obu podgrafów 1×, `zatwierdzenie` 1×, potem `interrupt`
     (`get_state().next == ('zatwierdzenie',)`). Po `invoke(Command(resume=...))` przyrost liczników:
     **tylko `zatwierdzenie` +1** — podgrafy i supervisor nie są wołane ponownie; `next == ()`.
   - błąd w środku podgrafu (`blad` w 2. węźle `agent_szkod`): router podgrafu → `END`, 3. węzeł nie rusza,
     supervisor widzi `blad` i kieruje do `zatwierdzenie`; resume jak wyżej.
   - `log` (lista bez reduktora, `agent/wezly.py:40`) przechodzi przez podgraf poprawnie: podgraf zwraca
     pełny stan, rodzic nadpisuje kanały (wszystkie kanały `StanGrafu` to LastValue, `agent/wezly.py:27-50`).

   Wzorzec do zadań 2–3:
   ```python
   # podgraf: StateGraph(StanGrafu), routery z błędem -> END zamiast "zatwierdzenie", compile() BEZ checkpointera
   b.add_conditional_edges("ekstrahuj", lambda s: END if s.get("blad") else "waliduj", {"waliduj": "waliduj", END: END})
   agent = b.compile()
   # rodzic
   rodzic.add_node("supervisor", sledz_wezel("supervisor", fn_supervisora),
                   destinations=("agent_underwritingu", "agent_szkod", "agent_owu", "zatwierdzenie", "zakoncz_inny"))
   rodzic.add_node("agent_szkod", agent)            # podgraf jako węzeł, dziedziczy checkpointer rodzica
   rodzic.add_edge("agent_szkod", "supervisor")     # powrót do supervisora krawędzią statyczną
   # fn_supervisora zwraca Command(goto=cel, update={...}); interrupt tylko w "zatwierdzenie" rodzica
   return rodzic.compile(checkpointer=checkpointer)
   ```
   - `sledz_wezel` (`obserwowalnosc/wezly.py:13-29`) zwraca wynik `fn` bez zmian, więc działa też, gdy węzeł zwraca `Command`.
     Owijka gubi jednak adnotację `-> Command[Literal[...]]`, więc graf do rysowania wymaga `destinations=`
     (parametr jest w `StateGraph.add_node` w 1.2.14, sprawdzone `inspect.signature`). Bez niego wykonanie
     działa, tylko diagram nie pokaże krawędzi z supervisora (w spike'u bez owijki użyto adnotacji).
   - Na resume `zatwierdzenie` wykonuje się od początku (standardowa semantyka `interrupt`), tak samo jak dziś.
     `agent/wezly.py:191-213` nie ma efektów ubocznych przed `interrupt`, więc to bezpieczne.
   - Na Postgres: NIESPRAWDZONE (zgodnie z ryzykiem w SPEC: tylko test `integracja`, jeśli starczy czasu).
   - Span `agent.<nazwa>` (decyzja 8): podgraf to `CompiledStateGraph`, nie funkcja. Żeby go owinąć spanem,
     trzeba dodać wrapper `lambda s: agent.invoke(s)`, a to zmienia zachowanie checkpointu (podgraf wołany
     z funkcji, a nie jako węzeł). NIESPRAWDZONE, patrz DO DECYZJI 3.
4. **Punkt odniesienia z 26.10** (`underwriter_etap19/ewaluacja/wyniki/`, 5 biegów na moduł, policzone
   skryptem `spike24/baseline.py` z `metadane` i `_czas_ms` przypadków):

   | moduł | tokeny we/dok | tokeny wy/dok | USD/dok | czas/dok (bieg÷n) | p50 / p95 przypadku | LLM/dok |
   |---|---|---|---|---|---|---|
   | wnioski (`gpt-5-mini_myslenie-low`, 14) | 4737 [4736–4738] | 1443 [1421–1478] | 0,00407 | 14,0 s [13,4–14,4] | 14,5 / 18,2 s (n=70) | 2,86 |
   | szkody (`gpt-5-mini`, 12) | 3826 [3826] | 1066 [1011–1125] | 0,00309 | 12,9 s [12,1–14,0] | 13,4 / 18,0 s (n=60) | 2,75 |

   Bieg 14 wniosków ≈ 3,3 min, 12 szkód ≈ 2,6 min. Poziom `reasoning` biegów szkód nie jest zapisany ani w nazwie
   pliku, ani w `metadane` (`ewaluacja/uruchom.py:476-477` dopisuje sufiks tylko dla `myslenie`/Gemini). Że
   był to `low` (domyślna wartość wg `uruchom.py:348`): **NIESPRAWDZONE**. W zadaniu 4 warto zapisywać
   `reasoning` w `metadane`.
   **Korekta oczekiwań:** krok 1 supervisora *zastępuje* `klasyfikuj`, więc wnioski nie dostają dodatkowego
   wywołania LLM (zmienia się tylko prompt klasyfikacji). Szkody dostają +1 (krok 2), czyli ~3,75 zamiast 2,75
   na dokument. Tezę „drożej i wolniej o krok supervisora” (decyzja 10) i szacunek „1–2 wywołania na dokument”
   (zadanie 5) trzeba więc rozbić na moduły: wnioski ≈ bez zmian, szkody ≈ +1. Koszt 20 biegów (bez `--limit-tokenow`)
   wychodzi rząd wielkości 10 × (14 × 0,0041) + 10 × (12 × 0,0031 × ~1,4) ≈ 1,1 USD, czyli mieści się w < 2 USD.

**DO DECYZJI**

> **ROZSTRZYGNIĘTE przez właściciela 27.10:** punkty 1 i 2 — przyjęte propozycje (atrapa: `zakoncz` tylko przy S01/S02,
> Z12 → `agent_owu`; `zakoncz` przy INNY → `zakoncz_inny`, inaczej → `zatwierdzenie`; `blad` po agencie →
> `zatwierdzenie` bez LLM). Zadanie 1 nadal czeka na scalenie etap19 (bramka STOP).
> **ROZSTRZYGNIĘTE przez właściciela 28.10:** punkt 3 — wariant **(c)**: bez spanu `agent.<nazwa>`; spany `wezel.*` dostają
> atrybut `uw.agent=<nazwa>`, grupowanie w KQL. Podgrafy zostają węzłami (mechanika ze spike'u bez zmian, bez drugiego
> spike'u resume). Decyzję 8 i checklistę zadania 3 czytać z tą poprawką.
> **ROZSTRZYGNIĘTE przez właściciela 28.10:** supervisor traktuje `podejrzane_instrukcje` jak `blad` — po agencie
> deterministycznie do `zatwierdzenie`, bez wywołania LLM (Z12; patrz uwaga pod zadaniem 2).
> **ROZSTRZYGNIĘTE przez właściciela 28.10** (pytania wykonawcy zad. 4, `d0c5cc7`): założenia 1 i 6 z notatki zad. 4
> przyjęte bez zmian — `trasa_zgodna` liczona na poziomie agentów (kolejność `agent_*`, pełna trasa węzłów osobno
> w `trasa`); pusty `GRAF_WARIANT=""` = brak zmiennej = wariant domyślny `jeden`.
1. **Reguła atrapy w kroku 2 (decyzja 4) rozjeżdża się z trasą obecnego grafu dla Z12.** Reguła „`agent_owu`, gdy
   `decyzja_llm` ≠ `None`, inaczej `zakoncz`” daje `zakoncz` dla Z09, Z11 i Z12 (`decyzja_llm: null`). Obecny
   graf idzie do `zatwierdzenie` tylko przy S01/S02 (`agent/wezly_szkody.py:198-202`). Z09 ma S01, a Z11 ma S02,
   ale Z12 ma `kody_polisy: []` (`dane/szkody/oczekiwane/Z12.json`, przypadek wstrzyknięcia poleceń), więc dziś idzie
   przez `szukaj_owu → ocen_pokrycie` (atrapa zwraca tam `SKIEROWANIE`, `ewaluacja/atrapa.py:124-125`). Z obecną
   regułą kryterium „trasa zgodna 26/26 na atrapie” (zadanie 4, kryteria akceptacji) jest niespełnialne.
   **Propozycja:** atrapa w kroku 2 wybiera `zakoncz` wtedy, gdy `kody_polisy` zawiera S01 albo S02, a w pozostałych
   przypadkach `agent_owu`. To lustro `po_sprawdzeniu_polisy`. Test atrapy w zadaniu 1 (Z09 → `zakoncz`, Z01 → `agent_owu`)
   zostaje i warto dodać Z12 → `agent_owu`.
2. **`zakoncz` w `AgentDocelowy` a `zakoncz_inny`.** Literal z decyzji 4 nie ma `zakoncz_inny`, a decyzja 5 mapuje INNY
   na `zakoncz_inny`. **Propozycja:** `zakoncz` przy `typ_dokumentu == INNY` → węzeł `zakoncz_inny`, w każdym innym
   przypadku → `zatwierdzenie`. Literal zostaje bez zmian, mapowanie robi `dozwolone_ruchy`/router.
   Doprecyzować też: gdy po agencie w stanie jest `blad`, supervisor idzie deterministycznie do `zatwierdzenie`
   **bez** LLM. SPEC mówi to tylko o błędzie samego supervisora (decyzja 6).
3. **Span `agent.<nazwa>` (decyzja 8).** Podgraf dodany wprost jako węzeł nie ma miejsca na span. Do wyboru:
   (a) span `agent.<nazwa>` otwierany w pierwszym węźle podgrafu i zamykany w ostatnim. To kruche przy błędzie w środku.
   (b) wrapper-funkcja `agent.invoke(stan)` owinięta `sledz_wezel("agent.<nazwa>")`. Prosty span, ale podgraf
   staje się wywołaniem z funkcji. Resume i checkpoint w tym układzie są NIESPRAWDZONE, wymagają drugiego spike'u.
   (c) zrezygnować z `agent.<nazwa>` i grupować po atrybucie `uw.agent=<nazwa>` na spanach `wezel.*`.
   **Propozycja:** (c), bo nie rusza mechaniki z punktu 3, która jest sprawdzona. Jeśli span ma zostać, to (b) z krótkim
   spike'iem resume na początku zadania 3.
4. **Uwaga (nie blokuje):** krok 1 zastępuje `klasyfikuj` własnym promptem supervisora. Klasyfikacja dostaje więc nowy
   prompt, wbrew zasadzie „te same prompty” z decyzji 2. W tablicy wyników warto pokazać `typ_dokumentu_ok`
   (pole istnieje w wynikach wniosków) i nazwać to w README jako druga zmienna.

**Czy zadanie 1 może ruszyć bez zmian w SPEC:** nie, z powodu bramki (brak `statystyka.py` na `main`). Merytorycznie
zadanie 1 nie zależy od `statystyka.py`. Jeśli sesja główna zdejmie bramkę dla zadań 1–3, przed startem zadania 1
trzeba rozstrzygnąć DO DECYZJI 1, bo zmienia test atrapy, oraz DO DECYZJI 2, bo dotyczy schematu. Punkt 3 dotyczy dopiero zadania 3.

### Zadanie 1: schemat, Protocol, implementacje (TDD, offline)
Pliki: `agent/schematy.py`, `agent/instrukcje_supervisor.py`, `agent/model.py`, `agent/model_azure.py`,
`agent/model_vllm.py`, `obserwowalnosc/model_sledzony.py`, `ewaluacja/atrapa.py`, `tests/test_supervisor.py`.
- [x] `DecyzjaSupervisora`: nieznany `nastepny` → błąd walidacji; `uzasadnienie` przycięte.
- [x] `podsumowanie_dla_supervisora`: tylko kody polisy, braki, status ryzyka/zdjęcia, rodzaj mienia, typ —
      **bez NIP, nazwy ubezpieczonego, adresu, treści dokumentu** (test na stanie z Z01).
- [x] `ModelAzure.decyduj_supervisor` z wstrzykniętym `llm`: krok 1 zawiera tekst dokumentu, krok 2 tylko JSON podsumowania.
- [x] Atrapa: W01 → `agent_underwritingu`/WNIOSEK; Z01 krok 2 → `agent_owu`; Z09 (S01) krok 2 → `zakoncz`.
- [x] `ModelSledzony.decyduj_supervisor` deleguje i tworzy span.

#### Notatka z wykonania (28.10.2026)

- Bramka STOP zdjeta: `git log main --oneline -1` = `ca8b62e` (Scalenie etap19), `ewaluacja/statystyka.py` i `tests/test_statystyka.py` sa na `main`; `etap23` scalony (`analizuj_zdjecie` w `agent/graf.py:86`).
- DO DECYZJI 1 i 2 wdrozone: atrapa w kroku 2 = lustro `po_sprawdzeniu_polisy` (`zakoncz` tylko przy S01/S02 w `kody_polisy` z podsumowania; Z12 -> `agent_owu`); `AgentDocelowy` bez `zakoncz_inny` (test).
- **UWAGA do zadania 3 (nie blokuje):** Z12 ma `podejrzane: true`, wiec w obecnym grafie `po_ekstrakcji_szkody` kieruje go z `ekstrahuj_szkode` prosto do `zatwierdzenie` (bez `szukaj_owu`; notatka z 27.10 mowila inaczej). Podgraf `agent_szkod` konczy sie wiec po ekstrakcji, a supervisor musi traktowac `podejrzane_instrukcje` jak `blad`: deterministycznie do `zatwierdzenie` bez LLM. Wtedy krok 2 atrapy dla Z12 w ogole nie jest wolany, a trasa jest zgodna.
- `ModelVLLM` dziedziczy `decyduj_supervisor` po `ModelAzure` (test na `FakeLLM`); NIESPRAWDZONE na zywym serwerze vLLM.

### Zadanie 2: agenci jako podgrafy (TDD, offline)
Pliki: `agent/agenci.py`, `tests/test_agenci.py`.
- [x] Każdy podgraf uruchomiony samodzielnie na atrapie daje te same pola stanu co odpowiadający odcinek
      obecnego grafu (W01, Z01, Z05; porównanie `pola`, `rekomendacja`/`wynik_polisy`/`ocena_pokrycia`, `kontrola*`).
- [x] Błąd LLM w podgrafie → `blad` w stanie, podgraf kończy się (nie idzie dalej), bez wyjątku.
- [x] Podgraf nie zawiera `zatwierdzenie` ani `interrupt` (jedyny punkt nadzoru jest w rodzicu — test na liście węzłów).

#### Notatka z wykonania (28.10.2026)
- `agent/agenci.py`: `zbuduj_agenta_underwritingu(model, wytyczne, instrukcje)`, `zbuduj_agenta_szkod(model, polisy, model_ryzyka=None)`,
  `zbuduj_agenta_owu(model, wyszukiwarka)`; skompilowane BEZ checkpointera, bez `zatwierdzenie`; routery obecnego grafu
  uzyte bez kopiowania logiki, ich `"zatwierdzenie"` mapowane na `END` (blad zostaje w stanie).
- `agent_szkod` konczy sie na `ocen_ryzyko_szkody`: decyzja S01/S02 (koniec vs OWU) zostaje supervisorowi (zadanie 3).
  `po_ekstrakcji_szkody` konczy podgraf tez przy `podejrzane_instrukcje` (Z12), jak w obecnym grafie.
- Dodatkowe wyszukiwanie OWU (Z07) dzieje sie wewnatrz `ocen_pokrycie`, wiec nie jest osobnym wezlem agenta.
- Wariant (c): `sledz_wezel(nazwa, fn, agent=None)` ustawia atrybut `uw.agent` na spanie `wezel.<nazwa>`; domyslnie bez zmian.
- Testy rownowaznosci porownuja caly stan (bez `log`) i nazwy wezlow w `log` z obecnym grafem dla 13 wnioskow (W14=INNY pominiety) i 12 szkod.
- NIESPRAWDZONE: dziedziczenie checkpointera sprawdzone tylko na `InMemorySaver`, nie na Postgresie.


### Zadanie 3: supervisor i graf wieloagentowy (TDD, offline)
Pliki: `agent/supervisor.py`, `agent/graf_wieloagentowy.py`, `agent/graf.py`, `agent/wezly.py`,
`agent/decyzje_szkody.py`, `tests/test_graf_wieloagentowy.py`, test RODO atrybutów spanów.
- [x] **Atrapa, wszystkie W01–W14 i Z01–Z12: decyzja w panelu identyczna jak w wariancie `jeden`** (test parametryczny).
- [x] INNY → `zakoncz_inny`, `decyzja_koncowa == "NIE_DOTYCZY"`, bez agentów.
- [x] Bramki: supervisor (atrapa-złośnik) wybiera `agent_owu` dla WNIOSKU → korekta do `agent_underwritingu`,
      `korekty_supervisora == 1`; wybiera tego samego agenta drugi raz → korekta; niespójne `typ_dokumentu`/`nastepny` → typ wygrywa.
- [x] Dozwolony, ale zły wybór: `zakoncz` dla Z01 → panel `SKIEROWANIE` z powodem `brak_oceny` (bez korekty) — test dokumentuje zachowanie.
- [x] Błąd LLM supervisora 2× → `SKIEROWANIE`, `blad` w panelu; `wywolania_llm` agentów bez zmian.
- [x] Po `agent_underwritingu` / `agent_owu` brak wywołania LLM supervisora (licznik).
- [x] `interrupt` + `Command(resume=…)` z `MemorySaver`: wznowienie kończy graf, agenci nie są wołani ponownie (licznik wywołań atrapy).
- [x] Spany: `wezel.supervisor` z atrybutami z decyzji 8, `agent.<nazwa>` (wariant (c): spany `wezel.*` w podgrafach z `uw.agent`, bez spanu `agent.<nazwa>`); rozszerzony test RODO zielony.
- [x] `wybierz_graf("jeden")` zwraca dokładnie dotychczasowy graf (te same węzły); nieznany wariant → `ValueError` (patrz notatka: `budowniczy_grafu` + `wybierz_graf(wariant, **kw)`).
- [x] Wszystkie dotychczasowe testy bez zmian.

#### Notatka wykonawcy zad. 3 (28.10.2026)

- Commit `039cf3c`. Pliki: `agent/supervisor.py` (nowy), `agent/graf_wieloagentowy.py` (nowy), `agent/graf.py` (tylko DODANE `WARIANTY_GRAFU`, `budowniczy_grafu`, `wybierz_graf`; `zbuduj_graf` bez zmian), `agent/wezly.py` (4 pola `StanGrafu` + klucz `orkiestracja` w panelu wniosku), `agent/decyzje_szkody.py` (`orkiestracja_do_panelu`, klucz w panelu szkody), `tests/test_graf_wieloagentowy.py` (64 testy), `tests/test_telemetria.py` (+1 test RODO, istniejace asercje bez zmian).
- Klucz `orkiestracja` w panelu pojawia sie tylko, gdy stan ma `trasa_agentow` (ustawia je supervisor); w wariancie `jeden` panel bez zmian.
- Przejscia deterministyczne (bez LLM): po `agent_underwritingu`, po `agent_owu` oraz po KAZDYM agencie przy `blad` albo `podejrzane_instrukcje` (Z12: 1 wywolanie supervisora zamiast 2). Wpis w `log`: `supervisor_deterministyczny`.
- Odstepstwa / interpretacje (nie sprzecznosci wymagajace decyzji, ale warto potwierdzic):
  1. **`wybierz_graf`**: SPEC mowi „`wybierz_graf(wariant, **kw)` zwraca `zbuduj_graf` albo `zbuduj_graf_wieloagentowy`”, a checklista „`wybierz_graf("jeden")` zwraca ... graf (te same wezly)”. Wybrano: `budowniczy_grafu(wariant)` zwraca FUNKCJE (`is zbuduj_graf`), a `wybierz_graf(wariant, **kw)` buduje i zwraca skompilowany graf (`kw` jak w `zbuduj_graf`). Zadanie 4 (`SerwisAgenta._zbuduj_graf`) moze uzyc `wybierz_graf(wariant, model=..., checkpointer=..., ...)`.
  2. **Licznik `wywolania_supervisora`** = liczba KROKOW supervisora z LLM (retry nie zwieksza; widac go w `log` jako `supervisor_probaN_blad`), limit `MAKS_KROKOW_SUPERVISORA = 3`. Kroki supervisora numerowane `uw.supervisor.krok` = (liczba agentow na trasie) + 1, wiec krok bez LLM tez ma numer (np. Z01: kroki 1, 2 z LLM, 3 deterministyczny).
  3. **Atrybut `uw.supervisor.wybor`** = ostateczny cel PO bramce (`agent_szkod`, `agent_owu`, `zatwierdzenie`, `zakoncz_inny`), a nie surowy wybor LLM. Surowy wybor LLM i fakt korekty: `uw.supervisor.korekta` i wpis `supervisor_korekta` w `log`.
  4. **Krok 1 bez `typ_dokumentu`** (LLM zwrocil null) liczy sie jak nieudana proba (ponowienie, po 2 -> `blad`); SPEC mowi tylko „wymagany w kroku 1”.
  5. **Blad kroku 1 supervisora** (2 proby): `typ_dokumentu` zostaje `None`, wiec panel jest w formacie wniosku z `blad` (jak przy bledzie `klasyfikuj` w grafie `jeden`), nie w formacie szkody z decyzja SKIEROWANIE. Blad kroku 2 (szkoda): panel szkody, SKIEROWANIE, `powody_decyzji == ["blad_agenta"]`.
  6. **`wywolania_llm` w wariancie wieloagentowym** jest o 1 nizsze niz w `jeden` (krok 1 supervisora zastepuje `klasyfikuj` i liczy sie w `wywolania_supervisora`); to skutek decyzji 6, wazne przy porownaniu „LLM na dokument” w zadaniu 4/5 (sumowac oba liczniki).
- TDD: testy napisane przed kodem w jednym przebiegu (pierwsze uruchomienie dopiero po napisaniu implementacji, wiec „czerwonego” przebiegu nie obserwowano osobno).
- NIESPRAWDZONE: Postgres jako checkpointer (tylko `InMemorySaver`); `Command(goto)` + podgraf + resume sprawdzone na `InMemorySaver` (test `test_wznowienie_konczy_graf_i_nie_woluje_agentow_ponownie`).
- Rozstrzygniecie właściciela 28.10: zostaja OBIE funkcje, `wybierz_graf(wariant, **kw)` buduje skompilowany graf, a `budowniczy_grafu(wariant)` zwraca funkcje budujaca; w API uzywamy `wybierz_graf`.

### Zadanie 4: przełącznik w API i ewaluacja (TDD na atrapie)
Pliki: `api/ustawienia.py`, `api/agent_serwis.py`, `ewaluacja/uruchom.py`, `ewaluacja/trasy_oczekiwane.py`,
`tests/test_ewaluacja_wariant.py`, `tests/test_api.py` (lub nowy test ustawień).
- [x] `GRAF_WARIANT` w ustawieniach (domyślnie `jeden`, zła wartość → błąd startu); test API na atrapie w obu wariantach.
- [x] `uruchom.py --wariant`: pola z decyzji 10 w JSON; `--atrapa` w obu wariantach: wnioski 14/14, szkody 12/12, `trasa_zgodna` 26/26.
- [x] Wynik JSON czytany bez błędu przez `statystyka stabilnosc` i `porownaj` (test na plikach z atrapy w `tmp_path`).

#### Notatka wykonawcy zad. 4 (28.10.2026)

- Commity `c576f3a` (ustawienia, API, testy API) i `f48153a` (ewaluacja). Pliki: `api/ustawienia.py` (`graf_wariant`, walidacja w `__post_init__`, `z_env` czyta `GRAF_WARIANT`), `api/agent_serwis.py` (`graf_wariant`, `wybierz_graf`), `api/main.py`, `ewaluacja/uruchom.py` (`--wariant`, pola wariantu, sufiks nazwy pliku, tag/parametr), `ewaluacja/trasy_oczekiwane.py` (nowy), `ewaluacja/mlflow_log.py` (tylko nowy kwarg `wariant` + czysta `_tagi_przebiegu`), `tests/test_api_wariant.py` i `tests/test_ewaluacja_wariant.py` (nowe; 51 testow + 1 pominiety bez mlflow). Istniejace testy bez zmian asercji.
- **Liczniki LLM:** w wariancie wieloagentowym `wywolania_llm` (agenci) jest o 1 nizsze niz w `jeden` (krok 1 supervisora zastepuje `klasyfikuj`). Pole porownywalne to `wywolania_llm_razem` = `wywolania_llm` + `wywolania_supervisora` (w wierszu przypadku), a w `metadane` `wywolania_llm_laczne` = suma; skladniki osobno: `wywolania_llm_agenci_laczne`, `wywolania_supervisora_laczne`. Na atrapie: wnioski 40 = 40 (suma rowna), szkody 34 (jeden) vs 45 (wielo: agenci 22 + supervisor 23), czyli +11, bo krok 2 supervisora dodaje 1 wywolanie we wszystkich przypadkach poza Z12 (przejscie deterministyczne).
- **Odstepstwa / zalozenia:**
  1. `trasa_zgodna` liczona na poziomie AGENTOW (kolejnosc `agent_*`), nie pelnych wezlow; trasa wezlow zapisana osobno w polu `trasa`. W `jeden` trasa agentow jest wyprowadzana z `log` (wezel -> agent).
  2. `TRASY_OCZEKIWANE` wygenerowane z biegu atrapy `jeden` (zgodnie z decyzja 10); test pilnuje, zeby nie rozjechalo sie z grafem.
  3. Nowe pola dodawane tez do wariantu `jeden` (addytywnie; potrzebne do `trasa_zgodna` w baseline). Istniejace klucze JSON i wartosci bez zmian.
  4. Tag MLflow `wariant` idzie osobnym kwargiem `zaloguj_przebieg(wariant=...)`, nie w `tagi_dodatkowe`, bo istniejacy test asercjonuje dokladny slownik `tagi_dodatkowe` (`test_run_rag_szkod_ma_tag_klucz_przebiegu`). Wariant `jeden` tez dostaje tag.
  5. Nazwa pliku wynikow wariantu innego niz `jeden` ma sufiks `_wieloagentowy` (nazwy dla `jeden` bez zmian); znacznik czasu nadal co do minuty, wiec dwa biegi TEGO SAMEGO wariantu w tej samej minucie nadpisza plik (dotyczy zad. 5, nie zmieniano).
  6. Pusty `GRAF_WARIANT=""` traktowany jak brak zmiennej (domyslny `jeden`); `GRAF_WARIANTY_DOZWOLONE` zduplikowane w `api/ustawienia.py` (konfiguracja nie importuje LangGraph), zgodnosc z `WARIANTY_GRAFU` pilnuje test.
  7. `wywolania_supervisora` liczy kroki, nie ponowienia, wiec przy awarii supervisora suma `wywolania_llm_razem` lekko niedoszacowuje realne wywolania (na atrapie bez znaczenia).
  8. `metadane.reasoning` zapisywane tylko dla modelu Azure (nie vLLM); dla atrapy/Gemini brak pola.
- NIESPRAWDZONE: prawdziwy bieg MLflow (w venv nie ma `mlflow`; test `test_zaloguj_przebieg_ustawia_tag_wariant` pominiety, sprawdzona tylko czysta `_tagi_przebiegu`); Postgres; bieg na zywo (zad. 5).

### Zadanie 5: biegi na żywo, statystyka, tablica
Pliki: `ewaluacja/wyniki/*`, `docs/ROZWOJ.md`.
- [x] 20 biegów przeplatanych (decyzja 10). Szacunek kosztu: dotychczasowe biegi ~ grosze na 14 dokumentów; supervisor
      dodaje 1–2 wywołania na dokument → całość rzędu < 2 USD (przeliczyć po pierwszym biegu; bezpiecznik `--limit-tokenow`).
      Czas: ~4 min × 20 ≈ 1,5 h — puścić w tle, zapisywać wyniki po każdym biegu (wznowienie od brakującego).
- [x] `stabilnosc` dla 4 kombinacji i `porownaj` dla 2 modułów, raporty `--zapisz` do `ewaluacja/wyniki/statystyka_2026-10-29_*.md`.
- [x] Tablica + akapit wniosku w `docs/ROZWOJ.md`; przypadki z `trasa_zgodna == False` wypisane z uzasadnieniem supervisora.
- [x] Jeśli któryś bieg padł (429, timeout) — nie powtarzać po cichu: zapisać w raporcie, dobić brakujący bieg i to też odnotować.

### Zadanie 6: dokumentacja
Pliki: `README.md`, `docs/ROZWOJ.md`.
- [x] README, sekcja „Wariant wieloagentowy”: diagram (supervisor + 3 agentów + `zatwierdzenie`), gdzie LLM
      a gdzie kod, bramki, przełącznik `GRAF_WARIANT`, wynik z tablicy, decyzja o frameworku (decyzja 1) z wzmianką
      CrewAI/PydanticAI jako poza zakresem, efekt sufitu i małe n.

## Kryteria akceptacji

- `pytest -m "not azure"` — dotychczasowe testy zielone bez zmian, nowe zielone offline.
- `GRAF_WARIANT` nieustawiony → zachowanie API i ewaluacji identyczne jak przed etapem.
- Atrapa w wariancie wieloagentowym: 14/14 i 12/12, trasa zgodna 26/26, jedyny `interrupt` w rodzicu.
- 5 biegów × 2 warianty × 2 moduły na gpt-5-mini, raporty `stabilnosc` i `porownaj` w repo, tablica z 8+ kolumnami
  i akapitem wniosku w `docs/ROZWOJ.md`, runy MLflow z tagiem `wariant`.
- README z sekcją i uczciwym opisem zakresu „wieloagentowości”.

## Ryzyka

- `statystyka.py` niescalona 29.10 → zadanie 0 zatrzymuje etap (decyzja o scaleniu należy do sesji głównej).
- Podgraf + `interrupt` w rodzicu + checkpointer Postgres: zachowanie przy wznowieniu sprawdzane na `MemorySaver`;
  na Postgres tylko w teście integracyjnym (marker `integracja`), jeśli czas pozwoli — odnotować, jeśli nie.
- Efekt sufitu (14/14, 12/12) i małe n — trafność nie rozstrzygnie; wniosek opiera się na koszcie, opóźnieniu i trasie.
- Zmienność gpt-5-mini między biegami (19a: W07 4/5) — 5 biegów przeplatanych + wynik większościowy, rozrzut raportowany.
- Limit TPM wdrożenia przy 20 biegach pod rząd → przerwy między biegami zamiast równoległości.
- Pokusa „poprawiania” promptu supervisora pod zestaw ewaluacyjny — prompt ustalony przed biegami; zmiana = nowy komplet 5 biegów.

## Czego nie robić

- Nie usuwać ani nie zmieniać zachowania obecnego grafu; nie zmieniać domyślnego wariantu.
- Nie przenosić deterministycznych kontroli (silnik reguł, S01–S04, kontrola cytatów) do LLM; supervisor nie podejmuje decyzji merytorycznej.
- Nie dodawać `langgraph-supervisor`, CrewAI, PydanticAI ani natywnego tool calling.
- Nie zmieniać promptów agentów (porównanie ma mierzyć orkiestrację).
- Nie dodawać frontendu, zasobów Azure, `terraform`; nie wdrażać.
- Nie kopiować `statystyka.py` z gałęzi `etap19` ani nie ruszać innych worktree.
