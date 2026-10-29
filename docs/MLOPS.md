# MLOps: model "szkoda do weryfikacji" na Azure ML (Etap 15)

> **Dane sa syntetyczne - celem jest cykl MLOps, nie jakosc modelu.** Etykieta pochodzi z ukrytej
> reguly w generatorze (`ryzyko/generator.py`) plus szum. Wynik modelu to sygnal dla likwidatora,
> nigdy decyzja (SPEC_ETAP15, decyzja 6).

Ten dokument jest budowany etapami; teraz opisuje zadania 3 i 4a (pipeline, rejestr, eksport) oraz 6
(job dryfu, alerty A i B, procedura testu na zywo - jeszcze niewykonana).

## Cykl

```
pipeline Azure ML (serverless Standard_DS2_v2)         lokalnie / recznie po pipeline
przygotuj -> trenuj -> ewaluuj -> zarejestruj  ---->   eksportuj_championa  ---->  Blob modele/ryzyko_szkody/
                         |                                                           champion.skops
                  rejestr modeli `ryzyko_szkody`                                     referencja.json
                  (tag modelu `champion=<wersja>`)                                   metadane.json
                                                                                     |
                                                              API: ModelRyzyka.z_bloba (przy starcie)
```

- Kod: `pipeline_ml/komponenty/{przygotuj,trenuj,ewaluuj,zarejestruj}.py` (kazdy to skrypt z argparse,
  wejscie i wyjscie = katalogi), `pipeline_ml/uruchom.py` (wysylka), `pipeline_ml/eksportuj_championa.py`.
- Cala logika modelu (cechy, generator, bramka, PSI, serwowanie) jest w pakiecie `ryzyko/` - komponenty
  go tylko wolaja (`code=` = skrypty + kopia `ryzyko/`), bez duplikowania.
- Srodowisko komponentow: `pipeline_ml/srodowisko.yml` (python 3.12, scikit-learn 1.9.1, skops 0.16.0,
  numpy 2.5.4, scipy 1.18.1, pandas 2.3.3, mlflow 3.15.0, azureml-mlflow 1.62.0.post6) - ta sama wersja
  sklearn co w API, bo skops/pickle modelu zaleza od wersji. Wersja srodowiska w Azure ML = skrot tresci
  pliku (zmiana pliku -> nowa wersja).

## Rejestr: co dziala w Azure ML, a co nie (zweryfikowane na zywo 26.10.2026)

| nie dziala | dziala |
|---|---|
| aliasy MLflow (404) | `mlflow.sklearn.save_model` + `mlflow.log_artifacts(d, artifact_path="model")` |
| `log_model(registered_model_name=)`, `mlflow.register_model` (404 `logged-models`) | `create_registered_model`, `create_model_version(N, source=<artifact_uri>/model, run_id=)` |
| `search_registered_models()` (400) | `get_registered_model(N)`, tagi wersji i modelu |

Dlatego:

- **wskaznik championa = tag MODELU `champion=<wersja>`** (promocja i rollback = jedno nadpisanie
  `set_registered_model_tag`; dokladnie jeden champion z konstrukcji),
- tagi wersji: `rola` (`champion` / `odrzucony` / `wycofany` = byly champion zastapiony nowym),
  `powod`, `rodzaj`, `pr_auc`, `roc_auc`, `brier`,
- artefakty wersji: model MLflow + `referencja.json` (granice koszy i proporcje do PSI) + `metryki.json`,
- bramka (`ryzyko/bramka.py`): challenger zostaje championem, gdy `PR AUC >= champion - 0,01`;
  brak championa -> promocja,
- odczyt championa i zapis tagu to nie transakcja: **nie puszczac dwoch pipeline'ow naraz**,
- mlflow 3.15 zapisuje sklearn w formacie skops, wiec `save_model` dostaje
  `skops_trusted_types=ZAUFANE_TYPY` (jedyny typ spoza listy domyslnej: `TreePredictor` z HGB).

## Uruchamianie

