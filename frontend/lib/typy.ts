/**
 * Typy TypeScript odpowiadajace ksztaltom z `api/schematy_api.py` i
 * `agent/schematy.py` (Etap 3). Zrodlo prawdy: zweryfikowane na zywym API
 * (patrz SPEC_ETAP4.md i opis zadania), nie zgadywane.
 */

export type Status =
  | "PRZETWARZANIE"
  | "CZEKA_NA_DECYZJE"
  | "ZAKONCZONY"
  | "INNY_DOKUMENT"
  | "BLAD";

/**
 * Decyzje mozliwe do wyslania przez underwritera. AKCEPTACJA tylko dla wniosku,
 * POKRYTA tylko dla zgloszenia szkody (API odrzuca krzyzowe kombinacje kodem 422).
 */
export type Decyzja = "AKCEPTACJA" | "POKRYTA" | "ODMOWA" | "UZUPELNIENIE" | "SKIEROWANIE";

/**
 * `decyzja_koncowa` zwracany przez API bywa tez "NIE_DOTYCZY" (dla
 * INNY_DOKUMENT) - typowane jako zwykly string, nie literal ograniczony do
 * 4 wartosci decyzji.
 */
export type DecyzjaKoncowa = string | null;

export interface Adres {
  ulica: string | null;
  kod: string | null;
  miasto: string | null;
}

export interface Szkoda {
  rok: number | null;
  przyczyna: string | null;
  kwota: number | null;
}

export type RodzajKonstrukcji =
  | "niepalna"
  | "drewniana"
  | "plyta_warstwowa_eps"
  | "mieszana";

export interface Pola {
  nazwa_firmy: string | null;
  nip: string | null;
  adres: Adres | null;
  pkd: string | null;
  branza: string | null;
  rodzaj_konstrukcji: RodzajKonstrukcji | string | null;
  rok_budowy: number | null;
  su_budynki: number | null;
  su_maszyny: number | null;
  su_zapasy: number | null;
  tryskacze: boolean | null;
  ssp: boolean | null;
  strefa_powodziowa: boolean | null;
  szkody_3_lata: Szkoda[] | null;
  okres_od: string | null;
  okres_do: string | null;
  data_wniosku: string | null;
  broker: string | null;
  uwagi: string | null;
}

export interface Uzasadnienie {
  regula: string;
  tekst: string;
}

export interface Rekomendacja {
  decyzja: string;
  reguly: string[];
  uzasadnienie: Uzasadnienie[];
}

export interface DecyzjaSilnika {
  decyzja: string;
  reguly: string[];
}

export interface Podsumowanie {
  blad: string | null;
  /** Sciezka tymczasowa serwera - NIE wyswietlac w UI. */
  plik: string | null;
  typ_dokumentu: string | null;
  pola: Pola | null;
  /** null, gdy graf ominal wezel waliduj (blad klasyfikacji/ekstrakcji). */
  problemy_walidacji: string[] | null;
  rekomendacja: Rekomendacja | null;
  decyzja_silnika: DecyzjaSilnika | null;
  zgodnosc: boolean | null;
  podejrzane_instrukcje: boolean;
}

/** Pola zgloszenia szkody (`agent/schematy.py: PolaSzkody`). */
export interface PolaSzkody {
  nr_polisy: string | null;
  ubezpieczony: string | null;
  nip: string | null;
  data_zdarzenia: string | null;
  data_zgloszenia: string | null;
  miejsce: Adres | null;
  przyczyna: string | null;
  rodzaj_mienia: string | null;
  szacowana_kwota: number | null;
  zalaczniki: string[] | null;
  okolicznosci: string | null;
}

/** Wynik `agent/polisy.py: sprawdz_polise` (kody S01-S04). */
export interface WynikPolisy {
  kody: string[];
  braki: string[];
  opis: string[];
  suma_ubezpieczenia: number | null;
  dni_do_zgloszenia: number | null;
}

/** Cytat z OWU wskazany przez model, uzupelniony przez serwer o pelna tresc ustepu. */
export interface CytatOwu {
  paragraf: string;
  ustep: string;
  uzasadnienie: string;
  /** null, gdy ustep nie byl wsrod pobranych fragmentow (kontrola cytatow go odrzuca). */
  fragment_id: string | null;
  tresc: string | null;
}

export interface KontrolaCytatow {
  ok: boolean;
  powod: string | null;
  odrzucone: { paragraf: string; ustep: string; uzasadnienie: string }[];
}

/**
 * Sygnal ryzyka modelu ML (Etap 15; `agent/decyzje_szkody.py: _ryzyko_do_panelu`). To pomoc dla
 * likwidatora, nigdy decyzja. Surowych cech nie ma - tylko wynik, wersja i nazwy glownych cech.
 */
