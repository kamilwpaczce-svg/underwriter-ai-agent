import type { Decyzja, Podsumowanie, PodsumowanieSzkody } from "./typy";

/**
 * Czysta funkcja odwzorowujaca DOKLADNIE logike serwera z `api/trasy.py:177`:
 *
 *   odejscie_od_rekomendacji = cialo.decyzja != rekomendacja_decyzja or cialo.decyzja != silnik_decyzja
 *
 * czyli: komentarz wymagany, chyba ze wybrana decyzja jest rowna JEDNOCZESNIE
 * rekomendacji LLM I decyzji silnika. Brak ktoregokolwiek z argumentow
 * (null/undefined) jest traktowany jako "nie wiadomo" - wymagamy komentarza
 * defensywnie.
 */
export function czyWymaganyKomentarz(
  decyzjaWybrana: string | null | undefined,
  rekomendacjaLlm: string | null | undefined,
  decyzjaSilnika: string | null | undefined
): boolean {
  if (
    decyzjaWybrana === null ||
    decyzjaWybrana === undefined ||
    rekomendacjaLlm === null ||
    rekomendacjaLlm === undefined ||
    decyzjaSilnika === null ||
    decyzjaSilnika === undefined
  ) {
    return true;
  }
  return decyzjaWybrana !== rekomendacjaLlm || decyzjaWybrana !== decyzjaSilnika;
}

/** Rozroznia podsumowanie zgloszenia szkody od podsumowania wniosku (pole `typ_dokumentu`). */
export function czySzkoda(
  podsumowanie: Podsumowanie | PodsumowanieSzkody | null | undefined
): podsumowanie is PodsumowanieSzkody {
  return podsumowanie !== null && podsumowanie !== undefined && podsumowanie.typ_dokumentu === "SZKODA";
}

export interface OpcjaDecyzji {
  wartosc: Decyzja;
  etykieta: string;
}

const OPCJE_WSPOLNE: OpcjaDecyzji[] = [
  { wartosc: "ODMOWA", etykieta: "Odmowa" },
  { wartosc: "UZUPELNIENIE", etykieta: "Uzupełnienie" },
  { wartosc: "SKIEROWANIE", etykieta: "Skierowanie" },
];

/**
 * Opcje decyzji zgodne z `api/schematy_api.py`: DECYZJE_SZKODY dla "SZKODA",
 * DECYZJE_WNIOSKU dla kazdego innego typu (zachowanie sprzed Etapu 10).
 */
export function opcjeDecyzji(typDokumentu: string | null | undefined): OpcjaDecyzji[] {
  const pierwsza: OpcjaDecyzji =
    typDokumentu === "SZKODA"
      ? { wartosc: "POKRYTA", etykieta: "Pokryta" }
      : { wartosc: "AKCEPTACJA", etykieta: "Akceptacja" };
  return [pierwsza, ...OPCJE_WSPOLNE];
}
