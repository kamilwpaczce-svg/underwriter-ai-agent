import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import SekcjaOcenyPokrycia from "./SekcjaOcenyPokrycia";
import type { PodsumowanieSzkody } from "@/lib/typy";

const TRESC_P4U1 = "§ 4. Zakres ubezpieczenia\n1. Ochrona obejmuje szkody w mieniu powstałe wskutek pożaru.";

const bazowePodsumowanie: PodsumowanieSzkody = {
  typ_dokumentu: "SZKODA",
  plik: "/tmp/Z01.pdf",
  pola: {
    nr_polisy: "MP/2026/000101",
    ubezpieczony: "Przykładowa Spółka z o.o.",
    nip: null,
    data_zdarzenia: "2026-09-02",
    data_zgloszenia: "2026-09-04",
    miejsce: null,
    przyczyna: "Pożar w hali magazynowej",
    rodzaj_mienia: "zapasy",
    szacowana_kwota: 120000,
    zalaczniki: ["protokół straży"],
    okolicznosci: null,
  },
  podejrzane_instrukcje: false,
  blad: null,
  wynik_polisy: { kody: [], braki: [], opis: [], suma_ubezpieczenia: 2000000, dni_do_zgloszenia: 2 },
  decyzja: "POKRYTA",
  powody_decyzji: ["ocena_llm"],
  decyzja_llm: "POKRYTA",
  cytaty: [
    { paragraf: "§ 4", ustep: "1", uzasadnienie: "Pożar jest ryzykiem objętym.", fragment_id: "p4u1", tresc: TRESC_P4U1 },
  ],
  brakujace_dokumenty: [],
  kontrola_cytatow: { ok: true, powod: null, odrzucone: [] },
  dodatkowe_zapytanie: null,
  fragmenty_owu_id: ["p4u1", "p6u1", "p2u3", "p5u2", "p7u1"],
};

