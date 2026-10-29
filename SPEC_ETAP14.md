# SPEC Etap 14 — ewaluacja RAG szkodowego w Azure AI Foundry

> Specyfikacja wykonawcza do wewnętrznego planu etapów (poza repo) (Etap 14, linie 580–592). Obowiązują
> ograniczenia globalne planu (linie 27–42). Kroki w checkboxach (`- [ ]`). Stan wiedzy:
> 2026-10-20, inwentarz (wewnętrzny plan etapów, poza repo).
> Fakty z dokumentacji mają źródło w nawiasie `[Ź1]…`; czego nie dało się potwierdzić —
> **„do sprawdzenia w zadaniu 0”** (DSZ0).

**Cel:** przebieg ewaluacji 12 przypadków szkodowych Z01–Z12 sędzią LLM (`azure-ai-evaluation`)
widoczny w portalu Foundry i w MLflow pod tym samym kluczem przebiegu + tabela „sędzia LLM vs
metryka deterministyczna” z odpowiedzią, której metryce ufać i dlaczego (Z10).

**Postęp zapisujesz commitami** — jeden commit na zadanie (gałąź `etap14`). Wznowienie od
ostatniego commita, nie od zera.

## Źródła

- [Ź1] PyPI `azure-ai-evaluation`: najnowsza **1.18.9** (wydana 2026-10-12, upload 2026-10-14), `requires_python >=3.9`; zależności m.in. `azure-identity>=1.19`, `azure-core>=1.31`, `azure-storage-blob>=12.19`, `openai>=1.108`, `pandas<3`, `nltk>=3.9.1`, `httpx<1`. Bez `promptflow` (od 1.10.0 domyślny silnik to wewnętrzny `RunSubmitterClient`).
- [Ź2] CHANGELOG `azure-ai-evaluation` (GitHub, `sdk/evaluation/azure-ai-evaluation/CHANGELOG.md`): 1.12.0 — `is_reasoning_model` dla `Groundedness`, `Retrieval`, `Relevance` (+ Coherence/Fluency/Similarity), „for o1/o3 models”; 1.14.0 — poprawka: `GroundednessEvaluator` z `query` nie wysyła już `max_tokens` do modeli rozumujących.
- [Ź3] README pakietu: `azure_ai_project` = **dict** (`subscription_id`, `resource_group_name`, `project_name` — projekt hubowy) **albo string URL** `https://{resource}.services.ai.azure.com/api/projects/{project}` (projekt Foundry).
- [Ź4] Źródło `_evaluate.py` (main): `evaluate(*, data, evaluators, evaluation_name=None, target=None, evaluator_config=None, azure_ai_project: str | AzureAIProject | None, output_path=None, fail_on_evaluator_errors=False, tags=None, **kwargs) -> EvaluationResult` z kluczami `rows`, `metrics`, `studio_url`; kolumny danych trafiają do wierszy jako `inputs.<kolumna>`.
- [Ź5] Źródła ewaluatorów (main): `GroundednessEvaluator(model_config, *, threshold=3, credential=None, **kwargs)`, `_OPTIONAL_PARAMS=["query"]`; `RelevanceEvaluator(model_config, *, credential=None, threshold=3)`; `RetrievalEvaluator(model_config, *, threshold=3, credential=None)`; `ResponseCompletenessEvaluator(model_config, *, threshold=…, credential=None, **kwargs)`; docstring `is_reasoning_model` w pierwszych trzech.
- [Ź6] learn.microsoft.com „Local Evaluation with the Azure AI Evaluation SDK (classic)” (2026-02-25): mapowanie `column_mapping` `${data.kolumna}`; klucze ewaluatorów wymagane przez UI (`groundedness`, `relevance`, `retrieval`); wiersz wyniku `outputs.<alias>.<metryka>`, `_reason`, `_result` (`pass`/`fail`), `_threshold`; `ResponseCompletenessEvaluator` wymaga `ground_truth`, `RetrievalEvaluator` = `query` + `context`; sędzia z listy `gpt-35-turbo / gpt-4 / gpt-4-turbo / gpt-4o / gpt-4o-mini` (lista nie wymienia gpt-5); przed logowaniem do projektu Foundry „create and connect your storage account”, przy Entra rola **Storage Blob Data Owner** dla użytkownika i projektu.
- [Ź7] Terraform Registry `hashicorp/azurerm` — najnowszy **5.10.0** (2026-10-15). Dokumentacja zasobów: `azurerm_cognitive_account` (`kind = "AIServices"`, `project_management_enabled`, `custom_subdomain_name`, `identity`, `local_auth_enabled`), **`azurerm_cognitive_account_project`** (wymaga konta AIServices z `project_management_enabled = true`, tożsamością i subdomeną; atrybut `endpoints`), `azurerm_cognitive_account_connection_entra_id` (`category = "AzureStorageAccount"`, `metadata.ResourceId` wymagane), `azurerm_cognitive_deployment`. `azurerm_ai_foundry_project` = projekt **hubowy (classic), „legacy, not compatible with the new Foundry experience”**.

## Decyzje (rozstrzygnięcie decyzji wstępnych 1–6 z planu)

1. **Ewaluatory:** `GroundednessEvaluator` (query+context+response), `RelevanceEvaluator` (query+response), `RetrievalEvaluator` (query+context) i **`ResponseCompletenessEvaluator`** (response+ground_truth) — czwarty wchodzi, bo tylko on porównuje odpowiedź z oczekiwanym rozstrzygnięciem; trzy pierwsze nie znają prawdy i nie złapią złej decyzji przy poprawnych cytatach (Z10). Lokalnie `evaluate(...)` z `azure_ai_project=<URL projektu Foundry>` [Ź3, Ź4] → przebieg w portalu, `result["studio_url"]`; ten sam wynik do MLflow osobnym runem z tagiem `klucz_przebiegu` = nazwa pliku wyników szkód (np. `20261022-1810_szkody_gpt-5-mini`). `evaluation_name` w Foundry = `szkody-<klucz>`, `tags={"klucz_przebiegu": klucz}`. Chmurowa ewaluacja (`AIProjectClient.evals`, `builtin.*`) świadomie odłożona — wymaga wgrania danych jako datasetu; lokalne `evaluate` daje to samo w portalu przy mniejszej liczbie ruchomych części.
2. **Projekt Foundry = nowe konto `AIServices` + `azurerm_cognitive_account_project` w Terraform (azurerm 5.10, bez `azapi`)** [Ź7]. `azurerm_ai_foundry`/`azurerm_ai_foundry_project` odrzucone (hub classic, legacy). Odrzucona też migracja `uw-demo-aoai-xx1` z `OpenAI` na `AIServices` (provider na to pozwala [Ź7]), bo konto żyje w Bicepie, a pełny deployment Bicepa jest niebezpieczny (ograniczenia globalne). Konto `uw-demo-ai-xx1`, `local_auth_enabled = false` (tylko Entra), projekt `uw-demo-ewaluacja`, region `swedencentral`. Konto i projekt nie mają opłaty stałej — płaci się za wywołania modeli (DSZ0: potwierdzić w kalkulatorze/`az consumption`). Połączenie Storage (wymóg z [Ź6]) jako zasób warunkowy `var.polacz_storage` — włączany dopiero, gdy pierwszy przebieg z `azure_ai_project` padnie na braku magazynu (DSZ0: czy nowy projekt Foundry go wymaga).
3. **Dane:** JSONL budowany z rekordów `porownaj_szkode`, które od tego etapu niosą `query`, `context`, `response`, `ground_truth`, `ocenia_llm` (zadanie 1). `query` = przyczyna + okoliczności + rodzaj mienia + kwota (bez NIP, nazwy ubezpieczonego, adresu, nr polisy); `context` = treść wszystkich `fragmenty_owu` (z dodatkowym zapytaniem); `response` = `decyzja_llm` + uzasadnienia cytatów **przyjętych przez kontrolę cytatów** (odrzucone wyłączone — sędzia ocenia to, co agent przekazał dalej; odrzucenie mierzy `kontrola_odrzucila`) + brakujące dokumenty z `ocena_pokrycia`; `ground_truth` = `ground_truth_sedziego` z pliku oczekiwanego (Z10) albo oczekiwana `decyzja_llm` + `paragrafy_oczekiwane`, plus `uwagi_dla_ewaluacji`. **RODO:** wartości `nip`, `ubezpieczony`, `nr_polisy`, `miejsce.*` z `stan["pola"]` zamieniane na `[ZANONIMIZOWANO]` we wszystkich 4 tekstach (LLM potrafi przepisać nazwę do uzasadnienia). Przypadki bez oceny LLM (reguły/podejrzane, `ocena_pokrycia` puste) **nie idą do JSONL** (9 wierszy, 36 wywołań), a w tabeli rozjazdów mają „n/d” — tabela ma 12 wierszy, średnie sędziego tylko po wierszach ≠ n/d. Stare pliki wyników (bez tych pól) → CLI kończy się kodem 3, potrzebny nowy przebieg szkód.
4. **Sędzia: `gpt-5-mini` na istniejącym `uw-demo-aoai-xx1` z `is_reasoning_model=True`**, Entra (`DefaultAzureCredential`, bez klucza — tak już działa `ModelAzure`). SDK ma parametr od 1.12.0 [Ź2, Ź5], ale dokumentacja opisuje go dla o1/o3 i nie wymienia gpt-5 wśród sędziów [Ź6] → **DSZ0: test jednego wiersza**. Porażka (błąd parametru, pusty wynik, `NaN`) → fallback `gpt-4o-mini` jako `azurerm_cognitive_deployment` na NOWYM koncie AIServices (`var.wdroz_sedziego_4o_mini`), nie na koncie z Bicepa. Zapisane wprost w raporcie: **sędzia gpt-5-mini ocenia gpt-5-mini — ryzyko pobłażliwości tej samej rodziny**; fallback 4o-mini to też OpenAI, więc ryzyko maleje, ale nie znika. Środek zaradczy to tabela z metryką deterministyczną (decyzja 5), nie zmiana sędziego.
5. **Tabela rozjazdów** (zadanie 6): per Z01–Z12 `decyzja_ok`, `cytat_trafiony`, 4 wyniki sędziego (`pass/fail` + liczba; G/Rel/Ret jako osobne kolumny), klasa **wyłącznie z `response_completeness`** (jedyny ewaluator znający prawdę) vs metryka deterministyczna: `zgoda_ok`, `zgoda_blad`, `sedzia_poblazliwy` (sędzia pass, deterministyczna błąd), `sedzia_surowy` (odwrotnie), `n/d`. **Zasada zaufania:** dla decyzji i paragrafów ufamy metryce deterministycznej (jest ground truth z `reguly.py`); sędziemu ufamy w tym, czego deterministyczna nie mierzy — czy uzasadnienie nie zmyśla poza OWU (groundedness) i czy odpowiada na zgłoszenie (relevance). Rozjazd `sedzia_poblazliwy` to argument na rozmowę, nie błąd do naprawy.
6. **Środowisko:** najpierw `.venv-ewaluacja` (Python 3.14.4; tam już `openai 3.28.0`, `azure-core 1.41.0`, `azure-identity 1.26.0`, `azure-storage-blob 12.27.1`, `pandas 2.3.3`, `msrest 0.7.1`, `Jinja2 3.1.6`, `aiohttp 3.14.5`, `httpx 0.28.1` — wszystkie spełniają wymagania [Ź1]; dochodzą głównie `nltk`, `ruamel.yaml`, `pyjwt`). Decyzja z `pip install --dry-run --report` przed instalacją, próba na kopii venv (zadanie 0). Kryterium porażki: `pip check` czerwony albo zmiana wersji `mlflow*`, `azureml-mlflow`, `azure-storage-blob`, `pandas` → `.venv-foundry` (bez MLflow; logowanie do MLflow wtedy z `.venv-ewaluacja` przez `--mlflow-z`, zadanie 5). Pin `azure-ai-evaluation==1.18.9` w `requirements-ewaluacja.txt` albo nowym `requirements-foundry.txt`. Główny `.venv` i CI bez zmian — testy czystych funkcji nie importują SDK.

