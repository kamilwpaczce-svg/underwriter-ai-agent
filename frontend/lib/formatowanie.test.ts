import { describe, expect, it } from "vitest";
import {
  formatujAdres,
  formatujBoolean,
  formatujDateCzas,
  formatujKwote,
  formatujNullable,
  formatujTypDokumentu,
} from "./formatowanie";

describe("formatujKwote", () => {
  it("formatuje kwote w PLN", () => {
    expect(formatujKwote(1800000)).toContain("1");
    expect(formatujKwote(1800000)).toContain("zł");
  });

  it("zwraca myslnik dla null", () => {
    expect(formatujKwote(null)).toBe("—");
  });

  it("zwraca myslnik dla undefined", () => {
    expect(formatujKwote(undefined)).toBe("—");
  });

  it("formatuje zero", () => {
    expect(formatujKwote(0)).not.toBe("—");
  });
});

describe("formatujBoolean", () => {
  it("true -> Tak", () => {
    expect(formatujBoolean(true)).toBe("Tak");
  });
  it("false -> Nie", () => {
    expect(formatujBoolean(false)).toBe("Nie");
  });
  it("null -> myslnik", () => {
    expect(formatujBoolean(null)).toBe("—");
  });
  it("undefined -> myslnik", () => {
    expect(formatujBoolean(undefined)).toBe("—");
  });
});

describe("formatujNullable", () => {
  it("zwraca wartosc jako string", () => {
    expect(formatujNullable("abc")).toBe("abc");
    expect(formatujNullable(42)).toBe("42");
  });
  it("null/undefined/pusty string -> myslnik", () => {
    expect(formatujNullable(null)).toBe("—");
    expect(formatujNullable(undefined)).toBe("—");
    expect(formatujNullable("")).toBe("—");
  });
});

describe("formatujAdres", () => {
  it("renderuje pelny adres jedna linia", () => {
    expect(
      formatujAdres({ ulica: "ul. Zbożowa 12", kod: "05-500", miasto: "Piaseczno" })
    ).toBe("ul. Zbożowa 12, 05-500 Piaseczno");
  });

  it("pomija brakujace czesci", () => {
    expect(formatujAdres({ ulica: null, kod: "05-500", miasto: "Piaseczno" })).toBe(
      "05-500 Piaseczno"
    );
    expect(formatujAdres({ ulica: "ul. Zbożowa 12", kod: null, miasto: null })).toBe(
      "ul. Zbożowa 12"
    );
  });

  it("myslnik gdy caly adres null", () => {
    expect(formatujAdres(null)).toBe("—");
    expect(formatujAdres(undefined)).toBe("—");
  });

  it("myslnik gdy wszystkie pola puste", () => {
    expect(formatujAdres({ ulica: null, kod: null, miasto: null })).toBe("—");
  });
});

describe("formatujDateCzas", () => {
  it("formatuje date ISO na lokalny format", () => {
    const wynik = formatujDateCzas("2026-10-10T17:11:43.313601Z");
    expect(wynik).not.toBe("—");
    expect(wynik.length).toBeGreaterThan(0);
  });

  it("myslnik dla null/undefined", () => {
    expect(formatujDateCzas(null)).toBe("—");
    expect(formatujDateCzas(undefined)).toBe("—");
  });
});

describe("formatujTypDokumentu", () => {
  it("etykiety typow z API", () => {
    expect(formatujTypDokumentu("WNIOSEK")).toBe("Wniosek");
    expect(formatujTypDokumentu("SZKODA")).toBe("Szkoda");
    expect(formatujTypDokumentu("INNY")).toBe("Inny dokument");
  });

  it("myslnik dla braku typu (wiersze sprzed Etapu 10, PRZETWARZANIE) i nieznanych wartosci", () => {
    expect(formatujTypDokumentu(null)).toBe("—");
    expect(formatujTypDokumentu(undefined)).toBe("—");
    expect(formatujTypDokumentu("POLISA")).toBe("—");
  });
});