describe("SekcjaOcenyPokrycia", () => {
  it("sygnal ryzyka OK: wynik z przecinkiem, wersja, dopisek i glowne czynniki", () => {
    render(
      <SekcjaOcenyPokrycia
        podsumowanie={{
          ...bazowePodsumowanie,
          ryzyko: { status: "OK", wynik: 0.73, wersja: "v3", glowne_cechy: ["udzial_kwoty", "szkody_3_lata"] },
        }}
      />
    );
    expect(screen.getByTestId("sygnal-ryzyka")).toHaveTextContent(
      "Sygnał ryzyka: 0,73 (model v3) — do weryfikacji likwidatora"
    );
    expect(screen.getByTestId("sygnal-ryzyka-cechy")).toHaveTextContent(
      "udział kwoty szkody w sumie ubezpieczenia, szkody w ostatnich 3 latach"
    );
  });

  it("sygnal ryzyka BRAK_DANYCH i MODEL_NIEDOSTEPNY: osobne komunikaty, bez czynnikow", () => {
    const { rerender } = render(
      <SekcjaOcenyPokrycia podsumowanie={{ ...bazowePodsumowanie, ryzyko: { status: "BRAK_DANYCH" } }} />
    );
    expect(screen.getByTestId("sygnal-ryzyka")).toHaveTextContent(
      "Sygnał ryzyka: brak danych (brak polisy lub pól)"
    );
    rerender(
      <SekcjaOcenyPokrycia
        podsumowanie={{
          ...bazowePodsumowanie,
          ryzyko: { status: "MODEL_NIEDOSTEPNY", wynik: null, wersja: null, glowne_cechy: [] },
        }}
      />
    );
    expect(screen.getByTestId("sygnal-ryzyka")).toHaveTextContent("Sygnał ryzyka: model niedostępny");
    expect(screen.queryByTestId("sygnal-ryzyka-cechy")).not.toBeInTheDocument();
  });

  it("podsumowanie bez klucza ryzyko (sprzed Etapu 15): brak wiersza", () => {
    render(<SekcjaOcenyPokrycia podsumowanie={bazowePodsumowanie} />);
    expect(screen.queryByTestId("sygnal-ryzyka")).not.toBeInTheDocument();
  });

  it("pokazuje decyzje i PELNA tresc cytowanego ustepu (Z01)", () => {
    render(<SekcjaOcenyPokrycia podsumowanie={bazowePodsumowanie} />);
    expect(screen.getByTestId("decyzja-szkody")).toHaveTextContent("POKRYTA");
    expect(screen.getByText("§ 4 ust. 1")).toBeInTheDocument();
    expect(screen.getByText(/Ochrona obejmuje szkody w mieniu powstałe wskutek pożaru/)).toBeInTheDocument();
    expect(screen.getByTestId("wynik-polisy")).toHaveTextContent("brak uwag");
    expect(screen.queryByTestId("kontrola-cytatow-odrzucila")).not.toBeInTheDocument();
  });

  it("kontrola cytatow odrzucila: baner z powodem, cytat bez tresci oznaczony", () => {
    render(
      <SekcjaOcenyPokrycia
        podsumowanie={{
          ...bazowePodsumowanie,
          decyzja: "SKIEROWANIE",
          powody_decyzji: ["cytat_spoza_kontekstu"],
          cytaty: [{ paragraf: "§ 9", ustep: "2", uzasadnienie: "x", fragment_id: null, tresc: null }],
          kontrola_cytatow: {
            ok: false,
            powod: "cytat_spoza_kontekstu",
            odrzucone: [{ paragraf: "§ 9", ustep: "2", uzasadnienie: "x" }],
          },
        }}
      />
    );
    expect(screen.getByTestId("kontrola-cytatow-odrzucila")).toHaveTextContent("cytat_spoza_kontekstu");
    expect(screen.getByTestId("cytat-bez-tresci")).toBeInTheDocument();
  });

  it("brakujace dokumenty, kod polisy i dodatkowe zapytanie (UZUPELNIENIE)", () => {
    render(
      <SekcjaOcenyPokrycia
        podsumowanie={{
          ...bazowePodsumowanie,
          decyzja: "UZUPELNIENIE",
          wynik_polisy: { kody: ["S04"], braki: [], opis: ["S04: zgloszenie po 9 dniach."], suma_ubezpieczenia: 2000000, dni_do_zgloszenia: 9 },
          brakujace_dokumenty: ["protokół policji"],
          dodatkowe_zapytanie: "kradziez z wlamaniem zabezpieczenia",
        }}
      />
    );
    expect(screen.getByTestId("brakujace-dokumenty")).toHaveTextContent("protokół policji");
    expect(screen.getByTestId("wynik-polisy")).toHaveTextContent("S04");
    expect(screen.getByTestId("dodatkowe-zapytanie")).toHaveTextContent("kradziez z wlamaniem");
  });

  it("proba wstrzykniecia (Z12): bez oceny modelu, bez polisy - baner zamiast bledu renderowania", () => {
    render(
      <SekcjaOcenyPokrycia
        podsumowanie={{
          ...bazowePodsumowanie,
          podejrzane_instrukcje: true,
          wynik_polisy: null,
          decyzja: "SKIEROWANIE",
          powody_decyzji: ["podejrzane_instrukcje"],
          decyzja_llm: null,
          cytaty: [],
          kontrola_cytatow: null,
          fragmenty_owu_id: [],
        }}
      />
    );
    expect(screen.getByTestId("baner-podejrzane-instrukcje")).toBeInTheDocument();
    expect(screen.queryByTestId("baner-ai")).not.toBeInTheDocument();
    expect(screen.getByText("Polisy nie sprawdzono.")).toBeInTheDocument();
    expect(screen.getByText("Model nie wskazał ustępów OWU.")).toBeInTheDocument();
  });
});