```
# wysylka pipeline'u (.venv-mlops; czeka na wynik, kod wyjscia 0 = Completed)
.venv-mlops\Scripts\python -I -X utf8 pipeline_ml\uruchom.py --rodzaj hgb        # hgb | logreg | zepsuty

# eksport championa do Blob (.venv-ewaluacja; --sprawdz = zaladuj z Blob jak API i ocen probke)
.venv-ewaluacja\Scripts\python -I -X utf8 pipeline_ml\eksportuj_championa.py --sprawdz
```

`zepsuty` = ten sam HGB uczony na losowo przetasowanych etykietach, oceniany na PRAWDZIWYCH etykietach
testu - celowo bezuzyteczny model do testu bramki. Eksport wymaga `az login` z rola Storage Blob Data
Contributor na koncie `uwdemostxx1` i istniejacego kontenera `modele`.

## Przebiegi bramki

Dane: `n=5000`, `seed=0`, podzial 70/30 (test = 1500 wierszy), serverless `Standard_DS2_v2`,
workspace `uw-demo-mlw` (eksperyment `etap15-ryzyko-szkody`), 26.10.2026.

| # | rodzaj | job pipeline'u | status | wersja | PR AUC | ROC AUC | Brier | rola | co zrobila bramka |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `hgb` | `cool_grape_vs3chvz68p` | Completed (ok. 5,6 min, w tym pierwszy build srodowiska) | 1 | 0,4420 | 0,7790 | 0,1028 | champion | brak championa -> promocja |
| 2 | `zepsuty` | `zen_drawer_7nm825tcqr` | Completed (ok. 2,6 min) | 2 | 0,1472 | 0,4986 | 0,1233 | odrzucony | `0,1472 < 0,4420 - 0,01` -> odrzucony, tag modelu `champion` bez zmian |

Stan rejestru po obu biegach (odczyt na zywo):

```
model tags: {'champion': '1'}
v1 rola=champion   pr_auc=0.441976 rodzaj=hgb      powod="brak championa - pierwsza wersja zostaje championem"
v2 rola=odrzucony  pr_auc=0.147233 rodzaj=zepsuty  powod="odrzucony: pr_auc challengera 0.1472 vs champion 0.4420 (tol 0.01), ponizej progu 0.4320"
```

Bramka zadzialala w obu stanach (promocja i odrzucenie). Zepsuty model ma ROC AUC ~0,5 (losowy) - luka
wzgledem championa jest o rzad wielkosci wieksza niz tolerancja 0,01, wiec test bramki cos znaczy.

## Eksport championa do Blob

Uruchomienie 26.10.2026 (`eksportuj_championa.py --sprawdz`): champion = wersja 1 (z tagu modelu).

```
modele/ryzyko_szkody/champion.skops   580582 B
modele/ryzyko_szkody/referencja.json    2629 B
modele/ryzyko_szkody/metadane.json       201 B   (wersja, data, metryki; zapisywane OSTATNIE)
```

Sprawdzenie ladowania tym samym kodem co API (`ModelRyzyka.z_bloba`) i ocena jednej syntetycznej probki:
wersja `1`, wynik 0,071, glowne cechy `szkody_3_lata`, `dni_do_zgloszenia`, `suma_ubezpieczenia`.
Sprawdzenie bylo z laptopa (tozsamosc `az login`), a NIE z tozsamosci kontenera API - tej odczytu nie testowano.

## Monitoring dryfu (zadanie 6)

Kod: `ryzyko/job_dryfu.py` (job), `ryzyko/zasiej_wejscia.py` (zasiew do testow), Terraform:
`infra/terraform/dryf.tf` (job `uw-dryf` + alerty A i B). Testy offline: `tests/test_ryzyko_job_dryfu.py`,
`tests/test_ryzyko_zasiej_wejscia.py` (w tym odtworzenie 4 przebiegow na SQLite).

