# SPEC Etap 19 — statystyka ewaluacji, SQL na transakcjach, metryki efektu

Cel: dołożyć do projektu trzy elementy: statystykę ewaluacji, SQL na transakcjach i metryki efektu.

| część | repo | czas | koszt | Azure |
|---|---|---|---|---|
| 19a statystyka | `underwriter_agent_demo` | 1 wieczór | ~0,5 USD | tak (biegi), część A25 bez |
| 19b SQL transakcyjny | `demo_mssql_metabase` | 1 wieczór | 0 | nie |
| 19c metryki efektu | `underwriter_agent_demo` | pół dnia | grosze | **tak, przed 9.11** |

**Kolejność:** 19a-zad.3 (A25, zero kosztu) → reszta 19a → 19c → 19b.
- 19c wymaga kredytu Azure (wygasa 9.11).
- 19b zmienia repo, dla którego 24.10 napisano przewodnik po kodzie pod Work Flow Service (termin 02.11, formularz niewysłany). Zrób 19b **po wysłaniu formularza WFS** albo na osobnej gałęzi, żeby przewodnik nie rozjechał się z `main`.

**Gałęzie:** 19a i 19c na `etap19` od `main`, 19b na `transakcje` w `demo_mssql_metabase`.

### Środowisko pracy (obowiązuje każdą sesję i każdego agenta Etapu 19)

- **Etap 19 pracuje WYŁĄCZNIE w worktree `projekty\underwriter_etap19`** (gałąź `etap19`). Katalog `projekty\underwriter_agent_demo` należy do Etapu 15 (gałąź `etap15`): tam nie wolno przełączać gałęzi ani commitować. Agenci Etapu 15 commitują tam na bieżąco i mają niezacommitowane zmiany.
- **Nigdy `git commit -a` ani `git add -A`/`.`**, tylko jawne ścieżki. 26.10 commit `-a` w katalogu Etapu 15 zgarnął 98 linii cudzej pracy (`agent/*.py`, `Dockerfile`) pod wiadomością o Etapie 19. Cofnięty `reset --mixed`, zmiany wróciły jako niezacommitowane.
- Python: worktree nie ma własnego `.venv`, więc testy uruchamiasz przez `..\underwriter_agent_demo\.venv\Scripts\python -m pytest ...`. `.venv-ewaluacja` i `.venv-mlops` też są tylko w katalogu głównym. **Venv tylko czytamy**: `pip install` zmieniłby środowisko Etapu 15.
- Do posprzątania (robi sesja Etapu 15, gdy jej agenci skończą): commit `b3a7b87` (ta specyfikacja) trafił omyłkowo na `etap15`. Na `etap19` jest jego kopia `439a78d`. Wycięcie: `git rebase --onto b3a7b87^ b3a7b87 etap15`, tylko przy czystym drzewie.
- Scalanie: `etap15` i `etap19` mają różne kopie dopisków w wewnętrznym planie etapów (poza repo). Przy merge drugiej z nich do `main` spodziewaj się konfliktu w tym pliku; rozwiązanie to suma obu zestawów dopisków.

---

## Stan zastany (sprawdzony 26.10, podstawa decyzji)

