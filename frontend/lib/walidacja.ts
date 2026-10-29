/**
 * Czyste funkcje walidujace dane wejsciowe po stronie klienta. To wygoda UX -
 * serwer (415/413/422 z api/trasy.py) jest zrodlem prawdy i jego odpowiedz
 * zawsze trzeba wyswietlic, nawet gdy walidacja klienta przeszla.
 */

export interface WynikWalidacji {
  poprawny: boolean;
  blad?: string;
}

/** Regex z SPEC_ETAP4: nagłówek X-Uzytkownik musi byc czystym ASCII. */
export const REGEX_IDENTYFIKATORA = /^[A-Za-z0-9._-]{2,40}$/;

/** Waliduje identyfikator underwritera wysylany w naglowku X-Uzytkownik. */
export function walidujIdentyfikator(identyfikator: string): WynikWalidacji {
  if (!identyfikator || identyfikator.trim().length === 0) {
    return { poprawny: false, blad: "Identyfikator jest wymagany." };
  }
  if (!REGEX_IDENTYFIKATORA.test(identyfikator)) {
    return {
      poprawny: false,
      blad:
        "Identyfikator moze zawierac tylko litery ASCII, cyfry, kropke, podkreslenie i myslnik (2-40 znakow). Polskie znaki (np. \"ń\") sa niedozwolone.",
    };
  }
  return { poprawny: true };
}

const ROZSZERZENIA_DOZWOLONE = [".pdf", ".jpg", ".jpeg", ".eml"];
const MAX_ROZMIAR_B = 10 * 1024 * 1024;

function wyciagnijRozszerzenie(nazwaPliku: string): string {
  const kropka = nazwaPliku.lastIndexOf(".");
  if (kropka === -1) {
    return "";
  }
  return nazwaPliku.slice(kropka).toLowerCase();
}

/** Waliduje plik przed uploadem: rozszerzenie i rozmiar. */
export function walidujPlik(plik: File): WynikWalidacji {
  const rozszerzenie = wyciagnijRozszerzenie(plik.name);
  if (!ROZSZERZENIA_DOZWOLONE.includes(rozszerzenie)) {
    return {
      poprawny: false,
      blad: `Nieobslugiwane rozszerzenie "${rozszerzenie || "(brak)"}". Dozwolone: .pdf, .jpg, .jpeg, .eml.`,
    };
  }
  if (plik.size > MAX_ROZMIAR_B) {
    return {
      poprawny: false,
      blad: `Plik przekracza limit 10 MB (ma ${(plik.size / (1024 * 1024)).toFixed(2)} MB).`,
    };
  }
  return { poprawny: true };
}