## Pliki

- Modify: `ewaluacja/szkody.py` — `pola_rag(oczekiwany, stan) -> dict` + 5 kluczy w `porownaj_szkode`; stała `KLUCZE_RAG`
- Modify: `ewaluacja/uruchom.py` (`_main_szkody`) — artefakt JSON dla MLflow **bez** kluczy RAG (`KLUCZE_RAG`); pełny JSON z tekstami zostaje tylko lokalnie w `ewaluacja/wyniki/`
- Modify: `dane/szkody/oczekiwane/Z10.json` — klucz `ground_truth_sedziego` (przegląd p. 4)
- Create: `ewaluacja/foundry.py` — JSONL, ewaluatory, mapowanie kolumn, parsowanie wyniku, tabela rozjazdów
- Create: `ewaluacja/foundry_uruchom.py` — CLI (`--wyniki`, `--projekt`, `--sedzia`, `--bez-rozumowania`, `--mlflow`, `--mlflow-z`)
- Create: `infra/terraform/foundry.tf`; Modify: `infra/terraform/variables.tf`, `outputs.tf`, `README.md`
- Modify: `requirements-ewaluacja.txt` **albo** Create: `requirements-foundry.txt` (wynik zadania 0); Modify: `.gitignore` (`.venv-foundry/`, jeśli powstanie)
- Modify: `docs/ROZWOJ.md` (Etap 14), `SPEC_ETAP14.md` (tabela wyników w zadaniu 6)
- Test: `tests/test_ewaluacja_szkody.py` (dopisane), `tests/test_foundry.py`, `tests/test_infra_foundry.py`

## Interfejsy

- Produces: `ewaluacja.szkody.pola_rag(oczekiwany: dict, stan: dict) -> dict[str, Any]` — klucze `query`, `context`, `response`, `ground_truth`, `ocenia_llm` (= `KLUCZE_RAG`; wartości osobowe zamaskowane); `porownaj_szkode` rozszerza wiersz o te klucze (`tabela_szkod_mlflow` i `raport_md_szkod` bez zmian — nie pokazują tekstów).
- Produces: `ewaluacja.foundry.KLUCZE_JSONL = ("id", "query", "context", "response", "ground_truth", "ocenia_llm")`; `zapisz_jsonl(wiersze: list[dict], sciezka: Path) -> int` (rzuca `BrakPolRag`); `mapowanie_kolumn() -> dict`; `zbuduj_ewaluatory(model_config: dict, credential, rozumujacy: bool) -> dict[str, Callable]`; `oceny_z_wyniku(wynik: dict) -> dict[str, dict]`; `klasyfikuj(det_ok: bool, sedzia_ok: bool | None) -> str`; `tabela_rozjazdow(wiersze: list[dict], oceny: dict[str, dict]) -> list[dict]` (klasa z `response_completeness`); `wiersze_bez_oceny(wiersze, oceny) -> list[str]`; `tabela_mlflow(tabela) -> dict[str, list]`; `raport_rozjazdow_md(tabela: list[dict], klucz: str, studio_url: str | None) -> str`; `metryki_sedziego(tabela: list[dict]) -> dict[str, float]`.
- Produces: `python -m ewaluacja.foundry_uruchom --wyniki ewaluacja/wyniki/<klucz>.json [--projekt URL | --bez-foundry] [--sedzia DEPLOYMENT] [--bez-rozumowania] [--oczekiwane DIR] [--mlflow]` → `ewaluacja/wyniki/<klucz>_sedzia.jsonl` (tylko wiersze `ocenia_llm=True`), `<klucz>_sedzia.json` (`output_path`), `<klucz>_rozjazdy.md` (wszystkie 12 wierszy, n/d dla reguł). `--mlflow-z <klucz>_sedzia.json --wyniki <klucz>.json` = tylko logowanie do MLflow z gotowego wyniku (bez wywołań LLM; `--wyniki` wymagane w tym trybie, sprawdzane w `main`, nie przez `required=True` argparse).
- **Kody wyjścia** (każdy ≠ 0 = przebieg nie liczy się jako wynik):
  - 0 — OK: każdy wiersz z oceną LLM oceniony, liczba wierszy z oceną LLM = liczba oczekiwanych z `decyzja_llm != null`, żaden wiersz nie ma `blad`, przebieg zalogowany w Foundry (albo jawne `--bez-foundry`);
  - 2 — brak konfiguracji: brak endpointu sędziego (`AZURE_EVAL_ENDPOINT`/`AZURE_OPENAI_ENDPOINT`), brak projektu Foundry (`--projekt`/`AZURE_AI_PROJECT_ENDPOINT`) bez `--bez-foundry`, `--mlflow-z` bez `--wyniki`;
  - 3 — plik wyników bez pól RAG (sprzed Etapu 14);
  - 4 — wyjątek `evaluate` (SDK, uprawnienia, sieć);
  - 5 — MLflow niedostępny w tym venv (`ImportError`) albo błąd `zaloguj_przebieg`;
  - 6 — sędzia nie ocenił wiersza z oceną LLM (cicha awaria ewaluatora);
  - 7 — przebieg RAG niepełny: mniej wierszy `ocenia_llm=True` niż oczekiwanych z `decyzja_llm != null` (dziś 9) albo którykolwiek wiersz ma `blad` (graf padł — wszystko `ocenia_llm=False` dałoby inaczej fałszywe 0);
  - 8 — projekt Foundry podany, ale `evaluate` zwrócił pusty `studio_url` (nie zalogowano — fałszywy sukces „widoczne w portalu”).
- Consumes: `porownaj_szkode`, `przypadek_szkody_zgodny`, `wczytaj_oczekiwany_szkody` (`ewaluacja/szkody.py`), `zaloguj_przebieg(parametry, metadane, wiersze, artefakty, czesciowy, zrodlo, czas_startu, tagi_dodatkowe, metryki, tabela: dict[str, list] | None)` (`ewaluacja/mlflow_log.py:206`; `tabela` = kolumny → listy wartości, płaskie skalary), env: `AZURE_EVAL_ENDPOINT` (fallback `AZURE_OPENAI_ENDPOINT`), `AZURE_EVAL_DEPLOYMENT` (domyślna wartość `--sedzia`, fallback `gpt-5-mini`), `AZURE_OPENAI_API_VERSION`, nowy `AZURE_AI_PROJECT_ENDPOINT`. **Wybór (przegląd p. 10):** zmienne `AZURE_EVAL_*` podłączone, nie usunięte — sędzia może siedzieć na innym koncie (fallback 4o-mini na koncie Foundry, decyzja 4) niż RAG.

## Zadania

### Zadanie 0: gałąź, środowisko, rozpoznanie SDK

- [ ] Gałąź: jeśli Etap 13 scalony — `git switch main && git pull && git switch -c etap14`. Jeśli **nie** scalony — `git switch etap13 && git pull && git switch -c etap14` i zapisz w `docs/ROZWOJ.md`, że etap14 trzeba rebase'ować na `main` po scaleniu 13 (`git rebase main` przed PR). Etap 14 dotyka `infra/terraform/` z Etapu 13 — bez niego `foundry.tf` nie ma `versions.tf` ani `data.azurerm_resource_group.rg`.
- [ ] **Decyzja przed instalacją, nie po** (oryginalny `.venv-ewaluacja` nie jest modyfikowany, dopóki decyzja nie zapadnie): `.venv-ewaluacja\Scripts\pip install --dry-run --report $env:TEMP\raport_foundry.json azure-ai-evaluation==1.18.9`, potem w Pythonie z raportu (`install[].metadata.name/version`) lista pakietów, które pip **zmieniłby** — porównaj z `pip freeze` dla `mlflow`, `mlflow-skinny`, `mlflow-tracing`, `azureml-mlflow`, `azure-storage-blob`, `azure-core`, `azure-identity`, `pandas`, `openai`, `httpx`. Dowolna zmiana wersji z tej listy → od razu `.venv-foundry` (krok niżej), bez instalacji w `.venv-ewaluacja`.
- [ ] Raport czysty (tylko nowe pakiety) → **próba na kopii**, nie na oryginale (**wybór przeglądu p. 11** — wycofanie = skasowanie kopii, zero ryzyka dla venv z MLflow): `py -3.14 -m venv .venv-ewaluacja-proba`, `.venv-ewaluacja-proba\Scripts\pip install -r requirements-ewaluacja.txt azure-ai-evaluation==1.18.9`, `pip check`, `python -c "import mlflow, azureml.mlflow, azure.ai.evaluation"`. Zielone → ta sama instalacja w `.venv-ewaluacja` i dopisanie pinu do `requirements-ewaluacja.txt`; kopię usuń (`Remove-Item -Recurse .venv-ewaluacja-proba`; dopisz `.venv-ewaluacja-proba/` do `.gitignore` na czas próby). Czerwone → kopia do kosza i `.venv-foundry`.
- [ ] Wariant `.venv-foundry` (raport z konfliktem albo czerwona kopia): `py -3.14 -m venv .venv-foundry`, `.venv-foundry\Scripts\pip install azure-ai-evaluation==1.18.9 -r requirements.txt` (graf szkód musi się importować — `foundry_uruchom` nie uruchamia grafu, ale `ewaluacja.szkody` importuje `langgraph`), `pip check`; dopisz `.venv-foundry/` do `.gitignore`, utwórz `requirements-foundry.txt` z pinami z `pip freeze` (tylko pakiety bezpośrednie + `azure-ai-evaluation`).
- [ ] **Test jednego wiersza sędziego (koszt < 0,01 USD)** w wybranym venv — skrypt w scratchpadzie, nie w repo: `GroundednessEvaluator(model_config, credential=DefaultAzureCredential(), is_reasoning_model=True)(query=..., context=..., response=...)` na `gpt-5-mini`. Zapisz: czy zwraca `groundedness` jako liczbę, `groundedness_result`, `groundedness_reason`; czy pojawiają się klucze tokenów (`*_prompt_tokens`/`*_completion_tokens` — potrzebne do kosztu); czy `ResponseCompletenessEvaluator` przyjmuje `is_reasoning_model=True` (nie ma go w docstringu [Ź5]). Błąd → decyzja 4, fallback 4o-mini (zadanie 4 z `-var wdroz_sedziego_4o_mini=true`).
- [ ] Sprawdź DSZ0 i wpisz odpowiedzi do sekcji „Do sprawdzenia” na końcu tego pliku: sterowanie współbieżnością `evaluate` (brak `max_workers` w sygnaturze [Ź4] — szukaj w źródle `_batch_run`/env), czy gpt-4o-mini jest jeszcze dostępny do nowych wdrożeń w swedencentral (`& $AZ cognitiveservices model list -l swedencentral -o json`, filtr w Pythonie).
- [ ] `pytest -q -m "not azure"` w `.venv` → zielone (liczba z końca Etapu 13). Commit: `etap14: zadanie 0 - srodowisko azure-ai-evaluation 1.18.9` (pliki requirements / .gitignore).