**Co robi job** (Container Apps Job `uw-dryf`, cron `0 6 * * *` UTC, TEN SAM obraz co `uw-api`, komenda
`python -m ryzyko.job_dryfu`): bierze z `wejscia_modelu` wiersze z ostatnich 30 dni (oba zrodla: `api` i
`symulacja`), wczytuje `modele/ryzyko_szkody/referencja.json` z Blob, liczy PSI per cecha (10 koszy z referencji)
i zapisuje wynik w spanie `dryf.przebieg`. Tylko CZYTA - nic nie zapisuje, wiec zdublowany bieg tego samego dnia
daje tylko drugi span. Przed wyjsciem wymusza flush telemetrii (job zyje kilka sekund).

| status spanu `uw.dryf.status` | warunek | exit | alert |
|---|---|---|---|
| `OK` | n >= 200, `psi_max` <= 0,2 | 0 | - |
| `DRYF` | n >= 200, `psi_max` > 0,2 | 0 (dryf to wynik, nie awaria joba) | A |
| `ZA_MALO_DANYCH` | n < 200 | 0 | **brak** (luka nizej) |
| (span ERROR) | brak/uszkodzona referencja, blad bazy, PSI nie do policzenia | 1 | A (Success == false), B po 26 h bez spanu |

Atrybuty: `uw.dryf.status`, `uw.dryf.n`, `uw.dryf.psi_max`, `uw.dryf.cecha_max`, `uw.dryf.psi.<cecha>`; przy
bledzie `error.type` (nazwa klasy) i `uw.dryf.etap_bledu` (`referencja` | `baza` | `psi` | `nieznany`).
Zero tresci dokumentow, NIP, nazwisk - tylko liczby i nazwy cech. **Nigdy PSI = 0 z braku danych.**

**Alerty** (Azure Monitor po Log Analytics, do istniejacej action group `uw-demo-alerty`, stanowe: jeden mail
Fired, potem Resolved):

- **A `uw-demo-alert-dryf`** - OSTATNI span `dryf.przebieg` z ostatnich 25 h ma `psi_max > 0,2` albo `Success == false`.
  Ocenia ostatni span, a nie kazdy, zeby zdrowy bieg zamykal alert od razu (Resolved), a nie po 25 h.
  `window_duration` w alertach v2 nie dopuszcza 25 h/26 h (lista konczy sie na `P2D`), wiec okno to `P2D`,
  a 25 h/26 h wycina `ago(...)` w zapytaniu.
- **B `uw-demo-alert-dryf-brak-joba`** - zero spanow `dryf.przebieg` w ostatnich 26 h (zmienna Terraform
  `dryf_okno_braku_joba`, domyslnie `26h`). Kanal niezalezny od joba: zapytanie Azure Monitor, w kontenerze nic
  nie musi zyc. Lapie tez zly connection string i blad eksportu spanow (wtedy B krzyczy mimo udanego biegu - to
  zamierzone, dla nas "brak telemetrii" = "brak monitoringu").
- **Luka nazwana wprost:** `ZA_MALO_DANYCH` NIE wysyla maila - demo nie ma ruchu, alarm bylby codzienny i
  uczylby ignorowania. Status jest w spanie i w zapytaniu 3 ponizej. W produkcji: osobny alert "proba za mala
  N dni z rzedu".
- Po pierwszym `apply` alert B odpali sie, dopoki job nie wykona pierwszego biegu - uruchom job recznie (krok 0 testu).

### Zapytania KQL (Log Analytics `uw-demo-logs`)

1. Ostatnie przebiegi:

```kusto
union AppRequests, AppDependencies
| where Name == "dryf.przebieg" and TimeGenerated > ago(7d)
| project TimeGenerated, Success, status = tostring(Properties["uw.dryf.status"]),
          n = toint(Properties["uw.dryf.n"]), psi_max = todouble(Properties["uw.dryf.psi_max"]),
          cecha_max = tostring(Properties["uw.dryf.cecha_max"]),
          etap_bledu = tostring(Properties["uw.dryf.etap_bledu"]), blad = tostring(Properties["error.type"])
| order by TimeGenerated desc
```

2. PSI per cecha (ostatni przebieg z policzonym PSI):