describe("SekcjaOcenyPokrycia - wiersz Zdjecie (Etap 23)", () => {
  const ocena = {
    czy_widac_szkode: true,
    rodzaj_zdarzenia: "pozar" as const,
    widoczne_mienie: ["regały"],
    dlugotrwalosc: "NAGLE" as const,
    oznaki: ["sadza"],
    pewnosc: 0.92,
    tekst_na_zdjeciu: false,
  };
  const zdjecieOk = {
    status: "OK" as const,
    ocena,
    kategoria_zgloszona: "pozar" as const,
    zgodnosc_rodzaju: "ZGODNE" as const,
    sygnal_dlugotrwalosci: false,
    powody: [],
  };

  const renderuj = (zdjecie: PodsumowanieSzkody["zdjecie"]) =>
    render(<SekcjaOcenyPokrycia podsumowanie={{ ...bazowePodsumowanie, zdjecie }} />);

  it("ZGODNE: rodzaj, pewnosc z przecinkiem, charakter i zgodnosc ze zgloszeniem", () => {
    renderuj(zdjecieOk);
    expect(screen.getByTestId("sygnal-zdjecia")).toHaveTextContent(
      "Zdjęcie: pożar (pewność modelu 0,92), nagłe — zgodne ze zgłoszeniem"
    );
    expect(screen.queryByTestId("sygnal-zdjecia-dlugotrwalosc")).not.toBeInTheDocument();
  });

  it("NIEZGODNE: wyraznie wskazane, z kategoria zgloszona i dopiskiem do weryfikacji", () => {
    renderuj({ ...zdjecieOk, ocena: { ...ocena, rodzaj_zdarzenia: "zalanie" }, kategoria_zgloszona: "pozar", zgodnosc_rodzaju: "NIEZGODNE" });
    expect(screen.getByTestId("sygnal-zdjecia")).toHaveTextContent(
      "Zdjęcie: zalanie (pewność modelu 0,92), nagłe — NIEZGODNE ze zgłoszeniem (zgłoszono: pożar) — do weryfikacji likwidatora"
    );
  });

  it("NIEUSTALONA: pokazuje, ze zgodnosci nie ustalono, i powod po polsku", () => {
    renderuj({ ...zdjecieOk, zgodnosc_rodzaju: "NIEUSTALONA", powody: ["niska_pewnosc"] });
    const wiersz = screen.getByTestId("sygnal-zdjecia");
    expect(wiersz).toHaveTextContent("zgodności ze zgłoszeniem nie ustalono (niska pewność modelu)");
    expect(wiersz).not.toHaveTextContent("zgodne ze zgłoszeniem");
    expect(wiersz).not.toHaveTextContent("NIEZGODNE");
  });

  it("sygnal dlugotrwalosci: osobna linia z oznakami przy zgloszeniu naglego zdarzenia", () => {
    renderuj({
      ...zdjecieOk,
      ocena: { ...ocena, rodzaj_zdarzenia: "korozja_zawilgocenie", dlugotrwalosc: "DLUGOTRWALE", oznaki: ["rdza", "zacieki"] },
      kategoria_zgloszona: "zalanie",
      zgodnosc_rodzaju: "NIEZGODNE",
      sygnal_dlugotrwalosci: true,
    });
    expect(screen.getByTestId("sygnal-zdjecia-dlugotrwalosc")).toHaveTextContent(
      "Oznaki długotrwałości (rdza, zacieki) przy zgłoszeniu nagłego zdarzenia"
    );
  });

  it("sygnal dlugotrwalosci bez oznak: linia bez nawiasu", () => {
    renderuj({ ...zdjecieOk, ocena: { ...ocena, oznaki: [] }, sygnal_dlugotrwalosci: true });
    expect(screen.getByTestId("sygnal-zdjecia-dlugotrwalosc")).toHaveTextContent(
      /^Oznaki długotrwałości przy zgłoszeniu nagłego zdarzenia/
    );
  });

  it("BRAK_ZDJECIA, MODEL_NIEDOSTEPNY, BLAD_ODCZYTU: tekst statusu, nie puste miejsce", () => {
    const { rerender } = renderuj({ status: "BRAK_ZDJECIA", powody: [] });
    expect(screen.getByTestId("sygnal-zdjecia")).toHaveTextContent("Zdjęcie: nie dołączono zdjęcia");
    rerender(<SekcjaOcenyPokrycia podsumowanie={{ ...bazowePodsumowanie, zdjecie: { status: "MODEL_NIEDOSTEPNY", powody: ["blad_modelu"] } }} />);
    expect(screen.getByTestId("sygnal-zdjecia")).toHaveTextContent("Zdjęcie: nie przeanalizowano — model niedostępny (blad_modelu)");
    rerender(<SekcjaOcenyPokrycia podsumowanie={{ ...bazowePodsumowanie, zdjecie: { status: "BLAD_ODCZYTU", powody: ["niezgodny_naglowek"] } }} />);
    expect(screen.getByTestId("sygnal-zdjecia")).toHaveTextContent(
      "Zdjęcie: nie udało się odczytać pliku (zawartość pliku nie zgadza się z jego rozszerzeniem)"
    );
    expect(screen.queryByTestId("sygnal-zdjecia-dlugotrwalosc")).not.toBeInTheDocument();
  });

  it("BRAK_ZDJECIA z powodem pominiete (podejrzane instrukcje): wyjasnienie zamiast pustego wiersza", () => {
    renderuj({ status: "BRAK_ZDJECIA", powody: ["pominiete"] });
    expect(screen.getByTestId("sygnal-zdjecia")).toHaveTextContent("nie przeanalizowano (pominięto przy podejrzanych instrukcjach w dokumencie)");
  });

  it("podsumowanie bez klucza zdjecie (sprzed Etapu 23): brak wiersza", () => {
    render(<SekcjaOcenyPokrycia podsumowanie={bazowePodsumowanie} />);
    expect(screen.queryByTestId("sygnal-zdjecia")).not.toBeInTheDocument();
  });

  it("tekst z modelu jest wyswietlany jako tekst, nie jako HTML", () => {
    renderuj({ ...zdjecieOk, ocena: { ...ocena, oznaki: ["<img src=x onerror=alert(1)>"] }, sygnal_dlugotrwalosci: true });
    expect(screen.getByTestId("sygnal-zdjecia-dlugotrwalosc")).toHaveTextContent("<img src=x onerror=alert(1)>");
    expect(document.querySelector("img")).toBeNull();
  });
});