### Zadanie 1: pola RAG w wynikach szkód (`pola_rag`)

- [ ] **Test (failing)** — dopisz do `tests/test_ewaluacja_szkody.py`:

```python
from ewaluacja.szkody import pola_rag

NIP_TESTOWY = "9524044407"


def _stan_z_polami() -> dict:
    stan = _stan(
        cytaty=[{"paragraf": "4", "ustep": "3", "uzasadnienie": "Zalanie z instalacji tryskaczowej jest objete."}],
        fragmenty=[{"id": "p4u3", "paragraf": 4, "ustep": 3, "tytul": "T", "tresc": "§ 4. Zakres\nust. 3. Zalanie."}],
    )
    stan["pola"] = {
        "nip": NIP_TESTOWY, "ubezpieczony": "Hurtownia Papieru Mazur sp. z o.o.", "nr_polisy": "PL/MSP/2026/0004",
        "miejsce": {"ulica": "ul. Skladowa 8", "kod": "05-500", "miasto": "Piaseczno"},
        "przyczyna": "Zalanie magazynu woda z instalacji tryskaczowej", "okolicznosci": "Tryskacze w nocy.",
        "rodzaj_mienia": "zapasy", "szacowana_kwota": 720000,
    }
    return stan


def test_pola_rag_buduja_cztery_teksty():
    oczekiwany = {**OCZEKIWANY, "decyzja_llm": "POKRYTA", "uwagi_dla_ewaluacji": "Kwota > SU zapasow."}
    rag = pola_rag(oczekiwany, _stan_z_polami())
    assert "tryskaczowej" in rag["query"] and "720000" in rag["query"]
    assert "Zalanie." in rag["context"] and "p4u3" in rag["context"]
    assert rag["response"].startswith("Decyzja: POKRYTA")
    assert "§4 ust. 3" in rag["response"]
    assert "§4 ust. 1" in rag["ground_truth"] and "Kwota > SU" in rag["ground_truth"]
    assert rag["ocenia_llm"] is True


ZAKAZANE = (NIP_TESTOWY, "Hurtownia Papieru Mazur sp. z o.o.", "ul. Skladowa 8", "05-500", "Piaseczno", "PL/MSP/2026/0004")


def test_pola_rag_bez_danych_osobowych():
    """Ograniczenia globalne (RODO): NIP, nazwa ubezpieczonego, adres, nr polisy nie trafiaja do JSONL."""
    rag = pola_rag(OCZEKIWANY, _stan_z_polami())
    tekst = " ".join(str(v) for v in rag.values())
    for zakazane in ZAKAZANE:
        assert zakazane not in tekst


def test_pola_rag_maskuje_dane_w_tekstach_llm():
    """Model moze przepisac nazwe/adres do uzasadnienia, okolicznosci albo fragmentu - maskowanie we wszystkich 4 tekstach."""
    stan = _stan_z_polami()
    stan["pola"]["okolicznosci"] = "Hurtownia Papieru Mazur sp. z o.o. zglosila zalanie w Piaseczno."
    stan["ocena_pokrycia"]["cytaty"][0]["uzasadnienie"] = (
        "Hurtownia Papieru Mazur sp. z o.o. (NIP 9524044407) ma polise PL/MSP/2026/0004, ul. Skladowa 8.")
    stan["fragmenty_owu"][0]["tresc"] += " Piaseczno"
    rag = pola_rag({**OCZEKIWANY, "uwagi_dla_ewaluacji": "Ubezpieczony Hurtownia Papieru Mazur sp. z o.o."}, stan)
    for klucz in ("query", "context", "response", "ground_truth"):
        for zakazane in ZAKAZANE:
            assert zakazane not in rag[klucz], (klucz, zakazane)
    assert "[ZANONIMIZOWANO]" in rag["response"] and "[ZANONIMIZOWANO]" in rag["query"]


def test_pola_rag_pomija_cytaty_odrzucone_przez_kontrole():
    cytat_zly = {"paragraf": "6", "ustep": "1", "uzasadnienie": "spoza kontekstu"}
    stan = _stan_z_polami()
    stan["ocena_pokrycia"]["cytaty"].append(cytat_zly)
    stan["kontrola_cytatow"] = {"ok": False, "powod": "cytat_spoza_kontekstu", "odrzucone": [cytat_zly]}
    rag = pola_rag(OCZEKIWANY, stan)
    assert "§4 ust. 3" in rag["response"] and "§6 ust. 1" not in rag["response"]


def test_pola_rag_bez_oceny_llm():
    stan = _stan_z_polami()
    stan["ocena_pokrycia"] = None
    rag = pola_rag(OCZEKIWANY, stan)
    assert rag["ocenia_llm"] is False
    assert rag["response"]  # tekst zastepczy, nie pusty - evaluate odrzuca puste wejscie


def test_porownaj_szkode_niesie_pola_rag():
    wiersz = porownaj_szkode(OCZEKIWANY, _stan_z_polami())
    assert {"query", "context", "response", "ground_truth", "ocenia_llm"} <= wiersz.keys()


def test_artefakt_mlflow_bez_tekstow_rag(monkeypatch, tmp_path):
    """Przegląd p. 8: JSON idacy do MLflow (Azure ML) nie niesie tekstow RAG; lokalny JSON - tak (sedzia go czyta)."""
    from ewaluacja.szkody import KLUCZE_RAG
    przekazane = {}
    monkeypatch.setattr(uruchom, "WYNIKI_DIR", tmp_path)
    monkeypatch.setattr(uruchom, "zaloguj_przebieg", lambda **kw: przekazane.update(kw) or "run-x", raising=False)
    assert uruchom.main(["--atrapa", "--modul", "szkody", "--mlflow"]) == 0
    lokalny = next(p for p in tmp_path.glob("*_szkody_*.json") if "_mlflow" not in p.name)
    assert set(KLUCZE_RAG) <= json.loads(lokalny.read_text(encoding="utf-8"))["przypadki"][0].keys()
    artefakt = next(p for p in przekazane["artefakty"] if str(p).endswith(".json"))
    for w in json.loads(Path(artefakt).read_text(encoding="utf-8"))["przypadki"]:
        assert not set(KLUCZE_RAG) & w.keys()
```

  (Sposób podmiany `zaloguj_przebieg` dopasuj do tego, jak `uruchom.py` go importuje — leniwie w `_main_szkody` → `monkeypatch.setattr("ewaluacja.mlflow_log.zaloguj_przebieg", ...)`; test istniejący `test_mlflow_run_szkod_ma_tag_i_parametry` pokazuje wzorzec. Bez MLflow w `.venv` — `pytest.importorskip("mlflow")` jak tam.)

- [ ] `pytest tests/test_ewaluacja_szkody.py -q` → 7 FAIL (ImportError).
- [ ] **Implementacja** — `ewaluacja/szkody.py`:

```python
BRAK_OCENY_LLM = "Brak oceny LLM - decyzja z regul (polisa/podejrzane instrukcje)."
BRAK_FRAGMENTOW = "(brak fragmentow OWU)"


def _query(pola: dict) -> str:
    # Etap 14: tylko opis zdarzenia i liczby - bez NIP, ubezpieczonego, adresu, nr polisy (RODO).
    czesci = [f"Zgloszenie szkody: {pola.get('przyczyna') or '-'}."]
    if pola.get("okolicznosci"):
        czesci.append(f"Okolicznosci: {pola['okolicznosci']}")
    czesci.append(f"Rodzaj mienia: {pola.get('rodzaj_mienia') or '-'}, kwota: {pola.get('szacowana_kwota') or '-'} PLN.")
    czesci.append("Czy szkoda jest objeta ochrona wedlug OWU i na jakiej podstawie?")
    return " ".join(czesci)


def _response(ocena: dict, odrzucone: set) -> str:
    # Przeglad p. 14: cytaty odrzucone przez kontrole cytatow NIE wchodza do response - sedzia ocenia
    # to, co agent faktycznie przekazal dalej; odrzucenie liczy metryka deterministyczna (kontrola_odrzucila).
    linie = [f"Decyzja: {ocena.get('decyzja')}."]
    linie += [f"§{c['paragraf']} ust. {c['ustep']}: {c.get('uzasadnienie') or ''}"
              for c in ocena.get("cytaty") or [] if klucz_cytatu(c) not in odrzucone]
    if ocena.get("brakujace_dokumenty"):
        linie.append("Brakujace dokumenty: " + ", ".join(ocena["brakujace_dokumenty"]))
    return "\n".join(linie)


MASKA = "[ZANONIMIZOWANO]"
KLUCZE_RAG = ("query", "context", "response", "ground_truth", "ocenia_llm")


def _wartosci_osobowe(pola: dict) -> list[str]:
    """NIP, ubezpieczony, nr_polisy, miejsce.* - wartosci z tego zgloszenia (najdluzsze pierwsze)."""
    wartosci = [pola.get(k) for k in ("nip", "ubezpieczony", "nr_polisy")]
    wartosci += list((pola.get("miejsce") or {}).values())
    return sorted({str(w).strip() for w in wartosci if w and str(w).strip()}, key=len, reverse=True)


def _maskuj(tekst: str, wartosci: list[str]) -> str:
    for w in wartosci:
        tekst = tekst.replace(w, MASKA)
    return tekst


def pola_rag(oczekiwany: dict, stan: dict) -> dict[str, Any]:
    """Etap 14: teksty do JSONL sedziego (query/context/response/ground_truth).
    Zostaja lokalnie w ewaluacja/wyniki/ (gitignore), nigdy w telemetrii. Wartosci osobowe
    z pol zgloszenia maskowane we WSZYSTKICH tekstach - LLM moze je przepisac do uzasadnienia."""
    pola = stan.get("pola") or {}
    ocena = stan.get("ocena_pokrycia") or {}
    odrzucone = {klucz_cytatu(c) for c in (stan.get("kontrola_cytatow") or {}).get("odrzucone") or []}
    fragmenty = stan.get("fragmenty_owu") or []
    kontekst = "\n\n".join(f"[{f['id']}] {f['tresc']}" for f in fragmenty) or BRAK_FRAGMENTOW
    paragrafy = ", ".join(oczekiwany.get("paragrafy_oczekiwane") or []) or "brak"
    prawda = oczekiwany.get("ground_truth_sedziego") or (
        f"Decyzja: {oczekiwany.get('decyzja_llm') or oczekiwany['decyzja']}. Podstawa: {paragrafy}.")
    if oczekiwany.get("uwagi_dla_ewaluacji"):
        prawda += f" {oczekiwany['uwagi_dla_ewaluacji']}"
    wartosci = _wartosci_osobowe(pola)
    teksty = {
        "query": _query(pola),
        "context": kontekst,
        "response": _response(ocena, odrzucone) if ocena else BRAK_OCENY_LLM,
        "ground_truth": prawda,
    }
    return {**{k: _maskuj(v, wartosci) for k, v in teksty.items()}, "ocenia_llm": bool(ocena)}
```

  i w `porownaj_szkode` przed `return`: `rag = pola_rag(oczekiwany, stan)`, a w słowniku wyniku `**rag,` na końcu. `_query` nadal nie wkleja pól osobowych; maska łapie je dopiero, gdy przyjdą w `okolicznosci`/`przyczyna`.
  **Ground truth Z10 (przegląd p. 4):** w `dane/szkody/oczekiwane/Z10.json` dopisz `"ground_truth_sedziego": "Ocena LLM: POKRYTA; decyzja koncowa po regulach: SKIEROWANIE (S03)."` — w przebiegu 1722 LLM odpowiedział UZUPELNIENIE (powody `['ocena_llm']`), a S03 odpala tylko przy POKRYTA, więc pomyłka LLM to żądanie dokumentów, nie przeoczenie SU. Domyślny szablon (`Decyzja: {decyzja_llm}`) zostaje dla pozostałych; `Pliki` — Modify `dane/szkody/oczekiwane/Z10.json`.
  **`uruchom.py` (przegląd p. 8):** w `_main_szkody` przy `--mlflow` zapisz obok drugi plik `<klucz>_mlflow.json` z `przypadki` = `[{k: v for k, v in w.items() if k not in KLUCZE_RAG} for w in wiersze]` i przekaż do `artefakty` jego zamiast pełnego JSON. `tabela_szkod_mlflow` i `raport_md_szkod` bez zmian (jawna lista kolumn).
