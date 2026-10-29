import { describe, expect, it } from "vitest";
import { walidujIdentyfikator, walidujPlik } from "./walidacja";

describe("walidujIdentyfikator", () => {
  it("akceptuje poprawny identyfikator ASCII", () => {
    expect(walidujIdentyfikator("a.nowak").poprawny).toBe(true);
  });

  it("akceptuje identyfikator z cyframi i myslnikiem/podkresleniem", () => {
    expect(walidujIdentyfikator("user_123-ab").poprawny).toBe(true);
  });

  it("odrzuca identyfikator z polskim znakiem", () => {
    const wynik = walidujIdentyfikator("Kusiński");
    expect(wynik.poprawny).toBe(false);
    expect(wynik.blad).toBeTruthy();
  });

  it("odrzuca pusty string", () => {
    expect(walidujIdentyfikator("").poprawny).toBe(false);
  });

  it("odrzuca zbyt krotki identyfikator", () => {
    expect(walidujIdentyfikator("a").poprawny).toBe(false);
  });

  it("odrzuca zbyt dlugi identyfikator (>40 znakow)", () => {
    expect(walidujIdentyfikator("a".repeat(41)).poprawny).toBe(false);
  });

  it("akceptuje identyfikator o dlugosci dokladnie 40", () => {
    expect(walidujIdentyfikator("a".repeat(40)).poprawny).toBe(true);
  });

  it("odrzuca spacje", () => {
    expect(walidujIdentyfikator("jan kowalski").poprawny).toBe(false);
  });
});

function zbudujPlik(nazwa: string, rozmiarB: number): File {
  const bajty = new Uint8Array(rozmiarB);
  return new File([bajty], nazwa);
}

describe("walidujPlik", () => {
  it("akceptuje .pdf w limicie rozmiaru", () => {
    const wynik = walidujPlik(zbudujPlik("wniosek.pdf", 1024));
    expect(wynik.poprawny).toBe(true);
  });

  it("akceptuje .jpg, .jpeg, .eml (case-insensitive)", () => {
    expect(walidujPlik(zbudujPlik("skan.JPG", 1024)).poprawny).toBe(true);
    expect(walidujPlik(zbudujPlik("skan.jpeg", 1024)).poprawny).toBe(true);
    expect(walidujPlik(zbudujPlik("wiadomosc.EML", 1024)).poprawny).toBe(true);
  });

  it("odrzuca niedozwolone rozszerzenie", () => {
    const wynik = walidujPlik(zbudujPlik("notatka.txt", 1024));
    expect(wynik.poprawny).toBe(false);
    expect(wynik.blad).toContain("txt");
  });

  it("odrzuca brak rozszerzenia", () => {
    expect(walidujPlik(zbudujPlik("plikbezrozszerzenia", 1024)).poprawny).toBe(false);
  });

  it("akceptuje plik dokladnie na granicy 10 MB", () => {
    const wynik = walidujPlik(zbudujPlik("wniosek.pdf", 10 * 1024 * 1024));
    expect(wynik.poprawny).toBe(true);
  });

  it("odrzuca plik przekraczajacy 10 MB o 1 bajt", () => {
    const wynik = walidujPlik(zbudujPlik("wniosek.pdf", 10 * 1024 * 1024 + 1));
    expect(wynik.poprawny).toBe(false);
    expect(wynik.blad).toContain("10 MB");
  });
});