```kusto
union AppRequests, AppDependencies
| where Name == "dryf.przebieg" and isnotempty(Properties["uw.dryf.psi_max"])
| top 1 by TimeGenerated desc
| project TimeGenerated, suma_ubezpieczenia = todouble(Properties["uw.dryf.psi.suma_ubezpieczenia"]),
          udzial_kwoty = todouble(Properties["uw.dryf.psi.udzial_kwoty"]),
          dni_do_zgloszenia = todouble(Properties["uw.dryf.psi.dni_do_zgloszenia"]),
          dni_od_poczatku_polisy = todouble(Properties["uw.dryf.psi.dni_od_poczatku_polisy"]),
          rodzaj_mienia = todouble(Properties["uw.dryf.psi.rodzaj_mienia"]),
          liczba_zalacznikow = todouble(Properties["uw.dryf.psi.liczba_zalacznikow"]),
          szkody_3_lata = todouble(Properties["uw.dryf.psi.szkody_3_lata"])
```

3. Dni z za mala proba (luka alertu A):

```kusto
union AppRequests, AppDependencies
| where Name == "dryf.przebieg" and TimeGenerated > ago(30d)
| summarize przebiegi = count(), za_malo = countif(tostring(Properties["uw.dryf.status"]) == "ZA_MALO_DANYCH") by bin(TimeGenerated, 1d)
| order by TimeGenerated desc
```

4. Log konsoli joba (stdout: `Dryf: status=... n=... psi_max=...` albo `etap=..., blad=<klasa>`; dla zasiewu
   `wstawiono=.. / usunieto=.. / w_tabeli=..`). Sprawdzone 26.10: logi joba trafiaja do tej tabeli z opoznieniem
   rzedu kilku-kilkunastu minut; kolumny `ContainerJobName_s` NIE ma (blad SEM0100), filtr po `ContainerGroupName_s`.
   Stdout zawiera tez logi HTTP klienta Azure SDK (naglowki zadan) - szum, nie blad:

```kusto
ContainerAppConsoleLogs_CL
| where ContainerGroupName_s startswith "uw-dryf"
| project TimeGenerated, Log_s
| order by TimeGenerated desc | take 30
```

### Kolejnosc wdrozenia (wazne)

1. Obraz `uw-api` MUSI zawierac `ryzyko/job_dryfu.py` oraz `numpy`/`pandas` w `requirements.txt` (zadanie 7:
   build, push, `az containerapp update` uw-api). `dryf.tf` bierze obraz z aktualnie dzialajacego `uw-api`
   (`data.azurerm_container_app`), wiec apply PRZED nowym obrazem utworzy job, ktory padnie na
   `No module named ryzyko.job_dryfu` (zadnego spanu - zlapie to dopiero alert B po 26 h).
   Job NIE aktualizuje sie sam po kolejnym deployu API: `terraform apply` przeniesie nowy obraz do joba
   (plan pokaze zmiane `image`), albo `az containerapp job update -n uw-dryf -g rg-underwriter-demo --image <obraz>`.
2. `terraform plan -var="email_alertow=<adres>" -out etap15.tfplan`, sprawdz `3 to add`, `0 to destroy`, potem
   `terraform apply etap15.tfplan` (Właściciel). DATABASE_URL joba jest czytany z sekretu `database-url` uw-api
   (`read_secrets = true`) i trafia do stanu Terraform (backend Blob, Entra) oraz do pliku planu - plik jest
   w `.gitignore` (`*.tfplan`), nie wklejac go nigdzie.
   Uwaga na zakonczenia linii: przy `core.autocrlf=true` heredoki w `main.tf` maja w kopii roboczej CRLF, a stan
   Terraform LF, wiec plan moze pokazac DODATKOWE `1 to change` na istniejacym alercie `awaria` (tylko znaki
   konca linii w `description` i `query`, tresc ta sama). To nie jest zmiana zwiazana z Etapem 15; z plikami
   `*.tf` zamienionymi na LF plan to `3 to add, 0 to change, 0 to destroy`.
3. Wymuszony pierwszy bieg (zamyka alert B): krok 0 testu ponizej.

