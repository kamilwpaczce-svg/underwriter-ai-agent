# Etap 8 — śledzenie ewaluacji w MLflow (backend: Azure ML)

Cel: każdy przebieg `ewaluacja/uruchom.py` staje się porównywalnym eksperymentem — parametry
(model, prompt, wytyczne), metryki (jakość, koszt, czas) i artefakty w jednym miejscu, zamiast
ręcznego zestawiania plików z `ewaluacja/wyniki/`. Lekcja, która to motywuje: Gemini 13/14 (prompt
etapu 2) vs 11/14 (prompt etapu 5) — wyniki porównywano bez zapisanej wersji promptu.

Backend lokalny (plik/SQLite) do testów i pracy offline; docelowo **workspace Azure ML jako serwer
śledzenia MLflow** (bez compute — przebiegi idą z laptopa).

## Zakres

1. **`ewaluacja/mlflow_log.py`** (nowy) — jedna funkcja publiczna, np.
   `zaloguj_przebieg(parametry: dict, metadane: dict, wiersze: list[dict], artefakty: list[Path], czesciowy: bool) -> str` (zwraca run_id).
   - Eksperyment: `underwriter-agent-ewaluacja` (nadpisywalny zmienną `MLFLOW_EXPERIMENT_NAME`).
   - Tracking URI: standardowo z `MLFLOW_TRACKING_URI`; gdy brak — `sqlite:///<ROOT>/mlruns.db`
     (dodać `mlruns.db`, `mlruns/`, `mlartifacts/` do `.gitignore`).
   - **Parametry:** `dostawca`, `model`, `myslenie` / `reasoning` (to, co faktycznie ustawione),
     `wersja_promptu` = pierwsze 12 znaków SHA-256 treści `agent/instrukcje.py`,
     `wersja_wytycznych` = SHA-256 (12 zn.) pliku `wytyczne/wytyczne_mienie_v1.yaml`,
     `wersja_wzorca` = SHA-256 (12 zn.) posortowanej zawartości `dane/oczekiwane/*.json`,
     `git_commit` (krótki SHA; gdy brak gita lub brudne drzewo — dopisać `-dirty`/`brak`),
     `przypadki` (lista id, przycięta do limitu długości parametru), `limit_tokenow`, `atrapa` (bool).
   - **Metryki:** `przypadki_ok`, `przypadki_lacznie`, `odsetek_ok`, `pola_trafione`, `pola_wszystkie`,
     `odsetek_pol`, `decyzje_llm_ok`, `reguly_llm_ok`, `silnik_na_polach_llm_ok`, `podejrzane_ok`,
     `czas_calkowity_s`, `wywolania_llm`, `tokeny_we`, `tokeny_wy`, oraz gdy są w metadanych:
     `koszt_llm_usd_szacunkowy`, `ocr_stron`, `ocr_wywolania_sieciowe`, `ocr_trafienia_cache`.
     Nazwy kluczy wierszy brać z `ewaluacja/porownanie.py` — nie zgadywać.
   - **Tabela per przypadek:** `mlflow.log_table` (id, typ_ok, pola, decyzja oczekiwana/otrzymana,
     reguły ok, czas, tokeny) — żeby w UI dało się zobaczyć, KTÓRY przypadek się zmienił między przebiegami.
   - **Artefakty:** pliki `.json` i `.md` zapisane przez `_zapisz_wyniki`.
   - **Tagi:** `czesciowy=true/false` (przebieg przerwany bezpiecznikiem tokenów — taki przebieg NIE
     jest porównywalny z pełnym; musi to być widoczne), `zrodlo=uruchom` lub `zrodlo=import`.
2. **`ewaluacja/uruchom.py`** — flagi:
   - `--mlflow` — po zapisaniu plików wyników wywołaj `zaloguj_przebieg`. Bez flagi zachowanie
     dokładnie jak dziś (istniejące testy bez zmian).
   - `--mlflow-trace` (implikuje `--mlflow`) — `mlflow.langchain.autolog()` przed budową grafu, żeby
     przebieg grafu LangGraph i wywołania modeli (AzureChatOpenAI / ChatGoogleGenerativeAI) trafiły
     jako ślady (traces) powiązane z runem. Sprawdź w dokumentacji MLflow (context7), jak w zainstalowanej
     wersji wiąże się ślady z aktywnym runem, i zrób to poprawnie.
   - **Kolejność i błędy:** najpierw pliki na dysk (jak dziś), POTEM MLflow. Gdy logowanie do MLflow
     się nie uda — wypisz na stderr `BLAD: MLflow: <przyczyna>` i zwróć **kod 5** (pliki zostają).
     Żadnego cichego `except: pass` — wynik „exit 0, a runu nie ma” jest niedopuszczalny.
   - Przebieg przerwany bezpiecznikiem tokenów (dzisiejszy `break`) → `czesciowy=True`.
