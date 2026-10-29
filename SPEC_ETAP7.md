# SPEC Etap 7 - README dla czytelnika technicznego + dokumentacja

Cel: osoba techniczna w 2-3 minuty rozumie, co to jest, jak dziala, jak jest
zmierzone i wdrozone. Obecny README jest dziennikiem etapow i ma zostac zachowany.

## Zakres

1. `git mv README.md docs/ROZWOJ.md` (tresc bez zmian, poza naglowkiem: dopisz na gorze jedno
   zdanie, ze to dziennik budowy etap po etapie, a opis projektu jest w `../README.md`).
   Popraw w nim linki wzgledne, ktore po przeniesieniu do `docs/` przestana dzialac
   (np. `SPEC_ETAP1.md` -> `../SPEC_ETAP1.md`).
2. Nowy `README.md` (konwencja repo: bez polskich znakow diakrytycznych, zero emoji,
   maks. ok. 150 linii). Sekcje w tej kolejnosci:
   - **Co to jest** (3-4 zdania): asystent underwritera mienia firm; PDF/skan -> OCR ->
     klasyfikacja -> ekstrakcja pol -> walidacja -> rekomendacja LLM + niezalezny
     deterministyczny silnik regul -> decyzja czlowieka (human-in-the-loop) -> audyt.
     Dane w pelni syntetyczne.
   - **Architektura**: diagram mermaid (flowchart) grafu LangGraph wedlug `agent/graf.py`
     (wezly i przejscia warunkowe dokladnie jak w kodzie, wlacznie ze skrotem do
     zatwierdzenia przy bledzie) oraz drugi diagram komponentow: Next.js (proxy
     `app/api/[...sciezka]`) -> FastAPI -> LangGraph + Postgres (checkpointer + tabele).
   - **Stos**: Python 3.14, FastAPI, LangGraph, Pydantic, SQLAlchemy/Alembic, PostgreSQL,
     Next.js 16 + TypeScript + Tailwind, Azure OpenAI / Gemini, Azure Document Intelligence,
     Docker, GitHub Actions, Azure Container Apps. Wersje bierz z `requirements.txt` i
     `frontend/package.json`, nie z pamieci.
   - **Wyniki ewaluacji**: tabela z dwoch zrodel, liczby przepisane z plikow, nie z tego
     SPEC-a:
     - Azure OpenAI: najlepszy przebieg z obecnego README (sekcja Etapu 5/6),
     - Gemini: `ewaluacja/wyniki/20261011-0744_gemini-3.8-flash_myslenie-low.md`
       (w pelni zgodne, decyzje, tokeny, czas).
     Pod tabela 2 zdania: zgodnosc decyzji vs zgodnosc pol; ten sam model dal rozne wyniki
     w kolejnych dniach (niedeterminizm) - to uczciwa informacja, nie ukrywac.
   - **Bezpieczenstwo i nadzor czlowieka**: interrupt przed decyzja, komentarz wymagany przy
     odejsciu od rekomendacji (422), audyt INSERT-only, wykrywanie wstrzykniecia polecen (W13),
     limit wywolan LLM, Easy Auth Entra, Managed Identity, OIDC w CI, API bez publicznego
     ingresu. Kazdy punkt z odnosnikiem `plik:linia` - sprawdz linie w kodzie.
   - **AI Act**: 3 zdania + link do `docs/AI_ACT.md` (nie wysokie ryzyko, bo mienie firm, a
     Zal. III 5(c) to zycie/zdrowie osob fizycznych; mimo to art. 9-15 zmapowane).
   - **Wdrozenie**: Azure Container Apps (swedencentral), ACR, Postgres Flexible
     (polandcentral), Log Analytics, skalowanie do zera (pierwsze zapytanie 20-40 s).
     Bez URL-a produkcyjnego i bez nazw tenantow/subskrypcji. Szczegoly: `SPEC_ETAP6.md`.
   - **Uruchomienie lokalne**: przepisz dzialajace komendy z obecnego README (docker compose,
     testy: `pytest -m "not azure"`, `npm test`). Nie wymyslaj nowych.
   - **Struktura repo**: krotka lista katalogow z jednym zdaniem kazdy.
   - **Dokumentacja**: linki do `docs/ROZWOJ.md`, `docs/AI_ACT.md`, `SPEC_ETAP1-6.md`.

## Ograniczenia

- Zero sekretow, kluczy, adresow e-mail, URL-i uslug Azure, identyfikatorow subskrypcji.
- Nie zmieniaj kodu ani testow. Tylko `README.md`, `docs/ROZWOJ.md`.
- Nie commituj - zleceniodawca przeglada diff.

## Kryteria akceptacji

- Kazda liczba w README ma zrodlo w pliku z repo (podaj w raporcie: liczba -> plik).
- Kazdy `plik:linia` istnieje (sprawdzone grepem).
- Wszystkie linki wzgledne w README.md i docs/ROZWOJ.md wskazuja na istniejace pliki
  (sprawdzone skryptem).
- Diagram mermaid zgodny z `agent/graf.py` (wypisz w raporcie krawedzie z kodu).
- `grep -P '[^\x00-\x7F]' README.md` - pusto.