## Test alertow na zywo - procedura (wykonac PO apply)

**Nie uruchamiac przed `apply` i przed wdrozeniem obrazu z `ryzyko.job_dryfu`.** Kazdy krok = (zasiew) + start joba +
czekanie ok. 10 min (ewaluacja alertu co 5 min + opoznienie App Insights 2-5 min) + sprawdzenie KQL nr 1 i skrzynki.
Test robic poza 06:00 UTC (cron joba zaklocilby przebiegi). Ruch demo jest maly, wiec `n` w spanie = 300 + ewentualne
wiersze `api` z ostatnich 30 dni - zapisz `n` z kroku 0.

```powershell
$AZ    = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
$RG    = "rg-underwriter-demo"

# start joba (domyslna komenda = ryzyko.job_dryfu) i lista wykonan
function Start-Dryf { & $AZ containerapp job start -n uw-dryf -g $RG }
function Wykonania  { & $AZ containerapp job execution list -n uw-dryf -g $RG -o table }

# zasiew / sprzatanie: jednorazowe wykonanie TEGO SAMEGO joba z nadpisana komenda (baza nie ma publicznego
# dostepu; job ma DATABASE_URL i tozsamosc). Skrypt wypisuje nazwe wykonania.
function Zasiej($n, $seed, $przesuniecie = $null) {
  $a = @("-m", "ryzyko.zasiej_wejscia", "--n", "$n", "--seed", "$seed")
  if ($przesuniecie) { $a += @("--przesuniecie", $przesuniecie) }
  python infra\start_joba_dryfu.py @a
}
function Sprzatnij { python infra\start_joba_dryfu.py -m ryzyko.zasiej_wejscia --sprzatnij }
```

`az containerapp job start --image/--container-name/--command/--args` NIE dziala dla zasiewu (sprawdzone 26.10):
az interpretuje `--n` z argumentow jako skrot wlasnych opcji (`ambiguous option: --n could match --name, --no-wait`).
Dlatego `infra/start_joba_dryfu.py` wola REST `jobs/uw-dryf/start` z szablonem kontenera skopiowanym z definicji
joba (image, env z secretRef, zasoby) i podmieniona tylko komenda.

### Alert A - 4 przebiegi (SPEC zadanie 6)

| krok | czynnosc | oczekiwany span | oczekiwany alert A |
|---|---|---|---|
| 0 | `Start-Dryf` (bez zasiewu); KQL nr 1 | `ZA_MALO_DANYCH` (n < 200) albo `OK` | cisza; alert B zamyka sie (jest span) |
| 1 | `Zasiej 300 11`, `Start-Dryf` | `OK`, `psi_max` ok. 0,03-0,06 | cisza |
| 2 | `Start-Dryf` ponownie (te same dane) | `OK`, ten sam `psi_max` | cisza |
| 3 | `Sprzatnij`, `Zasiej 300 12 "udzial_kwoty=0.5"`, `Start-Dryf` | `DRYF`, `cecha_max=udzial_kwoty`, `psi_max` >> 0,2 (offline ok. 5,4) | **mail Fired** w ciagu ok. 10 min |
| 4 | `Sprzatnij`, `Zasiej 300 13`, `Start-Dryf` | `OK` | **mail Resolved** (A ocenia ostatni span) |
| 5 | `Sprzatnij` (sprzatanie po tescie) | - | cisza; w `w_tabeli` brak zrodla `symulacja` |

Przed kazdym `Start-Dryf` sprawdz `Wykonania`: poprzednie wykonanie ma byc `Succeeded` (inaczej dwa biegi naraz).
Przebiegi 1-2 to kontrola "brak falszywych alarmow" (cisza ma byc CALY czas, nie tylko po pierwszym biegu).
Wartosci `psi_max` powyzej to pomiar offline na generatorze (n=300), nie na zywo.

### Alert B - brak biegu

1. Ostatni bieg joba mial miejsce przed chwila (krok 4 wyzej).
2. `terraform apply -var="email_alertow=<adres>" -var="dryf_okno_braku_joba=10m"` - zmienia tylko zapytanie alertu B
   (in-place, 0 destroy).
