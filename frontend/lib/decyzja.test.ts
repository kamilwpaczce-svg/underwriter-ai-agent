import { describe, expect, it } from "vitest";
import { czySzkoda, czyWymaganyKomentarz, opcjeDecyzji } from "./decyzja";
import type { PodsumowanieSzkody } from "./typy";

describe("czyWymaganyKomentarz", () => {
  it("decyzja = obie (rekomendacja LLM i silnika) -> false", () => {
    expect(czyWymaganyKomentarz("AKCEPTACJA", "AKCEPTACJA", "AKCEPTACJA")).toBe(false);
  });

  it("decyzja = tylko LLM, rozni sie od silnika -> true", () => {
    expect(czyWymaganyKomentarz("AKCEPTACJA", "AKCEPTACJA", "SKIEROWANIE")).toBe(true);
  });

  it("decyzja = tylko silnik, rozni sie od LLM -> true", () => {
    expect(czyWymaganyKomentarz("SKIEROWANIE", "AKCEPTACJA", "SKIEROWANIE")).toBe(true);
  });

  it("decyzja rozni sie od obu -> true", () => {
    expect(czyWymaganyKomentarz("ODMOWA", "AKCEPTACJA", "SKIEROWANIE")).toBe(true);
  });

  it("brak podsumowania (oba argumenty null) -> true", () => {
    expect(czyWymaganyKomentarz("AKCEPTACJA", null, null)).toBe(true);
  });

  it("brak podsumowania (oba argumenty undefined) -> true", () => {
    expect(czyWymaganyKomentarz("AKCEPTACJA", undefined, undefined)).toBe(true);
  });

  it("brak wybranej decyzji -> true (defensywnie)", () => {
    expect(czyWymaganyKomentarz(null, "AKCEPTACJA", "AKCEPTACJA")).toBe(true);
    expect(czyWymaganyKomentarz(undefined, "AKCEPTACJA", "AKCEPTACJA")).toBe(true);
  });
});

describe("opcjeDecyzji", () => {
  it("szkoda: POKRYTA zamiast AKCEPTACJA", () => {
    expect(opcjeDecyzji("SZKODA").map((o) => o.wartosc)).toEqual(["POKRYTA", "ODMOWA", "UZUPELNIENIE", "SKIEROWANIE"]);
  });

  it("wniosek, nieznany typ i brak typu: zachowanie sprzed Etapu 10", () => {
    for (const typ of ["WNIOSEK", "wniosek", null, undefined]) {
      expect(opcjeDecyzji(typ).map((o) => o.wartosc)).toEqual(["AKCEPTACJA", "ODMOWA", "UZUPELNIENIE", "SKIEROWANIE"]);
    }
  });
});

describe("czySzkoda", () => {
  it("rozpoznaje szkode po typ_dokumentu, null i wniosek -> false", () => {
    expect(czySzkoda({ typ_dokumentu: "SZKODA" } as PodsumowanieSzkody)).toBe(true);
    expect(czySzkoda(null)).toBe(false);
    expect(czySzkoda(undefined)).toBe(false);
  });
});
