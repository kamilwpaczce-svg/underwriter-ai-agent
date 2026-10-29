# Etap 4 — panel underwritera (Next.js)

Cel: interfejs w przeglądarce na API z etapu 3. Underwriter wgrywa dokument, widzi,
co agent wyciągnął i co rekomenduje, porównuje to z silnikiem reguł i podejmuje decyzję.
Zasada demo zostaje: **LLM rekomenduje, silnik reguł kontroluje, człowiek decyduje.**

## Zakres

- Katalog `frontend/` w repo demo. Kod Pythona z etapów 1–3 **bez zmian** (wyjątek: sekcja README).
- Next.js 16 (App Router), TypeScript `strict`, ESLint. Stylowanie: Tailwind z `create-next-app`
  albo zwykłe CSS modules. Bez bibliotek komponentów (shadcn, MUI) — mniej zależności, demo ma być czytelne.
- **Wszystkie wywołania API z przeglądarki** (komponenty klienckie, `fetch`). API ma CORS dla
  `http://localhost:3000`. Nie robić proxy przez route handlers Next.js.
- Adres API ze zmiennej `NEXT_PUBLIC_API_URL`, domyślnie `http://localhost:8000`. Plik `frontend/.env.example`.
- Jeden moduł klienta API (`lib/api.ts`) z typami odpowiadającymi `api/schematy_api.py`.
  Komponenty nie wołają `fetch` bezpośrednio.
- Interfejs po polsku, z polskimi znakami (UTF-8). Bez emoji.
- Brak logowania (demo). Tożsamość underwritera: patrz „Decyzja”.

## Kontrakt API (etap 3, `SPEC_ETAP3.md`)

| metoda | ścieżka | uwagi |
|---|---|---|
| POST | `/wnioski` | multipart, pole `plik`; `.pdf/.jpg/.jpeg/.eml`, maks. 10 MB; 202 `{id, status}` |
| GET | `/wnioski?status=&limit=` | lista `{id, nazwa_pliku, status, decyzja_koncowa, utworzono, zakonczono}` |
| GET | `/wnioski/{id}` | szczegóły, w tym `podsumowanie` (niżej) |
| GET | `/wnioski/{id}/dokument` | surowe bajty, `Content-Type` = `typ_mime` wniosku |
| POST | `/wnioski/{id}/decyzja` | nagłówek `X-Uzytkownik`, body `{decyzja, komentarz?}` |
| GET | `/wnioski/{id}/audyt` | `[{id, czas, zdarzenie, kto, dane}]` |
| GET | `/zdrowie` | `{status: "ok"}` |

Statusy: `PRZETWARZANIE`, `CZEKA_NA_DECYZJE`, `ZAKONCZONY`, `INNY_DOKUMENT`, `BLAD`.
Decyzje: `AKCEPTACJA`, `ODMOWA`, `UZUPELNIENIE`, `SKIEROWANIE`.
Zdarzenia audytu: `PRZYJETO`, `REKOMENDACJA`, `DECYZJA`, `BLAD` (i ewentualne inne — wyświetlać generycznie).

Kształt `podsumowanie` (żywa odpowiedź dla W01, model atrapa):

```json
{
  "blad": null,
  "plik": "C:\\...\\tmpXXXX.pdf",
  "typ_dokumentu": "WNIOSEK",
  "pola": {
    "nazwa_firmy": "Hurtownia Wisła Sp. z o.o.", "nip": "1234563201",
    "adres": {"ulica": "ul. Zbożowa 12", "kod": "05-500", "miasto": "Piaseczno"},
    "pkd": "46.49.Z", "branza": "...", "rodzaj_konstrukcji": "niepalna", "rok_budowy": 2005,
    "su_budynki": 1800000, "su_maszyny": 400000, "su_zapasy": 1000000,
    "tryskacze": false, "ssp": false, "strefa_powodziowa": false,
    "szkody_3_lata": [], "okres_od": "2026-11-01", "okres_do": "2027-10-31",
    "data_wniosku": "2026-09-20", "broker": "...", "uwagi": null
  },
  "problemy_walidacji": [],
  "rekomendacja": {"decyzja": "AKCEPTACJA", "reguly": [], "uzasadnienie": [{"regula": "OGOLNE", "tekst": "..."}]},
  "decyzja_silnika": {"decyzja": "AKCEPTACJA", "reguly": []},
  "zgodnosc": true,
  "podejrzane_instrukcje": false
}
```

- Pole `plik` to ścieżka tymczasowa serwera — **nie wyświetlać**.
- Struktura `szkody_3_lata` i elementów `reguly` — sprawdzić na żywym API (W02–W07 mają reguły i szkody)
  i odwzorować w typach. Nie zgadywać: uruchomić, odczytać, dopiero pisać typy.
