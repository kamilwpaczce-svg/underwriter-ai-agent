import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DecisionForm from "./DecisionForm";
import * as api from "@/lib/api";
import type { Podsumowanie, PodsumowanieSzkody, WniosekSzczegoly } from "@/lib/typy";

function zbudujWniosek(rekomendacja: string, silnik: string): WniosekSzczegoly {
  const podsumowanie: Podsumowanie = {
    blad: null,
    plik: "/tmp/x.pdf",
    typ_dokumentu: "wniosek",
    pola: null,
    problemy_walidacji: [],
    rekomendacja: { decyzja: rekomendacja, reguly: [], uzasadnienie: [] },
    decyzja_silnika: { decyzja: silnik, reguly: [] },
    zgodnosc: rekomendacja === silnik,
    podejrzane_instrukcje: false,
  };
  return {
    id: "wniosek-1",
    nazwa_pliku: "W03.pdf",
    typ_mime: "application/pdf",
    rozmiar_b: 10,
    status: "CZEKA_NA_DECYZJE",
    thread_id: "t-1",
    podsumowanie,
    log_wezlow: [],
    wywolania_llm: 1,
    tokeny_we: 0,
    tokeny_wy: 0,
    decyzja_koncowa: null,
    zatwierdzil: null,
    komentarz: null,
    utworzono: "2026-10-10T10:00:00Z",
    zakonczono: null,
  };
}

function zbudujSzkode(decyzja: string, decyzjaLlm: string): WniosekSzczegoly {
  const podsumowanie: PodsumowanieSzkody = {
    typ_dokumentu: "SZKODA",
    plik: "/tmp/Z10.pdf",
    pola: null,
    podejrzane_instrukcje: false,
    blad: null,
    wynik_polisy: { kody: ["S03"], braki: [], opis: [], suma_ubezpieczenia: 500000, dni_do_zgloszenia: 1 },
    decyzja,
    powody_decyzji: ["S03"],
    decyzja_llm: decyzjaLlm,
    cytaty: [],
    brakujace_dokumenty: [],
    kontrola_cytatow: { ok: true, powod: null, odrzucone: [] },
    dodatkowe_zapytanie: null,
    fragmenty_owu_id: [],
  };
  return { ...zbudujWniosek("SKIEROWANIE", "SKIEROWANIE"), nazwa_pliku: "Z10.pdf", podsumowanie };
}