- [ ] `pytest tests/test_ewaluacja_szkody.py -q` → zielone; `pytest -q -m "not azure"` → zielone (atrapa `test_main_szkody_na_atrapie_12_na_12` też — JSON wyników po prostu ma więcej kluczy).
- [ ] Commit: `etap14: pola RAG (query/context/response/ground_truth) w wynikach szkod`.

### Zadanie 2: JSONL, mapowanie kolumn, ewaluatory (`ewaluacja/foundry.py`)

- [ ] **Test (failing)** — `tests/test_foundry.py`:

```python
"""Etap 14: ewaluacja sedzia LLM (azure-ai-evaluation) - czesci offline, bez SDK i bez sieci."""

from __future__ import annotations

import json

import pytest

from ewaluacja import foundry


def _wiersz(id_: str, ocenia_llm: bool = True, **nadpisz) -> dict:
    w = {"id": id_, "query": "q", "context": "c", "response": "r", "ground_truth": "g",
         "ocenia_llm": ocenia_llm, "decyzja_ok": True, "cytat_trafiony": True, "_tokeny_we": 1}
    return {**w, **nadpisz}


def test_zapisz_jsonl_tylko_klucze_rag_i_wiersze_z_ocena_llm(tmp_path):
    sciezka = tmp_path / "x_sedzia.jsonl"
    wiersze = [_wiersz("Z01"), _wiersz("Z02"), _wiersz("Z09", ocenia_llm=False)]
    assert foundry.zapisz_jsonl(wiersze, sciezka) == 2  # Z09 (decyzja z regul) nie idzie do sedziego
    linie = [json.loads(l) for l in sciezka.read_text(encoding="utf-8").splitlines()]
    assert [l["id"] for l in linie] == ["Z01", "Z02"]
    assert [set(l) for l in linie] == [set(foundry.KLUCZE_JSONL)] * 2  # bez metryk i tokenow


def test_zapisz_jsonl_stary_plik_wynikow(tmp_path):
    with pytest.raises(foundry.BrakPolRag):
        foundry.zapisz_jsonl([{"id": "Z01", "decyzja_ok": True}], tmp_path / "x.jsonl")


def test_mapowanie_kolumn_zgodne_z_wymaganiami_ewaluatorow():
    m = foundry.mapowanie_kolumn()
    assert set(m) == {"groundedness", "relevance", "retrieval", "response_completeness"}
    assert m["groundedness"]["column_mapping"] == {
        "query": "${data.query}", "context": "${data.context}", "response": "${data.response}"}
    assert set(m["retrieval"]["column_mapping"]) == {"query", "context"}
    assert set(m["response_completeness"]["column_mapping"]) == {"response", "ground_truth"}
```

- [ ] `pytest tests/test_foundry.py -q` → FAIL (brak modułu).
- [ ] **Implementacja** — `ewaluacja/foundry.py` (SDK importowany leniwie, żeby `.venv` i CI działały bez niego):

```python
"""Ewaluacja RAG szkodowego sedzia LLM w Azure AI Foundry (Etap 14).

Czyste funkcje (JSONL, mapowanie, parsowanie, tabela rozjazdow) nie importuja
azure-ai-evaluation - pakiet jest tylko w .venv-ewaluacja/.venv-foundry, nie w CI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

KLUCZE_JSONL = ("id", "query", "context", "response", "ground_truth", "ocenia_llm")
WEJSCIA = {
    "groundedness": ("query", "context", "response"),
    "relevance": ("query", "response"),
    "retrieval": ("query", "context"),
    "response_completeness": ("response", "ground_truth"),
}


class BrakPolRag(ValueError):
    """Plik wynikow sprzed Etapu 14 - brak query/context/response/ground_truth."""


def zapisz_jsonl(wiersze: list[dict], sciezka: Path) -> int:
    """Tylko wiersze z ocena LLM (przeglad p. 6) - wiersze z regul nie maja czego sedziowac (n/d w tabeli)."""
    for w in wiersze:
        brak = [k for k in KLUCZE_JSONL if k not in w]
        if brak:
            raise BrakPolRag(f"{w.get('id')}: brak {brak} - uruchom ponownie --modul szkody (Etap 14).")
    do_sedziego = [w for w in wiersze if w["ocenia_llm"]]
    sciezka.write_text(
        "".join(json.dumps({k: w[k] for k in KLUCZE_JSONL}, ensure_ascii=False) + "\n" for w in do_sedziego),
        encoding="utf-8",
    )
    return len(do_sedziego)


def mapowanie_kolumn() -> dict[str, dict]:
    return {n: {"column_mapping": {k: f"${{data.{k}}}" for k in wejscia}} for n, wejscia in WEJSCIA.items()}


def zbuduj_ewaluatory(model_config: dict, credential, rozumujacy: bool) -> dict[str, Callable]:
    from azure.ai.evaluation import (GroundednessEvaluator, RelevanceEvaluator,
                                     ResponseCompletenessEvaluator, RetrievalEvaluator)
    opcje = {"credential": credential, "is_reasoning_model": rozumujacy}
    return {
        "groundedness": GroundednessEvaluator(model_config, **opcje),
        "relevance": RelevanceEvaluator(model_config, **opcje),
        "retrieval": RetrievalEvaluator(model_config, **opcje),
        # is_reasoning_model nieudokumentowany dla completeness - wynik zadania 0
        "response_completeness": ResponseCompletenessEvaluator(model_config, **opcje),
    }
```

- [ ] `pytest tests/test_foundry.py -q` → zielone. Commit: `etap14: JSONL i ewaluatory azure-ai-evaluation (offline)`.

### Zadanie 3: parsowanie wyniku i tabela rozjazdów

- [ ] **Test (failing)** — dopisz do `tests/test_foundry.py`:

```python
WYNIK = {  # ksztalt z [Z4]/[Z6]: rows z inputs.<kolumna> i outputs.<alias>.<metryka>
    "rows": [
        {"inputs.id": "Z01", **{f"outputs.{n}.{n}": 5.0 for n in foundry.WEJSCIA},
         **{f"outputs.{n}.{n}_result": "pass" for n in foundry.WEJSCIA}},
        {"inputs.id": "Z10", **{f"outputs.{n}.{n}": 4.0 for n in foundry.WEJSCIA},
         **{f"outputs.{n}.{n}_result": "pass" for n in foundry.WEJSCIA}},
        {"inputs.id": "Z11"},  # brak ocen - ewaluator padl albo n/d
    ],
    "metrics": {}, "studio_url": "https://ai.azure.com/x",
}


def test_oceny_z_wyniku():
    oceny = foundry.oceny_z_wyniku(WYNIK)
    assert oceny["Z01"]["groundedness"] == {"wynik": 5.0, "pass": True}
    assert oceny["Z11"] == {}


@pytest.mark.parametrize("det, sedzia, klasa", [
    (True, True, "zgoda_ok"), (False, False, "zgoda_blad"),
    (False, True, "sedzia_poblazliwy"), (True, False, "sedzia_surowy"), (True, None, "n/d"),
])
def test_klasyfikuj(det, sedzia, klasa):
    assert foundry.klasyfikuj(det, sedzia) == klasa


def test_tabela_rozjazdow_z10_poblazliwy():
    wiersze = [_wiersz("Z01"), _wiersz("Z10", decyzja_ok=False), _wiersz("Z11", ocenia_llm=False)]
    tabela = {t["id"]: t for t in foundry.tabela_rozjazdow(wiersze, foundry.oceny_z_wyniku(WYNIK))}
    assert tabela["Z01"]["klasa"] == "zgoda_ok"
    assert tabela["Z10"]["klasa"] == "sedzia_poblazliwy"
    assert tabela["Z11"]["klasa"] == "n/d"


def test_klasa_tylko_z_completeness():
    """Przeglad p. 5: G/Rel/Ret to osobne kolumny; klasa rozjazdu = completeness vs metryka deterministyczna."""
    wynik = {"rows": [{"inputs.id": "Z10",
                       **{f"outputs.{n}.{n}": 2.0 for n in foundry.WEJSCIA},
                       **{f"outputs.{n}.{n}_result": "fail" for n in foundry.WEJSCIA},
                       "outputs.response_completeness.response_completeness_result": "pass"}]}
    t = foundry.tabela_rozjazdow([_wiersz("Z10", decyzja_ok=False)], foundry.oceny_z_wyniku(wynik))[0]
    assert t["klasa"] == "sedzia_poblazliwy"
    assert t["groundedness"] == {"wynik": 2.0, "pass": False}  # kolumna zostaje w tabeli


def test_brak_oceny_przy_ocenie_llm_to_awaria():
    """Cicha awaria: ewaluator padl (fail_on_evaluator_errors=False daje pusty wiersz)."""
    wiersze = [_wiersz("Z11", ocenia_llm=True)]
    assert foundry.wiersze_bez_oceny(wiersze, foundry.oceny_z_wyniku(WYNIK)) == ["Z11"]


def test_metryki_sedziego_i_raport():
    wiersze = [_wiersz("Z01"), _wiersz("Z10", decyzja_ok=False)]
    tabela = foundry.tabela_rozjazdow(wiersze, foundry.oceny_z_wyniku(WYNIK))
    m = foundry.metryki_sedziego(tabela)
    assert m["sedzia_groundedness"] == pytest.approx(4.5)
    assert m["sedzia_rozjazdy"] == 1.0
    md = foundry.raport_rozjazdow_md(tabela, "20261022-1810_szkody_gpt-5-mini", WYNIK["studio_url"])
    assert "Z10" in md and "sedzia_poblazliwy" in md and "https://ai.azure.com/x" in md
```

