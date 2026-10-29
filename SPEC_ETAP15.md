# SPEC Etap 15 — model scikit-learn „szkoda do weryfikacji” i MLOps na Azure ML

> **Dla wykonawcy:** obowiązują „Ograniczenia globalne” z wewnętrznego planu etapów (poza repo) (kopia dla agentów:
> (wewnętrzny plan etapów, poza repo)). Gałąź `etap15`. **Commit po każdym zadaniu**
> (wznowienie od ostatniego commita, nie od zera). TDD: najpierw test offline, potem kod.
> Jedno wywołanie agenta = 1–2 zadania. Komendy tworzące zasoby Azure uruchamia właściciel.

**Cel:** pokazać pełny cykl klasycznego MLOps na Azure obok części LLM: dane → pipeline Azure ML
(serverless) → Model Registry z bramką champion/challenger → serwowanie w grafie jako **sygnał
dla człowieka** → monitoring dryfu z alertem przetestowanym w obu stanach.
**Dane są syntetyczne — celem jest cykl MLOps, nie jakość modelu** (zdanie wprost w README i `docs/MLOPS.md`).

## Źródła

- Inwentarz repo 26.10.2026 (agent `-low`): graf `agent/graf.py`, stan `agent/wezly.py:27-47`,
  węzły szkody `agent/wezly_szkody.py`, panel `agent/decyzje_szkody.py:93-113`, testy grafu
  `tests/test_graf_szkody.py` (atrapy `AtrapaSzkody`, `LiczacaWyszukiwarka`), MLflow
  `ewaluacja/mlflow_log.py:192`, Blob `api/magazyn.py`, baza `api/baza.py`, migracje `migracje/versions/`,
  telemetria `obserwowalnosc/telemetria.py`, alert `infra/terraform/main.tf:41`.
- Wzorzec bramki i aliasów: repo `ergonode_kategorie_herbert` (`bramka.py:45`, `serwis/rejestr.py`) —
  **kopiujemy wzorzec, nie importujemy** (osobne repo bez remote).
- Quota Azure ML swedencentral (sprawdzone 26.10): DSv2 0/6, łącznie 0/20 rdzeni (osobna od VM 4 vCPU).

## Decyzje (rozstrzygnięcie decyzji wstępnych 1–6 z planu, właściciel 26.10)

1. **Cechy = tylko to, co graf ma po `sprawdz_polise`** (trening i serwowanie z JEDNEJ funkcji
   `cechy_ze_stanu`): `suma_ubezpieczenia`, `udzial_kwoty` (= `szacowana_kwota / SU`),
   `dni_do_zgloszenia`, `dni_od_poczatku_polisy` (= `data_zdarzenia − okres_od`), `rodzaj_mienia`
   (kategoria), `liczba_zalacznikow`, `szkody_3_lata` (**nowe pole w `dane/polisy.json`**).
   Typ zdarzenia i kanał **odpadają** (brak w danych; wyprowadzanie z tekstu = szum i rozjazd
   trening/serwowanie). Argument: training–serving skew.
2. **Etykieta** z ukrytej reguły w generatorze + szum (logit: wysoki `udzial_kwoty`, szkoda w
   pierwszych 30 dniach polisy, `szkody_3_lata`, opóźnienie zgłoszenia > 14 dni, mało załączników;
   odsetek pozytywnych ~15%). Generator ma parametr `przesuniecie` do wstrzykiwania dryfu.
3. **Model:** `Pipeline(ColumnTransformer + HistGradientBoostingClassifier)`, baseline
   `LogisticRegression`. Metryki: ROC AUC, PR AUC, Brier. Główna metryka bramki: **PR AUC**
   (klasa rzadka).