3. NIE startowac joba przez > 10 min (i nie byc w okolicy 06:00 UTC) -> **mail Fired** alertu B w ciagu kolejnych ok. 5-10 min.
4. `Start-Dryf` -> span w oknie 10 min -> **mail Resolved**.
5. REVERT: `terraform apply -var="email_alertow=<adres>"` (bez `dryf_okno_braku_joba` = z powrotem `26h`);
   `terraform plan` ma pokazac brak zmian dla alertu B.

### Zapis wynikow testu (uzupelnic po wykonaniu)

| krok | czas | span / alert | uwagi |
|---|---|---|---|
| 0 | 19:27:36 | `ZA_MALO_DANYCH`, n=0, Success=true | A cisza |
| B Fired | 19:27:27 | alert B Fired (mail) - zasadnie: od apply ok. 30 min, przez 26 h zadnego spanu | mail potwierdzony |
| 1 | 19:30:58 | `OK`, n=300, psi_max 0,0678 (`udzial_kwoty`) | A cisza |
| 2 | 19:32:03 | `OK`, n=300, psi_max 0,0678 (identyczny) | A cisza (sprawdzone 19:42) |
| B Resolved | 19:43:28 | alert B Resolved (mail), 16 min po pierwszym spanie | mail potwierdzony |
| 3 | 19:52:20 | `DRYF`, n=300, psi_max 5,492, `cecha_max=udzial_kwoty` | **A Fired 19:54:04** (mail z instrukcja naprawy) |
| 4 | 20:02:35 | `OK`, n=300, psi_max 0,0332 (`dni_do_zgloszenia`) | **A Resolved 20:15** (mail), 13 min po spanie |
| 5 | ok. 20:13 | `--sprzatnij` przez `infra/start_joba_dryfu.py`, wykonanie Succeeded | cisza |

Wynik (26.10.2026, czasy UTC): oba alerty przetestowane na zywo w stanie chorym i zdrowym, 4 maile potwierdzone
w skrzynce. Alert B NIE wymagal skracania okna (`dryf_okno_braku_joba=10m`) - stan chory dal naturalny okres
miedzy `apply` a pierwszym biegiem. Rozwiazanie alertu log trwa 13-16 min od zdrowego spanu (kilka kolejnych
ewaluacji co 5 min + opoznienie ingestu). Zasiew przez `az containerapp job start --args` nie dziala (patrz wyzej).

### Koszt (szacunek, plan Consumption, 1 bieg dziennie)

Job 0,5 vCPU / 1 GiB, ok. 20-60 s na bieg: ok. 900 vCPU-s i 1800 GiB-s miesiecznie, czyli rzad 0,02-0,05 USD
poza darmowym limitem (180 000 vCPU-s i 360 000 GiB-s miesiecznie na subskrypcje - mieszcza sie w calosci).
Dwa nowe alerty log (ewaluacja co 5 min) to okolo 1,5 USD/mies. kazdy wedlug cennika Azure Monitor (stawki
zaleza od czestosci - do potwierdzenia w cenniku); to jest glowny koszt tej czesci. Ingest spanu (kilka KB dziennie)
pomijalny.

## Testy

- offline: `tests/test_pipeline_ml_*.py` (logika krokow, decyzja rejestracji na atrapie klienta MLflow,
  eksport na `MagazynPamieciowy`, pomocnicze funkcje `uruchom.py`). Lancuch 4 skryptow z lokalnym MLflow
  (SQLite) wymaga `mlflow` - uruchamiac w `.venv-ewaluacja`; w `.venv` jest pomijany.
- na zywo: `@pytest.mark.azure` (`test_azure_rejestr_ma_championa_z_rola_champion`).
- dryf: `tests/test_ryzyko_job_dryfu.py` (zdrowo, dryf, za malo danych, brak referencji, blad bazy, flush, duplikat biegu),
  `tests/test_ryzyko_zasiej_wejscia.py` (zasiew, sprzatanie tylko symulacji, 4 przebiegi na SQLite).