- [ ] FAIL → **implementacja** w `ewaluacja/foundry.py`:

```python
def oceny_z_wyniku(wynik: dict) -> dict[str, dict]:
    oceny: dict[str, dict] = {}
    for i, wiersz in enumerate(wynik.get("rows") or []):
        id_ = wiersz.get("inputs.id") or f"wiersz{i}"
        oceny[id_] = {}
        for n in WEJSCIA:
            liczba = wiersz.get(f"outputs.{n}.{n}")
            if isinstance(liczba, (int, float)) and liczba == liczba:  # NaN != NaN
                oceny[id_][n] = {"wynik": float(liczba), "pass": wiersz.get(f"outputs.{n}.{n}_result") == "pass"}
    return oceny


def klasyfikuj(det_ok: bool, sedzia_ok: bool | None) -> str:
    if sedzia_ok is None:
        return "n/d"
    if det_ok == sedzia_ok:
        return "zgoda_ok" if det_ok else "zgoda_blad"
    return "sedzia_poblazliwy" if sedzia_ok else "sedzia_surowy"


def wiersze_bez_oceny(wiersze: list[dict], oceny: dict[str, dict]) -> list[str]:
    return [w["id"] for w in wiersze if w["ocenia_llm"] and len(oceny.get(w["id"]) or {}) < len(WEJSCIA)]


KLASA_Z = "response_completeness"  # jedyny ewaluator porownujacy z ground_truth (przeglad p. 5)


def tabela_rozjazdow(wiersze: list[dict], oceny: dict[str, dict]) -> list[dict]:
    """Wszystkie wiersze (12), takze n/d - JSONL ma tylko ocenia_llm, tabela pokazuje calosc."""
    tabela = []
    for w in wiersze:
        o = oceny.get(w["id"]) or {}
        sedzia_ok = o[KLASA_Z]["pass"] if (w["ocenia_llm"] and KLASA_Z in o) else None
        det_ok = bool(w["decyzja_ok"]) and w.get("cytat_trafiony") is not False
        tabela.append({"id": w["id"], "decyzja_ok": w["decyzja_ok"], "cytat_trafiony": w.get("cytat_trafiony"),
                       **{n: o.get(n) for n in WEJSCIA}, "klasa": klasyfikuj(det_ok, sedzia_ok)})
    return tabela
```

  plus `metryki_sedziego` (średnia `wynik` per ewaluator **tylko po wierszach z klasą ≠ `n/d`** → `sedzia_<nazwa>`, `sedzia_rozjazdy` = liczba klas `sedzia_*`, `sedzia_ocenione` = liczba wierszy ≠ n/d; tabela dla MLflow — `tabela_mlflow(tabela) -> dict[str, list]` z płaskimi kolumnami `id`, `klasa`, `decyzja_ok`, `cytat_trafiony`, `<ewaluator>` = liczba albo `None`, `<ewaluator>_pass` = bool albo `None`; test: `set(tabela_mlflow(t)) ⊇ {"id", "klasa", "groundedness", "groundedness_pass"}` i wszystkie listy równej długości) i `raport_rozjazdow_md` (nagłówek z kluczem i `studio_url`, tabela Markdown `ID | decyzja_ok | cytat | G | Rel | Ret | Compl | klasa`, komórka `5.0 pass`/`2.0 FAIL`/`-`).
- [ ] `pytest tests/test_foundry.py -q` → zielone; `pytest -q -m "not azure"` → zielone. Commit: `etap14: tabela rozjazdow sedzia LLM vs metryka deterministyczna`.

### Zadanie 4: zasoby Azure (Terraform) — komendy dla właściciela

- [ ] **Test (failing)** — `tests/test_infra_foundry.py` (tekstowy, jak testy infra Etapu 13):

```python
"""Etap 14: projekt Foundry w Terraform - nowe konto AIServices, nie hub classic."""

import re
from pathlib import Path

TF = (Path(__file__).resolve().parent.parent / "infra" / "terraform" / "foundry.tf").read_text(encoding="utf-8")


def _jest(wzorzec: str) -> bool:
    # terraform fmt wyrownuje "=" spacjami - literalne asserty pekaja po fmt (przeglad p. 3)
    return re.search(wzorzec, TF) is not None


def test_konto_aiservices_z_projektem():
    assert _jest(r'\bkind\s+=\s+"AIServices"')
    assert _jest(r"\bproject_management_enabled\s+=\s+true\b")
    assert 'resource "azurerm_cognitive_account_project"' in TF
    assert _jest(r"\blocal_auth_enabled\s+=\s+false\b")


def test_bez_huba_classic_i_bez_ruszania_konta_z_bicepa():
    assert "azurerm_ai_foundry" not in TF
    assert "uw-demo-aoai-xx1" not in TF


def test_sedzia_4o_mini_i_storage_tylko_warunkowo():
    assert len(re.findall(r"\bcount\s+=\s+var\.wdroz_sedziego_4o_mini\s+\?\s+1\s+:\s+0", TF)) == 1
    # polaczenie + data storage + 2 role Storage Blob Data Owner
    assert len(re.findall(r"\bcount\s+=\s+var\.polacz_storage\s+\?\s+1\s+:\s+0", TF)) == 4


def test_role_storage_dla_wlasciciela_i_projektu():
    assert _jest(r"principal_id\s+=\s+azurerm_cognitive_account_project\.ewaluacja\.identity\[0\]\.principal_id")
    assert len(re.findall(r'role_definition_name\s+=\s+"Storage Blob Data Owner"', TF)) == 2
```

- [ ] **Implementacja** — `infra/terraform/foundry.tf`:

```hcl
// Etap 14 - projekt Microsoft Foundry (nowe doswiadczenie, nie hub classic) do logowania
// ewaluacji sedziego LLM. Konto AIServices bez kluczy (tylko Entra). Sedzia domyslnie
// gpt-5-mini na istniejacym koncie z Bicepa - tu tylko fallback 4o-mini (warunkowo).
resource "azurerm_cognitive_account" "foundry" {
  name                       = var.foundry_konto
  location                   = data.azurerm_resource_group.rg.location
  resource_group_name        = data.azurerm_resource_group.rg.name
  kind                       = "AIServices"
  sku_name                   = "S0"
  project_management_enabled = true
  custom_subdomain_name      = var.foundry_konto
  local_auth_enabled         = false

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_cognitive_account_project" "ewaluacja" {
  name                 = var.foundry_projekt
  cognitive_account_id = azurerm_cognitive_account.foundry.id
  location             = data.azurerm_resource_group.rg.location
  display_name         = "Underwriter - ewaluacja szkod"

  identity {
    type = "SystemAssigned"
  }
}

data "azurerm_client_config" "biezacy" {}

resource "azurerm_role_assignment" "wlasciciel_ai_user" {
  scope                = azurerm_cognitive_account.foundry.id
  role_definition_name = "Azure AI User" // DSZ0: rola wystarczajaca do zapisu wynikow evaluate
  principal_id         = data.azurerm_client_config.biezacy.object_id
}

resource "azurerm_cognitive_deployment" "sedzia_4o_mini" {
  count                = var.wdroz_sedziego_4o_mini ? 1 : 0
  name                 = "gpt-4o-mini"
  cognitive_account_id = azurerm_cognitive_account.foundry.id
  model {
    format  = "OpenAI"
    name    = "gpt-4o-mini"
    version = "2024-07-18" // DSZ0: dostepnosc w swedencentral / data wycofania
  }
  sku {
    name     = "GlobalStandard"
    capacity = 50 // tys. TPM; trial ma limit 200 dla 4o-mini
  }
}

data "azurerm_storage_account" "uw" {
  count               = var.polacz_storage ? 1 : 0
  name                = var.storage_konto
  resource_group_name = data.azurerm_resource_group.rg.name
}

resource "azurerm_cognitive_account_connection_entra_id" "storage" {
  count                = var.polacz_storage ? 1 : 0
  name                 = "uw-storage-ewaluacja"
  cognitive_account_id = azurerm_cognitive_account.foundry.id
  category             = "AzureStorageAccount"
  target               = data.azurerm_storage_account.uw[0].primary_blob_endpoint
  metadata = {
    ResourceId = data.azurerm_storage_account.uw[0].id
  }
}

// [Z6]: evaluate z projektem wymaga Storage Blob Data Owner dla uzytkownika i tozsamosci projektu.
resource "azurerm_role_assignment" "storage_wlasciciel" {
  count                = var.polacz_storage ? 1 : 0
  scope                = data.azurerm_storage_account.uw[0].id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = data.azurerm_client_config.biezacy.object_id
}

resource "azurerm_role_assignment" "storage_projekt" {
  count                = var.polacz_storage ? 1 : 0
  scope                = data.azurerm_storage_account.uw[0].id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = azurerm_cognitive_account_project.ewaluacja.identity[0].principal_id
}
```

  `variables.tf`: `foundry_konto` (`"uw-demo-ai-xx1"`), `foundry_projekt` (`"uw-demo-ewaluacja"`), `storage_konto` (`"uwdemostxx1"`), `wdroz_sedziego_4o_mini` (bool, `false`), `polacz_storage` (bool, `false`). `outputs.tf`: `foundry_projekt_endpoint = "https://${var.foundry_konto}.services.ai.azure.com/api/projects/${var.foundry_projekt}"` (format z [Ź3]; porównaj z atrybutem `azurerm_cognitive_account_project.ewaluacja.endpoints` po apply — DSZ0 nazwa klucza w mapie).
- [ ] `pytest tests/test_infra_foundry.py -q` → zielone; `terraform fmt -check` i `terraform init -backend=false && terraform validate` w `infra/terraform/` → OK. Commit: `etap14: projekt Foundry (AIServices + project) w Terraform`.
- [ ] **Komendy dla właściciela (zasoby tworzy właściciel, koszt zapowiedziany):** konto AIServices S0 i projekt — 0 USD stałego kosztu (płatne wywołania; DSZ0); przypisanie roli — 0 USD; fallback 4o-mini — płatny wyłącznie za tokeny; połączenie Storage — 0 USD (blob z wynikami ewaluacji: groszowe kwoty). **Bez upgrade'u trialu**, `spendingLimit On`.