- Wyniki ewaluacji underwritera to JSON-y w `ewaluacja/wyniki/` z listą `przypadki`, po jednym wierszu na przypadek. Pole binarne dla wniosków to `decyzja_llm_ok` (14 przypadków), dla szkód `decyzja_ok` (12 przypadków). Biegi uruchamia `python -m ewaluacja.uruchom`; jeden bieg daje jeden plik.
- Wyniki A25 (text-to-SQL) to `demo_mssql_metabase/asystent/wyniki/ewaluacja_azure-openai_2026-10-21.json` (10/12) i `..._2026-10-24.json` (9/12), oba z listą `pytania` (wiersze `WynikPytania`, pole `trafione`). **To ta sama konfiguracja w dwóch biegach**, więc porównanie pokazuje szum, a nie różnicę między modelami.
- `scipy` nie ma w `requirements*.txt`.
- Spany: `wniosek.*` mają `uw.typ_dokumentu`, `uw.decyzja`, `uw.status`, `uw.blad`, `error.type` (`api/agent_serwis.py:108-131`), a `llm.*` mają `gen_ai.request.model` i `gen_ai.usage.input_tokens/output_tokens` (`obserwowalnosc/model_sledzony.py`).
- **Brak w spanach:** odejścia człowieka od rekomendacji. Liczy je `api/trasy.py:186-197` (`odejscie_od_rekomendacji`), ale wynik trafia tylko do audytu w bazie.
- Cennik orientacyjny gpt-5-mini: `ewaluacja/uruchom.py:65-66` (0,25 / 2,00 USD za 1M tokenów).
- Test alarmu w dwóch stanach jest gotowy jako wzorzec: `obserwowalnosc/test_alarmu.py` (osobna rola `uw-test-alarmu`).
- `demo_mssql_metabase`: tabele `dostawca`, `produkt`, `cena_zakupu` (SCD2 per `sku`+`dostawca_id`), `cena_sprzedazy` (jedna cena na SKU, bez historii). Migracje to `sql/NNN_*.sql` z tabelą `schemat_wersja`. Generator ma stałe ziarno (`generuj(ziarno=42)`). Testy są per obszar (`test_widoki.py`, `test_rola_odczytu.py`, `test_asystent_ewaluacja.py`).
- **Nie ma stanu magazynu**, więc rotacji ani dni pokrycia nie da się dziś policzyć.

---

## 19a — ocena statystyczna

### Decyzje

1. **Czysty stdlib** (`math.comb`, `math.sqrt`), bez `scipy`. Dwie funkcje to kilkanaście linii, a nowa zależność w obrazie API to koszt bez zysku.
2. **Wilson 95%** (z = 1,959964) dla proporcji trafień. Przy n = 12–14 i p blisko 1 przedział Walda się sypie (wychodzi poza [0, 1]), a Wilson nie. To zdanie warto mieć gotowe na rozmowę.
3. **McNemar dokładny (dwumianowy)**, nie χ². Przy n = 14 par niezgodnych jest najwyżej kilka, a wersja χ² wymaga ich około 25 lub więcej. Liczymy p = min(1, 2·Σ_{k=0..min(b,c)} C(b+c, k)·0,5^(b+c)).
4. **Pięć biegów to nie 5 × 14 = 70 niezależnych prób.** Biegi tego samego przypadku są skorelowane, a efektywne n wynosi 14. Raport pokazuje więc:
   - wynik każdego biegu z przedziałem Wilsona na n = 14,
   - rozrzut (min–max, średnią) między biegami,
   - **przypadki niestabilne**, czyli trafione w części biegów, wypisane z identyfikatorami,
   - do McNemara: wynik przypadku = większość (≥ 3/5).

   Przedziału Wilsona na 70 próbach nie liczymy, bo zawyżałby pewność.
5. **Granica wykrywalności** jako jawne zdanie w raporcie: przy dokładnym McNemarze p < 0,05 wymaga co najmniej 6 par niezgodnych, wszystkich w jedną stronę (2/64 = 0,031; przy 5 parach 2/32 = 0,0625). Na 14 przypadkach druga konfiguracja musi więc wygrać na 6 przypadkach i nie przegrać żadnego. Wniosek: zestaw 14 przypadków wystarcza do pokazania regresji o sporej skali, ale do strojenia promptu jest za mały.

### Pliki

- `ewaluacja/statystyka.py` (nowy): funkcje i CLI
- `tests/test_statystyka.py` (nowy)
- `docs/ROZWOJ.md`: sekcja „Ocena statystyczna ewaluacji”
- `ewaluacja/wyniki/statystyka_*.md`: raporty lokalne (katalog w `.gitignore`); treść do repo trafia przez `docs/ROZWOJ.md`

### Interfejs

