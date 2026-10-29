#!/usr/bin/env bash
# Etap 9: sprzatanie po testach - usuwa caly klaster kind (nic nie zostaje, wlacznie
# z danymi Postgresa na PVC, ktory zyje tylko wewnatrz tego klastra).
set -euo pipefail

KLASTER="underwriter"

echo "Usuwam klaster kind '${KLASTER}'..."
kind delete cluster --name "${KLASTER}"