```powershell
cd infra\terraform
terraform init -backend-config=backend.hcl   # plik z Etapu 13 (README)
terraform plan -out etap14.tfplan            # oczekiwane: +3 zasoby (konto, projekt, rola), 0 change, 0 destroy
terraform apply etap14.tfplan
terraform output -raw foundry_projekt_endpoint
```

  Jeśli `plan` pokazuje jakąkolwiek zmianę/usunięcie zasobów Etapu 13 — **stop**, nie apply. Ustaw `$env:AZURE_AI_PROJECT_ENDPOINT` na wynik `output`.

### Zadanie 5: CLI `ewaluacja/foundry_uruchom.py`

- [ ] **Test (failing)** — dopisz do `tests/test_foundry.py` (bez sieci: `uruchom_evaluate` podmieniony). Import na **górze** pliku (E402, przegląd p. 15): `from ewaluacja import foundry, foundry_uruchom` zamiast `from ewaluacja import foundry`; na górze też `from pathlib import Path`.

```python
PROJEKT = ["--projekt", "https://p/api/projects/e"]


def _plik_wynikow(tmp_path, wiersze) -> Path:
    p = tmp_path / "20261022-1810_szkody_gpt-5-mini.json"
    p.write_text(json.dumps({"model": "gpt-5-mini", "modul": "szkody", "metadane": {}, "przypadki": wiersze}),
                 encoding="utf-8")
    return p


def _oczekiwane(tmp_path, ids_llm, ids_reguly=()) -> list[str]:
    katalog = tmp_path / "oczekiwane"
    katalog.mkdir(exist_ok=True)
    for id_ in ids_llm:
        (katalog / f"{id_}.json").write_text(json.dumps({"id": id_, "decyzja_llm": "POKRYTA"}), encoding="utf-8")
    for id_ in ids_reguly:
        (katalog / f"{id_}.json").write_text(json.dumps({"id": id_, "decyzja_llm": None}), encoding="utf-8")
    return ["--oczekiwane", str(katalog)]


@pytest.fixture(autouse=True)
def _bez_sdk(monkeypatch):
    # CI/.venv nie ma azure-ai-evaluation - ewaluatory zastepcze, evaluate podmieniany w testach
    monkeypatch.setattr(foundry_uruchom, "_ewaluatory", lambda *a: {})
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://x")
    monkeypatch.delenv("AZURE_EVAL_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_PROJECT_ENDPOINT", raising=False)


def _evaluate_zwraca(monkeypatch, wynik, przekazane=None):
    def falszywy(**kw):
        (przekazane if przekazane is not None else {}).update(kw)
        return wynik
    monkeypatch.setattr(foundry_uruchom, "uruchom_evaluate", falszywy)


def test_cli_stary_plik_kod_3(tmp_path):
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [{"id": "Z01"}])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 3


def test_cli_brak_endpointu_kod_2(tmp_path, monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT")
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 2


def test_cli_brak_projektu_kod_2_chyba_ze_bez_foundry(tmp_path, monkeypatch):
    _evaluate_zwraca(monkeypatch, WYNIK | {"studio_url": None})
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 2
    assert foundry_uruchom.main([*args, "--bez-foundry"]) == 0


def test_cli_projekt_bez_studio_url_kod_8(tmp_path, monkeypatch):
    _evaluate_zwraca(monkeypatch, WYNIK | {"studio_url": ""})
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 8


def test_cli_graf_padl_wszedzie_kod_7(tmp_path, monkeypatch):
    """Graf padl: wszystkie wiersze ocenia_llm=False i blad - bez kodu 7 bylby fałszywy sukces (0 wierszy do sedziego)."""
    _evaluate_zwraca(monkeypatch, {"rows": [], "metrics": {}, "studio_url": "https://ai.azure.com/x"})
    wiersze = [_wiersz(i, ocenia_llm=False, blad="Timeout") for i in ("Z01", "Z09")]
    args = ["--wyniki", str(_plik_wynikow(tmp_path, wiersze)), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"], ["Z09"])]
    assert foundry_uruchom.main(args) == 7


def test_cli_mniej_ocen_llm_niz_oczekiwanych_kod_7(tmp_path, monkeypatch):
    _evaluate_zwraca(monkeypatch, WYNIK)
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01"), _wiersz("Z10", ocenia_llm=False)])),
            *PROJEKT, *_oczekiwane(tmp_path, ["Z01", "Z10"])]
    assert foundry_uruchom.main(args) == 7


def test_cli_blad_w_jednym_wierszu_kod_7(tmp_path, monkeypatch):
    _evaluate_zwraca(monkeypatch, WYNIK)
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01", blad="RateLimit")])),
            *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 7


def test_cli_pusta_ocena_kod_6(tmp_path, monkeypatch):
    _evaluate_zwraca(monkeypatch, {"rows": [{"inputs.id": "Z01"}], "metrics": {}, "studio_url": "https://ai.azure.com/x"})
    args = ["--wyniki", str(_plik_wynikow(tmp_path, [_wiersz("Z01")])), *PROJEKT, *_oczekiwane(tmp_path, ["Z01"])]
    assert foundry_uruchom.main(args) == 6


def test_cli_mlflow_z_wymaga_wynikow(tmp_path):
    assert foundry_uruchom.main(["--mlflow-z", str(tmp_path / "x_sedzia.json")]) == 2


def test_cli_zapisuje_jsonl_i_raport(tmp_path, monkeypatch):
    przekazane = {}
    _evaluate_zwraca(monkeypatch, WYNIK, przekazane)
    plik = _plik_wynikow(tmp_path, [_wiersz("Z01"), _wiersz("Z10", decyzja_ok=False), _wiersz("Z11", ocenia_llm=False)])
    assert foundry_uruchom.main(["--wyniki", str(plik), *PROJEKT, *_oczekiwane(tmp_path, ["Z01", "Z10"], ["Z11"])]) == 0
    assert przekazane["evaluation_name"] == "szkody-20261022-1810_szkody_gpt-5-mini"
    assert przekazane["tags"] == {"klucz_przebiegu": "20261022-1810_szkody_gpt-5-mini"}
    assert przekazane["azure_ai_project"] == "https://p/api/projects/e"
    jsonl = (tmp_path / "20261022-1810_szkody_gpt-5-mini_sedzia.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(jsonl) == 2  # Z11 (reguly) poza sedzia
    md = (tmp_path / "20261022-1810_szkody_gpt-5-mini_rozjazdy.md").read_text(encoding="utf-8")
    assert "sedzia_poblazliwy" in md and "Z11" in md  # tabela pelna, n/d dla regul
```

- [ ] FAIL → **implementacja** (klucz z `Path(args.wyniki).stem`, pliki obok wyników; `--wyniki` w argparse **bez** `required=True`; `--sedzia` z `default=os.environ.get("AZURE_EVAL_DEPLOYMENT", "gpt-5-mini")`; `--oczekiwane` z domyślnym `dane/szkody/oczekiwane`; kluczowy fragment):

```python
def uruchom_evaluate(**kwargs) -> dict:
    from azure.ai.evaluation import evaluate
    return evaluate(**kwargs)


def _blad(tekst: str, kod: int) -> int:
    print(f"BLAD: {tekst}", file=sys.stderr)
    return kod


def _oczekiwane_z_llm(katalog: Path) -> set[str]:
    """Przypadki, w ktorych graf MUSI dojsc do oceny LLM (decyzja_llm != null) - dzis 9 z 12."""
    return {p.stem for p in katalog.glob("*.json")
            if json.loads(p.read_text(encoding="utf-8")).get("decyzja_llm") is not None}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.wyniki:
        return _blad("--wyniki wymagane (takze z --mlflow-z: tabela potrzebuje decyzja_ok).", 2)
    if args.mlflow_z:
        return _tylko_mlflow(Path(args.mlflow_z), Path(args.wyniki))
    sciezka = Path(args.wyniki)
    dane = json.loads(sciezka.read_text(encoding="utf-8"))
    klucz, wiersze = sciezka.stem, dane["przypadki"]
    jsonl = sciezka.with_name(f"{klucz}_sedzia.jsonl")
    try:
        foundry.zapisz_jsonl(wiersze, jsonl)
    except foundry.BrakPolRag as e:
        return _blad(str(e), 3)
    z_llm = {w["id"] for w in wiersze if w["ocenia_llm"]}
    oczekiwane = _oczekiwane_z_llm(Path(args.oczekiwane))
    bledy = [w["id"] for w in wiersze if w.get("blad")]
    if len(z_llm) < len(oczekiwane) or bledy:  # graf padl: 0 wierszy do sedziego != "wszystko OK"
        return _blad(f"przebieg RAG niepelny: ocena LLM w {len(z_llm)}/{len(oczekiwane)} "
                     f"(brak: {sorted(oczekiwane - z_llm)}), blad w {bledy}.", 7)
    endpoint = os.environ.get("AZURE_EVAL_ENDPOINT") or os.environ.get("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        return _blad("brak AZURE_EVAL_ENDPOINT/AZURE_OPENAI_ENDPOINT (sedzia).", 2)
    projekt = None if args.bez_foundry else (args.projekt or os.environ.get("AZURE_AI_PROJECT_ENDPOINT"))
    if not projekt and not args.bez_foundry:
        return _blad("brak projektu Foundry (--projekt / AZURE_AI_PROJECT_ENDPOINT); bez logowania: --bez-foundry.", 2)
    model_config = {"azure_endpoint": endpoint, "azure_deployment": args.sedzia,
                    "api_version": os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")}
    try:
        wynik = uruchom_evaluate(
            data=str(jsonl), evaluators=_ewaluatory(model_config, not args.bez_rozumowania),
            evaluator_config=foundry.mapowanie_kolumn(), evaluation_name=f"szkody-{klucz}",
            azure_ai_project=projekt,
            output_path=str(sciezka.with_name(f"{klucz}_sedzia.json")), tags={"klucz_przebiegu": klucz},
        )
    except Exception as e:  # blad SDK/uprawnien - nie wynik modelu
        return _blad(f"evaluate: {e}", 4)
    oceny = foundry.oceny_z_wyniku(wynik)
    brak = foundry.wiersze_bez_oceny(wiersze, oceny)
    if brak:  # pusty wynik != wynik zerowy
        return _blad(f"sedzia nie ocenil {brak} - sprawdz _sedzia.json (kolumny *_reason/bledy).", 6)
    tabela = foundry.tabela_rozjazdow(wiersze, oceny)
    studio_url = wynik.get("studio_url")
    sciezka.with_name(f"{klucz}_rozjazdy.md").write_text(
        foundry.raport_rozjazdow_md(tabela, klucz, studio_url), encoding="utf-8")
    if projekt and not studio_url:  # raport juz zapisany - do diagnozy
        return _blad("projekt podany, ale evaluate nie zwrocil studio_url - przebieg NIE jest w Foundry.", 8)
    print(f"Foundry: {studio_url or 'pominieto (--bez-foundry)'}")
    return _mlflow(args, klucz, tabela, sciezka) if args.mlflow else 0
```

  `_ewaluatory` = `foundry.zbuduj_ewaluatory(model_config, DefaultAzureCredential(), rozumujacy)` (import leniwy; w testach podmieniany fixturą `_bez_sdk`). `_tylko_mlflow(sedzia_json, wyniki)` odtwarza `oceny` z `_sedzia.json` (`oceny_z_wyniku`) i `tabela` z `wyniki`. `_mlflow`/`_tylko_mlflow`: leniwy import `zaloguj_przebieg`; `ImportError` albo wyjątek logowania → komunikat „uruchom w .venv-ewaluacja: `python -m ewaluacja.foundry_uruchom --mlflow-z <klucz>_sedzia.json --wyniki <klucz>.json`” i kod 5; `tabela=foundry.tabela_mlflow(tabela)` (`dict[str, list]`, płaskie wartości — nie słowniki `{"wynik", "pass"}`). Run MLflow: `zrodlo="foundry"`, `tagi_dodatkowe={"modul": "szkody-sedzia", "klucz_przebiegu": klucz, "foundry_url": studio_url or "-"}`, `metryki=foundry.metryki_sedziego(tabela)`, artefakty: `_sedzia.json`, `_rozjazdy.md` (**bez** `_sedzia.jsonl` w MLflow Azure ML? — dane fikcyjne, dopuszczalne; decyzja: JSONL też jako artefakt, bo to wejście przebiegu; to magazyn ewaluacji, nie telemetria).