```python
def przedzial_wilsona(trafienia: int, n: int, z: float = 1.959964) -> tuple[float, float]: ...
def mcnemar_dokladny(b: int, c: int) -> float: ...            # b: A ok / B zle, c: A zle / B ok
def wczytaj_wyniki(plik: Path, pole: str, klucz_listy: str = "przypadki",
                   pole_id: str = "id") -> dict[str, bool]: ...
def stabilnosc(biegi: list[dict[str, bool]]) -> dict: ...      # per bieg, rozrzut, niestabilne, wiekszosc
def porownaj(a: dict[str, bool], b: dict[str, bool]) -> dict: ...  # tylko wspolne id; b, c, p, roznica
```

CLI:
```
python -m ewaluacja.statystyka stabilnosc PLIK... --pole decyzja_llm_ok
python -m ewaluacja.statystyka porownaj PLIK_A PLIK_B --pole trafione --klucz-listy pytania --pole-id <id z WynikPytania>
```
CLI wypisuje tabelę markdown na stdout; `--zapisz` zapisuje ją do `ewaluacja/wyniki/statystyka_<data>_<opis>.md`. **Rozbieżność zbiorów id** (przypadek tylko w jednym pliku) → ostrzeżenie na stderr z listą id, porównanie na części wspólnej. Nie wolno jej cicho pominąć.

### Zadania

**Zad. 1: funkcje + testy (TDD). ZROBIONE 26.10 (`1bd537d`), 22 testy.** Wartości referencyjne:
- Wilson (Newcombe 1998, tab. I): 81/263 → (0,2553; 0,3662); 15/148 → (0,0624; 0,1605); 0/20 → (0; 0,1611); 1/29 → (0,0061; 0,1718). Tolerancja 1e-4.
- McNemar dokładny: (b=0, c=5) → 0,0625; (0, 6) → 0,03125; (1, 1) → 1,0; (3, 0) → 0,25; (0, 0) → 1,0.
- Przypadki brzegowe: n = 0 → `ValueError`; trafienia > n → `ValueError`.
- `wczytaj_wyniki`: pole nie-bool (np. `None` przy błędzie przypadku) → liczone jako **nietrafione** i zgłoszone w ostrzeżeniu. Błąd agenta to porażka, nie brak danych.

**Zad. 2: ZROBIONE 26.10 (`1bd537d`).** CLI `stabilnosc` i `porownaj` + test na dwóch małych plikach JSON w `tmp_path`.

**Zad. 3: ZROBIONE 26.10.** Wynik: 10 vs 9/12, 3 pary niezgodne (E06, E08 trafione tylko 21.10; E05 tylko 24.10), p = 1,0. Ta sama konfiguracja zmieniła wynik na 3 z 12 pytań. Raport lokalny `ewaluacja/wyniki/statystyka_2026-10-26_a25.md`. Pierwotny opis: A25, zero kosztu. Uruchom `porownaj` na obu plikach A25. Najpierw sprawdź, jak `WynikPytania` identyfikuje pytanie (`asystent/ewaluacja.py:144`). Oczekiwanie: p = 1,0 albo bliskie 1. To jest gotowe zdanie „10 vs 9 na 12 to szum” z liczbą. Raport → `ewaluacja/wyniki/statystyka_2026-10-xx_a25.md`.