4. **Pipeline Azure ML (SDK v2 `azure-ai-ml`)**, compute **serverless `Standard_DS2_v2`**, kroki:
   `przygotuj → trenuj → ewaluuj → zarejestruj`. Rejestracja zawsze jako nowa wersja; bramka:
   challenger zostaje championem, gdy `PR AUC ≥ champion − 0,01`; inaczej tag wersji
   `rola=odrzucony` + `powod`. Pierwsza wersja = champion.
   **Wskaźnik championa = tag MODELU `champion=<wersja>`** (zweryfikowane na żywo 26.10: aliasy MLflow
   w Azure ML dają 404 na `/registered-models/alias`; `log_model(registered_model_name=)` i
   `mlflow.register_model` padają na `logged-models`). Rejestracja: `save_model` + `log_artifacts` +
   `MlflowClient.create_model_version(N, source=<artifact_uri>/model, run_id=)`; promocja i rollback =
   jedno nadpisanie `set_registered_model_tag(N, "champion", v)` — dokładnie jeden champion z konstrukcji.
   Tagi wersji `rola` (champion/challenger/odrzucony) + `powod` = historia. Odczyt + zapis tagu to nie
   transakcja → nie puszczać dwóch pipeline'ów naraz. Nie używać `search_registered_models()` (400 „OR”),
   tylko `get_registered_model(N)`. Wariant zapasowy (kroki lokalnie, Azure ML tylko
   jako MLflow + rejestr) — **tylko awaryjnie**, gdy trial odrzuci serverless (procedura: zadanie 3, krok 6).
5. **Serwowanie przez Blob, nie przez rejestr w API.** Skrypt `eksportuj_championa` (lokalnie /
   ręcznie po pipeline) czyta `get_registered_model(N).tags["champion"]`, pobiera `models:/N/<wersja>`, zapisuje do Blob
   `modele/ryzyko_szkody/champion.skops` + `referencja.json` (granice koszy i proporcje do PSI) +
   metadane (wersja, PR AUC, data). API ładuje przy starcie **istniejącym klientem blob** (`api/magazyn.py`).
   Powód: `azureml-mlflow` wymusza `azure-storage-blob ≤ 12.27.1`, API ma 12.31; promocja nie
   wymaga przebudowy obrazu (restart rewizji wystarcza). Format `skops` (nie pickle — bezpieczne ładowanie).
6. **Węzeł `ocen_ryzyko_szkody`** między `sprawdz_polise` a routerem `po_sprawdzeniu_polisy` —
   działa na każdej ścieżce. Wynik w nowym polu stanu `ryzyko_szkody`:
   `{"status": "OK"|"BRAK_DANYCH"|"MODEL_NIEDOSTEPNY", "wynik": float|None, "wersja": str|None, "glowne_cechy": [...]}`.
   Brak polisy (S01) → `BRAK_DANYCH`; brak modelu / błąd ładowania → `MODEL_NIEDOSTEPNY`.
   **Węzeł nigdy nie zmienia decyzji ani trasy** — to sygnał dla likwidatora (AI Act art. 14, Etap 17).
7. **Panel:** `podsumowanie_szkody` dostaje klucz `ryzyko`; frontend — jeden wiersz
   „Sygnał ryzyka: 0,73 (model v3) — do weryfikacji likwidatora” + 2–3 główne cechy; przy statusie
   innym niż OK — tekst statusu, nie puste miejsce.
8. **Wejścia modelu → nowa tabela `wejscia_modelu`** (migracja alembic nr 2): `id`, `wniosek_id`,
   `wersja_modelu`, `cechy` (JSON — tylko liczby i kody), `wynik`, `zrodlo` (`api`|`symulacja`), `utworzono`.
   Zapis w `api/agent_serwis.py` przy REKOMENDACJI, gdy `status == OK`. Bez NIP, nazwisk, opisów.
9. **Job dryfu** = pierwszy Container Apps Job, **Terraform** (`infra/terraform/dryf.tf`), cron
   dzienny 06:00 UTC, ten sam obraz co API, inna komenda (`python -m ryzyko.job_dryfu`). Okno:
   ostatnie 30 dni, min. **200** wierszy; PSI per cecha (10 koszy z `referencja.json`).
   Wynik → span `dryf.przebieg` z atrybutami `uw.dryf.status` (`OK`|`DRYF`|`ZA_MALO_DANYCH`),
   `uw.dryf.n`, `uw.dryf.psi_max`, `uw.dryf.cecha_max`, `uw.dryf.psi.<cecha>`. Brak referencji /
   błąd bazy → span ERROR + exit 1 (**nigdy PSI = 0 z braku danych**).