- `podsumowanie` może być `null` (PRZETWARZANIE, BLAD, INNY_DOKUMENT) — UI musi to znieść.

## Ekrany

### 1. Lista wniosków (`/`)

- Tabela: nazwa pliku, status (etykieta kolorem), decyzja końcowa, utworzono, zakończono. Wiersz → szczegóły.
- Filtr statusu (wszystkie / każdy status). Sortowanie: najnowsze na górze (tak zwraca API).
- Upload: wybór pliku lub przeciągnij-upuść. Walidacja po stronie klienta (rozszerzenie, 10 MB)
  **i** wyświetlenie błędu z API (`detail`), jeśli serwer odrzuci. Po sukcesie — przejście do szczegółów.
- Odświeżanie: co 2 s, **tylko gdy** na liście jest wniosek w `PRZETWARZANIE`. Bez wiecznego pollingu.
- Wskaźnik stanu API z `/zdrowie` (ok / brak połączenia). Przy braku połączenia — czytelny komunikat
  z adresem API, nie pusta strona.

### 2. Szczegóły wniosku (`/wnioski/[id]`)

Układ dwukolumnowy: lewa — dokument, prawa — analiza i decyzja.

- **Dokument:** PDF w `<iframe>`/`<object>`, JPG w `<img>`, `.eml` — link „Pobierz plik” (bez renderowania maila).
- **PRZETWARZANIE:** komunikat „Agent analizuje dokument”, polling co 1,5 s do zmiany statusu.
- **INNY_DOKUMENT:** komunikat, że dokument nie jest wnioskiem; brak formularza decyzji.
- **BLAD:** komunikat + treść błędu z audytu (`dane.blad` / `dane.powod`); brak formularza.
- **Baner AI** (zawsze przy rekomendacji): „Rekomendacja wygenerowana przez model AI. Decyzję podejmuje
  underwriter.” — przejrzystość pod AI Act, nie ozdobnik.
- **Ostrzeżenie `podejrzane_instrukcje`** (W13): wyraźny czerwony baner — dokument zawiera treść
  przypominającą polecenia dla modelu; rekomendację traktować z ostrożnością.
- **Pola wniosku:** czytelna tabela z polskimi etykietami (mapa klucz → etykieta), kwoty sformatowane
  `Intl.NumberFormat('pl-PL')` z „zł”, boolean jako Tak/Nie, `null` jako „—”, adres w jednej linii,
  `szkody_3_lata` jako podtabela.
- **Problemy walidacji:** lista, jeśli niepusta (żółty blok).
- **Rekomendacja LLM vs silnik reguł** — dwie karty obok siebie: decyzja, reguły, uzasadnienie
  (reguła + tekst). Gdy `zgodnosc === false` — wyraźna flaga „Rozbieżność LLM i silnika reguł”.
- **Przebieg agenta:** tabela `log_wezlow` (węzeł, czas ms, tokeny we/wy) + suma: wywołania LLM, tokeny.
- **ZAKONCZONY:** decyzja końcowa, kto zatwierdził, komentarz, kiedy. Formularza nie ma.

### 3. Decyzja (w szczegółach, tylko `CZEKA_NA_DECYZJE`)

- Wybór jednej z 4 decyzji (radio/przyciski). Domyślnie **nic nie zaznaczone** — człowiek wybiera świadomie.
- Pole „Twój identyfikator” (`X-Uzytkownik`), zapamiętywane w `localStorage`.
  **Tylko ASCII** (`^[A-Za-z0-9._-]{2,40}$`, np. `a.nowak`): przeglądarka nie wyśle nagłówka
  ze znakami spoza ISO-8859-1 (`fetch` rzuca wyjątek dla „ń”). Walidacja z komunikatem.
- Komentarz: textarea. **Wymagany, gdy wybrana decyzja ≠ rekomendacja LLM lub ≠ decyzja silnika** —
  ta sama reguła co w `api/trasy.py` (`odejscie_od_rekomendacji`). Funkcja czysta w `lib/`,
  przetestowana. Etykieta zmienia się na „Komentarz (wymagany — odchodzisz od rekomendacji)”.
- Przycisk zatwierdzenia nieaktywny, dopóki formularz niepoprawny. Podwójne kliknięcie nie wysyła dwa razy.
- Błędy serwera pokazać dosłownie: 409 (ktoś już zdecydował / zmiana statusu) → komunikat + odświeżenie
  danych; 422 → `detail`; 500 → komunikat ogólny. Walidacja klienta jest wygodą, **serwer jest źródłem
  prawdy** — nie ukrywać jego odpowiedzi.