**Zad. 4: ZROBIONE 26.10 (wnioski low 14,14,13,14,14; szkody 12/12 x5; łącznie z zad. 5 koszt 0,65 USD; runner w scratchpadzie sesji, env z `.env.example`, cache OCR skopiowany z katalogu głównego).** 5 biegów gpt-5-mini. Koszt z tokenów biegów 17.10/21.10: wnioski ~0,06 USD/bieg, szkody ~0,04 USD/bieg, 5 + 5 ≈ 0,48 USD; z drugą konfiguracją (zad. 5) ≈ 0,8 USD. Uruchamiaj z TEGO worktree (wyniki lądują w jego `ewaluacja/wyniki/`). Pętla w powłoce, **bez zmian w `uruchom.py`**:
```
for i in 1 2 3 4 5; do python -m ewaluacja.uruchom --model <jak w ostatnim biegu 17.10> ; done
for i in 1 2 3 4 5; do python -m ewaluacja.uruchom --modul szkody --model <jak 21.10, bez sędziego> ; done
```
- Przed pętlą sprawdź flagi w `uruchom.py:317-363` i koszt jednego biegu z `_tokeny_we/_wy` w ostatnim JSON-ie. Jeśli 10 biegów przekracza 1 USD, zatrzymaj się i zapytaj.
- Uruchamia właściciel albo agent, jeśli poświadczenia Azure są w środowisku lokalnym.
- Potem `stabilnosc` dla obu modułów.

**Zad. 5: ZROBIONE 26.10. `low` vs `minimal`: 14 vs 9/14, pary 5:0, p = 0,0625 (granica wykrywalności); `--reasoning` przyjmuje tylko `minimal`/`low`, więc nie `medium`.** Porównanie dwóch konfiguracji.
- Jeśli Etap 18 już jest zrobiony, bierzemy jego konfiguracje.
- Jeśli nie: gpt-5-mini z wysiłkiem rozumowania low vs minimal (CLI nie ma `medium`), po 5 biegów każda, wynik przypadku = większość.
- Wcześniej sprawdź, czy pliki z 10.10 (gemini-3.8-flash, gpt-5-mini) mają te same id przypadków co dziś. Jeśli tak, wystarczy dodatkowe porównanie za darmo, z adnotacją „1 bieg”.
- McNemar + zdanie wniosku.

**Zad. 6: dokumentacja ZROBIONA 26.10 (`docs/ROZWOJ.md`, sekcja Etap 19a); log do MLflow POMINIĘTY (wymaga `.venv-ewaluacja`, wyniki są w docs; do zrobienia, jeśli potrzebne na demo).** MLflow + dokumentacja.
- Raport jako artefakt runu MLflow przez istniejące `ewaluacja/mlflow_log.zaloguj_przebieg` (sprawdź sygnaturę), metryki `trafnosc_min/max/srednia`, `niestabilne`.
- Sekcja w `docs/ROZWOJ.md`: metoda (dlaczego Wilson, dlaczego dokładny McNemar, dlaczego n = 14, a nie 70), tabela, granica wykrywalności, trzy zdania wniosku.

### Kryteria akceptacji 19a

- [x] testy funkcji przechodzą na wartościach referencyjnych powyżej
- [x] raport A25 z p-value i zdaniem wniosku
- [x] raport stabilności 5 biegów dla wniosków i szkód, z listą przypadków niestabilnych
- [x] jedno porównanie dwóch konfiguracji z p-value
- [x] sekcja w `docs/ROZWOJ.md` z granicą wykrywalności
- [x] pełny zestaw testów repo zielony

---

## 19b — SQL na danych transakcyjnych (`demo_mssql_metabase`)

### Decyzje

1. **Migracja `005_transakcje.sql`** z tabelami:
   - `klient` (id, nazwa, typ `HURT`/`DETAL`),
   - `zamowienie` (id, klient_id, data, status),
   - `pozycja_zamowienia` (zamowienie_id, sku, **dostawca_id**, ilosc, cena_sprzedazy_netto),
   - `zwrot` (pozycja_id, ilosc, powod, data),
   - `stan_magazynu` (sku, ilosc, na_dzien): jeden zrzut na koniec okresu, wystarczy do dni pokrycia.

   `dostawca_id` na pozycji jest konieczny, bo cena zakupu w SCD2 jest per para SKU–dostawca. Cena sprzedaży zapisana na pozycji rozwiązuje brak historii w `cena_sprzedazy`.