10. **Alerty (checklista `nadzor-automatu`):**
    - **A „dryf albo awaria joba”** — log query: span `dryf.przebieg` z `psi_max > 0,2` LUB `Success == false` w oknie 25 h → istniejąca action group. Opis alertu zawiera instrukcję naprawy (co sprawdzić, komendy).
    - **B „job się nie wykonał”** — log query: liczba spanów `dryf.przebieg` w oknie 26 h `== 0`.
      Kanał (Azure Monitor) niezależny od joba.
    - **Luka nazwana wprost:** `ZA_MALO_DANYCH` nie wysyła maila — demo nie ma ruchu, alarm byłby
      codzienny i uczyłby ignorowania. Status jest w spanie i w zapytaniu KQL w `docs/MLOPS.md`;
      w produkcji osobny alert „próba za mała N dni z rzędu”.
    - Alerty stanowe (`auto_mitigation_enabled`): jeden mail Fired, potem Resolved — jak Etap 13.
11. **Środowisko pipeline'u:** najpierw próba `azure-ai-ml` w `.venv-ewaluacja` + `pip check`;
    konflikt → `.venv-mlops` (`requirements-mlops.txt`). Środowisko komponentów w Azure ML: obraz
    kuratorowany sklearn albo `environment` z `conda`/pip pinami (sklearn, skops, mlflow, azureml-mlflow, pandas).
    API: do `requirements.txt` dochodzi `scikit-learn`, `skops`, `numpy` (wersje jak w `.venv`), **bez mlflow**.

## Pliki

| plik | rola |
|---|---|
| `ryzyko/__init__.py` | pakiet |
| `ryzyko/cechy.py` | `CECHY`, `cechy_ze_stanu(stan) -> dict \| None` — jedyne źródło cech |
| `ryzyko/generator.py` | `generuj_zbior(n, seed, przesuniecie=None) -> DataFrame` (cechy + `do_weryfikacji`) |
| `ryzyko/model.py` | `zbuduj_pipeline(rodzaj)`, `ocen(model, X, y) -> dict` |
| `ryzyko/bramka.py` | `decyzja(champ, chall, tol=0.01) -> (bool, powod)` |
| `ryzyko/psi.py` | `referencja(df) -> dict`, `psi(ref_cechy, biezace) -> dict` |
| `ryzyko/serwowanie.py` | `ModelRyzyka.z_bloba(magazyn)`, `.ocen(cechy) -> dict` |
| `ryzyko/job_dryfu.py` | `main()` — job Container Apps |
| `pipeline_ml/komponenty/*.py` + `pipeline_ml/uruchom.py` | pipeline SDK v2 |
| `pipeline_ml/eksportuj_championa.py` | rejestr → Blob |
| `pipeline_ml/symuluj_ruch.py` | wiersze `zrodlo='symulacja'` do `wejscia_modelu` (z dryfem / bez) |
| `agent/wezly_szkody.py`, `agent/graf.py`, `agent/wezly.py`, `agent/decyzje_szkody.py` | węzeł, krawędź, pole stanu, klucz panelu |
| `api/baza.py`, `migracje/versions/<nowa>.py`, `api/agent_serwis.py` | tabela + zapis wejść |
| `frontend/…` | wiersz sygnału w panelu |
| `infra/terraform/dryf.tf` | job + 2 alerty |
| `Dockerfile` | `COPY ryzyko/` |
| `tests/test_ryzyko_*.py`, `tests/test_graf_szkody.py` | testy offline |
| `docs/MLOPS.md` | opis cyklu, decyzje, KQL, wyniki testów alertów |

## Zadania

