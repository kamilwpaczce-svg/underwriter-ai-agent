# Etap 4 — panel underwritera (frontend)

Next.js 16 (App Router, React 19, TypeScript, Tailwind v4) — panel do przegladania
wnioskow przetworzonych przez agenta AI (Etap 1-3) i podejmowania decyzji
underwritingowych. Caly frontend jest renderowany po stronie klienta i rozmawia
bezposrednio z API Etapu 3 (bez proxy przez Next.js route handlers).

## Uruchomienie lokalne

Wymaga dzialajacego API Etapu 3 (patrz glowny `README.md` repo) — domyslnie
pod `http://localhost:8000`.

```bash
npm install
npm run dev
```

Aplikacja wystartuje na `http://localhost:3000`.

### Zmienne srodowiskowe

| Zmienna | Domyslna wartosc | Opis |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Adres API Etapu 3. Zapiekany w bundlu klienckim w czasie builda (`NEXT_PUBLIC_*`), wiec przy Dockerze trzeba go podac jako build-arg, nie runtime env. |

Przyklad: `frontend/.env.example`.

## Testy

```bash
npm run lint   # ESLint (eslint-config-next)
npm run build  # produkcyjny build Next.js (weryfikuje tez TypeScript)
npm test       # Vitest + React Testing Library — testy jednostkowe lib/ i components/
npm run e2e    # Playwright (Chrome) — testy e2e na ZYWYM API Etapu 3 (musi juz dzialac na :8000)
```

`npm run e2e` sam startuje `next dev` na porcie 3000 (Playwright `webServer`,
`reuseExistingServer: false`) i gasi go po zakonczeniu testow — nie wymaga
recznie odpalonego `npm run dev`. NIE startuje ani nie gasi API/Dockera —
to musi juz dzialac wczesniej.

## Docker

```bash
# z katalogu glownego repo (underwriter_agent_demo/):
docker build -t underwriter-frontend ./frontend

# uruchomienie razem z reszta stosu (profil "frontend", osobny od "api"):
docker compose --profile frontend up
```

`NEXT_PUBLIC_API_URL` jest build-argiem w `Dockerfile` (domyslnie
`http://localhost:8000`) — zeby zmienic adres API dla zbudowanego obrazu,
trzeba przebudowac obraz z innym `--build-arg NEXT_PUBLIC_API_URL=...`.

## Decyzje projektowe

### 1. Architektura "tylko fetch z klienta"

Wszystkie wywolania sieciowe ida wprost z przegladarki do API Etapu 3 (CORS
po stronie API juz dopuszcza `localhost:3000`), bez route handlers/proxy w
Next.js. Jedynym modulem, ktory wywoluje `fetch`, jest `lib/api.ts` —
komponenty nigdy nie woluja `fetch` bezposrednio. To upraszcza demo (brak
drugiej warstwy serwerowej do utrzymania, brak powielania typow miedzy
server/client) kosztem tego, ze sekrety API (gdyby jakies byly) musialyby
byc publiczne — w tym demie API nie wymaga zadnej autoryzacji, wiec koszt
jest zerowy.

### 2. Dlaczego `X-Uzytkownik` musi byc ASCII

Naglowki HTTP nie maja gwarantowanego, uniwersalnego traktowania znakow
spoza ASCII (roznie w zaleznosci od serwera/proxy/biblioteki klienckiej —
ryzyko cichego mojibake albo wyjatku przy serializacji). Zamiast ryzykowac,
identyfikator underwritera jest ograniczony regexem
`^[A-Za-z0-9._-]{2,40}$` (bez polskich znakow diakrytycznych) — walidowany
identycznie po stronie klienta (`lib/walidacja.ts`) i (zgodnie ze specyfikacja)
po stronie API.

### 3. Celowo zdublowana walidacja "komentarz wymagany"

Logika `czyWymaganyKomentarz` (`lib/decyzja.ts`) odtwarza DOKLADNIE regule
serwera z `api/trasy.py:177`
(`decyzja != rekomendacja or decyzja != silnik_decyzja`). Duplikacja jest
swiadoma: klient daje natychmiastowy feedback UX (blokuje przycisk, zanim
padnie zadanie sieciowe), ale serwer pozostaje jedynym zrodlem prawdy — API
i tak zwroci 422, gdy klient o czyms zapomni albo logika sie rozjedzie z
czasem. Gdyby kiedys zmienila sie regula serwera, trzeba pamietac o
rownoleglej zmianie tutaj (nie ma jednego wspolnego zrodla typow miedzy
Python a TypeScript w tym demie).