2. **Generator** to rozszerzenie `generator/generuj_dane.py`, to samo ziarno:
   - 12 miesięcy, rząd 20–30 tys. pozycji,
   - popyt Pareto, żeby ABC miało sens (~20% SKU ≈ 80% obrotu),
   - część SKU stabilna, część sezonowa lub skokowa, żeby XYZ miało sens,
   - ~2–4% zwrotów skupionych u 1–2 dostawców,
   - kilka celowych wyjątków (marża ujemna, ilość odstająca), żeby widok wyjątków nie był pusty.

   Dane są fikcyjne, jak dotąd.
3. **Konwencja okresu SCD2:** przed pisaniem JOIN-a potwierdź w `_historia()` generatora, czy `obowiazuje_do` jest wyłączne, czyli przedział [od, do). CHECK `do > od` na to wskazuje. JOIN marży: `z.data >= cz.obowiazuje_od AND (cz.obowiazuje_do IS NULL OR z.data < cz.obowiazuje_do)`.
4. **Widoki (`006_widoki_transakcje.sql`):**
   - `abc_xyz`: ABC po skumulowanym udziale obrotu (A ≤ 80%, B ≤ 95%), XYZ po współczynniku zmienności miesięcznej ilości (X ≤ 0,5, Y ≤ 1,0, Z > 1,0); okno `SUM() OVER (ORDER BY ...)`.
   - `rotacja`: średnia dzienna sprzedaż z ostatnich 90 dni, dni pokrycia = stan / średnia; SKU bez sprzedaży → NULL, nie dzielenie przez zero.
   - `marza_zamowienia`: z ceną zakupu z dnia zamówienia.
   - `zwroty_dostawcy`: odsetek zwróconej ilości per dostawca.
   - `zamowienia_wyjatki`: marża ujemna LUB ilość > średnia + 3σ dla SKU (`AVG/STDEV OVER (PARTITION BY sku)`), z kolumną `powod`.
5. **Rola odczytu:** sprawdź `004_rola_odczytu.sql`, czy uprawnienia idą per schemat czy per obiekt. Jeśli per obiekt, nadaj je nowym obiektom i dodaj przypadki do `test_rola_odczytu.py`. Asystent text-to-SQL musi widzieć nowe tabele, a nadal nie może pisać.
6. **Ewaluacja text-to-SQL:** 4 nowe pytania (ABC, marża z dnia zamówienia, zwroty per dostawca, wyjątki) jako **osobny zestaw** obok 12 starych. Wynik 10/12 z A25 zostaje porównywalny, a nowy zestaw raportujemy oddzielnie.

### Zadania

1. Migracja 005 + `test_schemat.py`: tabele, FK, CHECK (ilość > 0, zwrot ≤ ilość pozycji, przez trigger albo test, że generator tego nie łamie); drugi bieg migracji kończy się „nic do zrobienia” (`test_migracje.py`).
2. Generator + `test_generator.py`: determinizm ziarna, rozkład Pareto (udział top 20% SKU w obrocie w przedziale 0,7–0,9), obecność celowych wyjątków.
3. Widoki 006 + `test_widoki.py` na **małym, ręcznie znanym zbiorze**, jak dotychczasowe testy widoków. Obowiązkowo test marży z ceną zmienioną w środku okresu: zamówienie przed zmianą ma starą cenę zakupu, po zmianie nową.
4. Rola odczytu + test.
5. 2–3 karty w Metabase (`metabase/provisionuj.py`: macierz ABC/XYZ, top wyjątków, zwroty per dostawca) + `test_metabase.py`.
6. 4 pytania ewaluacyjne + bieg (Azure OpenAI z demo, koszt w groszach) + zapis wyniku.
7. README: sekcja „Dane transakcyjne”.

**Uwaga operacyjna:** pełny `compose up` podmienia dane. Przed biegiem na żywej bazie sprawdź w README, jak dziś zasiewa się dane, i nie nadpisuj stanu, na którym opiera się przewodnik demo.

### Kryteria akceptacji 19b

