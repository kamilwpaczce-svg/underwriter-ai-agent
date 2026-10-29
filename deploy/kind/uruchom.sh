#!/usr/bin/env bash
# Etap 9: idempotentne uruchomienie calej aplikacji (API + frontend + Postgres +
# Azurite) na lokalnym klastrze kind, chartem Helm z deploy/helm/underwriter/.
#
# Dziala w Git Bash na Windows ORAZ na ubuntu w CI (job "k8s",
# .github/workflows/ci-cd.yml) - stad brak twardych sciezek do kind/helm (maja byc
# w PATH wywolujacej powloki, patrz README tego katalogu/polecenie sesji).
set -euo pipefail

KATALOG_SKRYPTU="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KORZEN_REPO="$(cd "${KATALOG_SKRYPTU}/../.." && pwd)"
KLASTER="underwriter"
KONTEKST="kind-${KLASTER}"
WYDANIE="underwriter"
# Manifest Calico przypiety do konkretnej wersji - domyslny CNI kind (kindnet) NIE
# egzekwuje NetworkPolicy (patrz kind-config.yaml i docs/ROZWOJ.md, Etap 9).
CALICO_MANIFEST="https://raw.githubusercontent.com/projectcalico/calico/v3.28.0/manifests/calico.yaml"

echo "== Etap 9 / deploy/kind/uruchom.sh =="

# --- 1. Klaster kind (idempotentnie) ------------------------------------------
if kind get clusters 2>/dev/null | grep -qx "${KLASTER}"; then
    echo "Klaster kind '${KLASTER}' juz istnieje - pomijam tworzenie."
else
    echo "Tworze klaster kind '${KLASTER}'..."
    kind create cluster --name "${KLASTER}" --config "${KATALOG_SKRYPTU}/kind-config.yaml"
fi

# --- 2. CNI (Calico) - bez tego nody zostana NotReady na zawsze ----------------
if kubectl --context "${KONTEKST}" get namespace calico-system >/dev/null 2>&1 \
    || kubectl --context "${KONTEKST}" -n kube-system get daemonset calico-node >/dev/null 2>&1; then
    echo "Calico juz zainstalowane - pomijam."
else
    echo "Instaluje Calico (CNI z realnym egzekwowaniem NetworkPolicy)..."
    kubectl --context "${KONTEKST}" apply -f "${CALICO_MANIFEST}"
fi

echo "Czekam, az wezly beda Ready (CNI musi wstac)..."
kubectl --context "${KONTEKST}" wait --for=condition=Ready nodes --all --timeout=180s
echo "Czekam, az calico-node bedzie gotowe..."
kubectl --context "${KONTEKST}" -n kube-system rollout status daemonset/calico-node --timeout=180s

# --- 3. Tag obrazow = krotki SHA (+ "-dirty" przy niezcommitowanych zmianach) --
cd "${KORZEN_REPO}"
SHA="$(git rev-parse --short HEAD)"
if ! git diff --quiet || ! git diff --cached --quiet; then
    # Skrot diffu w tagu: samo "-dirty" bylo identyczne dla kazdej kolejnej zmiany,
    # wiec szablon poda sie nie zmienial i Kubernetes nie restartowal API - nowy
    # kod lezal w klastrze, a dzialal stary (14.10). Pliki nieSLEDZONE nie wchodza
    # do skrotu - przed testem zmiany w nowych plikach trzeba dodac do indeksu.
    SHA="${SHA}-dirty-$(git diff HEAD | git hash-object --stdin | cut -c1-7)"
fi
echo "Tag obrazow: ${SHA}"

# --- 4. Budowa obrazow i zaladowanie ich do klastra (bez rejestru) -------------
echo "Buduje obraz API (underwriter-api:${SHA})..."
docker build -t "underwriter-api:${SHA}" "${KORZEN_REPO}"
echo "Buduje obraz frontendu (underwriter-frontend:${SHA})..."
docker build -t "underwriter-frontend:${SHA}" "${KORZEN_REPO}/frontend"

echo "Laduje obrazy do klastra kind (kind load docker-image)..."
kind load docker-image "underwriter-api:${SHA}" --name "${KLASTER}"
kind load docker-image "underwriter-frontend:${SHA}" --name "${KLASTER}"

# --- 5. helm upgrade --install ----------------------------------------------
# --wait-for-jobs: Job migracji (job-migracje.yaml) jest zwyklym zasobem, nie hookiem -
# bez tej flagi Helm uznalby wydanie za udane mimo nieudanej migracji.
echo "helm upgrade --install (--wait --wait-for-jobs, timeout 5m)..."
helm upgrade --install "${WYDANIE}" "${KORZEN_REPO}/deploy/helm/underwriter" \
    --kube-context "${KONTEKST}" \
    --wait --wait-for-jobs --timeout 5m \
    --set "api.image.tag=${SHA}" \
    --set "frontend.image.tag=${SHA}"

echo ""
echo "== Gotowe =="
echo "Frontend: http://localhost:8080"
echo "(NodePort 30080 wewnatrz klastra -> host :8080, patrz kind-config.yaml)"