- Po sukcesie: odświeżenie szczegółów i audytu.

### 4. Ślad audytowy (w szczegółach)

- Oś czasu: czas (lokalny, `pl-PL`), zdarzenie, kto (`system`, gdy `null`), rozwijane `dane` jako
  sformatowany JSON. Dla `DECYZJA` wyróżnić `odejscie_od_rekomendacji: true`.
- Podpis: „Zapis tylko do dopisywania — zdarzeń nie można edytować ani usuwać.” (prawda w API: tylko INSERT).

## Testy (wynik ma być weryfikowalny)

1. `npm run lint` i `npm run build` — bez błędów, bez ostrzeżeń TypeScript.
2. **Vitest + React Testing Library** (`npm test`):
   - reguła wymaganego komentarza: wszystkie kombinacje (decyzja = obie / = tylko LLM / = tylko silnik / ≠ obu,
     brak `podsumowanie`);
   - walidacja identyfikatora (ASCII, „Kusiński” odrzucone);
   - walidacja pliku (rozszerzenie, rozmiar);
   - formatowanie pól (kwota, boolean, null, adres);
   - formularz decyzji: przycisk nieaktywny bez komentarza przy odejściu; aktywny przy zgodnej decyzji;
     wysyła poprawny nagłówek i body (mock `fetch`);
   - widok szczegółów renderuje baner `podejrzane_instrukcje` i flagę rozbieżności z danych testowych.
3. **Playwright e2e** (`npm run e2e`) na **żywym API z modelem atrapa** (`http://localhost:8000`, już
   uruchomione — nie startować drugiego, nie zatrzymywać istniejącego) i `next dev`/`next start` na :3000:
   - Użyć **zainstalowanego Chrome** (`channel: 'chrome'`), żeby nie ściągać przeglądarek Playwrighta.
   - Scenariusze (pliki z `../dane/wnioski/`):
     - W01: upload → PRZETWARZANIE → CZEKA_NA_DECYZJE; decyzja zgodna bez komentarza → ZAKONCZONY;
       w audycie jest `DECYZJA` z identyfikatorem;
     - wniosek z regułą (wybrać z W02–W07 ten, gdzie rekomendacja ≠ AKCEPTACJA): wybranie AKCEPTACJI
       blokuje przycisk do wpisania komentarza; po komentarzu → ZAKONCZONY, audyt `odejscie_od_rekomendacji: true`;
     - W13: widoczny baner podejrzanych instrukcji;
     - W14: status INNY_DOKUMENT, brak formularza;
     - plik `.txt`: błąd walidacji bez wysyłki;
     - API wyłączone nie jest testowane w e2e (byłoby niszczące dla działającego serwera) — pokryć testem
       jednostkowym komponentu stanu API z mockiem `fetch`.
   - e2e tworzy nowe wnioski w lokalnej bazie — to akceptowalne (dane fikcyjne).
4. **Zero wywołań Gemini / płatnych API.** Nie czytać plików z kluczami (`~/.gemini_api_key*`), nie ustawiać
   `MODEL_AGENTA=gemini`.

## Wdrożenie (pod etap 6)

- `next.config`: `output: 'standalone'`.
- `frontend/Dockerfile` wieloetapowy (node:22-alpine lub nowszy LTS), użytkownik nie-root, port 3000.
  `NEXT_PUBLIC_API_URL` jako `ARG` w czasie budowania (zmienne `NEXT_PUBLIC_*` są wkompilowane).
  Zbudować obraz raz lokalnie, jeśli Docker działa (`docker build`), i odnotować wynik.
- `docker-compose.yml`: dodać usługę `frontend` w profilu (jak `api`), bez zmiany usług istniejących.

## Dokumentacja

- `frontend/README.md`: uruchomienie (API + `npm run dev`), zmienne, testy, decyzje projektowe (wywołania
  z przeglądarki, ASCII w nagłówku, reguła komentarza zdublowana świadomie: klient = wygoda, serwer = prawda).
- `README.md` w katalogu głównym: krótka sekcja „Etap 4” z linkiem do `frontend/README.md`.

## Czego NIE robić

- Nie zmieniać kodu Pythona etapów 1–3 ani migracji. Jeśli API ma błąd lub brakuje pola — opisać w raporcie,
  nie łatać.
- Nie publikować niczego (GitHub, Vercel, Azure). Nie tworzyć zasobów w chmurze.
- Nie zatrzymywać działającego API ani kontenerów `underwriter_agent_demo-*`.
- Nie dodawać autoryzacji, i18n, trybu ciemnego ani innych ozdobników spoza zakresu.