- [ ] drugi bieg migracji kończy się „nic do zrobienia”
- [ ] każdy widok ma test na znanym zbiorze; jest test marży ze zmianą ceny w środku okresu
- [ ] rola odczytu widzi nowe obiekty i nie może pisać (test)
- [ ] nowy zestaw pytań text-to-SQL ma wynik raportowany osobno od 12 starych
- [ ] pełny zestaw testów zielony

---

## 19c — metryki efektu rozwiązania (underwriter, Azure)

### Decyzje

1. **Pięć metryk** liczonych z telemetrii, nie z bazy. App Insights zostaje jedynym źródłem, a dashboard nie potrzebuje dostępu do Postgresa:

   | metryka | źródło |
   |---|---|
   | koszt LLM na wniosek (średnia, p95) | suma tokenów `llm.*` × cennik, grupowanie po id wniosku |
   | odsetek wniosków z rekomendacją `SKIEROWANIE` (sprawy niestandardowe) | `uw.decyzja` na `wniosek.uruchom` |
   | **odsetek odejść człowieka od rekomendacji** | **nowy** `uw.odejscie_od_rekomendacji` na spanie `wznow` |
   | odsetek wniosków z błędem agenta | `uw.blad` |
   | p95 czasu przebiegu agenta | `duration` spanu `wniosek.uruchom` |

   Każdy wniosek trafia do człowieka (interrupt), więc „odsetek do człowieka” wynosiłby zawsze 100%. Dlatego metryką wyjątków jest odsetek rekomendacji `SKIEROWANIE`, i tak trzeba to nazwać w dokumentacji.
2. **Atrybut odejścia:** `trasy.py` ma już `odejscie_od_rekomendacji` przed `serwis.wznow(...)`. Przekazujemy go nowym opcjonalnym argumentem `wznow(..., odejscie: bool | None = None)` i ustawiamy na spanie wewnątrz `wznow`, obok `_opisz_wynik`. Dodatkowo `uw.decyzja_czlowieka` (kod decyzji, bez treści, zgodnie z RODO jak dotąd).
3. **Id wniosku na spanach:** `uruchom` (zadanie w tle) i `wznow` (późniejszy request) to **dwa różne trace'y**, więc `operation_Id` ich nie połączy. Sprawdź, czy `api/agent_serwis.py:94-98` ustawia `uw.wniosek_id` na obu spanach (w `test_alarmu.py:109` atrybut istnieje). Jeśli nie, dodaj go; KQL grupuje po nim.
4. **Cennik w KQL** jako `let` ze stałymi z `uruchom.py:65-66`, z tym samym komentarzem „orientacyjny”. Cennik żyje w dwóch miejscach, więc test pilnuje, że stałe w pliku `.kql` i w `uruchom.py` są równe.
5. **Workbook w Terraform** (`azurerm_application_insights_workbook`, `data_json` z `templatefile`): pięć kafelków i parametr `cloud_RoleName`, żeby odfiltrować ruch testowy. Jeśli workbook na trialu okaże się niepraktyczny, zostają zapytania w repo + zrzut ekranu w docs; decyzja w trakcie, odnotowana w docs.
6. **Nowy alert to alert JAKOŚCI, nie awarii:** odsetek odejść od rekomendacji > 50% w oknie 24 h przy min. 5 decyzjach. Istniejący alert z Etapu 13 łapie każdy błąd techniczny, więc alert na odsetek błędów by go dublował. Odejścia mierzą co innego: model działa technicznie, ale ludzie przestają mu ufać, co jest sygnałem dryfu. Próg i okno są wstępne; przed wdrożeniem przejdź skill `nadzor-automatu`.
7. **Zasiew danych** (≥ 10 wniosków przed 9.11): skrypt `obserwowalnosc/zasiej_wnioski.py`, lokalnie, wzorzec `test_alarmu.py`:
   - osobna rola `uw-zasiew`,
   - FastAPI `TestClient` z prawdziwym grafem i gpt-5-mini, więc ścieżka przez `trasy.py` jest prawdziwa,
   - przypadki W01–W14, decyzje człowieka z listy w skrypcie (część zgodna, część odbiegająca, z komentarzem),
   - wymaga Postgresa/Bloba jak lokalny `compose`; sprawdź, czego `TestClient` potrzebuje, zanim napiszesz skrypt.

   Obraz na Azure nie musi się zmieniać, żeby metryki zadziałały. Wdrożenie atrybutu na `uw-api` to osobny, opcjonalny krok wykonywany przez właściciela. **Pełny bicep kasuje sekret Easy Auth `uw-web`**, więc tylko `containerapp update`, a Terraform przed bicepem.

