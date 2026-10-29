#!/bin/sh
# Etap 6: migracje Alembic przy starcie kontenera API, tylko gdy jawnie wlaczone.
#
# MIGRACJE_PRZY_STARCIE=1 (Azure Container Apps - zaslepka obrazu nie ma dostepu do
# `.venv\Scripts\python -m alembic upgrade head` z hosta): uruchom migracje, a dopiero
# potem uvicorn. `set -e` powoduje, ze blad migracji (niezerowy kod wyjscia `alembic`)
# konczy caly skrypt tym samym niezerowym kodem - kontener NIE wstaje cicho bez schematu.
#
# Bez zmiennej (domyslnie, docker-compose.yml lokalnie): zachowanie jak dotychczas -
# zero migracji tutaj, od razu uvicorn (schemat zaklada sie, ze jest juz zastosowany
# recznie, patrz README "Uruchomienie lokalne").
set -e

if [ "${MIGRACJE_PRZY_STARCIE:-0}" = "1" ]; then
    echo "MIGRACJE_PRZY_STARCIE=1 - uruchamiam 'alembic upgrade head'..."
    alembic upgrade head
fi

exec uvicorn api.main:app --host 0.0.0.0 --port 8000