export interface RyzykoSzkody {
  status: "OK" | "BRAK_DANYCH" | "MODEL_NIEDOSTEPNY";
  wynik?: number | null;
  wersja?: string | null;
  glowne_cechy?: string[];
}

export type RodzajZdarzenia =
  | "pozar"
  | "zalanie"
  | "przepiecie"
  | "kradziez_wlamanie"
  | "huragan_wiatr"
  | "korozja_zawilgocenie"
  | "awaria_wewnetrzna"
  | "inne";

/** Opis zdjecia przez model vision (`agent/schematy.py: OcenaZdjecia`); model nie widzial zgloszonej przyczyny. */
export interface OcenaZdjecia {
  czy_widac_szkode: boolean;
  rodzaj_zdarzenia: RodzajZdarzenia;
  widoczne_mienie: string[];
  dlugotrwalosc: "NAGLE" | "DLUGOTRWALE" | "NIEOKRESLONE";
  oznaki: string[];
  pewnosc: number;
  tekst_na_zdjeciu: boolean;
}

/**
 * Sygnal ze zdjecia szkody (Etap 23; `agent/wezly_szkody.py: _sygnal_zdjecia`). To pomoc dla
 * likwidatora, nigdy decyzja - `decyzja` w podsumowaniu go nie uwzglednia. `ocena` jest tylko przy
 * statusie OK; `zgodnosc_rodzaju` liczy kod (nie model).
 */
export interface ZdjecieSzkody {
  status: "OK" | "BRAK_ZDJECIA" | "MODEL_NIEDOSTEPNY" | "BLAD_ODCZYTU";
  ocena?: OcenaZdjecia | null;
  kategoria_zgloszona?: RodzajZdarzenia | null;
  zgodnosc_rodzaju?: "ZGODNE" | "NIEZGODNE" | "NIEUSTALONA" | null;
  sygnal_dlugotrwalosci?: boolean;
  powody?: string[];
}

/** Podsumowanie zgloszenia szkody (`agent/decyzje_szkody.py: podsumowanie_szkody`). */
export interface PodsumowanieSzkody {
  typ_dokumentu: "SZKODA";
  /** Sciezka tymczasowa serwera - NIE wyswietlac w UI. */
  plik: string | null;
  pola: PolaSzkody | null;
  podejrzane_instrukcje: boolean | null;
  blad: string | null;
  wynik_polisy: WynikPolisy | null;
  /** Decyzja po regulach S01-S04 i kontroli cytatow - to jest rekomendacja dla czlowieka. */
  decyzja: string;
  powody_decyzji: string[];
  decyzja_llm: string | null;
  cytaty: CytatOwu[];
  brakujace_dokumenty: string[];
  kontrola_cytatow: KontrolaCytatow | null;
  dodatkowe_zapytanie: string | null;
  fragmenty_owu_id: string[];
  /** Opcjonalne: podsumowania sprzed Etapu 15 nie maja tego klucza. */
  ryzyko?: RyzykoSzkody;
  /** Opcjonalne: podsumowania sprzed Etapu 23 nie maja tego klucza. */
  zdjecie?: ZdjecieSzkody;
}

export interface LogWezel {
  wezel: string;
  czas_ms: number;
  tokeny_we: number | null;
  tokeny_wy: number | null;
}

export interface WniosekLista {
  id: string;
  nazwa_pliku: string;
  status: string;
  /** "WNIOSEK" | "SZKODA" | "INNY"; null, gdy klasyfikacja jeszcze nie skonczona. */
  typ_dokumentu?: string | null;
  decyzja_koncowa: DecyzjaKoncowa;
  utworzono: string;
  zakonczono: string | null;
}

export interface WniosekSzczegoly {
  id: string;
  nazwa_pliku: string;
  typ_mime: string;
  rozmiar_b: number;
  status: string;
  thread_id: string;
  podsumowanie: Podsumowanie | PodsumowanieSzkody | null;
  log_wezlow: LogWezel[] | null;
  wywolania_llm: number | null;
  tokeny_we: number | null;
  tokeny_wy: number | null;
  decyzja_koncowa: DecyzjaKoncowa;
  zatwierdzil: string | null;
  komentarz: string | null;
  utworzono: string;
  zakonczono: string | null;
}

export interface UtworzWniosekOut {
  id: string;
  status: string;
}

export interface ZdarzenieAudytu {
  id: string;
  czas: string;
  zdarzenie: string;
  kto: string | null;
  dane: Record<string, unknown> | null;
}

export interface ZdrowieOut {
  status: "ok";
}