### Pliki

- `api/agent_serwis.py` (`wznow`, ewentualnie `uw.wniosek_id`), `api/trasy.py` (przekazanie flagi)
- `tests/test_telemetria.py`: nowe przypadki z `InMemorySpanExporter`
- `obserwowalnosc/metryki_efektu.kql` (nowy, 5 zapytań + zapytanie alertu)
- `obserwowalnosc/zasiej_wnioski.py` (nowy)
- `infra/terraform/`: workbook + `azurerm_monitor_scheduled_query_rules_alert_v2` dla odejść
- `docs/MONITORING.md`: sekcja „Metryki efektu”

### Zadania

0. **ZROBIONE 26.10 (`8fd7922`).** Luka: `uw.decyzja` dla SZKODA z payloadu interruptu (`api/agent_serwis.py::_opisz_wynik`) + testy; komentarz zapytania 2 w .kql.
1. **ZROBIONE 26.10 (`2b2eea9`).** Atrybuty `uw.odejscie_od_rekomendacji`, `uw.decyzja_czlowieka` (+ `uw.wniosek_id`, jeśli brak) z testami: decyzja zgodna → `False`; odbiegająca z komentarzem → `True`; brak treści dokumentu w atrybutach (istniejący test RODO rozszerzony o nowe klucze).
2. **ZROBIONE 26.10 (`2b2eea9`).** `metryki_efektu.kql` + test zgodności cennika. KQL sprawdzasz ręcznie w portalu (Logs) na danych z zad. 4. Najpierw ustal, w której tabeli lądują spany wewnętrzne (`dependencies` vs `requests`) i jak wyglądają klucze w `customDimensions`; zrób to na danych z testu alarmu z 24.10.
3. **CZĘŚCIOWO 26.10 (`ccd7059`): plan zrobiony** (`terraform plan -lock=false`: tylko dodania, 2 zasoby), `apply` czeka na właściciela. Terraform: workbook + alert; `terraform plan` pokazuje tylko dodanie zasobów (żadnej zmiany ani usunięcia istniejących). `apply` uruchamia właściciel.
4. **SKRYPT GOTOWY 26.10 (`bf4592f`), bieg płatny czeka** (gpt-5-mini + eksport do App Insights, uruchamia właściciel; na atrapie zdrowy i chory przechodzą). `zasiej_wnioski.py` + bieg w stanie **zdrowym**: 10 wniosków, 2 odejścia (20%) → alert milczy, workbook pokazuje pięć metryk.
5. Bieg w stanie **chorym**: drugi zasiew, 6 z 8 decyzji odbiega → alert odpala, mail dochodzi. Potem potwierdź Resolved albo opisz, dlaczego okno 24 h go nie domknie w czasie testu (wtedy test z krótszym oknem tymczasowo, przywrócony po teście).
   **Przegląd `nadzor-automatu` 26.10, harmonogram testu:** okno 24 h sumuje oba zasiewy. Chory zasiew w ciągu 24 h od zdrowego daje (2+6)/(10+8) = 44% i alert NIE odpali. Dlatego zasiewy rozdziela co najmniej 25 h, bez zmiany okna w regule:
   (a) po `apply` zasiew zdrowy, alert milczy przez 2 ewaluacje (PT1H);
   (b) ≥ 25 h później zasiew chory, alert odpala, mail dochodzi;
   (c) ~24 h po chorym dane wypadają z okna, alert Resolved (auto_mitigation), w tym czasie żadnego drugiego maila.
   Wszystko przed 9.11.
   **Apply tylko z `-target`** na dwa nowe zasoby (`azurerm_application_insights_workbook.metryki_efektu`, `azurerm_monitor_scheduled_query_rules_alert_v2.odejscia`). Stan `etap13.tfstate` jest wspólny z Etapem 15, a worktree etap19 nie ma `dryf.tf`. Pełny apply po wdrożeniu Etapu 15 zniszczyłby jego zasoby. Z Windows pełny plan pokazuje też fałszywą zmianę alertu `awaria` (CRLF w heredocach); `-target` ją omija.
