/**
 * Czyste funkcje formatujace dane wniosku do wyswietlenia. Zadna nie wywoluje
 * fetch ani nie ma efektow ubocznych - testowalne w izolacji (Vitest).
 */

import type { Adres } from "./typy";

const FORMATER_KWOTY = new Intl.NumberFormat("pl-PL", {
  style: "currency",
  currency: "PLN",
  maximumFractionDigits: 0,
});

/** Formatuje kwote w PLN albo zwraca "—" dla null/undefined. */
export function formatujKwote(kwota: number | null | undefined): string {
  if (kwota === null || kwota === undefined) {
    return "—";
  }
  return FORMATER_KWOTY.format(kwota);
}

/** Formatuje wartosc logiczna jako "Tak"/"Nie", albo "—" dla null/undefined. */
export function formatujBoolean(wartosc: boolean | null | undefined): string {
  if (wartosc === null || wartosc === undefined) {
    return "—";
  }
  return wartosc ? "Tak" : "Nie";
}

/** Zwraca "—" dla null/undefined/pustego stringa, w przeciwnym razie tekst. */
export function formatujNullable(
  wartosc: string | number | null | undefined
): string {
  if (wartosc === null || wartosc === undefined || wartosc === "") {
    return "—";
  }
  return String(wartosc);
}

/** Renderuje adres jedna linia: "ulica, kod miasto", pomijajac brakujace czesci. */
export function formatujAdres(adres: Adres | null | undefined): string {
  if (!adres) {
    return "—";
  }
  const { ulica, kod, miasto } = adres;
  const kodMiasto = [kod, miasto].filter(Boolean).join(" ");
  const czesci = [ulica, kodMiasto].filter((czesc) => czesc && czesc.length > 0);
  if (czesci.length === 0) {
    return "—";
  }
  return czesci.join(", ");
}

/** Formatuje date ISO ("YYYY-MM-DD") lub znacznik czasu na lokalny format pl-PL. */
export function formatujDateCzas(wartosc: string | null | undefined): string {
  if (!wartosc) {
    return "—";
  }
  const data = new Date(wartosc);
  if (Number.isNaN(data.getTime())) {
    return wartosc;
  }
  return data.toLocaleString("pl-PL");
}

const ETYKIETY_TYPU: Record<string, string> = {
  WNIOSEK: "Wniosek",
  SZKODA: "Szkoda",
  INNY: "Inny dokument",
};

/** Etykieta typu dokumentu dla listy; "—" dla null/undefined i nieznanych wartosci. */
export function formatujTypDokumentu(typ: string | null | undefined): string {
  if (!typ) {
    return "—";
  }
  return ETYKIETY_TYPU[typ] ?? "—";
}
