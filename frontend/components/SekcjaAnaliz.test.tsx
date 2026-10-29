import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import SekcjaAnaliz from "./SekcjaAnaliz";
import type { Podsumowanie, WniosekSzczegoly } from "@/lib/typy";

function zbudujWniosek(podsumowanie: Podsumowanie): WniosekSzczegoly {
  return {
    id: "id-1",
    nazwa_pliku: "W13.pdf",
    typ_mime: "application/pdf",
    rozmiar_b: 1234,
    status: "CZEKA_NA_DECYZJE",
    thread_id: "t-1",
    podsumowanie,
    log_wezlow: [],
    wywolania_llm: 3,
    tokeny_we: 0,
    tokeny_wy: 0,
    decyzja_koncowa: null,
    zatwierdzil: null,
    komentarz: null,
    utworzono: "2026-10-10T10:00:00Z",
    zakonczono: null,
  };
}

const bazowePodsumowanie: Podsumowanie = {
  blad: null,
  plik: "/tmp/x.pdf",
  typ_dokumentu: "wniosek",
  pola: null,
  problemy_walidacji: [],
  rekomendacja: { decyzja: "SKIEROWANIE", reguly: ["R04"], uzasadnienie: [] },
  decyzja_silnika: { decyzja: "SKIEROWANIE", reguly: ["R04"] },
  zgodnosc: true,
  podejrzane_instrukcje: false,
};

describe("SekcjaAnaliz", () => {
  it("pokazuje czerwony baner podejrzanych instrukcji, gdy podejrzane_instrukcje=true (dane W13)", () => {
    const podsumowanie: Podsumowanie = { ...bazowePodsumowanie, podejrzane_instrukcje: true };
    render(<SekcjaAnaliz podsumowanie={podsumowanie} wniosek={zbudujWniosek(podsumowanie)} />);
    expect(screen.getByTestId("baner-podejrzane-instrukcje")).toBeInTheDocument();
  });

  it("NIE pokazuje banera podejrzanych instrukcji, gdy podejrzane_instrukcje=false", () => {
    render(
      <SekcjaAnaliz podsumowanie={bazowePodsumowanie} wniosek={zbudujWniosek(bazowePodsumowanie)} />
    );
    expect(screen.queryByTestId("baner-podejrzane-instrukcje")).not.toBeInTheDocument();
  });

  it("pokazuje flage rozbieznosci, gdy zgodnosc===false", () => {
    const podsumowanie: Podsumowanie = {
      ...bazowePodsumowanie,
      rekomendacja: { decyzja: "SKIEROWANIE", reguly: ["R04"], uzasadnienie: [] },
      decyzja_silnika: { decyzja: "AKCEPTACJA", reguly: [] },
      zgodnosc: false,
    };
    render(<SekcjaAnaliz podsumowanie={podsumowanie} wniosek={zbudujWniosek(podsumowanie)} />);
    expect(screen.getByTestId("flaga-rozbieznosci")).toBeInTheDocument();
  });

  it("NIE pokazuje flagi rozbieznosci, gdy zgodnosc===true", () => {
    render(
      <SekcjaAnaliz podsumowanie={bazowePodsumowanie} wniosek={zbudujWniosek(bazowePodsumowanie)} />
    );
    expect(screen.queryByTestId("flaga-rozbieznosci")).not.toBeInTheDocument();
  });

  it("pokazuje baner AI, gdy jest rekomendacja", () => {
    render(
      <SekcjaAnaliz podsumowanie={bazowePodsumowanie} wniosek={zbudujWniosek(bazowePodsumowanie)} />
    );
    expect(screen.getByTestId("baner-ai")).toBeInTheDocument();
  });

  it("pokazuje blok problemow walidacji, gdy lista nie jest pusta", () => {
    const podsumowanie: Podsumowanie = {
      ...bazowePodsumowanie,
      problemy_walidacji: ["Brak adresu."],
    };
    render(<SekcjaAnaliz podsumowanie={podsumowanie} wniosek={zbudujWniosek(podsumowanie)} />);
    expect(screen.getByTestId("problemy-walidacji")).toHaveTextContent("Brak adresu.");
  });

  // Graf skraca klasyfikuj/ekstrahuj -> zatwierdzenie przy bledzie i pomija waliduj,
  // wiec problemy_walidacji przychodzi jako null. 2026-10-11 w chmurze .length na null
  // wywracal cala strone ("This page couldn't load"), takze po przeladowaniu.
  it("nie wywraca sie przy problemy_walidacji=null i pokazuje blad agenta", () => {
    const podsumowanie: Podsumowanie = {
      ...bazowePodsumowanie,
      problemy_walidacji: null,
      rekomendacja: null,
      decyzja_silnika: null,
      zgodnosc: null,
      blad: "Ekstrakcja nie powiodla sie: timeout.",
    };
    render(<SekcjaAnaliz podsumowanie={podsumowanie} wniosek={zbudujWniosek(podsumowanie)} />);
    expect(screen.getByTestId("blad-agenta")).toHaveTextContent("Ekstrakcja nie powiodla sie: timeout.");
    expect(screen.queryByTestId("problemy-walidacji")).not.toBeInTheDocument();
  });
});