- [ ] `pytest -q -m "not azure"` → zielone. Commit: `etap14: CLI foundry_uruchom (evaluate + Foundry + MLflow)`.

### Zadanie 6: przebieg na żywo, koszt, tabela rozjazdów

- [ ] Nowy przebieg szkód (pola RAG): `.venv-ewaluacja\Scripts\python ewaluacja\uruchom.py --modul szkody --dostawca azure --mlflow` (koszt ~0,04 USD wg 15.10). Zanotuj klucz (`<YYYYMMDD-HHMM>_szkody_gpt-5-mini`).
- [ ] Sędzia: `<venv>\Scripts\python -m ewaluacja.foundry_uruchom --wyniki ewaluacja\wyniki\<klucz>.json --mlflow` (z `.venv-foundry` → potem `--mlflow-z <klucz>_sedzia.json --wyniki <klucz>.json` z `.venv-ewaluacja`). **Zapowiedziany koszt sędziego:** 9 wierszy z oceną LLM × 4 ewaluatory = 36 wywołań (Z09, Z11, Z12 — decyzja z reguł, poza JSONL); szacunek ~3k tokenów WE i ~1,5k WY (rozumowanie) na wywołanie → 0,108 M × 0,25 + 0,054 M × 2,00 ≈ **0,14 USD** (cennik z `ewaluacja/uruchom.py:62-65`, „do weryfikacji”). Bezpiecznik: jeśli po 1. przebiegu koszt > 0,50 USD — nie powtarzać.
- [ ] Sprawdź oba stany „widoczności”: (a) w portalu Foundry przebieg `szkody-<klucz>` z 4 metrykami i 9 wierszami; (b) w MLflow run z tagiem `klucz_przebiegu=<klucz>` i metrykami `sedzia_*`. Kod ≠ 0 → nie wpisuj wyniku, diagnozuj.
- [ ] Koszt rzeczywisty: tokeny z kolumn `*_prompt_tokens`/`*_completion_tokens` w `_sedzia.json` (jeśli są — DSZ0), inaczej metryka `ProcessedPromptTokens`/`GeneratedTokens` wdrożenia za okno przebiegu (`az monitor metrics list ... -o json`). Wpisz do `docs/ROZWOJ.md`.
- [ ] Opcjonalnie (≈0,14 USD): drugi przebieg sędziego na **tym samym** JSONL → stabilność sędziego (ile klas się zmieniło). Bez tego rozjazd 1 przypadku nie odróżnia się od szumu sędziego.
- [ ] Uzupełnij tabelę poniżej (kolumny sędziego i klasa) i wnioski. Commit: `etap14: wynik ewaluacji Foundry i tabela rozjazdow`.

**Tabela „sędzia LLM vs metryka deterministyczna”** — przebieg na żywo 2026-10-21, klucz `20261021-2033_szkody_gpt-5-mini` (gpt-5-mini, 12/12 decyzji zgodnych, recall@5 = 1,00), sędzia gpt-5-mini (`is_reasoning_model=True`), wiersze z `_rozjazdy.md`. Run MLflow sędziego `cbfad3b4`, run RAG `c46be1cf` (Azure ML `uw-demo-mlw`), ewaluacja w projekcie Foundry `uw-demo-ewaluacja`.

| ID | decyzja oczek.→otrzym. | decyzja_ok | cytat | G | Rel | Ret | Compl | klasa | uwagi |
|---|---|---|---|---|---|---|---|---|---|
| Z01 | zgodna (POKRYTA) | True | True | 2 FAIL | 4 | 5 | 5 | zgoda_ok | G FAIL: fakty ze zgłoszenia (przyczyna pożaru, załączone zaświadczenie straży) nie są w `context` |
| Z02 | zgodna | True | True | 5 | 4 | 5 | 5 | zgoda_ok | |
| Z03 | zgodna | True | True | 5 | 3 | 5 | 4 | zgoda_ok | |
| Z04 | zgodna | True | True | 5 | 5 | 5 | 5 | zgoda_ok | |
| Z05 | zgodna | True | True | 5 | 4 | 5 | 4 | zgoda_ok | |
| Z06 | zgodna (ODMOWA) | True | True | 2 FAIL | 4 | 5 | 5 | zgoda_ok | G FAIL: oświadczenie „brak przepięcia” pochodzi ze zgłoszenia, nie z OWU |
| Z07 | zgodna | True | True | 4 | 5 | 5 | 4 | zgoda_ok | |
| Z08 | zgodna | True | True | 5 | 4 | 5 | 4 | zgoda_ok | |
| Z09 | zgodna (reguły) | True | – | – | – | – | – | n/d | brak oceny LLM |
| **Z10** | zgodna (SKIEROWANIE) | **True** | True | 2 FAIL | 5 | 5 | 3 | zgoda_ok | W tym przebiegu LLM dał POKRYTA, S03 skierowała → hipoteza z 1722 (`zgoda_blad`/`sedzia_poblazliwy`) **nietestowalna**; G FAIL za SU 500 000 z wyniku sprawdzenia polisy, której nie ma w `context` |
| Z11, Z12 | zgodna (reguły/podejrzane) | True | – | – | – | – | – | n/d | brak oceny LLM |

Średnie: G 3,89 (pass 6/9), Rel 4,22, Ret 5,00, Compl 4,33 (pass 9/9); rozjazdy klasy = 0.

**Wniosek z przebiegu:** wszystkie 3 porażki groundedness to **artefakt konstrukcji `context`**, nie zmyślenie: `context` zawiera tylko fragmenty OWU, a odpowiedź poprawnie korzysta też z faktów zgłoszenia i z wyniku sprawdzenia polisy (SU). Sędzia ocenia to jako „unsupported”. Poprawka (poza zakresem Etapu 14): dołożyć do `context` zamaskowane streszczenie zgłoszenia i wynik sprawdzenia polisy — wtedy G FAIL będzie znaczyć realne zmyślenie. Z10: LLM jest niedeterministyczny (1722 UZUPEŁNIENIE, 2033 POKRYTA), więc pojedynczy przebieg nie rozstrzyga hipotezy; do weryfikacji potrzebne kilka przebiegów.

**Interpretacja (do potwierdzenia wynikiem):** groundedness mierzy „nie zmyśla poza kontekstem”, nie „ma rację”. Z10 to przypadek, gdzie odpowiedź jest w pełni ugruntowana i zła — o decyzji rozstrzyga metryka deterministyczna (jest prawda z `reguly.py`), a sędzia służy do jakości uzasadnienia tam, gdzie prawdy nie ma. W produkcji: sędzia jako filtr do przeglądu (`fail` → człowiek), nigdy jako jedyna bramka wdrożenia.

### Zadanie 7: dokumentacja i domknięcie

- [ ] `docs/ROZWOJ.md` — sekcja Etap 14: decyzje 1–6 (1 linia każda), pułapki (venv, `is_reasoning_model`, storage, kody 6/7/8 — fałszywe sukcesy), koszt przebiegu, link `studio_url` bez tokenów.
- [ ] `infra/terraform/README.md` — sekcja Foundry: zmienne warunkowe, komendy z zadania 4, **pułapka soft-delete**: po `terraform destroy` konto AIServices zostaje 48 h w soft-delete i blokuje nazwę/subdomenę `uw-demo-ai-xx1` — przed ponownym `apply` `& $AZ cognitiveservices account purge -g <rg> -n uw-demo-ai-xx1 -l swedencentral` albo inna wartość `-var foundry_konto=...`.
- [ ] `pytest -q -m "not azure"` → zielone; `git push -u origin etap14` (nie `main`). Scalenie — decyzja właściciela. Commit: `etap14: dokumentacja`.

## Kryteria akceptacji

- Przebieg `szkody-<klucz>` widoczny w portalu Foundry (`studio_url`) z 4 metrykami (`groundedness`, `relevance`, `retrieval`, `response_completeness`) dla 9 wierszy (wszystkie z `decyzja_llm != null`); CLI zakończony kodem 0 (żaden wiersz z oceną LLM bez oceny, 9/9 ocen LLM, zero `blad`, niepusty `studio_url`). `_rozjazdy.md` ma 12 wierszy (3 × n/d); średnie `sedzia_*` liczone po 9.
- Run MLflow z tagiem `klucz_przebiegu` = ten sam klucz, metryki `sedzia_*`, artefakty `_sedzia.json`, `_rozjazdy.md`.
- Tabela rozjazdów w tym pliku wypełniona dla Z01–Z12 z wnioskiem dla Z10; koszt przebiegu (RAG + sędzia) zapisany w `docs/ROZWOJ.md`.
- JSONL i wyniki tylko w `ewaluacja/wyniki/` (gitignore); test RODO zielony (brak NIP, nazwy, adresu, nr polisy w polach RAG); nic z treści nie idzie do App Insights (nie przekazujemy konfiguracji App Insights do `evaluate`).
- `pytest -q -m "not azure"` zielone w `.venv`; `terraform validate` OK; `plan` Etapu 14 bez zmian w zasobach Etapu 13.

## Ryzyka