describe("DecisionForm", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("przycisk jest zablokowany, dopoki nie wybrano decyzji i identyfikatora", () => {
    render(<DecisionForm wniosek={zbudujWniosek("SKIEROWANIE", "SKIEROWANIE")} onPoDecyzji={vi.fn()} />);
    expect(screen.getByRole("button", { name: /zatwierdź decyzję/i })).toBeDisabled();
  });

  it("gdy wybrana decyzja ZGADZA SIE z rekomendacja i silnikiem - komentarz opcjonalny, przycisk aktywny bez komentarza", async () => {
    const user = userEvent.setup();
    render(<DecisionForm wniosek={zbudujWniosek("SKIEROWANIE", "SKIEROWANIE")} onPoDecyzji={vi.fn()} />);

    await user.click(screen.getByRole("radio", { name: "Skierowanie" }));
    await user.type(screen.getByLabelText("Twój identyfikator"), "test.manual");

    expect(screen.getByText(/Komentarz \(opcjonalny\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /zatwierdź decyzję/i })).toBeEnabled();
  });

  it("gdy wybrana decyzja ODBIEGA od rekomendacji LUB silnika - komentarz wymagany, przycisk zablokowany bez komentarza, odblokowany po jego wpisaniu", async () => {
    const user = userEvent.setup();
    // rekomendacja i silnik = SKIEROWANIE (jak W03), wybieramy AKCEPTACJA
    render(<DecisionForm wniosek={zbudujWniosek("SKIEROWANIE", "SKIEROWANIE")} onPoDecyzji={vi.fn()} />);

    await user.click(screen.getByRole("radio", { name: "Akceptacja" }));
    await user.type(screen.getByLabelText("Twój identyfikator"), "test.manual");

    expect(screen.getByText(/Komentarz \(wymagany/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /zatwierdź decyzję/i })).toBeDisabled();

    await user.type(screen.getByLabelText(/Komentarz/), "Odstępuję, bo klient ma dodatkowe zabezpieczenia.");
    expect(screen.getByRole("button", { name: /zatwierdź decyzję/i })).toBeEnabled();
  });

  it("wysyla X-Uzytkownik i poprawne cialo JSON do wyslijDecyzje, zapamietuje identyfikator w localStorage", async () => {
    const spy = vi.spyOn(api, "wyslijDecyzje").mockResolvedValue(zbudujWniosek("SKIEROWANIE", "SKIEROWANIE"));
    const onPoDecyzji = vi.fn();
    const user = userEvent.setup();
    render(<DecisionForm wniosek={zbudujWniosek("SKIEROWANIE", "SKIEROWANIE")} onPoDecyzji={onPoDecyzji} />);

    await user.click(screen.getByRole("radio", { name: "Skierowanie" }));
    await user.type(screen.getByLabelText("Twój identyfikator"), "test.manual");
    await user.click(screen.getByRole("button", { name: /zatwierdź decyzję/i }));

    await waitFor(() => expect(onPoDecyzji).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith("wniosek-1", "SKIEROWANIE", null, "test.manual");
    expect(window.localStorage.getItem("underwriter_identyfikator")).toBe("test.manual");
  });

  it("pokazuje literalny blad 422 z API i NIE wywoluje onPoDecyzji", async () => {
    vi.spyOn(api, "wyslijDecyzje").mockRejectedValue(
      new api.BladApi(422, "Komentarz jest wymagany przy odejsciu od rekomendacji.")
    );
    const onPoDecyzji = vi.fn();
    const user = userEvent.setup();
    render(<DecisionForm wniosek={zbudujWniosek("SKIEROWANIE", "SKIEROWANIE")} onPoDecyzji={onPoDecyzji} />);

    await user.click(screen.getByRole("radio", { name: "Skierowanie" }));
    await user.type(screen.getByLabelText("Twój identyfikator"), "test.manual");
    await user.click(screen.getByRole("button", { name: /zatwierdź decyzję/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Komentarz jest wymagany przy odejsciu od rekomendacji."
    );
    expect(onPoDecyzji).not.toHaveBeenCalled();
  });

  it("przy bledzie 409 pokazuje komunikat O ZMIANIE STATUSU i mimo to wywoluje onPoDecyzji (odswiezenie danych)", async () => {
    vi.spyOn(api, "wyslijDecyzje").mockRejectedValue(new api.BladApi(409, "Status wniosku juz zmieniony."));
    const onPoDecyzji = vi.fn();
    const user = userEvent.setup();
    render(<DecisionForm wniosek={zbudujWniosek("SKIEROWANIE", "SKIEROWANIE")} onPoDecyzji={onPoDecyzji} />);

    await user.click(screen.getByRole("radio", { name: "Skierowanie" }));
    await user.type(screen.getByLabelText("Twój identyfikator"), "test.manual");
    await user.click(screen.getByRole("button", { name: /zatwierdź decyzję/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Status wniosku juz zmieniony.");
    expect(onPoDecyzji).toHaveBeenCalled();
  });

  it("odczytuje zapamietany identyfikator z localStorage przy montowaniu", async () => {
    window.localStorage.setItem("underwriter_identyfikator", "a.nowak");
    render(<DecisionForm wniosek={zbudujWniosek("SKIEROWANIE", "SKIEROWANIE")} onPoDecyzji={vi.fn()} />);
    // Etap 6: przed odczytem localStorage komponent najpierw probuje GET /api/.ja
    // (Easy Auth) - w testach (bez mocka fetch) to wywolanie odrzuca sie
    // asynchronicznie, wiec odczyt z localStorage nastepuje dopiero po tym
    // odrzuceniu. `waitFor` czeka na to zamiast sprawdzac stan od razu.
    await waitFor(() => {
      expect(screen.getByLabelText("Twój identyfikator")).toHaveValue(
        "a.nowak"
      );
    });
  });

  it("gdy proxy zglasza tozsamosc z Easy Auth, pole jest wypelnione i zablokowane", async () => {
    vi.spyOn(api, "pobierzTozsamosc").mockResolvedValue({
      identyfikator: "jan.kowalski@firma.pl",
    });
    render(
      <DecisionForm
        wniosek={zbudujWniosek("SKIEROWANIE", "SKIEROWANIE")}
        onPoDecyzji={vi.fn()}
      />
    );

    const pole = await screen.findByLabelText<HTMLInputElement>("Twój identyfikator");
    await waitFor(() => {
      expect(pole).toHaveValue("jan.kowalski@firma.pl");
    });
    expect(pole).toBeDisabled();
  });

  // 2026-10-11 w chmurze: e-mail z Easy Auth nie przechodzil regexu recznego wpisu
  // (brak "@"), wiec przycisk zostawal nieaktywny mimo wybranej decyzji.
  it("z tozsamoscia z Easy Auth (e-mail z '@') przycisk jest aktywny po wybraniu decyzji", async () => {
    vi.spyOn(api, "pobierzTozsamosc").mockResolvedValue({
      identyfikator: "jan.kowalski@firma.pl",
    });
    const user = userEvent.setup();
    render(
      <DecisionForm
        wniosek={zbudujWniosek("SKIEROWANIE", "SKIEROWANIE")}
        onPoDecyzji={vi.fn()}
      />
    );

    const pole = await screen.findByLabelText<HTMLInputElement>("Twój identyfikator");
    await waitFor(() => {
      expect(pole).toHaveValue("jan.kowalski@firma.pl");
    });
    await user.click(screen.getByRole("radio", { name: "Skierowanie" }));
    expect(screen.getByRole("button", { name: /zatwierdź decyzję/i })).toBeEnabled();
  });

  it("gdy proxy zglasza brak tozsamosci (null), pole zostaje odblokowane i puste", async () => {
    vi.spyOn(api, "pobierzTozsamosc").mockResolvedValue({ identyfikator: null });
    render(
      <DecisionForm
        wniosek={zbudujWniosek("SKIEROWANIE", "SKIEROWANIE")}
        onPoDecyzji={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(api.pobierzTozsamosc).toHaveBeenCalled();
    });
    const pole = screen.getByLabelText<HTMLInputElement>("Twój identyfikator");
    expect(pole).not.toBeDisabled();
    expect(pole).toHaveValue("");
  });

  it("szkoda: opcja Pokryta zamiast Akceptacja", () => {
    render(<DecisionForm wniosek={zbudujSzkode("POKRYTA", "POKRYTA")} onPoDecyzji={vi.fn()} />);
    expect(screen.getByRole("radio", { name: "Pokryta" })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Akceptacja" })).not.toBeInTheDocument();
  });

  it("szkoda Z10: zgoda z decyzja po regulach (SKIEROWANIE) bez komentarza, mimo innej oceny LLM", async () => {
    const user = userEvent.setup();
    render(<DecisionForm wniosek={zbudujSzkode("SKIEROWANIE", "POKRYTA")} onPoDecyzji={vi.fn()} />);

    await user.click(screen.getByRole("radio", { name: "Skierowanie" }));
    await user.type(screen.getByLabelText("Twój identyfikator"), "test.manual");
    expect(screen.getByText(/Komentarz \(opcjonalny\)/)).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Pokryta" }));
    expect(screen.getByText(/Komentarz \(wymagany/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /zatwierdź decyzję/i })).toBeDisabled();
  });
});
