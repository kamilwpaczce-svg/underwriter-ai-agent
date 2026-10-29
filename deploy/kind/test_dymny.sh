#!/usr/bin/env bash
# Etap 9: test dymny na klastrze kind (po deploy/kind/uruchom.sh). Kazdy
# niespelniony warunek konczy caly skrypt kodem != 0 (set -e + jawne "exit 1").
#
# Punkty a-e odpowiadaja SPEC_ETAP9.md pkt 2 (test_dymny.sh).
set -euo pipefail

KATALOG_SKRYPTU="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KORZEN_REPO="$(cd "${KATALOG_SKRYPTU}/../.." && pwd)"
KLASTER="underwriter"
# KONTEKST i HOST z otoczenia: ten sam test idzie na AKS (deploy/aks/README.md podaje
# kontekst AKS i adres z kubectl port-forward). Domyslnie kind.
KONTEKST="${KONTEKST:-kind-${KLASTER}}"
WYDANIE="underwriter"
HOST="${HOST:-http://localhost:8080}"
OBRAZ_CURL="curlimages/curl:8.11.1"
DOKUMENT_TESTOWY="${KORZEN_REPO}/dane/wnioski/W01.pdf"

kctl() { kubectl --context "${KONTEKST}" "$@"; }

blad() {
    echo "BLAD: $*" >&2
    exit 1
}

echo "== Etap 9 / deploy/kind/test_dymny.sh =="

# --- a) frontend odpowiada 200 -------------------------------------------------
echo "-- a) GET ${HOST}/ --"
KOD_A="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${HOST}/")"
echo "Status: ${KOD_A}"
[ "${KOD_A}" = "200" ] || blad "Oczekiwano 200 z ${HOST}/, otrzymano ${KOD_A}."

# --- b) utworzenie wniosku przez proxy frontendu + odczyt stanu ---------------
echo "-- b) POST ${HOST}/api/wnioski (dokument: $(basename "${DOKUMENT_TESTOWY}")) --"
[ -f "${DOKUMENT_TESTOWY}" ] || blad "Brak pliku testowego ${DOKUMENT_TESTOWY}."

# curl z katalogu pliku i sama nazwa: w Git Bash natywny curl.exe nie rozumie sciezki
# "/c/Users/..." wewnatrz "plik=@..." (MSYS jej nie tlumaczy) - konczy sie kodem 26.
ODPOWIEDZ_UTWORZ="$(cd "$(dirname "${DOKUMENT_TESTOWY}")" && curl -s -w '\n%{http_code}' --max-time 30 \
    -F "plik=@$(basename "${DOKUMENT_TESTOWY}");type=application/pdf" \
    "${HOST}/api/wnioski")"
KOD_UTWORZ="$(echo "${ODPOWIEDZ_UTWORZ}" | tail -n1)"
CIALO_UTWORZ="$(echo "${ODPOWIEDZ_UTWORZ}" | sed '$d')"
echo "Status utworzenia: ${KOD_UTWORZ}, cialo: ${CIALO_UTWORZ}"
[ "${KOD_UTWORZ}" = "202" ] || blad "Oczekiwano 202 z POST /api/wnioski, otrzymano ${KOD_UTWORZ}."

WNIOSEK_ID="$(echo "${CIALO_UTWORZ}" | jq -r '.id')"
[ -n "${WNIOSEK_ID}" ] && [ "${WNIOSEK_ID}" != "null" ] || blad "Brak 'id' w odpowiedzi POST /api/wnioski."
echo "Wniosek: ${WNIOSEK_ID}"

echo "Czekam na przetworzenie (atrapa, timeout 30s)..."
STATUS=""
for _ in $(seq 1 60); do
    STATUS="$(curl -s --max-time 10 "${HOST}/api/wnioski/${WNIOSEK_ID}" | jq -r '.status')"
    case "${STATUS}" in
        PRZETWARZANIE) sleep 0.5 ;;
        *) break ;;
    esac
done
echo "Status koncowy: ${STATUS}"
[ "${STATUS}" = "CZEKA_NA_DECYZJE" ] || [ "${STATUS}" = "ZAKONCZONY" ] || [ "${STATUS}" = "INNY_DOKUMENT" ] \
    || blad "Wniosek ${WNIOSEK_ID} nie przeszedl przetwarzania (status: ${STATUS})."

# --- c) restart poda API -> stan w Postgresie przetrwal ------------------------
echo "-- c) kubectl delete pod (api) -> ten sam wniosek nadal istnieje --"
POD_API="$(kctl get pod -l app.kubernetes.io/component=api -o jsonpath='{.items[0].metadata.name}')"
[ -n "${POD_API}" ] || blad "Nie znaleziono poda API (etykieta app.kubernetes.io/component=api)."
echo "Usuwam pod ${POD_API}..."
kctl delete pod "${POD_API}"

echo "Czekam na nowy pod API (Ready)..."
# NIE "rollout status": zaraz po delete Deployment wciaz raportuje stary stan (1/1
# available) i komenda konczy sie od razu, zanim nowy pod przejdzie initContainer -
# w CI 14.10 frontend dostal 502 dziewiec sekund po usunieciu poda. Czekamy na pod
# o INNEJ nazwie niz usuniety, z warunkiem Ready.
nowy_pod_api_gotowy() {
    kctl get pod -l app.kubernetes.io/component=api -o json \
        | jq -e --arg stary "${POD_API}" '[.items[]
            | select(.metadata.name != $stary and .metadata.deletionTimestamp == null)
            | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))
          ] | length > 0' >/dev/null
}
KONIEC_C=$(( $(date +%s) + 180 ))
until nowy_pod_api_gotowy; do
    [ "$(date +%s)" -lt "${KONIEC_C}" ] || blad "Nowy pod API nie byl Ready przez 180 s po usunieciu ${POD_API}."
    sleep 3
