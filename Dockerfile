FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ agent/
COPY api/ api/
COPY ewaluacja/ ewaluacja/
COPY generator/ generator/
COPY migracje/ migracje/
COPY wytyczne/ wytyczne/
# Etap 13: telemetria OpenTelemetry (api.main importuje obserwowalnosc.telemetria).
COPY obserwowalnosc/ obserwowalnosc/
COPY dane/oczekiwane/ dane/oczekiwane/
# Etap 10: RAG po OWU (fragmenty + BM25 lokalny), polisy do sprawdz_polise, atrapa Z01-Z12.
COPY rag/ rag/
COPY ryzyko/ ryzyko/
COPY owu/ owu/
COPY dane/polisy.json dane/polisy.json
COPY dane/szkody/oczekiwane/ dane/szkody/oczekiwane/
COPY alembic.ini .
COPY --chmod=755 docker/start_api.sh docker/start_api.sh

RUN useradd --create-home --uid 1000 uzytkownik
# Cache OCR (agent/ocr_azure.py, KATALOG_CACHE_DOMYSLNY = /app/.cache_ocr) musi byc
# zapisywalny dla uzytkownika - /app nalezy do roota. Bez tego 2026-10-11 w chmurze
# kazdy dokument konczyl sie "Blad wezla 'klasyfikuj' (PermissionError)" po udanym OCR.
RUN mkdir -p /app/.cache_ocr && chown uzytkownik:uzytkownik /app/.cache_ocr
USER uzytkownik

EXPOSE 8000

# Etap 6: docker/start_api.sh uruchamia `alembic upgrade head` przed uvicorn tylko gdy
# MIGRACJE_PRZY_STARCIE=1 (Azure); bez tej zmiennej (docker-compose.yml lokalnie)
# zachowanie identyczne jak dotychczas - od razu uvicorn.
CMD ["docker/start_api.sh"]
