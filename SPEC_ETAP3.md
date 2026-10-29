# Etap 3 — API (FastAPI) + Postgres + Azurite (Blob)

Wejście: agent z etapu 2 (`agent/`, `ewaluacja/atrapa.py`), dane z etapu 1. Grafu i węzłów
nie przebudowujemy — API je opakowuje. Dopuszczalne są tylko drobne zmiany w `agent/`
potrzebne do trwałego checkpointera (patrz „Stan grafu a checkpointer").

## Cel

Underwriter wgrywa dokument → API zapisuje go w Blob Storage, rejestruje wniosek w Postgresie
i w tle puszcza graf do `interrupt()` → wniosek czeka z rekomendacją LLM, decyzją silnika
reguł i flagami → underwriter zatwierdza lub zmienia decyzję → graf wznawia się z
checkpointu w Postgresie i kończy. **Stan przerwanego grafu przeżywa restart API** — to
główny dowód etapu (test integracyjny).

Lokalnie Azurite emuluje Azure Blob Storage; w etapie 6 ta sama klasa działa na prawdziwym
koncie (zmiana connection stringa, zero zmian w kodzie).

## Środowisko

- `.venv` jak w etapie 2 (Python 3.14). Doinstaluj: `fastapi`, `uvicorn[standard]`,
  `python-multipart`, `sqlalchemy` (2.x), `psycopg[binary]` (3.x), `psycopg-pool`,
  `langgraph-checkpoint-postgres`, `azure-storage-blob`, `alembic`, `httpx` (TestClient).
  Sprawdź, że każdy ma koło dla 3.14/Windows; jeśli nie — zgłoś, nie obchodź.
  Dopisz do `requirements.txt` z wersjami `==` faktycznie zainstalowanymi (sekcja „Etap 3").
- `docker-compose.yml`: `postgres:17` (port 5432, wolumen nazwany, healthcheck `pg_isready`),
  `mcr.microsoft.com/azure-storage/azurite` (tylko blob, port 10000, `--loose`
  niepotrzebne). Usługa `api` z `Dockerfile` (python:3.14-slim, uvicorn, użytkownik nie-root)
  w profilu `api`, żeby `docker compose up -d` stawiał tylko zależności do pracy lokalnej.
- Konfiguracja wyłącznie ze zmiennych środowiskowych (moduł `api/ustawienia.py`, bez
  dodatkowych bibliotek): `DATABASE_URL`, `AZURE_STORAGE_CONNECTION_STRING`,
  `KONTENER_BLOB` (domyślnie `wnioski`), `MODEL_AGENTA` (`atrapa` | `gemini`, **domyślnie
  `atrapa`** — zero kosztów, dopóki ktoś jawnie nie wybierze Gemini), `GEMINI_MODEL`,
  `GEMINI_THINKING`, `CORS_ORIGINS` (domyślnie `http://localhost:3000` pod etap 4).
  Plik `.env.example` z wartościami dla Azurite (znany publiczny klucz deweloperski Azurite
  jest jawny z definicji — wolno go wpisać). Żadnych prawdziwych sekretów w repo.
- Klucz Gemini: tak jak w etapie 2 (`agent/model.py`), API go nie loguje i nie zwraca.

## Struktura

```
api/
  __init__.py
  ustawienia.py      # dataclass Ustawienia.z_env()
  baza.py            # SQLAlchemy 2.0: modele Wniosek, ZdarzenieAudytu; sesje
  magazyn.py         # Protocol MagazynDokumentow + MagazynBlob (azure-storage-blob) + MagazynPamieciowy (testy)
  agent_serwis.py    # budowa grafu z checkpointerem, start i wznowienie przebiegu, model atrapa/gemini
  schematy_api.py    # Pydantic: odpowiedzi i żądania API
  trasy.py           # APIRouter
  main.py            # utworz_aplikacje(ustawienia, *, magazyn=None, checkpointer=None, model=None) + app
migracje/            # Alembic, jedna migracja początkowa
alembic.ini
docker-compose.yml
Dockerfile
.env.example
tests/test_api.py           # bez sieci i bez Dockera (SQLite w pamieci, atrapa)
tests/test_api_integracja.py
```

## Model danych (Postgres)

`wnioski`: `id` (uuid, PK), `nazwa_pliku`, `typ_mime`, `rozmiar_b`, `blob_nazwa`,
`status` (`PRZETWARZANIE` | `CZEKA_NA_DECYZJE` | `ZAKONCZONY` | `INNY_DOKUMENT` | `BLAD`),
`thread_id` (= str(id)), `podsumowanie` (JSONB: to, co węzeł `zatwierdzenie` przekazuje do
`interrupt()` — pola, flagi, rekomendacja, decyzja silnika, zgodność, błąd), `log_wezlow`
(JSONB), `wywolania_llm`, `tokeny_we`, `tokeny_wy`, `decyzja_koncowa`, `zatwierdzil`,
`komentarz`, `utworzono`, `zakonczono` (timestamptz).

`audyt` (tylko INSERT, nigdy UPDATE/DELETE z kodu): `id`, `wniosek_id` (FK), `czas`,
`zdarzenie` (`PRZYJETO` | `REKOMENDACJA` | `DECYZJA` | `BLAD`), `kto`, `dane` (JSONB).
Ślad audytowy jest argumentem pod AI Act (etap 7): kto, kiedy, co zalecił model, co
zdecydował człowiek, czy odszedł od rekomendacji.

Schemat tworzy Alembic (`alembic upgrade head`); tabele checkpointera tworzy
`PostgresSaver.setup()` przy starcie API.

## Endpointy

| Metoda | Ścieżka | Działanie |
|---|---|---|
| POST | `/wnioski` | multipart `plik` (.pdf/.jpg/.jpeg/.eml, max 10 MB, inne → 415/413). Zapis do Blob, rekord `PRZETWARZANIE`, audyt `PRZYJETO`, graf w tle (`BackgroundTasks`). Zwraca 202 + `{id, status}`. |
| GET | `/wnioski` | lista, filtr `?status=`, sortowanie od najnowszych, `limit` (domyślnie 50, max 200) |
| GET | `/wnioski/{id}` | szczegóły z podsumowaniem i logiem węzłów; 404 gdy brak |
| GET | `/wnioski/{id}/dokument` | strumień oryginału z Blob z właściwym `Content-Type` |
| POST | `/wnioski/{id}/decyzja` | body `{decyzja, komentarz?}`, nagłówek `X-Uzytkownik` (wymagany). `decyzja` ∈ AKCEPTACJA, ODMOWA, UZUPELNIENIE, SKIEROWANIE. 409 gdy status ≠ `CZEKA_NA_DECYZJE`. **Gdy decyzja ≠ rekomendacji LLM albo ≠ decyzji silnika — `komentarz` wymagany (422).** Wznawia graf `Command(resume={"decyzja", "kto"})`, status `ZAKONCZONY`, audyt `DECYZJA` z polem `odejscie_od_rekomendacji`. |
| GET | `/wnioski/{id}/audyt` | zdarzenia audytu chronologicznie |
| GET | `/zdrowie` | 200 gdy Postgres (`SELECT 1`) i Blob (istnienie kontenera) odpowiadają; inaczej 503 z wskazaniem, co leży |

Uwierzytelnienie poza zakresem (etap 6: Entra ID / Easy Auth). `X-Uzytkownik` to jawna
zaślepka i README ma to tak nazwać.

## Przebieg w tle (`agent_serwis.py`)

- Graf z `agent/graf.py`, `thread_id` = id wniosku. Plik pobierany z Blob do katalogu
  tymczasowego, ścieżka do stanu (`plik`), plik tymczasowy usuwany po przebiegu.
- Po dojściu do `interrupt()`: odczyt wartości przerwania z `graf.get_state(config)`
  (`.interrupts` / `.tasks[..].interrupts` — sprawdź w zainstalowanej wersji langgraph,
  nie zgaduj), zapis `podsumowanie`, `log_wezlow`, sumy tokenów, status
  `CZEKA_NA_DECYZJE`, audyt `REKOMENDACJA`.
- Typ `INNY` (graf kończy się bez przerwania) → status `INNY_DOKUMENT`.
- Wyjątek → status `BLAD`, audyt `BLAD` z treścią błędu (bez sekretów), log `logging`
  na poziomie ERROR. **Żaden wyjątek z zadania w tle nie może zniknąć cicho.**
- Model `atrapa`: `ModelAtrapa(dane/oczekiwane)` z `ustaw_przypadek(<stem nazwy pliku>)`;
  plik spoza W01–W14 → `BLAD` z czytelnym komunikatem („atrapa zna tylko W01–W14").
  Model `gemini`: `ModelGemini` z etapu 2 (bezpieczniki kosztowe już tam są; limit 6
  wywołań na dokument zostaje).
- Wniosek wiszący w `PRZETWARZANIE` po restarcie API (proces padł w trakcie): przy starcie
  oznacz go `BLAD` z komunikatem „przerwany restartem" — nie wznawiaj automatycznie
  (wznowienie = ponowne płatne wywołania; decyzja należy do człowieka).

## Stan grafu a checkpointer

`StanGrafu.czesci` zawiera bajty dokumentu (`CzesciDokumentu` z `Medium`). Sprawdź, czy
serializer `PostgresSaver` (JsonPlusSerializer) to przyjmuje. Jeśli nie albo jeśli to
wielokrotnie powiela dokument w tabelach checkpointów — dopuszczalna zmiana w `agent/`:
po `ekstrahuj` (ostatnim węźle, który potrzebuje `czesci`) wyczyść `czesci` w stanie.
Dokument i tak jest w Blob. Testy etapu 2 muszą dalej przechodzić.

## Testy

- `tests/test_api.py` — **bez Dockera i bez sieci**: `utworz_aplikacje` z
  `MagazynPamieciowy`, `InMemorySaver`, modelem atrapą i bazą SQLite w pamięci (modele
  SQLAlchemy z typem `JSON` mapowanym na JSONB w Postgresie przez `with_variant`).
  Pokrycie: upload → `CZEKA_NA_DECYZJE` z podsumowaniem; W14 (INNY) → `INNY_DOKUMENT`;
  zła rozszerzenie → 415; za duży → 413; decyzja zgodna bez komentarza → 200 i
  `ZAKONCZONY`; decyzja niezgodna bez komentarza → 422; decyzja ponowna → 409; brak
  `X-Uzytkownik` → 422; audyt ma PRZYJETO, REKOMENDACJA, DECYZJA w kolejności; wyjątek
  modelu → `BLAD` + audyt `BLAD`; `/zdrowie` 200 i 503 (magazyn zgłaszający błąd).
- `tests/test_api_integracja.py` — marker `integracja`, pomijany, gdy Postgres/Azurite z
  `docker compose` nie odpowiadają (czytelny powód w `skip`). Pokrycie: upload przez
  prawdziwy Blob (Azurite), `PostgresSaver`, **restart**: nowa instancja aplikacji (nowa
  pula połączeń, nowy graf) zatwierdza wniosek przerwany przez poprzednią i graf kończy
  się poprawnie; `/wnioski/{id}/dokument` zwraca bajty identyczne z wgranymi.
- Wszystkie dotychczasowe testy (114 + 1 pominięty) przechodzą bez zmian.
- **Żaden test nie woła Gemini.** Zabezpieczenie: fixture ustawia `MODEL_AGENTA=atrapa`
  i usuwa `GEMINI_API_KEY` ze środowiska testów.

## README

Sekcja „Etap 3 — API": jak uruchomić (`docker compose up -d`, `alembic upgrade head`,
`uvicorn api.main:app --reload`), przykład curl przepływu upload → szczegóły → decyzja,
link do `/docs`, co jest zaślepką (uwierzytelnienie, przetwarzanie w `BackgroundTasks`
zamiast kolejki — w produkcji Azure Service Bus / Container Apps Jobs).

## Poza zakresem

Frontend (etap 4), uwierzytelnienie i wdrożenie w Azure (etapy 5–6), Document
Intelligence (etap 5), kolejka komunikatów, wieloprocesowe workery.
