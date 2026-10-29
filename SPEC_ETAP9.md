# Etap 9 — Kubernetes: chart Helm, uruchomienie i test na kind

Cel: ta sama aplikacja (API + frontend + Postgres + Azurite) wdrażana do Kubernetesa jednym
chartem Helm, sprawdzona end-to-end na lokalnym klastrze kind — za darmo, bez zasobów Azure.
AKS to osobny krok (9b) dopiero po zgodzie właściciela na koszt — **w tym etapie nic w Azure nie powstaje**.

Agent na klastrze: `MODEL_AGENTA=atrapa` (bez sieci, bez kluczy). Chart ma pozwalać przełączyć
dostawcę wartością, ale tego etapu nie weryfikujemy na żywym modelu.

## Zakres

1. **Chart `deploy/helm/underwriter/`** (Chart.yaml, values.yaml, templates/, `_helpers.tpl`):
   - **api** — Deployment (obraz `underwriter-api:<tag>`, `imagePullPolicy: IfNotPresent`), Service
     **ClusterIP** (tylko wewnątrz klastra — tak jak ingress wewnętrzny `uw-api` na Container Apps).
     Konfiguracja z ConfigMap (`MODEL_AGENTA`, `KONTENER_BLOB`, `CORS_ORIGINS`) i Secret
     (`DATABASE_URL`, `AZURE_STORAGE_CONNECTION_STRING`). Sondy: startup + readiness na `/zdrowie`,
     liveness lżejsza (nie może restartować poda przy chwilowej niedostępności bazy — sprawdź, co
     `/zdrowie` faktycznie bada, i dobierz sondy świadomie, z komentarzem).
   - **frontend** — Deployment + Service NodePort `30080`; `API_URL_WEWNETRZNY` = nazwa Service API.
   - **postgres** — StatefulSet `postgres:17` z PVC (1Gi), readiness `pg_isready`. Hasło w Secret,
     generowane przy instalacji i **stabilne przy `helm upgrade`** (`lookup` istniejącego Secretu) —
     inaczej upgrade zmienia hasło, a baza na PVC ma stare. Przełącznik `postgres.wewnetrzny`
     (false = zewnętrzny `DATABASE_URL` z values, pod przyszły AKS + Postgres Flexible).
   - **azurite** — Deployment z `--skipApiVersionCheck` (powód: komentarz w `docker-compose.yml`),
     przełącznik `azurite.wlaczony`.
   - **Migracje Alembic: dokładnie raz na wydanie, nie w każdym podzie.** Pod API nie może być Ready
     przed istnieniem schematu. Wybierz mechanizm (Job jako hook Helm albo initContainer + uzasadnienie
     przy replikach > 1 — alembic nie bierze blokady) i opisz wybór komentarzem w szablonie.
     Błąd migracji ma zatrzymać wdrożenie (`helm --wait` kończy się błędem), nie dać API bez schematu.
   - **Bezpieczeństwo podów:** każdy kontener `runAsNonRoot`, `allowPrivilegeEscalation: false`,
     `capabilities.drop: [ALL]`, `seccompProfile: RuntimeDefault`; `readOnlyRootFilesystem: true` tam,
     gdzie się da (emptyDir na `/tmp`, `/app/.cache_ocr` itd.) — gdzie się nie da (np. Postgres),
     komentarz dlaczego. Każdy kontener ma `resources.requests` i `limits`.
   - **NetworkPolicy:** domyślnie deny ingress w release; frontend przyjmuje ruch z zewnątrz; API tylko
     od frontendu (+ ewentualnie job migracji, jeśli potrzebuje — nie potrzebuje, bo łączy się do
     Postgresa); Postgres tylko od API i migracji; Azurite tylko od API. Polityki DNS/egress nie
     ograniczamy (poza zakresem).
   - `helm test` (`templates/tests/`): pod sprawdzający `/zdrowie` API z wnętrza klastra — UWAGA na
     własną NetworkPolicy (pod testowy musi mieć etykietę dopuszczoną do API albo osobną regułę).
   - Żadnych tagów `latest` w values.