### Zadanie 0: rozpoznanie (DSZ0) — bez kodu produkcyjnego
- [ ] `azure-ai-ml` w `.venv-ewaluacja` + `pip check` → zapisz wynik; konflikt → `.venv-mlops`.
- [ ] Wersje `scikit-learn`, `skops`, `numpy` w `.venv`; czy `skops` ładuje `HistGradientBoostingClassifier` w `Pipeline` (trusted types).
- [ ] Rozmiar obrazu API przed zmianą (`docker image ls`) — do porównania w zadaniu 7.
- [ ] Test dymny serverless: jedno zadanie `command` „echo” na `Standard_DS2_v2` w `uw-demo-mlw` (koszt < 0,01 USD; jeśli klasyfikator blokuje — komenda dla właściciela). Wynik decyduje o wariancie zapasowym.
- [ ] Czy tożsamość `uw-api` ma rolę na kontenerze `modele` w storage (czy trzeba nadać — komenda dla właściciela).

**Wyniki DSZ0 (26.10):**
- `azure-ai-ml` 1.35.2 wymaga `azure-storage-blob` 12.31 → kolizja z `azureml-mlflow` (≤ 12.27.1). Podział:
  **`.venv-mlops`** (Python 3.14, tylko `azure-ai-ml` + `azure-identity`, `pip check` czysty) — wysyłanie pipeline'u;
  **`.venv-ewaluacja`** — `eksportuj_championa` (MLflow); komponenty w chmurze — własne środowisko Azure ML.
- `.venv`: scikit-learn 1.9.1, skops 0.16.0, numpy 2.5.4, scipy 1.18.1, pandas 2.3.3. Skops: zapis/odczyt
  `Pipeline(ColumnTransformer+HGB)` z predykcjami identycznymi; trusted types = `["sklearn.ensemble._hist_gradient_boosting.predictor.TreePredictor"]`.
  **Kuratorowane środowisko `sklearn-1.5` ma inną wersję sklearn** → komponenty na własnym `Environment` z pinem `scikit-learn==1.9.1` + `skops==0.16.0` (ta sama wersja co API).
- Obraz `uw-api:proba` lokalnie: 208 MB treści (924 MB na dysku) — punkt odniesienia.
- Serverless DS2_v2 **działa na trialu**: job `musing_tongue_s77w0z2mz3` COMPLETED (kolejka ~3 min, całość ~4,7 min).
- Storage API `uwdemostxx1`; tożsamość `uw-demo-id` ma Storage Blob Data Contributor na koncie → bez nowej roli.
  Kontenera `modele` brak → właściciel: `az storage container create --name modele --account-name uwdemostxx1 --auth-mode login`.

### Zadanie 1: cechy, polisy, generator (TDD)
- [ ] `szkody_3_lata` w `dane/polisy.json` (10 rekordów, wartości 0–4); testy czytające polisy zielone.
- [ ] `cechy_ze_stanu`: testy — pełny stan → 7 cech; brak polisy → `None`; brak `szacowana_kwota` → `None` (nie 0!); SU = 0 → `None`.
- [ ] `generuj_zbior`: deterministyczny dla seeda, odsetek pozytywnych 10–20%, `przesuniecie` zmienia rozkład wskazanej cechy.

### Zadanie 2: model, bramka, PSI (TDD)
- [ ] `ocen` zwraca `roc_auc`, `pr_auc`, `brier`; HGB > baseline na zbiorze 5000.
- [ ] `decyzja`: równy → promuj; słabszy o 0,02 → odrzuć z powodem; brak championa → promuj.
- [ ] `psi`: te same rozkłady → < 0,1; wstrzyknięty dryf → > 0,2; kategoria nieznana w referencji → osobny kosz, nie wyjątek.

### Zadanie 3: pipeline Azure ML
- [ ] Komponenty jako skrypty z argparse (wejście/wyjście = katalogi) — każdy uruchamialny lokalnie; test offline: łańcuch 4 skryptów na `tmp_path` z lokalnym MLflow (`sqlite`).
- [ ] `uruchom.py`: `@pipeline`, serverless DS2_v2, parametry `seed`, `n`, `rodzaj` (`hgb`|`logreg`|`zepsuty` — etykiety przetasowane, do testu bramki).
- [ ] Bieg 1 (`hgb`) → wersja 1 = `champion`. Bieg 2 (`zepsuty`) → odrzucony, tag wersji `rola=odrzucony` + `powod`, tag modelu `champion` bez zmian. **Bramka w obu stanach na żywo** — zapis ID biegów w `docs/MLOPS.md`.
- [ ] Wariant zapasowy (tylko awaryjnie): te same skrypty lokalnie z `MLFLOW_TRACKING_URI` workspace'u.