6. `docs/MONITORING.md`: definicje metryk (zwłaszcza dlaczego `SKIEROWANIE`, a nie „do człowieka”), zrzut workbooka, opis testu alertu w obu stanach z datami. Dwa zastrzeżenia z przeglądu `nadzor-automatu`:
   - **Co mierzy odejście:** dla wniosku flaga z `trasy.py` jest prawdziwa, gdy człowiek różni się od LLM **albo** od silnika reguł. Gdy LLM i silnik się nie zgadzają, każda decyzja jest „odejściem”. Metryka miesza więc nieufność człowieka z niezgodnością LLM–silnik i trzeba to napisać wprost.
   - **Poniżej 5 decyzji w 24 h alert milczy**, co znaczy „nie sprawdzono”, a nie „zdrowo”. Osobnego alertu na małą próbę nie ma, bo demo bez ruchu odpalałoby go stale. Kafelek workbooka pokazuje liczbę decyzji obok odsetka.
7. Lista sprzątania przed 9.11 w `docs/ROZWOJ.md` dopisuje workbook i nową regułę alertu.

### Kryteria akceptacji 19c

- [ ] nowe atrybuty z testami, test RODO zielony
- [ ] 5 metryk widocznych dla ≥ 10 wniosków (workbook albo zapisane zapytania + zrzut)
- [ ] alert odejść przetestowany w obu stanach, z datami w docs
- [ ] `terraform plan` bez zmian w istniejących zasobach
- [ ] pełny zestaw testów repo zielony

---

## Ryzyka

| ryzyko | skutek | co robimy |
|---|---|---|
| koszt 10–20 biegów 19a | > budżet „kilka centów” | koszt jednego biegu z JSON przed pętlą; > 1 USD → pytanie do właściciela |
| zmiana zestawu przypadków od 10.10 | porównanie z archiwalnymi plikami nieważne | `porownaj` ostrzega o rozbieżnych id i liczy na części wspólnej |
| 19c po 9.11 | brak Azure, brak metryk | 19c przed 19b; zasiew najpóźniej 7.11 |
| workbook w TF na trialu | dzień walki z JSON-em | fallback: zapytania + zrzut |
| 19b przed wysłaniem formularza WFS | przewodnik niezgodny z `main` | 19b po WFS albo na gałęzi |
| zasiew ruchem testowym psuje metryki „prawdziwe” | mieszanie danych | osobna `cloud_RoleName`, parametr w workbooku |

## Zdania na rozmowę (cel etapu)

- „10 vs 9 na 12 pytań: dokładny McNemar daje p = …, więc to szum. Na 14 przypadkach różnica musi wynosić 6 przypadków w jedną stronę, żeby była istotna, i dlatego zestaw ewaluacyjny rozbudowuję, zanim zacznę stroić prompt.”
- „Pięć biegów to nie 70 prób, bo biegi tego samego przypadku są skorelowane. Raportuję rozrzut i przypadki niestabilne.”
- „Efekt automatyzacji mierzę kosztem na wniosek, odsetkiem spraw niestandardowych i odsetkiem odejść człowieka od rekomendacji. Na ten ostatni jest alert, bo to sygnał dryfu, którego alert techniczny nie widzi.”
- „Marża liczona po cenie zakupu z dnia zamówienia (SCD2), z testem na zmianie ceny w środku okresu.”