2. **`deploy/kind/`:**
   - `kind-config.yaml` — 1 węzeł, `extraPortMappings` 30080 -> host `8080`.
   - `uruchom.sh` — idempotentnie: klaster `underwriter` (jeśli nie istnieje), `docker build` obu
     obrazów z tagiem = krótki SHA commita (z `-dirty` gdy brudne drzewo), `kind load docker-image`,
     `helm upgrade --install --wait --timeout 5m`, wypisanie adresu.
   - `test_dymny.sh` — kończy się kodem != 0 przy każdym niespełnionym warunku:
     a) `http://localhost:8080` zwraca 200;
     b) przez proxy frontendu (`/api/...`) utworzenie wniosku z dokumentem z `dane/` i odczyt jego stanu
        (atrapa) — sprawdź kontrakt w `api/trasy.py` i `frontend/app/api/[...sciezka]/route.ts`,
        nie zgaduj ścieżek;
     c) `kubectl delete pod` API -> po powrocie do Ready ten sam wniosek nadal istnieje (stan w Postgresie);
     d) **NetworkPolicy działa naprawdę:** efemeryczny pod bez etykiet NIE dostaje się do API
        (timeout), a pod z etykietą frontendu — dostaje. Test w obu stanach; samo „zasoby utworzone"
        nie dowodzi egzekwowania (sprawdź, czy CNI kind egzekwuje polityki w zainstalowanej wersji).
     e) `helm test` przechodzi.
   - `usun.sh` — `kind delete cluster --name underwriter`.

3. **Test pytest `tests/test_helm.py`** (pomijany, gdy brak `helm` w PATH): `helm template` z
   domyślnymi values i z `postgres.wewnetrzny=false` + `azurite.wlaczony=false`; asercje: każdy kontener
   ma limits/requests i `runAsNonRoot`, brak `:latest`, Service API to ClusterIP, przy wyłączonym
   Postgresie nie renderuje się StatefulSet, a `DATABASE_URL` pochodzi z values.

4. **CI (`.github/workflows/ci-cd.yml`):** nowy job `k8s` (równoległy, **nie blokuje** `wdrozenie`):
   instalacja helm + kind (oficjalne akcje), `helm lint`, `uruchom.sh`, `test_dymny.sh`. Job `testy`
   bez zmian zachowania (test_helm pominie się, jeśli helm tam nie ma — albo doinstaluj helm w testy,
   wtedy test się wykona; wybierz i opisz).

5. **Dokumentacja:** `docs/ROZWOJ.md` sekcja „Etap 9 — Kubernetes (kind)" (komendy, wymagania:
   Docker Desktop, kind, helm, kubectl; decyzje: migracje, sondy, NetworkPolicy, hasło przy upgrade);
   README — krótka wzmianka + jedna linia w tabeli/liście etapów, jeśli taka jest.

## Poza zakresem

AKS, Ingress controller, cert-manager, HPA/metrics-server, Workload Identity, values-aks.yaml
(projektujemy w 9b), zmiany w kodzie aplikacji (jeśli okaże się konieczna — zatrzymaj się i zgłoś).

## Kryteria akceptacji

- `deploy/kind/uruchom.sh && deploy/kind/test_dymny.sh` na czystym klastrze -> kod 0; drugi
  `uruchom.sh` (upgrade) -> nadal działa, hasło Postgresa niezmienione, dane zachowane.
- Test d) pokazany w obu stanach (wynik odmowy i dopuszczenia w raporcie).
- `pytest -m "not azure"` w `.venv`: wszystko zielone (165 passed + nowe); vitest bez zmian.
- Commit lokalny, **bez push** (push do main = deploy; robi go sesja po przeglądzie).