### Zadanie 4: eksport i ładowanie (TDD)
- [ ] `eksportuj_championa`: tag modelu `champion` → skops + `referencja.json` + metadane do Blob (test offline na Azurite/atrapie magazynu).
- [ ] `ModelRyzyka.z_bloba`: brak blobu / zły plik → `None` + log (API startuje). Test: wynik z bloba == wynik modelu przed eksportem.

### Zadanie 5: węzeł, panel, zapis wejść (TDD)
- [ ] Węzeł + krawędź; testy: S01 → `BRAK_DANYCH` i trasa bez zmian; model `None` → `MODEL_NIEDOSTEPNY`; OK → wynik w panelu; **decyzja i trasa identyczne z węzłem i bez** (dla wszystkich przypadków istniejących testów).
- [ ] Span węzła bez wartości cech osobowych (tylko status, wersja, wynik).
- [ ] Migracja `wejscia_modelu` + zapis w `agent_serwis`; test integracyjny (marker `integracja`).
- [ ] Wiersz w panelu frontendu (3 stany).

### Zadanie 6: job dryfu + alerty
- [ ] `job_dryfu.main` (TDD): `<200` wierszy → `ZA_MALO_DANYCH`; brak referencji → exit 1 + span ERROR; bez dryfu → `OK`; z dryfem → `DRYF` i `cecha_max`.
- [ ] `dryf.tf`: `azurerm_container_app_job` (schedule `0 6 * * *`, sekrety DB i App Insights jak w `uw-api`) + alerty A i B; `terraform plan` → właściciel `apply`.
- [ ] **Test alertu A w 4 przebiegach:** symulacja bez dryfu → cisza; ponownie → cisza; symulacja z dryfem → mail Fired; czysta symulacja → Resolved. Wiersze `symulacja` sprzątnięte po teście.
- [ ] **Test alertu B:** tymczasowo okno 26 h → 10 min, job wstrzymany → mail; revert okna. Zapis w `docs/MLOPS.md`.
- [ ] Zdublowany bieg tego samego dnia — tylko drugi span, nic nie zapisuje (job tylko czyta).

### Zadanie 7: obraz, wdrożenie, dokumentacja
- [ ] `requirements.txt` + `Dockerfile` (`COPY ryzyko/`); rozmiar obrazu przed/po; `pytest -m "not azure"` zielone.
- [ ] Wdrożenie = scalenie do `main` **po decyzji właściciela**; env `uw-api` przez `az containerapp update` (nie Bicep).
- [ ] `docs/MLOPS.md`, wpis w `docs/ROZWOJ.md`.

## Kryteria akceptacji

- Pipeline Azure ML na serverless z modelem w rejestrze i tagiem modelu `champion=<wersja>`; bramka odrzuciła słabszego challengera (oba stany na żywo).
- Węzeł w grafie z testami offline (3 statusy, trasa i decyzja bez zmian).
- Sygnał widoczny w panelu; wejścia w `wejscia_modelu` bez danych osobowych.
- Job dryfu w Terraform; alert A przetestowany w 4 przebiegach, alert B w stanie chorym; zapis przebiegów.
- Testy offline zielone; koszt etapu zapisany.

## Ryzyka

- Trial odrzuci serverless mimo quoty → wariant zapasowy (zadanie 3).
- `skops` a wersja sklearn w obrazie ≠ wersja w komponencie Azure ML → **ta sama wersja przypięta w obu** (test ładowania w zadaniu 4).
- Rozmiar obrazu API (+ sklearn/numpy/scipy ~100–150 MB) — zmierzyć, zaakceptować albo `scikit-learn` bez extras.
- Job Container Apps potrzebuje sekretów DB — nie duplikować haseł w kodzie TF (referencja do Key Vault / zmienna).