done

echo "Odczytuje ten sam wniosek po restarcie poda..."
# Ponowienie TYLKO przy 502 (frontend nie dosiegnal API): miedzy Ready poda a
# dopisaniem go do endpointow Service mija chwila. 404 = wniosek zniknal -> od razu blad.
for PROBA in 1 2 3 4 5; do
    ODPOWIEDZ_PO_RESTARCIE="$(curl -s -w '\n%{http_code}' --max-time 15 "${HOST}/api/wnioski/${WNIOSEK_ID}")"
    KOD_PO_RESTARCIE="$(echo "${ODPOWIEDZ_PO_RESTARCIE}" | tail -n1)"
    [ "${KOD_PO_RESTARCIE}" = "502" ] || break
    echo "Proba ${PROBA}: 502, ponawiam za 2 s..."
    sleep 2
done
CIALO_PO_RESTARCIE="$(echo "${ODPOWIEDZ_PO_RESTARCIE}" | sed '$d')"
echo "Status: ${KOD_PO_RESTARCIE}, cialo: ${CIALO_PO_RESTARCIE}"
[ "${KOD_PO_RESTARCIE}" = "200" ] || blad "Wniosek ${WNIOSEK_ID} zniknal po restarcie poda API (kod ${KOD_PO_RESTARCIE})."
ID_PO_RESTARCIE="$(echo "${CIALO_PO_RESTARCIE}" | jq -r '.id')"
[ "${ID_PO_RESTARCIE}" = "${WNIOSEK_ID}" ] || blad "Niezgodnosc id po restarcie poda."

# --- d) NetworkPolicy dziala naprawde (oba stany) ------------------------------
# Jednorazowy pod z curl do /zdrowie API; wynik w KOD_CURL i WYJSCIE_CURL.
# Bez "kubectl run -i --rm": w CI szybki pod konczyl sie, zanim kubectl sie podlaczyl,
# i wyjscie przepadalo ("pod ... terminated (Error)" zamiast odpowiedzi, 14.10).
# Kod wyjscia czytamy ze statusu poda, odpowiedz z "kubectl logs".
curl_z_poda() {  # nazwa, etykiety ("" = brak), limit czasu curla [s]
    local nazwa="$1" etykiety="$2" limit="$3" faza="" koniec
    kctl delete pod "${nazwa}" --ignore-not-found >/dev/null 2>&1 || true
    MSYS_NO_PATHCONV=1 kctl run "${nazwa}" --restart=Never --image="${OBRAZ_CURL}" \
        ${etykiety:+--labels="${etykiety}"} \
        --command -- curl --fail --silent --show-error --max-time "${limit}" \
        "http://${WYDANIE}-api:8000/zdrowie" >/dev/null
    koniec=$(( $(date +%s) + 120 ))
    until faza="$(kctl get pod "${nazwa}" -o jsonpath='{.status.phase}')"; \
        [ "${faza}" = "Succeeded" ] || [ "${faza}" = "Failed" ]; do
        [ "$(date +%s)" -lt "${koniec}" ] || blad "Pod ${nazwa} nie zakonczyl sie w 120 s (faza: ${faza})."
        sleep 2
    done
    WYJSCIE_CURL="$(kctl logs "${nazwa}" 2>&1 || true)"
    KOD_CURL="$(kctl get pod "${nazwa}" -o jsonpath='{.status.containerStatuses[0].state.terminated.exitCode}')"
    kctl delete pod "${nazwa}" --ignore-not-found >/dev/null 2>&1 || true
}

echo "-- d) NetworkPolicy: pod bez etykiet vs pod z etykieta frontendu --"

echo "   * pod BEZ etykiet -> oczekiwana ODMOWA (timeout)"
curl_z_poda siec-test-brak-etykiety "" 5
echo "     Wyjscie curla: ${WYJSCIE_CURL}"
echo "     Kod wyjscia: ${KOD_CURL}"
[ "${KOD_CURL}" != "0" ] || blad "Pod bez etykiet DOSTAL SIE do API - NetworkPolicy nie dziala."
# Tylko 28 (timeout curla) to odmowa przez polityke. Inny kod (6 = DNS, 7 = odrzucone
# polaczenie, blad obrazu/poda) znaczy, ze test nie sprawdzil polityki - nie zaliczamy.
[ "${KOD_CURL}" = "28" ] || blad "Oczekiwano timeoutu (curl 28), otrzymano ${KOD_CURL} - test nie dowodzi blokady."
echo "     OK - odmowa potwierdzona (pod bez etykiet nie dostal sie do API)."

echo "   * pod Z ETYKIETA frontendu -> oczekiwane DOPUSZCZENIE (200)"
curl_z_poda siec-test-z-etykieta-frontend "app.kubernetes.io/component=frontend" 10
echo "     Odpowiedz API: ${WYJSCIE_CURL} (kod curla ${KOD_CURL})"
[ "${KOD_CURL}" = "0" ] && echo "${WYJSCIE_CURL}" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' \
    || blad "Pod z etykieta frontendu NIE dostal sie do API (NetworkPolicy za bardzo restrykcyjna)."
echo "     OK - dopuszczenie potwierdzone (pod z etykieta frontendu dostal sie do API)."

# --- e) helm test ---------------------------------------------------------------
echo "-- e) helm test --"
helm test "${WYDANIE}" --kube-context "${KONTEKST}" --timeout 2m \
    || blad "helm test nie przeszedl."

echo ""
echo "== Test dymny: WSZYSTKO OK =="