- **gpt-5-mini jako sędzia** — parametr `is_reasoning_model` udokumentowany dla o1/o3 [Ź2]; gpt-5 nie ma na liście sędziów [Ź6]. Zadanie 0 rozstrzyga testem jednego wiersza; fallback 4o-mini (o ile jeszcze wdrażalny).
- **Pobłażliwość tej samej rodziny** (gpt-5-mini ocenia gpt-5-mini) — nazwana w raporcie; kontra: metryka deterministyczna + opcjonalny drugi przebieg sędziego.
- **Konflikt z MLflow 3.15 / azureml-mlflow** — `.venv-foundry`; MLflow przez `--mlflow-z` z `.venv-ewaluacja`.
- **Wymóg Storage dla projektu Foundry** [Ź6] — zasób warunkowy; włączenie dodaje role „Storage Blob Data Owner” na istniejącym koncie (zmiana uprawnień — zapowiedzieć właścicielowi).
- **Limit TPM 50k** na `gpt-5-mini` przy równoległym sędziowaniu (36 wywołań, rozumowanie) — 429 → ewaluator zwraca błąd w wierszu, `fail_on_evaluator_errors=False` daje pusty wynik; łapie to kod 6. Sterowanie współbieżnością — DSZ0.
- **Niedeterminizm RAG** (1711 vs 1722 różne pomyłki) — tabela opisuje jeden przebieg; nie uogólniać z jednego Z10.
- **Region** — ewaluatory jakości (prompty) działają na dowolnym wdrożeniu GPT, więc region swedencentral dotyczy tylko modelu sędziego i projektu; ograniczenia regionalne dotyczą ewaluatorów bezpieczeństwa i `GroundednessProEvaluator` (backend Content Safety) [Ź6], których nie używamy.
- **Koszt konta AIServices** — brak opłaty stałej zakładany, DSZ0; budżet `underwriter-demo-170eur` z alertami jako siatka.

## Do sprawdzenia w zadaniu 0 (DSZ0)

Stan na 2026-10-21, `.venv-ewaluacja` z `azure-ai-evaluation==1.18.9`. Skrypty testowe poza repo (scratchpad sesji). Rozstrzygnięte = sprawdzone testem lub źródłem; **po apply zadania 4** = nie da się ustalić bez zasobu.

1. **`is_reasoning_model=True` z `gpt-5-mini` — DZIAŁA (rozstrzygnięte).** Test 1 wiersza na `uw-demo-aoai-xx1`, wdrożenie `gpt-5-mini` (model `gpt-5-mini-2025-08-07`), Entra (`AzureCliCredential`), `api_version=2025-04-01-preview` (ta z `ModelAzure`). Wszystkie 4 ewaluatory zwróciły liczbę i `*_result="pass"`: groundedness 5.0, relevance 4.0, retrieval 5.0, response_completeness 5.0, `*_status="completed"`, brak NaN. Mechanizm (źródło `_legacy/prompty/_prompty.py`): przy `is_reasoning_model=True` SDK zamienia `max_tokens` na `max_completion_tokens=60000` i usuwa `temperature`/`top_p`/`presence_penalty`/`frequency_penalty` — dokładnie to, czego gpt-5-mini wymaga. Fallback 4o-mini z decyzji 4 **nie jest potrzebny** (zadanie 4: `wdroz_sedziego_4o_mini` zostaje `false`). Czas: 6-15 s na wywołanie.
2. **`ResponseCompletenessEvaluator` przyjmuje `is_reasoning_model` — TAK (rozstrzygnięte testem i źródłem).** Sygnatura `(model_config, *, threshold=3, credential=None, **kwargs)` przekazuje `**kwargs` do `PromptyEvaluatorBase`, który czyta `kwargs.get("is_reasoning_model")`. Test z `is_reasoning_model=True` dał 5.0/pass. Wszystkie 4 sygnatury mają `**kwargs` (także Relevance i Retrieval).
3. **Połączenie Storage dla `evaluate(azure_ai_project=<URL>)` — NIE DA SIĘ ROZSTRZYGNĄĆ OFFLINE; po apply zadania 4.** Źródło (`_evaluate/_utils.py::_log_metrics_and_instance_results_onedp`): przy `azure_ai_project` jako string SDK idzie ścieżką „onedp": `start_pending_upload(TEMPORARY_BLOB_REFERENCE)` → SAS od usługi Foundry → upload `instance_results.jsonl` → `start_evaluation_run`/`update_evaluation_run`; `studio_url` = `properties["AiStudioEvaluationUri"]` z odpowiedzi (może być `None` — stąd kod wyjścia 8). Kod SDK sam nie odwołuje się do konta Storage użytkownika; dokumentacja [Ź6] (strona „classic", 2026-02-25) mimo to każe „create and connect your storage account" i przy Entra nadać **Storage Blob Data Owner** użytkownikowi i zasobowi projektu. Dla nowego projektu AIServices pozostaje próba: pierwszy przebieg bez `var.polacz_storage`; błąd uploadu/403 → włączyć. Uwaga RODO: do projektu leci cały `instance_results.jsonl` (query/context/response po anonimizacji z decyzji 3), nie same metryki.
4. **Rola do zapisu wyników — NIEROZSTRZYGNIĘTE; po apply zadania 4.** Dokumentacja [Ź6] wymienia tylko `Cognitive Services OpenAI User` (inferencja sędziego, już jest na `uw-demo-aoai-xx1`) i Storage Blob Data Owner (pkt 3). Token do logowania ma zakres `https://ai.azure.com/.default` (`TokenScope.COGNITIVE_SERVICES_MANAGEMENT`); `credential` można przekazać do `evaluate(..., credential=...)` (czytane z `kwargs`; bez niego `AzureMLTokenManager` użyje domyślnego łańcucha poświadczeń). `Azure AI User` na koncie AIServices jest założeniem specu — sprawdzić pierwszym przebiegiem (403 wskaże brakującą rolę).
5. **Współbieżność `evaluate` — sterowana zmienną środowiskową `PF_WORKER_COUNT` (rozstrzygnięte źródłem).** `_evaluate/_batch_run/_run_submitter_client.py`: `RunSubmitterClient` czyta `PF_WORKER_COUNT` → `BatchEngineConfig.max_concurrency`; **domyślnie 10** (`_legacy/_batch_engine/_config.py`). Analogicznie `PF_LINE_TIMEOUT_SEC` (domyślnie 600 s na wiersz) i `PF_BATCH_TIMEOUT_SEC` (3600 s). Przy limicie TPM 50k ustawić w `foundry_uruchom` `PF_WORKER_COUNT` (np. 2-3) **przed** wywołaniem `evaluate` (zmienna czytana przy tworzeniu klienta). Brak parametru `max_workers` w sygnaturze potwierdzony (`evaluate(*, data, evaluators, evaluation_name, target, evaluator_config, azure_ai_project, output_path, fail_on_evaluator_errors, tags, **kwargs)`). Dodatkowo `AI_EVALS_BATCH_USE_ASYNC` (domyślnie `true`).
6. **Tokeny w wierszu wyniku — SĄ, ale pod INNYMI kluczami niż zakładał spec (rozstrzygnięte testem `evaluate`).** Nie ma kolumn `*_prompt_tokens`/`*_completion_tokens`. Wiersz wyniku ma klucze `outputs.<alias>.<metryka>`, `..._score`, `..._passed` (bool), `..._result` (`pass`/`fail`), `..._reason`, `..._status` (`completed`), `..._threshold` oraz **`outputs.<alias>.<metryka>_properties` = dict** `{prompt_tokens, completion_tokens, total_tokens, finish_reason, model, sample_input, sample_output}` (retrieval dodatkowo `thought_chain`). **Zadanie 6 (linia „Koszt rzeczywisty") i zadanie 3 muszą czytać `outputs.<alias>.<metryka>_properties["prompt_tokens"]`/`["completion_tokens"]`**, nie osobne kolumny. Metryki zbiorcze mają prefiks `<alias>.`: `relevance.relevance`, `relevance.relevance_score`, `relevance.relevance_passed`, `relevance.binary_aggregate`. **RODO:** `_properties.sample_input/sample_output` powtarzają treść zapytania i uzasadnienie sędziego — trafiają do `instance_results.jsonl` w Foundry i do `<klucz>_sedzia.json`; po anonimizacji z decyzji 3 OK, ale **nie logować `_properties` do MLflow** (tabela MLflow = płaskie skalary, jak w specu). Koszt testów: ok. 10,3 tys. tokenów wejścia i 2,6 tys. wyjścia (1 wiersz x 4 ewaluatory + 1 wiersz `evaluate`/relevance) = ok. 0,008 USD przy cenie 0,25/2,00 USD za 1 mln tokenów (cena ZAŁOŻONA z pamięci, nie sprawdzona w kalkulatorze). Na wywołanie 2-4 tys. tokenów; 36 wywołań ≈ 0,13-0,18 USD, zgodnie z szacunkiem specu.
7. **`gpt-4o-mini` 2024-07-18 w swedencentral — DOSTĘPNY, ale „Deprecating" (rozstrzygnięte `az cognitiveservices model list -l swedencentral`).** Dla kont `OpenAI` i `AIServices`: `lifecycleStatus=Deprecating`, wycofanie wnioskowania **2027-04-14**, SKU `Standard` (limit domyślny 10 i 50), `GlobalStandard`, `DataZoneStandard`. Fallback możliwy, ale z terminem ok. pół roku. Przy okazji: `gpt-5-mini 2025-08-07` — `GenerallyAvailable`, wycofanie wnioskowania **2027-02-09**, SKU tylko `GlobalStandard` (10) i `DataZoneStandard` (10) — brak `Standard` w swedencentral; `gpt-4.1-mini 2025-04-14` — `Legacy`, 2027-04-14.
8. **Klucze mapy `azurerm_cognitive_account_project.endpoints` — NIEROZSTRZYGNIĘTE; po apply zadania 4.** Dokumentacja providera (źródło GitHub `website/docs/r/cognitive_account_project.html.markdown`, odczytane przez narzędzie streszczające, nie dosłownie): `endpoints` to mapa nazwa → URL, **dokumentacja nie wymienia kluczy**. Argumenty wymagane: `name`, `cognitive_account_id`, `location`, `identity` (blok **na projekcie**, nie tylko na koncie); opcjonalne `description`, `display_name`, `tags`; atrybuty `id`, `default`, `endpoints`, `identity.principal_id/tenant_id`. Do zadania 4: `foundry.tf` musi mieć blok `identity` w `azurerm_cognitive_account_project` i `location`. URL w `outputs.tf` zostaje budowany z formatu [Ź3] (`https://{konto}.services.ai.azure.com/api/projects/{projekt}`); po apply porównać z `terraform state show` (atrybut `endpoints`).
9. **Brak opłaty stałej za konto AIServices S0 + projekt — NIEPOTWIERDZONE dokumentacją; po apply zadania 4 (Cost Management).** Strona kosztów Foundry w wersji hub/classic opisuje rozliczenie za usługi składowe (tokeny, Search, VM, Storage itd.) i mówi, że projekty hubowe nie mają osobnej pozycji w kalkulatorze; o nowych projektach (AIServices) w pobranych stronach nie ma nic o opłacie stałej ani o jej braku. Założenie „tylko tokeny + Storage" pozostaje założeniem. Siatka bezpieczeństwa: budżet `underwriter-demo-170eur`, `spendingLimit On`; po apply sprawdzić koszt konta po 24 h.