3. **`ewaluacja/import_historii.py`** (nowy) — jednorazowy import istniejących
   `ewaluacja/wyniki/*.json` (bez `archiwum_wzorzec_v1/`) jako runów z tagiem `zrodlo=import`.
   - Czas startu runu = znacznik z nazwy pliku (`YYYYMMDD-HHMM`).
   - Parametry, których stare pliki nie mają (wersja promptu itp.) → wartość `nieznana`, nie zgadywać.
   - Atrapa (`*_atrapa.json`) → pomiń domyślnie (flaga `--z-atrapa` włącza).
   - Idempotentność: nie importuj drugi raz pliku, który już ma run (tag `plik_zrodlowy`).
4. **Zależności:** `requirements-ewaluacja.txt` (nowy, `-r requirements.txt` + `mlflow` + `azureml-mlflow`),
   przypięte wersje. **NIE dodawać mlflow do `requirements.txt`** — obraz API w Dockerze ma zostać lekki
   (Dockerfile i CI instalują `requirements.txt`). Import `mlflow` tylko wewnątrz `mlflow_log.py`
   i ścieżek `--mlflow`, nigdy na poziomie modułu `uruchom.py`.
   Sprawdź zgodność `azureml-mlflow` z wybraną wersją `mlflow` (pip resolver, import `azureml.mlflow`).
5. **Testy** (`tests/test_mlflow_log.py`), tracking w `tmp_path` (SQLite), zawsze na atrapie, bez sieci:
   - `main(["--atrapa", "--mlflow", "--przypadki", "W01,W02"])` → kod 0; w eksperymencie 1 run;
     parametry `wersja_promptu`, `model`, `atrapa` obecne; metryka `przypadki_lacznie == 2`;
     artefakty `.json` i `.md` obecne; tag `czesciowy == "false"`.
   - Zmiana treści promptu (monkeypatch ścieżki/treści) → inna `wersja_promptu`.
   - Błędny tracking URI (np. schemat nieobsługiwany) → kod 5, komunikat `BLAD: MLflow` na stderr,
     pliki wyników w katalogu wyników nadal zapisane (przekieruj `WYNIKI_DIR` do `tmp_path`).
   - Bezpiecznik tokenów (niski `--limit-tokenow` na atrapie, jeśli atrapa raportuje tokeny; jeśli nie —
     test jednostkowy `zaloguj_przebieg(..., czesciowy=True)`) → tag `czesciowy == "true"`.
   - Import historii: 2 sztuczne pliki json w `tmp_path` → 2 runy; drugi import → nadal 2.
   - Testy pomijane (`pytest.importorskip("mlflow")`), gdy mlflow nie jest zainstalowany — CI instaluje
     tylko `requirements.txt` i ma przejść bez zmian.
6. **README / `docs/ROZWOJ.md`** — krótka sekcja „Śledzenie ewaluacji (MLflow, Azure ML)”: jak uruchomić
   lokalnie (`mlflow ui --backend-store-uri sqlite:///mlruns.db`), jak przełączyć na Azure ML
   (`MLFLOW_TRACKING_URI` z `az ml workspace show`), co jest parametrem, co metryką i dlaczego
   (wersja promptu jako parametr — lekcja 13/14 vs 11/14).

## Poza zakresem

- Tworzenie zasobów Azure (workspace Azure ML) — robi właściciel komendami z sekcji niżej.
- Ewaluacja w CI na prawdziwym modelu (koszt), rejestr modeli, compute Azure ML.
- Zmiany w grafie, promptach, API, froncie.

## Azure ML — workspace (uruchamia właściciel)

```powershell
$AZ = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
& $AZ extension add -n ml
& $AZ ml workspace create -n uw-demo-mlw -g rg-underwriter-demo -l swedencentral
& $AZ ml workspace show -n uw-demo-mlw -g rg-underwriter-demo --query mlflow_tracking_uri -o tsv
```

Workspace tworzy zależne zasoby (Storage, Key Vault, Application Insights). Bez compute koszt to
grosze miesięcznie (magazyn + operacje Key Vault). Uwierzytelnienie: `az login` (DefaultAzureCredential).

## Kryteria akceptacji

- `pytest` — wszystkie dotychczasowe testy przechodzą bez zmian; nowe testy przechodzą przy
  zainstalowanym `requirements-ewaluacja.txt`; bez mlflow są pomijane, nie padają.
- `python ewaluacja/uruchom.py --atrapa --mlflow` → run widoczny w lokalnym MLflow z parametrami,
  metrykami, tabelą i artefaktami.
- `python ewaluacja/import_historii.py` → historyczne przebiegi (Gemini, gpt-5-mini) widoczne jako
  runy; porównanie 13/14 vs 11/14 w UI.
- Z `MLFLOW_TRACKING_URI` Azure ML: ten sam przebieg atrapy widoczny w Azure ML Studio
  (weryfikacja po utworzeniu workspace).
